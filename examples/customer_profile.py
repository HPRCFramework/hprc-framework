"""Canonical HPRC example — the TYPICAL flow:  business logic → bindings → template.

This is the pattern you'll use in a real app:

    1. Your Python code runs business logic and produces a plain dict (JSON-like).
       (In production this is where you'd query a database, call services, and
        apply business rules.)
    2. You pass that dict to HPRC as `bindings` when you render the template.
    3. The SAME data is then available — via <fill> — in BOTH the visible HTML
       AND the embedded <prompt>, inside the template file
       (templates/customer_profile.sprep.html).

The template lives in its OWN file; this Python file only supplies data and calls
the renderer. The default LLM client is an offline mock, so this runs with no API key.

Run it::

    python examples/customer_profile.py
"""

from __future__ import annotations

import asyncio
import json
import os
from datetime import date

import hprc
from hprc import HPRCConfig, MockLLMClient

HERE = os.path.dirname(__file__)
TEMPLATE = os.path.join(HERE, "templates", "customer_profile.sprep.html")


# ---------------------------------------------------------------------------
# A tiny stand-in "database". In a real app this would be SQL / a REST service.
# ---------------------------------------------------------------------------
_CUSTOMERS = {
    "1001": {
        "name": "Ada Lovelace",
        "dob": "1970-12-10",
        "tier": "premium",
        "city": "London",
    },
}


def _age_on(dob_iso: str, today: date) -> int:
    """Whole years between a date of birth and a given day."""
    dob = date.fromisoformat(dob_iso)
    return today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))


# ---------------------------------------------------------------------------
# BUSINESS LOGIC → BINDINGS
# Returns a plain, JSON-serializable dict. This is exactly what you hand to HPRC
# as `bindings`. Derived values (age) and business rules (segment) are computed
# here, in Python — never in the template.
# ---------------------------------------------------------------------------
def build_customer_bindings(customer_id: str, today: date) -> dict:
    record = _CUSTOMERS[customer_id]
    age = _age_on(record["dob"], today)                 # derived value
    segment = "senior" if age >= 55 else "standard"     # a business rule

    return {
        "customer": {
            "name": record["name"],
            "age": age,            # e.g. 55 — used in BOTH the HTML and the prompt
            "segment": segment,    # e.g. "senior"
            "tier": record["tier"],
            "city": record["city"],
        }
    }


async def main() -> None:
    today = date(2026, 6, 6)  # fixed so the demo is reproducible

    # 1. business logic produces the data
    bindings = build_customer_bindings("1001", today)
    print("Business logic produced these bindings (JSON):")
    print(json.dumps(bindings, indent=2))

    # 2. configure HPRC (swap MockLLMClient for OpenAIClient/AnthropicClient/... anytime)
    config = HPRCConfig(llm_client=MockLLMClient())

    # 3. render the template file, passing the business data via `bindings`
    html = await hprc.render_template(
        template_path=TEMPLATE,
        request={"query": {"product": "Smart Garden Kit"}, "path": {}, "method": "GET"},
        bindings=bindings,          # <-- the same data flows into the HTML and the prompt
        config=config,
    )

    print("\n--- Rendered HTML ---\n")
    print(html)


if __name__ == "__main__":
    asyncio.run(main())
