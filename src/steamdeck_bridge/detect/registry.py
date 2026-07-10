"""Legacy fallback: RunningAppID from ~/.steam/registry.vdf.

Broken (stuck at 0) on many post-UI-rewrite Steam clients — see
https://github.com/ValveSoftware/steam-for-linux/issues/9672 — so this is only
consulted when every other detector comes up empty, and 0 is never trusted.
"""

from __future__ import annotations

import re
from pathlib import Path

_RUNNING_RE = re.compile(r'"RunningAppID"\s+"(\d+)"', re.IGNORECASE)


def running_appid_from_registry(text: str) -> int | None:
    m = _RUNNING_RE.search(text)
    if not m:
        return None
    appid = int(m.group(1))
    return appid or None


class RegistryDetector:
    name = "registry"

    def __init__(self, registry_path: Path):
        self.path = registry_path

    def running_appid(self) -> int | None:
        try:
            return running_appid_from_registry(
                self.path.read_text(encoding="utf-8", errors="replace")
            )
        except OSError:
            return None
