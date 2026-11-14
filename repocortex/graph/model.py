"""In-memory graph produced by the builder and stored in HydraDB."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Node:
    uid: str
    label: str
    name: str
    file: str = ""
    qualname: str = ""
    signature: str = ""
    doc: str = ""
    start: int = 0
    end: int = 0
    kind: str = ""

    def as_row(self) -> dict:
        return {
            "uid": self.uid,
            "name": self.name,
            "file": self.file,
            "qualname": self.qualname,
            "signature": self.signature,
            "doc": self.doc,
            "start": self.start,
            "end": self.end,
            "kind": self.kind or self.label.lower(),
        }


@dataclass
class Edge:
    src: str
    dst: str
    rel: str
    w: float = 1.0
    hits: int = 0
    misses: int = 0
    count: int = 1

    def as_row(self) -> dict:
        return {
            "src": self.src,
            "dst": self.dst,
            "w": self.w,
            "hits": self.hits,
            "misses": self.misses,
            "count": self.count,
        }


@dataclass
class Graph:
    nodes: dict[str, Node] = field(default_factory=dict)
    edges: dict[tuple[str, str, str], Edge] = field(default_factory=dict)

    def add_node(self, node: Node) -> None:
        self.nodes[node.uid] = node

    def add_edge(self, src: str, dst: str, rel: str, count: int = 1) -> None:
        if not src or not dst or src == dst:
            return
        if src not in self.nodes or dst not in self.nodes:
            return
        key = (src, rel, dst)
        existing = self.edges.get(key)
        if existing is None:
            self.edges[key] = Edge(src=src, dst=dst, rel=rel, count=count)
        else:
            existing.count += count

    def by_label(self, label: str) -> list[Node]:
        return [node for node in self.nodes.values() if node.label == label]
