"""Replay train issues in time order and score the held-out set at checkpoints."""

from __future__ import annotations

from repocortex.eval.metrics import bootstrap_ci, score_issue, summarize
from repocortex.learn.base import Episode
from repocortex.learn.compress import PathCompressor
from repocortex.learn.credit import credit_and_debit
from repocortex.learn.gap import GapIngestor
from repocortex.learn.merge import EntityMerger
from repocortex.learn.reweight import EdgeReweighter

# Each learning mode stores the fix (FIXED_IN) and then turns operators on.
# Learning disabled does not store the fix, so that line matches step 0.
MODES = {
    "disabled": (),
    "reweight": ("reweight",),
    "shortcuts": ("reweight", "shortcuts"),
    "gap": ("reweight", "shortcuts", "gap"),
    "full": ("reweight", "shortcuts", "gap", "merge"),
}

LEARNED_RELS = {"SHORTCUT", "FIXED_IN", "SAME_AS", "REFINES"}


def checkpoint_steps(n: int, points: int = 15) -> list[int]:
    """Evenly spaced checkpoints from 0 through n, about `points` of them."""
    if n <= 0:
        return [0]
    points = max(2, int(points))
    raw = [int(round(i * n / (points - 1))) for i in range(points)]
    steps: list[int] = []
    for step in raw:
        step = max(0, min(n, step))
        if not steps or step != steps[-1]:
            steps.append(step)
    if steps[0] != 0:
        steps.insert(0, 0)
    if steps[-1] != n:
        steps.append(n)
    return steps


def _legacy_steps(n: int, every: int) -> list[int]:
    steps = [0]
    if n <= 0:
        return steps
    step = max(1, every)
    while step < n:
        steps.append(step)
        step += every
    if steps[-1] != n:
        steps.append(n)
    return steps


def _touched(key, props) -> bool:
    weight = float(props.get("w") or 1.0)
    return bool(
        props.get("learned")
        or key[1] in LEARNED_RELS
        or int(props.get("hits") or 0)
        or int(props.get("misses") or 0)
        or abs(weight - 1.0) > 1e-6
    )


def _edge_row(key, props) -> dict:
    return {
        "src": key[0],
        "rel": key[1],
        "dst": key[2],
        "w": round(float(props.get("w") or 1.0), 4),
        "hits": int(props.get("hits") or 0),
        "misses": int(props.get("misses") or 0),
    }


def make_operators(ranker, mode: str, lr: float, merger_every: int, decay: float = 0.08) -> list:
    enabled = set(MODES[mode])
    operators = []
    if "gap" in enabled:
        operators.append(GapIngestor(nodes=getattr(ranker, "nodes", {}), ranker=ranker))
    if "shortcuts" in enabled:
        operators.append(
            PathCompressor(
                min_support=int(getattr(ranker, "shortcut_min_support", 3) or 3),
                min_precision=float(getattr(ranker, "shortcut_min_precision", 0.4) or 0.4),
            )
        )
    if "merge" in enabled:
        operators.append(EntityMerger(ranker=ranker, every=merger_every))
    if "reweight" in enabled:
        operators.append(EdgeReweighter(lr=lr, decay=decay))
    return operators


def learn_one(ranker, issue: dict, operators: list):
    """Predict, then let the operators and the fix memory see the outcome."""
    pred = ranker.predict(issue, k=10)
    if not operators:
        return pred, []
    credit, debit, promoted = credit_and_debit(pred, issue["gold_functions"])
    episode = Episode(
        ticket=int(issue["ticket"]),
        seeds=list(pred.seeds),
        gold=list(issue["gold_functions"]),
        predicted=[hit.uid for hit in pred.hits],
        traversed=list(pred.traversed),
        credit=credit,
        debit=debit,
        concepts=list(pred.concepts),
        promoted=promoted,
        frontier=list(pred.frontier),
        gap_concepts=list(getattr(pred, "gap_concepts", []) or []),
    )
    extra = ranker.gold_concepts(issue["gold_functions"]) if hasattr(ranker, "gold_concepts") else []
    if extra:
        concepts = list(episode.concepts)
        for concept in extra:
            if concept not in concepts:
                concepts.append(concept)
        episode.concepts = concepts
    results = [op.on_outcome(ranker.edges, episode) for op in operators]
    if hasattr(ranker, "observe"):
        ranker.observe(issue)
    return pred, results


def replay(
    ranker,
    train: list[dict],
    holdout: list[dict],
    every: int = 40,
    lr: float = 0.25,
    mode: str = "full",
    points: int | None = None,
    record_prequential: bool = False,
    snapshots: bool = False,
    decay: float | None = None,
) -> dict:
    if mode not in MODES:
        raise ValueError(f"unknown replay mode {mode}")
    if decay is None:
        decay = float(getattr(ranker, "credit_decay", 0.08) or 0.0)
    operators = make_operators(ranker, mode, lr, merger_every=every, decay=decay)
    operator_totals = {op.name: 0 for op in operators}
    if hasattr(ranker, "prepare"):
        ranker.prepare(list(train) + list(holdout))
    steps = checkpoint_steps(len(train), points) if points else _legacy_steps(len(train), every)
    step_set = set(steps)
    curve = []
    provenance = []
    prequential = []
    snapshot_rows = []
    seen_weight: dict[tuple, float] = {}
    seen_modules: set[str] = set()
    seen_files: set[str] = set()

    def checkpoint(step: int, capture: bool) -> None:
        rows = []
        scored = []
        captured = []
        for issue in holdout:
            pred = ranker.predict(issue, k=10)
            ranked = [hit.uid for hit in pred.hits]
            files = [hit.file for hit in pred.hits]
            rows.append(
                {
                    "ranked": ranked,
                    "files": files,
                    "gold": issue["gold_functions"],
                    "gold_files": issue["gold_files"],
                    "ticket": int(issue["ticket"]),
                }
            )
            item = score_issue(ranked, files, issue["gold_functions"], issue["gold_files"])
            item["ticket"] = int(issue["ticket"])
            scored.append(item)
            if capture:
                gold = set(issue["gold_functions"])
                captured.append(
                    {
                        "ticket": int(issue["ticket"]),
                        "gold": list(issue["gold_functions"]),
                        "hits": [
                            {
                                "rank": rank,
                                "uid": hit.uid,
                                "file": hit.file,
                                "line": int((ranker.nodes.get(hit.uid) or {}).get("start") or 0),
                                "score": round(hit.score, 4),
                                "gold": hit.uid in gold,
                                "path": hit.path,
                            }
                            for rank, hit in enumerate(pred.hits[:5], start=1)
                        ],
                    }
                )
        metrics = summarize(rows)
        metrics["step"] = step
        metrics["ci"] = bootstrap_ci(scored)
        if operators:
            metrics["slices"] = _slices(rows, seen_modules, seen_files)
        curve.append(metrics)
        curve[-1]["_per_issue"] = scored
        print(
            f"  [{mode}] checkpoint {step} acc10={metrics['function_acc@10']:.4f} mrr={metrics['mrr']:.4f}",
            flush=True,
        )
        if capture:
            provenance.extend(captured)
        if snapshots:
            snapshot_rows.append(_snapshot(step, metrics, operator_totals, ranker, seen_weight))

    if not operators:
        checkpoint(0, False)
        if record_prequential:
            for index, issue in enumerate(train, start=1):
                pred = ranker.predict(issue, k=10)
                ranked = [hit.uid for hit in pred.hits]
                files = [hit.file for hit in pred.hits]
                item = score_issue(ranked, files, issue["gold_functions"], issue["gold_files"])
                item["ticket"] = int(issue["ticket"])
                item["index"] = index
                item["time"] = int(issue.get("time") or 0)
                prequential.append(item)
        for step in steps[1:]:
            row = {key: value for key, value in curve[0].items() if key != "_per_issue"}
            row["step"] = step
            curve.append(row)
    else:
        checkpoint(0, False)
        for index, issue in enumerate(train, start=1):
            if index % 50 == 0 or index == len(train):
                print(f"  [{mode}] replay {index}/{len(train)}", flush=True)
            pred, results = learn_one(ranker, issue, operators)
            for result in results:
                operator_totals[result.name] = operator_totals.get(result.name, 0) + result.applied
            if record_prequential:
                ranked = [hit.uid for hit in pred.hits]
                files = [hit.file for hit in pred.hits]
                item = score_issue(ranked, files, issue["gold_functions"], issue["gold_files"])
                item["ticket"] = int(issue["ticket"])
                item["index"] = index
                item["time"] = int(issue.get("time") or 0)
                prequential.append(item)
            seen_modules |= _areas(issue, 2)
            seen_files |= _areas(issue, 0)
            if index in step_set:
                if hasattr(ranker, "flush"):
                    ranker.flush()
                elif hasattr(ranker, "edges"):
                    ranker.edges.flush(getattr(ranker, "client", None))
                checkpoint(index, index == len(train))

    final_scores = []
    for row in curve:
        scores = row.pop("_per_issue", None)
        if scores is not None:
            final_scores = scores
    params = {}
    for name in (
        "bm25_mix",
        "memory_lam",
        "memory_thresh",
        "memory_k",
        "shortcut_lam",
        "graph_mix",
        "shortcut_min_support",
        "shortcut_min_precision",
        "memory_agg",
        "memory_frontier",
        "recency_half_life",
        "file_prior_lam",
        "module_prior_lam",
        "prior_seeds",
        "generalize_concepts",
        "credit_decay",
    ):
        if hasattr(ranker, name):
            params[name] = getattr(ranker, name)
    params["decay"] = decay
    return {
        "curve": curve,
        "operators": operator_totals,
        "provenance": provenance,
        "params": params,
        "lr": lr,
        "every": every,
        "mode": mode,
        "steps": steps,
        "per_issue": final_scores,
        "prequential": prequential,
        "snapshots": snapshot_rows,
    }


def _snapshot(step, metrics, operators, ranker, seen_weight: dict) -> dict:
    edges = getattr(ranker, "edges", None)
    table = getattr(edges, "edges", {}) if edges is not None else {}
    counts: dict[str, int] = {}
    new_edges = []
    new_count = 0
    weight_updates = 0
    for key, props in table.items():
        if not _touched(key, props):
            continue
        counts[key[1]] = counts.get(key[1], 0) + 1
        weight = round(float(props.get("w") or 1.0), 4)
        previous = seen_weight.get(key)
        if previous is None:
            new_count += 1
            if len(new_edges) < 400:
                new_edges.append(_edge_row(key, props))
            seen_weight[key] = weight
        elif previous != weight:
            weight_updates += 1
            seen_weight[key] = weight
    public = {key: value for key, value in metrics.items() if key != "_per_issue"}
    return {
        "step": step,
        "metrics": {key: value for key, value in public.items() if key != "ci"},
        "ci": public.get("ci") or {},
        "operators": dict(operators),
        "learned_edges": counts,
        "new_edge_count": new_count,
        "new_edges": new_edges,
        "weight_updates": weight_updates,
    }


def _areas(issue: dict, depth: int) -> set[str]:
    """Gold files when depth is 0, otherwise the first `depth` path parts."""
    found: set[str] = set()
    golds = issue.get("gold_functions") or issue.get("gold") or []
    for uid in golds:
        parts = str(uid).split(":", 2)
        if len(parts) < 2 or not parts[1]:
            continue
        if depth <= 0:
            found.add(parts[1])
            continue
        segs = [seg for seg in parts[1].split("/") if seg]
        if segs:
            found.add("/".join(segs[:depth]))
    return found


def _brief(rows: list[dict]) -> dict:
    if not rows:
        return {"n": 0, "function_acc@10": None, "mrr": None}
    metrics = summarize(rows)
    return {
        "n": metrics["n"],
        "function_acc@10": metrics["function_acc@10"],
        "mrr": metrics["mrr"],
    }


def _slices(rows: list[dict], seen_modules: set[str], seen_files: set[str]) -> dict:
    buckets = {
        "seen_module": [],
        "unseen_module": [],
        "seen_file": [],
        "unseen_file": [],
    }
    for row in rows:
        modules = _areas(row, 2)
        files = _areas(row, 0)
        buckets["seen_module" if modules & seen_modules else "unseen_module"].append(row)
        buckets["seen_file" if files & seen_files else "unseen_file"].append(row)
    return {name: _brief(group) for name, group in buckets.items()}


def rolling_mean(values: list[float], window: int) -> list[float]:
    if window < 1:
        window = 1
    out = []
    total = 0.0
    for index, value in enumerate(values):
        total += value
        if index >= window:
            total -= values[index - window]
        count = index + 1 if index < window else window
        out.append(total / count)
    return out
