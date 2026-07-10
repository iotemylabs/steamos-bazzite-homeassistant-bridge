"""Artwork resolution chain:

  1. Steam librarycache      (installed Steam games)
  2. userdata grid overrides (only local source for non-Steam shortcuts)
  3. Heroic store cache art URLs
  4. SteamGridDB API v2      (optional, needs API key)
  5. Steam CDN               (uninstalled Steam games)
  6. Local disk cache of anything fetched remotely
"""

from __future__ import annotations

import logging
from pathlib import Path
from urllib.parse import quote

import aiohttp

from .config import ArtworkConfig

log = logging.getLogger(__name__)

ArtKind = str  # capsule | cover | header | hero | logo | icon | background

# kind -> librarycache filename stems (checked in order)
LIBRARYCACHE_STEMS: dict[str, list[str]] = {
    "capsule": ["library_600x900"],
    "cover": ["library_600x900"],
    "header": ["header"],
    "hero": ["library_hero"],
    "background": ["library_hero", "page_bg_generated_v6b"],
    "logo": ["logo"],
    "icon": ["icon"],
}

# kind -> grid-folder suffixes ("" = bare appid.png = vertical capsule)
GRID_SUFFIXES: dict[str, list[str]] = {
    "capsule": ["p", ""],
    "cover": ["p", ""],
    "header": [""],
    "hero": ["_hero"],
    "background": ["_hero"],
    "logo": ["_logo"],
    "icon": ["_icon"],
}

STEAM_CDN = "https://steamcdn-a.akamaihd.net/steam/apps"
CDN_FILES: dict[str, str] = {
    "capsule": "library_600x900_2x.jpg",
    "cover": "library_600x900_2x.jpg",
    "header": "header.jpg",
    "hero": "library_hero.jpg",
    "background": "library_hero.jpg",
    "logo": "logo.png",
}

SGDB_ENDPOINTS: dict[str, str] = {
    "capsule": "grids", "cover": "grids",
    "hero": "heroes", "background": "heroes",
    "logo": "logos", "icon": "icons", "header": "grids",
}

_EXTS = (".jpg", ".png", ".jpeg", ".webp", ".ico")


def find_librarycache_art(librarycache: Path, appid: int, kind: ArtKind) -> Path | None:
    stems = LIBRARYCACHE_STEMS.get(kind, [])
    for stem in stems:
        for ext in _EXTS:
            # Older layout: librarycache/<appid>_<stem><ext>
            p = librarycache / f"{appid}_{stem}{ext}"
            if p.is_file():
                return p
        # Newer layout (2024+): librarycache/<appid>/<hash>/<stem><ext> or
        # librarycache/<appid>/<stem><ext>
        appdir = librarycache / str(appid)
        if appdir.is_dir():
            hits = sorted(appdir.rglob(f"{stem}.*"))
            for hit in hits:
                if hit.suffix.lower() in _EXTS:
                    return hit
    return None


def find_grid_art(grid_dir: Path, appid: int, kind: ArtKind) -> Path | None:
    for suffix in GRID_SUFFIXES.get(kind, []):
        for ext in _EXTS:
            p = grid_dir / f"{appid}{suffix}{ext}"
            if p.is_file():
                return p
    return None


class ArtworkResolver:
    def __init__(
        self,
        config: ArtworkConfig,
        steam_root: Path | None,
        userdata: list[Path],
    ):
        self.config = config
        self.steam_root = steam_root
        self.userdata = userdata
        self.cache_dir = Path(config.cache_dir).expanduser()
        self._session: aiohttp.ClientSession | None = None

    async def close(self) -> None:
        if self._session:
            await self._session.close()
            self._session = None

    def _http(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=15)
            )
        return self._session

    # -- local sources -------------------------------------------------------

    def resolve_local(self, appid: int, kind: ArtKind) -> Path | None:
        # grid overrides first: they're deliberate user/tool choices and the
        # only art non-Steam shortcuts have.
        for user_dir in self.userdata:
            hit = find_grid_art(user_dir / "config" / "grid", appid, kind)
            if hit:
                return hit
        if self.steam_root:
            hit = find_librarycache_art(
                self.steam_root / "appcache" / "librarycache", appid, kind
            )
            if hit:
                return hit
        return self._cached(appid, kind)

    def _cached(self, appid: int, kind: ArtKind) -> Path | None:
        if not self.cache_dir.is_dir():
            return None
        for ext in _EXTS:
            p = self.cache_dir / f"{appid}_{kind}{ext}"
            if p.is_file():
                return p
        return None

    # -- remote sources -----------------------------------------------------

    async def resolve(self, appid: int, kind: ArtKind, title: str = "") -> Path | None:
        """Full chain. Returns a local file path (possibly freshly cached)."""
        hit = self.resolve_local(appid, kind)
        if hit or not self.config.allow_remote:
            return hit

        url: str | None = None
        # Steam CDN only makes sense for real Steam AppIDs.
        if not appid & 0x80000000 and kind in CDN_FILES:
            url = f"{STEAM_CDN}/{appid}/{CDN_FILES[kind]}"
            path = await self._download(appid, kind, url)
            if path:
                return path

        if self.config.steamgriddb_api_key and title:
            url = await self._steamgriddb_url(appid, kind, title)
            if url:
                return await self._download(appid, kind, url)
        return None

    async def _steamgriddb_url(self, appid: int, kind: ArtKind, title: str) -> str | None:
        endpoint = SGDB_ENDPOINTS.get(kind)
        if not endpoint:
            return None
        headers = {"Authorization": f"Bearer {self.config.steamgriddb_api_key}"}
        base = "https://www.steamgriddb.com/api/v2"
        try:
            http = self._http()
            if not appid & 0x80000000:
                # Real Steam AppID: direct lookup
                async with http.get(
                    f"{base}/{endpoint}/steam/{appid}", headers=headers
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        items = data.get("data") or []
                        if items:
                            return items[0].get("url")
            # Fall back to title search
            async with http.get(
                f"{base}/search/autocomplete/{quote(title)}",
                headers=headers,
            ) as resp:
                if resp.status != 200:
                    return None
                games = (await resp.json()).get("data") or []
            if not games:
                return None
            game_id = games[0]["id"]
            async with http.get(
                f"{base}/{endpoint}/game/{game_id}", headers=headers
            ) as resp:
                if resp.status != 200:
                    return None
                items = (await resp.json()).get("data") or []
                return items[0].get("url") if items else None
        except (aiohttp.ClientError, KeyError, TimeoutError) as e:
            log.debug("steamgriddb lookup failed for %s: %s", title, e)
            return None

    async def _download(self, appid: int, kind: ArtKind, url: str) -> Path | None:
        try:
            http = self._http()
            async with http.get(url) as resp:
                if resp.status != 200:
                    return None
                content = await resp.read()
                ctype = resp.headers.get("Content-Type", "")
        except (aiohttp.ClientError, TimeoutError) as e:
            log.debug("artwork download failed %s: %s", url, e)
            return None
        ext = ".png" if "png" in ctype else ".webp" if "webp" in ctype else ".jpg"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        path = self.cache_dir / f"{appid}_{kind}{ext}"
        path.write_bytes(content)
        return path
