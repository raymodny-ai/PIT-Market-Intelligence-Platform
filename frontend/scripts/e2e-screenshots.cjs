/**
 * E2E screenshot harness for PIT Market Intelligence Platform.
 *
 * Uses puppeteer-core to drive the system chromium binary and waits
 * for actual network idle + DOM content before snapping — solving
 * the "react-query still loading" problem that bare --screenshot
 * hits because it just waits on virtual time.
 *
 * Usage: node frontend/scripts/e2e-screenshots.cjs [outdir]
 */
const path = require("path");
const fs = require("fs");
const puppeteer = require("puppeteer-core");

const OUTDIR = process.argv[2] || "/tmp/pit-mobile";
fs.mkdirSync(OUTDIR, { recursive: true });

// (label, url, viewport, waitForSelector, optional prep fn)
const PAGES = [
  {
    label: "1-dashboard-mobile",
    url: "http://127.0.0.1:8701/dashboard",
    viewport: { width: 375, height: 200, deviceScaleFactor: 2 },
    waitFor: "header, .sticky",
    fullPage: false,
  },
  {
    label: "2-dashboard-desktop",
    url: "http://127.0.0.1:8701/dashboard",
    viewport: { width: 1440, height: 200 },
    waitFor: "header, .sticky",
    fullPage: false,
  },
  {
    label: "3-panels-list",
    url: "http://127.0.0.1:8701/panels",
    viewport: { width: 1280, height: 900 },
    // Wait for at least one panel link or the empty state to render.
    waitFor: "a[href^='/panels/cli-'], a[href='/panels/new'], .text-ink-500",
    fullPage: false,
  },
  {
    label: "4-new-panel-form",
    url: "http://127.0.0.1:8701/panels/new",
    viewport: { width: 1280, height: 900 },
    // Wait for the universe chips to render (button[name=GLD] is one of them).
    waitFor: "button",
    fullPage: true,
  },
  {
    label: "5-new-panel-form-mobile",
    url: "http://127.0.0.1:8701/panels/new",
    viewport: { width: 375, height: 900, deviceScaleFactor: 2 },
    waitFor: "button",
    fullPage: true,
  },
  {
    label: "6-panel-detail",
    url: "http://127.0.0.1:8701/panels/cli-20240630T180500Z-SPY-QQQ-GLD-SLV",
    viewport: { width: 1280, height: 900 },
    waitFor: "body",
    fullPage: false,
  },
];

(async () => {
  const browser = await puppeteer.launch({
    executablePath: "/usr/bin/chromium",
    headless: "new",
    args: [
      "--no-sandbox",
      "--disable-setuid-sandbox",
      "--disable-dev-shm-usage",
      "--disable-gpu",
      "--hide-scrollbars",
    ],
  });

  for (const p of PAGES) {
    const page = await browser.newPage();
    await page.setViewport(p.viewport);
    const start = Date.now();
    try {
      await page.goto(p.url, {
        waitUntil: "networkidle2",
        timeout: 30000,
      });
      // Wait for the specific selector to confirm the page is hydrated.
      await page.waitForSelector(p.waitFor, { timeout: 15000 });
      // Give react-query an extra 500ms to finish painting.
      await new Promise((r) => setTimeout(r, 500));
      const out = path.join(OUTDIR, `${p.label}.png`);
      await page.screenshot({
        path: out,
        fullPage: !!p.fullPage,
      });
      const ms = Date.now() - start;
      const title = await page.title();
      console.log(`  ✓ ${p.label}  ${ms}ms  title="${title}"  →  ${out}`);
    } catch (e) {
      console.error(`  ✗ ${p.label}  ${e.message}`);
    } finally {
      await page.close();
    }
  }

  await browser.close();
})();