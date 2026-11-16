"""Index a local, trusted source repository into a fresh, isolated output directory.

This reuses the same parser and corpus format as scripts/build_graph.py, but it
never touches the benchmark data (data/, results/), never writes to HydraDB, and
never clones or downloads anything. The result is a structural code graph and a
text corpus. With --embed --runtime it also writes empty serving state. It is
NOT a learned runtime: learned edges and issue memory only
exist after real fix history or feedback has been replayed.

Example:
    python scripts/index_repository.py --repo ~/src/myproject --out ~/rc-index/myproject
    python scripts/index_repository.py --repo ~/src/myproject --out /tmp/x --dry-run
    python scripts/index_repository.py --repo ~/src/myproject --out ~/rc-index/myproject --embed
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from repocortex.graph.builder import build_graph  # noqa: E402

# Directories that are never part of the project's own source.
EXCLUDED_DIRS = {
    ".git", ".hg", ".svn", ".venv", "venv", "env", ".env", ".tox", ".nox",
    "node_modules", "site-packages", "__pycache__", "build", "dist",
    ".next", ".turbo", "out", "coverage", "vendor", ".eggs", ".mypy_cache", ".pytest_cache", ".ruff_cache", ".idea", ".vscode",
}
# Names like build/ or env/ can be real packages when nested, so only skip them at top level.
NESTED_EXCLUDED_DIRS = EXCLUDED_DIRS - {"build", "dist", "env"}
MAX_FILE_BYTES = 2_000_000
FORMAT_VERSION = 1
LANGUAGE_SUFFIXES = {
    "python": {".py"}, "go": {".go"},
    "typescript": {".ts", ".tsx"}, "javascript": {".js", ".jsx", ".mjs", ".cjs"},
}

LIMITATIONS = [
    "Structural graph only: CONTAINS, DEFINES, IMPORTS, INHERITS, CALLS, TESTED_BY, "
    "MENTIONS and RAISES edges from static parsing. Call resolution is name-based and "
    "skips ambiguous targets.",
    "No CO_CHANGED edges: no commit/fix history was mined for this repository.",
    "No learned state: learned_state.json / learned_state.npz are not produced, so "
    "repocortex.serve.load.load_ranker cannot load this directory as a runtime, and no "
    "learned SHORTCUT/FIXED_IN edges or issue memory exist until history or feedback is replayed.",
    "No database writes: nothing was ingested into HydraDB or Bolt.",
    "Embeddings are only present if --embed was used; without them, only lexical/graph "
    "signals are available.",
    "Files that fail static parsing are skipped (counted in "
    "manifest.json). Migrations directories and vendored/virtualenv directories are skipped.",
]


class ValidationError(Exception):
    """Input that cannot be indexed; the message says how to fix it."""


def log(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


def _looks_remote(text: str) -> bool:
    lowered = text.strip().lower()
    return (
        "://" in lowered
        or lowered.startswith("git@")
        or (":" in lowered.split("/")[0] and not os.path.exists(text) and len(lowered.split(":")[0]) > 1)
    )


def _is_within(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def protected_paths(project_root: Path = PROJECT_ROOT) -> list[Path]:
    """Benchmark and runtime locations this command must never write into."""
    root = project_root.resolve()
    return [root / "data", root / "results", root / "repocortex", root / "scripts", root / "tests"]


def validate_repo(raw: str) -> Path:
    if _looks_remote(raw):
        raise ValidationError(
            f"--repo {raw!r} looks like a remote URL. This command never clones or downloads. "
            "Clone it yourself after reviewing it, then pass the local path."
        )
    repo = Path(raw).expanduser()
    if not repo.exists():
        raise ValidationError(f"--repo {repo} does not exist. Pass the path to a local checkout.")
    if not repo.is_dir():
        raise ValidationError(f"--repo {repo} is not a directory. Pass the repository root directory.")
    return repo.resolve()


def validate_out(raw: str, repo: Path, project_root: Path = PROJECT_ROOT) -> Path:
    out = Path(raw).expanduser().resolve()
    for protected in protected_paths(project_root):
        if out == protected or _is_within(out, protected) or _is_within(protected, out):
            raise ValidationError(
                f"--out {out} overlaps {protected}, which holds the benchmark/runtime. "
                "Choose a separate directory, e.g. ~/repocortex-indexes/<name>."
            )
    if out == project_root.resolve():
        raise ValidationError(f"--out {out} is the RepoCortex project root. Choose a separate directory.")
    if out == repo or _is_within(out, repo) or _is_within(repo, out):
        raise ValidationError(
            f"--out {out} overlaps the input repository {repo}. Choose a directory outside the repository "
            "so the index is never parsed as source and the repository is left untouched."
        )
    if out.exists():
        if not out.is_dir():
            raise ValidationError(f"--out {out} exists and is not a directory. Choose a new path.")
        if any(out.iterdir()):
            raise ValidationError(
                f"--out {out} already exists and is not empty. This command never overwrites; "
                "choose a new directory or remove the old one yourself."
            )
    if not out.parent.exists():
        raise ValidationError(f"parent of --out ({out.parent}) does not exist. Create it first.")
    return out


def parse_scope(value: str | None) -> tuple[str, ...] | None:
    if not value:
        return None
    parts = []
    for item in value.split(","):
        item = item.strip()
        if not item:
            continue
        if item.startswith("/") or ".." in Path(item).parts:
            raise ValidationError(f"--scope entry {item!r} must be a relative path inside the repository.")
        parts.append(item.rstrip("/"))
    if not parts:
        raise ValidationError("--scope is empty. Pass comma-separated directories, e.g. --scope src,tests.")
    return tuple(parts)


def detect_scope(repo: Path, suffixes: set[str] | None = None) -> tuple[str, ...]:
    """Top-level directories that contain selected source files, skipping tooling/vendor dirs."""
    suffixes = suffixes or {".py"}
    scope = []
    for child in sorted(repo.iterdir()):
        if not child.is_dir() or child.is_symlink():
            continue
        if child.name in EXCLUDED_DIRS or child.name.startswith("."):
            continue
        if any(p.suffix in suffixes for p in child.rglob("*") if p.is_file()):
            scope.append(child.name)
    return tuple(scope)


def _keep(repo: Path, relpath: str) -> bool:
    parts = Path(relpath).parts
    if not parts or parts[0] in EXCLUDED_DIRS or "migrations" in parts[:-1]:
        return False
    if any(part in NESTED_EXCLUDED_DIRS for part in parts[:-1]):
        return False
    path = repo / relpath
    try:
        if not _is_within(path.resolve(), repo):
            return False  # symlink escaping the repository
        if not path.is_file() or path.stat().st_size > MAX_FILE_BYTES:
            return False
    except OSError:
        return False
    return True


def collect_sources(repo: Path, scope: tuple[str, ...], include_root_files: bool,
                    max_files: int = 0, suffixes: set[str] | None = None) -> tuple[list[tuple[str, str]], int]:
    """Filter paths and bound file counts before reading source contents."""
    suffixes = suffixes or {".py"}
    for prefix in scope:
        base = repo / prefix
        if not base.is_dir() or not _is_within(base.resolve(), repo):
            raise ValidationError(f"--scope entry {prefix!r} is not a directory under {repo}.")
    def paths():
        for prefix in scope:
            yield from sorted(p for p in (repo / prefix).rglob("*") if p.suffix in suffixes)
        if include_root_files:
            yield from sorted(p for p in repo.iterdir() if p.suffix in suffixes)
    seen = set()
    kept = []
    skipped = 0
    for path in paths():
        relpath = path.relative_to(repo).as_posix()
        if relpath in seen:
            continue
        seen.add(relpath)
        if not _keep(repo, relpath):
            skipped += 1
            continue
        if max_files and len(kept) >= max_files:
            raise ValidationError(
                f"Source files exceed --max-files {max_files}. Narrow --scope or raise --max-files."
            )
        try:
            with path.open("rb") as source:
                raw = source.read(MAX_FILE_BYTES + 1)
        except OSError:
            skipped += 1
            continue
        if len(raw) > MAX_FILE_BYTES:
            skipped += 1
            continue
        kept.append((relpath, raw.decode("utf-8", errors="replace")))
    return kept, skipped


def name_repository(graph, name: str) -> None:
    """Replace the shared builder's historical root without changing benchmark code."""
    old_uid = "repo:django"
    node = graph.nodes.pop(old_uid)
    node.uid = "repo:" + name
    node.name = name
    graph.nodes[node.uid] = node
    remapped = {}
    for edge in graph.edges.values():
        if edge.src == old_uid:
            edge.src = node.uid
        if edge.dst == old_uid:
            edge.dst = node.uid
        remapped[(edge.src, edge.rel, edge.dst)] = edge
    graph.edges = remapped


def add_source_context(graph, files: list[tuple[str, str]]) -> None:
    """Keep bounded implementation text with each function in opt-in indexes."""
    lines = {path: text.splitlines() for path, text in files}
    for node in graph.by_label("Function"):
        source = lines.get(node.file, [])
        if not 0 < node.start <= node.end <= len(source):
            continue
        excerpt = "\n".join(source[node.start - 1:min(node.end, node.start + 79)])[:2000]
        node.doc = (node.doc + "\nImplementation:\n" + excerpt).strip()


def read_git_head(repo: Path) -> str:
    """Read HEAD from the .git directory without running git (no hooks, no config)."""
    head = repo / ".git" / "HEAD"
    try:
        text = head.read_text(encoding="utf-8").strip()
    except OSError:
        return ""
    if text.startswith("ref: "):
        ref = text[5:].strip()
        ref_path = repo / ".git" / ref
        try:
            return ref_path.read_text(encoding="utf-8").strip()
        except OSError:
            packed = repo / ".git" / "packed-refs"
            try:
                for line in packed.read_text(encoding="utf-8").splitlines():
                    if line.endswith(" " + ref):
                        return line.split(" ", 1)[0]
            except OSError:
                return ""
            return ""
    return text


def corpus_from_graph(graph) -> dict:
    """Same shape as data/corpus.json written by scripts/build_graph.py."""
    return {
        "nodes": {uid: node.as_row() | {"label": node.label} for uid, node in graph.nodes.items()},
        "edges": [
            {"src": src, "rel": rel, "dst": dst, "w": edge.w}
            for (src, rel, dst), edge in graph.edges.items()
        ],
    }


def graph_stats(graph) -> dict:
    labels: dict[str, int] = {}
    for node in graph.nodes.values():
        labels[node.label] = labels.get(node.label, 0) + 1
    rels: dict[str, int] = {}
    for edge in graph.edges.values():
        rels[edge.rel] = rels.get(edge.rel, 0) + 1
    return {"nodes": len(graph.nodes), "edges": len(graph.edges), "labels": labels, "relations": rels}


def write_embeddings(corpus: dict, path: Path, model_name: str | None) -> dict:
    """Optional local dense embeddings. Offline only: the model must already be cached."""
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    try:
        from repocortex.retrieve.dense import MODEL_NAME, Embedder, build_dense_index
    except ImportError as exc:  # numpy missing
        raise ValidationError(f"--embed needs numpy and sentence-transformers: {exc}") from exc
    name = model_name or MODEL_NAME
    try:
        embedder = Embedder(name)
    except ImportError as exc:
        raise ValidationError(
            "--embed needs sentence-transformers. Install the project dependencies "
            "(pip install -e .) or rerun without --embed."
        ) from exc
    except Exception as exc:
        raise ValidationError(
            f"could not load embedding model {name!r} offline ({type(exc).__name__}). "
            "This command does not download models; cache it first or rerun without --embed."
        ) from exc
    index = build_dense_index(corpus["nodes"], embedder, cache=path)
    return {"model": name, "functions": len(index.uids), "dim": int(index.matrix.shape[1]) if len(index.uids) else 0}


def run(args: argparse.Namespace) -> dict:
    started = time.time()
    steps = 5 if args.embed else 4
    log(f"[1/{steps}] validating inputs")
    if args.max_files < 0:
        raise ValidationError("--max-files must be zero or positive")
    if args.runtime:
        if not args.embed:
            raise ValidationError("--runtime requires --embed to produce a searchable runtime")
        from repocortex.retrieve.dense import MODEL_NAME
        if args.model and args.model != MODEL_NAME:
            raise ValidationError(f"--runtime supports only the serving model {MODEL_NAME!r}")
    repo = validate_repo(args.repo)
    out = validate_out(args.out, repo)
    languages = getattr(args, "languages", ["python"])
    suffixes = set().union(*(LANGUAGE_SUFFIXES[name] for name in languages))
    scope = parse_scope(args.scope)
    auto_scope = scope is None
    if auto_scope:
        scope = detect_scope(repo, suffixes)
    has_root_sources = auto_scope and any(p.is_file() and p.suffix in suffixes for p in repo.iterdir())
    if not scope and not has_root_sources:
        raise ValidationError(
            f"no selected-language files found under {repo} (skipping {', '.join(sorted(EXCLUDED_DIRS)[:6])}, ...). "
            "Pass --scope with the directories that contain your source."
        )
    log(f"      repo={repo}")
    log(f"      scope={','.join(scope) or '(root files only)'}{' (auto-detected)' if auto_scope else ''}")
    log(f"      out={out}")

    log(f"[2/{steps}] reading selected source files")
    files, skipped = collect_sources(repo, scope, include_root_files=has_root_sources, max_files=args.max_files, suffixes=suffixes)
    if not files:
        raise ValidationError(
            f"no indexable source files in scope {scope} under {repo}. Check --scope; migrations, "
            "virtualenv/vendor directories and files over 2 MB are skipped."
        )
    log(f"      files={len(files)} skipped={skipped}")

    log(f"[3/{steps}] parsing graph with repocortex.graph.builder")
    graph = build_graph([(path, text) for path, text in files if Path(path).suffix == ".py"])
    other_files = [(path, text) for path, text in files if Path(path).suffix != ".py"]
    if other_files:
        try:
            from repocortex.graph.multilang import build_multilang_graph
            other = build_multilang_graph(other_files)
        except ImportError as exc:
            raise ValidationError("Go/TypeScript/JavaScript parsing requires pip install -e '.[multilang]'") from exc
        graph.nodes.update(other.nodes)
        graph.edges.update(other.edges)
    if getattr(args, "source_context", False):
        add_source_context(graph, files)
    name_repository(graph, repo.name)
    stats = graph_stats(graph)
    parsed_files = stats["labels"].get("File", 0)
    unparsed = len(files) - parsed_files
    log(
        f"      nodes={stats['nodes']} edges={stats['edges']} functions={stats['labels'].get('Function', 0)} "
        f"unparseable_files={unparsed}"
    )
    if stats["labels"].get("Function", 0) == 0:
        log("      warning: no non-test functions found; rankers will have nothing to return")

    if args.runtime and stats["labels"].get("Function", 0) == 0:
        raise ValidationError("--runtime requires at least one non-test function to search")
    limitations = list(LIMITATIONS)
    if args.runtime:
        limitations = [item for item in limitations if not item.startswith("No learned state:")]
        limitations.append("Untrained runtime: serving state starts with zero learned edges and zero issue memories. "
                            "Structural search can run offline; live HydraDB ingestion and confirmed-fix learning are separate steps.")
    if other_files:
        limitations.append("Go/TypeScript/JavaScript use Tree-sitter declarations and unambiguous same-file direct calls only; imports, inheritance and dynamic calls are not resolved.")
    manifest = {
        "format_version": FORMAT_VERSION,
        "kind": "repocortex-untrained-runtime" if args.runtime else "repocortex-structural-index",
        "runtime_ready": bool(args.runtime),
        "training_reports": 0,
        "learned_runtime": False,
        "db_writes": False,
        "repo": str(repo),
        "git_head": read_git_head(repo),
        "scope": list(scope),
        "languages": languages,
        "source_context": bool(getattr(args, "source_context", False)),
        "auto_scope": auto_scope,
        "files_indexed": len(files),
        "files_skipped": skipped,
        "files_unparseable": unparsed,
        "graph": stats,
        "embeddings": None,
        "outputs": ["manifest.json", "data/corpus.json", "results/graph_stats.json"],
        "limitations": limitations,
    }
    if args.dry_run:
        log("dry run: nothing written")
        manifest["dry_run"] = True
        return manifest

    log(f"[4/{steps}] writing corpus to a staging directory")
    staging = Path(tempfile.mkdtemp(prefix=f".{out.name}.partial-", dir=out.parent))
    try:
        (staging / "data").mkdir()
        (staging / "results").mkdir()
        corpus = corpus_from_graph(graph)
        (staging / "data" / "corpus.json").write_text(json.dumps(corpus), encoding="utf-8")
        (staging / "results" / "graph_stats.json").write_text(json.dumps(stats, indent=2), encoding="utf-8")
        if args.embed:
            log(f"[5/{steps}] embedding functions locally (offline)")
            manifest["embeddings"] = write_embeddings(corpus, staging / "data" / "embeddings.npz", args.model)
            manifest["outputs"].append("data/embeddings.npz")
            log(f"      embedded={manifest['embeddings']['functions']}")
        if args.runtime:
            import numpy as np
            if manifest["embeddings"]["dim"] != 384:
                raise ValidationError("serving model must produce 384-dimensional embeddings")
            (staging / "data" / "learned_state.json").write_text("[]\n", encoding="utf-8")
            np.savez(staging / "data" / "learned_state.npz",
                     vectors=np.empty((0, 384), dtype=np.float32),
                     tickets=np.empty(0, dtype=np.int64),
                     golds=np.empty(0, dtype="U1"))
            manifest["outputs"].extend(["data/learned_state.json", "data/learned_state.npz"])
        manifest["elapsed_seconds"] = round(time.time() - started, 2)
        (staging / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        # Final no-overwrite check, then move into place in one rename.
        if out.exists():
            if any(out.iterdir()):
                raise ValidationError(f"--out {out} was populated while indexing; refusing to overwrite.")
            out.rmdir()
        staging.rename(out)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    log(f"done: {out}")
    log("note: this is an untrained runtime" if args.runtime else
        "note: this is a structural index, not a learned runtime (see manifest.json limitations)")
    return manifest


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="index_repository.py",
        description=(
            "Parse a local, trusted source repository into a RepoCortex structural graph and corpus, "
            "written to a new directory separate from the benchmark data. No network, no git clone, "
            "no database writes. The output is NOT a learned runtime: there is no fix history, "
            "learned edges or issue memory until history or feedback is replayed."
        ),
        epilog="See docs/index-repository.md for outputs and limitations.",
    )
    parser.add_argument("--repo", required=True, help="path to a local checkout you trust (URLs are rejected)")
    parser.add_argument(
        "--out", required=True,
        help="new or empty output directory outside the repo and outside RepoCortex data/ and results/",
    )
    parser.add_argument(
        "--scope", default=None,
        help="comma-separated directories under --repo to parse (default: auto-detect top-level "
        "dirs with selected-language files, plus matching top-level files)",
    )
    parser.add_argument("--languages", nargs="+", choices=list(LANGUAGE_SUFFIXES), default=["python"],
                        help="languages to index; non-Python languages require the multilang extra")
    parser.add_argument("--source-context", action="store_true",
                        help="include up to 80 lines / 2000 characters of each function body in its search document")
    parser.add_argument("--max-files", type=int, default=20000, help="fail if more files than this (default 20000; 0 disables)")
    parser.add_argument("--dry-run", action="store_true", help="validate and parse, print the summary, write nothing")
    parser.add_argument(
        "--embed", action="store_true",
        help="also write data/embeddings.npz with a locally cached sentence-transformers model (offline only)",
    )
    parser.add_argument("--runtime", action="store_true",
                        help="with --embed, write empty serving state for untrained search; default model only")
    parser.add_argument("--model", default=None, help="embedding model name for --embed (default: the project model)")
    parser.add_argument("--json", action="store_true", help="print the manifest as JSON on stdout")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        manifest = run(args)
    except ValidationError as exc:
        log(f"error: {exc}")
        return 2
    if args.json:
        print(json.dumps(manifest, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
