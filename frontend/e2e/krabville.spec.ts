import { expect, test } from "@playwright/test";
import path from "node:path";

test("the live town is readable, interactive, and nonblank", async ({ page }, testInfo) => {
  if (testInfo.project.name.includes("reduced")) {
    await page.emulateMedia({ reducedMotion: "reduce" });
  }
  const consoleErrors: string[] = [];
  page.on("console", (message) => {
    if (message.type() === "error" && !message.location().url.endsWith("/favicon.ico")) consoleErrors.push(message.text());
  });
  page.on("pageerror", (error) => consoleErrors.push(error.message));

  await page.goto("/");
  await expect(page.locator("#live-state b")).toContainText(/running|paused|complete/i);
  await expect(page.locator(".resident-row")).toHaveCount(12);
  const canvas = page.locator("#world canvas");
  await expect(canvas).toBeVisible();
  await page.waitForTimeout(1_500);
  const world = page.locator("#world");
  await expect(world).toHaveAttribute("data-map-asset", "/assets/kvsim-town-v2.webp");
  await expect(world).toHaveAttribute("data-world-width", "3072");
  await expect(world).toHaveAttribute("data-world-height", "2048");
  await expect(world).toHaveAttribute("data-paths-in-bounds", "true");
  await expect(world).toHaveAttribute("data-coordinate-space", /map|projected-legacy/);
  const loadedAssets = await page.evaluate(() => performance.getEntriesByType("resource").map((entry) => entry.name));
  expect(loadedAssets.some((name) => name.endsWith("/assets/kvsim-town-v2.webp"))).toBe(true);
  expect(loadedAssets.some((name) => name.endsWith("/assets/life-stages-v2.png"))).toBe(true);
  expect(loadedAssets.some((name) => name.endsWith("/assets/interiors-v2.png"))).toBe(true);

  const initialZoom = Number(await world.getAttribute("data-camera-zoom"));
  await page.locator("#zoom-in").click();
  await expect.poll(async () => Number(await world.getAttribute("data-camera-zoom"))).toBeGreaterThan(initialZoom);
  await page.locator("#map-fit").click();

  const pixels = await canvas.evaluate((element: HTMLCanvasElement) => {
    const context = element.getContext("2d");
    if (!context) return { opaque: 0, varied: 0 };
    const data = context.getImageData(0, 0, element.width, element.height).data;
    let opaque = 0;
    let varied = 0;
    for (let index = 0; index < data.length; index += 64) {
      if (data[index + 3] > 0) opaque += 1;
      if (data[index] + data[index + 1] + data[index + 2] > 35) varied += 1;
    }
    return { opaque, varied };
  });
  expect(pixels.opaque).toBeGreaterThan(100);
  expect(pixels.varied).toBeGreaterThan(100);

  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true);
  const rosterToggle = page.locator("#roster-toggle");
  if (await rosterToggle.isVisible()) await rosterToggle.click();
  const firstResident = page.locator(".resident-row").first();
  await firstResident.hover();
  await expect(page.locator("#resident-peek")).toBeVisible();
  expect(await page.locator("#resident-peek .peek-need").count()).toBeGreaterThanOrEqual(5);
  await expect(page.locator("#resident-peek .peek-forecast")).toContainText("Pondering");
  await firstResident.click();
  await expect(page.locator("#dossier")).toBeVisible();
  await expect(page.locator("#dossier-name")).not.toHaveText("Loading...");
  await expect(page.locator("#dossier .decision-row")).toHaveCount(3);
  await expect(page.getByRole("button", { name: "Needs & wants" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Secrets & beliefs" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Finances" })).toBeVisible();
  await page.getByRole("button", { name: "Needs & wants" }).click();
  await expect(page.locator("#dossier-needs .section-label").first()).toContainText("high is healthy");
  const satisfaction = await page.locator("#dossier-needs .need-row").evaluateAll((rows) => rows.map((row) => Number((row as HTMLElement).dataset.satisfaction)));
  expect(satisfaction.every((value) => value >= 0 && value <= 100)).toBe(true);
  await page.getByRole("button", { name: "Relationships" }).click();
  await expect(page.locator("#relationship-canvas")).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.locator("#dossier")).toBeHidden();

  const storyToggle = page.locator("#story-toggle");
  if (await storyToggle.isVisible()) await storyToggle.click();
  await page.locator('[data-story-tab="property"]').click();
  await expect(page.locator(".place-card").first()).toBeVisible();
  await expect(page.locator(".place-card button").first()).toContainText(/focus/i);
  if (testInfo.project.name === "1024x600") await page.waitForTimeout(5_250);
  await page.locator(".place-card button").first().click();
  await expect(page.locator("#interior-view")).toBeVisible();
  await expect(world).toHaveAttribute("data-focused-location", /.+/);
  await page.locator("#interior-close").click();
  if (await storyToggle.isVisible()) await storyToggle.click();
  await page.locator('[data-story-tab="seasons"]').click();
  await expect(page.locator("[data-open-archive]")).toBeVisible();

  await page.locator("#archive-open").click();
  await expect(page.locator("#archive-view")).toBeVisible();
  await expect(page.locator("#archive-list button").first()).toBeVisible();
  await page.locator("#archive-close").click();

  const screenshotRoot = process.env.KRABVILLE_SCREENSHOT_DIR;
  if (screenshotRoot && !testInfo.project.name.includes("reduced")) {
    await page.screenshot({
      path: path.join(screenshotRoot, `krabville-${testInfo.project.name}.png`),
      animations: "disabled",
    });
  }
  expect(consoleErrors).toEqual([]);
});
