"""The HPRC renderer.

This is the orchestration core. Given a parsed template, a request, an
application context and a :class:`~hprc.config.HPRCConfig`, it:

1. normalizes the request,
2. evaluates each prompt's ``condition`` rule to decide what executes,
3. builds the prompt dependency graph and its concurrent execution levels,
4. resolves fills / params / includes into final prompt text,
5. executes prompts (with caching) concurrently within each level,
6. serializes the document, injecting responses and leaving prompts tacit.
"""

from __future__ import annotations

import asyncio
import html
from typing import Any, Dict, List, Optional

from .cache import build_cache_key, parse_ttl
from .config import HPRCConfig
from .dependency_graph import build_graph, topological_levels
from .models import Node, PromptDefinition, RenderContext, TemplateDefinition
from .parser import _as_bool, parse_file
from .request_context import normalize_request, resolve_path
from .rules import RuleError, evaluate_rule
from .tools import invoke_tool, resolve_tools

# Tags that HPRC interprets rather than passing through as literal HTML.
_VOID = {
    "area", "base", "br", "col", "embed", "hr", "img", "input",
    "link", "meta", "source", "track", "wbr",
}


class Renderer:
    """Stateless-per-call renderer driven by a :class:`HPRCConfig`."""

    def __init__(self, config: HPRCConfig) -> None:
        self.config = config

    # ------------------------------------------------------------------
    # Namespace + value resolution
    # ------------------------------------------------------------------
    @staticmethod
    def _namespace(rc: RenderContext) -> Dict[str, Any]:
        """The root namespace fills resolve against (bindings + request)."""
        ns = dict(rc.bindings)
        ns["request"] = rc.request
        return ns

    def _resolve_fill(self, path: str, rc: RenderContext) -> Any:
        return resolve_path(self._namespace(rc), path.strip())

    def _resolve_param(self, name: str, rc: RenderContext) -> Any:
        query = rc.request.get("query", {}) if rc.request else {}
        return query.get(name.strip(), "")

    # ------------------------------------------------------------------
    # Prompt text construction
    # ------------------------------------------------------------------
    def _build_prompt_text(
        self,
        pid: str,
        template: TemplateDefinition,
        rc: RenderContext,
        memo: Dict[str, str],
    ) -> str:
        if pid in memo:
            return memo[pid]
        prompt = template.prompts[pid]
        parts: List[str] = []
        self._collect_prompt_body(prompt.body, template, rc, memo, parts)
        text = "".join(parts).strip()
        memo[pid] = text
        return text

    def _collect_prompt_body(
        self,
        nodes: List[Node],
        template: TemplateDefinition,
        rc: RenderContext,
        memo: Dict[str, str],
        out: List[str],
    ) -> None:
        for node in nodes:
            if node.type == "text":
                out.append(html.unescape(node.text))
                continue
            tag = node.tag
            if tag == "fill":
                out.append(str(self._resolve_fill(self._inner_text(node), rc)))
            elif tag == "param":
                out.append(str(self._resolve_param(self._inner_text(node), rc)))
            elif tag == "include":
                ref_resp = node.attrs.get("response")
                ref_prompt = node.attrs.get("prompt")
                if ref_resp is not None:
                    out.append(rc.responses.get(ref_resp, ""))
                elif ref_prompt is not None and ref_prompt in template.prompts:
                    out.append(self._build_prompt_text(ref_prompt, template, rc, memo))
            else:
                # Unknown element inside a prompt body: recurse into its content.
                self._collect_prompt_body(node.children, template, rc, memo, out)

    @staticmethod
    def _inner_text(node: Node) -> str:
        return "".join(c.text for c in node.children if c.type == "text")

    # ------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------
    async def _execute_prompt(
        self,
        prompt: PromptDefinition,
        template: TemplateDefinition,
        rc: RenderContext,
        memo: Dict[str, str],
    ) -> None:
        if rc.skipped.get(prompt.id):
            rc.responses[prompt.id] = ""
            return

        prompt_text = self._build_prompt_text(prompt.id, template, rc, memo)
        # gather_responses: a sequential prompt receives the responses of the
        # earlier sequential prompts in this render, prepended as context.
        if rc.gather_responses and not prompt.is_async and rc.gathered:
            prompt_text = self._with_gathered(rc.gathered, prompt_text)

        tools = resolve_tools(prompt.tools, self.config.tool_registry)
        # Resolve any logical model alias to its concrete model before use, so
        # both the cache key and the call reflect the real target.
        model = self.config.model_aliases.get(prompt.model, prompt.model) if prompt.model else prompt.model

        # Prompts that declare tools run a single tool-execution iteration and are
        # NOT cached (tool outputs are dynamic). A None result means the model was
        # still requesting a tool after that iteration → render nothing.
        if tools:
            result = await self.config.llm_client.generate_with_tools(
                prompt_text,
                model=model,
                temperature=prompt.temperature,
                max_tokens=prompt.max_tokens,
                tools=tools,
                execute=self._make_tool_executor(tools),
            )
            self._record(rc, prompt, result if result is not None else "")
            return

        ttl = parse_ttl(prompt.cache)
        cache = self.config.cache
        key: Optional[str] = None
        if ttl is not None and cache is not None:
            key = build_cache_key(
                prompt_text=prompt_text,
                model=model,
                temperature=prompt.temperature,
                max_tokens=prompt.max_tokens,
                tools=prompt.tools,
            )
            cached = await cache.get(key)
            if cached is not None:
                self._record(rc, prompt, cached)
                return

        result = await self.config.llm_client.generate(
            prompt=prompt_text,
            model=model,
            temperature=prompt.temperature,
            max_tokens=prompt.max_tokens,
            tools=tools,
        )
        self._record(rc, prompt, result)
        if key is not None and cache is not None:
            await cache.set(key, result, ttl)

    @staticmethod
    def _with_gathered(gathered, prompt_text: str) -> str:
        """Prepend earlier sequential responses to a prompt as labeled context."""
        prior = "\n\n".join(f"[{pid}] {resp}" for pid, resp in gathered if resp)
        if not prior:
            return prompt_text
        return (
            "Context from earlier prompts on this page:\n"
            f"{prior}\n\n---\n{prompt_text}"
        )

    @staticmethod
    def _record(rc: RenderContext, prompt: PromptDefinition, result: str) -> None:
        """Store a prompt's response, and add it to the gather chain if eligible."""
        rc.responses[prompt.id] = result
        if rc.gather_responses and not prompt.is_async and result:
            rc.gathered.append((prompt.id, result))

    @staticmethod
    def _make_tool_executor(tools):
        """Build the callback adapters use to run a tool by name with the model's
        arguments. The map is restricted to this prompt's allowlisted tools."""
        registry = {t.name: t for t in tools}

        async def execute(name, args):
            tool = registry.get(name)
            if tool is None:
                return f"error: tool '{name}' is not available to this prompt"
            try:
                result = await invoke_tool(tool, **(args or {}))
            except Exception as exc:  # surface the error back to the model
                return f"error executing {name}: {exc}"
            return result if isinstance(result, str) else str(result)

        return execute

    async def _execute_all(
        self, template: TemplateDefinition, rc: RenderContext, memo: Dict[str, str]
    ) -> None:
        graph = build_graph(template.prompts)
        for level in topological_levels(graph):
            # Prompts run sequentially by default. A prompt can opt into
            # concurrency with async="yes"; within a level, all such prompts run
            # together (they are independent), while the rest run one at a time.
            # A level may therefore be sequential, concurrent, or a mix of both.
            concurrent = []
            for pid in level:
                prompt = template.prompts[pid]
                if prompt.is_async:
                    concurrent.append(self._execute_prompt(prompt, template, rc, memo))
                else:
                    await self._execute_prompt(prompt, template, rc, memo)
            if concurrent:
                await asyncio.gather(*concurrent)

    # ------------------------------------------------------------------
    # Document serialization
    # ------------------------------------------------------------------
    def _serialize(self, nodes: List[Node], rc: RenderContext) -> str:
        out: List[str] = []
        for node in nodes:
            out.append(self._serialize_node(node, rc))
        return "".join(out)

    def _serialize_node(self, node: Node, rc: RenderContext) -> str:
        if node.type == "text":
            return node.text

        tag = node.tag
        if tag == "prompt":
            return ""  # Tacit: prompts are never rendered.
        if tag == "response":
            rid = node.attrs.get("id", "")
            # Same truthiness rule the parser uses, so render="..." is parsed
            # identically everywhere.
            render = _as_bool(node.attrs.get("render"), default=True)
            return rc.responses.get(rid, "") if render else ""
        if tag == "include":
            ref_resp = node.attrs.get("response")
            if ref_resp is not None:
                return rc.responses.get(ref_resp, "")
            return ""  # include prompt="..." is a prompt-construction directive.
        if tag == "fill":
            return html.escape(str(self._resolve_fill(self._inner_text(node), rc)))
        if tag == "param":
            return html.escape(str(self._resolve_param(self._inner_text(node), rc)))

        # Generic HTML element: re-emit faithfully.
        return self._serialize_element(node, rc)

    def _serialize_element(self, node: Node, rc: RenderContext) -> str:
        attrs = "".join(self._attr_str(k, v) for k, v in node.attrs.items())
        open_tag = f"<{node.tag}{attrs}>"
        if node.tag in _VOID:
            return open_tag
        inner = self._serialize(node.children, rc)
        return f"{open_tag}{inner}</{node.tag}>"

    @staticmethod
    def _attr_str(key: str, value: Optional[str]) -> str:
        if value is None:
            return f" {key}"
        return f' {key}="{html.escape(value, quote=True)}"'

    # ------------------------------------------------------------------
    # Public entry
    # ------------------------------------------------------------------
    async def render(self, template: TemplateDefinition, rc: RenderContext) -> str:
        # 1. Decide which prompts execute based on their condition rule.
        #    An unregistered rule is a configuration mistake and fails loudly;
        #    a rule that runs but *raises* (e.g. the bindings lack a key it reads)
        #    is treated as "condition not met" and skips that one prompt.
        for pid, prompt in template.prompts.items():
            condition = prompt.condition or ""
            if condition and condition not in rc.rules:
                raise RuleError(
                    f"Prompt '{pid}' references rule '{condition}', which is not "
                    f"registered in HPRCConfig.rules."
                )
            try:
                should_run = evaluate_rule(condition, rc.rules, rc.bindings)
            except RuleError:
                raise
            except Exception:
                should_run = False
            rc.skipped[pid] = not should_run

        # 2-5. Execute prompts honoring dependencies + concurrency.
        memo: Dict[str, str] = {}
        await self._execute_all(template, rc, memo)

        # 6. Serialize the final document.
        return self._serialize(template.root, rc)


# ---------------------------------------------------------------------------
# Public functional API
# ---------------------------------------------------------------------------
async def render_template(
    template_path: str,
    request: Any = None,
    bindings: Optional[Dict[str, Any]] = None,
    config: Optional[HPRCConfig] = None,
    gather_responses: bool = False,
) -> str:
    """Render a ``.sprep.html`` template file to final HTML.

    ``bindings`` is your data, bound into ``<fill>`` (in both the HTML and the
    prompts). ``gather_responses`` (off by default) makes each sequential prompt
    receive the responses of the earlier sequential prompts in this render.

    This is the primary entry point an application calls::

        html = await hprc.render_template(
            template_path="customer.sprep.html",
            request=request,
            bindings=bindings,
            config=config,
        )
    """
    config = config or HPRCConfig()
    template = parse_file(template_path)
    return await render_string(
        template=template, request=request, bindings=bindings, config=config,
        gather_responses=gather_responses,
    )


async def render_template_string(
    template_html: str,
    request: Any = None,
    bindings: Optional[Dict[str, Any]] = None,
    config: Optional[HPRCConfig] = None,
    gather_responses: bool = False,
) -> str:
    """Render template HTML supplied as a string (no file I/O)."""
    from .parser import parse

    config = config or HPRCConfig()
    template = parse(template_html)
    return await render_string(
        template=template, request=request, bindings=bindings, config=config,
        gather_responses=gather_responses,
    )


async def render_string(
    template: TemplateDefinition,
    request: Any = None,
    bindings: Optional[Dict[str, Any]] = None,
    config: Optional[HPRCConfig] = None,
    gather_responses: bool = False,
) -> str:
    """Render an already-parsed :class:`TemplateDefinition`."""
    config = config or HPRCConfig()
    rc = RenderContext(
        bindings=dict(bindings or {}),
        request=normalize_request(request),
        rules=dict(config.rules),
        tools=config.tool_registry,
        gather_responses=gather_responses,
    )
    renderer = Renderer(config)
    return await renderer.render(template, rc)
