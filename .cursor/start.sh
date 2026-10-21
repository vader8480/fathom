#!/usr/bin/env bash
# Cloud Agent boot: run the Fathom dev server in the "fathom-server" tmux session.
set -euo pipefail
cd "$(dirname "$0")/.."

port="${FATHOM_PORT:-8080}"
session="fathom-server"
tmux_conf=()
[ -f /exec-daemon/tmux.portal.conf ] && tmux_conf=(-f /exec-daemon/tmux.portal.conf)

if curl -fsS "http://127.0.0.1:${port}/healthz" >/dev/null 2>&1; then
  echo "fathom already answering on :${port}"
  exit 0
fi

if [ ! -x .venv/bin/fathom ]; then
  echo "error: .venv/bin/fathom missing; the install step did not run" >&2
  exit 1
fi

tmux "${tmux_conf[@]}" kill-session -t "=${session}" 2>/dev/null || true
tmux "${tmux_conf[@]}" new-session -d -s "${session}" -c "$PWD" \
  "bash -lc '.venv/bin/fathom serve --host 0.0.0.0 --port ${port} 2>&1 | tee /tmp/fathom-server.log'"

for _ in $(seq 1 60); do
  if curl -fsS "http://127.0.0.1:${port}/healthz" >/dev/null 2>&1; then
    echo "fathom ready on http://localhost:${port} (tmux session ${session}, log /tmp/fathom-server.log)"
    exit 0
  fi
  sleep 1
done
echo "error: fathom did not answer /healthz within 60 s; see /tmp/fathom-server.log" >&2
exit 1
