"""Template parser.

Turns a ``.sprep.html`` string into a :class:`~hprc.models.TemplateDefinition`:

1. A tolerant HTML parser (stdlib :mod:`html.parser`) builds a generic node
   tree, faithfully preserving text, entities, comments, the doctype and
   self-closing/void elements so the document can be re-serialized verbatim.
2. A second pass walks the tree to index ``<prompt>`` and ``<response>``
   elements into typed definitions.

The parser is deliberately framework- and provider-agnostic.
"""

from __future__ import annotations

from html.parser import HTMLParser
from typing import List, Optional

from .models import (
    Node,
    PromptDefinition,
    ResponseDefinition,
    TemplateDefinition,
)

# HTML void elements are emitted without a closing tag. Note: HPRC's ``<param>``
# carries content, so it is intentionally NOT treated as void here.
VOID_ELEMENTS = {
    "area", "base", "br", "col", "embed", "hr", "img", "input",
    "link", "meta", "source", "track", "wbr",
}


class _TreeBuilder(HTMLParser):
    """Builds a :class:`Node` tree from an HTML string."""

    def __init__(self) -> None:
        # convert_charrefs=False so entities survive round-tripping.
        super().__init__(convert_charrefs=False)
        self.root = Node(type="element", tag="#root")
        self._stack: List[Node] = [self.root]

    # -- helpers ----------------------------------------------------------
    @property
    def _current(self) -> Node:
        return self._stack[-1]

    def _append(self, node: Node) -> None:
        self._current.children.append(node)

    def _add_text(self, text: str) -> None:
        if not text:
            return
        # Merge consecutive text runs for a tidier tree.
        children = self._current.children
        if children and children[-1].type == "text":
            children[-1].text += text
        else:
            self._append(Node(type="text", text=text))

    # -- HTMLParser callbacks --------------------------------------------
    def handle_starttag(self, tag, attrs):
        node = Node(type="element", tag=tag, attrs=dict(attrs))
        self._append(node)
        if tag in VOID_ELEMENTS:
            # Void element: never push; it has no children/closing tag.
            return
        self._stack.append(node)

    def handle_startendtag(self, tag, attrs):
        # Explicit self-closing form: <include .../>
        node = Node(type="element", tag=tag, attrs=dict(attrs))
        self._append(node)

    def handle_endtag(self, tag):
        # Pop until we find the matching open tag (tolerant of bad nesting).
        for i in range(len(self._stack) - 1, 0, -1):
            if self._stack[i].tag == tag:
                del self._stack[i:]
                return
        # No matching open tag: ignore stray end tag.

    def handle_data(self, data):
        self._add_text(data)

    def handle_entityref(self, name):
        self._add_text(f"&{name};")

    def handle_charref(self, name):
        self._add_text(f"&#{name};")

    def handle_comment(self, data):
        self._append(Node(type="text", text=f"<!--{data}-->"))

    def handle_decl(self, decl):
        self._append(Node(type="text", text=f"<!{decl}>"))

    def handle_pi(self, data):
        self._append(Node(type="text", text=f"<?{data}>"))


# ---------------------------------------------------------------------------
# Attribute coercion helpers
# ---------------------------------------------------------------------------
def _as_bool(value: Optional[str], default: bool) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"yes", "true", "1", "on"}


def _as_float(value: Optional[str], attr: str = "value") -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except ValueError:
        raise ValueError(f"Invalid numeric {attr}: {value!r} (expected a number).")


def _as_int(value: Optional[str], attr: str = "value") -> Optional[int]:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except ValueError:
        raise ValueError(f"Invalid integer {attr}: {value!r} (expected an integer).")


def _as_list(value: Optional[str]) -> List[str]:
    if not value:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


# ---------------------------------------------------------------------------
# Extraction pass
# ---------------------------------------------------------------------------
def _build_prompt(node: Node) -> PromptDefinition:
    attrs = node.attrs
    pid = attrs.get("id")
    if not pid:
        raise ValueError("<prompt> elements require an 'id' attribute.")
    return PromptDefinition(
        id=pid,
        model=attrs.get("model"),
        condition=attrs.get("condition"),
        temperature=_as_float(attrs.get("temperature"), "temperature"),
        max_tokens=_as_int(attrs.get("max_tokens"), "max_tokens"),
        is_async=_as_bool(attrs.get("async"), default=False),
        cache=attrs.get("cache"),
        tools=_as_list(attrs.get("tools")),
        body=list(node.children),
    )


def _build_response(node: Node) -> ResponseDefinition:
    attrs = node.attrs
    rid = attrs.get("id")
    if not rid:
        raise ValueError("<response> elements require an 'id' attribute.")
    return ResponseDefinition(id=rid, render=_as_bool(attrs.get("render"), default=True))


def _extract(node: Node, template: TemplateDefinition) -> None:
    for child in node.children:
        if child.type != "element":
            continue
        if child.tag == "prompt":
            prompt = _build_prompt(child)
            if prompt.id in template.prompts:
                raise ValueError(f"Duplicate prompt id: {prompt.id!r}")
            template.prompts[prompt.id] = prompt
            # Do not descend into prompt bodies for the prompt/response index;
            # fills/includes inside are resolved at execution time.
            continue
        if child.tag == "response":
            template.responses.append(_build_response(child))
            continue
        _extract(child, template)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def _validate_includes(template: TemplateDefinition) -> None:
    """Fail loudly when an ``<include>`` references an unknown prompt id.

    Both ``<include prompt="X"/>`` and ``<include response="X"/>`` refer to a
    prompt definition (a response is the output of the prompt with the same id),
    so the target must be a defined prompt. This mirrors the parser's other
    authoring-error checks instead of silently dropping the include.
    """

    def check(nodes: List[Node]) -> None:
        for node in nodes:
            if node.type == "element" and node.tag == "include":
                ref = node.attrs.get("prompt") or node.attrs.get("response")
                if ref and ref not in template.prompts:
                    kind = "prompt" if node.attrs.get("prompt") else "response"
                    raise ValueError(
                        f'<include {kind}="{ref}"/> references prompt id '
                        f"{ref!r}, which is not defined in the template."
                    )
            if node.children:
                check(node.children)

    for prompt in template.prompts.values():
        check(prompt.body)
    check(template.root)


def parse(html: str) -> TemplateDefinition:
    """Parse an HTML/SPREP template string into a :class:`TemplateDefinition`."""
    builder = _TreeBuilder()
    builder.feed(html)
    builder.close()

    template = TemplateDefinition(root=list(builder.root.children))
    _extract(builder.root, template)
    _validate_includes(template)
    return template


def parse_file(path: str, encoding: str = "utf-8") -> TemplateDefinition:
    """Read and parse a template file."""
    with open(path, "r", encoding=encoding) as handle:
        return parse(handle.read())
