#!/bin/sh
# Install and start the Fathom systemd service. Run as: sudo deploy/install-service.sh
set -eu

if [ "$(id -u)" -ne 0 ]; then
  echo "run with sudo: sudo $0" >&2
  exit 1
fi

here=$(cd "$(dirname "$0")" && pwd)

install -d -o cccadmin -g cccadmin -m 0750 /home/cccadmin/.fathom
install -m 0644 "$here/fathom.service" /etc/systemd/system/fathom.service
systemctl daemon-reload
systemctl enable --now fathom.service

if command -v ufw >/dev/null 2>&1 && ufw status | grep -q '^Status: active'; then
  ufw allow 8080/tcp
else
  echo "ufw is not active; no firewall rule added"
fi

sleep 2
systemctl --no-pager status fathom.service || true
