# Architecture

`steamdeck-bridge` is a single-process asyncio Python daemon running as a
**user-level systemd service** on SteamOS, Bazzite, or any Linux gaming device.

```
                 ┌────────────────────────────────────────────────┐
                 │                steamdeck-bridge                │
                 │                                                │
 gamescope ─X11──▶ detect/gamescope ─┐                            │
 /proc     ──────▶ detect/steam_proc ┤                            │
 registry.vdf ───▶ detect/registry   ├─▶ DetectionPipeline ─┐     │
 heroic cfg ─────▶ detect/heroic     │                      │     │
 lutris db ──────▶ detect/lutris    ─┘                      ▼     │
                 │                                    StateStore  │
 steam files ────▶ steam/ (library, shortcuts) ──▶ enrichment │   │
 /sys ───────────▶ system.py (battery, dock, mode) ───────────┤   │
                 │                                            │   │
                 │          ┌─────────────┬───────────────────┤   │
                 │          ▼             ▼                   ▼   │
                 │      REST API     WebSocket /ws        MQTT    │
                 │      (aiohttp)    (state stream)   (discovery, │
                 │          │             │            state,     │
                 └──────────┼─────────────┼────────────commands)──┘
                            ▼             ▼                ▼
                       curl / apps   dashboards      Home Assistant
```

## Core loop

`daemon.py` runs a poll cycle (default 2 s, configurable):

1. Run the **detection pipeline** — ordered detectors, first confident answer wins:
   1. `GamescopeDetector` — `GAMESCOPE_FOCUSED_APP` root atom (Gaming Mode)
   2. `SteamProcessDetector` — `/proc` scan for `reaper SteamLaunch AppId=N`
   3. `HeroicDetector` / `LutrisDetector` — runner process scans
   4. `RegistryDetector` — `registry.vdf` `RunningAppID` (legacy hint only)
2. **Enrich** the raw AppID/PID into a `GameSession`:
   - Steam AppID → `appmanifest_*.acf` (title, installdir)
   - Shortcut AppID → `shortcuts.vdf` entry (title, exe, launch options) →
     EmuDeck ROM/platform inference → SRM/Heroic/Lutris attribution
   - launch timestamp from `/proc/<pid>` or first-seen time; session duration derived
3. Read **device state** (battery, docked, session mode, steam login, awake).
4. Diff against `StateStore`; on change fan out to WebSocket clients and MQTT.

Everything is event-diffed: MQTT/WS traffic only flows on change plus a periodic
keepalive, so the daemon is idle-cheap on battery.

## Modules

| Module | Responsibility |
|---|---|
| `config.py` | TOML config + env overrides, token management |
| `models.py` | `GameSession`, `DeviceState`, `BridgeState` dataclasses (JSON-serializable) |
| `steam/paths.py` | Locate Steam root (native/Flatpak), userdata, libraries |
| `steam/library.py` | `libraryfolders.vdf`, `appmanifest_*.acf` index |
| `steam/shortcuts.py` | Binary `shortcuts.vdf` parser, legacy CRC AppID, EmuDeck inference |
| `detect/*` | Detector implementations (see above) |
| `system.py` | Battery/dock/mode sensors; suspend/shutdown/launch/close actions |
| `artwork.py` | Resolution chain + disk cache + SteamGridDB client |
| `api/rest.py` | aiohttp REST + WebSocket, bearer-token auth |
| `mqtt.py` | HA MQTT discovery, state publishing, command subscription |
| `daemon.py` | Orchestrator, poll loop, lifecycle |

## Security model

- **Local-only by default**: binds `127.0.0.1`; the user opts into LAN exposure.
- **Bearer token** (generated on first run into the config file) required on all
  REST/WS endpoints except `/api/health`. Artwork URLs accept the token as a query
  parameter so HA can embed them.
- **TLS** is delegated to a reverse proxy (caddy/nginx/traefik); documented, not
  implemented — a game device should not manage certificates.
- MQTT credentials live in the config file with `0600` perms.
- Power/launch commands only ever execute a fixed allowlist (no arbitrary shell
  from MQTT/REST).

## Why Python (and not a go-hass-agent fork)

See `docs/RESEARCH.md` §7. Summary: the domain logic (binary VDF, X11 atoms,
artwork proxying, media-player semantics) doesn't fit go-hass-agent's worker
model; a standalone daemon with three pure-Python runtime deps (`aiohttp`,
`aiomqtt`, `vdf`) installs cleanly on an immutable OS via `pipx`/`uv tool` without
layering packages, and coexists with go-hass-agent for generic telemetry.

## Testing strategy

- **Unit tests (CI, any OS)** cover everything with pure inputs: binary/text VDF
  parsing, shortcut CRC derivation, ROM/platform inference, config
  loading/overrides, artwork path resolution, discovery payload shape (including
  the "no game" template guard). `tests/` runs on Windows/macOS/Linux — all
  Linux-only surfaces (`/proc`, `/sys`, X11) are behind functions that take
  injectable paths or degrade to `None`.
- **Smoke test**: the daemon boots on a Steam-less machine, serves
  `/api/health`, enforces auth, and idles cleanly — exercised manually and easy
  to script in CI.
- **On-device validation** (release checklist): gamescope atom detection in
  Gaming Mode, reaper scan in Desktop Mode, an EmuDeck shortcut resolving to
  ROM title + platform, HA discovery on a live broker, suspend/launch actions.
- CI (GitHub Actions) runs lint (ruff) + pytest on Python 3.11–3.13 and builds
  the wheel.

## Multi-device

Each device runs its own bridge with a distinct `device_id`; MQTT discovery
namespaces every entity under that device. A Home Assistant instance therefore
aggregates any number of Decks/Allys/HTPCs with zero extra configuration.
