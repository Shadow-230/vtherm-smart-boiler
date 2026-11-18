// Screenshots of the Boiler page on sample data (frontend/preview/index.html), in the Chromium
// scripts/bootstrap_browser.sh puts into .tools/: `npm run screenshots` after `npm run build`
// writes .tmp/screenshots/*.png and fails on any error in the page. The page and the built module
// are handed to the browser from disk; nothing is served on the network.
import { existsSync, mkdirSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright";

const here = dirname(fileURLToPath(import.meta.url));
const root = resolve(here, "../..");
const out = join(root, ".tmp/screenshots");
const libs = join(root, ".tools/chromium-libs/usr/lib/x86_64-linux-gnu");
const FILES = {
  "/index.html": join(here, "../preview/index.html"),
  "/vtherm-smart-boiler-panel.js": join(
    root,
    "custom_components/vtherm_smart_boiler/frontend/vtherm-smart-boiler-panel.js",
  ),
};
const VIEWS = [
  { name: "desktop-pl", width: 1280, height: 720, query: "", scale: 2, dialog: true, preview: true },
  { name: "desktop-pl-day", width: 1280, height: 720, query: "", scale: 1, replay: 120 },
  { name: "phone-pl-dark", width: 390, height: 844, query: "?dark=1", scale: 1 },
  { name: "desktop-en-user", width: 1280, height: 600, query: "?lang=en&user=1", scale: 1 },
  { name: "desktop-pl-hot-water", width: 1280, height: 600, query: "?dhw=1", scale: 1 },
  { name: "desktop-en-combi-dark", width: 1280, height: 600, query: "?lang=en&combi=1&dark=1", scale: 1 },
];

mkdirSync(out, { recursive: true });
const env = existsSync(libs)
  ? { ...process.env, LD_LIBRARY_PATH: [libs, process.env.LD_LIBRARY_PATH].filter(Boolean).join(":") }
  : process.env;
const browser = await chromium.launch({ env });
let failed = false;
for (const view of VIEWS) {
  const page = await browser.newPage({
    viewport: { width: view.width, height: view.height },
    deviceScaleFactor: view.scale,
  });
  const errors = [];
  page.on("pageerror", (error) => errors.push(error.message));
  page.on("console", (message) => message.type() === "error" && errors.push(message.text()));
  await page.route("http://preview.local/**", (route) => {
    const path = new URL(route.request().url()).pathname;
    const file = FILES[path];
    if (!file) return route.fulfill({ status: 404 });
    const contentType = path.endsWith(".js") ? "text/javascript" : "text/html";
    return route.fulfill({ path: file, contentType });
  });
  await page.goto(`http://preview.local/index.html${view.query}`);
  await page.locator("vtherm-smart-boiler-overview .hero").waitFor();
  await page.screenshot({ path: join(out, `${view.name}.png`), fullPage: true });
  if (view.dialog) {
    await page.locator("vtherm-smart-boiler-overview button.switch").click();
    await page.locator("vtherm-smart-boiler-overview dialog[open]").waitFor();
    await page.screenshot({ path: join(out, `${view.name}-dialog.png`) });
    await page.locator("vtherm-smart-boiler-overview dialog button.primary").click();
    const call = await page.evaluate(() => window.lastCall);
    console.log(`${view.name}: confirmed, the switch was called with`, JSON.stringify(call));
  }
  if (view.replay) {
    await page.locator("vtherm-smart-boiler-timeline input.scrub").fill(String(view.replay));
    await page.waitForTimeout(200);
    await page.screenshot({ path: join(out, `${view.name}-replay.png`), fullPage: true });
  }
  if (view.preview) {
    await page.locator("vtherm-smart-boiler-curve button.outline").click();
    await page.locator("vtherm-smart-boiler-curve button.handle").waitFor();
    const handle = page.locator("vtherm-smart-boiler-curve button.handle");
    const box = await handle.boundingBox();
    await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
    await page.mouse.down();
    await page.mouse.move(box.x + box.width / 2 + 30, box.y + box.height / 2 - 40, { steps: 5 });
    await page.mouse.up();
    await page.waitForTimeout(200);
    await page.locator("vtherm-smart-boiler-curve").screenshot({ path: join(out, `${view.name}-curve-preview.png`) });
  }
  if (errors.length) {
    failed = true;
    console.error(`${view.name}: errors in the page`, errors);
  } else {
    console.log(`${view.name}: no errors`);
  }
  await page.close();
}
await browser.close();
process.exit(failed ? 1 : 0);
