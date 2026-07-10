"""Tests for detection-pipeline enrichment (pure logic, no Linux needed)."""

from pathlib import Path

from steamdeck_bridge.detect import DetectionPipeline
from steamdeck_bridge.models import GameSource
from steamdeck_bridge.steam.library import InstalledApp, SteamLibrary
from steamdeck_bridge.steam.shortcuts import Shortcut, ShortcutIndex


def make_pipeline(tmp_path: Path) -> DetectionPipeline:
    library = SteamLibrary(tmp_path)
    library.apps = {632470: InstalledApp(632470, "Disco Elysium", "Disco Elysium", "")}
    shortcuts = ShortcutIndex(tmp_path)
    sc = Shortcut(
        appid=0x9ABCDEF0,
        app_name="Super Mario World",
        exe="/usr/bin/retroarch",
        launch_options='-L snes9x.so "/home/deck/Emulation/roms/snes/Super Mario World (USA).sfc"',
    )
    sc.emulator = "retroarch"
    sc.rom_title = "Super Mario World"
    sc.platform = "Super Nintendo"
    shortcuts.shortcuts = {sc.appid: sc}
    return DetectionPipeline(library, shortcuts, home=tmp_path)


def test_enrich_steam_appid(tmp_path: Path):
    p = make_pipeline(tmp_path)
    session = p._enrich_steam_appid(632470, "test")
    assert session.source == GameSource.STEAM
    assert session.appid == 632470
    assert session.title == "Disco Elysium"
    assert session.platform == "Steam"
    assert session.duration_s >= 0


def test_enrich_known_shortcut_prefers_rom_title(tmp_path: Path):
    p = make_pipeline(tmp_path)
    session = p._enrich_steam_appid(0x9ABCDEF0, "test")
    assert session.source == GameSource.SHORTCUT
    assert session.shortcut_appid == 0x9ABCDEF0
    assert session.title == "Super Mario World"
    assert session.emulator == "retroarch"
    assert session.is_emulator
    assert session.platform == "Super Nintendo"


def test_enrich_unknown_shortcut_appid(tmp_path: Path):
    p = make_pipeline(tmp_path)
    session = p._enrich_steam_appid(0x80000001, "test")
    assert session.source == GameSource.SHORTCUT
    assert session.platform == "Non-Steam"


def test_enrich_unknown_steam_appid(tmp_path: Path):
    p = make_pipeline(tmp_path)
    session = p._enrich_steam_appid(999999, "test")
    assert session.source == GameSource.STEAM
    assert "999999" in session.title


def test_state_serialization_round_trip(tmp_path: Path):
    import json

    p = make_pipeline(tmp_path)
    session = p._enrich_steam_appid(632470, "test")
    payload = json.dumps(session.to_dict())
    assert "Disco Elysium" in payload
