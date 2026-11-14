import ast
import unittest

from repocortex.graph.builder import build_graph, parse_source


SAMPLE = '''
import os
from django.db.models import query

class QuerySet:
    """Query rows."""

    def filter(self, *args):
        """Keep some rows."""
        self._filter_or_exclude(False)
        raise FieldError("bad lookup in filter")

    def _filter_or_exclude(self, negate):
        return negate


def public_api(qs):
    """Public entry."""
    return qs.filter()
'''


class BuilderTest(unittest.TestCase):
    def test_nodes_and_calls(self):
        graph = build_graph([("django/db/models/query.py", SAMPLE)])
        labels = {node.label for node in graph.nodes.values()}
        self.assertIn("Function", labels)
        self.assertIn("Class", labels)
        self.assertIn("File", labels)
        names = {node.name for node in graph.nodes.values() if node.label == "Function"}
        self.assertEqual(names, {"filter", "_filter_or_exclude", "public_api"})
        rels = {edge.rel for edge in graph.edges.values()}
        self.assertIn("CALLS", rels)
        self.assertIn("DEFINES", rels)
        self.assertIn("RAISES", rels)
        self.assertTrue(any(node.name == "FieldError" for node in graph.nodes.values()))

    def test_parse_recovers_span(self):
        parsed = parse_source("django/db/models/query.py", SAMPLE)
        self.assertIsNotNone(parsed)
        spans = {fn["name"]: (fn["start"], fn["end"]) for fn in parsed["functions"]}
        self.assertLess(spans["filter"][0], spans["_filter_or_exclude"][0])
        tree = ast.parse(SAMPLE)
        self.assertIsNotNone(tree)


if __name__ == "__main__":
    unittest.main()
