"""HPRC dashboard example — mixing CSV/data panels with concurrent LLM panels.

Run it::

    python examples/dashboard.py
    # writes examples/dashboard_output.html and prints a summary

This showcases how HPRC combines NON-LLM data with AI content in one render:

* **Data panels** (KPI tiles, the raw table) come straight from a CSV file that
  the controller loads into the `bindings` dict — no LLM involved (Level 1 of the
  data-composition design: `bindings` is the universal data plane).
* **AI panels** are `<prompt>` blocks that are *grounded* on that same CSV data
  via `<fill>`. The three top panels are independent, so HPRC runs them
  **concurrently**; `subject` depends on `exec_summary` (via `<include>`) so it
  runs in a later level; `risk` only runs when a CSV-derived **rule** fires.

To use a real model, swap `DemoLLMClient()` for e.g.
``OpenAIClient(api_key=...)`` / ``AnthropicClient(...)`` /
``OllamaClient(default_model="llama3")`` — nothing else changes.
"""

from __future__ import annotations

import asyncio
import csv
import os
import time
from collections import defaultdict

import hprc
from hprc import HPRCConfig
from hprc.llm import LLMClient

HERE = os.path.dirname(__file__)
CSV_PATH = os.path.join(HERE, "data", "sales.csv")
TEMPLATE = os.path.join(HERE, "templates", "dashboard.sprep.html")
OUTPUT = os.path.join(HERE, "dashboard_output.html")

TARGET = 30_000  # revenue target used by the `underperforming` rule


# ---------------------------------------------------------------------------
# 1. Build the bindings from a plain CSV file (this is ordinary Python — it could
#    just as easily be a SQL query or a REST call).
# ---------------------------------------------------------------------------
def load_sales_bindings(csv_path: str) -> dict:
    with open(csv_path, newline="") as f:
        rows = list(csv.DictReader(f))
    for r in rows:
        r["units"] = int(r["units"])
        r["revenue"] = int(r["revenue"])

    total_revenue = sum(r["revenue"] for r in rows)
    total_units = sum(r["units"] for r in rows)

    rev_by_region: dict[str, int] = defaultdict(int)
    units_by_product: dict[str, int] = defaultdict(int)
    for r in rows:
        rev_by_region[r["region"]] += r["revenue"]
        units_by_product[r["product"]] += r["units"]

    top_region = max(rev_by_region, key=rev_by_region.get)
    top_product = max(units_by_product, key=units_by_product.get)

    # A preformatted text table — used both for display (<pre>) and as grounding
    # text inside the prompts.
    header = f"{'Region':<8}{'Product':<12}{'Units':>6}{'Revenue':>10}"
    lines = [header, "-" * len(header)]
    for r in rows:
        lines.append(
            f"{r['region']:<8}{r['product']:<12}{r['units']:>6}{'$' + format(r['revenue'], ',') :>10}"
        )
    table_text = "\n".join(lines)

    return {
        "sales": {
            "source": os.path.basename(csv_path),
            "rows": rows,
            "row_count": len(rows),
            "region_count": len(rev_by_region),
            "total_revenue": total_revenue,
            "total_revenue_fmt": format(total_revenue, ","),
            "total_units": total_units,
            "target": TARGET,
            "target_fmt": format(TARGET, ","),
            "top_region": top_region,
            "top_region_revenue_fmt": format(rev_by_region[top_region], ","),
            "top_product": top_product,
            "top_product_units": units_by_product[top_product],
            "table_text": table_text,
        }
    }


# ---------------------------------------------------------------------------
# 2. A small demo client: sleeps briefly (so concurrency is *visible*) and
#    returns deterministic, realistic copy keyed on the prompt's intent.
#    Replace with any real provider client to get live output.
# ---------------------------------------------------------------------------
class DemoLLMClient(LLMClient):
    def __init__(self, delay: float = 0.4):
        self.delay = delay
        self.calls = 0

    async def generate(self, prompt, model=None, temperature=None, max_tokens=None, tools=None):
        self.calls += 1
        await asyncio.sleep(self.delay)
        p = prompt.lower()
        if "subject line" in p:
            return "WidgetPro Leads — Mind the Target Gap"
        if "headline" in p:
            return "Revenue reaches $25.9K as WidgetPro leads all four regions."
        if "focus" in p:
            return "Double down on North with WidgetPro while reviving GadgetMax in the East."
        if "risk" in p:
            return "Trailing the target by ~$4K signals softening demand outside the North."
        if "executive summary" in p:
            return ("WidgetPro drove most of the $25,865 in revenue across four regions, "
                    "led by the North. Results trail the $30,000 target, so next quarter "
                    "should push under-indexed regions and lift GadgetMax.")
        return "(demo response)"


# CSV-derived business rule: gates the conditional `risk` AI panel.
RULES = {
    "underperforming": lambda ctx: ctx["sales"]["total_revenue"] < ctx["sales"]["target"],
}


async def main():
    bindings = load_sales_bindings(CSV_PATH)
    client = DemoLLMClient(delay=0.4)
    config = HPRCConfig(llm_client=client, rules=RULES)

    started = time.perf_counter()
    html = await hprc.render_template(
        template_path=TEMPLATE,
        request={"query": {}, "path": {}, "method": "GET"},
        bindings=bindings,
        config=config,
    )
    elapsed = time.perf_counter() - started

    with open(OUTPUT, "w") as f:
        f.write(html)

    sequential = client.calls * client.delay
    s = bindings["sales"]
    print(f"Loaded {s['row_count']} CSV rows → revenue ${s['total_revenue_fmt']} "
          f"(target ${s['target_fmt']}), top region {s['top_region']}.")
    print(f"Ran {client.calls} prompts. Wall-clock: {elapsed:.2f}s "
          f"(sequential would be ~{sequential:.2f}s — concurrency at work).")
    print(f"Wrote {OUTPUT} — open it in a browser.")


if __name__ == "__main__":
    asyncio.run(main())
