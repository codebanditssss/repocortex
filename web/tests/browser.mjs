import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { mkdirSync, mkdtempSync, rmSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { join } from "node:path";
import { readFileSync } from "node:fs";

// Run against `npm start` with the Factory agent-browser CLI installed.
const root = fileURLToPath(new URL("..", import.meta.url));
const tempRoot = join(root, ".tmp");
mkdirSync(tempRoot, { recursive: true });
const temp = mkdtempSync(join(tempRoot, "browser-"));
const base = process.env.REPOCORTEX_BASE_URL ?? "http://127.0.0.1:3000";
const env = {
  ...process.env,
  HOME: join(temp, "home"),
  TMPDIR: temp,
  XDG_CACHE_HOME: join(temp, "cache"),
  XDG_CONFIG_HOME: join(temp, "config"),
  XDG_DATA_HOME: join(temp, "data"),
  XDG_RUNTIME_DIR: join(temp, "run"),
  AGENT_BROWSER_EXECUTABLE_PATH: process.env.AGENT_BROWSER_EXECUTABLE_PATH ?? "/usr/bin/google-chrome",
};
mkdirSync(env.HOME, { recursive: true });
mkdirSync(env.XDG_RUNTIME_DIR, { recursive: true });
env.AGENT_BROWSER_SESSION = process.env.AGENT_BROWSER_SESSION ??
  execFileSync("agent-browser", ["session", "id", "--scope", "worktree", "--prefix", "rc"], {
    cwd: root, env, encoding: "utf8",
  }).trim();

const run = (...args) => execFileSync("agent-browser", args, {
  cwd: root, env, encoding: "utf8", timeout: 30000,
});
const json = (...args) => {
  const result = JSON.parse(run(...args, "--json"));
  assert.equal(result.success, true, JSON.stringify(result.error));
  return result.data;
};
const evaluate = (source) => json("eval", source).result;
const routes = ["/", "/app", "/app/overview", "/app/replay", "/app/locate", "/app/agent", "/app/load", "/app/graph", "/app/connect"];

try {
  for (const width of [1440, 768, 320]) {
    run("open", base);
    run("set", "viewport", String(width), "900");
    for (const route of routes) {
      run("open", `${base}${route}`);
      const state = evaluate(`(async () => {
        await document.fonts.ready;
        return {
          width: innerWidth,
          scrollWidth: document.documentElement.scrollWidth,
          headings: document.querySelectorAll("h1").length,
          main: document.querySelectorAll("main#main-content").length,
          active: document.querySelector('.chap [aria-current="page"]')?.getAttribute("href"),
          background: getComputedStyle(document.body).backgroundColor,
          text: document.body.innerText,
          localFont: document.fonts.check('16px "Departure Mono"'),
          grain: getComputedStyle(document.querySelector(".grain")).backgroundImage.startsWith('url("data:image/png'),
          footerBottom: document.querySelector("footer").getBoundingClientRect().bottom,
        };
      })()`);
      const screenshots = process.env.REPOCORTEX_SCREENSHOTS_DIR;
      if (screenshots && width !== 768) {
        mkdirSync(screenshots, { recursive: true });
        run("screenshot", join(screenshots, `${route === "/" ? "landing" : route === "/app" ? "overview" : route.split("/").at(-1)}-${width}.png`));
      }
      assert.equal(state.width, width);
      assert.ok(state.scrollWidth <= width, `${route} overflows at ${width}px`);
      assert.equal(state.headings, 1);
      assert.equal(state.main, 1);
      assert.equal(state.background, "rgb(242, 238, 230)");
      assert.equal(state.localFont, true);
      assert.equal(state.grain, true);
      assert.doesNotMatch(state.text, /\u2014|\p{Extended_Pictographic}/u);
      if (route === "/") {
        assert.match(state.text, /held-out ticket \/ #\d+/i);
        assert.match(state.text, /36857/);
        assert.match(state.text, /0\.843/);
        assert.match(state.text, /learned graph beats dense on both/);
        assert.doesNotMatch(state.text, /Not run in this pass|still lead|slips from/);
        const content = evaluate(`({
          plates: [...document.querySelectorAll(".paper-plate img")].map(img => ({ alt: img.alt, source: img.getAttribute("src"), fit: getComputedStyle(img).objectFit })),
          loadRows: [...document.querySelectorAll(".load-table tbody tr")].map(row => [...row.children].map(cell => cell.textContent)),
          agentFixture: document.querySelector(".agent-section .fixture-label").textContent,
          plateBottom: document.querySelector(".hero-mycelium").getBoundingClientRect().bottom,
          copyTop: document.querySelector(".hero-copy").getBoundingClientRect().top
        })`);
        assert.equal(content.plates.length, 4);
        assert.ok(content.plates[0].source.includes("hero-mycelium"));
        assert.equal(content.plates[0].fit, "contain");
        assert.ok(content.plates.every(plate => plate.alt.length > 20 && !plate.source.includes("teaser-")));
        assert.deepEqual(content.loadRows, [["8", "21", "44", "0", "62.94"]]);
        assert.equal(content.agentFixture, "Placeholder fixture");
        assert.ok(content.plateBottom <= content.copyTop, "the whole hero plate and caption must remain above the typography");
      }
      if (route === "/" && width === 320) {
        const labels = evaluate(`({
          captionBottom: document.querySelector(".route-inset-label").getBoundingClientRect().bottom,
          predictionTop: document.querySelector(".route-prediction-one").getBoundingClientRect().top
        })`);
        assert.ok(labels.captionBottom <= labels.predictionTop, "mobile graph captions must not overlap");
      }
      if (route !== "/") {
        assert.equal(state.active, route === "/app" ? "/app/overview" : route);
        assert.match(state.text, /1281 train \/ 319 held out/);
        if (width === 1440) assert.ok(state.footerBottom <= 901, `${route} running foot must fit the 900px journal frame: ${state.footerBottom}`);
      }
      if (width === 1440) {
        const audit = json("a11y");
        assert.equal(audit.counts.violations, 0, JSON.stringify(audit.violations));
      }
      const errors = json("errors").errors ?? [];
      assert.equal(errors.length, 0, JSON.stringify(errors));
      console.log(`PASS ${route} at ${width}px`);
    }
  }

  // Landing controls are exercised against the production build and real fixtures.
  const curve = JSON.parse(readFileSync(join(root, "public/data/curve.json"), "utf8"));
  run("set", "viewport", "1440", "900");
  run("open", base);
  run("wait", "--fn", 'document.querySelector(".hero-ticket button").textContent.includes("Restart")');
  const offscreen = evaluate(`(async () => {
    document.querySelector("#install").scrollIntoView();
    await new Promise(resolve => setTimeout(resolve, 150));
    const start = document.querySelector(".ticket-title > [aria-hidden]").textContent;
    await new Promise(resolve => setTimeout(resolve, 500));
    return { start, end: document.querySelector(".ticket-title > [aria-hidden]").textContent };
  })()`);
  assert.equal(offscreen.start, offscreen.end, "hero typing must pause offscreen");
  // A resize must not trigger canvas printing while the plate is offscreen.
  evaluate(`window.__platePrints = 0;
    window.__originalPutImageData = CanvasRenderingContext2D.prototype.putImageData;
    CanvasRenderingContext2D.prototype.putImageData = function(...args) {
      if (this.canvas.closest(".graph-print")) window.__platePrints++;
      return window.__originalPutImageData.apply(this, args);
    };`);
  run("set", "viewport", "1360", "900");
  assert.equal(evaluate("(async()=>{await new Promise(resolve=>setTimeout(resolve,200));return window.__platePrints})()"), 0);
  evaluate("document.querySelector('.hero').scrollIntoView()");
  run("wait", "--fn", "window.__platePrints > 0");
  evaluate("CanvasRenderingContext2D.prototype.putImageData = window.__originalPutImageData");
  run("set", "viewport", "1440", "900");
  console.log("PASS default autoplay and offscreen typing/canvas suspension");
  run("set", "media", "light", "reduced-motion");
  run("open", base);
  run("wait", "--fn", 'document.querySelector(".hero .graph-print")?.dataset.ready === "true"');
  assert.equal(evaluate('matchMedia("(prefers-reduced-motion: reduce)").matches'), true);
  assert.equal(evaluate('document.querySelector(".hero-route").classList.contains("is-found")'), true);
  assert.equal(evaluate('document.querySelector(".hero-ticket button").textContent.includes("Play")'), true);
  assert.equal(evaluate('document.querySelector(".hero canvas").getAttribute("aria-hidden")'), "true");
  assert.equal(evaluate('document.querySelector(".hero-counter > .num").textContent'), "1281");

  const screenshots = process.env.REPOCORTEX_SCREENSHOTS_DIR;
  if (screenshots) run("screenshot", join(screenshots, "landing-annotated-1440.png"));

  run("click", 'a[href="#replay"].landing-primary');
  assert.equal(evaluate("location.hash"), "#replay");
  run("wait", "--fn", 'document.querySelector(".replay-graph .graph-print")?.dataset.ready === "true"');
  assert.equal(evaluate('document.querySelector(".metric-switch [aria-pressed=true]").textContent'), "File Acc@1");
  for (const metric of ["file_acc@1", "function_acc@10"]) {
    run("click", `.metric-switch button:nth-child(${metric === "file_acc@1" ? 1 : 2})`);
    run("focus", "#replay-step");
    run("press", "Home");
    for (const [index, point] of curve.curve.entries()) {
      if (index) run("press", "ArrowRight");
      const state = evaluate(`({
        step: document.querySelector(".replay-range output").textContent,
        value: document.querySelector(".chart-label-repo .chart-series-value").textContent,
        graphStep: document.querySelector(".replay-graph .graph-print").dataset.step,
        baselineCount: document.querySelectorAll(".chart-label-baseline").length,
        chartTitle: document.querySelector(".metric-chart title").textContent
      })`);
      assert.equal(state.step, `${point.step} / ${curve.train}`);
      assert.equal(state.value, `${Number((point[metric] * 100).toFixed(2))}%`);
      assert.equal(state.graphStep, String(point.step));
      assert.equal(state.baselineCount, 3);
      assert.ok(state.chartTitle.includes(String(point.step)));
      const geometry = evaluate(`(() => {
        const texts = [...document.querySelectorAll(".chart-series-label, .chart-series-value, .chart-tick, .chart-axis-title")].map(el => {
          const r = el.getBBox(); return { text: el.textContent, x: r.x, y: r.y, right: r.x + r.width, bottom: r.y + r.height };
        });
        const overlaps = [];
        for (let i = 0; i < texts.length; i++) for (let j = i + 1; j < texts.length; j++) {
          const a = texts[i], b = texts[j];
          if (a.x < b.right && b.x < a.right && a.y < b.bottom && b.y < a.bottom) overlaps.push([a.text,b.text]);
        }
        return {
          overlaps,
          labelXs: [...document.querySelectorAll(".chart-series-label, .chart-series-value")].map(el => el.getBBox().x),
          plotRight: Number(document.querySelector(".chart-rule").getAttribute("x2"))
        };
      })()`);
      assert.deepEqual(geometry.overlaps, [], `${metric} at ${point.step}: text overlaps`);
      assert.ok(geometry.labelXs.every(x => x > geometry.plotRight), "series labels must stay off data strokes");
    }
  }
  run("click", ".show-numbers");
  assert.equal(evaluate('document.querySelector(".show-numbers").getAttribute("aria-expanded")'), "true");
  assert.equal(evaluate('document.querySelectorAll("#curve-data tbody tr").length'), curve.curve.length * 2);
  const audit = json("a11y");
  assert.equal(audit.counts.violations, 0, JSON.stringify(audit.violations));
  run("click", ".show-numbers");
  run("click", ".metric-switch button:first-child");
  if (screenshots) run("screenshot", join(screenshots, "landing-replay-1440.png"));
  run("click", ".replay-play");
  assert.equal(evaluate('document.querySelector(".replay-play").getAttribute("aria-label")'), "Pause learning replay");
  run("wait", "--fn", 'Number(document.querySelector("#replay-step").value) > 0');
  run("click", ".replay-play");
  assert.equal(evaluate('document.querySelector(".replay-play").getAttribute("aria-label")'), "Play learning replay");
  run("open", `${base}#install`);
  evaluate('window.__copiedCommand = null; Object.defineProperty(navigator, "clipboard", {configurable:true,value:{writeText:async text=>{window.__copiedCommand=text}}})');
  run("click", ".command-line button");
  assert.equal(evaluate("window.__copiedCommand"), "npx repocortex");
  assert.equal(evaluate('document.querySelector(".copy-status").textContent'), "Copied");
  evaluate('Object.defineProperty(navigator, "clipboard", {configurable:true,value:{writeText:async ()=>{throw new Error("denied")}}})');
  run("click", ".command-line button");
  assert.equal(evaluate('document.querySelector(".copy-status").textContent'), "Select and copy the command");
  assert.equal(evaluate("getSelection().toString()"), "npx repocortex");
  run("open", base);
  run("click", ".hero-ticket button");
  assert.equal(evaluate('document.querySelector(".hero-ticket button").textContent.includes("Restart")'), true);
  evaluate("document.activeElement.blur()");
  run("press", "Space");
  assert.equal(evaluate('document.querySelector(".hero-route").classList.contains("is-found")'), false);
  run("wait", "--fn", 'document.querySelector(".hero-route").classList.contains("is-found")');
  run("wait", "--fn", 'document.querySelector(".hero-ticket button").textContent.includes("Play")');
  console.log("PASS reduced motion, hero replay, every metric checkpoint, table, replay playback, copy and clipboard failure");

  run("set", "viewport", "320", "900");
  run("open", `${base}#replay`);
  run("click", ".metric-switch button:nth-child(2)");
  run("focus", "#replay-step");
  run("press", "Home");
  assert.equal(evaluate('document.querySelector(".replay-range output").textContent'), "0 / 1281");
  run("press", "End");
  assert.equal(evaluate('document.querySelector(".chart-label-repo .chart-series-value").textContent'), "43.75%");
  assert.equal(evaluate("document.documentElement.scrollWidth <= innerWidth"), true);
  const mobileAudit = json("a11y");
  assert.equal(mobileAudit.counts.violations, 0, JSON.stringify(mobileAudit.violations));
  if (screenshots) run("screenshot", join(screenshots, "landing-replay-320.png"));
  console.log("PASS mobile replay keyboard control and accessibility");

  // Dashboard controls use the same real curve, but a per-fix playhead.
  run("set", "viewport", "1440", "900");
  run("open", `${base}/app/replay`);
  assert.equal(evaluate('document.querySelector(".replay-toggle").textContent.includes("Play")'), true);
  evaluate("document.activeElement.blur()");
  run("press", "]");
  assert.equal(evaluate('document.querySelector("#dashboard-replay-step").value'), "201");
  run("press", "[");
  assert.equal(evaluate('document.querySelector("#dashboard-replay-step").value'), "200");
  run("focus", ".replay-toggle");
  run("press", "]");
  assert.equal(evaluate('document.querySelector("#dashboard-replay-step").value'), "201", "step keys must also work after using a playback button");
  run("press", "[");
  assert.equal(evaluate('document.querySelector("#dashboard-replay-step").value'), "200");
  for (const metric of ["file_acc@1", "function_acc@10"]) {
    run("click", `.manual-metric-switch button:nth-child(${metric === "file_acc@1" ? 1 : 2})`);
    for (const point of curve.curve) {
      run("click", `.checkpoint-buttons button[data-step="${point.step}"]`);
      assert.equal(evaluate('document.querySelector(".chart-label-repo .chart-series-value").textContent'), `${Number((point[metric] * 100).toFixed(2))}%`);
      const overlaps = evaluate(`(() => {
        const text = [...document.querySelectorAll(".chart-series-label, .chart-series-value, .chart-tick, .chart-axis-title")].map(el => {
          const b = el.getBBox(); return { text: el.textContent, x: b.x, y: b.y, right: b.x+b.width, bottom: b.y+b.height };
        });
        return text.flatMap((a,i) => text.slice(i+1).filter(b => a.x<b.right && b.x<a.right && a.y<b.bottom && b.y<a.bottom).map(b=>[a.text,b.text]));
      })()`);
      assert.deepEqual(overlaps, [], `${metric} dashboard at ${point.step}`);
    }
  }
  run("click", ".underlined-control");
  assert.equal(evaluate('document.querySelector("#dashboard-replay-step").value'), "1281");
  evaluate("document.activeElement.blur()");
  run("press", "Space");
  run("wait", "--fn", 'Number(document.querySelector("#dashboard-replay-step").value) > 0 && Number(document.querySelector("#dashboard-replay-step").value) < 1281');
  run("press", "Space");
  assert.equal(evaluate('document.querySelector(".replay-toggle").textContent.includes("Play")'), true);
  run("click", '.replay-speeds button:last-child');
  run("click", '.checkpoint-buttons button[data-step="274"]');
  run("click", ".replay-toggle");
  run("wait", "--fn", 'document.querySelector("#dashboard-replay-step").value === "1281" && document.querySelector(".replay-toggle").textContent.includes("Play")');
  console.log("PASS dashboard checkpoints, label geometry, prev/next, keyboard playback, speed and stop at end");

  run("open", `${base}/app/locate`);
  assert.match(evaluate('document.querySelector(".expanded-hit").textContent'), /36857/);
  assert.match(evaluate('document.querySelector(".ranked-hit.is-selected").textContent'), /QuerySet.totally_ordered.*0\.843/s);
  run("click", ".ranked-hits > li:nth-child(2) .ranked-hit");
  assert.equal(evaluate('document.querySelectorAll(".expanded-hit").length'), 1);
  run("click", ".receipt-source summary");
  assert.match(evaluate('document.querySelector(".provenance-tree").textContent'), /rank 2/);
  run("fill", "#locate-query", "query.py");
  run("press", "Enter");
  assert.ok(evaluate('document.querySelector("#matched-ticket").options.length') > 1);
  run("fill", "#locate-query", "no-such-file-xyz-123");
  run("press", "Enter");
  assert.match(evaluate('document.querySelector(".locate-empty").textContent'), /Nothing in this index matches/);
  run("fill", "#locate-query", "");
  run("press", "Enter");
  assert.match(evaluate('document.querySelector(".locate-empty").textContent'), /Start with a ticket/);
  run("click", ".locate-empty button");
  assert.match(evaluate('document.querySelector(".expanded-hit").textContent'), /36857/);
  const typingCheck = evaluate('location.pathname');
  run("fill", "#locate-query", "LOAD");
  assert.equal(evaluate('location.pathname'), typingCheck);
  evaluate("document.activeElement.blur()");
  run("press", "?");
  assert.equal(evaluate('document.querySelector(".shortcuts-dialog").open'), true);
  assert.equal(json("a11y").counts.violations, 0, "the shortcuts dialog must be accessible");
  run("press", "Tab");
  assert.equal(evaluate('document.activeElement.closest("dialog") !== null'), true);
  run("press", "Escape");
  assert.equal(evaluate('document.querySelector(".shortcuts-dialog").open'), false);
  assert.equal(evaluate('document.activeElement.className'), "shortcuts-trigger");
  for (const [key, route] of [["o","overview"], ["r","replay"], ["l","locate"], ["a","agent"], ["d","load"], ["g","graph"], ["c","connect"]]) {
    run("press", key);
    run("wait", "--url", `**/app/${route}`);
  }
  run("press", "k");
  run("wait", "--fn", 'document.activeElement.id === "locate-query"');
  console.log("PASS Locate selected receipts, substring search, no matches, empty state, samples, text-field guards and global shortcuts");

  run("open", `${base}/app/connect`);
  evaluate('window.__copiedConfig = null; Object.defineProperty(navigator, "clipboard", {configurable:true,value:{writeText:async text=>{window.__copiedConfig=text}}})');
  run("click", ".config-sheet-head button");
  assert.equal(JSON.parse(evaluate("window.__copiedConfig")).mcpServers.repocortex.command, "python");
  assert.equal(evaluate('document.querySelector(".copy-config-status").textContent'), "Copied");
  evaluate('Object.defineProperty(navigator, "clipboard", {configurable:true,value:{writeText:async()=>{throw new Error("denied")}}})');
  run("click", ".config-sheet-head button");
  assert.match(evaluate('document.querySelector(".copy-config-status").textContent'), /Select and copy/);
  assert.match(evaluate("getSelection().toString()"), /mcpServers/);
  console.log("PASS MCP configuration clipboard success and failure");

  run("set", "viewport", "320", "900");
  run("open", `${base}/app/locate`);
  run("click", ".receipt-source summary");
  assert.equal(evaluate("document.documentElement.scrollWidth <= innerWidth"), true, "full provenance receipts must not widen the mobile page");
  run("fill", "#locate-query", "QuerySet totally_ordered");
  run("press", "Enter");
  assert.match(evaluate('document.querySelector(".ranked-hits").textContent'), /totally_ordered/);
  assert.equal(evaluate("document.documentElement.scrollWidth <= innerWidth"), true);
  assert.equal(json("a11y").counts.violations, 0);
  console.log("PASS mobile Locate phrase search and expanded receipt accessibility");

  run("open", `${base}/app`);
  run("click", '.chap a[href="/app/replay"]');
  run("wait", "--url", "**/app/replay");
  assert.equal(evaluate('document.querySelector(".chap [aria-current]").getAttribute("href")'), "/app/replay");
  assert.match(evaluate('document.querySelector("footer").textContent'), /plate ii of vii/);
  run("back");
  run("wait", "--url", "**/app");
  assert.equal(evaluate('document.querySelector(".chap [aria-current]").getAttribute("href")'), "/app/overview");

  run("open", base);
  run("press", "Tab");
  assert.equal(evaluate("document.activeElement.className"), "skip-link");
  assert.ok(evaluate("document.activeElement.getBoundingClientRect().top") >= 0);
  run("press", "Enter");
  assert.equal(evaluate("document.activeElement.id"), "main-content");
  console.log("PASS client navigation, browser history, and keyboard skip link");

  for (const name of ["curve", "baselines", "graph", "graph_stats", "snapshots", "provenance", "agent", "load", "loadtest"]) {
    const response = await fetch(`${base}/data/${name}.json`);
    assert.equal(response.status, 200);
    assert.match(response.headers.get("content-type"), /json/);
    const data = await response.json();
    assert.equal(data.placeholder, ["graph", "snapshots", "agent"].includes(name));
  }
  const font = await fetch(`${base}/fonts/DepartureMono-Regular.woff2`);
  assert.equal(font.status, 200);
  console.log("PASS all public JSON and local font endpoints");
  const errors = json("errors").errors ?? [];
  assert.equal(errors.length, 0, JSON.stringify(errors));
} finally {
  try { run("close"); } finally { rmSync(temp, { recursive: true, force: true }); }
}
