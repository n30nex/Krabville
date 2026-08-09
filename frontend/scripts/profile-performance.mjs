import fs from "node:fs/promises";
import { performance } from "node:perf_hooks";
import { chromium } from "@playwright/test";

function argument(name, fallback) {
  const index = process.argv.indexOf(name);
  return index < 0 ? fallback : process.argv[index + 1];
}

function summary(values) {
  const ordered = [...values].sort((left, right) => left - right);
  if (!ordered.length) return null;
  const middle = Math.floor(ordered.length / 2);
  const median = ordered.length % 2
    ? ordered[middle]
    : (ordered[middle - 1] + ordered[middle]) / 2;
  const p95 = ordered[Math.max(0, Math.ceil(ordered.length * 0.95) - 1)];
  return {
    min: Number(ordered[0].toFixed(3)),
    median: Number(median.toFixed(3)),
    p95: Number(p95.toFixed(3)),
    max: Number(ordered.at(-1).toFixed(3)),
  };
}

function selectedMetrics(result) {
  const available = Object.fromEntries(result.metrics.map((metric) => [metric.name, metric.value]));
  return Object.fromEntries(
    [
      "JSHeapUsedSize",
      "JSHeapTotalSize",
      "Nodes",
      "Documents",
      "Frames",
      "LayoutCount",
      "RecalcStyleCount",
      "LayoutDuration",
      "RecalcStyleDuration",
      "ScriptDuration",
      "TaskDuration",
    ]
      .filter((name) => name in available)
      .map((name) => [name, available[name]]),
  );
}

async function memorySnapshot(cdp) {
  const [metrics, dom] = await Promise.all([
    cdp.send("Performance.getMetrics"),
    cdp.send("Memory.getDOMCounters"),
  ]);
  return {
    ...selectedMetrics(metrics),
    domDocuments: dom.documents,
    domNodes: dom.nodes,
    domEventListeners: dom.jsEventListeners,
  };
}

const baseURL = argument("--url", "http://127.0.0.1:18889");
const durationSeconds = Number(argument("--duration-seconds", "600"));
const output = argument("--output", "browser-baseline.json");
if (!Number.isFinite(durationSeconds) || durationSeconds < 0) throw new Error("invalid duration");

const browser = await chromium.launch({
  headless: true,
  args: ["--enable-precise-memory-info"],
});

try {
  const context = await browser.newContext({
    viewport: { width: 1366, height: 768 },
    serviceWorkers: "block",
  });
  const page = await context.newPage();
  const cdp = await context.newCDPSession(page);
  await Promise.all([cdp.send("Performance.enable"), cdp.send("Network.enable")]);

  const started = performance.now();
  const stateRequests = [];
  const streamRequests = [];
  const failedRequests = [];
  const consoleErrors = [];
  const pageErrors = [];
  const streamEvents = [];
  page.on("request", (request) => {
    const path = new URL(request.url()).pathname;
    const atMs = performance.now() - started;
    if (path === "/api/v3/state") stateRequests.push(atMs);
    if (path === "/api/v3/events/stream") streamRequests.push(atMs);
  });
  page.on("requestfailed", (request) => {
    failedRequests.push({
      path: new URL(request.url()).pathname,
      error: request.failure()?.errorText ?? "unknown",
    });
  });
  page.on("console", (message) => {
    if (message.type() === "error" && !message.location().url.endsWith("/favicon.ico")) {
      consoleErrors.push(message.text());
    }
  });
  page.on("pageerror", (error) => pageErrors.push(error.message));
  cdp.on("Network.eventSourceMessageReceived", (event) => {
    streamEvents.push({ name: event.eventName || "message", atMs: performance.now() - started });
  });

  await page.goto(baseURL, { waitUntil: "domcontentloaded", timeout: 60_000 });
  await page.locator("#live-state b").waitFor({ state: "visible", timeout: 60_000 });
  const shellReadyMs = performance.now() - started;
  const canvas = page.locator("#world canvas");
  await canvas.waitFor({ state: "visible", timeout: 60_000 });
  await page.waitForFunction(
    () => document.querySelector("#world")?.getAttribute("data-paths-in-bounds") === "true",
    undefined,
    { timeout: 60_000 },
  );
  const mapInteractiveMs = performance.now() - started;
  await page.waitForLoadState("load");
  await page.waitForTimeout(1_000);

  const initialResources = await page.evaluate(() =>
    performance.getEntriesByType("resource").map((entry) => {
      const resource = /** @type {PerformanceResourceTiming} */ (entry);
      return {
        path: new URL(resource.name).pathname,
        initiatorType: resource.initiatorType,
        transferSize: resource.transferSize,
        encodedBodySize: resource.encodedBodySize,
        decodedBodySize: resource.decodedBodySize,
        durationMs: Number(resource.duration.toFixed(3)),
      };
    }),
  );
  const navigation = await page.evaluate(() => {
    const entry = /** @type {PerformanceNavigationTiming | undefined} */ (
      performance.getEntriesByType("navigation")[0]
    );
    const paints = Object.fromEntries(
      performance
        .getEntriesByType("paint")
        .map((paint) => [paint.name, Number(paint.startTime.toFixed(3))]),
    );
    return entry
      ? {
          responseEndMs: Number(entry.responseEnd.toFixed(3)),
          domContentLoadedMs: Number(entry.domContentLoadedEventEnd.toFixed(3)),
          loadEventMs: Number(entry.loadEventEnd.toFixed(3)),
          transferSize: entry.transferSize,
          encodedBodySize: entry.encodedBodySize,
          decodedBodySize: entry.decodedBodySize,
          paints,
        }
      : { paints };
  });
  const canvasEvidence = await canvas.evaluate((element) => {
    const target = /** @type {HTMLCanvasElement} */ (element);
    const renderer = target.getContext("webgl2")
      ? "webgl2"
      : target.getContext("webgl")
        ? "webgl"
        : target.getContext("2d")
          ? "2d"
          : "unknown";
    return {
      width: target.width,
      height: target.height,
      clientWidth: target.clientWidth,
      clientHeight: target.clientHeight,
      renderer,
    };
  });
  const screenshotBytes = (await page.locator("#world").screenshot({ animations: "disabled" })).length;

  const stateResponse = await fetch(`${baseURL}/api/v3/state`);
  if (!stateResponse.ok) throw new Error(`state parse sample failed: ${stateResponse.status}`);
  const stateText = await stateResponse.text();
  const parse = await page.evaluate((source) => {
    for (let index = 0; index < 5; index += 1) JSON.parse(source);
    const timings = [];
    let checksum = 0;
    for (let index = 0; index < 40; index += 1) {
      const before = performance.now();
      const value = JSON.parse(source);
      timings.push(performance.now() - before);
      checksum += Array.isArray(value.residents) ? value.residents.length : 0;
    }
    return { timings, checksum };
  }, stateText);

  const initialMemory = await memorySnapshot(cdp);
  const soakStartedAtMs = performance.now() - started;
  await page.waitForTimeout(durationSeconds * 1_000);
  const finalMemory = await memorySnapshot(cdp);
  const observationMs = performance.now() - started;
  const intervals = stateRequests.slice(1).map((value, index) => value - stateRequests[index]);
  const soakStateRequests = stateRequests.filter((value) => value >= soakStartedAtMs).length;
  const memoryDelta = Object.fromEntries(
    Object.keys(finalMemory)
      .filter((key) => typeof initialMemory[key] === "number")
      .map((key) => [key, finalMemory[key] - initialMemory[key]]),
  );

  await fs.writeFile(
    output,
    `${JSON.stringify(
      {
        browser: `Chromium ${browser.version()}`,
        viewport: { width: 1366, height: 768 },
        durationSeconds,
        timing: {
          shellReadyMs: Number(shellReadyMs.toFixed(3)),
          mapInteractiveMs: Number(mapInteractiveMs.toFixed(3)),
          navigation,
          screenshotBytes,
          canvas: canvasEvidence,
        },
        jsonParse: {
          sourceBytes: Buffer.byteLength(stateText),
          samples: parse.timings.length,
          milliseconds: summary(parse.timings),
          checksum: parse.checksum,
        },
        refresh: {
          stateRequests: stateRequests.length,
          soakStateRequests,
          observationSeconds: Number((observationMs / 1_000).toFixed(3)),
          observedIntervals: intervals.length,
          intervalMs: summary(intervals),
          requestsPerMinute:
            observationMs > 0
              ? Number((Math.max(0, stateRequests.length - 1) / (observationMs / 60_000)).toFixed(3))
              : null,
        },
        sse: {
          connections: streamRequests.length,
          reconnects: Math.max(0, streamRequests.length - 1),
          messages: streamEvents.length,
          eventNames: Object.fromEntries(
            [...new Set(streamEvents.map((event) => event.name))].map((name) => [
              name,
              streamEvents.filter((event) => event.name === name).length,
            ]),
          ),
        },
        memory: { initial: initialMemory, final: finalMemory, delta: memoryDelta },
        initialResources,
        errors: { console: consoleErrors, page: pageErrors, requests: failedRequests },
      },
      null,
      2,
    )}\n`,
    "utf8",
  );
} finally {
  await browser.close();
}
