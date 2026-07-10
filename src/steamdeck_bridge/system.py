"""Device sensors (battery, dock, session mode, steam state) and actions
(launch/close game, power control). Linux-only paths are guarded so the
module imports cleanly on any OS for testing."""

from __future__ import annotations

import logging
import os
import signal
import subprocess
from pathlib import Path

from .config import ActionsConfig
from .models import DeviceState, SessionMode
from .steam.paths import steam_pid_file

log = logging.getLogger(__name__)

POWER_SUPPLY = Path("/sys/class/power_supply")
DRM = Path("/sys/class/drm")


# -- sensors ----------------------------------------------------------------

def read_battery(base: Path = POWER_SUPPLY) -> tuple[int | None, str, bool | None]:
    """Return (percent, state, on_ac). Enumerates supplies so Deck (BAT1),
    Ally, and Legion Go all work."""
    percent: int | None = None
    state = ""
    on_ac: bool | None = None
    if not base.is_dir():
        return percent, state, on_ac
    for supply in sorted(base.iterdir()):
        try:
            kind = (supply / "type").read_text().strip()
        except OSError:
            continue
        if kind == "Battery" and percent is None:
            try:
                percent = int((supply / "capacity").read_text().strip())
                state = (supply / "status").read_text().strip().lower()
            except (OSError, ValueError):
                pass
        elif kind == "Mains":
            try:
                online = (supply / "online").read_text().strip() == "1"
                on_ac = online if on_ac is None else (on_ac or online)
            except OSError:
                pass
    return percent, state, on_ac


def count_connected_displays(base: Path = DRM) -> int:
    count = 0
    if not base.is_dir():
        return 0
    for conn in base.glob("card*-*"):
        try:
            if (conn / "status").read_text().strip() == "connected":
                count += 1
        except OSError:
            continue
    return count


def _proc_names(proc: Path = Path("/proc")) -> set[str]:
    names: set[str] = set()
    try:
        for p in proc.iterdir():
            if not p.name.isdigit():
                continue
            try:
                names.add((p / "comm").read_text().strip())
            except OSError:
                continue
    except OSError:
        pass
    return names


def detect_session_mode() -> SessionMode:
    names = _proc_names()
    if not names:
        return SessionMode.UNKNOWN
    if "gamescope-session" in names or "gamescope" in names:
        return SessionMode.GAMING
    if names & {"plasmashell", "gnome-shell", "kwin_wayland", "kwin_x11"}:
        return SessionMode.DESKTOP
    return SessionMode.UNKNOWN


def steam_is_running(home: Path | None = None) -> bool:
    pid_file = steam_pid_file(home)
    try:
        pid = int(pid_file.read_text().strip())
        comm = Path(f"/proc/{pid}/comm").read_text().strip()
        return comm.startswith("steam")
    except (OSError, ValueError):
        return False


def read_device_state(steam_user: str = "", home: Path | None = None) -> DeviceState:
    percent, batt_state, on_ac = read_battery()
    displays = count_connected_displays()
    mode = detect_session_mode()
    # Heuristic: handheld panel is 1 display; more than one connected connector
    # while on AC = docked. On battery, external displays still count.
    docked = displays > 1 if displays else None
    return DeviceState(
        mode=mode,
        awake=True,  # if we're running, we're awake; suspend gaps show up as unavailability
        battery_percent=percent,
        battery_state=batt_state,
        on_ac=on_ac,
        docked=docked,
        steam_running=steam_is_running(home),
        steam_user=steam_user,
    )


# -- actions ------------------------------------------------------------------

SHORTCUT_BIT = 0x80000000


def shortcut_rungameid(appid_u32: int) -> int:
    """64-bit steam://rungameid value for a non-Steam shortcut AppID."""
    return (appid_u32 << 32) | 0x02000000


class Actions:
    """Fixed allowlist of device actions. Nothing here ever executes
    caller-supplied strings as shell."""

    def __init__(self, config: ActionsConfig):
        self.config = config

    def _run(self, argv: list[str]) -> bool:
        try:
            subprocess.Popen(
                argv,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            return True
        except OSError as e:
            log.error("action %s failed: %s", argv[0], e)
            return False

    def _steam_url(self, url: str) -> bool:
        return self._run(["steam", url])

    # launch / close ---------------------------------------------------------

    def launch_game(self, appid: int) -> bool:
        if not (self.config.enabled and self.config.allow_launch):
            return False
        appid_u32 = appid & 0xFFFFFFFF
        rungameid = shortcut_rungameid(appid_u32) if appid_u32 & SHORTCUT_BIT else appid_u32
        return self._steam_url(f"steam://rungameid/{rungameid}")

    def close_game(self, pid: int | None) -> bool:
        """SIGTERM to the game's process group; Steam's reaper cleans up."""
        if not (self.config.enabled and self.config.allow_launch) or not pid:
            return False
        try:
            os.killpg(os.getpgid(pid), signal.SIGTERM)
            return True
        except (OSError, PermissionError) as e:
            log.error("close_game(%s) failed: %s", pid, e)
            try:
                os.kill(pid, signal.SIGTERM)
                return True
            except OSError:
                return False

    def switch_game(self, appid: int, current_pid: int | None) -> bool:
        # Steam brings the new game forward; closing the old one first avoids
        # two heavyweight titles fighting for the GPU.
        self.close_game(current_pid)
        return self.launch_game(appid)

    # steam / session ----------------------------------------------------------

    def restart_steam(self) -> bool:
        if not (self.config.enabled and self.config.allow_steam_restart):
            return False
        # In Gaming Mode the session supervisor relaunches Steam automatically;
        # in Desktop Mode users relaunch from the menu, so also try starting it.
        ok = self._steam_url("steam://exit")
        self._run(["bash", "-c", "sleep 8 && exec steam -silent"])
        return ok

    def restart_gamescope(self) -> bool:
        """Restarting Steam inside a gamescope session restarts the whole
        session (gamescope supervises steam)."""
        return self.restart_steam()

    # power ----------------------------------------------------------------------

    def suspend(self) -> bool:
        return self._power(["systemctl", "suspend"])

    def shutdown(self) -> bool:
        return self._power(["systemctl", "poweroff"])

    def reboot(self) -> bool:
        return self._power(["systemctl", "reboot"])

    def _power(self, argv: list[str]) -> bool:
        if not (self.config.enabled and self.config.allow_power):
            return False
        return self._run(argv)
