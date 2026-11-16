"""Refined shortcuts retain inherited and subsequent outcome evidence."""

from types import SimpleNamespace

from repocortex.learn.base import Episode
from repocortex.learn.compress import PathCompressor
from repocortex.learn.merge import EntityMerger
from repocortex.retrieve.frozen import EdgeTable


def refined_shortcut():
    nodes = {f"f{i}": {"file": f"pkg/mod{i // 2}/code.py"} for i in range(12)}
    table = EdgeTable({})
    for i in range(12):
        table.ensure(
            "concept:c", "SHORTCUT", f"f{i}", hits=3,
            misses=0 if i < 2 else 20, count=3, tickets="1,2,3",
        )
    compressor = PathCompressor()
    compressor.hydrate(table)
    merger = EntityMerger(ranker=SimpleNamespace(nodes=nodes), every=1)
    merger.on_outcome(table, Episode(ticket=4, seeds=[], gold=[], predicted=[]))
    return table, compressor, merger, ("concept:c@pkg.mod0", "SHORTCUT", "f0")


def debit(compressor, table, key, ticket):
    compressor.on_outcome(
        table, Episode(ticket=ticket, seeds=[], gold=["other"], predicted=["f0"], debit=[key])
    )


def test_first_child_debit_preserves_inherited_support():
    table, compressor, _, key = refined_shortcut()
    debit(compressor, table, key, 5)
    edge = table.edges[key]
    assert (edge["hits"], edge["misses"], edge["count"]) == (3, 1, 3)
    assert edge["w"] == 0.75
    assert edge["tickets"] == "1,2,3"
    debit(compressor, table, key, 6)
    assert (edge["hits"], edge["misses"]) == (3, 2)
    assert edge["w"] == 0.6


def test_first_child_credit_preserves_inherited_support():
    table, compressor, _, key = refined_shortcut()
    compressor.on_outcome(
        table, Episode(ticket=5, seeds=[], gold=["f0"], predicted=[], concepts=[key[0]])
    )
    edge = table.edges[key]
    assert (edge["hits"], edge["misses"], edge["count"]) == (4, 0, 4)
    assert edge["tickets"] == "1,2,3,5"


def test_repeated_merge_preserves_child_specific_evidence():
    table, compressor, merger, key = refined_shortcut()
    debit(compressor, table, key, 5)
    expected = dict(table.edges[key])
    merger.on_outcome(table, Episode(ticket=6, seeds=[], gold=[], predicted=[]))
    assert table.edges[key] == expected
    debit(compressor, table, key, 7)
    assert (table.edges[key]["hits"], table.edges[key]["misses"]) == (3, 2)


def test_hydrated_child_does_not_count_inherited_support_twice():
    table, _, _, key = refined_shortcut()
    compressor = PathCompressor()
    compressor.hydrate(table)
    debit(compressor, table, key, 5)
    assert (table.edges[key]["hits"], table.edges[key]["misses"]) == (3, 1)
    restarted = PathCompressor()
    restarted.hydrate(table)
    debit(restarted, table, key, 6)
    assert (table.edges[key]["hits"], table.edges[key]["misses"]) == (3, 2)
