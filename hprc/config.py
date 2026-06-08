"""Public configuration object.

The application developer builds a :class:`HPRCConfig` and hands it to
:func:`hprc.render_template`. It bundles the four pluggable pieces of the
framework: the LLM client, the rule registry, the tool registry and the cache.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .cache import Cache, MemoryCache
from .llm import LLMClient, MockLLMClient
from .models import ToolDefinition
from .tools import normalize_tools


class HPRCConfig(BaseModel):
    """Bundle of the pluggable components a render needs.

    * ``llm_client`` — any :class:`~hprc.llm.LLMClient` (defaults to
      :class:`~hprc.llm.MockLLMClient` for offline use).
    * ``rules`` — ``{name: predicate(context) -> bool}``.
    * ``tools`` — ``{name: callable | ToolDefinition}``; normalized on init.
    * ``cache`` — any :class:`~hprc.cache.Cache` (defaults to
      :class:`~hprc.cache.MemoryCache`).
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    llm_client: LLMClient = Field(default_factory=MockLLMClient)
    rules: Dict[str, Callable[[Dict[str, Any]], bool]] = Field(default_factory=dict)
    tools: Dict[str, Any] = Field(default_factory=dict)
    cache: Optional[Cache] = Field(default_factory=MemoryCache)
    # Optional logical-name -> concrete-model map, resolved before each call.
    # Lets templates use portable names (e.g. model="summarizer") or route via a
    # MultiProviderClient (e.g. {"summarizer": "anthropic:claude-sonnet-4-6"}).
    model_aliases: Dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _normalize(self) -> "HPRCConfig":
        # Coerce bare callables into ToolDefinition objects once, up front.
        self.tools = normalize_tools(self.tools)
        if self.cache is None:
            self.cache = MemoryCache()
        return self

    @property
    def tool_registry(self) -> Dict[str, ToolDefinition]:
        """The normalized tool registry (``{name: ToolDefinition}``)."""
        return self.tools  # type: ignore[return-value]
