"""Bridge orchestrator: poll loop, state store, action dispatch, fan-out."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from pathlib import Path

from aiohttp import web

from .artwork import ArtworkResolver
from .config import Config
from .detect import DetectionPipeline
from .models import BridgeState, GameSession
from .steam.library import SteamLibrary
from .steam.paths import find_steam_root, userdata_dirs
from .steam.shortcuts import ShortcutIndex
from .system import Actions, read_device_state

log = logging.getLogger(__name__)

# Sensors that change continuously (duration) shouldn't spam MQTT; publish a
# keepalive snapshot at most this often while state is otherwise unchanged.
KEEPALIVE_S = 30.0


class Bridge:
    def __init__(self, config: Config, home: Path | None = None):
        self.config = config
        self.home = home
        self.steam_root = find_steam_root(home)
        if self.steam_root is None:
            log.warning("no Steam installation found; Steam features disabled")
            # Empty stand-ins keep the rest of the code branch-free.
            self.library = SteamLibrary(Path("/nonexistent"))
            self.shortcuts = ShortcutIndex(Path("/nonexistent"))
            self._userdata: list[Path] = []
        else:
            log.info("Steam root: %s", self.steam_root)
            self.library = SteamLibrary(self.steam_root)
            self.shortcuts = ShortcutIndex(self.steam_root)
            self._userdata = userdata_dirs(self.steam_root)

        self.pipeline = DetectionPipeline(self.library, self.shortcuts, home)
        self.artwork = ArtworkResolver(config.artwork, self.steam_root, self._userdata)
        self.actions = Actions(config.actions)
        self.state = BridgeState()
        self.ws_clients: set[web.WebSocketResponse] = set()
        self.mqtt = None  # set by main() when MQTT is enabled
        self._stop = asyncio.Event()

    # -- lifecycle ------------------------------------------------------------

    def refresh_library(self) -> None:
        if self.steam_root:
            self._userdata = userdata_dirs(self.steam_root)
            self.library.refresh()
            self.shortcuts.refresh(self._userdata)
            self.artwork.userdata = self._userdata

    async def run(self) -> None:
        self.refresh_library()
        interval = max(0.5, self.config.detection.interval)
        last_broadcast = 0.0
        last_identity = None
        loop = asyncio.get_running_loop()

        while not self._stop.is_set():
            try:
                # Detection touches /proc, X11, and disk: keep it off the event loop.
                game = await loop.run_in_executor(None, self.pipeline.detect)
                steam_user = await loop.run_in_executor(None, self.library.current_user)
                device = await loop.run_in_executor(
                    None, read_device_state, steam_user, self.home
                )

                # Preserve the original start time across polls of the same session.
                if game and self.state.game and game.identity == self.state.game.identity:
                    game.started_at = self.state.game.started_at
                    if game.pid is None:
                        game.pid = self.state.game.pid

                changed = (
                    (game.identity if game else None) != last_identity
                    or device.to_dict() != self.state.device.to_dict()
                )
                self.state.game = game
                self.state.device = device
                last_identity = game.identity if game else None

                now = loop.time()
                if changed or (now - last_broadcast) >= KEEPALIVE_S:
                    last_broadcast = now
                    await self._broadcast()
            except Exception:
                log.exception("poll cycle failed")

            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._stop.wait(), timeout=interval)

        await self.artwork.close()

    def stop(self) -> None:
        self._stop.set()

    async def _broadcast(self) -> None:
        payload = self.state.to_dict()
        if self.mqtt:
            self.mqtt.publish_state(payload)
        dead = []
        for ws in self.ws_clients:
            try:
                await ws.send_json({"type": "state", "data": payload})
            except (ConnectionError, RuntimeError):
                dead.append(ws)
        for ws in dead:
            self.ws_clients.discard(ws)

    # -- actions --------------------------------------------------------------

    async def run_action(self, action: str, params: dict) -> bool:
        log.info("action %s %s", action, params or "")
        a = self.actions
        current_pid = self.state.game.pid if self.state.game else None

        if action == "launch_game":
            appid = _appid_from(params)
            return a.launch_game(appid) if appid else False
        if action == "switch_game":
            appid = _appid_from(params)
            return a.switch_game(appid, current_pid) if appid else False
        if action == "close_game":
            return a.close_game(current_pid)
        if action == "restart_steam":
            return a.restart_steam()
        if action == "restart_gamescope":
            return a.restart_gamescope()
        if action == "suspend":
            return a.suspend()
        if action == "shutdown":
            return a.shutdown()
        if action == "reboot":
            return a.reboot()
        if action == "wake":
            # Wake-from-suspend can't be initiated by a suspended daemon;
            # use Wake-on-LAN from HA (documented) — accepted as a no-op here.
            return True
        if action in ("refresh_library", "refresh_metadata"):
            self.refresh_library()
            self.pipeline.refresh_metadata()
            return True
        return False


def _appid_from(params: dict) -> int | None:
    try:
        return int(params.get("appid"))
    except (TypeError, ValueError):
        return None


def make_game_session_json(game: GameSession | None) -> dict | None:
    return game.to_dict() if game else None
