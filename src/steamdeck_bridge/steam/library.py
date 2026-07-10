"""Steam library index: libraryfolders.vdf + appmanifest_*.acf + loginusers.vdf."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import vdf

log = logging.getLogger(__name__)


@dataclass(slots=True)
class InstalledApp:
    appid: int
    name: str
    installdir: str
    library_path: str


def parse_libraryfolders(text: str) -> list[str]:
    """Return library mount paths from a libraryfolders.vdf document."""
    data = vdf.loads(text)
    folders = data.get("libraryfolders") or data.get("LibraryFolders") or {}
    paths: list[str] = []
    for key, entry in folders.items():
        if not key.isdigit():
            continue
        # dict is the modern format; very old files map "1" -> "/path" directly
        path = entry.get("path") if isinstance(entry, dict) else entry
        if path:
            paths.append(path)
    return paths


def parse_appmanifest(text: str, library_path: str = "") -> InstalledApp | None:
    data = vdf.loads(text)
    state = data.get("AppState") or data.get("appstate")
    if not state:
        return None
    try:
        appid = int(state["appid"])
    except (KeyError, ValueError):
        return None
    return InstalledApp(
        appid=appid,
        name=state.get("name", ""),
        installdir=state.get("installdir", ""),
        library_path=library_path,
    )


def parse_loginusers(text: str) -> str:
    """Return the persona name of the most recent Steam login, or ''."""
    data = vdf.loads(text)
    users = data.get("users") or {}
    fallback = ""
    for info in users.values():
        if not isinstance(info, dict):
            continue
        name = info.get("PersonaName") or info.get("AccountName") or ""
        if str(info.get("MostRecent") or info.get("mostrecent") or "0") == "1":
            return name
        fallback = fallback or name
    return fallback


class SteamLibrary:
    """Index of installed Steam apps across all library folders."""

    def __init__(self, steam_root: Path):
        self.root = steam_root
        self.apps: dict[int, InstalledApp] = {}

    def refresh(self) -> None:
        apps: dict[int, InstalledApp] = {}
        lf = self.root / "steamapps" / "libraryfolders.vdf"
        library_paths = [str(self.root)]
        if lf.is_file():
            try:
                for p in parse_libraryfolders(lf.read_text(encoding="utf-8", errors="replace")):
                    if p not in library_paths:
                        library_paths.append(p)
            except SyntaxError as e:
                log.warning("failed to parse %s: %s", lf, e)

        for lib in library_paths:
            steamapps = Path(lib) / "steamapps"
            if not steamapps.is_dir():
                continue
            for manifest in steamapps.glob("appmanifest_*.acf"):
                try:
                    app = parse_appmanifest(
                        manifest.read_text(encoding="utf-8", errors="replace"), lib
                    )
                except (SyntaxError, OSError) as e:
                    log.warning("failed to parse %s: %s", manifest, e)
                    continue
                if app:
                    apps[app.appid] = app
        self.apps = apps
        log.debug("library refreshed: %d installed apps", len(apps))

    def get(self, appid: int) -> InstalledApp | None:
        return self.apps.get(appid)

    def current_user(self) -> str:
        lu = self.root / "config" / "loginusers.vdf"
        if not lu.is_file():
            return ""
        try:
            return parse_loginusers(lu.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:
            return ""
