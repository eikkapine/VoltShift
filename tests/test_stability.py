import pytest

from voltshift.stability import (SEVERITY_CRITICAL, SPIKE_TRAIN_COUNT,
                                 StabilityMonitor)
from voltshift.telemetry.sample import FrameStats, Sample


def _frames(frametimes, pid=100):
    return FrameStats.from_frametimes(frametimes, "game.exe", pid, "test")


def _spiky_sample(t, pid=100):
    # One very long frame among short ones drives p99 far above the average.
    return Sample(t=t, clock_mhz=2900, gpu_util_pct=98.0,
                  frames=_frames([8.0] * 40 + [200.0], pid))


def _clean_sample(t, clock=2900, util=98.0, pid=100):
    return Sample(t=t, clock_mhz=clock, gpu_util_pct=util,
                  frames=_frames([8.0] * 40, pid))


def test_clean_samples_raise_nothing():
    monitor = StabilityMonitor()
    monitor.note_change({"voltage_mv": -100}, t=0.0)
    for i in range(10):
        assert monitor.feed(_clean_sample(float(i))) == []


def test_spike_train_fires_only_inside_the_settle_window():
    monitor = StabilityMonitor()
    monitor.note_change({"voltage_mv": -150}, t=0.0)
    fired = []
    for i in range(SPIKE_TRAIN_COUNT):
        fired = monitor.feed(_spiky_sample(0.1 * i))
    assert fired, "a burst of spikes right after a change should be reported"
    assert fired[0].kind == "spike_train"
    assert fired[0].severity == SEVERITY_CRITICAL


def test_spikes_long_after_a_change_are_ignored():
    # The same spikes, but 60 seconds later — that is gameplay, not the
    # settings write, and must not be attributed to it.
    monitor = StabilityMonitor()
    monitor.note_change({"voltage_mv": -150}, t=0.0)
    for i in range(SPIKE_TRAIN_COUNT + 2):
        assert monitor.feed(_spiky_sample(60.0 + i)) == []


def test_clock_cliff_needs_load():
    monitor = StabilityMonitor()
    monitor.set_reference_clock(2900)

    # Low clock while idle is normal power management, not a fault.
    assert monitor.feed(_clean_sample(1.0, clock=800, util=5.0)) == []

    fired = monitor.feed(_clean_sample(2.0, clock=1500, util=95.0))
    assert fired and fired[0].kind == "clock_cliff"


def test_clock_cliff_ignores_small_dips():
    monitor = StabilityMonitor()
    monitor.set_reference_clock(2900)
    assert monitor.feed(_clean_sample(1.0, clock=2700, util=95.0)) == []


def test_process_death_detected_after_the_process_was_seen():
    monitor = StabilityMonitor()
    monitor.watch_process(100)
    monitor.note_change({"voltage_mv": -160}, t=0.0)
    monitor.feed(_clean_sample(0.1, pid=100))          # seen presenting
    fired = monitor.feed(_clean_sample(0.2, pid=999))  # someone else now
    assert fired and fired[0].kind == "process_death"


def test_process_death_not_reported_before_it_was_ever_seen():
    monitor = StabilityMonitor()
    monitor.watch_process(100)
    monitor.note_change({}, t=0.0)
    assert monitor.feed(_clean_sample(0.1, pid=999)) == []


def test_tdr_poller_reports_only_increases():
    counts = iter([2, 2, 5])
    monitor = StabilityMonitor(tdr_poller=lambda: next(counts))
    assert monitor.feed(_clean_sample(1.0)) == []   # establishes the baseline
    assert monitor.feed(_clean_sample(2.0)) == []   # unchanged
    fired = monitor.feed(_clean_sample(3.0))
    assert fired and fired[0].kind == "tdr"


def test_events_accumulate_and_reset():
    monitor = StabilityMonitor()
    monitor.set_reference_clock(2900)
    monitor.feed(_clean_sample(1.0, clock=1000, util=99.0))
    assert len(monitor.critical_events) == 1
    monitor.reset()
    assert monitor.events == []


def test_on_event_callback_fires():
    seen = []
    monitor = StabilityMonitor()
    monitor.on_event = seen.append
    monitor.set_reference_clock(2900)
    monitor.feed(_clean_sample(1.0, clock=1000, util=99.0))
    assert len(seen) == 1
    assert seen[0].critical
