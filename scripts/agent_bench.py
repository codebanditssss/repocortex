"""Tool-using agent on held-out Django bugs, with and without locate_bug.

Both conditions get the same Django checkout (the graph snapshot) and the same
tools: search_code, read_file, list_dir, and submit. with-mcp also gets
locate_bug, which runs the same function the MCP server exposes. The ticket
number is never shown, so the agent cannot grep for a regression test by id.

    python scripts/agent_eval.py prepare --n 15
    python scripts/agent_bench.py run --condition without-mcp --limit 15
    python scripts/agent_bench.py run --condition with-mcp --limit 15
    python scripts/agent_bench.py report

Provider is anthropic by default (ANTHROPIC_API_KEY, AGENT_MODEL, default
claude-sonnet-5-5). --provider gmi uses the OpenAI-compatible GMI endpoint
(GMI_API_KEY).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from repocortex.eval.metrics import bootstrap_ci, score_rows, summarize  # noqa: E402
from scripts.agent_eval import function_index, resolve_name  # noqa: E402

OUT_DIR = ROOT / "results" / "agent_eval"
MAX_TURNS = 14
MAX_OUT = 1200
INPUT_BUDGET = 140_000  # input tokens per issue, cache reads included
READ_LINES = 120
SEARCH_HITS = 30

# USD per million tokens
PRICES = {
    "claude-sonnet-5-5": {"in": 2.0, "out": 10.0, "cache_write": 2.5, "cache_read": 0.10},
    "claude-sonnet-5": {"in": 2.0, "out": 10.0, "cache_write": 2.5, "cache_read": 0.20},
    "claude-haiku-4-5-20251001": {"in": 1.0, "out": 5.0, "cache_write": 1.25, "cache_read": 0.10},
}

SYSTEM = (
    "You are a coding agent working in a checkout of the Django repository. "
    "Given a bug report, find the product functions that the fix has to change. "
    "Use the tools to search and read code. Paths are relative to the repo root "
    "(for example django/db/models/query.py). Test code is never the answer. "
    "Be efficient: you have a limited tool budget. When you are confident, call "
    "submit with up to 10 functions, most likely first, written as "
    "path/to/file.py::Class.method or path/to/file.py::function."
)

BASE_TOOLS = [
    {
        "name": "search_code",
        "description": "Regex search (ripgrep) over the repo. Returns up to 30 'path:line: text' matches.",
        "input_schema": {
            "type": "object",
            "properties": {
                "pattern": {"type": "string"},
                "path": {"type": "string", "description": "optional subdirectory or file, e.g. django/forms"},
            },
            "required": ["pattern"],
        },
    },
    {
        "name": "read_file",
        "description": "Read lines of a file, at most 120 lines per call.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "start": {"type": "integer"},
                "end": {"type": "integer"},
            },
            "required": ["path"],
        },
    },
    {
        "name": "list_dir",
        "description": "List a directory.",
        "input_schema": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]},
    },
    {
        "name": "submit",
        "description": "Final answer. Functions most likely first, at most 10.",
        "input_schema": {
            "type": "object",
            "properties": {"functions": {"type": "array", "items": {"type": "string"}}},
            "required": ["functions"],
        },
    },
]

LOCATE_FIRST = (
    " Start by calling locate_bug once with the bug report, then verify its hits in the code."
)

LOCATE_TOOL = {
    "name": "locate_bug",
    "description": (
        "RepoCortex MCP tool. Ranks Django functions for a bug report using a code graph "
        "learned from past fixes. Each hit has file, qualname, line, score, and the path that produced it."
    ),
    "input_schema": {
        "type": "object",
        "properties": {"report": {"type": "string"}, "k": {"type": "integer"}},
        "required": ["report"],
    },
}


class Repo:
    def __init__(self, path: Path):
        self.path = path.resolve()

    def _safe(self, rel: str) -> Path | None:
        target = (self.path / (rel or ".").lstrip("/")).resolve()
        if target != self.path and self.path not in target.parents:
            return None
        if ".git" in target.parts:
            return None
        return target

    def search(self, pattern: str, sub: str = "") -> str:
        target = self._safe(sub or ".")
        if target is None or not target.exists():
            return "error: bad path"
        cmd = ["rg", "-n", "--no-heading", "--max-columns", "200", "-g", "*.py", "-e", pattern, str(target)]
        try:
            out = subprocess.run(cmd, capture_output=True, text=True, timeout=20).stdout
        except subprocess.TimeoutExpired:
            return "error: search timed out"
        lines = [line.replace(str(self.path) + "/", "") for line in out.splitlines()]
        if not lines:
            return "no matches"
        more = f"\n... {len(lines) - SEARCH_HITS} more matches" if len(lines) > SEARCH_HITS else ""
        return "\n".join(lines[:SEARCH_HITS]) + more

    def read(self, rel: str, start: int | None, end: int | None) -> str:
        target = self._safe(rel)
        if target is None or not target.is_file():
            return "error: no such file"
        lines = target.read_text(encoding="utf-8", errors="replace").splitlines()
        start = max(1, _int(start, 1))
        end = _int(end, start + READ_LINES - 1)
        end = min(end, start + READ_LINES - 1, len(lines))
        body = "\n".join(f"{i}: {lines[i - 1]}" for i in range(start, end + 1))
        return f"{rel} lines {start}-{end} of {len(lines)}\n{body}"

    def listdir(self, rel: str) -> str:
        target = self._safe(rel)
        if target is None or not target.is_dir():
            return "error: no such directory"
        names = sorted(p.name + ("/" if p.is_dir() else "") for p in target.iterdir() if p.name != ".git")
        return "\n".join(names[:200])


def _int(value, default: int) -> int:
    match = re.search(r"-?\d+", str(value)) if value is not None else None
    return int(match.group(0)) if match else default


def task_prompt(task: dict) -> str:
    return (
        f"Bug report\n\nSummary:\n{(task.get('summary') or '').strip()}\n\n"
        f"Description:\n{(task.get('description') or '').strip()[:6000]}"
    )


def compact_hits(hits: list[dict]) -> list[dict]:
    return [
        {
            "rank": h["rank"],
            "file": h["file"],
            "qualname": h["qualname"],
            "line": h["line"],
            "score": h["score"],
            "path": (h.get("path") or "")[:160],
        }
        for h in hits
    ]


def http_json(url: str, body: dict, headers: dict, tries: int = 4) -> dict:
    data = json.dumps(body).encode("utf-8")
    for attempt in range(tries):
        request = urllib.request.Request(url, data=data, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=180) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as err:
            detail = err.read().decode("utf-8", "replace")[:400]
            if err.code in (429, 500, 502, 503, 529) and attempt < tries - 1:
                time.sleep(5 * (attempt + 1))
                continue
            raise RuntimeError(f"HTTP {err.code}: {detail}") from None
        except (urllib.error.URLError, TimeoutError):
            if attempt < tries - 1:
                time.sleep(5)
                continue
            raise
    raise RuntimeError("unreachable")


class Anthropic:
    def __init__(self, model: str):
        self.model = model
        self.key = os.environ["ANTHROPIC_API_KEY"].strip()

    def call(self, system: str, messages: list, tools: list, force_submit: bool) -> tuple[list, dict]:
        msgs = json.loads(json.dumps(messages))
        last = msgs[-1]
        if isinstance(last["content"], str):
            last["content"] = [{"type": "text", "text": last["content"]}]
        last["content"][-1]["cache_control"] = {"type": "ephemeral"}
        tool_list = json.loads(json.dumps(tools))
        tool_list[-1]["cache_control"] = {"type": "ephemeral"}
        body = {
            "model": self.model,
            "max_tokens": MAX_OUT,
            "system": system,
            "messages": msgs,
            "tools": tool_list,
        }
        if force_submit:
            # forced tool_choice is rejected while thinking is on, so ask in text instead
            body["tool_choice"] = {"type": "auto"}
        payload = http_json(
            "https://api.anthropic.com/v1/messages",
            body,
            {"x-api-key": self.key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
        )
        usage = payload.get("usage") or {}
        blocks = payload.get("content") or []
        return blocks, {
            "input": int(usage.get("input_tokens") or 0),
            "cache_write": int(usage.get("cache_creation_input_tokens") or 0),
            "cache_read": int(usage.get("cache_read_input_tokens") or 0),
            "output": int(usage.get("output_tokens") or 0),
        }


class OpenAICompat:
    """GMI endpoint. Converts the Anthropic-shaped transcript to OpenAI chat format."""

    def __init__(self, model: str):
        self.model = model
        self.key = os.environ["GMI_API_KEY"].strip()

    def call(self, system: str, messages: list, tools: list, force_submit: bool) -> tuple[list, dict]:
        chat = [{"role": "system", "content": system}]
        for msg in messages:
            content = msg["content"]
            if isinstance(content, str):
                chat.append({"role": msg["role"], "content": content})
                continue
            if msg["role"] == "assistant":
                text = "".join(b.get("text", "") for b in content if b["type"] == "text")
                calls = [
                    {"id": b["id"], "type": "function", "function": {"name": b["name"], "arguments": json.dumps(b["input"])}}
                    for b in content
                    if b["type"] == "tool_use"
                ]
                item = {"role": "assistant", "content": text or None}
                if calls:
                    item["tool_calls"] = calls
                chat.append(item)
            else:
                for b in content:
                    if b["type"] == "tool_result":
                        chat.append({"role": "tool", "tool_call_id": b["tool_use_id"], "content": b["content"]})
                    elif b["type"] == "text":
                        chat.append({"role": "user", "content": b["text"]})
        body = {
            "model": self.model,
            "max_tokens": MAX_OUT * 3,
            "messages": chat,
            "tools": [
                {"type": "function", "function": {"name": t["name"], "description": t["description"], "parameters": t["input_schema"]}}
                for t in tools
            ],
        }
        if force_submit:
            body["tool_choice"] = {"type": "function", "function": {"name": "submit"}}
        payload = http_json(
            "https://api.gmi-serving.com/v1/chat/completions",
            body,
            {"Authorization": f"Bearer {self.key}", "content-type": "application/json"},
        )
        choice = (payload.get("choices") or [{}])[0].get("message") or {}
        blocks = []
        if choice.get("content"):
            blocks.append({"type": "text", "text": choice["content"]})
        for call in choice.get("tool_calls") or []:
            try:
                args = json.loads(call["function"].get("arguments") or "{}")
            except json.JSONDecodeError:
                args = {}
            blocks.append({"type": "tool_use", "id": call["id"], "name": call["function"]["name"], "input": args})
        usage = payload.get("usage") or {}
        cached = int(((usage.get("prompt_tokens_details") or {}).get("cached_tokens")) or 0)
        return blocks, {
            "input": int(usage.get("prompt_tokens") or 0) - cached,
            "cache_write": 0,
            "cache_read": cached,
            "output": int(usage.get("completion_tokens") or 0),
        }


def cost_of(usage: dict, model: str) -> float:
    price = PRICES.get(model)
    if not price:
        return 0.0
    return (
        usage["input"] * price["in"]
        + usage["output"] * price["out"]
        + usage["cache_write"] * price["cache_write"]
        + usage["cache_read"] * price["cache_read"]
    ) / 1e6


def run_issue(task: dict, condition: str, client, repo: Repo, ranker, locate_first: bool = False) -> dict:
    tools = list(BASE_TOOLS)
    if condition == "with-mcp":
        tools = [LOCATE_TOOL] + tools
    messages: list = [{"role": "user", "content": task_prompt(task)}]
    usage = {"input": 0, "cache_write": 0, "cache_read": 0, "output": 0}
    calls: dict[str, int] = {}
    files_opened: list[str] = []
    answer: list[str] | None = None
    started = time.time()
    turns = 0
    stop = ""
    for turn in range(MAX_TURNS + 3):
        spent = usage["input"] + usage["cache_write"] + usage["cache_read"]
        force = turn >= MAX_TURNS or spent > INPUT_BUDGET
        if force and messages[-1]["role"] == "user" and isinstance(messages[-1]["content"], list):
            messages[-1]["content"].append(
                {"type": "text", "text": "Tool budget used up. Call submit now with your best answer, no other tool."}
            )
        system = SYSTEM + (LOCATE_FIRST if locate_first and ranker is not None else "")
        blocks, step = client.call(system, messages, tools, force)
        turns += 1
        for key in usage:
            usage[key] += step[key]
        uses = [b for b in blocks if b.get("type") == "tool_use"]
        clean = [
            {k: v for k, v in b.items() if k in ("type", "text", "id", "name", "input")}
            for b in blocks
            if b.get("type") in ("text", "tool_use")
        ]
        if not uses:
            text = "".join(b.get("text", "") for b in blocks if b.get("type") == "text")
            match = re.search(r"\{.*\}", text, flags=re.DOTALL)
            if match:
                try:
                    answer = list(json.loads(match.group(0)).get("functions") or [])
                except (json.JSONDecodeError, AttributeError):
                    answer = None
            if answer is None and not force:
                messages.append({"role": "assistant", "content": clean or [{"type": "text", "text": "..."}]})
                messages.append({"role": "user", "content": [{"type": "text", "text": "Call submit with your answer."}]})
                continue
            stop = "text"
            break
        messages.append({"role": "assistant", "content": clean})
        results = []
        for block in uses:
            name = block.get("name")
            args = block.get("input") or {}
            calls[name] = calls.get(name, 0) + 1
            if name == "submit":
                answer = [str(x) for x in (args.get("functions") or [])]
                body = "ok"
            elif name == "search_code":
                body = repo.search(str(args.get("pattern") or ""), str(args.get("path") or ""))
            elif name == "read_file":
                path = str(args.get("path") or "")
                if path not in files_opened:
                    files_opened.append(path)
                body = repo.read(path, args.get("start"), args.get("end"))
            elif name == "list_dir":
                body = repo.listdir(str(args.get("path") or ""))
            elif name == "locate_bug" and ranker is not None:
                from repocortex.serve.load import locate

                k = max(1, min(_int(args.get("k"), 10), 20))
                body = json.dumps({"hits": compact_hits(locate(ranker, str(args.get("report") or task_prompt(task)), k))})
            else:
                body = "error: unknown tool"
            results.append({"type": "tool_result", "tool_use_id": block["id"], "content": body})
        if answer is not None:
            stop = "submit"
            break
        messages.append({"role": "user", "content": results})
    return {
        "ticket": int(task["ticket"]),
        "functions": answer or [],
        "stop": stop or "turns",
        "turns": turns,
        "tool_calls": sum(v for k, v in calls.items() if k != "submit"),
        "calls_by_tool": calls,
        "files_opened": len(files_opened),
        "files": files_opened,
        "usage": usage,
        "wall_s": round(time.time() - started, 1),
    }


def score(tasks: list[dict], preds: list[dict], index: dict) -> tuple[dict, list[dict]]:
    """Pair runs with tasks by position. Runs are written in task order."""
    rows, per_issue = [], []
    for position, pred in enumerate(preds):
        task = tasks[pred.get("task_index", position)]
        if int(task["ticket"]) != int(pred["ticket"]):
            raise SystemExit(f"run {position} is ticket {pred['ticket']}, task is {task['ticket']}")
        ranked, files = [], []
        for name in pred["functions"]:
            text = str(name).replace(":", "::", 1) if "::" not in str(name) and ".py:" in str(name) else str(name)
            uid = resolve_name(text, index)
            if uid and uid not in ranked:
                ranked.append(uid)
                files.append((index["uid"].get(uid) or {}).get("file") or "")
        gold = task["gold_functions"]
        rows.append({"ranked": ranked, "files": files, "gold": gold, "gold_files": task["gold_files"]})
        gold_set = set(gold)
        per_issue.append(
            {
                "ticket": int(task["ticket"]),
                "top1_hit": int(bool(ranked) and ranked[0] in gold_set),
                "any_gold_top5": int(bool(gold_set & set(ranked[:5]))),
                "file_top1_hit": int(bool(files) and files[0] in set(task["gold_files"])),
                "resolved": len(ranked),
                "named": len(pred["functions"]),
            }
        )
    summary = summarize(rows)
    summary["ci"] = bootstrap_ci(score_rows(rows)) if rows else {}
    return summary, per_issue


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)
    run = sub.add_parser("run")
    run.add_argument("--condition", choices=("with-mcp", "without-mcp"), required=True)
    run.add_argument("--provider", choices=("anthropic", "gmi"), default="anthropic")
    run.add_argument("--model", default=None)
    run.add_argument("--limit", type=int, default=15)
    run.add_argument("--offset", type=int, default=0)
    run.add_argument("--tag", default="")
    run.add_argument("--max-cost", type=float, default=4.0)
    run.add_argument("--locate-first", action="store_true", help="with-mcp only: tell the agent to call locate_bug first")
    sub.add_parser("report")
    sub.add_parser("tool-only", help="score locate_bug alone on the same tasks, no model")
    args = parser.parse_args()

    tasks = json.loads((OUT_DIR / "tasks.json").read_text())["tasks"]
    if args.cmd == "tool-only":
        tool_only(tasks)
        return
    if args.cmd == "report":
        build_report(tasks)
        return
    model = args.model or ("claude-sonnet-5-5" if args.provider == "anthropic" else "deepseek-ai/DeepSeek-V4-Pro")
    client = Anthropic(model) if args.provider == "anthropic" else OpenAICompat(model)
    repo = Repo(ROOT / "data" / "django")
    ranker = None
    if args.condition == "with-mcp":
        from repocortex.serve.load import load_ranker

        ranker = load_ranker(ROOT)
    tag = args.tag or args.provider
    out = OUT_DIR / f"runs-{tag}-{args.condition}.json"
    done = json.loads(out.read_text())["runs"] if out.exists() else []
    spent = sum(r.get("cost_usd", 0) for r in done)
    # runs are stored in task order, so resume by position (a ticket can appear twice)
    for position in range(args.offset + len(done), args.offset + args.limit):
        if position >= len(tasks):
            break
        task = tasks[position]
        if spent > args.max_cost:
            print(f"stopping: cost {spent:.3f} over cap {args.max_cost}")
            break
        result = run_issue(task, args.condition, client, repo, ranker, args.locate_first)
        result["task_index"] = position
        result["model"] = model
        result["cost_usd"] = round(cost_of(result["usage"], model), 5)
        spent += result["cost_usd"]
        done.append(result)
        label = args.condition + ("-first" if args.locate_first else "")
        out.write_text(json.dumps({"condition": label, "model": model, "runs": done}, indent=2))
        print(
            f"ticket={task['ticket']} calls={result['tool_calls']} files={result['files_opened']} "
            f"cost=${result['cost_usd']:.4f} total=${spent:.3f} wall={result['wall_s']}s stop={result['stop']} "
            f"pred={result['functions'][:2]} gold={task['gold_functions'][:2]}",
            flush=True,
        )


def tool_only(tasks: list[dict]) -> None:
    from repocortex.serve.load import load_ranker, locate

    ranker = load_ranker(ROOT)
    rows, top1, any5, file1 = [], 0, 0, 0
    for task in tasks:
        hits = locate(ranker, task_prompt(task), 10)
        ranked = [h["uid"] for h in hits]
        files = [h["file"] for h in hits]
        gold = set(task["gold_functions"])
        rows.append({"ranked": ranked, "files": files, "gold": task["gold_functions"], "gold_files": task["gold_files"]})
        top1 += int(bool(ranked) and ranked[0] in gold)
        any5 += int(bool(gold & set(ranked[:5])))
        file1 += int(bool(files) and files[0] in set(task["gold_files"]))
    n = max(len(tasks), 1)
    out = {
        "n": len(tasks),
        "localization": {"top1_function_hit": top1 / n, "any_gold_function_top5": any5 / n, "top1_file_hit": file1 / n},
        "strict": summarize(rows),
    }
    (OUT_DIR / "tool_only.json").write_text(json.dumps(out, indent=2))
    print(json.dumps(out["localization"]))


def build_report(tasks: list[dict]) -> None:
    corpus = json.loads((ROOT / "data" / "corpus.json").read_text())
    index = function_index(corpus["nodes"])
    report = {"conditions": {}}
    for path in sorted(OUT_DIR.glob("runs-*.json")):
        blob = json.loads(path.read_text())
        runs = blob["runs"]
        summary, per_issue = score(tasks, runs, index)
        n = len(runs)
        tot = lambda key: sum(r["usage"][key] for r in runs)  # noqa: E731
        name = path.stem.replace("runs-", "")
        report["conditions"][name] = {
            "condition": blob["condition"],
            "model": blob["model"],
            "n": n,
            "localization": {
                "top1_function_hit": sum(p["top1_hit"] for p in per_issue) / max(n, 1),
                "any_gold_function_top5": sum(p["any_gold_top5"] for p in per_issue) / max(n, 1),
                "top1_file_hit": sum(p["file_top1_hit"] for p in per_issue) / max(n, 1),
            },
            "strict": summary,
            "mean": {
                "input_tokens": (tot("input") + tot("cache_write") + tot("cache_read")) / max(n, 1),
                "uncached_input_tokens": (tot("input") + tot("cache_write")) / max(n, 1),
                "output_tokens": tot("output") / max(n, 1),
                "tool_calls": sum(r["tool_calls"] for r in runs) / max(n, 1),
                "locate_bug_calls": sum(r["calls_by_tool"].get("locate_bug", 0) for r in runs) / max(n, 1),
                "files_opened": sum(r["files_opened"] for r in runs) / max(n, 1),
                "turns": sum(r["turns"] for r in runs) / max(n, 1),
                "wall_s": sum(r["wall_s"] for r in runs) / max(n, 1),
                "cost_usd": sum(r["cost_usd"] for r in runs) / max(n, 1),
            },
            "total_cost_usd": sum(r["cost_usd"] for r in runs),
            "per_issue": [
                {**p, **{k: r[k] for k in ("tool_calls", "files_opened", "turns", "wall_s", "cost_usd", "stop")},
                 "tokens_in": r["usage"]["input"] + r["usage"]["cache_write"] + r["usage"]["cache_read"],
                 "tokens_out": r["usage"]["output"], "predicted": r["functions"][:5]}
                for p, r in zip(per_issue, runs)
            ],
        }
    tool_path = OUT_DIR / "tool_only.json"
    if tool_path.exists():
        report["locate_bug_alone"] = json.loads(tool_path.read_text())
    report["setup"] = {
        "tasks": "oldest 30 held-out Django fixes from results/agent_eval/tasks.json",
        "snapshot": "f24f38c6b282",
        "max_turns": MAX_TURNS,
        "input_budget_tokens": INPUT_BUDGET,
        "max_output_tokens_per_call": MAX_OUT,
        "prices_usd_per_mtok": PRICES,
    }
    (OUT_DIR / "results.json").write_text(json.dumps(report, indent=2))
    for name, item in report["conditions"].items():
        loc, mean = item["localization"], item["mean"]
        print(
            f"{name}: n={item['n']} top1fn={loc['top1_function_hit']:.2f} any5={loc['any_gold_function_top5']:.2f} "
            f"file1={loc['top1_file_hit']:.2f} acc5={item['strict']['function_acc@5']:.2f} "
            f"in={mean['input_tokens']:.0f} out={mean['output_tokens']:.0f} calls={mean['tool_calls']:.1f} "
            f"files={mean['files_opened']:.1f} wall={mean['wall_s']:.0f}s cost=${item['total_cost_usd']:.3f}"
        )


if __name__ == "__main__":
    main()
