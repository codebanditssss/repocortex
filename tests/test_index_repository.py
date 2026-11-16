import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from repocortex.graph.export import load_corpus  # noqa: E402
from scripts import index_repository as ix  # noqa: E402


PKG = '''
class Store:
    """Keep rows in memory."""

    def save_record(self, row):
        """Persist one record."""
        self._validate_record(row)
        return row

    def _validate_record(self, row):
        if not row:
            raise ValueError("record must not be empty here")
'''

USES = '''
from shop.store import Store


def checkout_order(order):
    """Checkout an order."""
    return Store().save_record(order)
'''

TESTS = '''
from shop.api import checkout_order


def test_checkout_order():
    assert checkout_order({"id": 1})
'''


def make_repo(base: Path) -> Path:
    repo = base / "sample"
    (repo / "shop").mkdir(parents=True)
    (repo / "shop" / "__init__.py").write_text("")
    (repo / "shop" / "store.py").write_text(PKG)
    (repo / "shop" / "api.py").write_text(USES)
    (repo / "shop" / "broken.py").write_text("def nope(:\n")
    (repo / "shop" / "migrations").mkdir()
    (repo / "shop" / "migrations" / "0001.py").write_text("def migrate_rows():\n    pass\n")
    (repo / "tests").mkdir()
    (repo / "tests" / "test_api.py").write_text(TESTS)
    (repo / ".venv" / "lib").mkdir(parents=True)
    (repo / ".venv" / "lib" / "vendored.py").write_text("def vendored_helper():\n    pass\n")
    (repo / "shop" / "node_modules").mkdir()
    (repo / "shop" / "node_modules" / "x.py").write_text("def nested_vendor():\n    pass\n")
    (repo / "setup.py").write_text("def configure_package():\n    pass\n")
    (repo / ".git").mkdir()
    (repo / ".git" / "HEAD").write_text("ref: refs/heads/main\n")
    (repo / ".git" / "refs" / "heads").mkdir(parents=True)
    (repo / ".git" / "refs" / "heads" / "main").write_text("a" * 40 + "\n")
    return repo


def run_cli(*argv: str) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = ix.main(list(argv))
    return code, out.getvalue(), err.getvalue()


class IndexRepositoryTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.repo = make_repo(self.base)
        self.out = self.base / "index"

    def tearDown(self):
        self.tmp.cleanup()

    def test_indexes_repo_into_fresh_directory(self):
        code, stdout, stderr = run_cli("--repo", str(self.repo), "--out", str(self.out), "--json")
        self.assertEqual(code, 0, stderr)
        self.assertIn("[1/4] validating inputs", stderr)
        self.assertIn("not a learned runtime", stderr)
        self.assertEqual(
            sorted(p.relative_to(self.out).as_posix() for p in self.out.rglob("*") if p.is_file()),
            ["data/corpus.json", "manifest.json", "results/graph_stats.json"],
        )
        # The corpus loads through the same reader the rest of the project uses.
        nodes, edges = load_corpus(self.out / "data" / "corpus.json")
        functions = {n["name"] for n in nodes.values() if n["label"] == "Function"}
        self.assertEqual(functions, {"save_record", "_validate_record", "checkout_order", "configure_package"})
        self.assertNotIn("vendored_helper", functions)
        self.assertNotIn("nested_vendor", functions)
        self.assertNotIn("migrate_rows", functions)
        rels = {rel for _, rel, _ in edges}
        self.assertTrue({"CALLS", "DEFINES", "IMPORTS", "TESTED_BY", "RAISES"} <= rels)
        self.assertNotIn("CO_CHANGED", rels)

        manifest = json.loads((self.out / "manifest.json").read_text())
        self.assertEqual(manifest, json.loads(stdout) | {"elapsed_seconds": manifest["elapsed_seconds"]})
        self.assertFalse(manifest["learned_runtime"])
        self.assertFalse(manifest["db_writes"])
        self.assertIsNone(manifest["embeddings"])
        self.assertEqual(manifest["git_head"], "a" * 40)
        self.assertEqual(manifest["scope"], ["shop", "tests"])
        self.assertEqual(manifest["files_unparseable"], 1)
        self.assertGreaterEqual(manifest["files_skipped"], 1)
        self.assertTrue(any("learned_state" in item for item in manifest["limitations"]))
        # No staging directory is left behind.
        self.assertEqual(sorted(p.name for p in self.base.iterdir()), ["index", "sample"])

    def test_explicit_scope_limits_parsing(self):
        code, stdout, stderr = run_cli(
            "--repo", str(self.repo), "--out", str(self.out), "--scope", "tests", "--dry-run", "--json"
        )
        self.assertEqual(code, 0, stderr)
        manifest = json.loads(stdout)
        self.assertEqual(manifest["scope"], ["tests"])
        self.assertEqual(manifest["graph"]["labels"].get("Function", 0), 0)
        self.assertIn("no non-test functions", stderr)

    def test_dry_run_writes_nothing(self):
        code, stdout, stderr = run_cli("--repo", str(self.repo), "--out", str(self.out), "--dry-run")
        self.assertEqual(code, 0, stderr)
        self.assertIn("dry run: nothing written", stderr)
        self.assertFalse(self.out.exists())

    def test_never_overwrites_existing_output(self):
        self.out.mkdir()
        (self.out / "corpus.json").write_text("keep me")
        code, _, stderr = run_cli("--repo", str(self.repo), "--out", str(self.out))
        self.assertEqual(code, 2)
        self.assertIn("never overwrites", stderr)
        self.assertEqual((self.out / "corpus.json").read_text(), "keep me")

    def test_empty_existing_directory_is_accepted(self):
        self.out.mkdir()
        code, _, stderr = run_cli("--repo", str(self.repo), "--out", str(self.out))
        self.assertEqual(code, 0, stderr)
        self.assertTrue((self.out / "data" / "corpus.json").is_file())

    def test_rejects_benchmark_and_project_paths(self):
        for target in (ROOT / "data", ROOT / "data" / "new-index", ROOT / "results" / "x", ROOT, ROOT / "repocortex"):
            code, _, stderr = run_cli("--repo", str(self.repo), "--out", str(target), "--dry-run")
            self.assertEqual(code, 2, target)
            self.assertIn("error:", stderr)

    def test_rejects_output_inside_repo(self):
        code, _, stderr = run_cli("--repo", str(self.repo), "--out", str(self.repo / "index"))
        self.assertEqual(code, 2)
        self.assertIn("overlaps the input repository", stderr)
        self.assertFalse((self.repo / "index").exists())

    def test_rejects_remote_urls_without_network(self):
        for url in ("https://github.com/django/django", "git@github.com:django/django.git", "ssh://host/repo"):
            code, _, stderr = run_cli("--repo", url, "--out", str(self.out))
            self.assertEqual(code, 2, url)
            self.assertIn("never clones", stderr)
        self.assertFalse(self.out.exists())

    def test_actionable_errors(self):
        cases = [
            (["--repo", str(self.base / "missing"), "--out", str(self.out)], "does not exist"),
            (["--repo", str(self.repo / "setup.py"), "--out", str(self.out)], "not a directory"),
            (["--repo", str(self.repo), "--out", str(self.base / "no" / "parent")], "Create it first"),
            (["--repo", str(self.repo), "--out", str(self.out), "--scope", "nothere"], "not a directory under"),
            (["--repo", str(self.repo), "--out", str(self.out), "--scope", "../x"], "relative path inside"),
            (["--repo", str(self.repo), "--out", str(self.out), "--max-files", "2"], "exceed --max-files"),
        ]
        for argv, expected in cases:
            code, _, stderr = run_cli(*argv)
            self.assertEqual(code, 2, argv)
            self.assertIn(expected, stderr, argv)
        self.assertFalse(self.out.exists())

    def test_repo_without_python(self):
        empty = self.base / "empty"
        (empty / "docs").mkdir(parents=True)
        (empty / "docs" / "readme.md").write_text("hi")
        code, _, stderr = run_cli("--repo", str(empty), "--out", str(self.out))
        self.assertEqual(code, 2)
        self.assertIn("no selected-language files", stderr)

    def test_symlink_outside_repo_is_skipped(self):
        outside = self.base / "outside.py"
        outside.write_text("def secret_outside():\n    pass\n")
        (self.repo / "shop" / "link.py").symlink_to(outside)
        code, stdout, stderr = run_cli("--repo", str(self.repo), "--out", str(self.out), "--json")
        self.assertEqual(code, 0, stderr)
        nodes, _ = load_corpus(self.out / "data" / "corpus.json")
        self.assertNotIn("secret_outside", {n["name"] for n in nodes.values()})

    def test_filters_files_before_reading_and_remaps_repository_root(self):
        outside = self.base / "outside.py"
        outside.write_text("def outside_secret(): pass\n")
        link = self.repo / "shop" / "link.py"
        link.symlink_to(outside)
        large = self.repo / "shop" / "large.py"
        large.write_bytes(b"#" * (ix.MAX_FILE_BYTES + 1))
        vendor = self.repo / "shop" / "node_modules" / "x.py"
        blocked = {link, large, vendor}
        real_open = Path.open
        def guarded(path, *args, **kwargs):
            if path in blocked:
                raise AssertionError("excluded source was opened: " + str(path))
            return real_open(path, *args, **kwargs)
        with mock.patch.object(Path, "open", guarded):
            code, _, stderr = run_cli("--repo", str(self.repo), "--out", str(self.out))
        self.assertEqual(code, 0, stderr)
        nodes, edges = load_corpus(self.out / "data" / "corpus.json")
        self.assertIn("repo:sample", nodes)
        self.assertEqual(nodes["repo:sample"]["name"], "sample")
        self.assertNotIn("repo:django", nodes)
        self.assertTrue(all(src in nodes and dst in nodes for src, _, dst in edges))
        self.assertTrue(any(src == "repo:sample" for src, _, _ in edges))

    def test_max_files_is_checked_before_reading_next_file(self):
        real_open = Path.open
        reads = []
        def watched(path, *args, **kwargs):
            if path.suffix == ".py":
                reads.append(path)
            return real_open(path, *args, **kwargs)
        with mock.patch.object(Path, "open", watched):
            with self.assertRaises(ix.ValidationError):
                ix.collect_sources(self.repo, ("shop",), False, max_files=1)
        self.assertEqual(len(reads), 1)

    def test_absolute_scope_is_rejected(self):
        with self.assertRaises(ix.ValidationError):
            ix.parse_scope("/shop")

    def test_failure_cleans_staging_and_leaves_no_output(self):
        with mock.patch.object(ix, "corpus_from_graph", side_effect=RuntimeError("boom")):
            with self.assertRaises(RuntimeError):
                run_cli("--repo", str(self.repo), "--out", str(self.out))
        self.assertEqual(sorted(p.name for p in self.base.iterdir()), ["sample"])

    def test_does_not_touch_benchmark_or_database(self):
        watched = [ROOT / "data" / "corpus.json", ROOT / "results" / "graph_stats.json"]
        before = {p: p.stat().st_mtime_ns for p in watched if p.exists()}
        with mock.patch("repocortex.hydradb.connect", side_effect=AssertionError("db used")):
            code, _, stderr = run_cli("--repo", str(self.repo), "--out", str(self.out))
        self.assertEqual(code, 0, stderr)
        self.assertEqual(before, {p: p.stat().st_mtime_ns for p in watched if p.exists()})

    def test_embed_uses_offline_local_model(self):
        import numpy as np

        class FakeEmbedder:
            def __init__(self, name):
                self.model_name = name

            def encode(self, texts):
                return np.ones((len(texts), 3), dtype=np.float32)

        with mock.patch("repocortex.retrieve.dense.Embedder", FakeEmbedder), \
                mock.patch.dict("os.environ", {}, clear=False):
            code, stdout, stderr = run_cli("--repo", str(self.repo), "--out", str(self.out), "--embed", "--json")
            import os
            self.assertEqual(os.environ.get("HF_HUB_OFFLINE"), "1")
        self.assertEqual(code, 0, stderr)
        self.assertIn("[5/5] embedding", stderr)
        manifest = json.loads(stdout)
        self.assertEqual(manifest["embeddings"]["functions"], 4)
        blob = np.load(self.out / "data" / "embeddings.npz")
        self.assertEqual(len(blob["uids"]), 4)
        self.assertIn("data/embeddings.npz", manifest["outputs"])

    def test_embed_failure_is_actionable_and_writes_nothing(self):
        def broken(name):
            raise OSError("model not cached")

        with mock.patch("repocortex.retrieve.dense.Embedder", side_effect=broken):
            code, _, stderr = run_cli("--repo", str(self.repo), "--out", str(self.out), "--embed")
        self.assertEqual(code, 2)
        self.assertIn("does not download models", stderr)
        self.assertEqual(sorted(p.name for p in self.base.iterdir()), ["sample"])

    def test_runtime_loads_with_empty_memory_and_default_model(self):
        import numpy as np
        from repocortex.retrieve.dense import MODEL_NAME
        from repocortex.serve.load import load_ranker

        class FakeEmbedder:
            def __init__(self, name=MODEL_NAME):
                self.model_name = name
            def encode(self, texts):
                return np.ones((len(texts), 384), dtype=np.float32)
            def encode_one(self, text):
                return self.encode([text])[0]

        with mock.patch("repocortex.retrieve.dense.Embedder", FakeEmbedder), \
                mock.patch("repocortex.serve.load.Embedder", FakeEmbedder):
            code, stdout, stderr = run_cli("--repo", str(self.repo), "--out", str(self.out),
                                          "--embed", "--runtime", "--json")
            self.assertEqual(code, 0, stderr)
            ranker = load_ranker(self.out)
            self.assertEqual(ranker.memory, [])
            self.assertEqual(ranker.n, 4)
            self.assertTrue(ranker.predict({"ticket": 1, "summary": "checkout order", "description": ""}, k=3).hits)
        manifest = json.loads(stdout)
        self.assertEqual(manifest["kind"], "repocortex-untrained-runtime")
        self.assertTrue(manifest["runtime_ready"])
        self.assertFalse(manifest["learned_runtime"])
        self.assertEqual(manifest["training_reports"], 0)
        self.assertEqual(json.loads((self.out / "data/learned_state.json").read_text()), [])
        with np.load(self.out / "data/learned_state.npz", allow_pickle=False) as state:
            self.assertEqual(state["vectors"].shape, (0, 384))
            self.assertEqual(state["tickets"].dtype, np.dtype("int64"))
            self.assertEqual(state["golds"].dtype.kind, "U")

    def test_runtime_rejects_missing_embeddings_or_wrong_model_before_reading(self):
        with mock.patch.object(ix, "collect_sources", side_effect=AssertionError("source read")):
            for extra in (["--runtime"], ["--runtime", "--embed", "--model", "other/model"]):
                code, _, stderr = run_cli("--repo", str(self.repo), "--out", str(self.out), *extra)
                self.assertEqual(code, 2, stderr)
        self.assertFalse(self.out.exists())

    def test_mixed_language_cli_preserves_root_and_selected_scope(self):
        import importlib.util
        if any(importlib.util.find_spec(name) is None for name in
               ("tree_sitter", "tree_sitter_go", "tree_sitter_typescript", "tree_sitter_javascript")):
            self.skipTest("optional multilang dependencies are not installed")
        (self.repo / "shop" / "worker.go").write_text("package shop\nfunc DispatchJob() {}\n")
        (self.repo / "shop" / "view.tsx").write_text("export const Widget = () => <div>ready</div>;\n")
        (self.repo / "shop" / "unselected.js").write_text("function hiddenLanguage() {}\n")
        code, stdout, stderr = run_cli("--repo", str(self.repo), "--out", str(self.out),
                                      "--scope", "shop", "--languages", "python", "go", "typescript", "--json")
        self.assertEqual(code, 0, stderr)
        nodes, edges = load_corpus(self.out / "data/corpus.json")
        names = {n["name"] for n in nodes.values() if n["label"] == "Function"}
        self.assertTrue({"save_record", "DispatchJob", "Widget"} <= names)
        self.assertNotIn("hiddenLanguage", names)
        self.assertEqual([uid for uid, n in nodes.items() if n["label"] == "Repo"], ["repo:sample"])
        self.assertTrue(all(src in nodes and dst in nodes for src, _, dst in edges))
        self.assertEqual(json.loads(stdout)["languages"], ["python", "go", "typescript"])

    def test_help_mentions_limits(self):
        text = " ".join(ix.build_parser().format_help().split())
        self.assertIn("NOT a learned runtime", text)
        self.assertIn("no database writes", text)


if __name__ == "__main__":
    unittest.main()
