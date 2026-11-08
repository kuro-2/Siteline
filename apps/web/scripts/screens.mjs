// Design self-review (docs/06 §9): screenshots at 390px and 1280px, light and dark.
// Usage: node scripts/screens.mjs [baseUrl] [outDir] [path ...]
import { chromium } from "@playwright/test";
import { mkdirSync } from "node:fs";

const base = process.argv[2] || "http://localhost:3000";
const out = process.argv[3] || "screens";
const paths = process.argv.slice(4).length ? process.argv.slice(4) : ["/", "/explore/pilot"];
mkdirSync(out, { recursive: true });
const browser = await chromium.launch();
for (const scheme of ["light", "dark"]) {
  for (const width of [390, 1280]) {
    const ctx = await browser.newContext({
      viewport: { width, height: width < 600 ? 844 : 800 },
      colorScheme: scheme,
      deviceScaleFactor: 1,
    });
    const page = await ctx.newPage();
    for (const p of paths) {
      await page.goto(base + p, { waitUntil: "networkidle" }).catch(() => {});
      await page.waitForTimeout(2500);
      const name = `${p.replace(/[^a-z0-9]+/gi, "_") || "home"}-${width}-${scheme}.png`;
      await page.screenshot({ path: `${out}/${name}` }).catch((e) => console.error(name, e.message));
      console.log(`${out}/${name}`);
    }
    await ctx.close();
  }
}
await browser.close();
