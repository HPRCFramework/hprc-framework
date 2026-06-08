"""Rendering, tacit prompts, hidden responses, conditions and tool tests."""

from hprc import MockLLMClient, HPRCConfig, render_template_string
from hprc.models import ToolDefinition
from hprc.rules import RuleError
from hprc.tools import ToolError, normalize_tools, resolve_tools


# -- tacit prompts ----------------------------------------------------------
async def test_prompt_never_rendered():
    # Fixed responder so the prompt text can't leak via the mock echo.
    cfg = HPRCConfig(llm_client=MockLLMClient(responder=lambda *a: "DONE"))
    tpl = '<prompt id="a">SECRET PROMPT TEXT</prompt><x><response id="a"/></x>'
    html = await render_template_string(tpl, config=cfg)
    assert "SECRET PROMPT TEXT" not in html  # prompt body is tacit
    assert "<prompt" not in html
    assert "<x>DONE</x>" in html


# -- response render flag ---------------------------------------------------
async def test_hidden_response_not_rendered_but_available():
    tpl = (
        '<prompt id="a">hi</prompt>'
        '<prompt id="b">uses <include response="a"/></prompt>'
        '<hidden><response id="a" render="no"/></hidden>'
        '<shown><response id="b"/></shown>'
    )
    html = await render_template_string(tpl)
    # a is hidden...
    assert "<hidden></hidden>" in html
    # ...but b still consumed a's response.
    assert "[mock:default] hi" in html


# -- conditions -------------------------------------------------------------
async def test_condition_true_executes():
    cfg = HPRCConfig(
        llm_client=MockLLMClient(),
        rules={"premium": lambda ctx: ctx["tier"] == "premium"},
    )
    tpl = '<prompt id="a" condition="premium">go</prompt><x><response id="a"/></x>'
    html = await render_template_string(tpl, bindings={"tier": "premium"}, config=cfg)
    assert "[mock:default] go" in html
    assert len(cfg.llm_client.calls) == 1


async def test_condition_false_skips():
    cfg = HPRCConfig(
        llm_client=MockLLMClient(),
        rules={"premium": lambda ctx: ctx["tier"] == "premium"},
    )
    tpl = '<prompt id="a" condition="premium">go</prompt><x><response id="a"/></x>'
    html = await render_template_string(tpl, bindings={"tier": "free"}, config=cfg)
    assert "<x></x>" in html
    assert len(cfg.llm_client.calls) == 0


async def test_unregistered_condition_raises_ruleerror():
    # A typo'd / unregistered rule name is a config mistake → fail loudly.
    cfg = HPRCConfig(llm_client=MockLLMClient(), rules={})
    tpl = '<prompt id="a" condition="ghost_rule">go</prompt><x><response id="a"/></x>'
    try:
        await render_template_string(tpl, bindings={}, config=cfg)
    except RuleError as exc:
        assert "ghost_rule" in str(exc) and "a" in str(exc)
        return
    raise AssertionError("expected RuleError for an unregistered condition")


async def test_rule_that_raises_skips_prompt():
    # A registered rule that raises on the data (missing key) skips just that prompt.
    cfg = HPRCConfig(
        llm_client=MockLLMClient(),
        rules={"needs_key": lambda ctx: ctx["missing"]["deep"] == 1},
    )
    tpl = '<prompt id="a" condition="needs_key">go</prompt><x><response id="a"/></x>'
    html = await render_template_string(tpl, bindings={}, config=cfg)
    assert "<x></x>" in html
    assert len(cfg.llm_client.calls) == 0


# -- model / temperature pass-through ---------------------------------------
async def test_model_and_params_pass_through():
    client = MockLLMClient()
    cfg = HPRCConfig(llm_client=client)
    tpl = (
        '<prompt id="a" model="gpt-5" temperature="0.2" max_tokens="500">hi</prompt>'
        '<x><response id="a"/></x>'
    )
    await render_template_string(tpl, config=cfg)
    call = client.calls[0]
    assert call["model"] == "gpt-5"
    assert call["temperature"] == 0.2
    assert call["max_tokens"] == 500


# -- tools ------------------------------------------------------------------
def test_normalize_callable_tool():
    def weather(city):
        "Look up weather"
        return "sunny"

    registry = normalize_tools({"weather": weather})
    assert isinstance(registry["weather"], ToolDefinition)
    assert registry["weather"].description == "Look up weather"


def test_resolve_tools_allowlist():
    registry = normalize_tools({"a": lambda: 1})
    resolved = resolve_tools(["a"], registry)
    assert [t.name for t in resolved] == ["a"]


def test_resolve_unregistered_tool_raises():
    try:
        resolve_tools(["ghost"], {})
    except ToolError:
        return
    raise AssertionError("expected ToolError")


async def test_tools_passed_to_client():
    client = MockLLMClient()
    cfg = HPRCConfig(llm_client=client, tools={"weather": lambda: "x", "crm_lookup": lambda: "y"})
    tpl = '<prompt id="a" tools="weather,crm_lookup">hi</prompt><x><response id="a"/></x>'
    await render_template_string(tpl, config=cfg)
    assert sorted(client.calls[0]["tools"]) == ["crm_lookup", "weather"]
