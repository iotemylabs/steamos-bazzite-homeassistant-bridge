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
    sc.emulator = "RetroArch"
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
    assert session.title == "Super Mario World"  # shortcut AppName, not filename
    assert session.emulator == "RetroArch"
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


def test_steamui_focus_falls_back_to_process_scan(tmp_path: Path, monkeypatch):
    """Steam home menu (gamescope reports steamui) must not drop the running
    game while its reaper process is still alive."""
    from steamdeck_bridge.detect.steam_process import RunningApp

    p = make_pipeline(tmp_path)
    monkeypatch.setattr(p.gamescope, "focused_appid", lambda: 0)
    monkeypatch.setattr(
        p.process, "running",
        lambda: RunningApp(appid=632470, pid=4242, started_at=1000.0),
    )
    session = p.detect()
    assert session is not None
    assert session.title == "Disco Elysium"
    assert session.pid == 4242


def test_steamui_focus_with_no_game_reports_idle(tmp_path: Path, monkeypatch):
    p = make_pipeline(tmp_path)
    monkeypatch.setattr(p.gamescope, "focused_appid", lambda: 0)
    monkeypatch.setattr(p.process, "running", lambda: None)
    monkeypatch.setattr(p.heroic, "running", lambda: None)
    monkeypatch.setattr(p.lutris, "running", lambda: None)
    monkeypatch.setattr(p.registry, "running_appid", lambda: None)
    assert p.detect() is None


def test_child_pids_parsing(tmp_path: Path):
    from steamdeck_bridge.system import child_pids

    task = tmp_path / "4242" / "task" / "4242"
    task.mkdir(parents=True)
    (task / "children").write_text("5001 5002 ", encoding="ascii")
    assert child_pids(4242, proc=tmp_path) == [5001, 5002]
    assert child_pids(9999, proc=tmp_path) == []


def test_state_serialization_round_trip(tmp_path: Path):
    import json

    p = make_pipeline(tmp_path)
    session = p._enrich_steam_appid(632470, "test")
    payload = json.dumps(session.to_dict())
    assert "Disco Elysium" in payload
