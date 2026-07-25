import time

import pytest

from voltshift.adaptive import (PHASE_CONFIRM_TICKS, AdaptiveGovernor, Phase,
                                ProbeBudget, classify)
from voltshift.optimizer import RecordingApplier, Safeguard, SearchSpace
from voltshift.optimizer.space import VOLTAGE
from voltshift.telemetry.sample import FrameStats, Sample

TUNING = {
    "gfx": {
        "interface": "MGT2_1", "voltageMv": 0, "maxFreqMhz": 3100,
        "voltageRange": {"min": -200, "max": 0, "step": 5},
        "maxFreqRange": {"min": 2000, "max": 3400, "step": 10},
    },
}


def _sample(util, fps=None, stutter_frames=0, t=0.0):
    frames = None
    if fps is not None:
        frametimes = [1000.0 / fps] * 30 + [300.0] * stutter_frames
        frames = FrameStats.from_frametimes(frametimes, "game.exe", 100, "test")
    return Sample(t=t, gpu_util_pct=util, clock_mhz=2900, board_w=250.0,
                  hotspot_c=70.0, frames=frames)


# ── phase classification ──────────────────────────────────────────────────────

def test_idle_when_the_gpu_is_asleep():
    assert classify(_sample(3.0), []) == Phase.IDLE
    assert classify(Sample(t=0.0), []) == Phase.IDLE


def test_heavy_under_full_load():
    assert classify(_sample(97.0, fps=90.0), []) == Phase.HEAVY


def test_light_under_partial_load():
    assert classify(_sample(50.0, fps=90.0), []) == Phase.LIGHT


def test_menu_is_high_fps_at_low_load():
    assert classify(_sample(30.0, fps=600.0), []) == Phase.MENU


def test_loading_is_thrashing_load_with_broken_pacing():
    recent = [_sample(u, fps=40.0, stutter_frames=8)
              for u in (10.0, 95.0, 12.0, 90.0, 15.0, 88.0)]
    assert classify(recent[-1], recent) == Phase.LOADING


def test_steady_load_is_not_mistaken_for_loading():
    recent = [_sample(u, fps=90.0) for u in (95.0, 96.0, 94.0, 97.0, 95.0, 96.0)]
    assert classify(recent[-1], recent) == Phase.HEAVY


def test_only_gameplay_phases_are_tunable():
    assert Phase.HEAVY.tunable and Phase.LIGHT.tunable
    assert not Phase.LOADING.tunable
    assert not Phase.MENU.tunable
    assert not Phase.IDLE.tunable


# ── probe budget ──────────────────────────────────────────────────────────────

def test_budget_blocks_until_the_interval_has_passed():
    budget = ProbeBudget(min_interval_sec=100.0)
    budget.last_probe_t = 50.0
    assert not budget.ready(100.0)
    assert budget.ready(160.0)


def test_budget_is_exhausted_by_its_probe_count():
    budget = ProbeBudget(max_probes=2, min_interval_sec=0.0)
    budget.spent = 2
    assert budget.exhausted
    assert not budget.ready(1000.0)


def test_a_single_fault_spends_the_whole_budget():
    budget = ProbeBudget(max_probes=10, min_interval_sec=0.0)
    budget.failures = 1
    assert budget.exhausted, "one real fault must stop further experimentation"


def test_zero_budget_never_probes():
    budget = ProbeBudget(max_probes=0)
    assert budget.exhausted
    assert not budget.ready(1e9)


# ── governor ──────────────────────────────────────────────────────────────────

class FakeHub:
    def __init__(self, sample=None):
        self.latest = sample or _sample(97.0, fps=90.0)
        self.subscribers = []
        self.frame_source = None

    def subscribe(self, callback):
        self.subscribers.append(callback)
        return lambda: self.subscribers.remove(callback)

    def history(self, seconds=None):
        return [self.latest] * 6

    def set_applied_offset(self, mv):
        pass


def _governor(knowledge=None, budget=None, initial=None):
    space = SearchSpace.from_tuning(TUNING)
    applier = RecordingApplier(initial or {VOLTAGE: 0, "max_clock_mhz": 3100})
    hub = FakeHub()
    guard = Safeguard(space, knowledge=knowledge, gpu_key="sim")
    governor = AdaptiveGovernor(hub, applier, space, guard, knowledge=knowledge,
                                gpu_key="sim", goal="balanced",
                                budget=budget or ProbeBudget(max_probes=0),
                                tick_sec=0.02)
    return governor, applier, hub, guard


def test_governor_starts_and_stops_cleanly():
    governor, applier, _, _ = _governor()
    governor.start()
    assert governor.running
    time.sleep(0.1)
    governor.stop()
    assert not governor.running
    assert applier.current[VOLTAGE] == 0


def test_stopping_restores_the_desktop_configuration():
    governor, applier, _, _ = _governor()
    governor.start()
    time.sleep(0.05)
    applier.apply({VOLTAGE: -80})
    governor.stop(restore=True)
    assert applier.current[VOLTAGE] == 0


def test_phase_changes_need_confirmation():
    governor, _, hub, _ = _governor()
    governor._phase = Phase.IDLE
    heavy = _sample(97.0, fps=90.0)
    for _ in range(PHASE_CONFIRM_TICKS - 1):
        governor._track_phase(heavy)
        assert governor._phase == Phase.IDLE, "one reading must not flip the phase"
    governor._track_phase(heavy)
    assert governor._phase == Phase.HEAVY


def test_a_flapping_signal_does_not_change_phase():
    governor, _, _, _ = _governor()
    governor._phase = Phase.IDLE
    for i in range(10):
        governor._track_phase(_sample(97.0 if i % 2 else 3.0, fps=90.0))
    assert governor._phase == Phase.IDLE


def test_ramp_moves_one_capped_step_at_a_time():
    governor, applier, _, _ = _governor()
    governor._desktop_config = {VOLTAGE: 0}
    governor._target = {VOLTAGE: -200, "max_clock_mhz": 3100}

    governor._ramp_toward_target()
    assert applier.current[VOLTAGE] == -40   # the per-step cap, not -200

    governor._ramp_toward_target()
    assert applier.current[VOLTAGE] == -80


def test_ramp_stops_once_the_target_is_reached():
    governor, applier, _, _ = _governor()
    governor._target = {VOLTAGE: -20, "max_clock_mhz": 3100}
    governor._ramp_toward_target()
    assert applier.current[VOLTAGE] == -20
    assert governor._target is None


def test_ramp_refuses_a_target_the_safeguard_rejects():
    knowledge_stub = type("K", (), {
        "unsafe_configs": lambda self, gpu: [],
        "frontier_limit": lambda self, gpu, clock: -50,
    })()
    governor, applier, _, _ = _governor(knowledge=knowledge_stub)
    governor._target = {VOLTAGE: -40, "max_clock_mhz": 3100}
    governor._ramp_toward_target()
    assert applier.current[VOLTAGE] == 0, "below the learned frontier must not apply"
    assert governor._target is None


def test_a_critical_event_reverts_and_records():
    from voltshift.stability import SEVERITY_CRITICAL, StabilityEvent

    marked = []

    class Knowledge:
        def unsafe_configs(self, gpu):
            return []

        def frontier_limit(self, gpu, clock):
            return None

        def mark_unsafe(self, gpu, config, kind):
            marked.append((config, kind))

        def record_failure(self, gpu, mv, clock):
            marked.append(("failure", mv))

    governor, applier, _, _ = _governor(knowledge=Knowledge())
    governor._desktop_config = {VOLTAGE: 0}
    applier.apply({VOLTAGE: -120})

    governor._on_stability_event(
        StabilityEvent("tdr", SEVERITY_CRITICAL, "driver reset"))

    assert applier.current[VOLTAGE] == 0, "a fault must revert immediately"
    assert governor._budget.failures == 1
    assert any(entry[0] == "failure" for entry in marked)


def test_non_critical_events_are_ignored():
    from voltshift.stability import SEVERITY_INFO, StabilityEvent

    governor, applier, _, _ = _governor()
    governor._desktop_config = {VOLTAGE: 0}
    applier.apply({VOLTAGE: -60})
    governor._on_stability_event(StabilityEvent("noise", SEVERITY_INFO, "hmm"))
    assert applier.current[VOLTAGE] == -60


def test_probe_proposal_is_a_single_small_step():
    governor, applier, _, _ = _governor(budget=ProbeBudget(max_probes=4))
    current = {VOLTAGE: 0, "max_clock_mhz": 3100}
    proposal = governor._propose_probe(current)
    assert proposal is not None
    changed = [k for k in current if proposal[k] != current[k]]
    assert len(changed) == 1, "a probe changes exactly one knob"
    knob = governor._space.knob(changed[0])
    assert abs(proposal[changed[0]] - current[changed[0]]) <= knob.max_delta


def test_probe_proposal_respects_the_tabu_set():
    governor, _, _, guard = _governor(budget=ProbeBudget(max_probes=4))
    current = {VOLTAGE: 0, "max_clock_mhz": 3100}
    for _ in range(40):
        proposal = governor._propose_probe(current)
        if proposal is None:
            break
        assert guard.check(proposal, current)
        guard.mark_unsafe(proposal, "test")


def test_status_reports_the_governors_view():
    governor, _, _, _ = _governor(budget=ProbeBudget(max_probes=5))
    status = governor.status()
    assert status.phase == Phase.IDLE
    assert status.probes_left == 5
    assert status.game is None
