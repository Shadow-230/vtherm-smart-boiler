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
  "/translations/en.json": join(root, "custom_components/vtherm_smart_boiler/translations/en.json"),
  "/translations/pl.json": join(root, "custom_components/vtherm_smart_boiler/translations/pl.json"),
};
const VIEWS = [
  { name: "desktop-pl", width: 1280, height: 720, query: "", scale: 2, settings: true, preview: true },
  { name: "desktop-pl-day", width: 1280, height: 720, query: "", scale: 1, replay: 120 },
  { name: "desktop-pl-burner", width: 1280, height: 720, query: "#burner", scale: 1 },
  { name: "phone-en-burner-dark", width: 390, height: 844, query: "?lang=en&dark=1#burner", scale: 1 },
  { name: "desktop-pl-use", width: 1280, height: 720, query: "#use", scale: 1 },
  { name: "phone-pl-use-dark", width: 390, height: 844, query: "?dark=1#use", scale: 1 },
  { name: "desktop-pl-cards", width: 1280, height: 900, query: "?cards=1", scale: 1, cards: true },
  { name: "phone-en-cards-dark", width: 390, height: 844, query: "?lang=en&dark=1&cards=1", scale: 1, cards: true },
  { name: "desktop-pl-analyses", width: 1280, height: 900, query: "#analyses", scale: 1 },
  { name: "phone-en-analyses-dark", width: 390, height: 844, query: "?lang=en&dark=1#analyses", scale: 1 },
  { name: "desktop-en-analyses-user", width: 1280, height: 900, query: "?lang=en&user=1#analyses", scale: 1 },
  { name: "desktop-pl-journal", width: 1280, height: 900, query: "#journal", scale: 1, zoom: true },
  { name: "desktop-en-journal-week", width: 1280, height: 900, query: "?lang=en#journal", scale: 1, week: true },
  { name: "phone-pl-journal-dark", width: 390, height: 844, query: "?dark=1#journal", scale: 1 },
  { name: "desktop-pl-status", width: 1280, height: 720, query: "#status", scale: 1, reset: true },
  { name: "phone-en-status-dark", width: 390, height: 844, query: "?lang=en&dark=1#status", scale: 1 },
  { name: "desktop-en-status-user", width: 1280, height: 720, query: "?lang=en&user=1#status", scale: 1 },
  { name: "desktop-pl-between-burns", width: 1280, height: 600, query: "?flame=0", scale: 1 },
  { name: "phone-pl-dark", width: 390, height: 844, query: "?dark=1", scale: 1 },
  { name: "desktop-en-user", width: 1280, height: 600, query: "?lang=en&user=1", scale: 1 },
  { name: "desktop-pl-hot-water", width: 1280, height: 600, query: "?dhw=1", scale: 1 },
  { name: "desktop-en-combi-dark", width: 1280, height: 600, query: "?lang=en&combi=1&dark=1", scale: 1 },
  // F21: the schematic card in one narrow dashboard column, on a wide screen.
  { name: "column-340-en-combi", width: 900, height: 900, query: "?lang=en&combi=1&cards=1&column=340", scale: 2, cards: true, column: true },
  { name: "column-340-pl-pause", width: 900, height: 900, query: "?flame=0&cards=1&column=340", scale: 2, cards: true, column: true },
  { name: "column-420-pl-combi-hot-water", width: 900, height: 900, query: "?combi=1&dhw=1&cards=1&column=420", scale: 2, cards: true, column: true },
  { name: "column-420-en", width: 900, height: 900, query: "?lang=en&cards=1&column=420", scale: 2, cards: true, column: true },
];

// The boiler's body and the tank in the drawing's units (schematic.ts, `drawSchematic`; the view box
// starts at y 70 and is 1000 wide).
const BOILER = { x1: 60, y1: 110, x2: 210, y2: 360 };
const TANK = { x1: 255, y1: 195, x2: 345, y2: 415 };

// Every schematic on the page: no two labels overlap, the boiler's state stays inside its body and
// clear of the flame, the words beside the drawing stay off the boiler and the tank, and none leaves
// the card. A word is measured by its text, a value by its badge; the badges sit on the pipes, so
// they may touch the boiler's edge.
function schematicProblems({ BOILER, TANK }) {
  const all = (root, tag, found = []) => {
    for (const element of root.querySelectorAll("*")) {
      if (element.localName === tag) found.push(element);
      if (element.shadowRoot) all(element.shadowRoot, tag, found);
    }
    return found;
  };
  const meets = (a, b) => a.left < b.right - 0.5 && b.left < a.right - 0.5 && a.top < b.bottom - 0.5 && b.top < a.bottom - 0.5;
  const problems = [];
  for (const schematic of all(document, "vtherm-smart-boiler-schematic")) {
    const root = schematic.shadowRoot;
    const drawing = root.querySelector(".drawing");
    if (!drawing) continue;
    const d = drawing.getBoundingClientRect();
    const s = d.width / 1000;
    const box = (b) => ({ left: d.left + b.x1 * s, right: d.left + b.x2 * s, top: d.top + (b.y1 - 70) * s, bottom: d.top + (b.y2 - 70) * s });
    const boiler = box(BOILER);
    const obstacles = [boiler];
    if ([...root.querySelectorAll("path.coil")].some((path) => path.getAttribute("d"))) obstacles.push(box(TANK));
    const flame = root.querySelector("svg.flame").getBoundingClientRect();
    const host = schematic.getBoundingClientRect();
    const extent = (span) => {
      if (!span.classList.contains("text") && !span.classList.contains("inside")) return span.getBoundingClientRect();
      const range = document.createRange();
      range.selectNodeContents(span);
      return range.getBoundingClientRect();
    };
    const labels = [...drawing.querySelectorAll(":scope > span")]
      .filter((span) => getComputedStyle(span).display !== "none")
      .map((span) => ({
        text: span.textContent.trim(),
        inside: span.classList.contains("inside"),
        word: span.classList.contains("text"),
        rect: extent(span),
      }));
    labels.forEach((a, i) => {
      for (const b of labels.slice(i + 1)) if (meets(a.rect, b.rect)) problems.push(`"${a.text}" overlaps "${b.text}"`);
      if (a.rect.left < host.left || a.rect.right > host.right) problems.push(`"${a.text}" leaves the card`);
      if (a.inside) {
        const r = a.rect;
        if (r.left < boiler.left || r.right > boiler.right || r.top < boiler.top || r.bottom > boiler.bottom)
          problems.push(`"${a.text}" sticks out of the boiler`);
        if (meets(r, flame)) problems.push(`"${a.text}" overlaps the flame`);
      } else if (a.word && obstacles.some((o) => meets(a.rect, o))) {
        problems.push(`"${a.text}" overlaps the boiler or the tank`);
      }
    });
  }
  return problems;
}

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
    const contentType = path.endsWith(".js")
      ? "text/javascript"
      : path.endsWith(".json")
        ? "application/json"
        : "text/html";
    return route.fulfill({ path: file, contentType });
  });
  await page.goto(`http://preview.local/index.html${view.query}`);
  await page
    .locator(
      view.query.includes("#burner")
        ? "vtherm-smart-boiler-burner .tiles"
        : view.query.includes("#use")
          ? "vtherm-smart-boiler-use .tiles"
          : view.query.includes("#status")
            ? "vtherm-smart-boiler-status .verdict"
            : view.query.includes("#journal")
              ? "vtherm-smart-boiler-journal .tracks"
              : view.query.includes("#analyses")
                ? "vtherm-smart-boiler-analyses .calendar"
                : view.cards
                  ? "vtherm-smart-boiler-day-card vtherm-smart-boiler-timeline"
                  : "vtherm-smart-boiler-overview .hero",
    )
    .waitFor();
  await page.waitForTimeout(300);
  await page.screenshot({ path: join(out, `${view.name}.png`), fullPage: true });
  if (view.column) {
    await page.locator("vtherm-smart-boiler-schematic-card").screenshot({ path: join(out, `${view.name}-schematic.png`) });
  }
  for (const problem of await page.evaluate(schematicProblems, { BOILER, TANK })) errors.push(`schematic: ${problem}`);
  const pageWidth = await page.evaluate(() => document.documentElement.scrollWidth);
  if (pageWidth > view.width) errors.push(`the page is ${pageWidth} px wide on a ${view.width} px screen`);
  if (view.settings) {
    // I11: control is switched in the plugin's settings; the page leads an administrator there.
    await page.locator("vtherm-smart-boiler-overview button.text").click();
    const path = await page.evaluate(() => window.location.pathname);
    console.log(`${view.name}: "Change in settings" leads to`, path);
  }
  if (view.cards) {
    const listed = await page.evaluate(() => window.customCards.map((card) => `${card.type}: ${card.name}`));
    console.log(`${view.name}: in the card picker`, JSON.stringify(listed));
  }
  if (view.week) {
    await page.locator("vtherm-smart-boiler-journal button.window").nth(2).click();
    await page.waitForTimeout(200);
    await page.screenshot({ path: join(out, `${view.name}.png`), fullPage: true });
    await page.locator("vtherm-smart-boiler-journal section.card").first().screenshot({ path: join(out, `${view.name}-lanes.png`) });
  }
  if (view.zoom) {
    const tracks = page.locator("vtherm-smart-boiler-journal .tracks");
    const box = await tracks.boundingBox();
    await page.mouse.move(box.x + box.width * 0.3, box.y + 20);
    await page.mouse.down();
    await page.mouse.move(box.x + box.width * 0.6, box.y + 40, { steps: 6 });
    await page.mouse.up();
    await page.waitForTimeout(200);
    await page.locator("vtherm-smart-boiler-journal section.card").first().screenshot({ path: join(out, `${view.name}-zoom.png`) });
  }
  if (view.reset) {
    await page.locator("vtherm-smart-boiler-status button.outline").first().click();
    await page.locator("vtherm-smart-boiler-status dialog[open]").waitFor();
    await page.screenshot({ path: join(out, `${view.name}-reset.png`) });
    await page.locator("vtherm-smart-boiler-status dialog button.primary").click();
    console.log(`${view.name}: confirmed, the button was pressed with`, JSON.stringify(await page.evaluate(() => window.lastCall)));
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
    // The mouse reaches only what is on the screen: a taller part above can push the point below.
    await handle.scrollIntoViewIfNeeded();
    const box = await handle.boundingBox();
    await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
    await page.mouse.down();
    await page.mouse.move(box.x + box.width / 2 + 30, box.y + box.height / 2 - 40, { steps: 5 });
    await page.mouse.up();
    await page.waitForTimeout(200);
    await page.locator("vtherm-smart-boiler-curve").screenshot({ path: join(out, `${view.name}-curve-preview.png`) });
    await page.locator("vtherm-smart-boiler-curve button.primary").first().click();
    await page.locator("vtherm-smart-boiler-curve dialog[open]").waitFor();
    await page.screenshot({ path: join(out, `${view.name}-curve-save.png`) });
    await page.locator("vtherm-smart-boiler-curve dialog button.primary").click();
    await page.waitForTimeout(200);
    console.log(`${view.name}: the curve was saved with`, JSON.stringify(await page.evaluate(() => window.lastSave)));
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
