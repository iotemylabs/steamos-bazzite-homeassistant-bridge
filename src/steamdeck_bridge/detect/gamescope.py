"""Detect the focused game via gamescope's X11 root-window atoms.

Gamescope (Gaming Mode) maintains GAMESCOPE_FOCUSED_APP on the root window of
its nested X server. We read it with `xprop` (present on SteamOS/Bazzite) so we
don't need a compiled X11 binding. AppID 769 is steamui itself = "no game".
"""

from __future__ import annotations

import logging
import re
import subprocess
from pathlib import Path

log = logging.getLogger(__name__)

STEAMUI_APPID = 769
_ATOMS = ("GAMESCOPE_FOCUSED_APP", "GAMESCOPE_FOCUSED_APP_GFX")
_VALUE_RE = re.compile(r"=\s*(\d+)")


def candidate_displays() -> list[str]:
    """X displays that might be gamescope's nested server."""
    displays = []
    sockets = Path("/tmp/.X11-unix")
    if sockets.is_dir():
        for sock in sorted(sockets.iterdir()):
            if sock.name.startswith("X") and sock.name[1:].isdigit():
                displays.append(f":{sock.name[1:]}")
    return displays or [":0", ":1"]


def _read_atom(display: str, atom: str, timeout: float = 2.0) -> int | None:
    try:
        out = subprocess.run(
            ["xprop", "-root", "-display", display, atom],
            capture_output=True, text=True, timeout=timeout, check=False,
        ).stdout
    except (OSError, subprocess.TimeoutExpired):
        return None
    if "not found" in out or not out:
        return None
    m = _VALUE_RE.search(out)
    return int(m.group(1)) if m else None


class GamescopeDetector:
    """Yields the focused AppID in Gaming Mode; caches the working display."""

    name = "gamescope"

    def __init__(self) -> None:
        self._display: str | None = None

    def focused_appid(self) -> int | None:
        """Return the focused AppID, 0 for 'no game focused', None if no
        gamescope display is reachable (e.g. Desktop Mode)."""
        displays = [self._display] if self._display else candidate_displays()
        for display in displays:
            for atom in _ATOMS:
                value = _read_atom(display, atom)
                if value is None:
                    continue
                self._display = display
                if value in (0, STEAMUI_APPID):
                    return 0
                return value
        self._display = None
        return None

    @property
    def gamescope_present(self) -> bool:
        return self._display is not None
