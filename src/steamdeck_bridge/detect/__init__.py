"""Detection pipeline: ordered detectors + metadata enrichment.

Order of trust:
  1. gamescope focused-app atom (authoritative in Gaming Mode)
  2. reaper `SteamLaunch AppId=` process scan (works everywhere)
  3. Heroic / Lutris process matching
  4. registry.vdf RunningAppID (legacy hint)
"""

from __future__ import annotations

import logging
import time
from pathlib import Path

from ..models import GameSession, GameSource
from ..steam.library import SteamLibrary
from ..steam.paths import registry_vdf
from ..steam.shortcuts import ShortcutIndex
from .gamescope import GamescopeDetector
from .heroic import HeroicDetector
from .lutris import LutrisDetector
from .registry import RegistryDetector
from .steam_process import SteamProcessDetector

log = logging.getLogger(__name__)

SHORTCUT_BIT = 0x80000000


class DetectionPipeline:
    def __init__(
        self,
        library: SteamLibrary,
        shortcuts: ShortcutIndex,
        home: Path | None = None,
    ):
        self.library = library
        self.shortcuts = shortcuts
        self.gamescope = GamescopeDetector()
        self.process = SteamProcessDetector()
        self.heroic = HeroicDetector(home)
        self.lutris = LutrisDetector(home)
        self.registry = RegistryDetector(registry_vdf(home))

    # -- public ---------------------------------------------------------

    def detect(self) -> GameSession | None:
        """Return the enriched current game session, or None when idle."""
        # 1. gamescope atom
        appid = self.gamescope.focused_appid()
        if appid == 0:
            # Gaming Mode with steamui focused. A game may still be running
            # in the background; prefer "nothing focused" = no active game.
            return None
        if appid is not None:
            return self._enrich_steam_appid(appid, source_hint="gamescope")

        # 2. reaper process scan (desktop mode, or gamescope unreachable)
        running = self.process.running()
        if running is not None:
            return self._enrich_steam_appid(
                running.appid,
                source_hint="process",
                pid=running.pid,
                started_at=running.started_at,
                launch_command=running.launch_command,
            )

        # 3. third-party launchers
        heroic_hit = self.heroic.running()
        if heroic_hit is not None:
            game, pid = heroic_hit
            return GameSession(
                source=GameSource.HEROIC,
                title=game.title,
                steam_title="",
                platform=game.platform,
                exe=game.install_path,
                pid=pid,
            )
        lutris_hit = self.lutris.running()
        if lutris_hit is not None:
            game, pid = lutris_hit
            return GameSession(
                source=GameSource.LUTRIS,
                title=game.name,
                platform=f"Lutris ({game.runner})" if game.runner else "Lutris",
                exe=game.directory,
                pid=pid,
            )

        # 4. legacy registry hint
        appid = self.registry.running_appid()
        if appid:
            return self._enrich_steam_appid(appid, source_hint="registry")

        return None

    def refresh_metadata(self) -> None:
        """Re-read library, shortcuts, and launcher indexes."""
        self.heroic.refresh()
        self.lutris.refresh()

    # -- enrichment -------------------------------------------------------

    def _enrich_steam_appid(
        self,
        appid: int,
        source_hint: str,
        pid: int | None = None,
        started_at: float = 0.0,
        launch_command: str = "",
    ) -> GameSession:
        appid_u32 = appid & 0xFFFFFFFF
        session = GameSession(pid=pid, launch_command=launch_command)
        if started_at:
            session.started_at = started_at
        else:
            session.started_at = time.time()

        # Fill pid/timestamps from the process table when the hint lacked them.
        if pid is None:
            running = self.process.by_appid(appid_u32)
            if running:
                session.pid = running.pid
                if running.started_at:
                    session.started_at = running.started_at
                session.launch_command = session.launch_command or running.launch_command

        shortcut = self.shortcuts.get(appid_u32)
        if shortcut is not None or appid_u32 & SHORTCUT_BIT:
            session.source = GameSource.SHORTCUT
            session.shortcut_appid = appid_u32
            if shortcut is not None:
                session.title = shortcut.app_name
                session.steam_title = shortcut.app_name
                session.exe = shortcut.exe
                session.launch_command = session.launch_command or shortcut.launch_options
                session.emulator = shortcut.emulator
                session.is_emulator = bool(shortcut.emulator)
                session.is_srm_shortcut = shortcut.is_srm_style
                session.rom_title = shortcut.rom_title
                session.platform = shortcut.platform or "Non-Steam"
                if shortcut.rom_title:
                    session.title = shortcut.rom_title
            else:
                session.title = f"Non-Steam app {appid_u32}"
                session.platform = "Non-Steam"
            return session

        session.source = GameSource.STEAM
        session.appid = appid_u32
        session.platform = "Steam"
        app = self.library.get(appid_u32)
        if app is not None:
            session.title = app.name
            session.steam_title = app.name
        else:
            session.title = f"Steam app {appid_u32}"
        log.debug("detected %s via %s", session.title, source_hint)
        return session
