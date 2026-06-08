"""Prompt dependency graph.

A prompt depends on another prompt when its body includes that prompt's response
(``<include response="A"/>``) or its constructed prompt text
(``<include prompt="A"/>``). HPRC builds this graph automatically and produces
*execution levels*: prompts in the same level have no dependencies on one another
and can run concurrently; later levels wait for earlier ones.

This removes any need for the application developer to orchestrate prompt order
manually.
"""

from __future__ import annotations

from typing import Dict, List, Set

from .models import Node, PromptDefinition


class DependencyError(Exception):
    """Raised on cyclic or unresolvable prompt dependencies."""


def find_include_deps(nodes: List[Node]) -> Set[str]:
    """Collect the ids of prompts/responses included anywhere in ``nodes``."""
    deps: Set[str] = set()

    def walk(items: List[Node]) -> None:
        for node in items:
            if node.type == "element" and node.tag == "include":
                ref = node.attrs.get("response") or node.attrs.get("prompt")
                if ref:
                    deps.add(ref)
            if node.children:
                walk(node.children)

    walk(nodes)
    return deps


def build_graph(prompts: Dict[str, PromptDefinition]) -> Dict[str, Set[str]]:
    """Build ``{prompt_id: {dependency_ids}}`` restricted to known prompts."""
    graph: Dict[str, Set[str]] = {}
    for pid, prompt in prompts.items():
        deps = find_include_deps(prompt.body)
        # Only depend on ids that are actual prompts; a response include refers
        # to a prompt of the same id.
        graph[pid] = {dep for dep in deps if dep in prompts and dep != pid}
    return graph


def topological_levels(graph: Dict[str, Set[str]]) -> List[List[str]]:
    """Return execution levels via Kahn's algorithm.

    Each inner list is a set of prompt ids with no remaining dependencies and may
    be executed concurrently. Raises :class:`DependencyError` on cycles.
    """
    remaining = {node: set(deps) for node, deps in graph.items()}
    levels: List[List[str]] = []

    while remaining:
        ready = sorted(node for node, deps in remaining.items() if not deps)
        if not ready:
            raise DependencyError(
                f"Cyclic prompt dependency detected among: {sorted(remaining)}"
            )
        levels.append(ready)
        for node in ready:
            del remaining[node]
        for deps in remaining.values():
            deps.difference_update(ready)

    return levels
