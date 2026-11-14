import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { readFileSync } from "node:fs";

// Uses an existing Playwright installation, with no project dependency added.
const { chromium } = createRequire(import.meta.url)(process.env.PLAYWRIGHT_MODULE_PATH ?? "playwright");
const base = process.env.REPOCORTEX_BASE_URL ?? "http://127.0.0.1:3311";
const provenance = JSON.parse(readFileSync(new URL("../public/data/provenance.json", import.meta.url), "utf8"));
const routes = ["/", "/app", ...["overview", "replay", "locate", "agent", "load", "graph", "connect"].map(chapter => `/app/${chapter}`)];
const browser = await chromium.launch({ headless: true });
const problems = [];
const localLinks = new Set();

const observe = page => {
  page.on("console", message => {
    if (["warning", "error"].includes(message.type())) problems.push(`${page.url()}: ${message.text()}`);
  });
  page.on("pageerror", error => problems.push(`${page.url()}: ${error.message}`));
  page.on("response", response => {
    if (response.status() >= 400) problems.push(`${response.status()} ${response.url()}`);
  });
};
const noOverflow = async (page, context) => {
  const size = await page.evaluate(() => ({ viewport: innerWidth, document: document.documentElement.scrollWidth }));
  assert.ok(size.document <= size.viewport, `${context}: ${JSON.stringify(size)}`);
};

try {
  for (const width of [1440, 768, 390, 320]) {
    for (const route of routes) {
      const page = await browser.newPage({ viewport: { width, height: 844 }, reducedMotion: "reduce" });
      observe(page);
      try {
        assert.equal((await page.goto(`${base}${route}`)).status(), 200);
        await page.waitForLoadState("networkidle");
        await page.evaluate(() => document.fonts.ready);
        await noOverflow(page, `${route} at ${width}px`);
        assert.equal(await page.locator("h1").count(), 1);
        const assets = await page.evaluate(async () => {
          for (const image of document.images) {
            image.loading = "eager";
            await image.decode().catch(() => {});
          }
          return [...document.images].map(image => ({ src: image.src, loaded: image.complete && image.naturalWidth > 0, alt: image.alt }));
        });
        assert.ok(assets.every(image => image.loaded && image.alt.length > 20), JSON.stringify(assets));
        const links = await page.locator("a[href]").evaluateAll(links => links.map(link => link.getAttribute("href")));
        for (const href of links) {
          if (href.startsWith("#")) assert.equal(await page.locator(`[id="${href.slice(1)}"]`).count(), 1, `${route}: ${href}`);
          else if (href.startsWith("/")) localLinks.add(href);
        }
        for (const details of await page.locator("details").all()) await details.evaluate(element => { element.open = true; });
        if (route === "/") await page.getByRole("button", { name: "Show the numbers" }).click();
        await noOverflow(page, `${route} expanded at ${width}px`);
        if (width <= 390) {
          for (const chart of await page.locator(".metric-chart").all()) {
            assert.equal(await chart.evaluate(element => element.getBoundingClientRect().width >= element.viewBox.baseVal.width), true, `${route}: preserve readable chart labels`);
            const scroll = chart.locator("..");
            assert.equal(await scroll.evaluate(element => element.scrollWidth > element.clientWidth), true, `${route}: chart must scroll locally`);
            await scroll.focus();
            await scroll.press("End");
            await scroll.evaluate(element => { element.scrollLeft = element.scrollWidth; });
            assert.equal(await scroll.evaluate(element => element.scrollLeft + element.clientWidth >= element.scrollWidth - 1), true, `${route}: chart labels must be reachable`);
          }
          const small = await page.locator("button, input, select, summary, a").evaluateAll(controls => controls
            .filter(control => control.getRootNode() === document && control.checkVisibility() && !control.closest(".sr-only") && !control.classList.contains("skip-link"))
            .map(control => ({ name: control.textContent || control.getAttribute("aria-label") || control.id, width: control.getBoundingClientRect().width, height: control.getBoundingClientRect().height }))
            .filter(control => control.width < 44 || control.height < 44));
          assert.deepEqual(small, [], `${route} tap targets at ${width}px`);
        }
        console.log(`PASS ${route}, ${width}x844, expanded content, images, links and tap targets`);
      } finally {
        await page.close();
      }
    }
  }

  const page = await browser.newPage({ viewport: { width: 390, height: 844 }, reducedMotion: "reduce" });
  observe(page);
  try {
    await page.goto(`${base}/app/locate`);
    await page.waitForLoadState("networkidle");
    await page.locator("#locate-query").fill("query.py");
    await page.locator("#locate-query").press("Enter");
    assert.ok(await page.locator("#matched-ticket option").count() > 1);
    assert.ok(await page.locator("#matched-ticket").evaluate(element => element.getBoundingClientRect().height) >= 44);

    // Repeated ticket IDs refer to different saved fixes. Neither may be hidden.
    const repeated = provenance.issues.filter(issue => issue.ticket === 26434);
    assert.ok(repeated.length > 1);
    await page.locator("#locate-query").fill("26434");
    await page.locator("#locate-query").press("Enter");
    assert.equal(await page.locator("#matched-ticket option").count(), repeated.length);
    for (let index = 0; index < repeated.length; index++) {
      await page.locator("#matched-ticket").selectOption(String(index));
      const expected = repeated[index];
      assert.deepEqual(await page.locator(".ranked-hit .hit-score").allTextContents(), expected.hits.map(hit => hit.score.toFixed(3)));
      assert.deepEqual(await page.locator(".ranked-hit .hit-function small").allTextContents(), expected.hits.map(hit => hit.file));
      assert.equal(await page.locator(".ranked-hit.is-selected .hit-rank").textContent(), String(expected.hits[0].rank));
      await page.locator(".receipt-source summary").click();
      const receipt = await page.locator(".provenance-tree").textContent();
      assert.ok(receipt.includes(expected.hits[0].path.split(" | ")[0].includes("FIXED_IN") ? "FIXED_IN" : expected.hits[0].path.split(" | ")[0]));
      for (const gold of expected.gold) assert.ok(receipt.includes(gold));
      await page.locator(".ranked-hit").nth(1).focus();
      await page.keyboard.press("Enter");
      assert.equal(await page.locator(".ranked-hit.is-selected .hit-rank").textContent(), String(expected.hits[1].rank));
      await noOverflow(page, `duplicate record ${index}, expanded receipt`);
    }
    await page.locator("#matched-ticket").selectOption("0");
    await page.locator("#locate-query").fill("no-such-fix-xyz");
    await page.locator("#locate-query").press("Enter");
    await page.getByRole("button", { name: /Load demo ticket/ }).click();
    assert.equal(await page.locator(".expanded-hit").count(), 1);
    console.log("PASS duplicate-ticket selection, search resets, keyboard receipt expansion and 44px picker");

    await page.goto(`${base}/app/replay`);
    await page.waitForLoadState("networkidle");
    const toggle = page.getByRole("button", { name: "Play learning replay" });
    await toggle.focus();
    await page.keyboard.press("Space");
    assert.equal(await page.getByRole("button", { name: "Pause learning replay" }).getAttribute("aria-pressed"), "true");
    await page.keyboard.press("Space");
    await page.locator("#dashboard-replay-step").focus();
    await page.keyboard.press("End");
    assert.equal(await page.locator("#dashboard-replay-step").inputValue(), "1281");
    await page.keyboard.press("Home");
    assert.equal(await page.locator("#dashboard-replay-step").inputValue(), "0");
    await page.locator(".manual-data summary").click();
    assert.match(await page.locator(".manual-data").textContent(), /frozen reference is this pass's step 0 graph/);
    await page.getByRole("button", { name: "Keyboard shortcuts" }).click();
    await page.keyboard.press("Tab");
    assert.equal(await page.evaluate(() => document.activeElement.closest("dialog") !== null), true);
    await page.keyboard.press("Escape");
    assert.equal(await page.locator(".shortcuts-trigger").evaluate(element => element === document.activeElement), true);
    console.log("PASS Replay keyboard playback, toggle state, slider endpoints and dialog focus");

    await page.goto(`${base}/app/agent`);
    await page.waitForLoadState("networkidle");
    for (const value of ["63,885", "53,888", "46,361", "0.47", "0.40", "gold named third"]) assert.ok((await page.locator("main").textContent()).includes(value));
    for (const href of localLinks) assert.equal((await page.request.get(new URL(href, base).href)).status(), 200, href);
    assert.deepEqual(problems, [], "Browser errors, warnings and failed resources");
    console.log("PASS measured Agent results preserved, all local routes and no console errors or warnings");
  } finally {
    await page.close();
  }
} finally {
  await browser.close();
}
