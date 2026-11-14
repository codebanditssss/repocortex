# RepoCortex web

The marketing landing page at `/` and the dashboard at `/app` live here.
Next.js App Router, strict TypeScript, and Tailwind CSS.

Run `npm install`, then `npm run dev`. Check with `npm run build`, `npm run lint`,
`npm run typecheck`, and `npm test`.
With `npm start` running and Factory's `agent-browser` installed, run
`npm run test:browser` for desktop/mobile navigation and accessibility checks.
With an existing Playwright installation, `node tests/polish.browser.mjs` checks
console warnings, expanded mobile states, images, links, tap targets, and repeated
ticket records. Set `PLAYWRIGHT_MODULE_PATH` to its module path and
`REPOCORTEX_BASE_URL` to the running app (defaults to `http://127.0.0.1:3311`).

Numbers come from `public/data`, sourced from backend `results/` when real.
`curve.json` and `baselines.json` contain the current measured backend evaluation.
Provenance, agent results, load results, and graph counts are real.
Graph layout and edge-delta snapshots remain labeled placeholders.
`lib/data.ts` provides typed browser loaders. Build-time pages import the same JSON.

The visual source is mockups-v3: paper, ink, vermilion, and running heads and feet.
`public/art/CATALOG.md` describes the ink-on-paper plates. The hero uses the
mycelium plate alongside the live graph; three small doodles mark section margins.
Fonts use `next/font/google`, so the first build needs access to Google Fonts.
Departure Mono is served locally from `public/fonts/`.

## Landing page

The landing page follows Concept B in the v3 field-manual language. Its 2D
Atkinson plates reuse `lib/graph.ts` and the precomputed layout. Synthetic
shortcut edges are excluded. Plates redraw only on data or size changes while
near the viewport and the tab is visible. There is no force layout or added
animation dependency.

The ticket demo starts once, after a short delay. Space replays it while the
hero is visible. Reduced motion shows the final annotations without autoplay.
Replay has explicit play/pause, keyboard-accessible checkpoint scrubbing, both
measured metrics, three single-point baseline references, and accessible tables.
The landing hero is a measured rank-one gold hit with a FIXED_IN receipt from the held-out provenance file.
The replay uses every checkpoint in the held-out curve. Frozen is the unlearned hybrid ranker, so step 0 is the starting point for this pass's learning gain.
The single Locust run is shown as eight users, not a concurrency sweep.
Graph layouts and weight deltas, and the unpublished install
command are explicitly labeled as placeholders. Synthetic snapshots use the
nearest earlier fixture checkpoint; their cadence is independent of the curve.

`tests/landing.test.mjs` checks chart geometry, label separation at every
checkpoint, and provenance fidelity. `tests/browser.mjs` also exercises landing
controls, reduced motion, clipboard success/failure, and mobile accessibility.

## Dashboard field manual

All seven chapters are implemented at `/app/overview`, `/app/replay`,
`/app/locate`, `/app/agent`, `/app/load`, `/app/graph`, and `/app/connect`.
`/app` opens Overview. The dashboard uses small, framed spot-art plates and the
v3 running head, roman chapter navigation, hairlines, and running foot.

Overview compares both measured metrics with every baseline and records the
four operator totals. Replay reuses the landing's SVG chart and dithered graph
renderer. Its playhead moves through fixes 0 to 1281; scores come only from the
recorded checkpoints. Graph layout and weight deltas remain placeholders.
Playback starts paused, has 1x/4x/8x speeds, and stops at the last fix.

Locate searches all 319 saved provenance records locally by ticket number,
function UID, or filename substring. Whitespace-separated search terms must
all match those fields. This is not live semantic search over report bodies.
It opens on a measured held-out ticket and preserves the selected hit's score, gold annotation,
FIXED_IN evidence, SHORTCUT evidence, and full provenance receipt. Separate fixes
for the same ticket remain independently selectable in the record picker.

Agent shows the measured 30-bug Claude Sonnet 5.5 evaluation: 63,885 mean input
tokens without the tool, 53,888 with it available (16% fewer), and 46,361 when
told to call it first (27% fewer). Accuracy is about the same. The example trace
found the gold function with and without the tool.
Load shows only the measured eight-user, 20-second Locust run. Graph separates
real node/edge/label counts from the placeholder printed layout. Connect offers
a copyable, unverified local MCP configuration example using the backend script
paths, not a claimed published installer or live health check.

Press `?` for the native, focus-trapped shortcuts dialog. `O R L A D G C` switch
chapters; `K` focuses Locate; Space plays or pauses Replay, or opens it from
another chapter; `[` and `]` step the playhead. Escape closes the dialog.
Text fields retain their normal typing behavior.

`tests/dashboard.test.mjs` adds checkpoint, local search, and selected-receipt
regressions. The existing browser suite now also tests dashboard playback,
every chart checkpoint, Locate states, global shortcuts, and configuration copy.
It checks all routes at 1440, 768, 390, and 320 pixels, plus desktop axe audits.
