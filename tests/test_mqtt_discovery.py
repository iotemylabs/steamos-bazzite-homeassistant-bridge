"""Tests for the HA MQTT discovery payloads and topic layout."""

import json

from steamdeck_bridge.config import Config
from steamdeck_bridge.mqtt import build_discovery, topics


def make_config() -> Config:
    cfg = Config()
    cfg.device.id = "deck1"
    cfg.device.name = "Living Room Deck"
    return cfg


def test_topic_layout():
    t = topics(make_config())
    assert t["state"] == "steamdeck_bridge/deck1/state"
    assert t["availability"] == "steamdeck_bridge/deck1/availability"
    assert t["command"] == "steamdeck_bridge/deck1/command"


def test_discovery_unique_ids_and_device_block():
    entities = build_discovery(make_config())
    unique_ids = [payload["unique_id"] for _, payload in entities]
    assert len(unique_ids) == len(set(unique_ids)), "unique_ids must be unique"
    for topic, payload in entities:
        assert topic.startswith("homeassistant/")
        assert topic.endswith("/config")
        assert payload["availability_topic"] == "steamdeck_bridge/deck1/availability"
        assert payload["device"]["name"] == "Living Room Deck"


def test_discovery_covers_required_sensors():
    entities = build_discovery(make_config())
    object_ids = {payload["unique_id"].removeprefix("sdb_deck1_") for _, payload in entities}
    required = {
        "current_game", "steam_appid", "shortcut_appid", "platform", "emulator",
        "session_mode", "battery", "docked", "in_game", "non_steam_game",
        "steam_running", "steam_user", "session_duration",
    }
    assert required <= object_ids, f"missing: {required - object_ids}"


def test_buttons_publish_json_actions():
    entities = build_discovery(make_config())
    buttons = [p for t, p in entities if "/button/" in t]
    assert buttons, "no buttons discovered"
    for payload in buttons:
        assert payload["command_topic"] == "steamdeck_bridge/deck1/command"
        action = json.loads(payload["payload_press"])["action"]
        assert action in {
            "suspend", "shutdown", "reboot", "restart_steam",
            "close_game", "refresh_library",
        }


def test_templates_handle_no_game():
    """value_templates must not blow up when game is null — they all guard
    with `if value_json.game`."""
    entities = build_discovery(make_config())
    for _, payload in entities:
        template = payload.get("value_template", "")
        if "value_json.game." in template:
            assert "if value_json.game" in template, template
