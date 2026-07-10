"""Shared state models. Everything is JSON-serializable via .to_dict()."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class GameSource(StrEnum):
    STEAM = "steam"              # regular Steam AppID
    SHORTCUT = "shortcut"        # non-Steam shortcut (incl. SRM/EmuDeck)
    HEROIC = "heroic"
    LUTRIS = "lutris"
    UNKNOWN = "unknown"


class SessionMode(StrEnum):
    GAMING = "gaming"            # gamescope session
    DESKTOP = "desktop"
    UNKNOWN = "unknown"


@dataclass(slots=True)
class GameSession:
    """A currently running (or just-detected) game."""

    source: GameSource = GameSource.UNKNOWN
    appid: int | None = None             # Steam AppID (source == steam)
    shortcut_appid: int | None = None    # non-Steam shortcut AppID
    title: str = ""                      # display title (best available)
    steam_title: str = ""                # title as Steam knows it
    rom_title: str = ""                  # inferred ROM title, if emulator shortcut
    platform: str = ""                   # e.g. "Steam", "Nintendo Switch", "GOG"
    emulator: str = ""                   # e.g. "ryujinx", "retroarch"
    is_emulator: bool = False
    is_srm_shortcut: bool = False        # AppID matches the legacy CRC derivation
    exe: str = ""                        # executable path
    launch_command: str = ""             # full launch command / options
    pid: int | None = None
    started_at: float = field(default_factory=time.time)  # epoch seconds

    @property
    def duration_s(self) -> int:
        return max(0, int(time.time() - self.started_at))

    @property
    def identity(self) -> tuple:
        """Key used to decide whether two detections are the same session."""
        return (self.source, self.appid, self.shortcut_appid, self.title)

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source.value,
            "appid": self.appid,
            "shortcut_appid": self.shortcut_appid,
            "title": self.title,
            "steam_title": self.steam_title,
            "rom_title": self.rom_title,
            "platform": self.platform,
            "emulator": self.emulator,
            "is_emulator": self.is_emulator,
            "is_srm_shortcut": self.is_srm_shortcut,
            "exe": self.exe,
            "launch_command": self.launch_command,
            "pid": self.pid,
            "started_at": self.started_at,
            "duration_s": self.duration_s,
        }


@dataclass(slots=True)
class DeviceState:
    mode: SessionMode = SessionMode.UNKNOWN
    awake: bool = True
    battery_percent: int | None = None
    battery_state: str = ""              # charging / discharging / full
    on_ac: bool | None = None
    docked: bool | None = None
    steam_running: bool = False
    steam_user: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode.value,
            "awake": self.awake,
            "battery_percent": self.battery_percent,
            "battery_state": self.battery_state,
            "on_ac": self.on_ac,
            "docked": self.docked,
            "steam_running": self.steam_running,
            "steam_user": self.steam_user,
        }


@dataclass(slots=True)
class BridgeState:
    game: GameSession | None = None
    device: DeviceState = field(default_factory=DeviceState)

    def to_dict(self) -> dict[str, Any]:
        return {
            "game": self.game.to_dict() if self.game else None,
            "device": self.device.to_dict(),
        }
