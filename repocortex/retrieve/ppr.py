"""Personalized PageRank on a small subgraph. No server-side GDS."""

from __future__ import annotations


def personalized_pagerank(
    nodes: list[str],
    adj: dict[str, list[tuple[str, float]]],
    seeds: dict[str, float],
    teleport: float = 0.15,
    iterations: int = 25,
) -> dict[str, float]:
    """Power iteration. `adj` maps a node to (neighbor, weight) pairs.

    `teleport` is the probability of jumping back to the seed distribution.
    """
    if not nodes:
        return {}
    index = {uid: i for i, uid in enumerate(nodes)}
    size = len(nodes)
    seed = [0.0] * size
    for uid, weight in seeds.items():
        if uid in index and weight > 0:
            seed[index[uid]] += weight
    total = sum(seed)
    if total <= 0:
        share = 1.0 / size
        seed = [share] * size
    else:
        seed = [value / total for value in seed]

    outgoing: list[list[tuple[int, float]]] = [[] for _ in range(size)]
    for uid, nbrs in adj.items():
        if uid not in index:
            continue
        src = index[uid]
        weights = []
        for nbr, weight in nbrs:
            if nbr in index and weight > 0:
                weights.append((index[nbr], weight))
        denom = sum(weight for _, weight in weights)
        if denom <= 0:
            continue
        outgoing[src] = [(dst, weight / denom) for dst, weight in weights]

    rank = seed[:]
    for _ in range(iterations):
        nxt = [teleport * seed[i] for i in range(size)]
        for src, nbrs in enumerate(outgoing):
            if not nbrs:
                # Dangling mass stays on the node, then mixes with teleport.
                nxt[src] += (1.0 - teleport) * rank[src]
                continue
            share = (1.0 - teleport) * rank[src]
            for dst, prob in nbrs:
                nxt[dst] += share * prob
        rank = nxt
    return {uid: rank[i] for i, uid in enumerate(nodes)}
