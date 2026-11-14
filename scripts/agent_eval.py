"""Compare an agent with the RepoCortex MCP tools against the same agent without them.

prepare and score do not need a model key. run calls the Anthropic Messages API
and executes locate_bug locally for the with-mcp condition.

    python scripts/agent_eval.py prepare --n 30
    python scripts/agent_eval.py score --predictions results/agent_eval/predictions.json
    ANTHROPIC_API_KEY=... python scripts/agent_eval.py run --condition with-mcp
    ANTHROPIC_API_KEY=... python scripts/agent_eval.py run --condition without-mcp
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.request
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from repocortex.config import Settings
from repocortex.eval.metrics import bootstrap_ci, summarize
from repocortex.mine.dataset import load_dataset

LOCATE_TOOL = {
    "name": "locate_bug",
    "description": "Rank functions in the Django code graph for a bug report.",
    "input_schema": {
        "type": "object",
        "properties": {
            "report": {"type": "string"},
            "k": {"type": "integer"},
        },
        "required": ["report"],
    },
}


def task_prompt(task: dict) -> str:
    summary = (task.get("summary") or "").strip()
    description = (task.get("description") or "").strip()
    return (
        "You are locating the functions a Django bug touches.\n\n"
        f"Summary:\n{summary}\n\n"
        f"Description:\n{description}\n\n"
        'Reply with JSON only: {"functions": ["qualname or file path", ...]}. '
        "Put the most likely function first. At most 10 functions."
    )


def parse_functions(text: str) -> list[str]:
    raw = text or ""
    match = re.search(r"\{.*\}", raw, flags=re.DOTALL)
    if match:
        try:
            payload = json.loads(match.group(0))
        except json.JSONDecodeError:
            payload = None
        if isinstance(payload, dict) and isinstance(payload.get("functions"), list):
            return [str(item).strip() for item in payload["functions"] if str(item).strip()]
    names = []
    for line in raw.splitlines():
        line = line.strip().lstrip("-").strip()
        if line:
            names.append(line)
    return names[:10]


def function_index(nodes: dict) -> dict:
    by_uid = {}
    by_qual = defaultdict(list)
    by_file_name = defaultdict(list)
    by_name = defaultdict(list)
    for uid, node in nodes.items():
        if (node.get("label") or "") != "Function":
            continue
        by_uid[uid] = node
        qual = node.get("qualname") or ""
        name = node.get("name") or ""
        file = node.get("file") or ""
        if qual:
            by_qual[qual].append(uid)
        if file and name:
            by_file_name[(file, name)].append(uid)
        if name:
            by_name[name].append(uid)
    return {"uid": by_uid, "qual": by_qual, "file_name": by_file_name, "name": by_name}


def resolve_name(name: str, index: dict) -> str:
    text = (name or "").strip().strip("`")
    if not text:
        return ""
    if text in index["uid"]:
        return text
    if text in index["qual"] and len(index["qual"][text]) == 1:
        return index["qual"][text][0]
    if "::" in text:
        file, qual = text.split("::", 1)
        choices = [uid for uid in index["qual"].get(qual, []) if (index["uid"][uid].get("file") or "") == file]
        if len(choices) == 1:
            return choices[0]
    if ":" in text and not text.startswith("func:"):
        file, qual = text.split(":", 1)
        choices = [uid for uid in index["qual"].get(qual, []) if (index["uid"][uid].get("file") or "") == file]
        if len(choices) == 1:
            return choices[0]
        short = qual.rsplit(".", 1)[-1]
        named = index["file_name"].get((file, short), [])
        if len(named) == 1:
            return named[0]
    short = text.rsplit(".", 1)[-1]
    named = index["name"].get(short, [])
    unique = list(dict.fromkeys(named))
    if len(unique) == 1:
        return unique[0]
    return ""


def score_predictions(tasks: list[dict], predictions: list[dict], nodes: dict) -> dict:
    by_ticket = {int(item["ticket"]): item for item in predictions}
    index = function_index(nodes)
    rows = []
    unresolved = 0
    missing = 0
    for task in tasks:
        ticket = int(task["ticket"])
        pred = by_ticket.get(ticket)
        names = []
        if pred is None:
            missing += 1
        else:
            names = [str(item) for item in pred.get("functions") or []]
        ranked = []
        files = []
        for name in names:
            uid = resolve_name(name, index)
            if not uid:
                unresolved += 1
                continue
            if uid in ranked:
                continue
            ranked.append(uid)
            files.append((index["uid"].get(uid) or {}).get("file") or "")
        rows.append(
            {
                "ranked": ranked,
                "files": files,
                "gold": task["gold_functions"],
                "gold_files": task["gold_files"],
                "ticket": ticket,
            }
        )
    from repocortex.eval.metrics import score_rows

    summary = summarize(rows)
    scored = score_rows(rows)
    summary["ci"] = bootstrap_ci(scored)
    summary["unresolved_names"] = unresolved
    summary["missing_predictions"] = missing
    return summary


def prepare_tasks(dataset: dict, n: int) -> list[dict]:
    holdout = [issue for issue in dataset["issues"] if issue["split"] == "test"]
    holdout.sort(key=lambda item: (item["time"], item["ticket"]))
    chosen = holdout[:n] if n else holdout
    tasks = []
    for issue in chosen:
        tasks.append(
            {
                "ticket": int(issue["ticket"]),
                "time": int(issue["time"]),
                "summary": issue.get("summary") or issue.get("subject") or "",
                "description": issue.get("description") or "",
                "gold_functions": list(issue["gold_functions"]),
                "gold_files": list(issue["gold_files"]),
            }
        )
    return tasks


def _anthropic(messages: list, tools: list | None) -> dict:
    key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not key:
        raise RuntimeError("ANTHROPIC_API_KEY is not set")
    body = {
        "model": os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-5"),
        "max_tokens": 1024,
        "messages": messages,
    }
    if tools:
        body["tools"] = tools
    request = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=json.dumps(body).encode("utf-8"),
        headers={
            "x-api-key": key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=120) as response:
        return json.loads(response.read().decode("utf-8"))


def run_task(task: dict, condition: str, ranker=None) -> dict:
    messages = [{"role": "user", "content": task_prompt(task)}]
    tools = [LOCATE_TOOL] if condition == "with-mcp" else None
    text = ""
    tool_calls = 0
    for _turn in range(4):
        payload = _anthropic(messages, tools)
        content = payload.get("content") or []
        uses = [block for block in content if block.get("type") == "tool_use"]
        text = "".join(block.get("text") or "" for block in content if block.get("type") == "text")
        if not uses or condition != "with-mcp":
            break
        if ranker is None:
            raise RuntimeError("with-mcp needs a loaded ranker")
        from repocortex.serve.load import locate

        messages.append({"role": "assistant", "content": content})
        results = []
        for block in uses:
            tool_calls += 1
            arguments = block.get("input") or {}
            if block.get("name") == "locate_bug":
                report = arguments.get("report") or task_prompt(task)
                k = int(arguments.get("k") or 10)
                hits = locate(ranker, report, k)
                body = json.dumps({"hits": hits})
            else:
                body = json.dumps({"error": "unknown tool"})
            results.append({"type": "tool_result", "tool_use_id": block.get("id"), "content": body})
        messages.append({"role": "user", "content": results})
    return {"ticket": int(task["ticket"]), "functions": parse_functions(text), "tool_calls": tool_calls, "raw": text}


def _load_nodes(root: Path) -> dict:
    corpus = json.loads((root / "data" / "corpus.json").read_text(encoding="utf-8"))
    return corpus["nodes"]


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    settings = Settings.load(root)
    parser = argparse.ArgumentParser(description="with-mcp vs without-mcp agent eval")
    sub = parser.add_subparsers(dest="command", required=True)

    prep = sub.add_parser("prepare", help="write holdout tasks")
    prep.add_argument("--dataset", type=Path, default=settings.data_dir / "dataset.json")
    prep.add_argument("--n", type=int, default=30)
    prep.add_argument("--out", type=Path, default=settings.results_dir / "agent_eval" / "tasks.json")

    score = sub.add_parser("score", help="score a predictions file")
    score.add_argument("--tasks", type=Path, default=settings.results_dir / "agent_eval" / "tasks.json")
    score.add_argument("--predictions", type=Path, required=True)
    score.add_argument("--out", type=Path, default=settings.results_dir / "agent_eval" / "scores.json")

    run = sub.add_parser("run", help="call Claude. Needs ANTHROPIC_API_KEY.")
    run.add_argument("--condition", choices=("with-mcp", "without-mcp"), required=True)
    run.add_argument("--tasks", type=Path, default=settings.results_dir / "agent_eval" / "tasks.json")
    run.add_argument("--out", type=Path, default=None)
    run.add_argument("--limit", type=int, default=0, help="score only the first N tasks")

    args = parser.parse_args()
    if args.command == "prepare":
        dataset = load_dataset(args.dataset)
        tasks = prepare_tasks(dataset, args.n)
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps({"tasks": tasks}, indent=2), encoding="utf-8")
        print(f"wrote {len(tasks)} tasks to {args.out}")
        return
    if args.command == "score":
        tasks = json.loads(args.tasks.read_text(encoding="utf-8"))["tasks"]
        predictions = json.loads(args.predictions.read_text(encoding="utf-8"))
        if isinstance(predictions, dict):
            predictions = predictions.get("predictions") or []
        summary = score_predictions(tasks, predictions, _load_nodes(root))
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(summary, indent=2), encoding="utf-8")
        print(json.dumps({key: summary[key] for key in summary if key != "per_issue"}, indent=2))
        return
    if not os.environ.get("ANTHROPIC_API_KEY", "").strip():
        print("ANTHROPIC_API_KEY is not set, so the model was not called.")
        print("prepare and score work without a key.")
        print("With a key:")
        print("  ANTHROPIC_API_KEY=... python scripts/agent_eval.py run --condition with-mcp")
        print("  ANTHROPIC_API_KEY=... python scripts/agent_eval.py run --condition without-mcp")
        print("Optional: ANTHROPIC_MODEL (default claude-sonnet-4-5).")
        print("with-mcp loads data/corpus.json, data/embeddings.npz, and data/learned_state.npz.")
        return
    tasks = json.loads(args.tasks.read_text(encoding="utf-8"))["tasks"]
    if args.limit:
        tasks = tasks[: args.limit]
    ranker = None
    if args.condition == "with-mcp":
        from repocortex.serve.load import load_ranker

        ranker = load_ranker(root)
    predictions = []
    for index, task in enumerate(tasks, start=1):
        print(f"task {index}/{len(tasks)} ticket={task['ticket']}", flush=True)
        predictions.append(run_task(task, args.condition, ranker))
    out = args.out or (settings.results_dir / "agent_eval" / f"predictions-{args.condition}.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"condition": args.condition, "predictions": predictions}, indent=2), encoding="utf-8")
    summary = score_predictions(tasks, predictions, _load_nodes(root))
    summary_path = out.with_name(out.stem + "-scores.json")
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"wrote {out}")
    print(json.dumps({key: summary[key] for key in ("n", "function_acc@10", "mrr", "ci")}, indent=2))


if __name__ == "__main__":
    main()
