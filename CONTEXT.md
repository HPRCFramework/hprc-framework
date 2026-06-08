# CONTEXT.md — HPRC

Narrative context and decision record for the HPRC project. For working
instructions see [CLAUDE.md](CLAUDE.md); for the roadmap see [plan.txt](plan.txt).

## Vision
HPRC (**Simple Prompt Response Embedded Pages**) is an AI-native server-side templating
framework — JSP/PHP/Jinja/Thymeleaf, but with LLM prompts as a first-class
template element. The bet: most "LLM + web" code today is imperative glue
(hand-built prompt strings, manual call sequencing, manual splicing). HPRC makes
the **template the source of truth** — prompts live inline where their output
appears, and the framework does all orchestration (condition eval, fill
resolution, dependency ordering, concurrency, caching, serialization). The app
developer supplies only data + policy via one `HPRCConfig`.

Core principles: prompts are **tacit** (execute, never render); **no expression
language** in templates (named rules/tools only); **integrates with any web framework**
(FastAPI/Flask/Django or standalone; never imports one); **provider-independent** (one `LLMClient.generate`
coroutine); **no agent loop** (tools handed to the client, which decides usage).

## Current state (checkpoint 2026-05-31)
- **Library complete** — 10 modules, pip-installable, Pydantic v2.
- **12 required features** implemented and tested: tacit prompts, render yes/no,
  dot-path fills, request namespace + `<param>`, named-rule conditions, model/
  temperature/max_tokens pass-through, allowlisted tools, includes, auto
  dependency graph, async concurrency (with `async="no"` opt-out), TTL caching
  (`cache="0"` disables).
- **Providers** — Mock, OpenAI, Anthropic, Gemini, Ollama/LM-Studio, plus
  `MultiProviderClient` (`"provider:model"` prefix routing) and
  `HPRCConfig.model_aliases`. All SDKs lazy-imported and optional.
- **Tests** — 66 passing incl. a mocked provider **conformance suite**; pyflakes
  clean.
- **Examples** — `fastapi_app.py`, `standalone.py`, and a **dashboard** that
  sources its context from a CSV file and renders data panels + concurrent AI
  panels (0.81s vs ~2.0s sequential).
- **Docs** — offline HTML (`docs/index|user-guide|architecture.html`), plus
  `README.md` and `ARCHITECTURE.md`. (`docs/PROVISIONAL_PATENT_DRAFT.md` exists but
  is moot now that the patent path was dropped — candidate for deletion.)
- **License** — Apache-2.0 (`LICENSE` + `NOTICE`), © 2026 Rajesh Ramani.

## Key decisions
- **Adapter pattern for providers.** `.generate` is *our* uniform method; each
  client translates it to a vendor SDK call and extracts the text. The renderer
  only ever calls `.generate` — provider churn is confined to `hprc/llm.py`.
  Upkeep strategy: lazy extras + conformance tests + (future) capability metadata.
- **`client = provider, model = sub-selection`.** The configured client fixes the
  provider; `model="..."` picks the variant. Provider routing via `model` is
  opt-in through `MultiProviderClient` / `model_aliases`.
- **Data composition is layered.** Level 1 (done): app loads SQL/REST/CSV/computed
  data into `context`; `<fill>` renders it and prompts ground on it. Level 2/3
  (planned) add raw-HTML injection and async data providers — see plan.txt.
- **Tooling & MCP (planned).** The `tools` seam currently only hands definitions to
  the provider. Future: opt-in agentic tool execution per prompt, MCP server
  integration (tools exposed via the same allowlist, namespaced), and tool/MCP
  results as embeddable content in the dependency graph — see plan.txt.
- **Open source from the outset (Apache-2.0).** The provisional-patent path was
  dropped; HPRC ships open under Apache-2.0, created by Rajesh Ramani, and doubles
  as a portfolio / job showcase. Going public (GitHub, PyPI, article, LinkedIn) is
  unblocked.

## Open items / risks
- No template iteration construct (loops); tabular data is handled today via
  preformatted text or scalar fills, and will improve with Level 2 raw fragments.
- Model names in templates are provider-specific unless `model_aliases` is used.
