"""Provider adapter conformance tests.

Each shipped LLMClient is exercised against a *fake* SDK transport (injected by
setting the cached ``_client`` so the lazy import is bypassed). No network, no
API keys, no provider SDKs required. These tests are the early-warning system:
if a provider SDK changes its request shape or response location, the failure
shows up here in the adapter — never in the renderer.
"""

import types

import pytest

from hprc import (
    AnthropicClient,
    GeminiClient,
    MockLLMClient,
    MultiProviderClient,
    OllamaClient,
    OpenAIClient,
    HPRCConfig,
    render_template_string,
)
from hprc.models import ToolDefinition

TOOL = ToolDefinition(
    name="t",
    func=lambda: 1,
    description="d",
    parameters={"type": "object", "properties": {}},
)


# ---------------------------------------------------------------------------
# Fake SDK transports
# ---------------------------------------------------------------------------
def fake_openai(rec):
    async def create(**kwargs):
        rec.update(kwargs)
        msg = types.SimpleNamespace(content="OAI_OK")
        return types.SimpleNamespace(choices=[types.SimpleNamespace(message=msg)])

    return types.SimpleNamespace(
        chat=types.SimpleNamespace(completions=types.SimpleNamespace(create=create))
    )


def fake_anthropic(rec):
    async def create(**kwargs):
        rec.update(kwargs)
        block = types.SimpleNamespace(type="text", text="CLAUDE_OK")
        # include a non-text block to prove filtering works
        other = types.SimpleNamespace(type="tool_use", text="IGNORED")
        return types.SimpleNamespace(content=[block, other])

    return types.SimpleNamespace(messages=types.SimpleNamespace(create=create))


def fake_gemini(rec):
    async def generate_content(**kwargs):
        rec.update(kwargs)
        return types.SimpleNamespace(text="GEMINI_OK")

    return types.SimpleNamespace(
        aio=types.SimpleNamespace(
            models=types.SimpleNamespace(generate_content=generate_content)
        )
    )


# ---------------------------------------------------------------------------
# OpenAI
# ---------------------------------------------------------------------------
async def test_openai_adapter_maps_request_and_extracts_text():
    rec = {}
    c = OpenAIClient(api_key="x")
    c._client = fake_openai(rec)
    out = await c.generate("hi", model="gpt-x", temperature=0.3, max_tokens=42, tools=[TOOL])
    assert out == "OAI_OK"
    assert rec["model"] == "gpt-x"
    assert rec["temperature"] == 0.3
    assert rec["max_tokens"] == 42
    assert rec["messages"] == [{"role": "user", "content": "hi"}]
    assert rec["tools"][0]["type"] == "function"
    assert rec["tools"][0]["function"]["name"] == "t"


# ---------------------------------------------------------------------------
# Anthropic
# ---------------------------------------------------------------------------
async def test_anthropic_adapter_defaults_max_tokens_and_joins_text_blocks():
    rec = {}
    c = AnthropicClient(api_key="x", default_max_tokens=777)
    c._client = fake_anthropic(rec)
    out = await c.generate("hi", model="claude-x", temperature=0.1, tools=[TOOL])
    assert out == "CLAUDE_OK"  # non-text block filtered out
    assert rec["model"] == "claude-x"
    assert rec["max_tokens"] == 777  # required field defaulted
    assert rec["temperature"] == 0.1
    assert rec["messages"] == [{"role": "user", "content": "hi"}]
    assert rec["tools"][0]["name"] == "t"
    assert "input_schema" in rec["tools"][0]


async def test_anthropic_explicit_max_tokens_wins():
    rec = {}
    c = AnthropicClient(api_key="x", default_max_tokens=777)
    c._client = fake_anthropic(rec)
    await c.generate("hi", max_tokens=10)
    assert rec["max_tokens"] == 10


# ---------------------------------------------------------------------------
# Gemini
# ---------------------------------------------------------------------------
async def test_gemini_adapter_maps_config_and_renames_max_tokens():
    rec = {}
    c = GeminiClient(api_key="x")
    c._client = fake_gemini(rec)
    out = await c.generate("hi", model="gemini-x", temperature=0.5, max_tokens=64, tools=[TOOL])
    assert out == "GEMINI_OK"
    assert rec["model"] == "gemini-x"
    assert rec["contents"] == "hi"
    assert rec["config"]["temperature"] == 0.5
    assert rec["config"]["max_output_tokens"] == 64  # renamed param
    assert rec["config"]["tools"][0]["function_declarations"][0]["name"] == "t"


# ---------------------------------------------------------------------------
# Ollama / LM Studio (OpenAI-compatible)
# ---------------------------------------------------------------------------
async def test_ollama_is_openai_compatible_with_base_url():
    c = OllamaClient(base_url="http://localhost:11434/v1")
    assert isinstance(c, OpenAIClient)
    assert c._client_kwargs["base_url"] == "http://localhost:11434/v1"
    rec = {}
    c._client = fake_openai(rec)
    out = await c.generate("hi", model="llama3")
    assert out == "OAI_OK"
    assert rec["model"] == "llama3"


# ---------------------------------------------------------------------------
# MultiProviderClient routing
# ---------------------------------------------------------------------------
async def test_multiprovider_routes_by_prefix():
    oai = MockLLMClient(responder=lambda *a: "from-openai")
    ant = MockLLMClient(responder=lambda *a: "from-anthropic")
    mp = MultiProviderClient({"openai": oai, "anthropic": ant}, default="openai")

    out = await mp.generate("hi", model="anthropic:claude-x")
    assert out == "from-anthropic"
    assert ant.calls[0]["model"] == "claude-x"  # prefix stripped before forwarding

    out2 = await mp.generate("hi", model="gpt-5")  # no prefix -> default provider
    assert out2 == "from-openai"
    assert oai.calls[0]["model"] == "gpt-5"


async def test_multiprovider_unknown_provider_raises():
    mp = MultiProviderClient({"openai": MockLLMClient()})
    with pytest.raises(ValueError):
        await mp.generate("hi", model="mistral:big")


async def test_multiprovider_no_default_no_prefix_raises():
    mp = MultiProviderClient({"openai": MockLLMClient()})  # no default
    with pytest.raises(ValueError):
        await mp.generate("hi", model="gpt-5")


def test_multiprovider_requires_clients():
    with pytest.raises(ValueError):
        MultiProviderClient({})


# ---------------------------------------------------------------------------
# model_aliases resolution in the renderer
# ---------------------------------------------------------------------------
async def test_model_alias_resolved_before_call():
    client = MockLLMClient()
    cfg = HPRCConfig(llm_client=client, model_aliases={"summarizer": "gpt-5"})
    tpl = '<prompt id="a" model="summarizer">hi</prompt><x><response id="a"/></x>'
    await render_template_string(tpl, config=cfg)
    assert client.calls[0]["model"] == "gpt-5"


async def test_model_alias_with_multiprovider_routing():
    oai = MockLLMClient(responder=lambda *a: "ok")
    ant = MockLLMClient(responder=lambda *a: "ok")
    mp = MultiProviderClient({"openai": oai, "anthropic": ant}, default="openai")
    cfg = HPRCConfig(
        llm_client=mp,
        model_aliases={"summarizer": "anthropic:claude-sonnet-4-6"},
    )
    tpl = '<prompt id="a" model="summarizer">hi</prompt><x><response id="a"/></x>'
    await render_template_string(tpl, config=cfg)
    assert ant.calls[0]["model"] == "claude-sonnet-4-6"
    assert not oai.calls