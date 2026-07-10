"""MQTT publishing + Home Assistant discovery.

Topic layout (base = config.mqtt.base_topic, id = config.device.id):
  <base>/<id>/availability      online | offline   (LWT)
  <base>/<id>/state             full BridgeState JSON (retained)
  <base>/<id>/command           JSON commands: {"action": "...", "appid": 123}

Discovery: one JSON state topic; every entity extracts its value with a
value_template, so state publishing stays a single retained message.
`media_player` is not supported by HA MQTT discovery — the state topic doubles
as the source for the documented template/HACS media player (docs/HOME_ASSISTANT.md).
"""

from __future__ import annotations

import asyncio
import json
import logging

import aiomqtt

from . import __version__
from .config import Config

log = logging.getLogger(__name__)


def topics(config: Config) -> dict[str, str]:
    base = f"{config.mqtt.base_topic}/{config.device.id}"
    return {
        "availability": f"{base}/availability",
        "state": f"{base}/state",
        "command": f"{base}/command",
    }


def _device_block(config: Config) -> dict:
    return {
        "identifiers": [f"steamdeck_bridge_{config.device.id}"],
        "name": config.device.name,
        "manufacturer": "steamdeck-bridge",
        "model": "SteamOS/Bazzite bridge",
        "sw_version": __version__,
    }


def build_discovery(config: Config) -> list[tuple[str, dict]]:
    """(topic, payload) pairs for every discovered entity."""
    t = topics(config)
    dev = _device_block(config)
    prefix = config.mqtt.discovery_prefix
    uid = f"sdb_{config.device.id}"

    def entity(component: str, object_id: str, extra: dict) -> tuple[str, dict]:
        payload = {
            "unique_id": f"{uid}_{object_id}",
            "object_id": f"{config.device.id}_{object_id}",
            "device": dev,
            "availability_topic": t["availability"],
            "state_topic": t["state"],
            **extra,
        }
        return (f"{prefix}/{component}/{uid}/{object_id}/config", payload)

    entities = [
        entity("sensor", "current_game", {
            "name": "Current game",
            "icon": "mdi:gamepad-variant",
            "value_template": "{{ value_json.game.title if value_json.game else 'None' }}",
            "json_attributes_topic": t["state"],
            "json_attributes_template": "{{ (value_json.game or {}) | tojson }}",
        }),
        entity("sensor", "steam_appid", {
            "name": "Steam AppID",
            "icon": "mdi:steam",
            "value_template": "{{ value_json.game.appid if value_json.game else 'none' }}",
        }),
        entity("sensor", "shortcut_appid", {
            "name": "Shortcut AppID",
            "icon": "mdi:identifier",
            "value_template":
                "{{ value_json.game.shortcut_appid if value_json.game else 'none' }}",
        }),
        entity("sensor", "platform", {
            "name": "Platform",
            "icon": "mdi:controller-classic",
            "value_template": "{{ value_json.game.platform if value_json.game else 'none' }}",
        }),
        entity("sensor", "emulator", {
            "name": "Emulator",
            "icon": "mdi:nintendo-game-boy",
            "value_template": "{{ value_json.game.emulator if value_json.game else 'none' }}",
        }),
        entity("sensor", "game_source", {
            "name": "Game source",
            "icon": "mdi:source-branch",
            "value_template": "{{ value_json.game.source if value_json.game else 'none' }}",
        }),
        entity("sensor", "session_duration", {
            "name": "Session duration",
            "icon": "mdi:timer-outline",
            "unit_of_measurement": "s",
            "state_class": "measurement",
            "value_template": "{{ value_json.game.duration_s if value_json.game else 0 }}",
        }),
        entity("sensor", "session_mode", {
            "name": "Session mode",
            "icon": "mdi:steam",
            "value_template": "{{ value_json.device.mode }}",
        }),
        entity("sensor", "battery", {
            "name": "Battery",
            "device_class": "battery",
            "unit_of_measurement": "%",
            "state_class": "measurement",
            "value_template": "{{ value_json.device.battery_percent }}",
        }),
        entity("sensor", "steam_user", {
            "name": "Steam user",
            "icon": "mdi:account",
            "value_template": "{{ value_json.device.steam_user or 'none' }}",
        }),
        entity("binary_sensor", "in_game", {
            "name": "In game",
            "device_class": "running",
            "payload_on": "on", "payload_off": "off",
            "value_template": "{{ 'on' if value_json.game else 'off' }}",
        }),
        entity("binary_sensor", "non_steam_game", {
            "name": "Non-Steam game",
            "payload_on": "on", "payload_off": "off",
            "value_template":
                "{{ 'on' if value_json.game and value_json.game.source != 'steam' "
                "else 'off' }}",
        }),
        entity("binary_sensor", "steam_running", {
            "name": "Steam running",
            "device_class": "running",
            "payload_on": "on", "payload_off": "off",
            "value_template": "{{ 'on' if value_json.device.steam_running else 'off' }}",
        }),
        entity("binary_sensor", "docked", {
            "name": "Docked",
            "device_class": "plug",
            "payload_on": "on", "payload_off": "off",
            "value_template": "{{ 'on' if value_json.device.docked else 'off' }}",
        }),
        entity("binary_sensor", "on_ac", {
            "name": "On AC power",
            "device_class": "power",
            "payload_on": "on", "payload_off": "off",
            "value_template": "{{ 'on' if value_json.device.on_ac else 'off' }}",
        }),
    ]

    for action, (name, icon) in {
        "suspend": ("Suspend", "mdi:power-sleep"),
        "shutdown": ("Shutdown", "mdi:power"),
        "reboot": ("Reboot", "mdi:restart"),
        "restart_steam": ("Restart Steam", "mdi:steam"),
        "close_game": ("Close game", "mdi:close-circle"),
        "refresh_library": ("Refresh library", "mdi:refresh"),
    }.items():
        entities.append(entity("button", action, {
            "name": name,
            "icon": icon,
            "command_topic": t["command"],
            "payload_press": json.dumps({"action": action}),
        }))

    return entities


class MqttBridge:
    """Owns the MQTT connection: discovery, retained state, command intake."""

    def __init__(self, config: Config, on_command):
        self.config = config
        self.on_command = on_command  # async callable(action: str, params: dict)
        self.topics = topics(config)
        self._state_json = "{}"
        self._dirty = asyncio.Event()

    def publish_state(self, state_dict: dict) -> None:
        self._state_json = json.dumps(state_dict)
        self._dirty.set()

    async def run(self) -> None:
        """Reconnect-forever MQTT loop."""
        mq = self.config.mqtt
        will = aiomqtt.Will(self.topics["availability"], "offline", retain=True)
        while True:
            try:
                async with aiomqtt.Client(
                    hostname=mq.host,
                    port=mq.port,
                    username=mq.username or None,
                    password=mq.password or None,
                    will=will,
                    identifier=f"steamdeck-bridge-{self.config.device.id}",
                ) as client:
                    log.info("MQTT connected to %s:%s", mq.host, mq.port)
                    for topic, payload in build_discovery(self.config):
                        await client.publish(topic, json.dumps(payload), retain=True)
                    await client.publish(self.topics["availability"], "online", retain=True)
                    await client.publish(self.topics["state"], self._state_json, retain=True)
                    await client.subscribe(self.topics["command"])

                    publisher = asyncio.create_task(self._publish_loop(client))
                    try:
                        async for message in client.messages:
                            await self._handle_command(message)
                    finally:
                        publisher.cancel()
            except aiomqtt.MqttError as e:
                log.warning("MQTT connection lost (%s); retrying in 10s", e)
                await asyncio.sleep(10)

    async def _publish_loop(self, client: aiomqtt.Client) -> None:
        while True:
            await self._dirty.wait()
            self._dirty.clear()
            await client.publish(self.topics["state"], self._state_json, retain=True)

    async def _handle_command(self, message) -> None:
        try:
            payload = json.loads(message.payload)
            action = payload["action"]
        except (json.JSONDecodeError, KeyError, TypeError):
            log.warning("ignoring malformed MQTT command: %r", message.payload)
            return
        params = {k: v for k, v in payload.items() if k != "action"}
        await self.on_command(action, params)
