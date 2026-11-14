"""Pick memory hyperparameters on a late slice of the training period.

The newest 20% of training issues is the validation slice. The fit replay
never sees those labels, and it never sees the holdout. The holdout similarity
numbers written to results/diagnosis.json are a diagnosis only. They are not
an input to the selection rule.

Selection, locked before any validation score is read:
score = 0.65 * final validation MRR + 0.35 * midpoint validation MRR.
A candidate is kept when its score beats the incumbent by more than 0.01
and its final validation Acc@10 is not more than 0.02 worse.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from repocortex.graph.export import load_corpus
from repocortex.learn.gap import module_of
from repocortex.learn.replay import replay
from repocortex.mine.dataset import load_dataset
from repocortex.retrieve.bm25 import BM25Index
from repocortex.retrieve.dense import Embedder, build_dense_index
from repocortex.retrieve.frozen import EdgeTable
from repocortex.retrieve.hybrid import HybridRanker, QueryCache
from repocortex.retrieve.textutil import issue_text

ROOT = Path(__file__).resolve().parents[1]
RULE = (
    "score = 0.65 * final validation MRR + 0.35 * midpoint validation MRR; "
    "keep a candidate only when score beats the incumbent by more than 0.01 "
    "and final validation Acc@10 is not more than 0.02 worse. "
    "The holdout is not scored here."
)

BASE = {
    "memory_lam": 0.08,
    "memory_thresh": 0.55,
    "memory_k": 5,
    "memory_agg": "sum",
    "recency_half_life": 0.0,
    "file_prior_lam": 0.0,
    "module_prior_lam": 0.0,
    "credit_decay": 0.08,
    "generalize_concepts": False,
    "shortcut_min_support": 3,
    "shortcut_lam": 0.04,
}


def _unit(vector: np.ndarray) -> np.ndarray:
    vector = np.asarray(vector, dtype=np.float32)
    norm = float(np.linalg.norm(vector))
    if norm > 0:
        vector = vector / norm
    return vector


def _gold_modules(issue: dict) -> set[str]:
    found = set()
    for uid in issue["gold_functions"]:
        parts = uid.split(":", 2)
        if len(parts) >= 2:
            found.add(module_of(parts[1]))
    return found


def diagnose(train: list[dict], test: list[dict], embedder) -> dict:
    state = np.load(ROOT / "data" / "learned_state.npz", allow_pickle=False)
    by_ticket = {
        int(ticket): _unit(state["vectors"][index])
        for index, ticket in enumerate(state["tickets"].tolist())
    }
    matrix = []
    golds = []
    for issue in train:
        matrix.append(by_ticket[int(issue["ticket"])])
        golds.append(set(issue["gold_functions"]))
    matrix = np.vstack(matrix)
    print(f"encoding {len(test)} holdout issues for the diagnosis", flush=True)
    queries = embedder.encode([issue_text(issue) for issue in test])
    queries = np.asarray([_unit(row) for row in queries], dtype=np.float32)
    sims = queries @ matrix.T
    qgold = [set(issue["gold_functions"]) for issue in test]
    rows = []
    print("diagnosis (not used for selection)", flush=True)
    for end in (0, 100, 200, 400, 600, 800, 1000, matrix.shape[0]):
        if end == 0:
            maxsim = np.zeros(len(test))
            best_overlap = 0.0
            any_overlap = 0.0
        else:
            block = sims[:, :end]
            maxsim = block.max(axis=1)
            best = block.argmax(axis=1)
            best_hit = 0
            any_hit = 0
            for index in range(len(test)):
                if qgold[index] & golds[int(best[index])]:
                    best_hit += 1
                for neighbor in np.where(block[index] >= 0.55)[0]:
                    if qgold[index] & golds[int(neighbor)]:
                        any_hit += 1
                        break
            best_overlap = best_hit / len(test)
            any_overlap = any_hit / len(test)
        row = {
            "step": int(end),
            "sim_at_least_0.55": round(float((maxsim >= 0.55).mean()), 4),
            "sim_at_least_0.45": round(float((maxsim >= 0.45).mean()), 4),
            "median_max_sim": round(float(np.median(maxsim)), 4),
            "nearest_gold_overlap": round(float(best_overlap), 4),
            "any_neighbor_0.55_gold_overlap": round(float(any_overlap), 4),
        }
        rows.append(row)
        print(
            f"  step {end:4d}  sim>=.55 {row['sim_at_least_0.55']:.3f}"
            f"  nearest gold {row['nearest_gold_overlap']:.3f}"
            f"  any gold {row['any_neighbor_0.55_gold_overlap']:.3f}",
            flush=True,
        )
    return {"holdout": len(test), "train": len(train), "rows": rows, "used_for_selection": False}


def _score(row: dict) -> float:
    return 0.65 * float(row["mrr"]) + 0.35 * float(row["mid_mrr"])


def accept(challenger: dict, incumbent: dict) -> bool:
    if challenger["acc"] < incumbent["acc"] - 0.02:
        return False
    return _score(challenger) > _score(incumbent) + 0.01


def _eligible_leader(rows: list[dict]) -> dict:
    best_acc = max(row["acc"] for row in rows)
    eligible = [row for row in rows if row["acc"] >= best_acc - 0.02]
    return max(eligible, key=_score)


def _grid() -> list[dict]:
    rows = []
    for lam in (0.08, 0.22, 0.40):
        for thresh in (0.50, 0.62):
            for agg in ("sum", "max"):
                for k in (5, 15):
                    rows.append({**BASE, "memory_lam": lam, "memory_thresh": thresh, "memory_agg": agg, "memory_k": k})
    rows.append({**BASE, "memory_lam": 0.30, "memory_thresh": 0.55, "memory_agg": "max", "memory_k": 20})
    rows.append({**BASE, "memory_lam": 0.50, "memory_thresh": 0.70, "memory_agg": "max", "memory_k": 5})
    # File and module priors are in the search from the start. Counts exist
    # before a text neighbor shares the gold function, which is the early-rise lever.
    for file_lam in (0.10, 0.20):
        rows.append({**BASE, "memory_lam": 0.22, "memory_agg": "max", "memory_k": 15, "file_prior_lam": file_lam})
    rows.append({**BASE, "memory_lam": 0.22, "memory_agg": "max", "memory_k": 15, "module_prior_lam": 0.08})
    return rows


def _dedupe(rows: list[dict]) -> list[dict]:
    seen = set()
    out = []
    for row in rows:
        key = tuple(sorted((name, str(value)) for name, value in row.items()))
        if key in seen:
            continue
        seen.add(key)
        out.append(row)
    return out


def main() -> None:
    started = time.time()
    dataset = load_dataset(ROOT / "data" / "dataset.json")
    train = [issue for issue in dataset["issues"] if issue["split"] == "train"]
    test = [issue for issue in dataset["issues"] if issue["split"] == "test"]
    train.sort(key=lambda issue: (int(issue["time"]), int(issue["ticket"])))
    test.sort(key=lambda issue: (int(issue["time"]), int(issue["ticket"])))
    if train and test and int(train[-1]["time"]) > int(test[0]["time"]):
        raise SystemExit("training issues are not all older than the holdout")
    cut = len(train) - max(1, int(round(len(train) * 0.2)))
    fit, val = train[:cut], train[cut:]
    print(f"fit={len(fit)} val={len(val)} holdout={len(test)} (holdout not scored)", flush=True)

    print("loading corpus", flush=True)
    nodes, edges = load_corpus(ROOT / "data" / "corpus.json")
    print(f"corpus nodes={len(nodes)} edges={len(edges)}", flush=True)
    bm25 = BM25Index.from_nodes(nodes)
    embedder = Embedder()
    dense = build_dense_index(nodes, embedder, ROOT / "data" / "embeddings.npz")
    diagnosis = diagnose(train, test, embedder)
    (ROOT / "results" / "diagnosis.json").write_text(json.dumps(diagnosis, indent=2), encoding="utf-8")

    state = np.load(ROOT / "data" / "learned_state.npz", allow_pickle=False)
    shared: dict[int, np.ndarray] = {}
    for index, ticket in enumerate(state["tickets"].tolist()):
        shared[int(ticket)] = _unit(state["vectors"][index])
    cache = QueryCache()

    def evaluate(params: dict, mode: str) -> dict:
        fresh_nodes = {uid: dict(node) for uid, node in nodes.items()}
        ranker = HybridRanker(fresh_nodes, EdgeTable(edges), bm25, dense, embedder, client=None)
        for name, value in params.items():
            setattr(ranker, name, value)
        ranker._vec = shared
        ranker.score_cache = cache
        t0 = time.time()
        played = replay(ranker, fit, val, every=40, mode=mode, points=3)
        curve = played["curve"]
        mid = curve[len(curve) // 2]
        end = curve[-1]
        row = {
            "mode": mode,
            "params": params,
            "step0_acc": curve[0]["function_acc@10"],
            "step0_mrr": curve[0]["mrr"],
            "mid_step": mid["step"],
            "mid_acc": mid["function_acc@10"],
            "mid_mrr": mid["mrr"],
            "acc": end["function_acc@10"],
            "mrr": end["mrr"],
            "seconds": round(time.time() - t0, 1),
        }
        row["selection_score"] = round(_score(row), 6)
        print(
            f"  {mode} score={row['selection_score']:.4f} "
            f"acc {row['step0_acc']:.3f}->{row['mid_acc']:.3f}->{row['acc']:.3f} "
            f"mrr {row['step0_mrr']:.3f}->{row['mid_mrr']:.3f}->{row['mrr']:.3f} "
            f"({row['seconds']}s) {params['memory_agg']} lam={params['memory_lam']} "
            f"k={params['memory_k']} thr={params['memory_thresh']} "
            f"file={params['file_prior_lam']} mod={params['module_prior_lam']}",
            flush=True,
        )
        return row

    trials = []
    print("validation grid on reweight mode", flush=True)
    for params in _dedupe(_grid()):
        trials.append(evaluate(params, "reweight"))

    leader = _eligible_leader(trials)
    print(
        f"grid leader score={leader['selection_score']:.4f} acc={leader['acc']:.3f} mrr={leader['mrr']:.3f}",
        flush=True,
    )

    # Confirm the leader and the phase-3 baseline under the full operator set.
    confirm_params = [BASE, leader["params"]]
    for row in sorted(trials, key=_score, reverse=True)[:3]:
        confirm_params.append(row["params"])
    print("confirming finalists on the full operator set", flush=True)
    confirmed = []
    for params in _dedupe(confirm_params):
        confirmed.append(evaluate(params, "full"))
    winner = _eligible_leader(confirmed)
    baseline_full = next(row for row in confirmed if row["params"] == BASE)
    if not accept(winner, baseline_full):
        winner = baseline_full
        print("full-mode leader did not clear the baseline margin; keeping phase-3 params", flush=True)

    addons = [
        {"file_prior_lam": 0.10},
        {"file_prior_lam": 0.20},
        {"module_prior_lam": 0.08},
        {"recency_half_life": 250.0},
        {"recency_half_life": 600.0},
        {"credit_decay": 0.02},
        {"generalize_concepts": True},
        {"shortcut_min_support": 2},
        {"shortcut_lam": 0.10},
    ]
    print("trying one add-on at a time on the full replay", flush=True)
    for patch in addons:
        params = {**winner["params"], **patch}
        row = evaluate(params, "full")
        confirmed.append(row)
        if accept(row, winner):
            print(f"  kept {patch}", flush=True)
            winner = row
        else:
            print(f"  rejected {patch}", flush=True)

    payload = {
        "rule": RULE,
        "fit": len(fit),
        "validation": len(val),
        "holdout_scored": False,
        "chosen": winner["params"],
        "chosen_validation": {
            "step0_acc": winner["step0_acc"],
            "step0_mrr": winner["step0_mrr"],
            "mid_acc": winner["mid_acc"],
            "mid_mrr": winner["mid_mrr"],
            "acc": winner["acc"],
            "mrr": winner["mrr"],
            "selection_score": winner["selection_score"],
        },
        "grid": [
            {
                "mode": row["mode"],
                "selection_score": row["selection_score"],
                "acc": row["acc"],
                "mrr": row["mrr"],
                "mid_acc": row["mid_acc"],
                "mid_mrr": row["mid_mrr"],
                "params": row["params"],
            }
            for row in trials
        ],
        "confirmed": [
            {
                "mode": row["mode"],
                "selection_score": row["selection_score"],
                "acc": row["acc"],
                "mrr": row["mrr"],
                "mid_acc": row["mid_acc"],
                "mid_mrr": row["mid_mrr"],
                "params": row["params"],
            }
            for row in confirmed
        ],
    }
    (ROOT / "results" / "tuning.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"chose {json.dumps(winner['params'])}", flush=True)
    print(f"wrote results/tuning.json in {time.time() - started:.0f}s", flush=True)


if __name__ == "__main__":
    main()
