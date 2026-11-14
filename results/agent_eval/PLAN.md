# Agent eval plan

Compare a coding agent that can call RepoCortex with the same agent that only sees the bug report. The graph is the one produced by `scripts/run_eval.py --replay`. This file is the plan and the harness. The model calls are not run in this repo, because no Claude key is configured here.

## Question

Does `locate_bug` change strict function accuracy on held-out Django fixes?

## Conditions

- `without-mcp`: the model reads the ticket summary and description and returns function names. No graph, no retrieval tool.
- `with-mcp`: the same prompt, plus one tool, `locate_bug(report, k)`. The harness executes that tool against the local ranker and sends the hits back. The model then returns function names.

Both conditions use the same tasks, the same model, and the same scorer. The only difference is the tool.

## Tasks

`python scripts/agent_eval.py prepare --n 30` writes `results/agent_eval/tasks.json` from the held-out split, oldest first. Each task has the report text and the gold functions. The prompt sent to the model does not include the gold.

Gold is the same strict set the replay uses: product functions touched by the fix, tests excluded, at most 8 functions.

## Scoring

A prediction is a list of qualnames, `file::qualname`, or function uids, most likely first. Names are mapped onto the corpus. A name that matches more than one function is dropped.

Function Acc@k is 1 only when every gold function is inside the top k. MRR is the reciprocal rank of the first gold function, and it is 0 when that function is outside the returned list. The score file includes a 95% bootstrap interval (1000 resamples, seed 7).

```bash
python scripts/agent_eval.py score --predictions results/agent_eval/predictions-with-mcp.json
```

## How to run it

The harness talks to the Anthropic Messages API. It does not start the MCP process. For the with-mcp condition it calls the same `locate` function the MCP server exposes, so the comparison is the tool result, not the transport.

```bash
python scripts/agent_eval.py prepare --n 30
ANTHROPIC_API_KEY=... python scripts/agent_eval.py run --condition without-mcp
ANTHROPIC_API_KEY=... python scripts/agent_eval.py run --condition with-mcp
```

`ANTHROPIC_MODEL` overrides the default `claude-sonnet-4-5`. `with-mcp` needs `data/corpus.json`, `data/embeddings.npz`, and `data/learned_state.npz` from the replay. If `ANTHROPIC_API_KEY` is missing, `run` prints these commands and exits without calling a model.

Outputs:

- `results/agent_eval/predictions-with-mcp.json`
- `results/agent_eval/predictions-without-mcp.json`
- a `*-scores.json` next to each predictions file

## What not to claim

A higher with-mcp score means the tool helped on this task sample. It does not, by itself, mean the graph learned during the agent session. Online updates go through `learn_from_fix`, which this comparison does not call.
