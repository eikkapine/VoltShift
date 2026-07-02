"""Engine runner — the polling loop shared by the CLI and the GUI.

Owns the thread that reads metrics from the bridge, feeds the dynamic
voltage engine, applies its decisions, and records telemetry into the crash
logger. Consumers subscribe via callbacks; nothing here touches a UI.
"""

from __future__ import annotations

import threading
import time
from typing import Callable, Optional

from .bridgeclient import BridgeClient, BridgeError
from .crashlog import CrashLogger
from .engine import DynamicVoltageEngine, EngineConfig


class EngineRunner:
    def __init__(self, bridge: BridgeClient, config: EngineConfig,
                 crash_logger: Optional[CrashLogger] = None):
        self._bridge = bridge
        self._engine = DynamicVoltageEngine(config)
        self._crash_logger = crash_logger
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()

        # Callbacks (called from the runner thread).
        self.on_sample: Optional[Callable[[dict], None]] = None            # every poll
        self.on_voltage_change: Optional[Callable[[Optional[int], int], None]] = None
        self.on_log_entry: Optional[Callable[[str, str], None]] = None
        self.on_error: Optional[Callable[[str], None]] = None

    @property
    def engine(self) -> DynamicVoltageEngine:
        return self._engine

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def _log(self, msg: str, level: str = "info") -> None:
        if self.on_log_entry:
            self.on_log_entry(msg, level)

    def start(self) -> None:
        if self.running:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="voltshift-engine",
                                        daemon=True)
        self._thread.start()

    def stop(self, reset_gpu: bool = True) -> None:
        """Stop polling; by default restores AMD factory tuning."""
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=self._engine.config.poll_interval_sec + 3)
            self._thread = None
        if reset_gpu:
            try:
                self._bridge.tuning_reset()
                self._log("GPU restored to factory tuning")
            except BridgeError as exc:
                self._log(f"Factory reset failed: {exc}", "error")
        self._engine.reset()

    def _run(self) -> None:
        interval = self._engine.config.poll_interval_sec
        consecutive_errors = 0
        while not self._stop.is_set():
            started = time.monotonic()
            try:
                metrics = self._bridge.metrics()
                consecutive_errors = 0
            except BridgeError as exc:
                consecutive_errors += 1
                self._log(f"Metrics read failed: {exc}", "error")
                if consecutive_errors >= 5 and self.on_error:
                    self.on_error(f"Bridge unreachable ({exc})")
                    break
                self._stop.wait(interval)
                continue

            clock = metrics.get("clockMhz")
            if clock is not None:
                previous = self._engine.current_mv
                decision = self._engine.step(int(clock))
                if decision.applied_mv is not None:
                    try:
                        self._bridge.set_voltage_offset(decision.applied_mv)
                        self._log(f"{clock} MHz  →  {decision.applied_mv:+d} mV", "volt")
                        if self.on_voltage_change:
                            self.on_voltage_change(previous, decision.applied_mv)
                        if self._crash_logger:
                            self._crash_logger.on_voltage_changed(previous, decision.applied_mv)
                    except BridgeError as exc:
                        self._log(f"Voltage write failed: {exc}", "error")

            if self._crash_logger and clock is not None:
                self._crash_logger.record(
                    clock=int(clock),
                    voltage=self._engine.current_mv,
                    temp=metrics.get("tempC"),
                    hotspot=metrics.get("hotspotC"),
                    power=metrics.get("boardPowerW", metrics.get("powerW")),
                    fan_rpm=metrics.get("fanRpm"),
                )

            if self.on_sample:
                sample = dict(metrics)
                sample["appliedOffsetMv"] = self._engine.current_mv
                self.on_sample(sample)

            elapsed = time.monotonic() - started
            self._stop.wait(max(0.05, interval - elapsed))
