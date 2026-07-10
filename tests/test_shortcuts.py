"""Tests for binary shortcuts.vdf parsing, legacy CRC AppIDs, ROM inference."""

import vdf

from steamdeck_bridge.steam.shortcuts import (
    Shortcut,
    infer_rom,
    legacy_shortcut_appid,
    parse_shortcuts,
)


def make_blob(entries: list[dict]) -> bytes:
    return vdf.binary_dumps({"shortcuts": {str(i): e for i, e in enumerate(entries)}})


def test_parse_basic_shortcut():
    blob = make_blob([{
        "appid": -1573254212,  # stored signed by Steam
        "AppName": "Heroic",
        "Exe": '"/usr/bin/heroic"',
        "StartDir": '"/usr/bin/"',
        "LaunchOptions": "",
        "icon": "",
    }])
    shortcuts = parse_shortcuts(blob)
    assert len(shortcuts) == 1
    sc = shortcuts[0]
    assert sc.app_name == "Heroic"
    assert sc.exe == "/usr/bin/heroic"
    assert sc.appid == (-1573254212) & 0xFFFFFFFF
    assert sc.appid & 0x80000000  # shortcut AppIDs have the high bit set


def test_legacy_crc_appid_high_bit_and_determinism():
    a = legacy_shortcut_appid("/usr/bin/emu", "My Game")
    b = legacy_shortcut_appid("/usr/bin/emu", "My Game")
    assert a == b
    assert a & 0x80000000
    assert a != legacy_shortcut_appid("/usr/bin/emu", "Other Game")


def test_srm_style_detection():
    exe = "/usr/bin/retroarch"
    name = "Super Mario World"
    appid = legacy_shortcut_appid(exe, name)
    blob = make_blob([{
        "appid": appid if appid < 0x80000000 else appid - 0x100000000,  # to signed
        "AppName": name,
        "Exe": f'"{exe}"',
        "LaunchOptions": '-L cores/snes9x_libretro.so '
                         '"/home/deck/Emulation/roms/snes/Super Mario World (USA).sfc"',
    }])
    sc = parse_shortcuts(blob)[0]
    assert sc.is_srm_style
    assert sc.emulator == "retroarch"
    assert sc.platform == "Super Nintendo"
    assert sc.rom_title == "Super Mario World"


def test_rungameid_encoding():
    sc = Shortcut(appid=0xE1B2C3D4, app_name="x", exe="/bin/true")
    assert sc.rungameid == (0xE1B2C3D4 << 32) | 0x02000000


def test_infer_rom_emudeck_layout():
    path, title, platform = infer_rom(
        '"/run/media/mmcblk0p1/Emulation/roms/switch/Zelda TOTK [01007EF00011E000].nsp"',
        "/usr/bin/ryujinx",
    )
    assert path.endswith(".nsp")
    assert title == "Zelda TOTK"
    assert platform == "Nintendo Switch"


def test_infer_rom_unknown_platform_folder_passes_through():
    _, _, platform = infer_rom('"/data/roms/quest2/game.zip"', "/usr/bin/emu")
    assert platform == "quest2"


def test_infer_rom_none_when_no_rom_argument():
    assert infer_rom("--fullscreen", "/usr/bin/heroic") == ("", "", "")


def test_missing_appid_falls_back_to_crc():
    blob = make_blob([{
        "AppName": "Old Tool Shortcut",
        "Exe": '"/opt/emu"',
    }])
    sc = parse_shortcuts(blob)[0]
    assert sc.appid == legacy_shortcut_appid("/opt/emu", "Old Tool Shortcut")


def test_garbage_blob_returns_empty():
    assert parse_shortcuts(b"\x00not a vdf") == []
