#!/bin/bash
# Install the Linux computer-use stack so the Hermes agent can drive a real GUI
# (the "no-API hammer" for fingerprint-gated web UIs / legacy desktop apps).
# Idempotent + safe to re-run. Called by bootstrap.sh (so the snapshot bakes it)
# and runnable standalone to roll onto an existing box.
#
# Pieces: a headless desktop (Xvfb :99 + a fixed-address dbus session bus +
# AT-SPI + openbox) as a systemd service, plus the cua-driver MCP binary for the
# hermes user. The cua-driver MCP server itself is registered in config.yaml's
# `mcp_servers:` block (templated), so this script only installs the runtime.
set -uo pipefail

HERMES_USER="${HERMES_USER:-hermes}"

echo "[computer-use] installing desktop packages…"
export DEBIAN_FRONTEND=noninteractive
apt-get install -y -qq \
  xvfb x11-utils x11-xserver-utils openbox dbus-x11 at-spi2-core \
  xterm xdotool imagemagick fonts-dejavu >/dev/null 2>&1 || \
  echo "[computer-use] WARN: apt install had issues (continuing)"

# cua-driver for the hermes user. The Hermes install helper is macOS-gated on
# our fork, so use trycua's direct Linux installer (prebuilt x86_64 binary).
if [[ ! -x "/home/${HERMES_USER}/.local/bin/cua-driver" ]]; then
  echo "[computer-use] installing cua-driver for ${HERMES_USER}…"
  sudo -u "${HERMES_USER}" bash -lc \
    'curl -fsSL https://raw.githubusercontent.com/trycua/cua/main/libs/cua-driver/scripts/_install-rust.sh | bash' \
    >/dev/null 2>&1 || echo "[computer-use] WARN: cua-driver install failed"
else
  echo "[computer-use] cua-driver already present."
fi

echo "[computer-use] writing headless-desktop service…"
cat > /usr/local/bin/headless-desktop.sh <<'SH'
#!/bin/bash
# Xvfb display + fixed-address dbus session bus (so a separately-spawned
# cua-driver joins the SAME bus for AT-SPI) + at-spi bus + openbox WM.
export DISPLAY=:99
Xvfb :99 -screen 0 1280x800x24 -ac +extension RANDR +extension XTEST +extension GLX >/tmp/xvfb.log 2>&1 &
sleep 2
rm -f /tmp/cua_bus
dbus-daemon --session --address=unix:path=/tmp/cua_bus --nofork >/tmp/dbus.log 2>&1 &
sleep 1
export DBUS_SESSION_BUS_ADDRESS=unix:path=/tmp/cua_bus
/usr/libexec/at-spi-bus-launcher --launch-immediately >/tmp/atspi.log 2>&1 &
sleep 1
gsettings set org.gnome.desktop.interface toolkit-accessibility true 2>/dev/null || true
exec openbox
SH
chmod +x /usr/local/bin/headless-desktop.sh

cat > /etc/systemd/system/headless-desktop.service <<UNIT
[Unit]
Description=NoDesk headless desktop (Xvfb+dbus+at-spi+openbox) for Hermes computer-use
After=network.target

[Service]
User=${HERMES_USER}
Type=simple
ExecStart=/usr/local/bin/headless-desktop.sh
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
UNIT

if command -v systemctl >/dev/null 2>&1; then
  systemctl daemon-reload || true
  systemctl enable --now headless-desktop.service 2>/dev/null || \
    systemctl enable headless-desktop.service 2>/dev/null || true
fi
echo "[computer-use] done."
