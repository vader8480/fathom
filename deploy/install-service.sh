#!/bin/sh
# Install and start the Fathom systemd service on Ubuntu. Run as: sudo deploy/install-service.sh
#
# Defaults: a `fathom` system user, the checkout at /opt/fathom (with its .venv),
# data in /var/lib/fathom, port 8080. Override with environment variables, e.g. for
# an existing user's checkout:
#   sudo FATHOM_USER=cccadmin FATHOM_DIR=/home/cccadmin/Code/fathom FATHOM_DATA=/home/cccadmin/.fathom deploy/install-service.sh
set -eu

if [ "$(id -u)" -ne 0 ]; then
  echo "run with sudo: sudo $0" >&2
  exit 1
fi

here=$(cd "$(dirname "$0")" && pwd)
user=${FATHOM_USER:-fathom}
dir=${FATHOM_DIR:-/opt/fathom}
data=${FATHOM_DATA:-/var/lib/fathom}
port=${FATHOM_PORT:-8080}
public_url=${FATHOM_PUBLIC_URL:-http://$(hostname -f 2>/dev/null || hostname):$port}

if ! id "$user" >/dev/null 2>&1; then
  useradd --system --home-dir "$dir" --shell /usr/sbin/nologin "$user"
  echo "created system user $user"
fi
if [ ! -x "$dir/.venv/bin/gunicorn" ]; then
  echo "error: $dir/.venv/bin/gunicorn missing. From the checkout run:" >&2
  echo "  python3 -m venv --copies .venv && .venv/bin/pip install -e '.[serve,discovery]'" >&2
  exit 1
fi

install -d -o "$user" -g "$user" -m 0750 "$data"
sed -e "s|^User=.*|User=$user|" -e "s|^Group=.*|Group=$user|" \
    -e "s|^WorkingDirectory=.*|WorkingDirectory=$dir|" \
    -e "s|^Environment=FATHOM_DATA=.*|Environment=FATHOM_DATA=$data|" \
    -e "s|^Environment=FATHOM_PUBLIC_URL=.*|Environment=FATHOM_PUBLIC_URL=$public_url|" \
    -e "s|^ReadWritePaths=.*|ReadWritePaths=$data|" \
    -e "s|^ExecStart=.*|ExecStart=$dir/.venv/bin/gunicorn --bind 0.0.0.0:$port --workers 2 --threads 4 --timeout 180 --access-logfile - fathom.server:app|" \
    "$here/fathom.service" > /etc/systemd/system/fathom.service
case "$dir" in /home/*) sed -i 's|^ProtectHome=true|ProtectHome=read-only|' /etc/systemd/system/fathom.service ;; esac
chmod 0644 /etc/systemd/system/fathom.service
systemctl daemon-reload
systemctl enable --now fathom.service

if command -v ufw >/dev/null 2>&1 && ufw status | grep -q '^Status: active'; then
  ufw allow "$port"/tcp
else
  echo "ufw is not active; no firewall rule added"
fi

sleep 2
systemctl --no-pager status fathom.service || true
echo
echo "discovery check (same user and capabilities as the service):"
echo "  sudo systemd-run --uid=$user --gid=$user -p AmbientCapabilities=CAP_NET_RAW -t $dir/.venv/bin/fathom discovery doctor"
