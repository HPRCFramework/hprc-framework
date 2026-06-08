# HPRC Live Demo (real Claude)

A full-stack FastAPI page rendered by HPRC, backed by the **Anthropic (Claude)**
provider. It showcases the headline features end-to-end: tacit `<prompt>` blocks,
a `<fill>`/`<param>` data binding, a **rule** gating a premium-only prompt, and a
**dependency** (the `upsell` prompt includes `summary`'s response).

## Files
- `app.py` — the FastAPI app (form → render → result; plus `/edit` and `/health`).
- `templates/assistant.sprep.html` — the SPREP template, **read fresh per request**.
- `hprc-demo.service` — systemd `--user` unit (follows the project's service template).
- `deploy.sh` — one-command deploy/redeploy to the server.

## Run locally
```bash
pip install -e ".[fastapi,anthropic]"
export ANTHROPIC_API_KEY=sk-ant-...
python examples/live/app.py            # http://127.0.0.1:8123/
```
Without a key it still runs, using the offline `MockLLMClient` (clearly labelled).

## Deploy to a server (systemd `--user` service)
```bash
examples/live/deploy.sh user@your-server      # or: export HPRC_DEPLOY_TARGET=user@host
```
The Claude key is read from `~/hprc-demo/hprc-demo.env` on the server (never sent by
the deploy script). Set it once:
```bash
ssh user@your-server "echo 'ANTHROPIC_API_KEY=sk-ant-...' > ~/hprc-demo/hprc-demo.env && chmod 600 ~/hprc-demo/hprc-demo.env && systemctl --user restart hprc-demo"
```
Then open **http://your-server:8123/**. The unit uses systemd's `%h`, so it works for
any user; `loginctl enable-linger` keeps it running across logout/reboot.

## Updating prompts — no redeploy
The template is loaded from disk on every request, so changing the prompts is live:
- **In the browser:** open `/edit`, edit, Save — the next render uses it.
- **On the server:** edit `~/hprc-demo/Prep/examples/live/templates/assistant.sprep.html`.

**Redeploy is only needed when you change `app.py` or the library** — re-run
`deploy.sh` (it rsyncs, reinstalls, and restarts the service).

> Note: the repo is the source of truth. `deploy.sh` ships the repo's template, so
> it **overwrites** server-side `/edit` changes. Use `/edit` for live experiments;
> to make a prompt change permanent, edit the file in the repo and redeploy.

## Notes
- The `/edit` page writes the template file with no auth — fine for a LAN demo;
  set `HPRC_DEMO_ALLOW_EDIT=0` to disable it.
- Model defaults to `claude-sonnet-4-6` (override with `HPRC_DEMO_MODEL`).
