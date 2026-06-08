"""FastAPI sample application for HPRC.

Run it::

    pip install -e ".[fastapi]"      # from the repo root
    uvicorn examples.fastapi_app:app --reload

Then open:  http://127.0.0.1:8000/customer/42?product=WidgetPro

This demonstrates the full application-developer workflow:

* receive the HTTP request,
* build the application bindings (business logic stays in Python),
* register rules (named predicates) and tools (allowlisted callables),
* configure the LLM provider (MockLLMClient here — no API key needed),
* call HPRC's renderer and return the final HTML.

The developer writes **no prompt-orchestration logic**: HPRC resolves fills,
evaluates the rule, builds the dependency graph (``upsell`` depends on
``summary``) and executes the prompts for you.
"""

from __future__ import annotations

import os

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse

import hprc
from hprc import MemoryCache, MockLLMClient, HPRCConfig

# Optionally use a real provider when an API key is present.
try:  # pragma: no cover - optional dependency
    from hprc import OpenAIClient

    _HAS_OPENAI = True
except Exception:  # pragma: no cover
    _HAS_OPENAI = False

app = FastAPI(title="HPRC demo")

TEMPLATE = os.path.join(os.path.dirname(__file__), "templates", "customer.sprep.html")


# --- fake "business logic" (would be a DB in a real app) -------------------
_CUSTOMERS = {
    "42": {"name": "Ada Lovelace", "tier": "premium"},
    "7": {"name": "Charles Babbage", "tier": "free"},
}
_ACCOUNTS = {
    "42": {"balance": "$12,400"},
    "7": {"balance": "$0"},
}


def load_customer(customer_id: str) -> dict:
    return _CUSTOMERS.get(customer_id, {"name": "Unknown", "tier": "free"})


def load_account(customer_id: str) -> dict:
    return _ACCOUNTS.get(customer_id, {"balance": "$0"})


# --- tools (external to templates, allowlisted by name) --------------------
def crm_lookup(customer: str) -> str:
    """Look up CRM notes for a customer."""
    return f"CRM notes for {customer}: long-time customer, no open tickets."


def pricing_engine(product: str) -> str:
    """Return current pricing for a product."""
    return f"{product} is $49/mo with a 14-day trial."


def _build_llm_client():
    if _HAS_OPENAI and os.getenv("OPENAI_API_KEY"):
        return OpenAIClient(api_key=os.environ["OPENAI_API_KEY"])
    # Default: deterministic, offline mock so the demo runs with no API key.
    return MockLLMClient()


@app.get("/customer/{customer_id}", response_class=HTMLResponse)
async def customer_page(customer_id: str, request: Request):
    bindings = {
        "customer": load_customer(customer_id),
        "account": load_account(customer_id),
    }

    RULES = {
        "is_premium_customer": lambda ctx: ctx["customer"]["tier"] == "premium",
    }

    TOOLS = {
        "crm_lookup": crm_lookup,
        "pricing_engine": pricing_engine,
    }

    config = HPRCConfig(
        llm_client=_build_llm_client(),
        rules=RULES,
        tools=TOOLS,
        cache=MemoryCache(),
    )

    html = await hprc.render_template(
        template_path=TEMPLATE,
        request=request,
        bindings=bindings,
        config=config,
    )
    return HTMLResponse(html)


@app.get("/", response_class=HTMLResponse)
async def index():
    return HTMLResponse(
        '<h1>HPRC demo</h1><ul>'
        '<li><a href="/customer/42?product=WidgetPro">premium customer (42)</a></li>'
        '<li><a href="/customer/7?product=WidgetPro">free customer (7)</a></li>'
        "</ul>"
    )
