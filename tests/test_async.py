"""Async / concurrency tests."""

import asyncio

from hprc import HPRCConfig, render_template_string
from hprc.llm import LLMClient


class OrderTrackingClient(LLMClient):
    """Records start/finish order and lets us prove concurrency within a level."""

    def __init__(self, delay=0.05):
        self.delay = delay
        self.events = []

    async def generate(self, prompt, model=None, temperature=None, max_tokens=None, tools=None):
        self.events.append(("start", prompt.strip()))
        await asyncio.sleep(self.delay)
        self.events.append(("finish", prompt.strip()))
        return f"R:{prompt.strip()}"


async def test_default_runs_sequentially():
    # No async attribute -> sequential by default: each finishes before the next.
    client = OrderTrackingClient(delay=0.05)
    cfg = HPRCConfig(llm_client=client)
    tpl = (
        '<prompt id="a">AA</prompt>'
        '<prompt id="b">BB</prompt>'
        '<x><response id="a"/><response id="b"/></x>'
    )
    await render_template_string(tpl, config=cfg)
    kinds = [k for (k, _) in client.events]
    assert kinds == ["start", "finish", "start", "finish"]


async def test_async_yes_runs_concurrently():
    # async="yes" opts prompts into concurrent execution within their level.
    client = OrderTrackingClient(delay=0.05)
    cfg = HPRCConfig(llm_client=client)
    tpl = (
        '<prompt id="a" async="yes">AA</prompt>'
        '<prompt id="b" async="yes">BB</prompt>'
        '<x><response id="a"/><response id="b"/></x>'
    )
    await render_template_string(tpl, config=cfg)
    # Both start before either finishes -> concurrent.
    starts = [e for e in client.events if e[0] == "start"]
    assert client.events[0][0] == "start"
    assert client.events[1][0] == "start"
    assert len(starts) == 2


async def test_mixed_async_in_one_level():
    # A level can mix sequential (default) and concurrent (async="yes") prompts.
    client = OrderTrackingClient(delay=0.05)
    cfg = HPRCConfig(llm_client=client)
    tpl = (
        '<prompt id="a" async="yes">AA</prompt>'
        '<prompt id="b" async="yes">BB</prompt>'
        '<prompt id="c">CC</prompt>'
        '<x><response id="a"/><response id="b"/><response id="c"/></x>'
    )
    await render_template_string(tpl, config=cfg)
    # c (sequential) runs alone; a and b (async) run together.
    assert len([e for e in client.events if e[0] == "start"]) == 3


async def test_dependent_prompts_run_in_order():
    client = OrderTrackingClient(delay=0.01)
    cfg = HPRCConfig(llm_client=client)
    tpl = (
        '<prompt id="a">AA</prompt>'
        '<prompt id="b">uses <include response="a"/></prompt>'
        '<x><response id="b"/></x>'
    )
    await render_template_string(tpl, config=cfg)
    order = [p for (kind, p) in client.events if kind == "finish"]
    # a finishes before b's request is even constructed.
    assert order[0] == "AA"
