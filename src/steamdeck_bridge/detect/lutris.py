"""Detect running Lutris games via its sqlite database + process scan."""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)

DB_PATHS = (
    "~/.local/share/lutris/pga.db",
    "~/.var/app/net.lutris.Lutris/data/lutris/pga.db",
)


@dataclass(slots=True)
class LutrisGame:
    id: int
    name: str
    slug: str
    runner: str
    directory: str


def find_lutris_db(home: Path | None = None) -> Path | None:
    home = home or Path.home()
    for candidate in DB_PATHS:
        p = Path(candidate.replace("~", str(home)))
        if p.is_file():
            return p
    return None


def load_games(db_path: Path) -> list[LutrisGame]:
    games: list[LutrisGame] = []
    try:
        # Read-only URI so we never lock Lutris's own writes.
        con = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True)
        try:
            rows = con.execute(
                "SELECT id, name, slug, runner, directory FROM games "
                "WHERE installed = 1 AND directory IS NOT NULL AND directory != ''"
            ).fetchall()
        finally:
            con.close()
    except sqlite3.Error as e:
        log.warning("lutris db read failed: %s", e)
        return []
    for row in rows:
        games.append(LutrisGame(
            id=row[0], name=row[1] or "", slug=row[2] or "",
            runner=row[3] or "", directory=row[4] or "",
        ))
    return games


class LutrisDetector:
    name = "lutris"

    def __init__(self, home: Path | None = None):
        self._db = find_lutris_db(home)
        self._games: list[LutrisGame] = []
        self.refresh()

    def refresh(self) -> None:
        if self._db:
            self._games = load_games(self._db)
            log.debug("lutris: %d installed games", len(self._games))

    def running(self, proc: Path = Path("/proc")) -> tuple[LutrisGame, int] | None:
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
                    if game.directory and target.startswith(Path(game.directory).as_posix()):
                        return game, pid
        return None
