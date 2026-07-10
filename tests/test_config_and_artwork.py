"""Tests for config loading/overrides/token bootstrap and local artwork lookup."""

from pathlib import Path

from steamdeck_bridge.artwork import find_grid_art, find_librarycache_art
from steamdeck_bridge.config import load_config


def test_config_defaults_and_token_generated(tmp_path: Path):
    path = tmp_path / "config.toml"
    cfg = load_config(path)
    assert cfg.http.port == 8480
    assert cfg.http.token  # generated
    # token persisted for next run
    cfg2 = load_config(path)
    assert cfg2.http.token == cfg.http.token


def test_config_toml_and_env_override(tmp_path: Path, monkeypatch):
    path = tmp_path / "config.toml"
    path.write_text(
        '[device]\nid = "deck9"\n[http]\nport = 9000\ntoken = "abc"\n'
        '[mqtt]\nenabled = false\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("SDB_HTTP_PORT", "9001")
    monkeypatch.setenv("SDB_MQTT_ENABLED", "true")
    cfg = load_config(path)
    assert cfg.device.id == "deck9"
    assert cfg.http.port == 9001          # env beats file
    assert cfg.mqtt.enabled is True       # env beats file
    assert cfg.http.token == "abc"        # not regenerated


def test_find_grid_art_suffix_priority(tmp_path: Path):
    (tmp_path / "123p.png").write_bytes(b"x")
    (tmp_path / "123_hero.jpg").write_bytes(b"x")
    assert find_grid_art(tmp_path, 123, "capsule").name == "123p.png"
    assert find_grid_art(tmp_path, 123, "hero").name == "123_hero.jpg"
    assert find_grid_art(tmp_path, 123, "logo") is None


def test_find_librarycache_art_old_and_new_layout(tmp_path: Path):
    # old flat layout
    (tmp_path / "440_header.jpg").write_bytes(b"x")
    assert find_librarycache_art(tmp_path, 440, "header").name == "440_header.jpg"
    # new nested layout
    nested = tmp_path / "570" / "abcdef"
    nested.mkdir(parents=True)
    (nested / "library_600x900.jpg").write_bytes(b"x")
    hit = find_librarycache_art(tmp_path, 570, "capsule")
    assert hit is not None and hit.name == "library_600x900.jpg"
    assert find_librarycache_art(tmp_path, 999, "hero") is None
