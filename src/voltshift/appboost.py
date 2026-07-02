"""Per-app boost — apply a tuning boost while chosen games/apps are running.

A watcher thread polls the process list (psutil). While any watched
executable is alive, the boost values (power limit and optionally core max
clock) are applied; when the last one exits, the previous values are
restored. VoltShift's answer to RadeonTuner's PowerBoost, implemented
host-side instead of in the driver bridge.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Callable, Optional

import psutil

from .bridgeclient import BridgeClient, BridgeError


@dataclass
class BoostConfig:
    apps: list[str] = field(default_factory=list)  # exe names, case-insensitive
    power_limit_pct: Optional[int] = None
    max_clock_mhz: Optional[int] = None
    poll_interval_sec: float = 3.0

    def to_dict(self) -> dict:
        return {
            "apps": self.apps,
            "power_limit_pct": self.power_limit_pct,
            "max_clock_mhz": self.max_clock_mhz,
            "poll_interval_sec": self.poll_interval_sec,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "BoostConfig":
        return cls(
            apps=[str(a) for a in data.get("apps", [])],
            power_limit_pct=data.get("power_limit_pct"),
            max_clock_mhz=data.get("max_clock_mhz"),
            poll_interval_sec=float(data.get("poll_interval_sec", 3.0)),
        )


def running_watched_apps(watched: list[str]) -> set[str]:
    """Which of the watched exe names currently have a live process."""
    targets = {name.lower() for name in watched if name.strip()}
    if not targets:
        return set()
    found = set()
    for proc in psutil.process_iter(["name"]):
        try:
            name = (proc.info["name"] or "").lower()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
        if name in targets:
            found.add(name)
    return found


class AppBoostWatcher:
    def __init__(self, bridge: BridgeClient, config: BoostConfig):
        self._bridge = bridge
        self.config = config
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._boosted = False
        self._saved_power: Optional[int] = None
        self._saved_max_clock: Optional[int] = None
        self.on_log_entry: Optional[Callable[[str, str], None]] = None

    def _log(self, msg: str, level: str = "info") -> None:
        if self.on_log_entry:
            self.on_log_entry(msg, level)

    @property
    def active(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    @property
    def boosted(self) -> bool:
        return self._boosted

    def start(self) -> None:
        if self.active:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="voltshift-appboost",
                                        daemon=True)
        self._thread.start()
        self._log(f"App boost watching: {', '.join(self.config.apps) or '(no apps)'}")

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=self.config.poll_interval_sec + 2)
            self._thread = None
        if self._boosted:
            self._restore()

    def _run(self) -> None:
        while not self._stop.wait(self.config.poll_interval_sec):
            try:
                running = running_watched_apps(self.config.apps)
                if running and not self._boosted:
                    self._apply_boost(running)
                elif not running and self._boosted:
                    self._restore()
            except BridgeError as exc:
                self._log(f"App boost bridge error: {exc}", "error")

    def _apply_boost(self, running: set[str]) -> None:
        tuning = self._bridge.tuning_get()
        if self.config.power_limit_pct is not None:
            self._saved_power = tuning.get("power", {}).get("powerLimit")
            self._bridge.set_power_limit(self.config.power_limit_pct)
        if self.config.max_clock_mhz is not None:
            self._saved_max_clock = tuning.get("gfx", {}).get("maxFreqMhz")
            self._bridge.set_core_clocks(max_mhz=self.config.max_clock_mhz)
        self._boosted = True
        self._log(f"Boost ON ({', '.join(sorted(running))})", "volt")

    def _restore(self) -> None:
        try:
            if self._saved_power is not None:
                self._bridge.set_power_limit(self._saved_power)
            if self._saved_max_clock is not None:
                self._bridge.set_core_clocks(max_mhz=self._saved_max_clock)
            self._log("Boost OFF — watched apps closed", "volt")
        except BridgeError as exc:
            self._log(f"Boost restore failed: {exc}", "error")
        finally:
            self._boosted = False
            self._saved_power = None
            self._saved_max_clock = None
