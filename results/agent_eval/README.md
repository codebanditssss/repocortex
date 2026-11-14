# Agent eval results

A tool-using Claude agent tries to name the functions a Django fix touched, on the oldest 30 held-out fixes (the graph never trained on them). Every arm gets the same Django checkout at the graph snapshot `f24f38c6b282` and the same tools: `search_code` (ripgrep), `read_file` (120 lines per call), `list_dir`, and `submit`. `with-mcp` also gets `locate_bug`, which calls the same function the MCP server exposes, against the replayed graph. The ticket number is never shown, so the agent cannot grep for a regression test by id.

Model `claude-sonnet-5-5`, at most 14 model turns and 140k input tokens per issue, 1200 output tokens per call, prompt caching on. Harness: `scripts/agent_bench.py`. Raw runs: `runs-*.json`. Scored summary: `results.json`.

| | without-mcp | with-mcp | with-mcp, told to call it first | locate_bug alone, no model |
|---|---:|---:|---:|---:|
| top-1 function correct | 0.40 (12/30) | 0.43 (13/30) | 0.43 (13/30) | 0.47 (14/30) |
| top-1 file correct | 0.63 | 0.63 | 0.63 | 0.67 |
| strict fn Acc@5 | 0.37 | 0.40 | 0.37 | 0.30 |
| MRR | 0.45 | 0.47 | 0.47 | 0.49 |
| input tokens per issue | 63,885 | 53,888 (-16%) | 46,361 (-27%) | 0 |
| output tokens per issue | 3,615 | 2,952 | 2,577 | 0 |
| tool calls per issue | 11.3 | 9.8 | 9.1 | 1 |
| locate_bug calls per issue | 0 | 0.43 | 0.93 | 1 |
| files opened per issue | 2.8 | 2.4 | 2.2 | 0 |
| model turns per issue | 9.6 | 8.3 | 7.5 | 0 |
| wall time per issue | 36.5 s | 29.9 s | 41.8 s | under 1 s |
| cost per issue | $0.063 | $0.054 | $0.049 | $0 |
| cost for 30 issues | $1.90 | $1.62 | $1.47 | $0 |

Top-1 function correct means the first function the agent named is one the real fix changed. Strict Acc@5 needs every gold function in the first 5 names. Input tokens count cached reads too. Costs use Anthropic list prices for Sonnet 5.5 ($2 in, $10 out, $2.50 cache write, $0.10 cache read per million tokens).

## What this shows

- Accuracy is about the same. The with-mcp gain is one issue out of 30 (2 wins, 1 loss on top-1 against without-mcp), well inside the noise. The 95% interval on strict Acc@5 is about 0.2 to 0.6 for every arm.
- The agent works less with the tool: 16% fewer input tokens, 13% fewer tool calls, 15% lower cost. Told to call `locate_bug` first, it uses 27% fewer input tokens and costs 22% less.
- Left alone, the agent called `locate_bug` on only 13 of 30 issues.
- `locate_bug` by itself, with no model, gets the top-1 function as often as the agent does, in under a second and for free.

## Caveats

- 30 issues, one model, one run each. Small differences are noise.
- Wall time depends on API latency. The locate-first arm hit slow responses and one timeout retry, so its time is not comparable.
- The checkout is the graph snapshot, which already contains the fixes. That is the same setting the ranker is scored in, and the agent never sees git history.
- Ticket 26434 appears twice in the task list (two fix commits). Runs and scores are paired by task position.

## Reproduce

```bash
python scripts/agent_eval.py prepare --n 30
ANTHROPIC_API_KEY=... python scripts/agent_bench.py run --condition without-mcp --limit 30 --tag sonnet
ANTHROPIC_API_KEY=... python scripts/agent_bench.py run --condition with-mcp --limit 30 --tag sonnet
ANTHROPIC_API_KEY=... python scripts/agent_bench.py run --condition with-mcp --locate-first --limit 30 --tag sonnet-first
python scripts/agent_bench.py tool-only
python scripts/agent_bench.py report
```

`with-mcp` needs `data/corpus.json`, `data/embeddings.npz`, and `data/learned_state.npz` from `scripts/run_eval.py --replay`. `--provider gmi` runs the same loop on the GMI OpenAI-compatible endpoint.
