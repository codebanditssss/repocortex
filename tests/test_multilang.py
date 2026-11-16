import pytest
pytest.importorskip("tree_sitter")
pytest.importorskip("tree_sitter_typescript")
pytest.importorskip("tree_sitter_javascript")
pytest.importorskip("tree_sitter_go")
from repocortex.graph.multilang import build_multilang_graph


def named(graph, name):
    return [n for n in graph.nodes.values() if n.name == name and n.label in {"Function", "Test"}]


def calls(graph):
    return {(graph.nodes[a].name, graph.nodes[b].name) for a, rel, b in graph.edges if rel == "CALLS"}


def test_go_receiver_ranges_and_conservative_calls():
    source = '''package sample
func helper(value string) string { return value }
func (s *Store) Save(value string) string {
    s.Remote(value)
    return helper(value)
}
func blocked(helper func(string) string) { helper("x") }
'''
    graph = build_multilang_graph([("backend/store.go", source)])
    save = named(graph, "Save")[0]
    assert save.start == 3 and save.end == 6
    assert save.qualname.endswith("Store.Save")
    assert calls(graph) == {("Save", "helper")}
    assert ("file:backend/store.go", "DEFINES", save.uid) in graph.edges
    assert all(a in graph.nodes and b in graph.nodes for a, _, b in graph.edges)


def test_typescript_exports_arrows_methods_and_tsx():
    source = '''export function helper(value: string) { return value; }
export const run = async (value: string) => helper(value);
class Store {
  save(value: string) {
    return run(value);
  }
}
'''
    graph = build_multilang_graph([("frontend/api.ts", source),
        ("frontend/Widget.tsx", 'export const Widget = () => <div>Hello</div>;')])
    assert {n.name for n in graph.by_label("Function")} == {"helper", "run", "save", "Widget"}
    assert named(graph, "run")[0].start == 2
    assert named(graph, "save")[0].start == 4 and named(graph, "save")[0].end == 6
    assert calls(graph) == {("run", "helper"), ("save", "run")}
    owner = graph.by_label("Class")[0]
    assert (owner.uid, "DEFINES", named(graph, "save")[0].uid) in graph.edges


def test_no_cross_file_ambiguous_member_or_shadowed_resolution():
    graph = build_multilang_graph([
        ("a.js", '''function duplicate() {} function duplicate() {}
function helper() {} function run() { const helper = remote; helper(); duplicate(); obj.helper(); external(); }
function outer(helper) { function inner() { helper(); } }
'''),
        ("b.js", "function external() {}")])
    assert len(named(graph, "duplicate")) == 2
    assert calls(graph) == set()


def test_test_labels_error_files_and_unicode_lines():
    graph = build_multilang_graph([
        ("store_test.go", "package sample\nfunc TestSave(t *testing.T) {}"),
        ("ui.test.ts", "const testSave = () => true;"),
        ("broken.ts", "export function broken( {"),
        ("unicode.js", '// café 日本語\nexport function save() { return "é"; }\n'),
    ])
    assert {n.name for n in graph.by_label("Test")} == {"TestSave", "testSave"}
    assert "file:broken.ts" not in graph.nodes
    assert named(graph, "save")[0].start == 2
    assert len(graph.by_label("Function")) == 1
    assert all(a in graph.nodes and b in graph.nodes for a, _, b in graph.edges)


def test_reassigned_function_is_not_assumed_to_keep_its_target():
    graph = build_multilang_graph([("main.js", "function helper() {} helper = remote; function run() { helper(); }")])
    assert calls(graph) == set()


def test_iife_keeps_named_declarations_without_inventing_anonymous_functions():
    source = """(() => {
  function inside() { return helper(); }
  const namedArrow = () => inside();
  [1].map(() => 2);
})();
(function () {
  function inside() { return 3; }
})();
"""
    graph = build_multilang_graph([("extension/core.js", source)])
    functions = graph.by_label("Function")
    assert sorted(n.name for n in functions) == ["inside", "inside", "namedArrow"]
    assert len({n.uid for n in functions}) == 3
    assert len({n.qualname for n in named(graph, "inside")}) == 2
    assert sorted(n.start for n in named(graph, "inside")) == [2, 7]
    assert calls(graph) == set()


def test_named_function_expressions_and_property_functions_are_indexed_not_global_targets():
    source = """Half.parseTranscript = function parseTranscript(text) { return text; };
Half.makeCatchup = function makeCatchup(options = {}) { return options; };
Half.createCaptionBuffer = function createCaptionBuffer(element) { return element; };
const object = { arrow: () => 1, named: function internalName() { return 2; } };
class Store { field = (value: string) => value; }
(function namedIife() { return 3; })();
function caller() { parseTranscript(); makeCatchup(); internalName(); namedIife(); }
"""
    graph = build_multilang_graph([("core.ts", source)])
    assert {n.name for n in graph.by_label("Function")} == {
        "parseTranscript", "makeCatchup", "createCaptionBuffer", "arrow", "named", "field", "namedIife", "caller"
    }
    assert named(graph, "parseTranscript")[0].start == 1
    assert named(graph, "makeCatchup")[0].start == 2
    assert calls(graph) == set()
    assert all(a in graph.nodes and b in graph.nodes for a, _, b in graph.edges)


def test_function_expression_internal_name_shadows_same_named_global():
    graph = build_multilang_graph([("main.js", "function helper() {} const run = function helper(){ return helper(); };")])
    assert {n.name for n in graph.by_label("Function")} == {"helper", "run"}
    assert calls(graph) == set()
