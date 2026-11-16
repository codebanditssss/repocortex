import pytest
pytest.importorskip("tree_sitter")
pytest.importorskip("tree_sitter_go")
from repocortex.graph.multilang import build_multilang_graph


def calls(graph):
    return {(graph.nodes[a].qualname, graph.nodes[b].qualname) for a, rel, b in graph.edges if rel == "CALLS"}


STORE = ("svc/store.go", '''package svc
func Load(id string) string { return normalize(id) }
func normalize(id string) string { return id }
func (s *Store) Save(v string) string { return normalize(v) }
''')


def test_bare_cross_file_calls_in_functions_and_methods_share_package_and_directory():
    graph = build_multilang_graph([STORE, ("svc/api.go", '''package svc
type Server struct{}
func Handle(id string) string { return Load(id) + normalize(id) }
func (s *Server) Serve() { Handle("x") }
func (s *Server) Save() {}
func Caller() { Save() }
''')])
    assert calls(graph) == {
        ("svc.store.Load", "svc.store.normalize"),
        ("svc.store.Store.Save", "svc.store.normalize"),
        ("svc.api.Handle", "svc.store.Load"),
        ("svc.api.Handle", "svc.store.normalize"),
        ("svc.api.Server.Serve", "svc.api.Handle"),
    }
    # Function UIDs and node fields are unchanged by cross-file resolution.
    load = graph.nodes["func:svc/store.go:svc.store.Load"]
    assert (load.name, load.start, load.end, load.kind) == ("Load", 2, 2, "function")


def test_bare_calls_reject_ambiguity_shadowing_other_dirs_packages_and_closures():
    graph = build_multilang_graph([
        ("svc/a.go", "package svc\nfunc Dup() {}\n"),
        ("svc/a_linux.go", "package svc\nfunc Dup() {}\n"),
        ("svc/vars.go", "package svc\nvar Value = 1\nfunc Value2() {}\nconst Konst = 2\n"),
        ("svc/kons.go", "package svc\nfunc Konst() {}\n"),
        ("other/other.go", "package svc\nfunc Elsewhere() {}\n"),
        ("svc/gen.go", "package gen\nfunc Generated() {}\n"),
        ("svc/r.go", "package svc\nfunc Reassigned() {}\n"),
        ("svc/use.go", '''package svc
func Use(Param func()) {
    Dup()
    Konst()
    Elsewhere()
    Generated()
    local := func() {}
    local()
    Param()
    Value2 := 3
    Value2()
    Reassigned = nil
    go func() { Uniq() }()
    var Missing func()
    Missing()
}
func Uniq() {}
'''),
        ("svc/missing.go", "package svc\nfunc Missing() {}\n"),
    ])
    assert calls(graph) == set()


def test_dot_import_disables_bare_cross_file_and_tests_do_not_leak_into_production():
    graph = build_multilang_graph([
        ("pkg/a.go", 'package pkg\nimport . "example.com/m/other"\nfunc A() { Helper() }\n'),
        ("pkg/b.go", "package pkg\nfunc Helper() {}\nfunc B() { TestOnly() }\n"),
        ("pkg/util_test.go", "package pkg\nfunc TestOnly() {}\nfunc TestB(t *T) { Helper() }\n"),
        ("pkg/ext_test.go", "package pkg_test\nfunc TestExt(t *T) { Helper() }\n"),
    ])
    assert calls(graph) == {("pkg.util_test.TestB", "pkg.b.Helper")}


def test_syntax_error_sibling_makes_directory_unresolvable():
    graph = build_multilang_graph([
        ("pkg/a.go", "package pkg\nfunc A() { Helper() }\n"),
        ("pkg/b.go", "package pkg\nfunc Helper() {}\n"),
        ("pkg/broken.go", "package pkg\nfunc Helper( {\n"),
    ])
    assert calls(graph) == set()


MODULE_FILES = [
    ("lib/util/util.go", "package util\nfunc Clean() {}\nfunc private() {}\nfunc (u U) Method() {}\n"),
    ("lib/text/text.go", "package textual\nfunc Wrap() {}\n"),
    ("lib/nested/inner/inner.go", "package inner\nfunc Deep() {}\n"),
    ("lib/twopkg/a.go", "package a\nfunc Pick() {}\n"),
    ("lib/twopkg/b.go", "package b\nfunc Pick() {}\n"),
    ("lib/dup/x.go", "package dup\nfunc Same() {}\n"),
    ("lib/dup/y.go", "package dup\nfunc Same() {}\n"),
    ("cmd/app/main.go", '''package main
import (
    "fmt"
    "example.com/lib/util"
    tx "example.com/lib/text"
    _ "example.com/lib/dup"
    "example.com/lib/twopkg"
    "example.com/nested/inner"
    deep "example.com/lib/nested/inner"
    "github.com/other/util2"
)
func main() {
    util.Clean()
    util.private()
    util.Method()
    tx.Wrap()
    textual.Wrap()
    a.Pick()
    inner.Deep()
    deep.Deep()
    util2.Clean()
    fmt.Println()
    run()
}
func run() {
    util := helper{}
    util.Clean()
    func() { tx.Wrap() }()
}
'''),
]
MODULES = {"lib": "example.com/lib", "lib/nested": "example.com/nested", "cmd": "example.com/cmd"}


def test_alias_selector_calls_require_exact_module_mapping_and_unique_exported_target():
    graph = build_multilang_graph(MODULE_FILES, go_modules=MODULES)
    assert calls(graph) == {
        ("cmd.app.main.main", "lib.util.util.Clean"),
        ("cmd.app.main.main", "lib.text.text.Wrap"),
        ("cmd.app.main.main", "lib.nested.inner.inner.Deep"),
        ("cmd.app.main.main", "cmd.app.main.run"),
    }


def test_alias_selector_calls_stay_unresolved_without_mapping():
    graph = build_multilang_graph(MODULE_FILES)
    assert calls(graph) == {("cmd.app.main.main", "cmd.app.main.run")}


def test_nested_module_boundary_blocks_outer_module_path_and_most_specific_root_wins():
    files = [
        ("go/pkg/a/a.go", "package a\nfunc Outer() {}\n"),
        ("go/sub/b/b.go", "package b\nfunc Inner() {}\n"),
        ("go/use.go", '''package root
import (
    "ex.com/root/sub/b"
    "ex.com/sub/b"
    "ex.com/root/pkg/a"
    "a"
)
func Use() { b.Inner(); a.Outer() }
'''),
    ]
    modules = {"go": "ex.com/root", "go/sub": "ex.com/sub"}
    # The outer module path crosses the nested go/sub module boundary, and the
    # bare "a" path is never matched by suffix, so neither selector resolves.
    files[2] = ("go/use.go", 'package root\nimport (\n"ex.com/root/sub/b"\n"a"\n)\nfunc Use() { b.Inner(); a.Outer() }\n')
    assert calls(build_multilang_graph(files, go_modules=modules)) == set()
    files[2] = ("go/use.go", 'package root\nimport (\n"ex.com/sub/b"\n"ex.com/root/pkg/a"\n)\nfunc Use() { b.Inner(); a.Outer() }\n')
    assert calls(build_multilang_graph(files, go_modules=modules)) == {
        ("go.use.Use", "go.sub.b.b.Inner"), ("go.use.Use", "go.pkg.a.a.Outer")}
    # Without the nested root, the same path is ordinary outer-module content.
    files[2] = ("go/use.go", 'package root\nimport "ex.com/root/sub/b"\nfunc Use() { b.Inner() }\n')
    assert calls(build_multilang_graph(files, go_modules={"go": "ex.com/root"})) == {
        ("go.use.Use", "go.sub.b.b.Inner")}


def test_imports_never_target_test_files_main_packages_or_suffix_matches():
    graph = build_multilang_graph([
        ("tool/main.go", "package main\nfunc Run() {}\n"),
        ("lib/x/x.go", "package x\nfunc Prod() {}\n"),
        ("lib/x/x_test.go", "package x\nfunc OnlyTest() {}\n"),
        ("lib/x/ext_test.go", 'package x_test\nimport "m.io/lib/x"\nfunc TestUse(t *T) { x.Prod() }\n'),
        ("app/app.go", '''package app
import (
    "m.io/tool"
    "m.io/lib/x"
    y "lib/x"
)
func App() { main.Run(); tool.Run(); x.OnlyTest(); y.Prod(); x.Prod() }
'''),
    ], go_modules={".": "m.io"})
    assert calls(graph) == {("app.app.App", "lib.x.x.Prod"), ("lib.x.ext_test.TestUse", "lib.x.x.Prod")}
