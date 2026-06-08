"""Tool registration and resolution.

Tools are external to templates: a template only lists allowlisted tool *names*
(``tools="weather,crm_lookup"``) and the application registers the actual
callables. HPRC resolves the names to :class:`~hprc.models.ToolDefinition`
objects and hands them to the LLM client.

HPRC deliberately does **not** implement an agent loop. It provides a generic,
provider-independent tool abstraction; how a provider exposes/calls the tools is
up to the concrete :class:`~hprc.llm.LLMClient`.
"""

from __future__ import annotations

import inspect
from typing import Any, Dict, List

from .models import ToolDefinition


class ToolError(Exception):
    """Raised when a template references a tool that was never registered."""


def build_tool_definition(name: str, value: Any) -> ToolDefinition:
    """Coerce a registered tool value into a :class:`ToolDefinition`.

    Accepts either an already-built :class:`ToolDefinition` or a bare callable
    (whose docstring becomes the description).
    """
    if isinstance(value, ToolDefinition):
        return value
    if callable(value):
        return ToolDefinition(
            name=name,
            func=value,
            description=(inspect.getdoc(value) or "").strip(),
        )
    raise ToolError(f"Tool '{name}' must be a callable or ToolDefinition.")


def normalize_tools(tools: Dict[str, Any]) -> Dict[str, ToolDefinition]:
    """Normalize a registry of ``{name: callable | ToolDefinition}``."""
    return {name: build_tool_definition(name, value) for name, value in (tools or {}).items()}


def resolve_tools(
    names: List[str],
    registry: Dict[str, ToolDefinition],
) -> List[ToolDefinition]:
    """Resolve a list of allowlisted tool names against the registry.

    Raises :class:`ToolError` for any name that is not registered, enforcing the
    allowlist.
    """
    resolved: List[ToolDefinition] = []
    for name in names:
        name = name.strip()
        if not name:
            continue
        if name not in registry:
            raise ToolError(
                f"Tool '{name}' is referenced in a template but was not registered."
            )
        resolved.append(registry[name])
    return resolved


async def invoke_tool(tool: ToolDefinition, *args: Any, **kwargs: Any) -> Any:
    """Invoke a tool, awaiting it if it is a coroutine function.

    Provided as a convenience for LLM clients that choose to execute tools.
    """
    result = tool.func(*args, **kwargs)
    if inspect.isawaitable(result):
        return await result
    return result
