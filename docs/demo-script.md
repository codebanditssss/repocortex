# RepoCortex demo script

A 90-second walkthrough: one fresh query, its database receipts, the measured
learning curve, and the agent workflow. Record at 1080p with captions.

Before recording, open `/app/locate`, `/app/replay`, and `/app/agent`. Confirm the
Locate backend is reachable. Run the example once to check its actual response;
do not promise a particular rank or latency. If the backend returns cached mode,
label it cached and omit the live-database claim. Keep wait time visible or mark
an edit as “search wait shortened.”

## 0:00–0:10 · Start with the problem

Screen: landing page, then `/app/locate`.

Caption: Find the functions. Learn from the fix.

Voiceover: “Where should a coding agent look first? RepoCortex uses a repository's
code graph and past fixes to rank candidate functions, with evidence behind each
suggestion.”

## 0:10–0:30 · Run a fresh search

Screen: click **Query compilation**, then **Find functions**. Expand
one returned function. Show the actual file, line, and supporting paths.

Caption: Fresh ranking · live structural graph + cached learned memory

Voiceover, only when the response says live: “This is a fresh search. HydraDB
supplies the structural edges; saved fix memory adds what the replay learned.
Here is a candidate function, and the paths that supported it.”

## 0:30–0:43 · Show what the database did

Screen: expand **Database query receipts**, a relationship group, then a query. Show the Cypher,
returned-row count, and any row-limit notice. Do not present the illustrative
graph animation as a captured query or mutation log.

Caption: Bounded HydraDB reads · query and row counts visible

Voiceover: “These receipts show the database reads for this request. The search
is bounded, and the interface tells us when a query reaches its row limit.”

## 0:43–1:05 · Show the learning evidence

Screen: `/app/replay`, select Function Acc@10, scrub from the first to last
checkpoint. Open **What the benchmark measures** on the landing replay or overview.

Caption: No graph 41.7% → frozen graph 45.1% → learned 48.3%

Voiceover: “In the saved Django experiment, dense plus BM25 scores 41.7 percent.
The frozen graph scores 45.1; learning reaches 48.3. This is a retrospective
319-fix evaluation. Excluding three rows whose tickets appeared in training
preserves the gain.”

## 1:05–1:20 · Connect the evidence to agent work

Screen: `/app/agent`, show the three conditions and sample size.

Caption: 30 tasks · 16–27% fewer input tokens · accuracy gain not established

Voiceover: “In a small, thirty-task agent study, the tool reduced input tokens
by sixteen to twenty-seven percent. Accuracy differed by one task, so we do not
claim an accuracy improvement.”

## 1:20–1:30 · Close on the workflow

Screen: `/app/connect`, show `locate_bug` and `learn_from_fix`.

Caption: MCP · self-hosted HydraDB · confirmed fixes become memory

Voiceover: “Use it over MCP. Ask where to look, inspect the evidence, and feed
back the confirmed fix. RepoCortex gives the next investigation a better
starting point.”

## Sources

### Optional persistence demonstration

Run `.venv/bin/python -m scripts.demo_feedback` to inspect prediction → confirmed
diff → saved memory → reload → prediction. It uses two synthetic functions and
fixed vectors in a temporary directory; it does not connect to HydraDB, alter the
recovered runtime, or measure accuracy. The JSON checks that feedback promotes
the confirmed function, reloading preserves the result, and duplicate feedback
is skipped. Use this only to explain persistence, separately from the real Django
evaluation and live database receipts.

### Evidence files

- Accuracy and paired intervals: `results/lexical_gap.json`, `results/curve.json`
- Split, repeated tickets, and sensitivity: `docs/evaluation-audit.md`
- Agent study: `results/agent_eval/results.json`, `results/agent_eval/README.md`
- Recorded example paths: `results/provenance.json`
- Live receipts: the response captured during recording; not the saved benchmark

The video URL belongs in `SUBMISSION.md` only after the recording is uploaded.
