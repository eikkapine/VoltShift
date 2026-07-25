"""Which application is the user actually playing?

Two signals, in order of trust:

  1. The process presenting frames. If a frame source is live, whatever is
     pushing frames to the screen *is* the game — no heuristics required.
  2. The foreground window's process, for when no frame source is installed.

Both are filtered against a shell/browser denylist so VoltShift never decides
that Explorer is a game worth tuning for.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional

import psutil

try:
    import win32gui  # type: ignore
    import win32process  # type: ignore

    _WIN32_OK = True
except ImportError:
    _WIN32_OK = False

# Processes that present frames or hold the foreground but are never the
# workload we tune for.
NON_GAME_PROCESSES = {
    "explorer.exe", "dwm.exe", "searchhost.exe", "shellexperiencehost.exe",
    "startmenuexperiencehost.exe", "textinputhost.exe", "sihost.exe",
    "applicationframehost.exe", "systemsettings.exe", "taskmgr.exe",
    "chrome.exe", "msedge.exe", "firefox.exe", "brave.exe", "opera.exe",
    "discord.exe", "spotify.exe", "code.exe", "devenv.exe",
    "windowsterminal.exe", "cmd.exe", "powershell.exe", "pwsh.exe",
    "voltshift.exe", "voltshift_gui.exe", "python.exe", "pythonw.exe",
    "rtss.exe", "presentmon.exe", "obs64.exe", "nvcontainer.exe",
    "radeonsoftware.exe", "amdow.exe",
}


@dataclass(frozen=True)
class GameProcess:
    pid: int
    exe: str          # lower-case basename, e.g. "cyberpunk2077.exe"
    name: str         # friendly name for display
    source: str       # "frames" or "foreground"

    @property
    def key(self) -> str:
        return self.exe


def _normalise(exe_or_path: str) -> str:
    return os.path.basename(exe_or_path or "").strip().lower()


def is_game_like(exe: str) -> bool:
    exe = _normalise(exe)
    if not exe or not exe.endswith(".exe"):
        return False
    return exe not in NON_GAME_PROCESSES


def foreground_process() -> Optional[GameProcess]:
    """The process owning the foreground window, if it looks like an app."""
    if not _WIN32_OK:
        return None
    try:
        hwnd = win32gui.GetForegroundWindow()
        if not hwnd:
            return None
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        if not pid:
            return None
        proc = psutil.Process(pid)
        exe = _normalise(proc.name())
    except (psutil.NoSuchProcess, psutil.AccessDenied, Exception):
        return None
    if not is_game_like(exe):
        return None
    return GameProcess(pid=pid, exe=exe, name=exe[:-4], source="foreground")


def presenting_process(frame_source) -> Optional[GameProcess]:
    """The process currently presenting frames, per the frame source."""
    try:
        stats = frame_source.stats(3.0)
    except Exception:
        return None
    if stats is None:
        return None
    exe = _normalise(stats.process)
    if not is_game_like(exe):
        return None
    return GameProcess(pid=stats.pid, exe=exe, name=exe[:-4], source="frames")


def detect_game(frame_source=None) -> Optional[GameProcess]:
    """Best guess at the workload to tune for, frames first."""
    if frame_source is not None:
        found = presenting_process(frame_source)
        if found is not None:
            return found
    return foreground_process()


def process_alive(pid: int) -> bool:
    try:
        return psutil.pid_exists(pid) and psutil.Process(pid).is_running()
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return False
