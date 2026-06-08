"""Dependency graph and execution ordering tests."""

import pytest

from hprc import parse, render_template_string
from hprc.dependency_graph import (
    DependencyError,
    build_graph,
    topological_levels,
)


def test_graph_edges_from_includes():
    tpl = parse(
        '<prompt id="a">A</prompt>'
        '<prompt id="b">uses <include response="a"/></prompt>'
    )
    graph = build_graph(tpl.prompts)
    assert graph["b"] == {"a"}
    assert graph["a"] == set()


def test_topological_levels_order():
    graph = {"a": set(), "b": {"a"}, "c": {"b"}}
    levels = topological_levels(graph)
    assert levels == [["a"], ["b"], ["c"]]


def test_independent_prompts_same_level():
    graph = {"a": set(), "b": set(), "c": {"a", "b"}}
    levels = topological_levels(graph)
    assert levels[0] == ["a", "b"]
    assert levels[1] == ["c"]


def test_cycle_detected():
    with pytest.raises(DependencyError):
        topological_levels({"a": {"b"}, "b": {"a"}})


async def test_dependent_prompt_sees_dependency_response():
    tpl = (
        '<prompt id="a">first</prompt>'
        '<prompt id="b">based on <include response="a"/></prompt>'
        '<x><response id="b"/></x>'
    )
    html = await render_template_string(tpl)
    # b's prompt embeds a's mock response.
    assert "[mock:default] first" in html
