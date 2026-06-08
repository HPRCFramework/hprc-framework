"""HPRC Framework — HTML Prompt Response Construction.

Declarative AI rendering for web applications. Developers write **SPREP templates**
(Simple Prompt Response Embedded Pages) — HTML with embedded ``<prompt>``/``<response>``
elements — and the HPRC Framework renders them: prompt construction, dependency
resolution, rule evaluation, tool invocation, caching, async execution, and
response rendering.

Created by Rajesh Ramani.

Quick start::

    import hprc
    from hprc import HPRCConfig, MockLLMClient

    config = HPRCConfig(llm_client=MockLLMClient())
    html = await hprc.render_template_string(
        template_html="<response id='hi'/><prompt id='hi'>Say hi</prompt>",
        config=config,
    )
"""

from .cache import Cache, MemoryCache, NullCache, build_cache_key, parse_ttl
from .config import HPRCConfig
from .dependency_graph import build_graph, topological_levels
from .llm import (
    AnthropicClient,
    GeminiClient,
    LLMClient,
    MockLLMClient,
    MultiProviderClient,
    OllamaClient,
    OpenAIClient,
)
from .models import (
    IncludeDefinition,
    Node,
    PromptDefinition,
    RenderContext,
    ResponseDefinition,
    TemplateDefinition,
    ToolDefinition,
)
from .parser import parse, parse_file
from .renderer import (
    Renderer,
    render_string,
    render_template,
    render_template_string,
)

__version__ = "0.1.0"

__all__ = [
    "__version__",
    # Entry points
    "render_template",
    "render_template_string",
    "render_string",
    "Renderer",
    # Config + providers
    "HPRCConfig",
    "LLMClient",
    "MockLLMClient",
    "OpenAIClient",
    "AnthropicClient",
    "GeminiClient",
    "OllamaClient",
    "MultiProviderClient",
    # Cache
    "Cache",
    "MemoryCache",
    "NullCache",
    "build_cache_key",
    "parse_ttl",
    # Parser / graph
    "parse",
    "parse_file",
    "build_graph",
    "topological_levels",
    # Models
    "Node",
    "PromptDefinition",
    "ResponseDefinition",
    "IncludeDefinition",
    "TemplateDefinition",
    "RenderContext",
    "ToolDefinition",
]
