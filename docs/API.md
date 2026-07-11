# API Specification

Base URL: `http://<device>:8480` (default; local-only unless configured otherwise).

## Authentication

All endpoints except `GET /api/health` require the bearer token from
`~/.config/steamdeck-bridge/config.toml` (`[http] token`, generated on first run):

```
Authorization: Bearer <token>
```

or, for contexts that can't set headers (HA `picture-entity`, `<img>` tags):

```
?token=<token>
```

## REST

### `GET /api/health` (no auth)

```json
{ "ok": true, "version": "0.1.0" }
```

### `GET /api/state`

Current game + device state. `game` is `null` when idle.

```json
{
  "game": {
    "source": "shortcut",            // steam | shortcut | heroic | lutris | unknown
    "appid": null,                    // Steam AppID when source == steam
    "shortcut_appid": 2593523916,     // non-Steam shortcut AppID
    "title": "Super Mario World",     // display title (ROM title when available)
    "steam_title": "Super Mario World",
    "rom_title": "Super Mario World",
    "platform": "Super Nintendo",
    "emulator": "RetroArch",
    "is_emulator": true,
    "is_srm_shortcut": true,          // AppID matches the SRM/BoilR CRC derivation
    "exe": "/usr/bin/retroarch",
    "launch_command": "-L snes9x.so \"/home/deck/Emulation/roms/snes/....sfc\"",
    "pid": 12345,
    "started_at": 1783221731.4,
    "duration_s": 1843
  },
  "device": {
    "mode": "gaming",                 // gaming | desktop | unknown
    "awake": true,
    "battery_percent": 76,
    "battery_state": "discharging",
    "on_ac": false,
    "docked": false,
    "steam_running": true,
    "steam_user": "Brett"
  }
}
```

### `GET /api/library`

Installed Steam apps and non-Steam shortcuts.

```json
{
  "steam":     [ { "appid": 632470, "name": "Disco Elysium", "installdir": "Disco Elysium" } ],
  "shortcuts": [ { "appid": 2593523916, "name": "Super Mario World", "exe": "/usr/bin/retroarch",
                   "emulator": "RetroArch", "platform": "Super Nintendo",
                   "rom_title": "Super Mario World", "rungameid": 11139150900937490432 } ]
}
```

### `GET /api/artwork/{appid}/{kind}`

Returns the image (`image/jpeg` / `image/png`), 404 if unresolvable.
`kind` ∈ `capsule` (600×900 vertical), `cover` (alias), `header` (460×215),
`hero`, `logo`, `icon`, `background`.

Optional `?title=` overrides the title used for SteamGridDB lookups.

### `POST /api/actions/{action}`

| Action | Body | Notes |
|---|---|---|
| `launch_game` | `{"appid": 632470}` | Shortcut AppIDs handled automatically via rungameid |
| `switch_game` | `{"appid": 632470}` | Closes current game first |
| `close_game` | — | SIGTERM to the current game's process group |
| `restart_steam` | — | `steam://exit`, then relaunch |
| `restart_gamescope` | — | Equivalent to restart_steam inside a gamescope session |
| `suspend` / `shutdown` / `reboot` | — | via `systemctl` |
| `wake` | — | accepted no-op: use Wake-on-LAN from HA (see HOME_ASSISTANT.md) |
| `refresh_library` / `refresh_metadata` | — | re-index VDFs, Heroic, Lutris |

Response: `{"action": "...", "ok": true}` (HTTP 409 when disabled by config/unavailable).

## WebSocket — `GET /ws`

Token required (header or `?token=`). Server messages:

```json
{ "type": "state", "data": { ...same shape as /api/state... } }
```

- One snapshot on connect, then a message per state change, plus a keepalive
  snapshot at least every 30 s (duration_s ticks along with it).
- Client may send the literal text `ping`; server answers `pong`.

## MQTT

Topics (defaults: `base_topic = steamdeck_bridge`, `id = steamdeck`):

| Topic | Dir | Payload |
|---|---|---|
| `steamdeck_bridge/<id>/availability` | out, retained | `online` / `offline` (LWT) |
| `steamdeck_bridge/<id>/state` | out, retained | full state JSON (same as `/api/state`) |
| `steamdeck_bridge/<id>/command` | in | `{"action": "launch_game", "appid": 632470}` — same actions as REST |

Home Assistant discovery configs are published retained under
`homeassistant/{sensor,binary_sensor,button}/sdb_<id>/*/config`. See
[HOME_ASSISTANT.md](HOME_ASSISTANT.md) for the entity list and media player setup.
