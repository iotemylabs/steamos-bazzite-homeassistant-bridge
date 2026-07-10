# Roadmap

## MVP — v0.1 (this repository)

- [x] Steam root discovery (native + Flatpak), library & shortcuts indexing
- [x] Current-game detection: gamescope atoms → reaper process scan → Heroic →
      Lutris → registry fallback
- [x] Session enrichment: title, platform, exe, launch options, ROM/platform
      inference for EmuDeck shortcuts, launch time + duration
- [x] Device sensors: battery, docked, gaming/desktop mode, steam login, awake
- [x] REST API + WebSocket state stream, bearer-token auth, local-only default
- [x] Artwork resolver (librarycache → grid → Heroic → SteamGridDB → CDN) with cache
- [x] MQTT + HA discovery: sensors, binary sensors, action buttons, availability
- [x] Media-player-shaped MQTT topics + documented HACS/template YAML
- [x] systemd user unit, TOML config, MIT license, CI, tests for all parsers

## v0.2 — polish

- [ ] File watching (inotify) instead of polling for VDF/log changes
- [ ] `refresh_library` / `refresh_metadata` incremental cache invalidation
- [ ] Steam login/user-switch events from `loginusers.vdf` watch
- [ ] Playtime accumulation persisted across restarts; per-game statistics sensor
- [ ] Packaging: Copr/AUR/ujust recipe for Bazzite, one-line installer for SteamOS

## v0.3 — deeper integration

- [ ] Optional Decky Loader companion plugin pushing SteamClient JS data
      (achievements, download progress, friends presence) into the bridge REST API
- [ ] RetroArch network-command interface for in-emulator content titles
- [ ] Heroic/Lutris launch actions (`heroic://launch/...`, `lutris:rungameid/...`)
- [ ] HA custom integration (HACS) providing a native `media_player` +
      config-flow, replacing the template YAML
- [ ] Wayland-native gamescope state (as gamescope migrates off X11 atoms)

## Stretch

- [ ] Fleet dashboard artifact (multi-device Lovelace blueprint)
- [ ] go-hass-agent upstream contribution: gamescope focused-app sensor
- [ ] Suspend-aware session accounting (pause duration while asleep)
- [ ] Controller battery via hidraw/UPower
