"""Deterministic, non-recursive graph algorithms shared by metrics."""

from __future__ import annotations

from collections.abc import Iterable
from typing import TypeVar


Node = TypeVar("Node", bound=str)


def strong_components(
    nodes: set[Node], edges: Iterable[tuple[Node, Node]]
) -> list[set[Node]]:
    """Return SCCs using an iterative deterministic Kosaraju traversal."""
    adjacency = {node: set() for node in nodes}
    reverse = {node: set() for node in nodes}
    for source, target in edges:
        adjacency[source].add(target)
        reverse[target].add(source)

    seen: set[Node] = set()
    order: list[Node] = []
    for root in sorted(nodes):
        if root in seen:
            continue
        seen.add(root)
        stack = [(root, iter(sorted(adjacency[root])))]
        while stack:
            node, targets = stack[-1]
            try:
                target = next(targets)
            except StopIteration:
                order.append(node)
                stack.pop()
                continue
            if target not in seen:
                seen.add(target)
                stack.append((target, iter(sorted(adjacency[target]))))

    components: list[set[Node]] = []
    seen.clear()
    for root in reversed(order):
        if root in seen:
            continue
        component: set[Node] = set()
        pending = [root]
        seen.add(root)
        while pending:
            node = pending.pop()
            component.add(node)
            for target in sorted(reverse[node], reverse=True):
                if target not in seen:
                    seen.add(target)
                    pending.append(target)
        components.append(component)
    return components
