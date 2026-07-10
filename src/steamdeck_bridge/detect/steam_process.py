"""Detect running Steam games by scanning /proc for Steam's reaper wrapper.

Steam launches every title (native, Proton, non-Steam shortcuts) as:
    .../reaper SteamLaunch AppId=<appid> -- <game command>
which makes `/proc/*/cmdline` a reliable, mode-independent detection source.
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)

_APPID_RE = re.compile(r"AppId=(\d+)")


@dataclass(slots=True)
class RunningApp:
    appid: int
    pid: int
    started_at: float          # epoch seconds
    launch_command: str = ""   # command after the '--' separator


def _boot_time() -> float:
    try:
        with open("/proc/stat", encoding="ascii") as f:
            for line in f:
                if line.startswith("btime"):
                    return float(line.split()[1])
    except OSError:
        pass
    return 0.0


def _proc_start_epoch(pid: int, btime: float) -> float:
    """Process start time from /proc/<pid>/stat field 22 (clock ticks after boot)."""
    try:
        stat = Path(f"/proc/{pid}/stat").read_text(encoding="ascii", errors="replace")
        # comm can contain spaces/parens; fields resume after the last ')'
        fields = stat[stat.rindex(")") + 2:].split()
        ticks = int(fields[19])  # field 22 overall
        hz = os.sysconf("SC_CLK_TCK")
        return btime + ticks / hz
    except (OSError, ValueError, IndexError):
        return 0.0


def scan_running_apps(proc: Path = Path("/proc")) -> list[RunningApp]:
    """All reaper-launched Steam apps currently running, oldest first."""
    apps: dict[int, RunningApp] = {}
    btime = _boot_time()
    try:
        pids = [int(p.name) for p in proc.iterdir() if p.name.isdigit()]
    except OSError:
        return []

    for pid in pids:
        try:
            raw = (proc / str(pid) / "cmdline").read_bytes()
        except OSError:
            continue
        if b"SteamLaunch" not in raw or b"AppId=" not in raw:
            continue
        argv = [a.decode("utf-8", "replace") for a in raw.split(b"\0") if a]
        m = _APPID_RE.search(" ".join(argv[:4]))
        if not m:
            continue
        appid = int(m.group(1))
        launch_command = ""
        if "--" in argv:
            launch_command = " ".join(argv[argv.index("--") + 1:])
        started = _proc_start_epoch(pid, btime) if btime else 0.0
        existing = apps.get(appid)
        if existing is None or (started and started < existing.started_at):
            apps[appid] = RunningApp(
                appid=appid, pid=pid, started_at=started, launch_command=launch_command
            )
    return sorted(apps.values(), key=lambda a: a.started_at)


class SteamProcessDetector:
    name = "steam_process"

    def running(self) -> RunningApp | None:
        """Most recently started reaper app (the foreground one in practice)."""
        apps = scan_running_apps()
        return apps[-1] if apps else None

    def by_appid(self, appid: int) -> RunningApp | None:
        for app in scan_running_apps():
            if app.appid == appid or (app.appid & 0xFFFFFFFF) == (appid & 0xFFFFFFFF):
                return app
        return None
