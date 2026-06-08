"""Pydantic data models for HPRC.

These models describe the parsed template, prompt/response definitions, the
runtime render context, tool registrations and the public configuration object.

Everything that flows through the renderer is described here so that the rest of
the library can stay declarative and provider-independent.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------------------
# Template node tree
# ---------------------------------------------------------------------------
class Node(BaseModel):
    """A single node in the parsed template tree.

    ``type`` is either ``"text"`` (a raw text run) or ``"element"`` (a tag).
    Elements carry a ``tag`` name, an attribute dict and ordered ``children``.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    type: str
    tag: Optional[str] = None
    attrs: Dict[str, Optional[str]] = Field(default_factory=dict)
    children: List["Node"] = Field(default_factory=list)
    text: str = ""


# ---------------------------------------------------------------------------
# Prompt / Response / Include definitions
# ---------------------------------------------------------------------------
class IncludeDefinition(BaseModel):
    """An ``<include response="..."/>`` or ``<include prompt="..."/>`` element."""

    response: Optional[str] = None
    prompt: Optional[str] = None


class PromptDefinition(BaseModel):
    """A ``<prompt>`` block.

    Prompts are *tacit*: they are executable but never rendered into the final
    HTML. The ``body`` holds the inner node tree (text, ``<fill>``, ``<param>``
    and ``<include>``) that is resolved into the final prompt string at render
    time.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    id: str
    model: Optional[str] = None
    condition: Optional[str] = None
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None
    is_async: bool = False
    cache: Optional[str] = None
    tools: List[str] = Field(default_factory=list)
    body: List[Node] = Field(default_factory=list)


class ResponseDefinition(BaseModel):
    """A ``<response>`` placeholder element bound to a prompt ``id``."""

    id: str
    render: bool = True


# ---------------------------------------------------------------------------
# Template
# ---------------------------------------------------------------------------
class TemplateDefinition(BaseModel):
    """A fully parsed template.

    ``root`` is the document node tree used to produce the final HTML.
    ``prompts`` and ``responses`` are convenience indexes collected while
    parsing.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    root: List[Node] = Field(default_factory=list)
    prompts: Dict[str, PromptDefinition] = Field(default_factory=dict)
    responses: List[ResponseDefinition] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------
class ToolDefinition(BaseModel):
    """A registered, allowlisted tool.

    HPRC does not build an agent loop; it simply hands the resolved tool
    definitions to the LLM client, which decides how (or whether) to use them.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    name: str
    func: Callable[..., Any]
    description: str = ""
    parameters: Dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Render context
# ---------------------------------------------------------------------------
class RenderContext(BaseModel):
    """Everything needed to resolve fills and execute prompts for one render."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    bindings: Dict[str, Any] = Field(default_factory=dict)
    request: Dict[str, Any] = Field(default_factory=dict)
    rules: Dict[str, Callable[[Dict[str, Any]], bool]] = Field(default_factory=dict)
    tools: Dict[str, ToolDefinition] = Field(default_factory=dict)
    # When True, each sequential (non-async) prompt receives the responses of the
    # earlier sequential prompts in this render, prepended as context.
    gather_responses: bool = False
    # Filled in as prompts execute.
    responses: Dict[str, str] = Field(default_factory=dict)
    skipped: Dict[str, bool] = Field(default_factory=dict)
    # Ordered (id, response) of completed non-async prompts, for gather_responses.
    gathered: List[Any] = Field(default_factory=list)


Node.model_rebuild()
