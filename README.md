# steamdeck-bridge

Real-time **SteamOS / Bazzite → Home Assistant** bridge. A lightweight Python
daemon (user-level systemd service) that detects what's playing on your Steam
Deck, Bazzite HTPC, Legion Go, or ROG Ally and exposes it over **REST**,
**WebSocket**, and **MQTT with Home Assistant discovery** — think
[go-hass-agent](https://github.com/joshuar/go-hass-agent), but purpose-built for
Gamescope, Steam, EmuDeck, Heroic, and Lutris.

## What you get

- **Now playing**: Steam games, non-Steam shortcuts, Steam ROM Manager /
  EmuDeck emulator shortcuts (with ROM title + platform), Heroic and Lutris
  games — detected via Gamescope X11 atoms and Steam's process tree, **no UI
  automation, no Steam API key**.
- **Device state**: gaming vs desktop mode, battery, docked, awake, Steam login.
- **Home Assistant**: auto-discovered sensors + action buttons over MQTT;
  media-player card with artwork via the documented template/HACS setup.
- **Actions**: launch/switch/close game, restart Steam, suspend, shutdown,
  reboot, refresh library — from HA or any HTTP client.
- **Artwork**: hero, capsule (cover), header, logo, icon — resolved from the
  Steam cache, grid overrides, Heroic, SteamGridDB (optional), and served locally.
- **Local-only by default** with bearer-token auth; TLS via your reverse proxy.

## Quick start (on the device)

```bash
# SteamOS / Bazzite — no root, survives OS updates
pipx install steamdeck-bridge   # or: uv tool install steamdeck-bridge
mkdir -p ~/.config/steamdeck-bridge
cp config/config.example.toml ~/.config/steamdeck-bridge/config.toml
$EDITOR ~/.config/steamdeck-bridge/config.toml   # set MQTT broker

mkdir -p ~/.config/systemd/user
cp systemd/steamdeck-bridge.service ~/.config/systemd/user/
systemctl --user enable --now steamdeck-bridge
```

Entities appear in Home Assistant automatically once MQTT connects. Full guide:
[docs/INSTALL.md](docs/INSTALL.md) · [docs/HOME_ASSISTANT.md](docs/HOME_ASSISTANT.md).

## Try it

```bash
curl -H "Authorization: Bearer $TOKEN" http://127.0.0.1:8480/api/state | jq
```

```json
{
  "game": {
    "title": "The Legend of Zelda: Tears of the Kingdom",
    "source": "shortcut", "platform": "Nintendo Switch", "emulator": "ryujinx",
    "shortcut_appid": 2837219845, "started_at": "2026-07-10T18:02:11Z",
    "duration_s": 1843
  },
  "device": { "mode": "gaming", "battery": 76, "docked": true, "steam_user": "brett" }
}
```

## Documentation

| Doc | Contents |
|---|---|
| [docs/RESEARCH.md](docs/RESEARCH.md) | Detection surfaces research (gamescope atoms, VDFs, launchers) |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | Design, security model, go-hass-agent decision |
| [docs/API.md](docs/API.md) | REST / WebSocket / MQTT specification |
| [docs/HOME_ASSISTANT.md](docs/HOME_ASSISTANT.md) | Entities, media player setup, automations |
| [docs/INSTALL.md](docs/INSTALL.md) | Installation on SteamOS / Bazzite / generic Linux |
| [docs/ROADMAP.md](docs/ROADMAP.md) | MVP scope, v0.2/v0.3, stretch goals |

## License

[MIT](LICENSE)
