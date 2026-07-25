"""Frame-pacing sources.

VoltShift needs to know what the screen actually did, not just what the GPU
did — an undervolt that keeps clocks up while dropping frames is a loss, and
no hardware counter shows that. Two sources are supported:

  PresentMon (Intel, MIT)  — preferred. Per-frame present intervals for every
    process, plus GPU busy time. Bundled under `third_party/presentmon/` or
    found on PATH. Requires administrator rights (ETW), which VoltShift
    already needs for tuning writes.

  RTSS shared memory       — fallback. Reads RivaTuner Statistics Server's
    shared memory block if the user already runs RTSS or MSI Afterburner.
    Gives average frametime only, so percentile lows are coarse.

Both present the same interface, so the rest of the app never branches on
which one is live. When neither is available `NullFrameSource` reports
nothing and the optimizer falls back to hardware-only objectives.
"""

from __future__ import annotations

import csv
import ctypes
import mmap
import os
import shutil
import struct
import subprocess
import sys
import threading
import time
from collections import deque
from typing import Optional

from .. import paths
from .sample import FrameStats

# How much frame history to retain. 20 s at 240 fps is comfortably above any
# window the optimizer asks for.
MAX_FRAMES = 5000


class FrameSource:
    """Interface for anything that can report frame pacing."""

    name = "none"

    @property
    def available(self) -> bool:
        return False

    def start(self) -> None:
        pass

    def stop(self) -> None:
        pass

    def stats(self, window_sec: float = 2.0) -> Optional[FrameStats]:
        return None

    @property
    def status(self) -> str:
        return "unavailable"


class NullFrameSource(FrameSource):
    """No frame data. Everything still runs, just blind to frame pacing."""

    name = "none"

    @property
    def status(self) -> str:
        return "no frame source installed"


# ── PresentMon ────────────────────────────────────────────────────────────────

def find_presentmon() -> Optional[str]:
    """Locate a PresentMon executable: bundled, next to the app, or on PATH."""
    candidates = []
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        candidates.append(os.path.join(meipass, "PresentMon.exe"))
    base = paths.app_dir()
    candidates += [
        os.path.join(base, "third_party", "presentmon", "PresentMon.exe"),
        os.path.join(base, "_internal", "PresentMon.exe"),
        os.path.join(base, "PresentMon.exe"),
    ]
    for path in candidates:
        if os.path.isfile(path):
            return path
    # Any PresentMon-*.exe in the bundled directory (release builds are versioned).
    bundled = os.path.join(base, "third_party", "presentmon")
    if os.path.isdir(bundled):
        for entry in sorted(os.listdir(bundled)):
            if entry.lower().startswith("presentmon") and entry.lower().endswith(".exe"):
                return os.path.join(bundled, entry)
    return shutil.which("PresentMon.exe") or shutil.which("presentmon")


def _is_admin() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())  # type: ignore[attr-defined]
    except Exception:
        return False


# PresentMon 2.x capitalises its headers (MsBetweenPresents); 1.x does not
# (msBetweenPresents). Matching is case-insensitive so one mapping covers both.
_FRAMETIME_COLUMNS = ("msbetweenpresents", "frametime", "mscpubusy")
_GPUBUSY_COLUMNS = ("msgpubusy", "msgpuactive", "gputime", "msgputime")
_PROCESS_COLUMNS = ("application", "processname")
_PID_COLUMNS = ("processid", "pid")


class PresentMonSource(FrameSource):
    """Spawns PresentMon and consumes its CSV stream on a reader thread."""

    name = "presentmon"

    def __init__(self, exe_path: Optional[str] = None, process_name: Optional[str] = None):
        self._exe = exe_path or find_presentmon()
        self._process_name = process_name
        self._proc: Optional[subprocess.Popen] = None
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._lock = threading.Lock()
        # (monotonic_time, frametime_ms, gpu_busy_ms, process, pid)
        self._frames: deque = deque(maxlen=MAX_FRAMES)
        self._error: Optional[str] = None
        self._started_at = 0.0

    @property
    def available(self) -> bool:
        return bool(self._exe) and os.path.isfile(self._exe)

    @property
    def status(self) -> str:
        if not self.available:
            return "PresentMon not found (run scripts/fetch_presentmon.ps1)"
        if self._error:
            return f"PresentMon error: {self._error}"
        if self._proc is None:
            return "stopped"
        if self._proc.poll() is not None:
            return f"PresentMon exited (code {self._proc.poll()})"
        with self._lock:
            count = len(self._frames)
        return f"running ({count} frames buffered)"

    def _argv(self, v1: bool = False) -> list[str]:
        dash = "-" if v1 else "--"
        argv = [self._exe, f"{dash}output_stdout", f"{dash}stop_existing_session"]
        argv.append(f"{dash}no_top" if v1 else f"{dash}no_console_stats")
        if self._process_name:
            argv += [f"{dash}process_name", self._process_name]
        return argv

    def start(self) -> None:
        if self._proc is not None and self._proc.poll() is None:
            return
        if not self.available:
            self._error = "executable not found"
            return
        if not _is_admin():
            self._error = "administrator rights required for ETW tracing"
            return

        self._stop.clear()
        self._error = None
        self._started_at = time.monotonic()
        try:
            self._proc = subprocess.Popen(
                self._argv(),
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except OSError as exc:
            self._error = str(exc)
            self._proc = None
            return

        self._thread = threading.Thread(target=self._reader, name="voltshift-presentmon",
                                        daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        proc, self._proc = self._proc, None
        if proc is not None:
            try:
                proc.terminate()
                proc.wait(timeout=3)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass
        if self._thread:
            self._thread.join(timeout=2)
            self._thread = None

    def _reader(self) -> None:
        proc = self._proc
        if proc is None or proc.stdout is None:
            return
        header: Optional[dict[str, int]] = None
        try:
            for line in proc.stdout:
                if self._stop.is_set():
                    break
                line = line.strip()
                if not line:
                    continue
                fields = next(csv.reader([line]), None)
                if not fields:
                    continue
                if header is None:
                    header = {name.strip().lower(): i for i, name in enumerate(fields)}
                    if not any(c in header for c in _FRAMETIME_COLUMNS):
                        # Not a header we understand; keep looking (some builds
                        # print a banner line before the CSV header).
                        header = None
                    continue
                self._ingest(header, fields)
        except Exception as exc:  # reader dies with the process; surface why
            self._error = str(exc)

    def _ingest(self, header: dict[str, int], fields: list[str]) -> None:
        def get(names: tuple[str, ...]) -> Optional[str]:
            for candidate in names:
                index = header.get(candidate)
                if index is not None and index < len(fields):
                    value = fields[index].strip()
                    if value and value != "NA":
                        return value
            return None

        raw_ft = get(_FRAMETIME_COLUMNS)
        if raw_ft is None:
            return
        try:
            frametime = float(raw_ft)
        except ValueError:
            return
        if frametime <= 0:
            return

        gpu_busy = None
        raw_busy = get(_GPUBUSY_COLUMNS)
        if raw_busy is not None:
            try:
                gpu_busy = float(raw_busy)
            except ValueError:
                gpu_busy = None

        process = get(_PROCESS_COLUMNS) or "unknown"
        try:
            pid = int(get(_PID_COLUMNS) or 0)
        except ValueError:
            pid = 0

        with self._lock:
            self._frames.append((time.monotonic(), frametime, gpu_busy, process, pid))

    def stats(self, window_sec: float = 2.0) -> Optional[FrameStats]:
        cutoff = time.monotonic() - window_sec
        with self._lock:
            recent = [f for f in self._frames if f[0] >= cutoff]
        if len(recent) < 2:
            return None

        # Several processes can present at once (game + overlay + browser).
        # Attribute the window to whichever presented the most frames.
        counts: dict[tuple[str, int], int] = {}
        for _, _, _, process, pid in recent:
            key = (process, pid)
            counts[key] = counts.get(key, 0) + 1
        process, pid = max(counts, key=counts.__getitem__)

        frametimes = [f[1] for f in recent if (f[3], f[4]) == (process, pid)]
        busy = [f[2] for f in recent if (f[3], f[4]) == (process, pid) and f[2] is not None]
        return FrameStats.from_frametimes(frametimes, process, pid, self.name, busy or None)


# ── RTSS shared memory ────────────────────────────────────────────────────────

RTSS_SHARED_MEMORY = "RTSSSharedMemoryV2"
_RTSS_SIGNATURE = 0x53535452  # 'RTSS' little-endian


class RtssFrameSource(FrameSource):
    """Reads RivaTuner Statistics Server's shared memory block.

    RTSS publishes, per hooked application, a frame counter and a time window;
    dividing gives average FPS. There is no per-frame history, so percentile
    lows are derived from RTSS's own frametime field and are approximate.
    """

    name = "rtss"

    def __init__(self) -> None:
        self._mm: Optional[mmap.mmap] = None
        self._error: Optional[str] = None
        self._history: deque = deque(maxlen=600)  # (t, fps, frametime_ms, name, pid)
        self._lock = threading.Lock()
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()

    def _open(self) -> Optional[mmap.mmap]:
        if os.name != "nt":
            return None
        try:
            return mmap.mmap(-1, 0x10000, RTSS_SHARED_MEMORY, access=mmap.ACCESS_READ)
        except OSError:
            return None

    @property
    def available(self) -> bool:
        mm = self._mm or self._open()
        if mm is None:
            return False
        try:
            signature, = struct.unpack_from("<I", mm, 0)
        except Exception:
            return False
        finally:
            if mm is not self._mm:
                mm.close()
        return signature == _RTSS_SIGNATURE

    @property
    def status(self) -> str:
        if not self.available:
            return "RTSS not running"
        if self._error:
            return f"RTSS error: {self._error}"
        return "running"

    def start(self) -> None:
        if self._thread is not None:
            return
        self._mm = self._open()
        if self._mm is None:
            self._error = "shared memory not present"
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._poll, name="voltshift-rtss", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)
            self._thread = None
        if self._mm:
            try:
                self._mm.close()
            except Exception:
                pass
            self._mm = None

    def _read_entries(self) -> list[tuple[str, int, float, float]]:
        """Return (name, pid, fps, frametime_ms) for every live RTSS entry."""
        mm = self._mm
        if mm is None:
            return []
        try:
            # RTSS_SHARED_MEMORY header: signature, version, appEntrySize,
            # appArrOffset, appArrSize, then per-entry records.
            (signature, version, app_entry_size, app_arr_offset,
             app_arr_size) = struct.unpack_from("<IIIII", mm, 0)
            if signature != _RTSS_SIGNATURE or app_entry_size == 0:
                return []

            entries = []
            for i in range(app_arr_size):
                base = app_arr_offset + i * app_entry_size
                if base + 268 > len(mm):
                    break
                pid, = struct.unpack_from("<I", mm, base)
                if pid == 0:
                    continue
                raw_name = mm[base + 4:base + 264]
                name = raw_name.split(b"\x00", 1)[0].decode("ascii", "replace")
                # RTSSAppEntry: dwProcessID, szName[MAX_PATH], dwFlags,
                # dwTime0, dwTime1, dwFrames, dwFrameTime (microseconds).
                flags, time0, time1, frames, frametime_us = struct.unpack_from(
                    "<IIIII", mm, base + 264)
                span_ms = time1 - time0
                if span_ms <= 0 or frames == 0:
                    continue
                fps = frames * 1000.0 / span_ms
                frametime_ms = frametime_us / 1000.0 if frametime_us else (
                    1000.0 / fps if fps > 0 else 0.0)
                entries.append((os.path.basename(name), pid, fps, frametime_ms))
            return entries
        except Exception as exc:
            self._error = str(exc)
            return []

    def _poll(self) -> None:
        while not self._stop.wait(0.2):
            for name, pid, fps, frametime_ms in self._read_entries():
                with self._lock:
                    self._history.append((time.monotonic(), fps, frametime_ms, name, pid))

    def stats(self, window_sec: float = 2.0) -> Optional[FrameStats]:
        cutoff = time.monotonic() - window_sec
        with self._lock:
            recent = [h for h in self._history if h[0] >= cutoff]
        if not recent:
            return None

        counts: dict[tuple[str, int], int] = {}
        for _, _, _, name, pid in recent:
            key = (name, pid)
            counts[key] = counts.get(key, 0) + 1
        name, pid = max(counts, key=counts.__getitem__)
        rows = [r for r in recent if (r[3], r[4]) == (name, pid)]
        # RTSS reports an average per poll, so synthesise a frametime series
        # from those averages. Percentile lows are therefore smoothed.
        frametimes = [r[2] for r in rows if r[2] > 0]
        return FrameStats.from_frametimes(frametimes, name, pid, self.name)


# ── selection ─────────────────────────────────────────────────────────────────

def detect_frame_source(prefer: Optional[str] = None) -> FrameSource:
    """Pick the best available frame source.

    PresentMon first (per-frame data, works with every game), then RTSS, then
    a null source. `prefer` forces a specific backend by name.
    """
    builders = {
        "presentmon": PresentMonSource,
        "rtss": RtssFrameSource,
        "none": NullFrameSource,
    }
    if prefer:
        builder = builders.get(prefer.lower())
        if builder is not None:
            source = builder()
            if source.available or prefer.lower() == "none":
                return source

    presentmon = PresentMonSource()
    if presentmon.available:
        return presentmon
    rtss = RtssFrameSource()
    if rtss.available:
        return rtss
    return NullFrameSource()
