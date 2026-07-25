"""Stability monitor — the thing that notices an undervolt has gone wrong.

An unstable GPU rarely announces itself politely. It shows up as one of five
signatures, and VoltShift watches for all of them:

  TDR            The display driver reset. Windows logs event 4101; every
                 process with a GPU context dies, so this is often only
                 visible after the fact.
  Spike train    A burst of very long frames time-locked to a settings write.
                 Gameplay produces stutters too, but not reliably within two
                 seconds of every change.
  Clock cliff    Core clock collapses while utilisation and power stay high —
                 the driver clamping itself after an error it recovered from.
  Process death  The measured application vanished right after a write.
  Hard hang      No event at all: the machine stopped. Detected next boot by
                 the watchdog finding an unverified journal entry.

A monitor instance watches one tuning session. `note_change()` opens a settle
window; `feed()` is called with every telemetry sample and returns any events
that fired. Severity 3 means stop and revert now.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Optional

from .telemetry.sample import Sample

# How long after a settings write a fault is still attributed to that write.
SETTLE_WINDOW_SEC = 6.0
# A frame this many times the window median counts as a spike.
SPIKE_MULTIPLE = 3.0
# Spikes needed inside the settle window before it counts as a spike train.
SPIKE_TRAIN_COUNT = 3
# Clock must fall below this fraction of the reference to count as a cliff.
CLOCK_CLIFF_FRACTION = 0.72
# ...and the GPU must still be loaded this hard for the cliff to be suspicious.
CLIFF_MIN_UTIL_PCT = 70.0

SEVERITY_INFO = 1
SEVERITY_WARN = 2
SEVERITY_CRITICAL = 3


@dataclass(frozen=True)
class StabilityEvent:
    kind: str
    severity: int
    detail: str
    t: float = field(default_factory=time.monotonic)
    config: Optional[dict] = None

    @property
    def critical(self) -> bool:
        return self.severity >= SEVERITY_CRITICAL

    def __str__(self) -> str:
        return f"[{self.kind}] {self.detail}"


class StabilityMonitor:
    """Watches a telemetry stream for signs that the current config is unsafe."""

    def __init__(self, tdr_poller: Optional[Callable[[], int]] = None):
        self._lock = threading.Lock()
        # None means "no change recorded yet". A sentinel of 0.0 would be
        # ambiguous with a caller whose clock legitimately starts at zero.
        self._last_change_t: Optional[float] = None
        self._current_config: Optional[dict] = None
        self._reference_clock: Optional[float] = None
        self._spikes_since_change = 0
        self._events: list[StabilityEvent] = []
        self._watched_pid: Optional[int] = None
        self._saw_watched_pid = False
        self._tdr_poller = tdr_poller
        self._tdr_baseline: Optional[int] = None
        self.on_event: Optional[Callable[[StabilityEvent], None]] = None

    # ── session control ──────────────────────────────────────────────────────

    def note_change(self, config: Optional[dict] = None,
                    t: Optional[float] = None) -> None:
        """Mark that settings were just written; opens the attribution window.

        `t` must be on the same clock as the samples fed in afterwards — it
        defaults to `time.monotonic()`, which is what `TelemetryHub` stamps
        samples with.
        """
        with self._lock:
            self._last_change_t = time.monotonic() if t is None else t
            self._current_config = config
            self._spikes_since_change = 0

    def set_reference_clock(self, clock_mhz: Optional[float]) -> None:
        """Record the clock considered normal for the current workload."""
        with self._lock:
            self._reference_clock = clock_mhz

    def watch_process(self, pid: Optional[int]) -> None:
        """Track a process so its disappearance counts as a stability event."""
        with self._lock:
            self._watched_pid = pid
            self._saw_watched_pid = False

    def reset(self) -> None:
        with self._lock:
            self._last_change_t = None
            self._spikes_since_change = 0
            self._events.clear()
            self._reference_clock = None
            self._saw_watched_pid = False

    @property
    def events(self) -> list[StabilityEvent]:
        with self._lock:
            return list(self._events)

    @property
    def critical_events(self) -> list[StabilityEvent]:
        return [e for e in self.events if e.critical]

    # ── detection ────────────────────────────────────────────────────────────

    def feed(self, sample: Sample) -> list[StabilityEvent]:
        """Process one telemetry sample; returns events raised by this sample."""
        fired: list[StabilityEvent] = []
        with self._lock:
            # A sample only belongs to a change if it was taken *after* it.
            # Without the lower bound, a reading older than the write (a
            # buffered sample, or a caller using its own clock) would be
            # blamed on a change that had not happened yet.
            in_settle = (self._last_change_t is not None
                         and 0 <= sample.t - self._last_change_t <= SETTLE_WINDOW_SEC)
            config = self._current_config
            reference = self._reference_clock

        fired += self._check_spike_train(sample, in_settle, config)
        fired += self._check_clock_cliff(sample, reference, config)
        fired += self._check_process_death(sample, in_settle, config)
        fired += self._check_tdr(config)

        if fired:
            with self._lock:
                self._events.extend(fired)
            if self.on_event:
                for event in fired:
                    self.on_event(event)
        return fired

    def _check_spike_train(self, sample: Sample, in_settle: bool,
                           config: Optional[dict]) -> list[StabilityEvent]:
        if not in_settle or sample.frames is None:
            return []
        stats = sample.frames
        # A window whose p99 is a large multiple of its average means a few
        # frames took far longer than the rest.
        if stats.frametime_ms_avg <= 0:
            return []
        ratio = stats.frametime_ms_p99 / stats.frametime_ms_avg
        if ratio < SPIKE_MULTIPLE:
            return []

        with self._lock:
            self._spikes_since_change += 1
            count = self._spikes_since_change
        if count < SPIKE_TRAIN_COUNT:
            return []
        return [StabilityEvent(
            "spike_train", SEVERITY_CRITICAL,
            f"{count} frametime spikes within {SETTLE_WINDOW_SEC:.0f}s of the change "
            f"(p99 {stats.frametime_ms_p99:.1f}ms vs avg {stats.frametime_ms_avg:.1f}ms)",
            config=config)]

    def _check_clock_cliff(self, sample: Sample, reference: Optional[float],
                           config: Optional[dict]) -> list[StabilityEvent]:
        if reference is None or not reference or sample.clock_mhz is None:
            return []
        if sample.gpu_util_pct is None or sample.gpu_util_pct < CLIFF_MIN_UTIL_PCT:
            return []
        if sample.clock_mhz >= reference * CLOCK_CLIFF_FRACTION:
            return []
        return [StabilityEvent(
            "clock_cliff", SEVERITY_CRITICAL,
            f"core clock fell to {sample.clock_mhz} MHz "
            f"(reference {reference:.0f} MHz) at {sample.gpu_util_pct:.0f}% load",
            config=config)]

    def _check_process_death(self, sample: Sample, in_settle: bool,
                             config: Optional[dict]) -> list[StabilityEvent]:
        with self._lock:
            watched = self._watched_pid
            seen = self._saw_watched_pid
            if watched is not None and sample.frames is not None \
                    and sample.frames.pid == watched:
                self._saw_watched_pid = True
                return []
        if watched is None or not seen or not in_settle:
            return []
        if sample.frames is not None and sample.frames.pid != watched:
            return [StabilityEvent(
                "process_death", SEVERITY_CRITICAL,
                f"watched process {watched} stopped presenting within the settle window",
                config=config)]
        return []

    def _check_tdr(self, config: Optional[dict]) -> list[StabilityEvent]:
        if self._tdr_poller is None:
            return []
        try:
            count = self._tdr_poller()
        except Exception:
            return []
        if self._tdr_baseline is None:
            self._tdr_baseline = count
            return []
        if count <= self._tdr_baseline:
            return []
        delta = count - self._tdr_baseline
        self._tdr_baseline = count
        return [StabilityEvent(
            "tdr", SEVERITY_CRITICAL,
            f"{delta} new display driver reset event(s) in the Windows log",
            config=config)]


def make_tdr_poller(lookback_hours: int = 1) -> Callable[[], int]:
    """Build a poller that counts recent TDR events in the Windows Event Log.

    Reuses the crash logger's Event Log query so there is one implementation
    of the XPath fallbacks. Returns a callable that yields a running count;
    the monitor only cares that the number went up.
    """
    from .crashlog import _query_events  # local import: pywin32 is optional

    def poll() -> int:
        try:
            events = _query_events("System", 4101, max_events=50)
            return len(events)
        except Exception:
            return 0

    return poll
