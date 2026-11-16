from scripts.index_repository import add_source_context
from repocortex.graph.builder import build_graph


def test_context_includes_behavior_strings_and_preserves_graph_identity():
    files = [("app.py", 'def run():\n    return "Start an isolated worker in a registered project"\n')]
    graph = build_graph(files)
    identities = set(graph.nodes), set(graph.edges)
    node = graph.by_label("Function")[0]
    assert "registered project" not in node.doc
    add_source_context(graph, files)
    assert "registered project" in node.doc
    assert (set(graph.nodes), set(graph.edges)) == identities


def test_context_bounds_large_functions_and_does_not_leak_adjacent_function():
    files = [("app.py", "def large():\n" + "    pass  # " + "x" * 3000 + "\n" +
              "    pass\n" * 100 + "def adjacent():\n    return 'adjacent-only'\n")]
    graph = build_graph(files)
    add_source_context(graph, files)
    node = next(n for n in graph.by_label("Function") if n.name == "large")
    assert len(node.doc) <= 2020
    assert "adjacent-only" not in node.doc


def test_invalid_span_does_not_extract_unrelated_source():
    graph = build_graph([("app.py", "def run():\n    pass\n")])
    node = graph.by_label("Function")[0]
    node.end = 999
    original = node.doc
    add_source_context(graph, [("app.py", "unrelated")])
    assert node.doc == original


def test_index_cli_context_is_opt_in(tmp_path):
    import json
    from scripts.index_repository import build_parser, run
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "app.py").write_text('def run():\n    return "register an isolated worker"\n')
    documents = []
    for suffix, flags in [("plain", []), ("context", ["--source-context"])]:
        out = tmp_path / suffix
        manifest = run(build_parser().parse_args(["--repo", str(repo), "--out", str(out), *flags]))
        assert manifest["source_context"] == bool(flags)
        nodes = json.loads((out / "data/corpus.json").read_text())["nodes"]
        documents.append(next(n["doc"] for n in nodes.values() if n["label"] == "Function"))
    assert "isolated worker" not in documents[0]
    assert "isolated worker" in documents[1]
