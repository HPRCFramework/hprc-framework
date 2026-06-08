"""Bounded tool-execution loop tests.

Uses MockLLMClient's ``tool_plan`` to script the model: each entry is either a
list of ``(tool_name, args)`` to "call" that round, or a final text string. The
renderer builds the executor from the prompt's allowlisted tools and runs the
real Python functions.
"""

from hprc import HPRCConfig, MockLLMClient, render_template_string


async def test_tool_is_executed_and_final_text_rendered():
    seen = []

    def crm_lookup(customer_id):
        seen.append(customer_id)
        return f"notes for {customer_id}"

    # round 1: model calls crm_lookup; round 2: model returns final text
    client = MockLLMClient(tool_plan=[[("crm_lookup", {"customer_id": "1001"})], "DONE"])
    cfg = HPRCConfig(llm_client=client, tools={"crm_lookup": crm_lookup})
    tpl = '<prompt id="a" tools="crm_lookup">summarize</prompt><x><response id="a"/></x>'

    html = await render_template_string(tpl, config=cfg)

    assert seen == ["1001"]  # the real Python tool ran, with the model's args
    assert client.tool_results[0] == ("crm_lookup", {"customer_id": "1001"}, "notes for 1001")
    assert "<x>DONE</x>" in html  # the model's final text is rendered


async def test_async_tool_function_is_awaited():
    async def fetch(city):
        return f"weather in {city}: sunny"

    client = MockLLMClient(tool_plan=[[("fetch", {"city": "London"})], "FORECAST"])
    cfg = HPRCConfig(llm_client=client, tools={"fetch": fetch})
    tpl = '<prompt id="a" tools="fetch">forecast</prompt><x><response id="a"/></x>'

    html = await render_template_string(tpl, config=cfg)
    assert client.tool_results[0][2] == "weather in London: sunny"
    assert "<x>FORECAST</x>" in html


async def test_unfinished_iteration_renders_empty():
    # After the single iteration the model is still asking for a tool (no final
    # text turn) -> the prompt renders nothing.
    client = MockLLMClient(tool_plan=[[("t", {})]])  # a tool round, then no final text
    cfg = HPRCConfig(llm_client=client, tools={"t": lambda: "r"})
    tpl = '<prompt id="a" tools="t">go</prompt><x><response id="a"/></x>'

    html = await render_template_string(tpl, config=cfg)
    assert "<x></x>" in html  # nothing rendered


async def test_unregistered_tool_call_returns_error_to_model():
    # The model asks for a tool the prompt didn't allow-list -> executor returns
    # an error string (fed back to the model), and the loop still completes.
    client = MockLLMClient(tool_plan=[[("ghost", {"x": 1})], "RECOVERED"])
    cfg = HPRCConfig(llm_client=client, tools={"real": lambda: "r"})
    tpl = '<prompt id="a" tools="real">go</prompt><x><response id="a"/></x>'

    html = await render_template_string(tpl, config=cfg)
    name, _, result = client.tool_results[0]
    assert name == "ghost"
    assert "not available" in result
    assert "<x>RECOVERED</x>" in html


async def test_single_iteration_only_one_round_executes():
    # The model asks for a tool, then (after results) asks for ANOTHER tool. Only
    # the first round runs; the second tool call is NOT executed, and nothing renders.
    ran = []

    def a(**_):
        ran.append("a")
        return "ra"

    def b(**_):
        ran.append("b")
        return "rb"

    client = MockLLMClient(tool_plan=[[("a", {})], [("b", {})]])
    cfg = HPRCConfig(llm_client=client, tools={"a": a, "b": b})
    tpl = '<prompt id="p" tools="a,b">go</prompt><x><response id="p"/></x>'

    html = await render_template_string(tpl, config=cfg)
    assert ran == ["a"]  # only the first round executed; "b" was never called
    assert "<x></x>" in html  # final turn was still a tool call → nothing rendered


async def test_no_tool_plan_falls_back_to_plain_text():
    # A prompt with tools but a model that doesn't request any -> plain generation.
    client = MockLLMClient()  # no tool_plan
    cfg = HPRCConfig(llm_client=client, tools={"t": lambda: "r"})
    tpl = '<prompt id="a" tools="t">hello</prompt><x><response id="a"/></x>'

    html = await render_template_string(tpl, config=cfg)
    assert "[mock:default] hello" in html
