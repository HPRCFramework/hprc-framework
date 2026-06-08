"""Fill resolution, request parameters and rule evaluation tests."""

import pytest

from hprc import render_template_string
from hprc.request_context import normalize_request, resolve_path
from hprc.rules import RuleError, evaluate_rule


# -- fill / dot-path --------------------------------------------------------
def test_resolve_nested_dot_path():
    root = {"customer": {"profile": {"name": "Ada"}}}
    assert resolve_path(root, "customer.profile.name") == "Ada"


def test_resolve_missing_returns_empty():
    assert resolve_path({"a": {}}, "a.b.c") == ""


def test_resolve_list_index():
    assert resolve_path({"items": ["x", "y"]}, "items.1") == "y"


async def test_fill_renders_value():
    html = await render_template_string(
        "<h1><fill>customer.name</fill></h1>",
        bindings={"customer": {"name": "Ada"}},
    )
    assert "<h1>Ada</h1>" in html


async def test_fill_is_html_escaped():
    html = await render_template_string(
        "<p><fill>customer.name</fill></p>",
        bindings={"customer": {"name": "<script>"}},
    )
    assert "&lt;script&gt;" in html
    assert "<script>" not in html


# -- request parameters -----------------------------------------------------
def test_normalize_dict_request():
    req = normalize_request({"query": {"product": "X"}, "path": {"id": "1"}, "method": "POST"})
    assert req["query"]["product"] == "X"
    assert req["path"]["id"] == "1"
    assert req["method"] == "POST"


def test_normalize_object_request():
    class FakeRequest:
        query_params = {"product": "Y"}
        path_params = {"customer_id": "42"}
        method = "GET"

    req = normalize_request(FakeRequest())
    assert req["query"]["product"] == "Y"
    assert req["path"]["customer_id"] == "42"
    assert req["method"] == "GET"


async def test_param_shortcut_equals_request_query():
    tpl = "<a><param>product</param></a><b><fill>request.query.product</fill></b>"
    html = await render_template_string(
        tpl, request={"query": {"product": "WidgetPro"}}
    )
    assert "<a>WidgetPro</a>" in html
    assert "<b>WidgetPro</b>" in html


async def test_request_path_and_method():
    tpl = "<p><fill>request.path.customer_id</fill>-<fill>request.method</fill></p>"
    html = await render_template_string(
        tpl, request={"query": {}, "path": {"customer_id": "7"}, "method": "GET"}
    )
    assert "<p>7-GET</p>" in html


# -- rules ------------------------------------------------------------------
def test_rule_evaluates():
    rules = {"is_premium": lambda ctx: ctx["tier"] == "premium"}
    assert evaluate_rule("is_premium", rules, {"tier": "premium"}) is True
    assert evaluate_rule("is_premium", rules, {"tier": "free"}) is False


def test_blank_rule_is_true():
    assert evaluate_rule("", {}, {}) is True


def test_unknown_rule_raises():
    with pytest.raises(RuleError):
        evaluate_rule("nope", {}, {})
