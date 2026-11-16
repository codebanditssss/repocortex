"""Optional tree-sitter structure for Go and JavaScript/TypeScript.

No code is executed. Files with syntax errors are skipped. CALLS connects only
unambiguous same-file top-level functions invoked through bare identifiers,
without a local binding shadowing the target. Member calls, cross-file imports,
dynamic dispatch and anonymous callbacks are deliberately unresolved. This is
structural indexing, not a language-server/type-checker or learned graph.
"""
from __future__ import annotations

from collections import defaultdict
from pathlib import Path

from repocortex.graph.model import Graph, Node

SUPPORTED_SUFFIXES = {".go", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs"}
FUNCTION_TYPES = {"function_declaration", "generator_function_declaration", "method_declaration", "method_definition"}
CLOSURES = {"arrow_function", "function_expression", "generator_function", "func_literal"}


def _parser(suffix):
    try:
        from tree_sitter import Language, Parser
        if suffix == ".go":
            import tree_sitter_go
            grammar = tree_sitter_go.language()
        elif suffix in {".ts", ".tsx"}:
            import tree_sitter_typescript
            grammar = (tree_sitter_typescript.language_tsx() if suffix == ".tsx"
                       else tree_sitter_typescript.language_typescript())
        else:
            import tree_sitter_javascript
            grammar = tree_sitter_javascript.language()
    except ImportError as exc:
        raise ImportError("Go/TypeScript/JavaScript indexing requires pip install -e '.[multilang]'") from exc
    return Parser(Language(grammar))


def _walk(node):
    yield node
    for child in node.named_children:
        yield from _walk(child)


def _text(node, source):
    return source[node.start_byte:node.end_byte].decode("utf-8", "replace") if node else ""


def _is_test(path, name):
    file = Path(path)
    return (file.name.endswith("_test.go") or any(part in {"test", "tests", "__tests__"} for part in file.parts)
            or any(token in file.name for token in (".test.", ".spec."))
            or (file.suffix == ".go" and name.startswith("Test")))


def build_multilang_graph(files: list[tuple[str, str]]) -> Graph:
    graph = Graph()
    # Shared builder compatibility; index_repository replaces this root afterward.
    graph.add_node(Node(uid="repo:django", label="Repo", name="django", kind="repo"))
    parsers = {}
    for path, text in files:
        suffix = Path(path).suffix.lower()
        if suffix not in SUPPORTED_SUFFIXES:
            continue
        if suffix not in parsers:
            parsers[suffix] = _parser(suffix)
        parser = parsers[suffix]
        source = text.encode("utf-8")
        root = parser.parse(source).root_node
        if root.has_error:
            continue
        file_uid = f"file:{path}"
        module = path.rsplit(".", 1)[0].replace("/", ".")
        graph.add_node(Node(uid=file_uid, label="File", name=path, file=path, qualname=module, kind="file"))
        graph.add_edge("repo:django", file_uid, "CONTAINS")
        functions = []

        def visit(node, scope=(), owner="", inside_function=False):
            if node.type in {"class_declaration", "abstract_class_declaration"}:
                name = _text(node.child_by_field_name("name"), source)
                if name:
                    qual = ".".join((module, *scope, name))
                    uid = f"class:{path}:{qual}"
                    graph.add_node(Node(uid=uid, label="Class", name=name, file=path, qualname=qual,
                                        start=node.start_point.row + 1, end=node.end_point.row + 1, kind="class"))
                    graph.add_edge(file_uid, uid, "CONTAINS")
                    for child in node.named_children:
                        visit(child, (*scope, name), uid, inside_function)
                    return
            expression_name = node.child_by_field_name("name") if node.type in CLOSURES else None
            fn = node if node.type in FUNCTION_TYPES or expression_name is not None else None
            name_node = node.child_by_field_name("name") if fn else None
            if node.type in {"variable_declarator", "public_field_definition", "field_definition", "pair", "assignment_expression"}:
                value = node.child_by_field_name("value") or node.child_by_field_name("right")
                binding = node.child_by_field_name("name") or node.child_by_field_name("key") or node.child_by_field_name("left")
                if binding and binding.type == "member_expression":
                    binding = binding.child_by_field_name("property")
                if value and value.type in CLOSURES and binding and binding.type in {
                    "identifier", "property_identifier", "private_property_identifier"
                }:
                    fn, name_node = value, binding
            if fn is not None and name_node is not None:
                name = _text(name_node, source)
                # Computed property methods are not stable named functions.
                if name_node.type not in {"identifier", "field_identifier", "property_identifier", "private_property_identifier"}:
                    return
                parts = scope
                receiver = fn.child_by_field_name("receiver")
                if receiver:
                    types = [n for n in _walk(receiver) if n.type == "type_identifier"]
                    if types:
                        parts = (*scope, _text(types[0], source))
                qual = ".".join((module, *parts, name))
                label = "Test" if _is_test(path, name) else "Function"
                uid = f"{'test' if label == 'Test' else 'func'}:{path}:{qual}"
                if uid in graph.nodes:
                    uid += f"@{fn.start_point.row + 1}:{fn.start_point.column}"
                body = fn.child_by_field_name("body")
                signature_end = body.start_byte if body else fn.end_byte
                comment = node.prev_named_sibling
                doc = _text(comment, source)[:240] if comment and comment.type == "comment" else ""
                graph.add_node(Node(uid=uid, label=label, name=name, file=path, qualname=qual,
                                    signature=source[fn.start_byte:signature_end].decode("utf-8", "replace")[:200],
                                    doc=doc, start=fn.start_point.row + 1, end=fn.end_point.row + 1,
                                    kind="test" if label == "Test" else "function"))
                graph.add_edge(file_uid, uid, "CONTAINS")
                graph.add_edge(owner or file_uid, uid, "DEFINES")
                functions.append({"uid": uid, "name": name, "node": fn, "body": body,
                                  "nested": inside_function,
                                  "top": not inside_function and not owner and (node.type == "variable_declarator" or fn.type in {"function_declaration", "generator_function_declaration"})})
                if body:
                    for child in body.named_children:
                        visit(child, (*parts, name), "", True)
                return
            if node.type in CLOSURES | FUNCTION_TYPES:
                # Keep named declarations inside IIFEs/callbacks without inventing
                # an anonymous Function node or treating its children as globals.
                closure_scope = (*scope, f"<closure@{node.start_point.row + 1}:{node.start_point.column}>")
                for child in node.named_children:
                    visit(child, closure_scope, "", True)
                return
            for child in node.named_children:
                visit(child, scope, owner, inside_function)

        visit(root)
        reassigned = set()
        for node in _walk(root):
            if node.type in {"assignment_expression", "assignment_statement"}:
                left = node.child_by_field_name("left")
                if left:
                    reassigned.update(_text(n, source) for n in _walk(left) if n.type == "identifier")
        targets = defaultdict(list)
        for fn in functions:
            if fn["top"] and fn["name"] not in reassigned:
                targets[fn["name"]].append(fn["uid"])
        for fn in functions:
            body = fn["body"]
            if not body or fn["nested"]:
                continue
            shadowed = set()
            if fn["node"].type in CLOSURES:
                internal_name = fn["node"].child_by_field_name("name")
                if internal_name:
                    shadowed.add(_text(internal_name, source))
            parameters = fn["node"].child_by_field_name("parameters") or fn["node"].child_by_field_name("parameter")
            if parameters:
                shadowed.update(_text(n, source) for n in _walk(parameters) if n.type == "identifier")
            receiver = fn["node"].child_by_field_name("receiver")
            if receiver:
                shadowed.update(_text(n, source) for n in _walk(receiver) if n.type == "identifier")
            calls = []
            def scan(node):
                if node.type in FUNCTION_TYPES | CLOSURES:
                    name = node.child_by_field_name("name")
                    if name:
                        shadowed.add(_text(name, source))
                    return
                if node.type in {"variable_declarator", "short_var_declaration", "assignment_expression", "assignment_statement", "var_spec", "range_clause", "catch_clause"}:
                    bindings = list(node.children_by_field_name("name"))
                    bindings += [n for field in ("left", "parameter") if (n := node.child_by_field_name(field))]
                    for binding in bindings:
                        shadowed.update(_text(n, source) for n in _walk(binding) if n.type == "identifier")
                if node.type == "call_expression":
                    callee = node.child_by_field_name("function")
                    if callee and callee.type == "identifier":
                        calls.append(_text(callee, source))
                for child in node.named_children:
                    scan(child)
            scan(body)
            for name in calls:
                choices = targets.get(name, [])
                if name not in shadowed and len(choices) == 1:
                    graph.add_edge(fn["uid"], choices[0], "CALLS")
    return graph
