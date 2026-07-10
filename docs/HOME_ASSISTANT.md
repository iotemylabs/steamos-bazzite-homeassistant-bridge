# Home Assistant Integration

With MQTT enabled, entities appear automatically under a device named after
`[device] name` as soon as the bridge connects to your broker.

## Discovered entities

| Entity | Type | Notes |
|---|---|---|
| `sensor.<id>_current_game` | sensor | Title; all game fields as attributes |
| `sensor.<id>_steam_appid` | sensor | |
| `sensor.<id>_shortcut_appid` | sensor | |
| `sensor.<id>_platform` | sensor | Steam / Nintendo Switch / GOG / … |
| `sensor.<id>_emulator` | sensor | retroarch, ryujinx, … |
| `sensor.<id>_game_source` | sensor | steam / shortcut / heroic / lutris |
| `sensor.<id>_session_duration` | sensor | seconds |
| `sensor.<id>_session_mode` | sensor | gaming / desktop / unknown |
| `sensor.<id>_battery` | sensor | device_class battery |
| `sensor.<id>_steam_user` | sensor | persona name |
| `binary_sensor.<id>_in_game` | binary_sensor | |
| `binary_sensor.<id>_non_steam_game` | binary_sensor | |
| `binary_sensor.<id>_steam_running` | binary_sensor | |
| `binary_sensor.<id>_docked` | binary_sensor | |
| `binary_sensor.<id>_on_ac` | binary_sensor | |
| `button.<id>_suspend` … | button | suspend, shutdown, reboot, restart_steam, close_game, refresh_library |

Online/offline state (device availability) tracks the MQTT LWT — a suspended
or powered-off device shows all entities as unavailable, which doubles as the
"awake" signal.

## Launching games from HA

Publish to the command topic (e.g. in a script/automation):

```yaml
service: mqtt.publish
data:
  topic: steamdeck_bridge/steamdeck/command
  payload: '{"action": "launch_game", "appid": 632470}'
```

`GET /api/library` lists every launchable AppID, including shortcut AppIDs for
EmuDeck/SRM entries.

## Media player entity

HA's MQTT integration has no native `media_player` platform, so pick one:

### Option A — HACS `mqtt-media-player` (recommended)

Install [TroyFernandes/hass-mqtt-mediaplayer](https://github.com/TroyFernandes/hass-mqtt-mediaplayer)
via HACS, then:

```yaml
media_player:
  - platform: mqtt-media-player
    name: "Steam Deck"
    topic:
      song_title:
        topic: "steamdeck_bridge/steamdeck/state"
        value_template: "{{ value_json.game.title if value_json.game else 'Idle' }}"
      song_artist:
        topic: "steamdeck_bridge/steamdeck/state"
        value_template: "{{ value_json.game.platform if value_json.game else '' }}"
      player_status:
        topic: "steamdeck_bridge/steamdeck/state"
        value_template: "{{ 'playing' if value_json.game else 'idle' }}"
      album_art:
        topic: "steamdeck_bridge/steamdeck/state"
        # served by the bridge; use a URL HA can reach + the bridge token
        value_template: >-
          {% if value_json.game %}
          http://STEAMDECK_IP:8480/api/artwork/{{ value_json.game.appid or value_json.game.shortcut_appid }}/capsule?token=YOUR_TOKEN
          {% endif %}
    power_off:
      service: mqtt.publish
      data:
        topic: "steamdeck_bridge/steamdeck/command"
        payload: '{"action": "suspend"}'
```

### Option B — template media player (no HACS)

Use a [universal media player](https://www.home-assistant.io/integrations/universal/)
fed by the discovered sensors, with `entity_picture` pointing at the artwork URL
above. Fine for dashboards, fewer controls.

> For either option the bridge must listen beyond localhost:
> set `[http] host = "0.0.0.0"` (token still required), or keep it local-only
> and put caddy/nginx in front for TLS — see INSTALL.md.

## Wake from suspend

A suspended daemon can't wake itself; use HA's
[`wake_on_lan`](https://www.home-assistant.io/integrations/wake_on_lan/) integration.
The Steam Deck's dock and most Bazzite HTPCs support WoL:

```yaml
switch:
  - platform: wake_on_lan
    mac: "AA:BB:CC:DD:EE:FF"
    name: "Steam Deck Wake"
```

Pair it with `button.<id>_suspend` for full sleep/wake control.

## Example automation

```yaml
automation:
  - alias: "Dim lights when a game starts on the living-room Deck"
    trigger:
      - platform: state
        entity_id: binary_sensor.steamdeck_in_game
        to: "on"
    condition:
      - condition: state
        entity_id: binary_sensor.steamdeck_docked
        state: "on"
    action:
      - service: light.turn_on
        target: { entity_id: light.living_room }
        data: { brightness_pct: 15 }
```
