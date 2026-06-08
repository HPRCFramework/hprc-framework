"""Cache behavior tests."""

import pytest

from hprc import MemoryCache, MockLLMClient, HPRCConfig, render_template_string
from hprc.cache import build_cache_key, parse_ttl


# -- ttl parsing ------------------------------------------------------------
@pytest.mark.parametrize(
    "spec,expected",
    [
        ("24h", 86400),
        ("30m", 1800),
        ("10s", 10),
        ("2d", 172800),
        ("1w", 604800),
        ("3600", 3600),
        (None, None),
        ("", None),
        ("0", None),     # 0 disables caching
        ("0s", None),
    ],
)
def test_parse_ttl(spec, expected):
    assert parse_ttl(spec) == expected


def test_parse_ttl_invalid():
    with pytest.raises(ValueError):
        parse_ttl("banana")


# -- cache key --------------------------------------------------------------
def test_cache_key_changes_with_inputs():
    base = dict(prompt_text="hi", model="m", temperature=0.1, max_tokens=10, tools=[])
    k1 = build_cache_key(**base)
    k2 = build_cache_key(**{**base, "prompt_text": "ho"})
    k3 = build_cache_key(**{**base, "temperature": 0.9})
    assert k1 != k2 != k3
    # Tool ordering should not matter.
    ka = build_cache_key(**{**base, "tools": ["a", "b"]})
    kb = build_cache_key(**{**base, "tools": ["b", "a"]})
    assert ka == kb


# -- end to end caching -----------------------------------------------------
async def test_cached_prompt_only_calls_llm_once():
    client = MockLLMClient()
    cache = MemoryCache()
    cfg = HPRCConfig(llm_client=client, cache=cache)
    tpl = '<prompt id="a" cache="24h">hello</prompt><x><response id="a"/></x>'

    await render_template_string(tpl, config=cfg)
    await render_template_string(tpl, config=cfg)
    assert len(client.calls) == 1  # second render served from cache


async def test_uncached_prompt_calls_each_time():
    client = MockLLMClient()
    cfg = HPRCConfig(llm_client=client, cache=MemoryCache())
    tpl = '<prompt id="a">hello</prompt><x><response id="a"/></x>'

    await render_template_string(tpl, config=cfg)
    await render_template_string(tpl, config=cfg)
    assert len(client.calls) == 2


async def test_cache_zero_disables_caching():
    client = MockLLMClient()
    cfg = HPRCConfig(llm_client=client, cache=MemoryCache())
    tpl = '<prompt id="a" cache="0">hello</prompt><x><response id="a"/></x>'
    await render_template_string(tpl, config=cfg)
    await render_template_string(tpl, config=cfg)
    assert len(client.calls) == 2  # cache="0" means do not cache


async def test_cache_expiry():
    fake_time = {"now": 1000.0}
    cache = MemoryCache(time_func=lambda: fake_time["now"])
    client = MockLLMClient()
    cfg = HPRCConfig(llm_client=client, cache=cache)
    tpl = '<prompt id="a" cache="10s">hello</prompt><x><response id="a"/></x>'

    await render_template_string(tpl, config=cfg)
    fake_time["now"] += 100  # advance past TTL
    await render_template_string(tpl, config=cfg)
    assert len(client.calls) == 2
