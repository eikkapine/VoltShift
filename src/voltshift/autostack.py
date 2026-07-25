"""Assembling the closed-loop stack.

Auto-tune and the adaptive governor need the same seven pieces wired
together in the same order. Building that in one place keeps the CLI and the
GUI from drifting apart, and gives tests a single seam to substitute at.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional

from .bridgeclient import BridgeClient
from .knowledge import KnowledgeStore, gpu_key
from .optimizer import Safeguard, SearchSpace, make_optimizer
from .optimizer.applier import TuningApplier
from .stability import StabilityMonitor, make_tdr_poller
from .telemetry import TelemetryHub, detect_frame_source
from .watchdog import Watchdog


@dataclass
class AutoStack:
    bridge: BridgeClient
    hub: TelemetryHub
    space: SearchSpace
    applier: TuningApplier
    knowledge: KnowledgeStore
    safeguard: Safeguard
    watchdog: Watchdog
    stability: StabilityMonitor
    gpu_key: str

    @property
    def frame_source_status(self) -> str:
        return f"{self.hub.frame_source.name}: {self.hub.frame_source.status}"

    verified: bool = False

    @property
    def tunable(self) -> bool:
        return bool(self.space)

    def new_optimizer(self, seed: Optional[int] = None):
        return make_optimizer(self.space, seed=seed)

    def verify_controls(self, force: bool = False,
                        on_log: Optional[Callable[[str, str], None]] = None):
        """Measure which knobs this card honours and narrow the space to them.

        ADLX advertises ranges for controls some hardware ignores. Testing
        each one with a small restored write is the only way to know, and it
        keeps the optimiser from wasting trials on an inert knob or crediting
        it with another knob's effect.
        """
        from . import gpuprofile

        space, checks = gpuprofile.verify_space(
            self.applier, self.space, self.knowledge, self.gpu_key,
            log=on_log, force=force)
        self.space = space
        # The safeguard and applier both close over the space, so they must be
        # rebuilt against the narrowed one rather than left pointing at the old.
        self.applier = TuningApplier(self.bridge, space, on_log)
        self.safeguard = Safeguard(space, knowledge=self.knowledge,
                                   gpu_key=self.gpu_key)
        self.verified = True
        return checks

    def close(self) -> None:
        self.hub.stop()
        self.knowledge.close()


def build(bridge: BridgeClient, on_log: Optional[Callable[[str, str], None]] = None,
          prefer_frame_source: Optional[str] = None,
          poll_interval_sec: float = 0.5,
          knowledge_path: Optional[str] = None) -> AutoStack:
    """Wire up telemetry, tuning, safety and memory for one GPU."""
    info = bridge.info()
    tuning = bridge.tuning_get()

    space = SearchSpace.from_tuning(tuning)
    applier = TuningApplier(bridge, space, on_log)
    knowledge = KnowledgeStore(knowledge_path)
    key = gpu_key(info)
    safeguard = Safeguard(space, knowledge=knowledge, gpu_key=key)
    watchdog = Watchdog(on_log=on_log)

    hub = TelemetryHub(bridge, detect_frame_source(prefer_frame_source),
                       interval_sec=poll_interval_sec)

    # The TDR poller reads the Windows Event Log, which needs pywin32; without
    # it the other four stability signals still work.
    try:
        monitor = StabilityMonitor(tdr_poller=make_tdr_poller())
    except Exception:
        monitor = StabilityMonitor()

    return AutoStack(bridge, hub, space, applier, knowledge, safeguard,
                     watchdog, monitor, key)


def recover_previous_session(stack: AutoStack) -> Optional[str]:
    """Handle a config that was live when the last session stopped existing.

    Called at startup. If the previous run left an unverified journal entry,
    that configuration is recorded as unsafe for this card and the machine is
    put back to the last configuration that was proven good.
    """
    report = stack.watchdog.check_previous_session()
    if report is None:
        return None

    stack.safeguard.mark_unsafe(report.config, "hang")
    from .optimizer.space import VOLTAGE

    stack.knowledge.record_failure(stack.gpu_key, report.config.get(VOLTAGE), None)

    if report.known_good:
        try:
            stack.applier.apply(report.known_good, skip_unchanged=False)
        except Exception:
            stack.applier.reset()
    else:
        stack.applier.reset()

    return (f"{report.summary()} Restored "
            f"{'the last known-good configuration' if report.known_good else 'factory tuning'}.")
