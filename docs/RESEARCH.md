# Research Findings

This document records the research that drives the design of `steamdeck-bridge`.
Every detection mechanism below was evaluated for reliability on current (2025/2026)
SteamOS 3.x and Bazzite images before being assigned a role in the pipeline.

## 1. How to detect the currently running game

### 1.1 Gamescope X11 root-window atoms — **primary source**

Gamescope (the compositor behind Gaming Mode on SteamOS, Bazzite, ChimeraOS, and
`gamescope-session` on HTPCs) maintains X11 properties on the root window of its
nested X server:

| Atom | Meaning |
|---|---|
| `GAMESCOPE_FOCUSED_APP` | AppID of the focused app (used by Proton to decide whether to drop input) |
| `GAMESCOPE_FOCUSED_APP_GFX` | AppID of the app whose surface is displayed |
| `GAMESCOPE_FOCUSED_WINDOW` | X window ID of the focused window |
| `GAMESCOPECTRL_BASELAYER_APPID` | Base layer app stack managed by Steam |

Caveats found in [gamescope issue #416](https://github.com/ValveSoftware/gamescope/issues/416):

- In Steam Gaming Mode the atoms carry real Steam AppIDs (including non-Steam
  shortcut AppIDs, which appear as large 32-bit values with the high bit set).
- When gamescope runs *without* Steam (plain nested gamescope on a desktop), the
  property may carry window IDs instead of AppIDs — the bridge must sanity-check
  values (shortcut AppIDs always have bit 31 set; real Steam AppIDs are known from
  the library index).
- AppID `769` is the Steam overlay/steamui itself and means "no game focused".

The gamescope X display is typically `:0` or `:1` inside the session; the bridge
probes `/tmp/.X11-unix/` and each candidate display for the `GAMESCOPE_FOCUSED_APP`
atom to find the right one.

### 1.2 `reaper SteamLaunch AppId=` process scan — **primary fallback / desktop mode**

Steam launches every game (native, Proton, and non-Steam shortcuts) through its
reaper wrapper:

```
~/.local/share/Steam/ubuntu12_32/reaper SteamLaunch AppId=632470 -- <game cmd>
```

Scanning `/proc/*/cmdline` for `AppId=<n>` reliably yields the running AppID in
**both** Gaming Mode and Desktop Mode, works for Flatpak Steam (inside the
sandbox the process tree is still visible from the host), and gives us the game's
PID → launch timestamp (`/proc/<pid>/stat` field 22) and executable path.

### 1.3 `~/.steam/registry.vdf` `RunningAppID` — **legacy, unreliable**

Historically `HKCU\Software\Valve\Steam\RunningAppID` in `~/.steam/registry.vdf`
tracked the running game. Since the Steam client UI rewrite it is
[stuck at 0](https://github.com/ValveSoftware/steam-for-linux/issues/9672) for many
users. The bridge reads it only as a last-resort hint and never trusts a `0`.

### 1.4 Steam D-Bus / IPC

Steam on Linux exposes **no stable public D-Bus API** for game state. There is an
MPRIS interface for Steam Music only. The `steam://` URL protocol (via
`steam -ifrunning` or `xdg-open`) is the supported *control* channel:

- `steam steam://rungameid/<appid>` — launch a game (for non-Steam shortcuts the
  64-bit id `(shortcut_appid << 32) | 0x02000000` must be used)
- `steam steam://open/library`, `steam://exit`, etc.

Conclusion: **no UI automation is needed** — atoms + process scan for reads,
`steam://` URLs + systemd for writes.

## 2. Steam on-disk data

| File | Contents | Format |
|---|---|---|
| `steamapps/libraryfolders.vdf` | All library mount points | text VDF |
| `steamapps/appmanifest_<appid>.acf` | Installed game name, installdir, state | text VDF |
| `userdata/<uid3>/config/shortcuts.vdf` | Non-Steam shortcuts (name, exe, launch options, appid) | **binary** VDF |
| `userdata/<uid3>/config/localconfig.vdf` | Per-user app config, LastPlayed timestamps | text VDF |
| `config/loginusers.vdf` | Steam accounts, MostRecent flag | text VDF |
| `appcache/librarycache/` | Downloaded artwork per AppID | jpg/png |
| `userdata/<uid3>/config/grid/` | User-overridden artwork (incl. shortcut art from SRM/BoilR) | jpg/png |

Key finding on shortcut AppIDs
([steam-for-linux #9463](https://github.com/ValveSoftware/steam-for-linux/issues/9463)):
modern Steam clients assign a **random** AppID when a shortcut is added via the UI,
so the classic `crc32('"exe"' + appname) | 0x80000000` derivation is only valid for
shortcuts written by third-party tools (Steam ROM Manager, BoilR, EmuDeck). The
bridge therefore **reads** AppIDs from `shortcuts.vdf` and uses the CRC derivation
only to cross-match/verify tool-written entries.

Steam root discovery order (SteamOS and Bazzite are identical here — both put
native Steam in the home directory):

1. `~/.steam/root` symlink (canonical)
2. `~/.local/share/Steam`
3. `~/.var/app/com.valvesoftware.Steam/data/Steam` (Flatpak Steam — the default
   on some Bazzite desktop images and generic distros)

## 3. Third-party launchers

- **Heroic** (Epic/GOG/Amazon): pure GUI over `legendary`/`gogdl`/`nile`. Installed
  game metadata lives in `~/.config/heroic/` (`~/.var/app/com.heroicgameslauncher.hgl/config/heroic/`
  for Flatpak) — `legendary/installed.json`, `gog_store/installed.json`,
  `store_cache/*_library.json` (titles + art URLs). Running games are detected via
  process scan for the runner binaries and matched back to installed.json entries.
- **Lutris**: sqlite DB at `~/.local/share/lutris/pga.db` (`games` table: name,
  slug, runner, directory, playtime). Lutris also exposes `lutris:rungameid/<id>`
  URLs for launching. Running detection via process scan of the game directory.
- **EmuDeck / Steam ROM Manager**: emulator/ROM shortcuts land in `shortcuts.vdf`
  with the emulator as `Exe` and the ROM path in `LaunchOptions`. Platform and ROM
  title are inferred from the canonical EmuDeck layout `Emulation/roms/<platform>/<rom>`;
  a platform map (e.g. `snes` → Super Nintendo) covers the EmuDeck folder set.
- **RetroArch content**: current content readable from its network command
  interface (`GET_STATUS` UDP) when enabled — stretch goal.

## 4. Artwork sources (resolution order)

1. `appcache/librarycache/<appid>_{library_600x900,header,library_hero,logo,icon}.{jpg,png}`
   — present for all installed Steam games ([library assets docs](https://partner.steamgames.com/doc/store/assets/libraryassets))
2. `userdata/<uid3>/config/grid/<appid>{p,_hero,_logo,_icon}.{jpg,png}` — user/tool
   overrides; the **only** local source for non-Steam shortcuts
3. Heroic `store_cache` art URLs / `~/.config/heroic/icons`
4. [SteamGridDB API v2](https://www.steamgriddb.com/api/v2) (optional, needs API
   key): `/search/autocomplete/{term}`, `/grids|heroes|logos|icons/game/{id}`
5. Steam CDN (`https://steamcdn-a.akamaihd.net/steam/apps/<appid>/...`) for
   uninstalled Steam games
6. Local disk cache of everything fetched remotely

## 5. Device / session state

- **Gaming vs Desktop Mode**: a running `gamescope-session`/`steamos-session-select`
  session sets `XDG_CURRENT_DESKTOP=gamescope`; robust runtime check = presence of a
  `gamescope` process owning the atoms above ([Bazzite docs](https://docs.bazzite.gg/Handheld_and_HTPC_edition/Steam_Gaming_Mode/)).
- **Battery**: `/sys/class/power_supply/<BAT>/` (capacity, status). Steam Deck uses
  `BAT1`; Ally/Legion Go differ — enumerate rather than hardcode.
- **Docked / external display**: `/sys/class/drm/card*/status` connected count +
  `/sys/class/power_supply/ACAD|ADP*/online`.
- **Steam login**: `loginusers.vdf` MostRecent + `steam.pid` liveness
  (`/proc/<pid>` exists and comm is steam).
- **Power actions**: `systemctl suspend|poweroff|reboot` (polkit allows the seated
  user on SteamOS/Bazzite without a password).

## 6. Home Assistant transport

- **MQTT Discovery** covers `sensor`, `binary_sensor`, `button`, `switch`,
  `image`, `device_tracker` … but **not `media_player`**
  ([HA feature request](https://community.home-assistant.io/t/mqtt-media-player/191990)).
  The bridge therefore publishes a complete set of discovery-native entities and
  additionally exposes media-player-shaped state/command topics compatible with the
  HACS [`hass-mqtt-mediaplayer`](https://github.com/TroyFernandes/hass-mqtt-mediaplayer)
  integration; `docs/HOME_ASSISTANT.md` ships ready-made YAML.
- Artwork reaches HA two ways: an MQTT `image` discovery entity pointing at the
  bridge's REST artwork URL, and directly via `entity_picture` on the template
  media player.

## 7. go-hass-agent: fork, extend, or stand alone?

[go-hass-agent](https://github.com/joshuar/go-hass-agent) is a mature Go agent for
*generic* desktop telemetry (CPU, memory, media via MPRIS, D-Bus commands). Its
extension points are Go-level (or the sibling
[go-hass-anything](https://github.com/joshuar/go-hass-anything) MQTT framework) and
script-based custom sensors.

Decision — **standalone daemon, friendly coexistence**:

- The Steam/Gamescope domain (binary VDF parsing, X11 atom polling, artwork
  serving, media-player semantics, `steam://` launch control) is a poor fit for
  go-hass-agent's sensor-worker model and far outside its maintainer's stated scope.
- A separate daemon keeps the dependency surface tiny and installable on an
  immutable OS (SteamOS read-only rootfs) without touching the system image.
- go-hass-agent remains the recommended companion for generic system sensors; the
  bridge intentionally does not duplicate CPU/RAM/network telemetry.
- Upstream collaboration path: contribute a "gamescope focused app" sensor to
  go-hass-agent later; the detection module here is written as a dependency-light
  package to make that port easy.

## 8. Decky Loader

Decky plugins run a Python backend inside Gaming Mode with access to the Steam
client's JS API (via the frontend) — the richest possible metadata source
(achievements, cloud state, friends). Rather than *being* a Decky plugin (which
would not run in Desktop Mode or on headless HTPCs), the bridge is a systemd user
service, and a thin optional Decky plugin can later push SteamClient-JS-only data
into the bridge's REST API. See `docs/ROADMAP.md` stretch goals.

## Sources

- [gamescope issue #416 — GAMESCOPE_FOCUSED_APP behavior](https://github.com/ValveSoftware/gamescope/issues/416)
- [steam-for-linux #9672 — RunningAppID no longer set](https://github.com/ValveSoftware/steam-for-linux/issues/9672)
- [steam-for-linux #9463 — shortcut AppID no longer predictable](https://github.com/ValveSoftware/steam-for-linux/issues/9463)
- [Steam Shortcuts documentation (shortcuts.vdf format)](https://github.com/CorporalQuesadilla/Steam-Shortcut-Manager/wiki/Steam-Shortcuts-Documentation)
- [Steamworks library assets](https://partner.steamgames.com/doc/store/assets/libraryassets)
- [SteamGridDB API](https://www.steamgriddb.com/api/v2)
- [go-hass-agent](https://github.com/joshuar/go-hass-agent) / [go-hass-anything](https://github.com/joshuar/go-hass-anything)
- [hass-mqtt-mediaplayer (HACS)](https://github.com/TroyFernandes/hass-mqtt-mediaplayer)
- [HA community — MQTT media player status](https://community.home-assistant.io/t/mqtt-media-player/191990)
- [Bazzite Gaming Mode docs](https://docs.bazzite.gg/Handheld_and_HTPC_edition/Steam_Gaming_Mode/)
- [Decky plugin template](https://github.com/SteamDeckHomebrew/decky-plugin-template) / [Deckbrew wiki](https://wiki.deckbrew.xyz/plugin-dev/getting-started)
- [Heroic FAQ (config/log locations)](https://heroicgameslauncher.com/faq)
