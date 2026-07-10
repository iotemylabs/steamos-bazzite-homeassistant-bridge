"""Locate the Steam installation across SteamOS, Bazzite, and Flatpak layouts."""

from __future__ import annotations

from pathlib import Path

# Order matters: ~/.steam/root is the canonical symlink Valve maintains.
_CANDIDATE_ROOTS = (
    "~/.steam/root",
    "~/.local/share/Steam",
    "~/.var/app/com.valvesoftware.Steam/data/Steam",  # Flatpak Steam
    "~/.steam/steam",
)


def find_steam_root(home: Path | None = None) -> Path | None:
    home = home or Path.home()
    for candidate in _CANDIDATE_ROOTS:
        p = Path(candidate.replace("~", str(home))).resolve()
        if (p / "steamapps").is_dir() or (p / "userdata").is_dir():
            return p
    return None


def is_flatpak_steam(root: Path) -> bool:
    return ".var/app/com.valvesoftware.Steam" in root.as_posix()


def steam_pid_file(home: Path | None = None) -> Path:
    home = home or Path.home()
    return home / ".steam" / "steam.pid"


def registry_vdf(home: Path | None = None) -> Path:
    home = home or Path.home()
    return home / ".steam" / "registry.vdf"


def userdata_dirs(root: Path) -> list[Path]:
    """All per-user userdata directories (numeric account-id3 folders)."""
    userdata = root / "userdata"
    if not userdata.is_dir():
        return []
    return sorted(
        (d for d in userdata.iterdir() if d.is_dir() and d.name.isdigit() and d.name != "0"),
        key=lambda d: d.stat().st_mtime,
        reverse=True,  # most recently used account first
    )
