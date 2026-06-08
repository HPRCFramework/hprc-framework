# SPREP — Simple Prompt Response Embedded Pages
## Template Language Specification

**Version:** 0.1 (Draft) · **Status:** Working draft
**Reference implementation:** [HPRC Framework](../README.md) (`import hprc`)
**Author:** Rajesh Ramani · **License:** Apache-2.0

---

## 1. Overview

**SPREP** (*Simple Prompt Response Embedded Pages*) is a declarative, server-side
**template language** for embedding generative-model (LLM) prompts directly inside
HTML. A SPREP template is ordinary HTML augmented with a small set of elements that
declare prompts, mark where their responses appear, bind data into them, and compose
them together.

SPREP templates are executed by a **conforming renderer** during page rendering. The
reference renderer is the **HPRC Framework** (HTML Prompt Response Construction).

> Developers write **SPREP templates**. A renderer such as the **HPRC Framework**
> renders them.

### Design tenets
1. **Declarative templates** — the template says *what* to ask and *where* the answer goes; it never contains business logic.
2. **Prompts are tacit** — a `<prompt>` is executable but is *never* emitted into the output.
3. **Logic is external** — conditions reference *named rules*; the predicates live in host-language code.
4. **Capabilities are external** — tools are referenced by *name* from an allowlist; the renderer hands them to the model.
5. **Provider-independent** — the language says nothing about which model vendor is used.
6. **Composable** — one prompt may include another's response or constructed text; the renderer resolves the order automatically.

---

## 2. File format

- **Syntax base:** an HTML superset. A SPREP document is parsed as HTML; any markup
  that is not a SPREP element is preserved verbatim in the output.
- **Conventional file extension:** `.sprep.html`
- **Encoding:** UTF-8.
- **Media type (suggested):** `text/html` (a dedicated `application/sprep+html` MAY be used by tooling).

---

## 3. Namespaces & value resolution

`<fill>` and `<param>` resolve **dotted paths** against a root namespace composed of:

| Namespace | Source |
|---|---|
| application bindings | host-supplied data (a mapping/object) |
| `request.query.*` | request query-string parameters |
| `request.path.*` | request path parameters |
| `request.method` | the HTTP method (or empty for non-HTTP) |

- Path segments traverse mappings, object attributes, and integer sequence indices.
- A missing path resolves to the **empty string** (templates degrade gracefully).

---

## 4. Elements

SPREP defines five elements. All other markup is literal HTML.

### 4.1 `<prompt>` — executable, tacit

Declares a model call. Its body becomes the prompt text. **It is never rendered.**

| Attribute | Type | Default | Meaning |
|---|---|---|---|
| `id` | string | **required** | Unique within the document. Binds to `<response id="…">` and `<include …="id">`. |
| `model` | string | (renderer default) | Model identifier passed to the provider. |
| `condition` | rule name | (none) | Named rule gating execution. Absent ⇒ always runs. |
| `temperature` | number | (provider default) | Generation parameter. |
| `max_tokens` | integer | (provider default) | Output token cap. |
| `async` | `yes` \| `no` | `no` | Prompts run sequentially by default; `yes` opts this prompt into concurrent execution with other async prompts in its level. |
| `cache` | duration | (none) | TTL such as `24h`. Absent or `0` ⇒ no caching. |
| `tools` | name list | (none) | Comma-separated allowlist of tool names. |

**Body** may contain text and the directives `<fill>`, `<param>`, `<include>`.

### 4.2 `<response>` — placeholder

Marks where a prompt's generated output is inserted, bound by `id`.

| Attribute | Type | Default | Meaning |
|---|---|---|---|
| `id` | string | **required** | Must match a `<prompt id="…">`. |
| `render` | `yes` \| `no` | `yes` | `no` ⇒ the response is **generated but hidden** (still available to `<include response>`). |

A document MAY contain multiple `<response>` elements with the same `id` (the same
output is rendered in each place).

### 4.3 `<fill>` — data binding

```html
<fill>customer.profile.name</fill>
```

Resolves the dotted path to a value. In **document output** the value is **HTML-escaped**.
Inside a **prompt body** the value is inserted **raw** (it is text for the model).

### 4.4 `<param>` — request-query shortcut

```html
<param>product</param>   <!-- equivalent to: <fill>request.query.product</fill> -->
```

### 4.5 `<include>` — composition

```html
<include prompt="summary"/>     <!-- inserts the CONSTRUCTED PROMPT TEXT of prompt "summary" -->
<include response="summary"/>   <!-- inserts the GENERATED RESPONSE of prompt "summary" -->
```

An `<include>` creates a **dependency** on the referenced prompt. The target MUST be a
defined prompt `id`; a reference to an undefined prompt is an **error** (reported at
parse time by a conforming renderer).

---

## 5. Execution semantics

A conforming renderer, given a SPREP document, a request, the bindings, rules, tools, a
model client and a cache, performs one render pass:

1. **Parse** the document into a node tree and index `<prompt>` / `<response>` elements.
2. **Normalize the request** — convert whatever request object the web framework hands over (FastAPI, Flask, Django, or a plain dict) into one uniform `request` namespace the template can read: `request.query.*`, `request.path.*`, `request.method`. This is what `<param>` and `<fill>request.…</fill>` resolve against.
3. **Evaluate conditions** — for each prompt with a `condition`, evaluate the named rule against the bindings; if false, the prompt is **skipped** and its response resolves to empty. An **unregistered** rule name SHOULD be reported as an error (a configuration mistake); a rule that *raises* during evaluation MAY be treated as "condition not met" (skip).
4. **Build the dependency graph** by scanning each prompt body for `<include>` references; each referenced prompt becomes a dependency edge.
5. **Order execution** by topological partition into *levels*; prompts in one level are mutually independent. A cycle is an **error**.
6. **Execute** level by level. Prompts run **sequentially by default**; a prompt with `async="yes"` runs **concurrently** with the other async prompts in its level — so a level may be sequential, concurrent, or a mix of both. For each prompt the renderer constructs the final prompt text by resolving `<fill>`, `<param>` and `<include>` (constructed-prompt includes are resolved recursively, with memoization).
7. **Cache** — if `cache` is set, the renderer consults a cache keyed on the **fully-resolved prompt text**, `model`, `temperature`, `max_tokens` and the (order-independent) set of `tools`. On a hit, the model is not invoked.
8. **Invoke the model** through a provider-independent client, passing the resolved allowlisted tool definitions.
9. **Serialize** — produce the final HTML by walking the document and emitting each node:
   - a `<prompt>` emits **nothing** (it was executable, not for display);
   - a `<response id="X">` emits prompt *X*'s generated text (or nothing when `render="no"`);
   - an `<include response="X"/>` at document level emits prompt *X*'s text;
   - `<fill>` / `<param>` emit their resolved value, **HTML-escaped**;
   - all other markup is emitted **unchanged**.

---

## 6. Rules, tools, caching, async — external contracts

- **Rules.** Conditions are *named only*; there is **no expression language** in templates. The host supplies `{name → predicate(bindings) → bool}`.
- **Tools.** Templates list an **allowlist of names**; the host supplies `{name → tool}`. The renderer resolves names (rejecting unknown ones) and exposes the tools to the model. A conforming renderer MAY execute the tool calls the model requests and feed the results back; SPREP does not mandate an agent loop. (The reference implementation runs a **single iteration** — it executes the tool call(s) the model requests, feeds the results back, and renders the model's next response, or nothing if the model is still calling tools after that iteration. A multi-step agent loop is on its roadmap.)
- **Cache.** When a prompt sets `cache="…"`, the renderer **stores that prompt's generated response and reuses it on later renders instead of calling the model again** — saving latency and cost. The duration sets how long an entry stays valid: units `s`/`m`/`h`/`d`/`w` (e.g. `30m`, `24h`, `2d`, `1w`) or a bare integer of seconds; absent or non-positive (`0`) means *don't cache*. *Where* it is stored is the renderer's choice via a pluggable cache backend — the reference implementation ships an in-process memory cache, with the interface open for others (e.g. Redis). The cache key is derived from the fully-resolved prompt text plus `model`, `temperature`, `max_tokens` and `tools`, so any change to those produces a fresh result.
- **Async.** Prompts run in **sequential order by default**; `async="yes"` opts a prompt into concurrent execution with the other async prompts in its level (a level may be sequential, concurrent, or a mix). Dependent prompts always run after the prompts they include, regardless.

---

## 7. Escaping & safety

- Values emitted by `<fill>` / `<param>` in the document are **HTML-escaped** — special HTML characters (`<`, `>`, `&`, `"`, `'`) are converted to their entities (e.g. `<` becomes `&lt;`) so the value renders as **literal text** rather than being interpreted as markup. A value like `<script>…` therefore shows up as visible text instead of executing (preventing broken layout and HTML/script injection, i.e. XSS). This applies in the rendered document; inside a **prompt body** the same `<fill>` is inserted **raw**, because there it is text for the model, not HTML.
- Model responses inserted at `<response>` are emitted **as-is**; hosts SHOULD sanitize upstream if responses may contain untrusted markup.
- Prompt bodies are tacit and are never emitted, so prompt text (which may contain sensitive instructions) does not leak into output.

---

## 8. Conformance

A **conforming SPREP renderer** MUST:

- treat `<prompt>` as tacit (never emit it);
- resolve `<fill>` dotted paths against bindings and the `request` namespace, and support `<param>`;
- evaluate `condition` as a *named* rule lookup (no template-side expressions);
- build the `<include>` dependency graph and execute prompts in dependency order, detecting cycles;
- support `<response render="yes|no">`, where a hidden response is still available to `<include response>`;
- pass `model`, `temperature`, `max_tokens` and the resolved `tools` to the model client;
- cache responses when a `cache` directive is present, keyed on the output-determining inputs.

A conforming renderer MAY provide additional providers, cache backends, data sources,
or extensions, provided the above semantics are preserved.

---

## 9. Reference implementation

The **HPRC Framework** is the reference implementation (`pip install hprc-framework`,
`import hprc`). See [README](../README.md), the [User Guide](../docs/user-guide.html)
and the [Architecture](../docs/architecture.html).

---

## 10. Future extensions (non-normative)

These are **not** part of SPREP v0.1; they describe the planned direction (tracked in
the [HPRC roadmap](../docs/architecture.html#roadmap)). They would be added as optional,
non-normative elements/attributes:

- **`<system>`** — a system-message directive prepended to prompt model calls.
- **`format`** on `<response>` — `text` (escaped), `markdown` (→ sanitized HTML), `html` (sanitized).
- **`returns="json"`** on `<prompt>` — structured output whose fields fill many placeholders.
- **`<each>`** — iteration for rendering lists.
- **`<data>` / `<retrieve>`** — async data providers and RAG retrieval feeding prompts (`retrieved_context`).
- **`<live>`** — a region rendered as a placeholder + client hook, driven by a streaming endpoint (real-time widgets).

Renderer-level (not language) additions on the roadmap include a bounded multi-step tool
loop, MCP tool sources, an input message chain (`prior_context`), and returning the
executed turns to the caller.

---

## Appendix A — Complete example

```html
<!-- customer.sprep.html -->
<h1><fill>customer.name</fill></h1>

<prompt id="summary" model="gpt-5" condition="is_premium_customer"
        temperature="0.2" cache="24h" tools="crm_lookup,pricing_engine">
  Customer: <fill>customer.name</fill> (tier: <fill>customer.tier</fill>)
  Product of interest: <param>product</param>
  Write a 2-sentence account summary.
</prompt>

<prompt id="upsell" model="gpt-5">
  Given this summary: <include response="summary"/>
  Suggest one upsell for "<param>product</param>".
</prompt>

<section><h2>Summary</h2><response id="summary"/></section>
<section><h2>Next step</h2><response id="upsell"/></section>
```

`upsell` includes `summary`'s response, so a renderer executes `summary` first,
substitutes its output into `upsell`, and emits both — while neither `<prompt>` block
appears in the final HTML.

---

*SPREP is an open specification. Reference implementation © 2026 Rajesh Ramani,
Apache-2.0.*
