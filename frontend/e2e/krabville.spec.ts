import { expect, test } from "@playwright/test";
import path from "node:path";

test("the live town is readable, interactive, and nonblank", async ({ page }, testInfo) => {
  if (testInfo.project.name.includes("reduced")) {
    await page.emulateMedia({ reducedMotion: "reduce" });
  }
  const consoleErrors: string[] = [];
  page.on("console", (message) => {
    if (message.type() === "error") consoleErrors.push(message.text());
  });
  page.on("pageerror", (error) => consoleErrors.push(error.message));

  await page.goto("/");
  await expect(page.locator("#live-state b")).toContainText(/running|paused|complete/i);
  await expect(page.locator(".resident-row")).toHaveCount(12);
  const canvas = page.locator("#world canvas");
  await expect(canvas).toBeVisible();
  await page.waitForTimeout(1_500);

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
  await page.locator(".resident-row").first().click();
  await expect(page.locator("#dossier")).toBeVisible();
  await expect(page.locator("#dossier-name")).not.toHaveText("Loading...");
  await page.getByRole("button", { name: "Relationships" }).click();
  await expect(page.locator("#relationship-canvas")).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.locator("#dossier")).toBeHidden();

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
