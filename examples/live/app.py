"""HPRC live demo — full-stack FastAPI app backed by real Claude.

A small, self-contained showcase you can deploy on a server:

* a form collects a customer scenario,
* HPRC renders ``templates/assistant.sprep.html`` with the **Anthropic (Claude)**
  provider, executing the embedded ``<prompt>`` blocks during rendering,
* the page shows the rendered result (tacit prompts never appear).

The template is read **fresh from disk on every request**, so editing it — on the
server or via the built-in ``/edit`` page — takes effect on the next refresh with
**no redeploy**. Redeploy is only needed when you change this Python file.

Run locally::

    pip install -e ".[fastapi,anthropic]"
    export ANTHROPIC_API_KEY=sk-ant-...
    python examples/live/app.py            # serves on :8123

Env vars: ``ANTHROPIC_API_KEY`` (required for real output), ``HPRC_DEMO_PORT``
(default 8123), ``HPRC_DEMO_MODEL`` (default claude-sonnet-4-6),
``HPRC_DEMO_ALLOW_EDIT`` (default "1"; set "0" to disable the /edit page).
"""

from __future__ import annotations

import os
import html as html_mod

from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

import hprc
from hprc import HPRCConfig, MemoryCache, MockLLMClient

HERE = os.path.dirname(os.path.abspath(__file__))
TEMPLATE_DIR = os.path.join(HERE, "templates")
TEMPLATE_NAME = "assistant.sprep.html"
TEMPLATE_PATH = os.path.join(TEMPLATE_DIR, TEMPLATE_NAME)

MODEL = os.getenv("HPRC_DEMO_MODEL", "claude-sonnet-4-6")
ALLOW_EDIT = os.getenv("HPRC_DEMO_ALLOW_EDIT", "1") == "1"

app = FastAPI(title="HPRC Live Demo")


# --------------------------------------------------------------------------
# Provider: real Claude when a key is present, else the offline mock so the
# page still renders (clearly labelled) without a key.
# --------------------------------------------------------------------------
def build_llm_client():
    key = os.getenv("ANTHROPIC_API_KEY")
    if key:
        from hprc import AnthropicClient

        return AnthropicClient(api_key=key, default_model=MODEL), True
    return MockLLMClient(), False


def shell(title: str, body: str) -> str:
    """Wrap content in a small styled HTML shell (no external assets)."""
    return f"""<!DOCTYPE html><html lang="en"><head>
<meta charset="utf-8"/><meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>{html_mod.escape(title)}</title>
<style>
  :root {{ color-scheme: light dark; }}
  body {{ font-family: ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, sans-serif;
         max-width: 760px; margin: 2rem auto; padding: 0 1rem; line-height: 1.5; }}
  h1 {{ font-size: 1.6rem; margin-bottom: .2rem; }}
  .muted {{ color: #6b7280; }}
  form.scenario {{ display: grid; gap: .6rem; margin: 1rem 0; }}
  label {{ font-weight: 600; font-size: .9rem; }}
  input, select, textarea {{ width: 100%; padding: .5rem; font: inherit;
         border: 1px solid #cbd5e1; border-radius: 8px; box-sizing: border-box; }}
  textarea {{ min-height: 360px; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; }}
  button {{ padding: .55rem 1rem; font: inherit; font-weight: 600; border: 0;
         border-radius: 8px; background: #4f46e5; color: #fff; cursor: pointer; }}
  .card {{ border: 1px solid #e5e7eb; border-radius: 12px; padding: 1rem 1.2rem;
         margin: 1rem 0; background: rgba(127,127,127,.04); }}
  .card.premium {{ border-color: #2e7d32; }}
  .pill {{ display: inline-block; padding: .15rem .55rem; border-radius: 999px;
         font-size: .78rem; font-weight: 600; }}
  .pill.live {{ background: #cdebc5; color: #06280c; }}
  .pill.mock {{ background: #fde68a; color: #5b3d00; }}
  nav a {{ margin-right: 1rem; }}
  .err {{ border: 1px solid #ef4444; background: #fef2f2; color: #7f1d1d;
         padding: 1rem; border-radius: 12px; }}
</style></head><body>
<nav><a href="/">Home</a>{' <a href="/edit">Edit template</a>' if ALLOW_EDIT else ''} <a href="/health">Health</a></nav>
{body}
</body></html>"""


@app.get("/", response_class=HTMLResponse)
async def index():
    _, live = build_llm_client()
    badge = ('<span class="pill live">Claude live</span>' if live
             else '<span class="pill mock">Mock (no API key)</span>')
    body = f"""
<h1>HPRC Live Demo {badge}</h1>
<p class="muted">A FastAPI page rendered by HPRC. The form below builds the
   <code>bindings</code>; HPRC renders <code>{TEMPLATE_NAME}</code> — running the
   embedded <code>&lt;prompt&gt;</code> blocks with {html_mod.escape(MODEL)} — and returns the page.</p>
<form class="scenario" method="post" action="/render">
  <div><label>Customer name</label><input name="name" value="Ada Lovelace"/></div>
  <div><label>Tier</label>
    <select name="tier"><option>premium</option><option>free</option></select></div>
  <div><label>Product of interest</label><input name="product" value="WidgetPro"/></div>
  <div><label>Their question</label>
    <input name="ask" value="Can it handle 10k events per second?"/></div>
  <button type="submit">Render with HPRC</button>
</form>
<p class="muted">Tip: switch the tier to <code>free</code> — the premium-perk prompt
   is gated by a rule and won't run.</p>
"""
    return HTMLResponse(shell("HPRC Live Demo", body))


@app.post("/render", response_class=HTMLResponse)
async def render(request: Request,
                 name: str = Form("Ada Lovelace"),
                 tier: str = Form("premium"),
                 product: str = Form("WidgetPro"),
                 ask: str = Form("")):
    client, live = build_llm_client()
    bindings = {"customer": {"name": name, "tier": tier}, "ask": ask}
    config = HPRCConfig(
        llm_client=client,
        rules={"is_premium": lambda ctx: ctx["customer"]["tier"] == "premium"},
        cache=MemoryCache(),
    )
    # request carries ?product=... so <param>product</param> resolves; merge form value.
    req = {"query": {"product": product}, "path": {}, "method": "POST"}
    try:
        rendered = await hprc.render_template(
            template_path=TEMPLATE_PATH, request=req, bindings=bindings, config=config,
        )
    except Exception as exc:  # surface provider/template errors instead of a 500
        body = (f'<h1>Render failed</h1><div class="err"><strong>'
                f'{type(exc).__name__}:</strong> {html_mod.escape(str(exc))}</div>'
                f'<p><a href="/">Back</a></p>')
        return HTMLResponse(shell("Render failed", body), status_code=500)

    badge = ('<span class="pill live">Claude live</span>' if live
             else '<span class="pill mock">Mock (no API key)</span>')
    body = f'<p>{badge} &middot; <a href="/">new scenario</a></p>\n{rendered}'
    return HTMLResponse(shell("HPRC render", body))


@app.get("/edit", response_class=HTMLResponse)
async def edit_get():
    if not ALLOW_EDIT:
        return HTMLResponse(shell("Disabled", "<h1>Editing is disabled</h1>"), 403)
    with open(TEMPLATE_PATH, encoding="utf-8") as f:
        content = f.read()
    body = f"""
<h1>Edit <code>{TEMPLATE_NAME}</code></h1>
<p class="muted">Saved changes apply on the next render — no redeploy. The template
   is read fresh from disk per request.</p>
<form method="post" action="/edit">
  <textarea name="content" spellcheck="false">{html_mod.escape(content)}</textarea>
  <button type="submit">Save template</button>
</form>
"""
    return HTMLResponse(shell("Edit template", body))


@app.post("/edit")
async def edit_post(content: str = Form(...)):
    if not ALLOW_EDIT:
        return HTMLResponse(shell("Disabled", "<h1>Editing is disabled</h1>"), 403)
    with open(TEMPLATE_PATH, "w", encoding="utf-8") as f:
        f.write(content)
    return RedirectResponse("/edit", status_code=303)


@app.get("/health")
async def health():
    return JSONResponse({
        "ok": True,
        "provider": "anthropic" if os.getenv("ANTHROPIC_API_KEY") else "mock",
        "model": MODEL,
        "template": TEMPLATE_NAME,
        "edit_enabled": ALLOW_EDIT,
    })


if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("HPRC_DEMO_PORT", "8123"))
    uvicorn.run(app, host="0.0.0.0", port=port)
