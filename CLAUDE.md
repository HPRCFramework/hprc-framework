# CLAUDE.md — HPRC project instructions

Guidance for Claude Code when working in this repository. Read this first.

## License & direction
**Open source under Apache-2.0 from the outset** (no patent — that path was
dropped). Created by **Rajesh Ramani**; keep his attribution intact (LICENSE,
NOTICE, README, pyproject `authors`). The project is also a **portfolio / job
showcase**, so keep the code, docs, and README polished and presentable.

Git note: this folder has **no local commits yet**, and `~` is an *accidental*
git root. When committing, init a **dedicated** repo inside `~/ai/Prep` — never
commit into the home-directory repo. Going public (GitHub push, PyPI, article,
LinkedIn) is fine whenever the user wants; confirm before pushing to a remote.

## What HPRC is
An AI-native **server-side templating library** that integrates with any web framework
(FastAPI/Flask/Django) or runs standalone: embed LLM
prompts directly in HTML as `<prompt>` blocks, mark output with `<response>`, and
HPRC executes them during rendering — resolving fills, evaluating named rules,
auto-building a dependency graph from `<include>`s, running independent prompts
concurrently, caching, and injecting responses. Prompts are **tacit** (never
rendered). Templating first; LLM prompts are one element type among ordinary HTML.

## Repo layout
```
hprc/            core library (10 modules)
  models.py        pydantic models (Node, *Definition, RenderContext)
  parser.py        tolerant HTML→Node tree + prompt/response extraction
  request_context.py  request normalization + dotted-path resolution
  rules.py         named-rule evaluation (NO expression language in templates)
  tools.py         tool normalization + allowlist resolution
  cache.py         TTL parsing, cache-key hashing, Cache/Memory/Null
  llm.py           LLMClient ABC + Mock/OpenAI/Anthropic/Gemini/Ollama/MultiProvider
  dependency_graph.py  include-scan, graph build, Kahn topological levels
  config.py        HPRCConfig (llm_client, rules, tools, cache, model_aliases)
  renderer.py      orchestration core + public render_* entry points
examples/        fastapi_app.py, standalone.py, dashboard.py + templates/ + data/
tests/           pytest suite (66 passing)
docs/            offline HTML docs (index/user-guide/architecture) + build.py
                 (pandoc: Markdown -> styled HTML; regenerates README.html/PORTFOLIO.html)
sprep/           SPREP template-language spec (sprep-spec.md + sprep-spec.html)
README.html/PORTFOLIO.html   generated from the .md by `python docs/build.py`
```

## Conventions (match the existing code)
- **The renderer stays provider-agnostic.** Never import a provider SDK outside
  `hprc/llm.py`. New providers = a new `LLMClient` subclass with a lazy SDK import
  inside `_get_client`; no renderer/template changes.
- **No business logic or expression parsing in templates.** Rules and tools are
  referenced by *name*; predicates/callables live in the app via `HPRCConfig`.
- Provider SDKs are **optional/lazy** — `import hprc` must work with none installed.
  Declare each under `[project.optional-dependencies]` extras.
- `<fill>`/`<param>` output is **HTML-escaped** in the document; prompt-body fills
  are raw (they are text for the model).
- Pydantic v2 models for everything that flows through the renderer.
- Keep modules acyclic: `models` ← leaf services ← `config` ← `renderer` ← `__init__`.
- Add tests for new behavior; the provider conformance pattern is in
  `tests/test_providers.py` (mocked SDK transports — no keys/network).

## Commands
```bash
source .venv/bin/activate
pip install -e ".[dev]"        # or ".[all]" for every provider SDK
python -m pytest -q            # run tests (expect 66 passing)
python -m pyflakes hprc/ tests/
python examples/dashboard.py   # CSV-sourced context + concurrent AI panels
open docs/index.html           # offline docs
```

## Roadmap (see plan.txt for detail)
- **Level 2 (TODO):** raw/trusted HTML injection — `<fill raw="yes">` / honor
  `markupsafe.Markup` (for pre-rendered fragments; `<fill>` escapes by design).
- **Level 3 (TODO):** async **data providers** as a 4th `HPRCConfig` seam
  (`data={...}`, `<data id=.../>`, `<include data=.../>`) that join the same
  dependency graph as prompts, so DB/API fetches and LLM calls run concurrently.
- **Tooling & MCP (TODO):** make the `tools` seam first-class — opt-in agentic tool
  execution per prompt (model→tool→result→iterate, bounded), **MCP** server
  integration (discover/expose/execute MCP tools via the same allowlist, namespaced
  `mcp:server.tool`), and tool/MCP results as embeddable content joining the
  dependency graph. Tools/MCP stay external + name-referenced; no logic in templates.

## Pointers
- Plan & checkpoint: [plan.txt](plan.txt)
- Architecture: [ARCHITECTURE.md](ARCHITECTURE.md) / [docs/architecture.html](docs/architecture.html)
