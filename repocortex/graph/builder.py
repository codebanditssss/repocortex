"""Build a code graph from Python source with the stdlib ast module."""

from __future__ import annotations

import ast
import re
from collections import Counter, defaultdict
from pathlib import Path

from repocortex.graph.model import Graph, Node

STOP = {
    "self", "cls", "args", "kwargs", "true", "false", "none", "return",
    "test", "tests", "with", "from", "this", "that", "into", "over",
    "data", "value", "values", "result", "results", "object", "objects",
    "item", "items", "type", "name", "names", "path", "file", "base",
    "init", "main", "util", "utils", "helper", "helpers", "common",
}

_CAMEL = re.compile(r"[A-Z]+(?![a-z])|[A-Z]?[a-z]+|\d+")


def module_name(relpath: str) -> str:
    module = relpath[:-3].replace("/", ".") if relpath.endswith(".py") else relpath.replace("/", ".")
    if module.endswith(".__init__"):
        module = module[: -len(".__init__")]
    return module


def tokens(text: str) -> list[str]:
    out: list[str] = []
    for raw in text.replace("-", "_").split("_"):
        if not raw:
            continue
        bits = _CAMEL.findall(raw)
        if not bits:
            bits = [raw]
        for bit in bits:
            word = bit.lower()
            if len(word) >= 4 and word not in STOP and not word.isdigit():
                out.append(word)
    return out


def _doc(node: ast.AST) -> str:
    doc = ast.get_docstring(node) or ""
    return " ".join(doc.split())[:240]


def _signature(node: ast.AST) -> str:
    if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return ""
    args = []
    for arg in list(node.args.args) + list(node.args.kwonlyargs):
        args.append(arg.arg)
    if node.args.vararg:
        args.append("*" + node.args.vararg.arg)
    if node.args.kwarg:
        args.append("**" + node.args.kwarg.arg)
    return ", ".join(args)[:200]


def _call_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return ""


def _dotted(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _dotted(node.value)
        return f"{base}.{node.attr}" if base else node.attr
    return ""


class _FileParser(ast.NodeVisitor):
    def __init__(self, relpath: str):
        self.relpath = relpath
        self.module = module_name(relpath)
        self.scope: list[tuple[str, str]] = []
        self.functions: list[dict] = []
        self.classes: list[dict] = []
        self.imports: list[str] = []

    def _qual(self, name: str) -> str:
        parts = [self.module]
        parts.extend(item[1] for item in self.scope)
        parts.append(name)
        return ".".join(part for part in parts if part)

    def _in_function(self) -> bool:
        return any(kind == "func" for kind, _ in self.scope)

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            self.imports.append(alias.name)
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if node.module:
            self.imports.append(node.module)
        self.generic_visit(node)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        qual = self._qual(node.name)
        bases = []
        for base in node.bases:
            text = _dotted(base)
            if text:
                bases.append(text.split(".")[-1])
        self.classes.append(
            {
                "name": node.name,
                "qualname": qual,
                "start": node.lineno,
                "end": node.end_lineno or node.lineno,
                "doc": _doc(node),
                "bases": bases,
            }
        )
        self.scope.append(("class", node.name))
        self.generic_visit(node)
        self.scope.pop()

    def _visit_func(self, node: ast.AST) -> None:
        assert isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        qual = self._qual(node.name)
        calls, self_calls, raises, messages, attr_calls = _collect_body(node)
        # Walk nested defs ourselves so their calls stay on the nested function.
        self.functions.append(
            {
                "name": node.name,
                "qualname": qual,
                "start": node.lineno,
                "end": node.end_lineno or node.lineno,
                "doc": _doc(node),
                "signature": _signature(node),
                "calls": calls,
                "self_calls": self_calls,
                "attr_calls": attr_calls,
                "raises": raises,
                "messages": messages,
                "class": next((name for kind, name in reversed(self.scope) if kind == "class"), ""),
            }
        )
        self.scope.append(("func", node.name))
        for stmt in node.body:
            if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
                self._visit_func(stmt)
            elif isinstance(stmt, ast.ClassDef):
                self.visit_ClassDef(stmt)
            else:
                self.visit(stmt)
        self.scope.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        if self._in_function():
            return
        self._visit_func(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        if self._in_function():
            return
        self._visit_func(node)


def _collect_body(node: ast.AST) -> tuple[list[str], list[str], list[str], list[str], list[tuple[str, str]]]:
    """Calls and raises directly in this function, not in a nested function."""
    calls: list[str] = []
    self_calls: list[str] = []
    raises: list[str] = []
    messages: list[str] = []
    attr_calls: list[tuple[str, str]] = []

    def walk(tree: ast.AST) -> None:
        for child in ast.iter_child_nodes(tree):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                continue
            if isinstance(child, ast.Call):
                func = child.func
                if (
                    isinstance(func, ast.Attribute)
                    and isinstance(func.value, ast.Name)
                    and func.value.id in {"self", "cls"}
                ):
                    self_calls.append(func.attr)
                else:
                    if (
                        isinstance(func, ast.Attribute)
                        and isinstance(func.value, ast.Name)
                        and func.value.id not in {"self", "cls"}
                    ):
                        attr_calls.append((func.value.id, func.attr))
                    name = _call_name(func)
                    if name:
                        calls.append(name)
            if isinstance(child, ast.Raise) and child.exc is not None:
                exc = child.exc
                target = exc.func if isinstance(exc, ast.Call) else exc
                name = _call_name(target)
                if name and (
                    name.endswith("Error") or name.endswith("Exception") or name.endswith("Warning")
                ):
                    raises.append(name)
                if isinstance(exc, ast.Call):
                    for arg in exc.args:
                        if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                            text = " ".join(arg.value.split())
                            if 16 <= len(text) <= 100:
                                messages.append(text)
            walk(child)

    walk(node)
    return calls, self_calls, raises, messages, attr_calls


def _is_test(relpath: str, name: str, class_name: str) -> bool:
    lowered = relpath.replace("\\", "/")
    if "/tests/" in f"/{lowered}" or "/test_" in f"/{lowered}" or lowered.endswith("_tests.py"):
        return True
    if name.startswith("test_") or class_name.startswith("Test"):
        return True
    return False


def parse_source(relpath: str, source: str) -> dict | None:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return None
    parser = _FileParser(relpath)
    parser.visit(tree)
    return {
        "relpath": relpath,
        "module": parser.module,
        "imports": parser.imports,
        "classes": parser.classes,
        "functions": parser.functions,
    }


def iter_sources(root: Path, scope: tuple[str, ...]) -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    for prefix in scope:
        base = root / prefix
        if not base.exists():
            continue
        for path in sorted(base.rglob("*.py")):
            if "migrations" in path.parts:
                continue
            relpath = path.relative_to(root).as_posix()
            found.append((relpath, path.read_text(encoding="utf-8", errors="replace")))
    return found


def functions_touching(parsed: dict, lines: list[int]) -> list[str]:
    """Return function uids whose span contains any of `lines`."""
    if not parsed:
        return []
    relpath = parsed["relpath"]
    hits = []
    for fn in parsed["functions"]:
        if _is_test(relpath, fn["name"], fn["class"]):
            continue
        for line in lines:
            if fn["start"] <= line <= fn["end"]:
                hits.append(_function_uid(relpath, fn["qualname"]))
                break
    return hits


def _function_uid(relpath: str, qualname: str) -> str:
    return f"func:{relpath}:{qualname}"


def _class_uid(qualname: str) -> str:
    return f"class:{qualname}"


def build_graph(files: list[tuple[str, str]]) -> Graph:
    parsed = []
    for relpath, source in files:
        item = parse_source(relpath, source)
        if item is not None:
            parsed.append(item)

    graph = Graph()
    graph.add_node(Node(uid="repo:django", label="Repo", name="django", kind="repo"))

    module_to_file: dict[str, str] = {}
    classes_by_name: dict[str, list[str]] = defaultdict(list)
    functions_by_name: dict[str, list[str]] = defaultdict(list)
    methods_by_class: dict[str, dict[str, str]] = defaultdict(dict)

    for item in parsed:
        relpath = item["relpath"]
        file_uid = f"file:{relpath}"
        graph.add_node(Node(uid=file_uid, label="File", name=relpath, file=relpath, qualname=item["module"], kind="file"))
        graph.add_edge("repo:django", file_uid, "CONTAINS")
        module_to_file[item["module"]] = file_uid
        for cls in item["classes"]:
            uid = _class_uid(cls["qualname"])
            graph.add_node(
                Node(
                    uid=uid,
                    label="Class",
                    name=cls["name"],
                    file=relpath,
                    qualname=cls["qualname"],
                    doc=cls["doc"],
                    start=cls["start"],
                    end=cls["end"],
                    kind="class",
                )
            )
            graph.add_edge(file_uid, uid, "CONTAINS")
            classes_by_name[cls["name"]].append(uid)
        for fn in item["functions"]:
            is_test = _is_test(relpath, fn["name"], fn["class"])
            if is_test:
                uid = f"test:{relpath}:{fn['qualname']}"
                label = "Test"
            else:
                uid = _function_uid(relpath, fn["qualname"])
                label = "Function"
            graph.add_node(
                Node(
                    uid=uid,
                    label=label,
                    name=fn["name"],
                    file=relpath,
                    qualname=fn["qualname"],
                    signature=fn["signature"],
                    doc=fn["doc"],
                    start=fn["start"],
                    end=fn["end"],
                    kind="test" if is_test else "function",
                )
            )
            if fn["class"]:
                class_qual = fn["qualname"].rsplit("." + fn["name"], 1)[0]
                graph.add_edge(_class_uid(class_qual), uid, "DEFINES")
                methods_by_class[class_qual][fn["name"]] = uid
            else:
                graph.add_edge(file_uid, uid, "CONTAINS")
            if label == "Function":
                functions_by_name[fn["name"]].append(uid)
            fn["uid"] = uid
            fn["relpath"] = relpath
            fn["is_test"] = is_test

    for item in parsed:
        file_uid = f"file:{item['relpath']}"
        for imported in item["imports"]:
            target = module_to_file.get(imported)
            if target is None and "." in imported:
                target = module_to_file.get(imported.rsplit(".", 1)[0])
            if target and target != file_uid:
                graph.add_edge(file_uid, target, "IMPORTS")
        for cls in item["classes"]:
            src = _class_uid(cls["qualname"])
            for base in cls["bases"]:
                choices = classes_by_name.get(base, [])
                same = [c for c in choices if c.startswith("class:" + item["module"])]
                picked = same[0] if len(same) == 1 else (choices[0] if len(choices) == 1 else "")
                if picked:
                    graph.add_edge(src, picked, "INHERITS")

    concept_df: Counter[str] = Counter()
    fn_tokens: dict[str, list[str]] = {}
    for item in parsed:
        for fn in item["functions"]:
            if fn["is_test"]:
                fn_tokens[fn["uid"]] = []
                continue
            bag = tokens(fn["name"]) + tokens(fn["class"]) + tokens(fn["doc"])
            deduped = list(dict.fromkeys(bag))[:12]
            fn_tokens[fn["uid"]] = deduped
            concept_df.update(set(deduped))

    n_funcs = max(1, sum(1 for item in parsed for fn in item["functions"] if not fn["is_test"]))
    keep_floor = 2
    keep_ceil = max(8, int(n_funcs * 0.25))

    for item in parsed:
        for fn in item["functions"]:
            if not fn["is_test"]:
                for token in fn_tokens.get(fn["uid"], []):
                    df = concept_df[token]
                    if df < keep_floor or df > keep_ceil:
                        continue
                    cuid = f"concept:{token}"
                    if cuid not in graph.nodes:
                        graph.add_node(Node(uid=cuid, label="Concept", name=token, kind="concept"))
                    graph.add_edge(fn["uid"], cuid, "MENTIONS")
                for name in fn["raises"]:
                    suid = f"symptom:{name}"
                    if suid not in graph.nodes:
                        graph.add_node(Node(uid=suid, label="Symptom", name=name, kind="exception"))
                    graph.add_edge(fn["uid"], suid, "RAISES")
                for message in fn["messages"][:2]:
                    slug = re.sub(r"[^a-z0-9]+", "-", message.lower()).strip("-")[:48]
                    if not slug:
                        continue
                    suid = f"symptom:msg:{slug}"
                    if suid not in graph.nodes:
                        graph.add_node(Node(uid=suid, label="Symptom", name=message[:80], kind="message"))
                    graph.add_edge(fn["uid"], suid, "RAISES")

            for attr in fn["self_calls"]:
                class_qual = fn["qualname"].rsplit("." + fn["name"], 1)[0] if fn["class"] else ""
                target = methods_by_class.get(class_qual, {}).get(attr, "")
                if target:
                    graph.add_edge(fn["uid"], target, "CALLS")
            for owner, attr in fn.get("attr_calls") or []:
                classes = classes_by_name.get(owner, [])
                if len(classes) != 1:
                    continue
                qual = classes[0][len("class:") :]
                target = methods_by_class.get(qual, {}).get(attr, "")
                if target and target != fn["uid"]:
                    graph.add_edge(fn["uid"], target, "CALLS")
            for name in fn["calls"]:
                choices = functions_by_name.get(name, [])
                if not choices:
                    continue
                same_file = [c for c in choices if c.startswith(f"func:{fn['relpath']}:")]
                if len(same_file) == 1:
                    graph.add_edge(fn["uid"], same_file[0], "CALLS")
                elif len(choices) == 1:
                    graph.add_edge(fn["uid"], choices[0], "CALLS")
    calls_from: dict[str, list[str]] = defaultdict(list)
    for edge in graph.edges.values():
        if edge.rel == "CALLS":
            calls_from[edge.src].append(edge.dst)
    for item in parsed:
        for fn in item["functions"]:
            if not fn["is_test"]:
                continue
            for dst in calls_from.get(fn["uid"], []):
                if dst.startswith("func:"):
                    graph.add_edge(dst, fn["uid"], "TESTED_BY")

    return graph


def add_cochange(graph: Graph, groups: list[list[str]], cap: int = 12) -> int:
    """Add CO_CHANGED edges for functions edited in the same train commit."""
    added = 0
    for group in groups:
        unique = []
        seen = set()
        for uid in group:
            if uid in seen or uid not in graph.nodes:
                continue
            if graph.nodes[uid].label != "Function":
                continue
            seen.add(uid)
            unique.append(uid)
        if len(unique) < 2 or len(unique) > cap:
            continue
        unique.sort()
        for i, src in enumerate(unique):
            for dst in unique[i + 1 :]:
                before = (src, "CO_CHANGED", dst) in graph.edges
                graph.add_edge(src, dst, "CO_CHANGED")
                if not before:
                    added += 1
    return added
