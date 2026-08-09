import { chromium } from "@playwright/test";
import { mkdir } from "node:fs/promises";
import path from "node:path";

const baseURL = process.env.KRABVILLE_E2E_URL ?? "http://127.0.0.1:18890";
const output = process.env.KRABVILLE_SCREENSHOT_DIR ?? path.resolve("..", "docs", "screenshots");
await mkdir(output, { recursive: true });

const browser = await chromium.launch({ headless: true });
const page = await browser.newPage({ viewport: { width: 1366, height: 768 }, deviceScaleFactor: 1 });

async function ready(target = page) {
  await target.goto(baseURL);
  await target.locator("#live-state b").waitFor({ state: "attached" });
  await target.locator("#world canvas").waitFor();
  await target.waitForTimeout(1_200);
}

async function capture(name, target = page) {
  await target.screenshot({ path: path.join(output, name), animations: "disabled" });
}

try {
  await ready();
  await capture("v2-map-desktop.png");

  await page.locator('[data-explore="places"]').click();
  await page.locator(".property-directory-card").first().waitFor();
  await capture("v2-places.png");

  const publicState = await (await page.request.get(`${baseURL}/api/v3/state`)).json();
  const occupied = publicState.properties.find((property) => property.slug && property.inside?.length && property.inventoryItems);
  if (!occupied) throw new Error("No occupied stocked property is available for the README capture");
  await page.goto(`${baseURL}/#/property/${encodeURIComponent(occupied.slug)}`);
  await page.locator(".property-interior .interior-actor").first().waitFor();
  await capture("v2-live-interior.png");
  await page.locator("#explore-content .inventory-summary").scrollIntoViewIfNeeded();
  await page.locator("#explore-content .inventory-grid .item-icon").first().waitFor();
  await capture("v2-rpg-inventory.png");

  await page.goto(`${baseURL}/#/explore/bank`);
  await page.locator(".bank-analysis").waitFor();
  await capture("v2-economy.png");

  await page.goto(`${baseURL}/#/explore/analytics`);
  await page.locator(".analytics-grid").waitFor();
  await capture("v2-analytics-lab.png");

  const mobile = await browser.newPage({ viewport: { width: 375, height: 812 }, deviceScaleFactor: 1, hasTouch: true, isMobile: true });
  await ready(mobile);
  await capture("v2-mobile.png", mobile);
  await mobile.close();
} finally {
  await browser.close();
}
