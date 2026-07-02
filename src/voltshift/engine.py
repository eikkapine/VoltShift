"""Dynamic voltage engine — VoltShift's identity feature.

Maps the live core clock to a voltage offset through user-defined thresholds,
with hysteresis so a clock oscillating around a boundary doesn't cause
voltage flicker. Pure logic, no I/O: the runner (CLI/GUI) feeds it clock
readings and applies whatever offsets it decides on.

Matching: thresholds are evaluated highest clock first; the first threshold
whose clock the reading meets or exceeds wins. Below all thresholds the idle
offset applies.

Hysteresis: a new target must be observed `hysteresis_count` consecutive
polls before it is committed. Any change of the pending target resets the
counter.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

# The bridge enforces these too; the engine clamps early so the UI and
# saved configs can never even request an unsafe value.
MIN_OFFSET_MV = -200
MAX_OFFSET_MV = 0


@dataclass(frozen=True)
class Threshold:
    clock_mhz: int
    offset_mv: int


@dataclass
class EngineConfig:
    poll_interval_sec: float = 0.5
    hysteresis_count: int = 2
    idle_offset_mv: int = -100
    thresholds: list[Threshold] = field(default_factory=lambda: [
        Threshold(3200, -120),
        Threshold(3100, -160),
        Threshold(3000, -140),
    ])

    def clamped(self) -> "EngineConfig":
        """Copy with every offset forced into the safe hardware window."""
        def clamp(mv: int) -> int:
            return max(MIN_OFFSET_MV, min(MAX_OFFSET_MV, mv))

        return EngineConfig(
            poll_interval_sec=max(0.1, self.poll_interval_sec),
            hysteresis_count=max(1, self.hysteresis_count),
            idle_offset_mv=clamp(self.idle_offset_mv),
            thresholds=[Threshold(t.clock_mhz, clamp(t.offset_mv)) for t in self.thresholds],
        )

    def to_dict(self) -> dict:
        return {
            "poll_interval_sec": self.poll_interval_sec,
            "hysteresis_count": self.hysteresis_count,
            "idle_offset_mv": self.idle_offset_mv,
            "thresholds": [
                {"clock_mhz": t.clock_mhz, "offset_mv": t.offset_mv} for t in self.thresholds
            ],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "EngineConfig":
        return cls(
            poll_interval_sec=float(data.get("poll_interval_sec", 0.5)),
            hysteresis_count=int(data.get("hysteresis_count", 2)),
            idle_offset_mv=int(data.get("idle_offset_mv", -100)),
            thresholds=[
                Threshold(int(t["clock_mhz"]), int(t["offset_mv"]))
                for t in data.get("thresholds", [])
            ],
        ).clamped()


@dataclass(frozen=True)
class EngineDecision:
    """Outcome of one poll step."""
    clock_mhz: int
    target_mv: int          # what the thresholds say the offset should be
    applied_mv: Optional[int]  # offset to write now, or None (no change yet)
    pending_count: int      # consecutive polls the target has been pending
    current_mv: Optional[int]  # engine's view of the applied offset


class DynamicVoltageEngine:
    def __init__(self, config: EngineConfig):
        self._config = config.clamped()
        self._sorted = sorted(self._config.thresholds,
                              key=lambda t: t.clock_mhz, reverse=True)
        self.current_mv: Optional[int] = None  # None until the first commit
        self._pending_mv: Optional[int] = None
        self._pending_count = 0

    @property
    def config(self) -> EngineConfig:
        return self._config

    def target_offset(self, clock_mhz: int) -> int:
        for t in self._sorted:
            if clock_mhz >= t.clock_mhz:
                return t.offset_mv
        return self._config.idle_offset_mv

    def step(self, clock_mhz: int) -> EngineDecision:
        """Feed one clock reading; returns the decision for this poll."""
        target = self.target_offset(clock_mhz)

        if target == self.current_mv:
            self._pending_mv = None
            self._pending_count = 0
            return EngineDecision(clock_mhz, target, None, 0, self.current_mv)

        if target == self._pending_mv:
            self._pending_count += 1
        else:
            self._pending_mv = target
            self._pending_count = 1

        if self._pending_count >= self._config.hysteresis_count:
            self.current_mv = target
            self._pending_mv = None
            self._pending_count = 0
            return EngineDecision(clock_mhz, target, target, 0, self.current_mv)

        return EngineDecision(clock_mhz, target, None, self._pending_count, self.current_mv)

    def reset(self) -> None:
        """Forget all state (after a factory reset or engine stop)."""
        self.current_mv = None
        self._pending_mv = None
        self._pending_count = 0
