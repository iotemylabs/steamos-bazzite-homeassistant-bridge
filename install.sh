#!/usr/bin/env bash
# steamdeck-bridge installer for SteamOS / Bazzite / generic Linux.
#
# Usage:
#   ./install.sh                         # interactive install
#   ./install.sh --mqtt-host 10.0.0.5 --mqtt-user ha --mqtt-pass secret \
#                --device-id deck-livingroom --device-name "Living Room Deck"
#   ./install.sh --no-mqtt               # REST/WS only, no broker questions
#   ./install.sh --uninstall
#
# Everything is user-level: no root, no rpm-ostree layering, survives OS updates.
#
# The daemon is installed with `uv tool install` using a uv-managed Python
# (downloaded into ~/.local/share/uv/python) rather than the OS interpreter.
# A pipx venv symlinks /usr/bin/python3.X, so every Fedora/SteamOS base bump
# that drops the old minor version leaves the service failing with
# "status=203/EXEC ... No such file or directory". A uv-managed interpreter
# lives in $HOME and survives those updates. Override the version with
# SDB_PYTHON=3.12 if needed.
set -euo pipefail

REPO_URL="https://github.com/iotemylabs/steamos-bazzite-homeassistant-bridge"
PKG_SPEC="git+${REPO_URL}.git"
CONFIG_DIR="${HOME}/.config/steamdeck-bridge"
CONFIG_FILE="${CONFIG_DIR}/config.toml"
UNIT_DIR="${HOME}/.config/systemd/user"
UNIT_FILE="${UNIT_DIR}/steamdeck-bridge.service"
SERVICE="steamdeck-bridge"
PYTHON_VERSION="${SDB_PYTHON:-3.13}"
PIPX_VENV="${HOME}/.local/share/pipx/venvs/steamdeck-bridge"

MQTT_HOST="" MQTT_USER="" MQTT_PASS="" DEVICE_ID="" DEVICE_NAME=""
NO_MQTT=0 UNINSTALL=0 NONINTERACTIVE=0

info()  { printf '\033[1;32m==>\033[0m %s\n' "$*"; }
warn()  { printf '\033[1;33mwarning:\033[0m %s\n' "$*" >&2; }
die()   { printf '\033[1;31merror:\033[0m %s\n' "$*" >&2; exit 1; }

while [[ $# -gt 0 ]]; do
    case "$1" in
        --mqtt-host)   MQTT_HOST="$2"; NONINTERACTIVE=1; shift 2 ;;
        --mqtt-user)   MQTT_USER="$2"; shift 2 ;;
        --mqtt-pass)   MQTT_PASS="$2"; shift 2 ;;
        --device-id)   DEVICE_ID="$2"; shift 2 ;;
        --device-name) DEVICE_NAME="$2"; shift 2 ;;
        --no-mqtt)     NO_MQTT=1; NONINTERACTIVE=1; shift ;;
        --uninstall)   UNINSTALL=1; shift ;;
        -h|--help)     grep '^#' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *)             die "unknown option: $1 (see --help)" ;;
    esac
done

# ---------------------------------------------------------------- uninstall --
if [[ $UNINSTALL -eq 1 ]]; then
    info "Stopping and removing the ${SERVICE} service"
    systemctl --user disable --now "${SERVICE}" 2>/dev/null || true
    rm -f "${UNIT_FILE}"
    systemctl --user daemon-reload || true
    if command -v uv >/dev/null 2>&1; then
        uv tool uninstall steamdeck-bridge 2>/dev/null || true
    fi
    if [[ -d "${PIPX_VENV}" ]]; then
        # Legacy pipx install (pre-uv). pipx itself may be broken by the same
        # Python bump, so fall back to removing the venv by hand.
        pipx uninstall steamdeck-bridge 2>/dev/null || rm -rf "${PIPX_VENV}"
    fi
    rm -f "${HOME}/.local/bin/steamdeck-bridge"
    info "Left ${CONFIG_DIR} and ~/.cache/steamdeck-bridge in place (remove manually if desired)"
    exit 0
fi

# ------------------------------------------------------------------- checks --
[[ "$(uname -s)" == "Linux" ]] || die "this installer targets SteamOS/Bazzite/Linux"
[[ $EUID -ne 0 ]] || die "run as your normal user, not root"
command -v systemctl >/dev/null 2>&1 || die "systemd (user session) is required"

# ------------------------------------------------------------------ install --
# Prefer an existing checkout (script run from the repo) over the git URL, so
# development installs pick up local changes.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" 2>/dev/null && pwd || true)"
if [[ -n "${SCRIPT_DIR}" && -f "${SCRIPT_DIR}/pyproject.toml" ]]; then
    PKG_SPEC="${SCRIPT_DIR}"
    info "Installing from local checkout: ${PKG_SPEC}"
else
    info "Installing from ${PKG_SPEC}"
fi

export PATH="${HOME}/.local/bin:${PATH}"
if ! command -v uv >/dev/null 2>&1; then
    # uv is a static binary with no Python dependency, so it can't be broken
    # by an OS Python bump the way a pip-installed pipx can.
    info "uv not found; installing the standalone uv binary to ~/.local/bin"
    command -v curl >/dev/null 2>&1 || die "curl is required to download uv"
    curl -LsSf https://astral.sh/uv/install.sh | env UV_NO_MODIFY_PATH=1 sh \
        || die "could not install uv; see https://docs.astral.sh/uv/getting-started/installation/"
    command -v uv >/dev/null 2>&1 || die "uv installed but not on PATH; expected ~/.local/bin/uv"
fi

# Migrate a legacy pipx install so its dangling symlink doesn't shadow the
# uv-managed entry point. pipx itself may be broken, hence the rm fallback.
if [[ -d "${PIPX_VENV}" ]]; then
    info "Removing legacy pipx install (replaced by uv-managed Python)"
    pipx uninstall steamdeck-bridge 2>/dev/null || rm -rf "${PIPX_VENV}"
    rm -f "${HOME}/.local/bin/steamdeck-bridge"
fi

info "Installing with uv-managed Python ${PYTHON_VERSION}"
uv tool install --force --reinstall \
    --python "${PYTHON_VERSION}" --python-preference only-managed \
    "${PKG_SPEC}"

BIN="${HOME}/.local/bin/steamdeck-bridge"
[[ -x "${BIN}" ]] || die "expected ${BIN} after install; check uv output above"

# ------------------------------------------------------------------- config --
if [[ -f "${CONFIG_FILE}" ]]; then
    info "Keeping existing config: ${CONFIG_FILE}"
else
    info "Creating ${CONFIG_FILE}"
    if [[ $NONINTERACTIVE -eq 0 && -t 0 ]]; then
        read -rp "Device id (unique per device) [steamdeck]: " DEVICE_ID
        read -rp "Device name shown in Home Assistant [Steam Deck]: " DEVICE_NAME
        read -rp "MQTT broker host (empty to disable MQTT): " MQTT_HOST
        if [[ -n "${MQTT_HOST}" ]]; then
            read -rp "MQTT username (optional): " MQTT_USER
            read -rsp "MQTT password (optional): " MQTT_PASS; echo
        else
            NO_MQTT=1
        fi
    fi
    DEVICE_ID="${DEVICE_ID:-steamdeck}"
    DEVICE_NAME="${DEVICE_NAME:-Steam Deck}"
    MQTT_ENABLED=true
    [[ $NO_MQTT -eq 1 || -z "${MQTT_HOST}" ]] && MQTT_ENABLED=false

    mkdir -p "${CONFIG_DIR}"
    cat > "${CONFIG_FILE}" <<EOF
[device]
id = "${DEVICE_ID}"
name = "${DEVICE_NAME}"

[http]
host = "127.0.0.1"
port = 8480
token = ""

[mqtt]
enabled = ${MQTT_ENABLED}
host = "${MQTT_HOST:-homeassistant.local}"
port = 1883
username = "${MQTT_USER}"
password = "${MQTT_PASS}"
EOF
    chmod 600 "${CONFIG_FILE}"
fi

# ------------------------------------------------------------------ systemd --
info "Installing user service"
mkdir -p "${UNIT_DIR}"
cat > "${UNIT_FILE}" <<EOF
[Unit]
Description=SteamOS/Bazzite Home Assistant bridge
Documentation=${REPO_URL}
After=network-online.target
Wants=network-online.target

[Service]
Type=exec
ExecStart=${BIN}
Restart=on-failure
RestartSec=5
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=default.target
EOF
systemctl --user daemon-reload
systemctl --user enable --now "${SERVICE}"

# ------------------------------------------------------------------- verify --
sleep 3
if ! systemctl --user is-active --quiet "${SERVICE}"; then
    systemctl --user status "${SERVICE}" --no-pager || true
    die "service failed to start; see: journalctl --user -u ${SERVICE}"
fi

TOKEN="$(sed -n 's/^token = "\(.*\)"/\1/p' "${CONFIG_FILE}" | head -n1)"
info "Service running."
echo
echo "  Status:   systemctl --user status ${SERVICE}"
echo "  Logs:     journalctl --user -fu ${SERVICE}"
echo "  Config:   ${CONFIG_FILE}"
echo "  API:      curl -H \"Authorization: Bearer ${TOKEN:-<see config>}\" http://127.0.0.1:8480/api/state"
echo
if [[ "${MQTT_ENABLED:-true}" == "true" && -f "${CONFIG_FILE}" ]]; then
    echo "Home Assistant entities will appear automatically once the MQTT broker is reachable."
    echo "Media player setup + automations: ${REPO_URL}/blob/main/docs/HOME_ASSISTANT.md"
fi
