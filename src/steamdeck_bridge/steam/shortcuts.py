"""Non-Steam shortcuts: binary shortcuts.vdf parsing, legacy CRC AppIDs,
and EmuDeck/Steam ROM Manager emulator+ROM inference."""

from __future__ import annotations

import logging
import re
import zlib
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

import vdf

log = logging.getLogger(__name__)

# EmuDeck / common ROM folder names -> human platform names.
PLATFORM_MAP: dict[str, str] = {
    "3ds": "Nintendo 3DS", "n3ds": "Nintendo 3DS",
    "amiga": "Commodore Amiga",
    "arcade": "Arcade", "mame": "Arcade",
    "atari2600": "Atari 2600", "atari7800": "Atari 7800", "atarilynx": "Atari Lynx",
    "dreamcast": "Sega Dreamcast",
    "gamegear": "Sega Game Gear",
    "gb": "Game Boy", "gba": "Game Boy Advance", "gbc": "Game Boy Color",
    "gc": "Nintendo GameCube", "gamecube": "Nintendo GameCube",
    "genesis": "Sega Genesis", "megadrive": "Sega Mega Drive",
    "mastersystem": "Sega Master System",
    "n64": "Nintendo 64",
    "nds": "Nintendo DS",
    "neogeo": "Neo Geo",
    "nes": "Nintendo Entertainment System",
    "ngpx": "Neo Geo Pocket",
    "pcengine": "PC Engine", "tg16": "TurboGrafx-16",
    "ps2": "PlayStation 2", "ps3": "PlayStation 3", "psx": "PlayStation",
    "psp": "PlayStation Portable", "psvita": "PlayStation Vita",
    "saturn": "Sega Saturn",
    "scummvm": "ScummVM",
    "sega32x": "Sega 32X", "segacd": "Sega CD",
    "snes": "Super Nintendo", "sfc": "Super Famicom",
    "switch": "Nintendo Switch",
    "wii": "Nintendo Wii", "wiiu": "Nintendo Wii U",
    "xbox": "Xbox", "xbox360": "Xbox 360",
}

# Executable name -> emulator identifier.
EMULATORS: dict[str, str] = {
    "retroarch": "retroarch",
    "dolphin-emu": "dolphin", "dolphin": "dolphin",
    "ryujinx": "ryujinx",
    "citra": "citra", "lime3ds": "lime3ds", "azahar": "azahar",
    "cemu": "cemu",
    "duckstation": "duckstation", "duckstation-qt": "duckstation",
    "pcsx2": "pcsx2", "pcsx2-qt": "pcsx2",
    "rpcs3": "rpcs3",
    "ppsspp": "ppsspp", "ppssppsdl": "ppsspp",
    "melonds": "melonds",
    "mgba": "mgba",
    "flycast": "flycast",
    "xemu": "xemu", "xenia": "xenia",
    "vita3k": "vita3k",
    "scummvm": "scummvm",
    "ares": "ares", "mednafen": "mednafen",
    "primehack": "primehack",
}

ROM_EXTENSIONS = {
    ".nsp", ".xci", ".iso", ".wbfs", ".rvz", ".gcm", ".chd", ".cue", ".bin",
    ".sfc", ".smc", ".nes", ".gba", ".gbc", ".gb", ".z64", ".n64", ".v64",
    ".nds", ".3ds", ".cia", ".pbp", ".cso", ".wua", ".wux", ".md", ".gen",
    ".gg", ".sms", ".32x", ".a26", ".a78", ".lnx", ".ngp", ".ngc", ".pce",
    ".zip", ".7z",
}


@dataclass(slots=True)
class Shortcut:
    appid: int                      # unsigned 32-bit as stored by Steam
    app_name: str
    exe: str
    start_dir: str = ""
    launch_options: str = ""
    icon: str = ""
    # Derived:
    emulator: str = ""
    rom_path: str = ""
    rom_title: str = ""
    platform: str = ""
    is_srm_style: bool = field(default=False)  # AppID matches legacy CRC derivation

    @property
    def rungameid(self) -> int:
        """64-bit id for steam://rungameid/<id> launching of shortcuts."""
        return (self.appid << 32) | 0x02000000


def legacy_shortcut_appid(exe: str, app_name: str) -> int:
    """The classic CRC32 shortcut AppID used by Steam ROM Manager, BoilR, and
    older Steam clients: crc32('"exe"' + appname) with the high bit set.
    Modern Steam assigns random AppIDs, so treat this as a cross-check only."""
    key = f'"{exe}"{app_name}'
    return (zlib.crc32(key.encode("utf-8")) & 0xFFFFFFFF) | 0x80000000


def _unsigned(appid: int) -> int:
    return appid & 0xFFFFFFFF


def _strip_quotes(s: str) -> str:
    return s.strip().strip('"').strip("'")


_ROM_PATH_RE = re.compile(r'"([^"]+)"|(\S+)')


def infer_rom(launch_options: str, exe: str) -> tuple[str, str, str]:
    """Return (rom_path, rom_title, platform) inferred from a shortcut's
    launch options, using EmuDeck's Emulation/roms/<platform>/<rom> layout."""
    candidates: list[str] = []
    for m in _ROM_PATH_RE.finditer(launch_options or ""):
        token = m.group(1) or m.group(2)
        if PurePosixPath(token.replace("\\", "/")).suffix.lower() in ROM_EXTENSIONS:
            candidates.append(token)
    if not candidates:
        return "", "", ""

    rom_path = candidates[-1]
    posix = PurePosixPath(rom_path.replace("\\", "/"))
    rom_title = posix.stem
    # Strip common release decorations: "Game Name (USA) [Rev 1]" -> "Game Name"
    rom_title = re.sub(r"\s*[\(\[].*?[\)\]]", "", rom_title).strip() or posix.stem

    platform = ""
    parts = [p.lower() for p in posix.parts]
    if "roms" in parts:
        idx = parts.index("roms")
        if idx + 1 < len(parts) - 1:  # a folder exists between roms/ and the file
            platform = PLATFORM_MAP.get(parts[idx + 1], parts[idx + 1])
    return rom_path, rom_title, platform


def parse_shortcuts(blob: bytes) -> list[Shortcut]:
    """Parse a binary shortcuts.vdf blob into Shortcut objects."""
    try:
        data = vdf.binary_loads(blob)
    except (SyntaxError, ValueError) as e:
        log.warning("failed to parse shortcuts.vdf: %s", e)
        return []

    entries = data.get("shortcuts") or data.get("Shortcuts") or {}
    shortcuts: list[Shortcut] = []
    for entry in entries.values():
        if not isinstance(entry, dict):
            continue
        lower = {k.lower(): v for k, v in entry.items()}
        exe = _strip_quotes(str(lower.get("exe", "")))
        app_name = str(lower.get("appname", ""))
        raw_appid = lower.get("appid")
        appid = _unsigned(int(raw_appid)) if raw_appid is not None else legacy_shortcut_appid(
            _strip_quotes(str(lower.get("exe", ""))), app_name
        )

        sc = Shortcut(
            appid=appid,
            app_name=app_name,
            exe=exe,
            start_dir=_strip_quotes(str(lower.get("startdir", ""))),
            launch_options=str(lower.get("launchoptions", "")),
            icon=str(lower.get("icon", "")),
        )
        sc.is_srm_style = appid == legacy_shortcut_appid(sc.exe, app_name)

        exe_name = PurePosixPath(sc.exe.replace("\\", "/")).name.lower()
        exe_stem = exe_name.removesuffix(".exe").removesuffix(".appimage").removesuffix(".sh")
        for needle, emu in EMULATORS.items():
            if needle == exe_stem or needle in exe_stem:
                sc.emulator = emu
                break

        sc.rom_path, sc.rom_title, sc.platform = infer_rom(sc.launch_options, sc.exe)
        if not sc.platform and sc.emulator:
            sc.platform = "Emulation"
        shortcuts.append(sc)
    return shortcuts


class ShortcutIndex:
    """Shortcuts across all Steam userdata accounts, keyed by AppID."""

    def __init__(self, steam_root: Path):
        self.root = steam_root
        self.shortcuts: dict[int, Shortcut] = {}

    def refresh(self, userdata: list[Path]) -> None:
        found: dict[int, Shortcut] = {}
        for user_dir in userdata:
            f = user_dir / "config" / "shortcuts.vdf"
            if not f.is_file():
                continue
            try:
                for sc in parse_shortcuts(f.read_bytes()):
                    found.setdefault(sc.appid, sc)
            except OSError as e:
                log.warning("cannot read %s: %s", f, e)
        self.shortcuts = found
        log.debug("shortcut index refreshed: %d shortcuts", len(found))

    def get(self, appid: int) -> Shortcut | None:
        return self.shortcuts.get(_unsigned(appid))
