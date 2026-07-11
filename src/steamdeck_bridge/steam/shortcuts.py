"""Non-Steam shortcuts: binary shortcuts.vdf parsing, legacy CRC AppIDs,
and EmuDeck/Steam ROM Manager emulator+ROM inference.

EmuDeck/SRM shortcuts rarely point Exe at the emulator binary directly — they
go through launcher scripts (Emulation/tools/launchers/rpcs3.sh), flatpak
(`/usr/bin/flatpak run net.rpcs3.RPCS3 ...`), AppImages, or Proton (Xenia).
All inference therefore scans the *entire* launch command, not just Exe.
"""

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
    "ps1": "Sony PlayStation 1", "psx": "Sony PlayStation 1",
    "ps2": "Sony PlayStation 2",
    "ps3": "Sony PlayStation 3",
    "ps4": "Sony PlayStation 4",
    "psp": "Sony PlayStation Portable",
    "psvita": "Sony PlayStation Vita",
    "saturn": "Sega Saturn",
    "scummvm": "ScummVM",
    "sega32x": "Sega 32X", "segacd": "Sega CD",
    "snes": "Super Nintendo", "sfc": "Super Famicom",
    "switch": "Nintendo Switch",
    "wii": "Nintendo Wii", "wiiu": "Nintendo Wii U",
    "xbox": "Microsoft Xbox",
    "xbox360": "Microsoft Xbox 360", "x360": "Microsoft Xbox 360",
}

# Needle (lowercase; exact token basename or word-boundary substring of the
# full command) -> emulator display name. Flatpak app ids included.
EMULATORS: dict[str, str] = {
    "retroarch": "RetroArch", "org.libretro.retroarch": "RetroArch",
    "dolphin-emu": "Dolphin", "dolphin": "Dolphin",
    "org.dolphinemu.dolphin-emu": "Dolphin",
    "primehack": "PrimeHack",
    "ryujinx": "Ryujinx", "org.ryujinx.ryujinx": "Ryujinx",
    "yuzu": "yuzu", "suyu": "suyu", "citron": "Citron", "sudachi": "Sudachi",
    "citra": "Citra", "citra-qt": "Citra", "org.citra_emu.citra": "Citra",
    "lime3ds": "Lime3DS", "io.github.lime3ds.lime3ds": "Lime3DS",
    "azahar": "Azahar", "org.azahar_emu.azahar": "Azahar",
    "cemu": "Cemu", "info.cemu.cemu": "Cemu",
    "duckstation": "DuckStation", "duckstation-qt": "DuckStation",
    "org.duckstation.duckstation": "DuckStation",
    "pcsx2": "PCSX2", "pcsx2-qt": "PCSX2", "net.pcsx2.pcsx2": "PCSX2",
    "rpcs3": "RPCS3", "net.rpcs3.rpcs3": "RPCS3",
    "shadps4": "shadPS4", "shadps4-qt": "shadPS4",
    "io.github.shadps4_emu.shadps4": "shadPS4", "net.shadps4.shadps4": "shadPS4",
    "ppsspp": "PPSSPP", "ppssppsdl": "PPSSPP", "org.ppsspp.ppsspp": "PPSSPP",
    "vita3k": "Vita3K",
    "melonds": "melonDS", "net.kuribo64.melonds": "melonDS",
    "mgba": "mGBA",
    "flycast": "Flycast", "org.flycast.flycast": "Flycast",
    "xemu": "xemu", "app.xemu.xemu": "xemu",
    "xenia": "Xenia", "xenia_canary": "Xenia", "xenia-canary": "Xenia",
    "scummvm": "ScummVM",
    "ares": "ares", "mednafen": "Mednafen",
    "mame": "MAME",
    "supermodel": "Supermodel",
}

# Emulators that imply a platform when ROM-path inference can't determine one.
EMULATOR_PLATFORMS: dict[str, str] = {
    "RPCS3": "Sony PlayStation 3",
    "shadPS4": "Sony PlayStation 4",
    "DuckStation": "Sony PlayStation 1",
    "PCSX2": "Sony PlayStation 2",
    "PPSSPP": "Sony PlayStation Portable",
    "Vita3K": "Sony PlayStation Vita",
    "xemu": "Microsoft Xbox",
    "Xenia": "Microsoft Xbox 360",
    "Ryujinx": "Nintendo Switch",
    "yuzu": "Nintendo Switch", "suyu": "Nintendo Switch",
    "Citron": "Nintendo Switch", "Sudachi": "Nintendo Switch",
    "Citra": "Nintendo 3DS", "Lime3DS": "Nintendo 3DS", "Azahar": "Nintendo 3DS",
    "Cemu": "Nintendo Wii U",
    "melonDS": "Nintendo DS",
    "Flycast": "Sega Dreamcast",
    "mGBA": "Game Boy Advance",
}

# libretro core name fragments -> platform, for RetroArch `-L <core>.so` when
# the ROM path doesn't reveal the platform folder.
CORE_PLATFORMS: dict[str, str] = {
    "snes9x": "Super Nintendo", "bsnes": "Super Nintendo",
    "nestopia": "Nintendo Entertainment System",
    "fceumm": "Nintendo Entertainment System",
    "mesen": "Nintendo Entertainment System",
    "gambatte": "Game Boy",
    "mgba": "Game Boy Advance",
    "melonds": "Nintendo DS",
    "mupen64plus": "Nintendo 64", "parallel_n64": "Nintendo 64",
    "dolphin": "Nintendo GameCube",
    "citra": "Nintendo 3DS",
    "swanstation": "Sony PlayStation 1",
    "pcsx_rearmed": "Sony PlayStation 1",
    "beetle_psx": "Sony PlayStation 1",
    "ppsspp": "Sony PlayStation Portable",
    "genesis_plus_gx": "Sega Genesis", "picodrive": "Sega Genesis",
    "flycast": "Sega Dreamcast",
    "beetle_saturn": "Sega Saturn", "yabause": "Sega Saturn",
    "opera": "3DO",
    "stella": "Atari 2600",
    "mame": "Arcade", "fbneo": "Arcade",
}

ROM_EXTENSIONS = {
    ".nsp", ".xci", ".iso", ".wbfs", ".rvz", ".gcm", ".chd", ".cue", ".bin",
    ".sfc", ".smc", ".nes", ".gba", ".gbc", ".gb", ".z64", ".n64", ".v64",
    ".nds", ".3ds", ".cia", ".pbp", ".cso", ".wua", ".wux", ".md", ".gen",
    ".gg", ".sms", ".32x", ".a26", ".a78", ".lnx", ".ngp", ".ngc", ".pce",
    ".xex", ".xiso", ".wad", ".wia", ".dol", ".elf", ".m3u", ".pkg",
    ".zip", ".7z",
}

# Filenames that are container entry points, not game titles.
_GENERIC_ROM_NAMES = {"eboot", "eboot.bin", "eboot.elf", "default", "default.xex",
                      "param", "disc", "game"}


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


_TOKEN_RE = re.compile(r'"([^"]+)"|(\S+)')
_STRIP_SUFFIXES = (".sh", ".exe", ".appimage", ".desktop", ".bat")


def _tokens(command: str) -> list[str]:
    return [m.group(1) or m.group(2) for m in _TOKEN_RE.finditer(command)]


def detect_emulator(exe: str, launch_options: str) -> str:
    """Identify the emulator from the full launch command: binary names,
    EmuDeck launcher scripts, flatpak app ids, AppImages, Proton-wrapped exes."""
    command = f"{exe} {launch_options}".replace("\\", "/")
    lower = command.lower()

    # Pass 1: exact basename of every path-like token.
    for token in _tokens(lower):
        base = token.rsplit("/", 1)[-1]
        for suffix in _STRIP_SUFFIXES:
            base = base.removesuffix(suffix)
        if base in EMULATORS:
            return EMULATORS[base]

    # Pass 2: word-boundary substring over the whole command (flatpak ids,
    # nested wrapper commands). Boundaries avoid e.g. 'ares' inside 'shares'.
    for needle, display in EMULATORS.items():
        if re.search(rf"(?<![a-z0-9]){re.escape(needle)}(?![a-z0-9])", lower):
            return display
    return ""


def _clean_title(stem: str) -> str:
    """'Game Name (USA) [Rev 1]' -> 'Game Name'."""
    cleaned = re.sub(r"\s*[\(\[].*?[\)\]]", "", stem).strip()
    return cleaned or stem


def infer_rom(launch_options: str, exe: str = "") -> tuple[str, str, str]:
    """Return (rom_path, rom_title, platform) from a shortcut's launch options.

    Platform comes from the EmuDeck layout `.../roms/<platform>/...`. ROM
    candidates are matched by extension first; failing that, any argument that
    lives under a roms/ directory counts (XBLA content and other extension-less
    layouts). Xbox 360 paths containing an XBLA folder get 'Live Arcade'
    appended."""
    tokens = _tokens(launch_options or "")

    by_ext = [
        t for t in tokens
        if PurePosixPath(t.replace("\\", "/")).suffix.lower() in ROM_EXTENSIONS
    ]
    by_folder = [t for t in tokens if "/roms/" in t.replace("\\", "/").lower()]
    candidates = by_ext or by_folder
    if not candidates:
        return "", "", ""

    rom_path = candidates[-1]
    posix = PurePosixPath(rom_path.replace("\\", "/"))
    parts = list(posix.parts)
    parts_lower = [p.lower() for p in parts]

    platform = ""
    platform_idx = -1
    if "roms" in parts_lower:
        idx = parts_lower.index("roms")
        if idx + 1 < len(parts) - 1:  # a folder exists between roms/ and the file
            platform_idx = idx + 1
            folder = parts_lower[platform_idx]
            platform = PLATFORM_MAP.get(folder, parts[platform_idx])
            if folder in ("xbox360", "x360") and any(
                "xbla" in p or "live arcade" in p for p in parts_lower[platform_idx + 1:]
            ):
                platform += " Live Arcade"

    # Title: filename stem, unless it's a generic container entry point
    # (eboot.bin & co) — then the game's directory name is the real title.
    name_lower = posix.name.lower()
    stem = posix.stem
    if name_lower in _GENERIC_ROM_NAMES or stem.lower() in _GENERIC_ROM_NAMES:
        if platform_idx >= 0 and platform_idx + 1 < len(parts) - 1:
            stem = parts[platform_idx + 1]
        elif len(parts) >= 2:
            stem = parts[-2]
    rom_title = _clean_title(stem)

    return rom_path, rom_title, platform


def infer_platform(emulator: str, launch_options: str, rom_platform: str) -> str:
    """Best-effort platform: ROM folder > libretro core > emulator default."""
    if rom_platform:
        return rom_platform
    lower = (launch_options or "").lower()
    if "_libretro" in lower or "libretro" in lower:
        for fragment, platform in CORE_PLATFORMS.items():
            if fragment in lower:
                return platform
    if emulator and emulator in EMULATOR_PLATFORMS:
        return EMULATOR_PLATFORMS[emulator]
    return ""


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
        appid = (
            _unsigned(int(raw_appid))
            if raw_appid is not None
            else legacy_shortcut_appid(exe, app_name)
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
        sc.emulator = detect_emulator(sc.exe, sc.launch_options)
        sc.rom_path, sc.rom_title, rom_platform = infer_rom(sc.launch_options, sc.exe)
        sc.platform = infer_platform(sc.emulator, sc.launch_options, rom_platform)
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
