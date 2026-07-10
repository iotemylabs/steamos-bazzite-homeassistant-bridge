# Installation

The bridge is a pure-Python user-level daemon: no root, no layered packages,
survives SteamOS/Bazzite OS updates.

## Scripted install (recommended)

From a Desktop Mode terminal or SSH session on the device:

```bash
curl -fsSL https://raw.githubusercontent.com/iotemylabs/steamos-bazzite-homeassistant-bridge/main/install.sh | bash
```

or from a checkout: `./install.sh`. Flags for automation:

```
--mqtt-host HOST      MQTT broker (omit or --no-mqtt for REST/WS only)
--mqtt-user USER      broker username
--mqtt-pass PASS      broker password
--device-id ID        unique per device (default: steamdeck)
--device-name NAME    shown in Home Assistant (default: Steam Deck)
--uninstall           stop + remove the service and package
```

The script installs via pipx (or uv), writes
`~/.config/steamdeck-bridge/config.toml` (kept if it already exists), installs
the systemd user unit, starts it, and prints the API token. Re-running is safe —
it upgrades in place.

## Manual install

```bash
# 1. Install (pipx ships on both SteamOS and Bazzite; uv also works)
pipx install "git+https://github.com/iotemylabs/steamos-bazzite-homeassistant-bridge.git"
# from a git checkout instead:  pipx install /path/to/checkout

# 2. Configure
mkdir -p ~/.config/steamdeck-bridge
cp config/config.example.toml ~/.config/steamdeck-bridge/config.toml
nano ~/.config/steamdeck-bridge/config.toml   # set [mqtt] host/username/password,
                                              # and a unique [device] id per device

# 3. Run as a user service
mkdir -p ~/.config/systemd/user
cp systemd/steamdeck-bridge.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now steamdeck-bridge

# 4. Verify
systemctl --user status steamdeck-bridge
TOKEN=$(grep '^token' ~/.config/steamdeck-bridge/config.toml | cut -d'"' -f2)
curl -H "Authorization: Bearer $TOKEN" http://127.0.0.1:8480/api/state
```

Notes:

- **SteamOS**: user services keep running in both Gaming and Desktop Mode.
  `pipx` is preinstalled on SteamOS 3.5+; on older builds
  `python -m pip install --user pipx` first.
- **Bazzite**: everything above works as-is; `uv` is preinstalled on recent
  images. Do **not** use `rpm-ostree install` for this — user-level install is
  the point.
- **Gaming Mode**: the service reads gamescope's X display; no Decky Loader
  required.
- To keep the device from suspending while HA needs it awake, that's a Steam
  setting (Settings → Power), not a bridge concern.

## Multiple devices

Install on each device with a unique `[device] id` (`deck-livingroom`,
`ally-bedroom`, …). Each shows up as its own HA device; no coordination needed.

## LAN exposure & TLS

Default is `127.0.0.1` (MQTT is outbound, so HA discovery works without
opening any port). You only need LAN exposure for artwork URLs / REST control:

- Simple: `[http] host = "0.0.0.0"` — bearer token still gates everything.
- Better: keep localhost and reverse-proxy with TLS, e.g. caddy:

```
# /etc/caddy/Caddyfile (or run caddy as the user)
deck.example.lan {
    reverse_proxy 127.0.0.1:8480
    tls internal
}
```

## Upgrading

Re-run the install script (safe, keeps your config), or manually:

```bash
pipx install --force "git+https://github.com/iotemylabs/steamos-bazzite-homeassistant-bridge.git"
systemctl --user restart steamdeck-bridge
```

## Uninstall

```bash
systemctl --user disable --now steamdeck-bridge
rm ~/.config/systemd/user/steamdeck-bridge.service
pipx uninstall steamdeck-bridge
rm -rf ~/.config/steamdeck-bridge ~/.cache/steamdeck-bridge
```

## Troubleshooting

| Symptom | Check |
|---|---|
| No entities in HA | `journalctl --user -u steamdeck-bridge` — MQTT credentials/host; broker reachable? |
| Game not detected in Gaming Mode | `xprop -root -display :1 GAMESCOPE_FOCUSED_APP` from Desktop Mode SSH |
| Game not detected in Desktop Mode | `pgrep -af 'SteamLaunch AppId='` should show the reaper line |
| Shortcut shows raw AppID, no title | Shortcut added while bridge running? `POST /api/actions/refresh_library` |
| Artwork 404 for shortcuts | Add art via SRM/BoilR (grid folder) or set `steamgriddb_api_key` |
| Actions do nothing | `[actions]` switches in config; `systemctl suspend` works for your user? |
