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
  expect(loadedAssets.some((name) => name.endsWith("/assets/interiors-v3.png"))).toBe(true);
  expect(loadedAssets.some((name) => name.endsWith("/assets/weather-seasons-v1.png"))).toBe(true);

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
  const dependent = page.locator('.resident-row[data-life-stage="baby"], .resident-row[data-life-stage="child"]').first();
  if (!(await rosterToggle.isVisible())) {
    await dependent.hover();
    await expect(page.locator("#resident-peek")).toBeVisible();
    expect(await page.locator("#resident-peek .peek-need").count()).toBeGreaterThanOrEqual(5);
    await expect(page.locator("#resident-peek .peek-forecast")).toContainText("Pondering");
    await expect(page.locator("#resident-peek .peek-care")).toContainText("Caregiver");
  }
  await dependent.click();
  await expect(page.locator("#dossier")).toBeVisible();
  await expect(page.locator("#dossier-name")).not.toHaveText("Loading...");
  await expect(page.locator("#dossier .decision-row")).toHaveCount(3);
  const dossier = page.locator("#dossier");
  await expect(dossier.getByRole("button", { name: "Needs", exact: true })).toBeVisible();
  await expect(dossier.getByRole("button", { name: "Secrets", exact: true })).toBeVisible();
  await expect(dossier.getByRole("button", { name: "Money", exact: true })).toBeVisible();
  await dossier.getByRole("button", { name: "Needs", exact: true }).click();
  await expect(page.locator("#dossier-needs .section-label").first()).toContainText("high is healthy");
  const satisfaction = await page.locator("#dossier-needs .need-row").evaluateAll((rows) => rows.map((row) => Number((row as HTMLElement).dataset.satisfaction)));
  expect(satisfaction.every((value) => value >= 0 && value <= 100)).toBe(true);
  await dossier.getByRole("button", { name: "Health", exact: true }).click();
  await expect(page.locator("#dossier-health")).toContainText(/caregiver/i);
  await expect(page.locator("#dossier-health .fact-grid article").filter({ hasText: "Caregiver" }).locator("b")).not.toHaveText("Independent");
  await dossier.getByRole("button", { name: "Relationships", exact: true }).click();
  await expect(page.locator("#relationship-canvas")).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.locator("#dossier")).toBeHidden();

  await page.locator('[data-explore="bank"]').click();
  await expect(page.locator("#explore-view")).toBeVisible();
  await expect(page).toHaveURL(/#\/explore\/bank$/);
  await expect(page.locator(".bank-ledger button[data-resident]").first()).toBeVisible();
  await page.locator("#explore-close").click();
  await expect(page).not.toHaveURL(/#\/explore\//);

  await expect(page.locator(".story-rail")).toHaveCount(0);
  await page.locator('[data-explore="places"]').click();
  await expect(page.locator(".property-directory-card .building-thumb").first()).toBeVisible();
  await expect(page.locator(".property-directory-card .card-totals").first()).toContainText(/items/i);
  const publicState = await (await page.request.get("/api/v3/state")).json();
  const occupiedProperty = publicState.properties.find((property: { slug?: string; inside?: unknown[]; inventoryItems?: number }) => property.slug && property.inside?.length && property.inventoryItems);
  expect(occupiedProperty).toBeTruthy();
  await page.goto(`/#/property/${encodeURIComponent(occupiedProperty.slug)}`);
  await expect(page.locator("#explore-view")).toBeVisible();
  await expect(page.locator(".property-interior .interior-actor")).toHaveCount(occupiedProperty.inside.length);
  await expect(page.locator(".property-interior .interior-actor-sprite").first()).toBeVisible();
  expect(await page.locator(".property-interior .interior-actor-sprite").first().evaluate((element) => getComputedStyle(element).backgroundImage)).toMatch(/residents|life-stages/);
  const firstItemIcon = page.locator("#explore-content .inventory-grid .item-icon").first();
  await page.locator("#explore-content").evaluate((element) => element.scrollTo({ top: element.scrollHeight }));
  await expect(firstItemIcon).toBeVisible();
  expect(await firstItemIcon.evaluate((element) => getComputedStyle(element).backgroundImage)).toContain("inventory-items-v1.png");
  await page.locator("#explore-close").click();

  await page.locator('[data-explore="analytics"]').click();
  await expect(page.locator(".analytics-hero")).toContainText("Analytics Lab");
  await expect(page.locator(".analytics-grid .bar-chart").first()).toBeVisible();
  await expect(page.locator(".analytics-grid .line-chart").first()).toBeVisible();
  await page.locator("#explore-close").click();

  await expect(page.locator("#map-vote-trigger")).toBeVisible();
  await expect(world).toHaveAttribute("data-season", /spring|summer|fall|winter/);
  await expect(world).toHaveAttribute("data-weather", /.+/);

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

test("directory deep links open after the first state load", async ({ page }) => {
  await page.goto("/#/explore/bank");
  await expect(page.locator("#live-state b")).toContainText(/running|paused|complete/i);
  await expect(page.locator("#explore-view")).toBeVisible();
  await expect(page.locator("#explore-title")).toHaveText("Bank & economy");
  await expect(page.locator('[data-explore="bank"]')).toHaveClass(/active/);
});

test("every directory route, home focus, clothing, and semantic inventory controls work", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "1366x768", "full route audit runs once at desktop size");
  const consoleErrors: string[] = [];
  page.on("console", (message) => {
    if (message.type() === "error" && !message.location().url.endsWith("/favicon.ico")) consoleErrors.push(message.text());
  });
  page.on("pageerror", (error) => consoleErrors.push(error.message));

  const routes: Array<[string, string]> = [
    ["residents", "Residents"], ["households", "Households"], ["family", "Families"],
    ["calls", "Phone network"], ["places", "Places"], ["homes", "Homes"],
    ["buildings", "Work & civic places"], ["shops", "Shops & businesses"],
    ["bank", "Bank & economy"], ["analytics", "Krabville Analytics Lab"],
    ["story", "Living story"], ["events", "Event ledger"], ["seasons", "Seasons"],
  ];
  for (const [route, title] of routes) {
    await page.goto(`/#/explore/${route}`);
    await expect(page.locator("#explore-view")).toBeVisible();
    await expect(page.locator("#explore-title")).toHaveText(title);
    await expect(page.locator("#explore-content")).not.toBeEmpty();
  }

  await page.goto("/#/explore/households");
  const focusHome = page.getByRole("button", { name: "Focus home" }).first();
  await expect(focusHome).toBeVisible();
  await focusHome.click();
  await expect(page).toHaveURL(/#\/property\//);
  await expect(page.locator(".property-interior")).toBeVisible();

  const publicState = await (await page.request.get("/api/v3/state")).json();
  const generalStore = publicState.properties.find((property: { name: string; slug?: string }) => property.name === "Lagoon General Store");
  expect(generalStore?.slug).toBeTruthy();
  const resident = publicState.residents[0];
  const detail = await (await page.request.get(`/api/v3/residents/${encodeURIComponent(resident.slug)}`)).json();
  const storeDetail = await (await page.request.get(`/api/v3/properties/${encodeURIComponent(generalStore.slug)}`)).json();
  expect(detail.clothing.length).toBeGreaterThan(0);
  const expectedFrames: Record<string, number> = {
    "baby-bottle": 22, "stuffed-toy": 125, "batteries": 110,
    "toilet-paper": 76, "first-aid-kit": 87,
  };
  for (const [assetKey, frame] of Object.entries(expectedFrames)) {
    const item = storeDetail.inventory.find((candidate: { assetKey: string }) => candidate.assetKey === assetKey);
    expect(item, `${assetKey} should be stocked`).toBeTruthy();
    expect(item.assetIndex).toBe(frame);
  }

  await page.goto(`/#/`);
  await page.locator(`.resident-row[data-resident="${resident.slug}"]`).click();
  await page.getByRole("button", { name: "Home & goods", exact: true }).click();
  await expect(page.locator("#dossier-property")).toContainText("Clothing and outfit");
  await expect(page.locator("#dossier-property .item-icon").first()).toBeVisible();
  await page.keyboard.press("Escape");

  await page.goto(`/#/property/${encodeURIComponent(generalStore.slug)}`);
  const search = page.locator("[data-inventory-search]");
  await expect(search).toBeVisible();
  await search.fill("baby bottle");
  await expect(page.locator(".inventory-grid article:visible")).toHaveCount(1);
  await expect(page.locator(".inventory-grid article:visible")).toContainText("Baby bottle");
  await expect(page.locator("[data-inventory-visible]")).toHaveText("1 shown");

  expect(consoleErrors).toEqual([]);
});
