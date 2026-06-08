"""Standalone HPRC example — no web framework required.

Run it::

    python examples/standalone.py

Shows the whole flow with the offline MockLLMClient: bindings, a named rule,
tools, two dependent prompts and a hidden response.
"""

import asyncio

import hprc
from hprc import MemoryCache, MockLLMClient, HPRCConfig

TEMPLATE = """<!DOCTYPE html>
<html><body>
  <h1>Hello <fill>customer.name</fill> (<fill>customer.tier</fill>)</h1>

  <prompt id="summary" model="gpt-5" condition="is_premium" temperature="0.2" cache="24h">
    Customer <fill>customer.name</fill> is interested in <param>product</param>.
    Write a one-line account summary.
  </prompt>

  <prompt id="upsell" model="gpt-5">
    Given: <include response="summary"/>
    Suggest one upsell.
  </prompt>

  <section><h2>Summary</h2><response id="summary"/></section>
  <section><h2>Upsell</h2><response id="upsell"/></section>
</body></html>"""


async def main():
    config = HPRCConfig(
        llm_client=MockLLMClient(),
        rules={"is_premium": lambda ctx: ctx["customer"]["tier"] == "premium"},
        tools={},
        cache=MemoryCache(),
    )
    html = await hprc.render_template_string(
        template_html=TEMPLATE,
        request={"query": {"product": "WidgetPro"}, "path": {}, "method": "GET"},
        bindings={"customer": {"name": "Ada", "tier": "premium"}},
        config=config,
    )
    print(html)


if __name__ == "__main__":
    asyncio.run(main())
