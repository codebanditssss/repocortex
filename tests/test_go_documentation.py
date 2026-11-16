import pytest
pytest.importorskip("tree_sitter")
pytest.importorskip("tree_sitter_go")
from repocortex.graph.multilang import build_multilang_graph


def docs(source):
    graph = build_multilang_graph([("sample.go", source)])
    return {node.name: node.doc for node in graph.by_label("Function")}


def test_go_contiguous_comment_group_preserves_description():
    result = docs('''package sample
// Watch subscribes to filesystem edits.
//
// Bursts are combined into one notification.
func Watch() {}
''')
    assert result["Watch"] == "// Watch subscribes to filesystem edits.\n//\n// Bursts are combined into one notification."


def test_go_doc_stops_at_blank_line_and_intervening_code():
    result = docs('''package sample
// License header.

// First is the first function.
func First() {}
// An unrelated declaration.
var value = 1
func Second() {}
// Detached description.

func Third() {}
''')
    assert result == {"First": "// First is the first function.", "Second": "", "Third": ""}


def test_go_trailing_comments_are_not_function_documentation():
    result = docs('''package sample
var value = 1 // A variable explanation.
func First() {}
var other = 2 // Another variable explanation.
// Second has its own description.
func Second() {}
''')
    assert result == {"First": "", "Second": "// Second has its own description."}


def test_go_multiline_block_and_crlf_are_preserved():
    result = docs('package sample\r\n/* Store persists files.\r\nIt updates the index. */\r\nfunc Store() {}\r\n')
    assert result["Store"] == "/* Store persists files.\r\nIt updates the index. */"


def test_go_document_limit_preserves_beginning():
    text = "// Description " + "x" * 2100
    assert docs("package sample\n" + text + "\nfunc Work() {}\n")["Work"] == text[:2000]
