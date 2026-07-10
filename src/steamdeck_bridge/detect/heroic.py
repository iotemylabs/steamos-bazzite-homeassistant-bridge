"""Detect running Heroic (Epic/GOG/Amazon) games.

Heroic is a GUI over legendary/gogdl/nile; while a game runs, the game's own
process tree runs from its install path. We index installed games from
Heroic's JSON stores and match /proc executables/cwds against install paths.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)

CONFIG_DIRS = (
    "~/.config/heroic",
    "~/.var/app/com.heroicgameslauncher.hgl/config/heroic",
)

_STORE_PLATFORMS = {
    "legendary": "Epic Games",
    "gog_store": "GOG",
    "nile_config": "Amazon Games",
}


@dataclass(slots=True)
class HeroicGame:
    app_name: str          # store-internal id
    title: str
    install_path: str
    platform: str          # Epic Games / GOG / Amazon Games


def find_heroic_config(home: Path | None = None) -> Path | None:
    home = home or Path.home()
    for candidate in CONFIG_DIRS:
        p = Path(candidate.replace("~", str(home)))
        if p.is_dir():
            return p
    return None


def _load_json(path: Path) -> dict | list | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def load_installed_games(config_dir: Path) -> list[HeroicGame]:
    games: list[HeroicGame] = []

    # legendary/installed.json: {app_name: {title, install_path, ...}}
    data = _load_json(config_dir / "legendary" / "installed.json")
    if isinstance(data, dict):
        for app_name, info in data.items():
            if isinstance(info, dict) and info.get("install_path"):
                games.append(HeroicGame(
                    app_name=app_name,
                    title=info.get("title", app_name),
                    install_path=str(info["install_path"]),
                    platform="Epic Games",
                ))

    # gog_store/installed.json: {"installed": [{appName, install_path, ...}]}
    data = _load_json(config_dir / "gog_store" / "installed.json")
    if isinstance(data, dict):
        for info in data.get("installed", []):
            if isinstance(info, dict) and info.get("install_path"):
                games.append(HeroicGame(
                    app_name=str(info.get("appName", "")),
                    title=str(info.get("title") or info.get("appName", "")),
                    install_path=str(info["install_path"]),
                    platform="GOG",
                ))

    # nile_config/nile/installed.json: [{id, path}, ...]
    data = _load_json(config_dir / "nile_config" / "nile" / "installed.json")
    if isinstance(data, list):
        for info in data:
            if isinstance(info, dict) and info.get("path"):
                games.append(HeroicGame(
                    app_name=str(info.get("id", "")),
                    title=str(info.get("id", "")),
                    install_path=str(info["path"]),
                    platform="Amazon Games",
                ))

    return games


class HeroicDetector:
    name = "heroic"

    def __init__(self, home: Path | None = None):
        self.home = home
        self._config_dir = find_heroic_config(home)
        self._games: list[HeroicGame] = []
        self.refresh()

    def refresh(self) -> None:
        if self._config_dir:
            self._games = load_installed_games(self._config_dir)
            log.debug("heroic: %d installed games", len(self._games))

    def running(self, proc: Path = Path("/proc")) -> tuple[HeroicGame, int] | None:
        """Return (game, pid) if a process runs from a Heroic install path."""
        if not self._games:
            return None
        try:
            pids = [int(p.name) for p in proc.iterdir() if p.name.isdigit()]
        except OSError:
            return None
        for pid in pids:
            for link in ("exe", "cwd"):
                try:
                    target = (proc / str(pid) / link).resolve(strict=False).as_posix()
                except OSError:
                    continue
                for game in self._games:
                    if game.install_path and target.startswith(
                        Path(game.install_path).as_posix()
                    ):
                        return game, pid
        return None
