"""Optional tree-sitter structure for Go and JavaScript/TypeScript.

No code is executed. Files with syntax errors are skipped. CALLS connects only
unambiguous same-file top-level functions invoked through bare identifiers,
without a local binding shadowing the target. Go additionally resolves bare
calls to a unique top-level function of the same declared package in the same
directory, and, only when an authoritative ``go_modules`` mapping is supplied,
``alias.Exported()`` calls through an import whose exact path maps to one
indexed package. Member calls, receivers, dot imports, external imports,
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


def _go_doc(node, source: bytes) -> str:
    """Read the adjacent leading comment group, excluding trailing comments.

    Go's parser emits each // line as a separate sibling. A blank line or
    intervening declaration ends the group; a comment after code is not a doc.
    """
    comments = []
    following = node
    comment = node.prev_named_sibling
    while comment is not None and comment.type == "comment":
        gap = source[comment.end_byte:following.start_byte]
        line_start = source.rfind(b"\n", 0, comment.start_byte) + 1
        before_comment = source[line_start:comment.start_byte]
        if gap.strip() or gap.count(b"\n") != 1 or before_comment.strip():
            break
        comments.append(_text(comment, source))
        following, comment = comment, comment.prev_named_sibling
    return "\n".join(reversed(comments))[:2000]


def _is_test(path, name):
    file = Path(path)
    return (file.name.endswith("_test.go") or any(part in {"test", "tests", "__tests__"} for part in file.parts)
            or any(token in file.name for token in (".test.", ".spec."))
            or (file.suffix == ".go" and name.startswith("Test")))


GO_SCOPE_DECLS = {
    "short_var_declaration": ("left",), "var_spec": ("name",), "const_spec": ("name",),
    "type_spec": ("name",), "type_alias": ("name",), "type_switch_statement": ("alias",),
    "range_clause": ("left",), "receive_statement": ("left",), "parameter_declaration": ("name",),
    "variadic_parameter_declaration": ("name",), "type_parameter_declaration": ("name",),
}
_GO_NAMES = {"identifier", "type_identifier", "package_identifier"}


def _go_file_facts(root, source):
    """Package name, imports [(name|None, path)] and non-function top-level names."""
    package, imports, values = None, [], set()
    for decl in root.named_children:
        if decl.type == "package_clause":
            package = next((_text(n, source) for n in decl.named_children if n.type == "package_identifier"), None)
        elif decl.type == "import_declaration":
            for spec in _walk(decl):
                if spec.type == "import_spec":
                    name = spec.child_by_field_name("name")
                    path = spec.child_by_field_name("path")
                    content = [n for n in _walk(path) if n.type == "interpreted_string_literal_content"] if path else []
                    imports.append((_text(name, source) if name else None, _text(content[0], source) if content else ""))
        elif decl.type in {"var_declaration", "const_declaration", "type_declaration"}:
            for spec in _walk(decl):
                if spec.type in {"var_spec", "const_spec", "type_spec", "type_alias"}:
                    for name in spec.children_by_field_name("name"):
                        values.add(_text(name, source))
    return package, imports, values


def _go_function_calls(fn, body, source):
    """Bare and pkg.Name calls outside closures plus every locally declared name.

    Declarations are collected flow-insensitively (including inside closures and
    the signature) so any local binding of a name blocks resolution.
    """
    shadowed, bare, selectors = set(), [], []
    for field in ("receiver", "parameters", "result", "type_parameters"):
        part = fn.child_by_field_name(field)
        if part:
            shadowed.update(_text(n, source) for n in _walk(part) if n.type in _GO_NAMES)
    for node in _walk(body):
        for field in GO_SCOPE_DECLS.get(node.type, ()):
            for binding in node.children_by_field_name(field):
                shadowed.update(_text(n, source) for n in _walk(binding) if n.type in _GO_NAMES)

    def scan(node):
        if node.type == "func_literal":
            return
        if node.type == "call_expression":
            callee = node.child_by_field_name("function")
            if callee and callee.type == "identifier":
                bare.append(_text(callee, source))
            elif callee and callee.type == "selector_expression":
                operand, field = callee.child_by_field_name("operand"), callee.child_by_field_name("field")
                if operand and field and operand.type == "identifier" and field.type == "field_identifier":
                    selectors.append((_text(operand, source), _text(field, source)))
        for child in node.named_children:
            scan(child)
    scan(body)
    return bare, selectors, shadowed


def _norm_dir(path: str) -> str | None:
    parts = [p for p in path.strip().strip("/").split("/") if p not in {"", "."}]
    if ".." in parts:
        return None
    return "/".join(parts) or "."


def _resolve_go_cross_file(graph, records, incomplete_dirs, go_modules):
    packages = defaultdict(list)
    for record in records:
        if record["package"]:
            packages[(record["dir"], record["package"])].append(record)
    tables = {}
    for key, members in packages.items():
        funcs, blocked = defaultdict(list), set()
        for record in members:
            blocked |= record["values"] | record["reassigned"]
            for fn in record["functions"]:
                if fn["top"] and fn["node"].type == "function_declaration":
                    funcs[fn["name"]].append((fn["uid"], record))
        tables[key] = (funcs, blocked)

    def unique(key, name, allow_tests):
        funcs, blocked = tables[key]
        choices = funcs.get(name, [])
        if name in blocked or len(choices) != 1 or (choices[0][1]["test"] and not allow_tests):
            return None
        return choices[0]

    roots = {}
    for root, module in (go_modules or {}).items():
        root, module = _norm_dir(root), str(module).strip().rstrip("/")
        if root is not None and module:
            roots[root] = module

    def owner(directory):
        found = [r for r in roots if r == "." or directory == r or directory.startswith(r + "/")]
        return max(found, key=lambda r: (r != ".", len(r)), default=None)

    def importable(path):
        if not roots or not path or any(p in {"", ".", ".."} for p in path.split("/")):
            return None
        dirs = set()
        for root, module in roots.items():
            if path == module:
                rest = ""
            elif path.startswith(module + "/"):
                rest = path[len(module) + 1:]
            else:
                continue
            directory = _norm_dir(f"{'' if root == '.' else root}/{rest}")
            if directory is not None and owner(directory) == root:
                dirs.add(directory)
        if len(dirs) != 1:
            return None
        directory = dirs.pop()
        if directory in incomplete_dirs:
            return None
        names = {r["package"] for r in records if r["dir"] == directory and not r["test"]}
        if len(names) != 1 or None in names or "main" in names:
            return None
        return (directory, names.pop())

    for record in records:
        key = (record["dir"], record["package"])
        if not record["package"] or record["dir"] in incomplete_dirs:
            continue
        aliases, explicit = defaultdict(list), set()
        has_dot = False
        for name, path in record["imports"]:
            if name == ".":
                has_dot = True
                continue
            if name == "_":
                continue
            target = importable(path) if go_modules else None
            alias = name or (target[1] if target else None)
            if name:
                explicit.add(name)
            if alias:
                aliases[alias].append(target)
        funcs, blocked = tables[key]
        local_names = {fn["name"] for fn in record["functions"] if fn["top"]}
        for fn in record["functions"]:
            if fn["nested"] or not fn["body"]:
                continue
            bare, selectors, shadowed = _go_function_calls(fn["node"], fn["body"], record["source"])
            if not has_dot:
                for name in bare:
                    if name in shadowed or name in local_names or name in aliases or name in explicit:
                        continue
                    hit = unique(key, name, record["test"])
                    if hit and hit[1] is not record:
                        graph.add_edge(fn["uid"], hit[0], "CALLS")
            for alias, name in selectors:
                targets = aliases.get(alias, [])
                if (len(targets) != 1 or targets[0] is None or targets[0] == key or targets[0] not in tables
                        or alias in shadowed or alias in funcs or alias in blocked or not name[:1].isupper()):
                    continue
                hit = unique(targets[0], name, False)
                if hit:
                    graph.add_edge(fn["uid"], hit[0], "CALLS")


def build_multilang_graph(files: list[tuple[str, str]], *, go_modules: dict[str, str] | None = None) -> Graph:
    graph = Graph()
    # Shared builder compatibility; index_repository replaces this root afterward.
    graph.add_node(Node(uid="repo:django", label="Repo", name="django", kind="repo"))
    parsers = {}
    go_records, go_incomplete = [], set()
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
            if suffix == ".go":
                go_incomplete.add(_norm_dir(str(Path(path).parent)))
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
                doc = (_go_doc(node, source) if suffix == ".go" else
                       _text(comment, source)[:240] if comment and comment.type == "comment" else "")
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
        if suffix == ".go":
            package, imports, values = _go_file_facts(root, source)
            go_records.append({"path": path, "dir": _norm_dir(str(Path(path).parent)), "package": package,
                               "imports": imports, "values": values, "reassigned": reassigned,
                               "functions": functions, "source": source, "test": path.endswith("_test.go")})
    _resolve_go_cross_file(graph, go_records, go_incomplete, go_modules)
    return graph
