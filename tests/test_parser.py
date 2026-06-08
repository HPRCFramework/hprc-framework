"""Parsing tests."""

import pytest

from hprc import parse


def test_parses_prompt_attributes():
    tpl = parse(
        '<prompt id="s" model="gpt-5" temperature="0.2" max_tokens="500" '
        'async="no" cache="24h" tools="weather, crm_lookup">Hi</prompt>'
    )
    assert "s" in tpl.prompts
    p = tpl.prompts["s"]
    assert p.model == "gpt-5"
    assert p.temperature == 0.2
    assert p.max_tokens == 500
    assert p.is_async is False
    assert p.cache == "24h"
    assert p.tools == ["weather", "crm_lookup"]


def test_async_defaults_to_false():
    # Sequential by default; concurrency is opt-in via async="yes".
    tpl = parse('<prompt id="s">Hi</prompt>')
    assert tpl.prompts["s"].is_async is False


def test_response_render_flag():
    tpl = parse('<response id="a" render="no"/><response id="b"/>')
    by_id = {r.id: r.render for r in tpl.responses}
    assert by_id == {"a": False, "b": True}


def test_prompt_requires_id():
    with pytest.raises(ValueError):
        parse("<prompt>missing id</prompt>")


def test_duplicate_prompt_id_rejected():
    with pytest.raises(ValueError):
        parse('<prompt id="x">a</prompt><prompt id="x">b</prompt>')


def test_entities_round_trip_in_html():
    # Entities preserved in the document tree as text.
    tpl = parse("<p>Tom &amp; Jerry</p>")
    # Find the text node.
    p = tpl.root[0]
    assert p.tag == "p"
    assert p.children[0].text == "Tom &amp; Jerry"


def test_param_is_not_treated_as_void():
    tpl = parse("<prompt id='p'><param>product</param></prompt>")
    body = tpl.prompts["p"].body
    param = body[0]
    assert param.tag == "param"
    assert param.children[0].text == "product"


def test_self_closing_include():
    tpl = parse(
        '<prompt id="other">o</prompt>'
        '<prompt id="p">x <include response="other"/> y</prompt>'
    )
    tags = [n.tag for n in tpl.prompts["p"].body if n.type == "element"]
    assert "include" in tags


def test_include_unknown_target_raises():
    with pytest.raises(ValueError):
        parse('<prompt id="p">x <include response="ghost"/></prompt>')


def test_invalid_numeric_attribute_raises():
    with pytest.raises(ValueError):
        parse('<prompt id="p" temperature="hot">x</prompt>')
