"""Writing a configuration to the GPU, and reading one back.

Separated from the optimiser so the search can be tested without hardware,
and so there is exactly one place that understands ADLX's quirks.

The quirk that matters: `tuning.setVoltageOffset` is absolute on MGT2_1
(RDNA 4 — the value written *is* the offset) but relative on MGT2, where the
bridge adds the argument to the current voltage. A closed-loop optimiser that
re-applies "the same" configuration every few seconds would walk the voltage
steadily downward on an MGT2 card until it fell over. `TuningApplier` always
works in absolute terms and converts on the way out.
"""

from __future__ import annotations

import threading
from typing import Callable, Optional

from ..bridgeclient import BridgeClient, BridgeError
from .space import (MAX_CLOCK, MIN_CLOCK, POWER_LIMIT, VOLTAGE, VRAM_CLOCK,
                    SearchSpace)


class TuningApplier:
    """Applies canonical configuration dicts to the GPU."""

    def __init__(self, bridge: BridgeClient, space: SearchSpace,
                 on_log: Optional[Callable[[str, str], None]] = None):
        self._bridge = bridge
        self._space = space
        self._lock = threading.Lock()
        self._on_log = on_log
        self._last_applied: Optional[dict] = None

    def _log(self, message: str, level: str = "info") -> None:
        if self._on_log:
            self._on_log(message, level)

    # ── reading ──────────────────────────────────────────────────────────────

    def read_current(self) -> dict:
        """Current values for every knob in the space, as absolute values."""
        tuning = self._bridge.tuning_get()
        gfx = tuning.get("gfx", {})
        vram = tuning.get("vram", {})
        power = tuning.get("power", {})
        raw = {
            VOLTAGE: gfx.get("voltageMv"),
            MAX_CLOCK: gfx.get("maxFreqMhz"),
            MIN_CLOCK: gfx.get("minFreqMhz"),
            VRAM_CLOCK: vram.get("maxFreqMhz"),
            POWER_LIMIT: power.get("powerLimit"),
        }
        return {k.name: raw[k.name] for k in self._space.knobs
                if raw.get(k.name) is not None}

    def read_defaults(self) -> dict:
        """The card's factory values, where ADLX reports them."""
        tuning = self._bridge.tuning_get()
        gfx_defaults = tuning.get("gfx", {}).get("defaults", {})
        power_default = tuning.get("power", {}).get("powerLimitDefault")
        raw = {
            VOLTAGE: gfx_defaults.get("voltageMv"),
            MAX_CLOCK: gfx_defaults.get("maxFreqMhz"),
            MIN_CLOCK: gfx_defaults.get("minFreqMhz"),
            POWER_LIMIT: power_default,
        }
        return {k: v for k, v in raw.items() if v is not None}

    @property
    def last_applied(self) -> Optional[dict]:
        return dict(self._last_applied) if self._last_applied else None

    # ── writing ──────────────────────────────────────────────────────────────

    def apply(self, config: dict, skip_unchanged: bool = True) -> list[str]:
        """Write a configuration. Returns a log of what happened.

        Clocks go before voltage: raising a clock ceiling at an already-low
        voltage is the ordering most likely to be unstable, so the voltage
        write lands last and the card spends no time in the risky in-between.
        """
        applied: list[str] = []
        with self._lock:
            previous = self._last_applied or {}

            def changed(name: str) -> bool:
                if name not in config or config[name] is None:
                    return False
                return not skip_unchanged or previous.get(name) != config[name]

            if changed(MIN_CLOCK) or changed(MAX_CLOCK):
                try:
                    self._bridge.set_core_clocks(config.get(MIN_CLOCK),
                                                 config.get(MAX_CLOCK))
                    applied.append("core clocks")
                except BridgeError as exc:
                    self._log(f"core clock write failed: {exc}", "error")

            if changed(VRAM_CLOCK):
                try:
                    self._bridge.set_vram_max(config[VRAM_CLOCK])
                    applied.append("vram clock")
                except BridgeError as exc:
                    self._log(f"vram clock write failed: {exc}", "error")

            if changed(POWER_LIMIT):
                try:
                    self._bridge.set_power_limit(config[POWER_LIMIT])
                    applied.append("power limit")
                except BridgeError as exc:
                    self._log(f"power limit write failed: {exc}", "error")

            if changed(VOLTAGE):
                try:
                    self._write_voltage(config[VOLTAGE])
                    applied.append("voltage")
                except BridgeError as exc:
                    self._log(f"voltage write failed: {exc}", "error")

            merged = dict(previous)
            merged.update({k: v for k, v in config.items() if v is not None})
            self._last_applied = merged
        return applied

    def _write_voltage(self, target_mv: int) -> None:
        """Write an absolute voltage value, whatever the interface wants.

        On MGT2_1 the bridge treats the argument as the value to set, so it
        goes straight through. On MGT2 the bridge adds it to the current
        voltage, so the difference is what must be sent.
        """
        if self._space.voltage_is_offset:
            self._bridge.set_voltage_offset(int(target_mv))
            return
        current = self._bridge.tuning_get().get("gfx", {}).get("voltageMv")
        if current is None:
            raise BridgeError("cannot read current voltage to compute a delta")
        delta = int(target_mv) - int(current)
        if delta == 0:
            return
        if delta > 0:
            # The bridge refuses positive arguments as a safety rule, so
            # raising voltage on MGT2 means resetting and reapplying from the
            # factory baseline rather than nudging upward.
            self._bridge.tuning_reset()
            self._last_applied = None
            baseline = self._bridge.tuning_get().get("gfx", {}).get("voltageMv")
            if baseline is None:
                raise BridgeError("cannot read baseline voltage after reset")
            delta = int(target_mv) - int(baseline)
            if delta >= 0:
                return
        self._bridge.set_voltage_offset(delta)

    def reset(self) -> list[str]:
        """Restore AMD factory tuning and forget what we thought was applied."""
        with self._lock:
            try:
                self._bridge.tuning_reset()
                self._last_applied = None
                return ["factory reset"]
            except BridgeError as exc:
                self._log(f"factory reset failed: {exc}", "error")
                return []


class RecordingApplier:
    """In-memory applier for tests and dry runs."""

    def __init__(self, initial: Optional[dict] = None):
        self.history: list[dict] = []
        self.current = dict(initial or {})
        self.reset_count = 0

    def read_current(self) -> dict:
        return dict(self.current)

    def read_defaults(self) -> dict:
        return dict(self.current)

    def apply(self, config: dict, skip_unchanged: bool = True) -> list[str]:
        self.current.update({k: v for k, v in config.items() if v is not None})
        self.history.append(dict(self.current))
        return list(config.keys())

    def reset(self) -> list[str]:
        self.reset_count += 1
        return ["factory reset"]

    @property
    def last_applied(self) -> Optional[dict]:
        return dict(self.current) if self.current else None
