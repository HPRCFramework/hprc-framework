#!/usr/bin/env bash
# Deploy / redeploy the HPRC Live Demo to a server as a systemd --user service.
#
# Usage:   examples/live/deploy.sh [user@host]
# Or set:  export HPRC_DEPLOY_TARGET=user@host
#
# Idempotent: rsyncs the repo, (re)creates the venv, installs hprc + extras,
# installs/refreshes the systemd unit (it uses %h, so it works for any user), and
# restarts the service. The Claude API key is read from ~/hprc-demo/hprc-demo.env
# on the SERVER (never sent by this script) — create it once with:
#     ANTHROPIC_API_KEY=sk-ant-...
set -euo pipefail

TARGET="${1:-${HPRC_DEPLOY_TARGET:-user@your-server}}"
if [ "$TARGET" = "user@your-server" ]; then
  echo "set a target:  examples/live/deploy.sh user@host   (or export HPRC_DEPLOY_TARGET)"
  exit 2
fi

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
REMOTE_USER="${TARGET%@*}"
REMOTE_HOME="$(ssh "$TARGET" 'echo $HOME')"
REMOTE_BASE="$REMOTE_HOME/hprc-demo"
REMOTE_REPO="$REMOTE_BASE/Prep"

echo ">> deploying $REPO_ROOT  ->  $TARGET:$REMOTE_REPO"
ssh "$TARGET" "mkdir -p '$REMOTE_REPO'"

# 1. sync source (exclude local venv / caches / git)
rsync -az --delete \
  --exclude '.venv' --exclude '__pycache__' --exclude '.git' \
  --exclude '*.pyc' --exclude 'examples/live/templates/*.bak' \
  "$REPO_ROOT/" "$TARGET:$REMOTE_REPO/"

# 2. venv + install (editable, with fastapi + anthropic extras)
ssh "$TARGET" "
  set -e
  cd '$REMOTE_REPO'
  [ -d .venv ] || python3 -m venv .venv
  ./.venv/bin/pip install -q --upgrade pip
  ./.venv/bin/pip install -q -e '.[fastapi,anthropic]'
  # ensure an env file exists (you fill in the key; root-readable only)
  if [ ! -f '$REMOTE_BASE/hprc-demo.env' ]; then
    echo 'ANTHROPIC_API_KEY=' > '$REMOTE_BASE/hprc-demo.env'
    chmod 600 '$REMOTE_BASE/hprc-demo.env'
    echo '   (created empty $REMOTE_BASE/hprc-demo.env — add your ANTHROPIC_API_KEY)'
  fi
"

# 3. systemd --user unit + linger so it survives logout/reboot
ssh "$TARGET" "
  set -e
  mkdir -p ~/.config/systemd/user
  cp '$REMOTE_REPO/examples/live/hprc-demo.service' ~/.config/systemd/user/hprc-demo.service
  loginctl enable-linger '$REMOTE_USER' 2>/dev/null || \
    echo '   (to survive logout/reboot, enable linger once: sudo loginctl enable-linger $REMOTE_USER)'
  systemctl --user daemon-reload
  systemctl --user enable hprc-demo
  systemctl --user restart hprc-demo
  sleep 3
  systemctl --user status hprc-demo --no-pager | head -12
"

echo ">> done. open: http://${TARGET#*@}:8123/"
