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
    assert sc.emulator == "RetroArch"
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


# --- regression tests from on-device reports (EmuDeck launch styles) ---------


def shortcut_for(exe: str, options: str, name: str = "Game"):
    blob = make_blob([{
        "appid": -12345,
        "AppName": name,
        "Exe": f'"{exe}"',
        "LaunchOptions": options,
    }])
    return parse_shortcuts(blob)[0]


def test_rpcs3_flatpak_ps3_eboot():
    sc = shortcut_for(
        "/usr/bin/flatpak",
        'run --branch=stable --command=rpcs3 net.rpcs3.RPCS3 --no-gui '
        '"/run/media/mmcblk0p1/Emulation/roms/ps3/Demons Souls/PS3_GAME/USRDIR/EBOOT.BIN"',
        name="Demon's Souls",
    )
    assert sc.emulator == "RPCS3"
    assert sc.platform == "Sony PlayStation 3"
    assert sc.rom_title == "Demons Souls"  # eboot.bin -> game directory name


def test_shadps4_appimage_ps4_eboot():
    sc = shortcut_for(
        "/home/deck/Applications/Shadps4-qt.AppImage",
        '-g "/home/deck/Emulation/roms/ps4/Bloodborne/eboot.bin"',
        name="Bloodborne",
    )
    assert sc.emulator == "shadPS4"
    assert sc.platform == "Sony PlayStation 4"
    assert sc.rom_title == "Bloodborne"


def test_emudeck_launcher_script_ryujinx():
    sc = shortcut_for(
        "/home/deck/Emulation/tools/launchers/ryujinx.sh",
        '"/home/deck/Emulation/roms/switch/Game v1.0.nsp"',
    )
    assert sc.emulator == "Ryujinx"
    assert sc.platform == "Nintendo Switch"


def test_duckstation_flatpak_ps1():
    sc = shortcut_for(
        "/usr/bin/flatpak",
        'run org.duckstation.DuckStation -batch '
        '"/home/deck/Emulation/roms/psx/Tekken 3 (USA).chd"',
    )
    assert sc.emulator == "DuckStation"
    assert sc.platform == "Sony PlayStation 1"
    assert sc.rom_title == "Tekken 3"


def test_duckstation_default_platform_without_roms_folder():
    sc = shortcut_for(
        "/usr/bin/duckstation-qt",
        '-batch "/data/games/classics/Tekken 3.chd"',
    )
    assert sc.emulator == "DuckStation"
    assert sc.platform == "Sony PlayStation 1"  # emulator default kicks in


def test_ppsspp_flatpak_psp():
    sc = shortcut_for(
        "/usr/bin/flatpak",
        'run org.ppsspp.PPSSPP "/home/deck/Emulation/roms/psp/Lumines (USA).cso"',
    )
    assert sc.emulator == "PPSSPP"
    assert sc.platform == "Sony PlayStation Portable"


def test_xemu_xbox():
    sc = shortcut_for(
        "/usr/bin/flatpak",
        'run app.xemu.xemu -dvd_path "/home/deck/Emulation/roms/xbox/Halo (USA).xiso"',
    )
    assert sc.emulator == "xemu"
    assert sc.platform == "Microsoft Xbox"


def test_xenia_xbox360_via_proton():
    sc = shortcut_for(
        "/home/deck/Emulation/tools/launchers/xenia.sh",
        '"/home/deck/Emulation/roms/xbox360/Halo 3 (USA).xex"',
    )
    assert sc.emulator == "Xenia"
    assert sc.platform == "Microsoft Xbox 360"


def test_xenia_xbla_appends_live_arcade():
    sc = shortcut_for(
        "/home/deck/Emulation/tools/launchers/xenia.sh",
        '"/home/deck/Emulation/roms/xbox360/roms/XBLA/Castle Crashers/000D0000/584109C1"',
    )
    assert sc.emulator == "Xenia"
    assert sc.platform == "Microsoft Xbox 360 Live Arcade"


def test_wii_unknown_extension_still_gets_platform():
    sc = shortcut_for(
        "/usr/bin/dolphin-emu",
        '-b -e "/home/deck/Emulation/roms/wii/Mario Galaxy.nkit.gcz"',
    )
    assert sc.emulator == "Dolphin"
    assert sc.platform == "Nintendo Wii"  # /roms/ fallback, extension unknown


def test_azahar_3ds():
    sc = shortcut_for(
        "/usr/bin/flatpak",
        'run org.azahar_emu.Azahar "/home/deck/Emulation/roms/3ds/Game (EUR).3ds"',
    )
    assert sc.emulator == "Azahar"
    assert sc.platform == "Nintendo 3DS"


def test_retroarch_flatpak_with_core():
    sc = shortcut_for(
        "/usr/bin/flatpak",
        'run org.libretro.RetroArch -L '
        '"/var/lib/flatpak/app/org.libretro.RetroArch/x86_64/stable/active/'
        'files/lib/retroarch/cores/snes9x_libretro.so" '
        '"/home/deck/Emulation/roms/snes/Super Metroid (USA).sfc"',
    )
    assert sc.emulator == "RetroArch"
    assert sc.platform == "Super Nintendo"


def test_retroarch_core_platform_fallback_without_roms_folder():
    sc = shortcut_for(
        "/usr/bin/retroarch",
        '-L "/home/deck/cores/mupen64plus_next_libretro.so" "/data/n64stuff/Game.z64"',
    )
    assert sc.emulator == "RetroArch"
    assert sc.platform == "Nintendo 64"  # from the libretro core name
