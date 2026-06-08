"""gather_responses: chain earlier sequential responses into later prompts."""

from hprc import HPRCConfig, MockLLMClient, render_template_string


async def test_gather_chains_sequential_responses():
    client = MockLLMClient()  # echoes "[mock:default] <prompt>"
    cfg = HPRCConfig(llm_client=client)
    tpl = (
        '<prompt id="a">FIRST</prompt>'
        '<prompt id="b">SECOND</prompt>'
        '<x><response id="b"/></x>'
    )
    await render_template_string(tpl, config=cfg, gather_responses=True)

    a_call, b_call = client.calls[0], client.calls[1]
    assert a_call["prompt"].strip() == "FIRST"          # first prompt: no prior
    assert "[a]" in b_call["prompt"] and "FIRST" in b_call["prompt"]  # b sees a's response


async def test_no_gather_keeps_prompts_independent():
    client = MockLLMClient()
    cfg = HPRCConfig(llm_client=client)
    tpl = (
        '<prompt id="a">FIRST</prompt>'
        '<prompt id="b">SECOND</prompt>'
        '<x><response id="b"/></x>'
    )
    await render_template_string(tpl, config=cfg)  # gather off (default)
    assert client.calls[1]["prompt"].strip() == "SECOND"  # b unaffected by a


async def test_gather_excludes_async_prompts():
    client = MockLLMClient()
    cfg = HPRCConfig(llm_client=client)
    # a is concurrent (async="yes") -> not part of the gather chain; b is sequential.
    tpl = (
        '<prompt id="a" async="yes">FIRST</prompt>'
        '<prompt id="b">SECOND</prompt>'
        '<x><response id="a"/><response id="b"/></x>'
    )
    await render_template_string(tpl, config=cfg, gather_responses=True)

    b_call = next(c for c in client.calls if "SECOND" in c["prompt"])
    assert "FIRST" not in b_call["prompt"]  # async prompt isn't gathered into b
