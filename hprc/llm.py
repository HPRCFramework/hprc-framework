"""LLM provider abstraction.

HPRC never depends on a specific provider. All providers implement the
:class:`LLMClient` interface. Shipped implementations:

* :class:`MockLLMClient` — deterministic, offline, used for tests and demos.
* :class:`OpenAIClient` — adapter over the official ``openai`` package.
* :class:`AnthropicClient` — adapter over the ``anthropic`` package (Claude).
* :class:`GeminiClient` — adapter over the ``google-genai`` package (Gemini).
* :class:`OllamaClient` — OpenAI-compatible local models (Ollama / LM Studio).
* :class:`MultiProviderClient` — routes by a ``"provider:model"`` prefix.

Each provider SDK is imported lazily, so HPRC has no hard dependency on any of
them; install only the extras you use. Adding a new provider is just a matter of
implementing :meth:`LLMClient.generate`.
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from typing import Any, Awaitable, Callable, Dict, List, Optional

from .models import ToolDefinition

# An async callback HPRC supplies so an adapter can run a tool by name with the
# arguments the model chose. Returns the tool's result as a string.
ToolExecutor = Callable[[str, Dict[str, Any]], Awaitable[str]]


class LLMClient(ABC):
    """Abstract base class every provider adapter implements."""

    @abstractmethod
    async def generate(
        self,
        prompt: str,
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        tools: Optional[List[ToolDefinition]] = None,
    ) -> str:
        """Generate a completion for ``prompt`` and return the text."""
        raise NotImplementedError

    async def generate_with_tools(
        self,
        prompt: str,
        *,
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        tools: Optional[List[ToolDefinition]] = None,
        execute: Optional[ToolExecutor] = None,
    ) -> Optional[str]:
        """Run a **single tool iteration** and return the final text.

        One iteration: call the model with the prompt + tool schemas. If the model
        asks to call one or more tools, run them via ``execute(name, args)``, feed
        the results back, and call the model once more — that response is the
        answer. Returns the model's text, or ``None`` if the model is *still*
        asking for a tool after that single iteration (the renderer then leaves the
        response empty). A multi-step / agent loop is on the roadmap.

        The default implementation has no tool support and simply returns text;
        adapters that support tool calling override this.
        """
        return await self.generate(
            prompt, model=model, temperature=temperature,
            max_tokens=max_tokens, tools=tools,
        )


class MockLLMClient(LLMClient):
    """Deterministic, offline LLM for tests, demos and local development.

    It echoes a compact, reproducible summary of the request so that callers can
    assert on prompt construction, model selection, tools and parameters without
    network access. A custom ``responder`` callable may be supplied to script
    specific outputs.

    **Not for production** — it never calls a real model. Swap in a real provider
    (:class:`OpenAIClient`, :class:`AnthropicClient`, :class:`GeminiClient`,
    :class:`OllamaClient`) for actual generated output.
    """

    def __init__(self, responder=None, tool_plan=None) -> None:
        self.responder = responder
        # Optional script for generate_with_tools: a list whose entries are either
        # a list of (tool_name, args) to "call" this turn, or a str final answer.
        self.tool_plan = tool_plan
        self.calls: list = []
        self.tool_results: list = []  # (name, args, result) recorded during a loop

    async def generate(
        self,
        prompt: str,
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        tools: Optional[List[ToolDefinition]] = None,
    ) -> str:
        tool_names = [t.name for t in (tools or [])]
        self.calls.append(
            {
                "prompt": prompt,
                "model": model,
                "temperature": temperature,
                "max_tokens": max_tokens,
                "tools": tool_names,
            }
        )
        if self.responder is not None:
            result = self.responder(prompt, model, temperature, max_tokens, tools)
            return result
        parts = [f"[mock:{model or 'default'}] {prompt.strip()}"]
        if tool_names:
            parts.append(f"(tools: {', '.join(tool_names)})")
        return " ".join(parts)

    async def generate_with_tools(
        self, prompt, *, model=None, temperature=None, max_tokens=None,
        tools=None, execute=None,
    ) -> Optional[str]:
        # No script (or no executor) → behave like a plain text generation.
        if not self.tool_plan or execute is None:
            return await self.generate(
                prompt, model=model, temperature=temperature,
                max_tokens=max_tokens, tools=tools,
            )
        self.calls.append({"prompt": prompt, "model": model, "temperature": temperature,
                           "max_tokens": max_tokens, "tools": [t.name for t in (tools or [])]})
        self.tool_results = []
        plan = list(self.tool_plan)
        if not plan:
            return None
        first = plan.pop(0)
        if isinstance(first, str):
            return first  # the model answered immediately, no tool call
        # single iteration: execute the one-or-more tool calls, then take the final turn
        for name, args in first:
            result = await execute(name, dict(args or {}))
            self.tool_results.append((name, dict(args or {}), result))
        if not plan:
            return None
        final = plan.pop(0)
        return final if isinstance(final, str) else None  # final tool call → don't render


class OpenAIClient(LLMClient):
    """Adapter over the official ``openai`` async client.

    The ``openai`` package is imported lazily, so importing HPRC does not require
    it. Tools are forwarded as OpenAI-style function tool schemas when provided.
    """

    def __init__(self, api_key: Optional[str] = None, default_model: str = "gpt-4o-mini", **client_kwargs):
        self.api_key = api_key
        self.default_model = default_model
        self._client_kwargs = client_kwargs
        self._client = None

    def _get_client(self):
        if self._client is None:
            try:
                from openai import AsyncOpenAI  # type: ignore
            except ImportError as exc:  # pragma: no cover - depends on env
                raise ImportError(
                    "OpenAIClient requires the 'openai' package. "
                    "Install it with `pip install openai`."
                ) from exc
            kwargs = dict(self._client_kwargs)
            if self.api_key:
                kwargs["api_key"] = self.api_key
            self._client = AsyncOpenAI(**kwargs)
        return self._client

    @staticmethod
    def _tool_schemas(tools: Optional[List[ToolDefinition]]):
        schemas = []
        for tool in tools or []:
            schemas.append(
                {
                    "type": "function",
                    "function": {
                        "name": tool.name,
                        "description": tool.description or "",
                        "parameters": tool.parameters
                        or {"type": "object", "properties": {}},
                    },
                }
            )
        return schemas

    async def generate(
        self,
        prompt: str,
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        tools: Optional[List[ToolDefinition]] = None,
    ) -> str:
        client = self._get_client()
        kwargs = {
            "model": model or self.default_model,
            "messages": [{"role": "user", "content": prompt}],
        }
        if temperature is not None:
            kwargs["temperature"] = temperature
        if max_tokens is not None:
            kwargs["max_tokens"] = max_tokens
        schemas = self._tool_schemas(tools)
        if schemas:
            kwargs["tools"] = schemas

        response = await client.chat.completions.create(**kwargs)
        return response.choices[0].message.content or ""

    async def generate_with_tools(
        self, prompt, *, model=None, temperature=None, max_tokens=None,
        tools=None, execute=None,
    ) -> Optional[str]:
        schemas = self._tool_schemas(tools)
        if not schemas or execute is None:
            return await self.generate(prompt, model=model, temperature=temperature,
                                       max_tokens=max_tokens, tools=tools)
        client = self._get_client()
        base = {"model": model or self.default_model, "tools": schemas}
        if temperature is not None:
            base["temperature"] = temperature
        if max_tokens is not None:
            base["max_tokens"] = max_tokens
        messages = [{"role": "user", "content": prompt}]

        # First turn: the model answers, or requests one or more tool calls.
        msg = (await client.chat.completions.create(messages=messages, **base)).choices[0].message
        calls = getattr(msg, "tool_calls", None)
        if not calls:
            return msg.content or ""

        # Single iteration: execute the requested tools, feed the results back.
        messages.append({
            "role": "assistant", "content": msg.content or None,
            "tool_calls": [
                {"id": c.id, "type": "function",
                 "function": {"name": c.function.name, "arguments": c.function.arguments}}
                for c in calls
            ],
        })
        for c in calls:
            try:
                args = json.loads(c.function.arguments or "{}")
            except (ValueError, TypeError):
                args = {}
            result = await execute(c.function.name, args)
            messages.append({"role": "tool", "tool_call_id": c.id, "content": str(result)})

        # Final turn: render its text; if it is still a tool call, render nothing.
        final = (await client.chat.completions.create(messages=messages, **base)).choices[0].message
        if getattr(final, "tool_calls", None):
            return None
        return final.content or ""


class AnthropicClient(LLMClient):
    """Adapter over Anthropic's async Messages API (Claude).

    The ``anthropic`` package is imported lazily. Anthropic *requires*
    ``max_tokens``, so a ``default_max_tokens`` is supplied when a prompt does
    not specify one. Tools are forwarded in Anthropic's
    ``{"name", "description", "input_schema"}`` shape.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        default_model: str = "claude-sonnet-4-6",
        default_max_tokens: int = 1024,
        **client_kwargs,
    ):
        self.api_key = api_key
        self.default_model = default_model
        self.default_max_tokens = default_max_tokens
        self._client_kwargs = client_kwargs
        self._client = None

    def _get_client(self):
        if self._client is None:
            try:
                from anthropic import AsyncAnthropic  # type: ignore
            except ImportError as exc:  # pragma: no cover - depends on env
                raise ImportError(
                    "AnthropicClient requires the 'anthropic' package. "
                    "Install it with `pip install anthropic`."
                ) from exc
            kwargs = dict(self._client_kwargs)
            if self.api_key:
                kwargs["api_key"] = self.api_key
            self._client = AsyncAnthropic(**kwargs)
        return self._client

    @staticmethod
    def _tool_schemas(tools: Optional[List[ToolDefinition]]):
        schemas = []
        for tool in tools or []:
            schemas.append(
                {
                    "name": tool.name,
                    "description": tool.description or "",
                    "input_schema": tool.parameters
                    or {"type": "object", "properties": {}},
                }
            )
        return schemas

    async def generate(
        self,
        prompt: str,
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        tools: Optional[List[ToolDefinition]] = None,
    ) -> str:
        client = self._get_client()
        kwargs = {
            "model": model or self.default_model,
            "max_tokens": max_tokens or self.default_max_tokens,
            "messages": [{"role": "user", "content": prompt}],
        }
        if temperature is not None:
            kwargs["temperature"] = temperature
        schemas = self._tool_schemas(tools)
        if schemas:
            kwargs["tools"] = schemas

        response = await client.messages.create(**kwargs)
        # Response content is a list of typed blocks; concatenate the text ones.
        return "".join(
            getattr(block, "text", "")
            for block in getattr(response, "content", [])
            if getattr(block, "type", None) == "text"
        )

    @staticmethod
    def _block_to_dict(block):
        kind = getattr(block, "type", None)
        if kind == "text":
            return {"type": "text", "text": getattr(block, "text", "")}
        if kind == "tool_use":
            return {"type": "tool_use", "id": block.id, "name": block.name,
                    "input": getattr(block, "input", {}) or {}}
        return {"type": kind}

    async def generate_with_tools(
        self, prompt, *, model=None, temperature=None, max_tokens=None,
        tools=None, execute=None,
    ) -> Optional[str]:
        schemas = self._tool_schemas(tools)
        if not schemas or execute is None:
            return await self.generate(prompt, model=model, temperature=temperature,
                                       max_tokens=max_tokens, tools=tools)
        client = self._get_client()
        base = {"model": model or self.default_model,
                "max_tokens": max_tokens or self.default_max_tokens, "tools": schemas}
        if temperature is not None:
            base["temperature"] = temperature

        def text_of(content):
            return "".join(getattr(b, "text", "") for b in content
                           if getattr(b, "type", None) == "text")

        messages = [{"role": "user", "content": prompt}]

        # First turn: the model answers, or requests one or more tool calls.
        content = list(getattr(await client.messages.create(messages=messages, **base), "content", []))
        tool_uses = [b for b in content if getattr(b, "type", None) == "tool_use"]
        if not tool_uses:
            return text_of(content)

        # Single iteration: execute the requested tools, feed the results back.
        messages.append({"role": "assistant", "content": [self._block_to_dict(b) for b in content]})
        results = []
        for tu in tool_uses:
            result = await execute(tu.name, dict(getattr(tu, "input", {}) or {}))
            results.append({"type": "tool_result", "tool_use_id": tu.id, "content": str(result)})
        messages.append({"role": "user", "content": results})

        # Final turn: render its text; if it is still a tool call, render nothing.
        final = list(getattr(await client.messages.create(messages=messages, **base), "content", []))
        if any(getattr(b, "type", None) == "tool_use" for b in final):
            return None
        return text_of(final)


class GeminiClient(LLMClient):
    """Adapter over Google's ``google-genai`` async API (Gemini).

    The ``google-genai`` package is imported lazily. Generation parameters are
    passed under a ``config`` mapping, with ``max_tokens`` mapped to Gemini's
    ``max_output_tokens``. Tool *schemas* are forwarded as function declarations,
    but the tool-execution loop (``generate_with_tools``) is not yet implemented
    for Gemini — it falls back to a single text generation. Tool execution is
    currently supported by :class:`OpenAIClient` (and :class:`OllamaClient`) and
    :class:`AnthropicClient`.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        default_model: str = "gemini-2.0-flash",
        **client_kwargs,
    ):
        self.api_key = api_key
        self.default_model = default_model
        self._client_kwargs = client_kwargs
        self._client = None

    def _get_client(self):
        if self._client is None:
            try:
                from google import genai  # type: ignore
            except ImportError as exc:  # pragma: no cover - depends on env
                raise ImportError(
                    "GeminiClient requires the 'google-genai' package. "
                    "Install it with `pip install google-genai`."
                ) from exc
            kwargs = dict(self._client_kwargs)
            if self.api_key:
                kwargs["api_key"] = self.api_key
            self._client = genai.Client(**kwargs)
        return self._client

    @staticmethod
    def _tool_schemas(tools: Optional[List[ToolDefinition]]):
        declarations = []
        for tool in tools or []:
            declarations.append(
                {
                    "name": tool.name,
                    "description": tool.description or "",
                    "parameters": tool.parameters
                    or {"type": "object", "properties": {}},
                }
            )
        return [{"function_declarations": declarations}] if declarations else []

    async def generate(
        self,
        prompt: str,
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        tools: Optional[List[ToolDefinition]] = None,
    ) -> str:
        client = self._get_client()
        config: dict = {}
        if temperature is not None:
            config["temperature"] = temperature
        if max_tokens is not None:
            config["max_output_tokens"] = max_tokens
        schemas = self._tool_schemas(tools)
        if schemas:
            config["tools"] = schemas

        kwargs = {"model": model or self.default_model, "contents": prompt}
        if config:
            kwargs["config"] = config

        response = await client.aio.models.generate_content(**kwargs)
        return getattr(response, "text", "") or ""


class OllamaClient(OpenAIClient):
    """Local model adapter for OpenAI-compatible endpoints (Ollama, LM Studio).

    Ollama and LM Studio both expose an OpenAI-compatible HTTP API, so this is
    simply an :class:`OpenAIClient` pointed at a local ``base_url``. Defaults
    target Ollama (``http://localhost:11434/v1``); for LM Studio use
    ``base_url="http://localhost:1234/v1"``.
    """

    def __init__(
        self,
        base_url: str = "http://localhost:11434/v1",
        api_key: str = "not-needed",
        default_model: str = "llama3",
        **client_kwargs,
    ):
        super().__init__(
            api_key=api_key,
            default_model=default_model,
            base_url=base_url,
            **client_kwargs,
        )


class MultiProviderClient(LLMClient):
    """Routes each call to a sub-client based on a ``"provider:model"`` prefix.

    Example::

        client = MultiProviderClient(
            {"openai": OpenAIClient(), "anthropic": AnthropicClient()},
            default="openai",
        )
        # a prompt with model="anthropic:claude-sonnet-4-6" routes to Anthropic
        # and is sent as model="claude-sonnet-4-6"; a prompt with model="gpt-5"
        # (no prefix) routes to the default provider.

    This is the only mechanism by which the ``model`` attribute selects a
    *provider* rather than just a model variant.
    """

    def __init__(
        self,
        clients: dict,
        default: Optional[str] = None,
        separator: str = ":",
    ):
        if not clients:
            raise ValueError("MultiProviderClient requires at least one sub-client.")
        self._clients = dict(clients)
        self._default = default
        self._sep = separator

    def _route(self, model: Optional[str]):
        provider = self._default
        real_model = model
        if model and self._sep in model:
            provider, _, real_model = model.partition(self._sep)
        if provider is None:
            raise ValueError(
                "No provider specified and no default set for MultiProviderClient. "
                f"Use a '<provider>{self._sep}<model>' model value or set default=."
            )
        if provider not in self._clients:
            raise ValueError(
                f"Unknown provider {provider!r}. "
                f"Registered providers: {sorted(self._clients)}."
            )
        return self._clients[provider], (real_model or None)

    async def generate(
        self,
        prompt: str,
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        tools: Optional[List[ToolDefinition]] = None,
    ) -> str:
        client, real_model = self._route(model)
        return await client.generate(
            prompt=prompt,
            model=real_model,
            temperature=temperature,
            max_tokens=max_tokens,
            tools=tools,
        )

    async def generate_with_tools(
        self, prompt, *, model=None, temperature=None, max_tokens=None,
        tools=None, execute=None,
    ) -> Optional[str]:
        client, real_model = self._route(model)
        return await client.generate_with_tools(
            prompt, model=real_model, temperature=temperature,
            max_tokens=max_tokens, tools=tools, execute=execute,
        )
