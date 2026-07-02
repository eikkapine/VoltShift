import pytest

from voltshift.engine import (
    MAX_OFFSET_MV,
    MIN_OFFSET_MV,
    DynamicVoltageEngine,
    EngineConfig,
    Threshold,
)


def make_engine(hysteresis=2):
    config = EngineConfig(
        poll_interval_sec=0.5,
        hysteresis_count=hysteresis,
        idle_offset_mv=-100,
        thresholds=[
            Threshold(3200, -120),
            Threshold(3100, -160),
            Threshold(3000, -140),
        ],
    )
    return DynamicVoltageEngine(config)


class TestTargetOffset:
    def test_highest_threshold_wins(self):
        engine = make_engine()
        assert engine.target_offset(3250) == -120

    def test_first_match_from_top(self):
        engine = make_engine()
        assert engine.target_offset(3142) == -160

    def test_exact_boundary_matches(self):
        engine = make_engine()
        assert engine.target_offset(3200) == -120
        assert engine.target_offset(3100) == -160
        assert engine.target_offset(3000) == -140

    def test_below_all_thresholds_uses_idle(self):
        engine = make_engine()
        assert engine.target_offset(2999) == -100
        assert engine.target_offset(0) == -100

    def test_unsorted_threshold_input(self):
        config = EngineConfig(thresholds=[
            Threshold(3000, -140),
            Threshold(3200, -120),
            Threshold(3100, -160),
        ])
        engine = DynamicVoltageEngine(config)
        assert engine.target_offset(3150) == -160
        assert engine.target_offset(3300) == -120


class TestHysteresis:
    def test_commit_after_n_consecutive_reads(self):
        engine = make_engine(hysteresis=2)
        d1 = engine.step(3142)  # target -160, pending 1/2
        assert d1.applied_mv is None
        assert d1.pending_count == 1
        d2 = engine.step(3140)  # pending 2/2 -> commit
        assert d2.applied_mv == -160
        assert engine.current_mv == -160

    def test_target_flip_resets_counter(self):
        engine = make_engine(hysteresis=2)
        engine.step(2999)  # target idle -100, pending 1/2
        engine.step(3003)  # target -140, counter reset to 1
        d = engine.step(2997)  # target -100 again, reset to 1
        assert d.applied_mv is None
        d = engine.step(2995)  # -100 pending 2/2 -> commit
        assert d.applied_mv == -100

    def test_stable_target_no_rewrite(self):
        engine = make_engine(hysteresis=1)
        d = engine.step(3142)
        assert d.applied_mv == -160
        # Same range again: no new write.
        d = engine.step(3150)
        assert d.applied_mv is None
        assert engine.current_mv == -160

    def test_hysteresis_one_commits_immediately(self):
        engine = make_engine(hysteresis=1)
        assert engine.step(3250).applied_mv == -120

    def test_reset_forgets_state(self):
        engine = make_engine(hysteresis=1)
        engine.step(3142)
        engine.reset()
        assert engine.current_mv is None
        # Same clock now triggers a fresh commit.
        assert engine.step(3142).applied_mv == -160


class TestConfigSafety:
    def test_positive_offsets_clamped_to_zero(self):
        config = EngineConfig(idle_offset_mv=50,
                              thresholds=[Threshold(3000, 100)]).clamped()
        assert config.idle_offset_mv == MAX_OFFSET_MV
        assert config.thresholds[0].offset_mv == MAX_OFFSET_MV

    def test_below_hardware_floor_clamped(self):
        config = EngineConfig(idle_offset_mv=-500,
                              thresholds=[Threshold(3000, -999)]).clamped()
        assert config.idle_offset_mv == MIN_OFFSET_MV
        assert config.thresholds[0].offset_mv == MIN_OFFSET_MV

    def test_hysteresis_minimum_one(self):
        assert EngineConfig(hysteresis_count=0).clamped().hysteresis_count == 1

    def test_roundtrip_dict(self):
        config = EngineConfig(poll_interval_sec=0.75, hysteresis_count=3,
                              idle_offset_mv=-90,
                              thresholds=[Threshold(3100, -150)])
        restored = EngineConfig.from_dict(config.to_dict())
        assert restored.poll_interval_sec == 0.75
        assert restored.hysteresis_count == 3
        assert restored.idle_offset_mv == -90
        assert restored.thresholds == [Threshold(3100, -150)]

    def test_from_dict_clamps_unsafe_values(self):
        restored = EngineConfig.from_dict({
            "poll_interval_sec": 0.01,
            "hysteresis_count": 0,
            "idle_offset_mv": 40,
            "thresholds": [{"clock_mhz": 3000, "offset_mv": -400}],
        })
        assert restored.poll_interval_sec == pytest.approx(0.1)
        assert restored.hysteresis_count == 1
        assert restored.idle_offset_mv == 0
        assert restored.thresholds[0].offset_mv == MIN_OFFSET_MV
