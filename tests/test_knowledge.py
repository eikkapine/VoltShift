import time

import pytest

from voltshift.knowledge import (WEIGHT_OTHER_GAME, WEIGHT_SAME_GAME,
                                 KnowledgeStore, gpu_key)

GPU = "RX_9070_XT:7550:1"
OTHER_GPU = "RX_9070_XT:7550:2"


@pytest.fixture
def store(tmp_path):
    store = KnowledgeStore(str(tmp_path / "k.db"))
    yield store
    store.close()


def test_gpu_key_separates_identical_models():
    a = gpu_key({"name": "RX 9070 XT", "deviceId": "7550", "uniqueId": 1})
    b = gpu_key({"name": "RX 9070 XT", "deviceId": "7550", "uniqueId": 2})
    assert a != b, "two identical cards must keep separate stability history"


def test_observations_round_trip(store):
    store.record_observation(GPU, "game.exe", "balanced", {"voltage_mv": -100}, 0.4)
    found = store.observations(GPU, "game.exe", "balanced")
    assert len(found) == 1
    assert found[0].config == {"voltage_mv": -100}
    assert found[0].score == pytest.approx(0.4)


def test_best_config_keeps_only_improvements(store):
    store.record_best(GPU, "game.exe", "balanced", {"voltage_mv": -100}, 0.5)
    store.record_best(GPU, "game.exe", "balanced", {"voltage_mv": -80}, 0.2)
    assert store.best_config(GPU, "game.exe", "balanced") == {"voltage_mv": -100}

    store.record_best(GPU, "game.exe", "balanced", {"voltage_mv": -120}, 0.9)
    assert store.best_config(GPU, "game.exe", "balanced") == {"voltage_mv": -120}


def test_best_config_is_scoped_per_goal_and_game(store):
    store.record_best(GPU, "a.exe", "balanced", {"voltage_mv": -100}, 0.5)
    assert store.best_config(GPU, "b.exe", "balanced") is None
    assert store.best_config(GPU, "a.exe", "efficiency") is None
    assert store.best_config(OTHER_GPU, "a.exe", "balanced") is None


def test_priors_weight_this_game_above_borrowed_ones(store):
    store.record_observation(GPU, "game.exe", "balanced", {"voltage_mv": -100}, 0.4)
    store.record_observation(GPU, "other.exe", "balanced", {"voltage_mv": -90}, 0.3)

    priors = {p.exe: p for p in store.prior_observations(GPU, "game.exe", "balanced")}
    assert priors["game.exe"].weight == pytest.approx(WEIGHT_SAME_GAME, rel=0.02)
    assert priors["other.exe"].weight == pytest.approx(WEIGHT_OTHER_GAME, rel=0.02)
    assert priors["other.exe"].weight < priors["game.exe"].weight


def test_priors_exclude_unstable_observations(store):
    store.record_observation(GPU, "game.exe", "balanced", {"voltage_mv": -190}, -10.0,
                             stable=False)
    assert store.prior_observations(GPU, "game.exe", "balanced") == []


def test_priors_do_not_cross_cards(store):
    store.record_observation(OTHER_GPU, "game.exe", "balanced", {"voltage_mv": -100}, 0.4)
    assert store.prior_observations(GPU, "game.exe", "balanced") == []


def test_unsafe_configs_are_remembered(store):
    store.mark_unsafe(GPU, {"voltage_mv": -180}, "tdr")
    assert store.unsafe_configs(GPU) == [{"voltage_mv": -180}]
    assert store.unsafe_count(GPU) == 1
    assert store.unsafe_configs(OTHER_GPU) == []


def test_frontier_keeps_the_least_aggressive_failure(store):
    # -150 failing is the binding constraint; -180 also failing adds nothing.
    store.record_failure(GPU, -180, 2900)
    store.record_failure(GPU, -150, 2950)
    assert store.frontier_limit(GPU, 2900) == -150


def test_frontier_consults_neighbouring_clock_bands(store):
    store.record_failure(GPU, -150, 2900)
    assert store.frontier_limit(GPU, 2950) == -150   # same band
    assert store.frontier_limit(GPU, 3000) == -150   # adjacent band


def test_frontier_falls_back_to_the_worst_failure_anywhere(store):
    store.record_failure(GPU, -150, 1000)
    # Nothing recorded near 3000 MHz, but a card that failed once still
    # constrains the search.
    assert store.frontier_limit(GPU, 3000) == -150


def test_frontier_is_empty_without_failures(store):
    assert store.frontier_limit(GPU, 2900) is None
    assert store.frontier(GPU) == []


def test_frontier_ignores_missing_voltages(store):
    store.record_failure(GPU, None, 2900)
    assert store.frontier_limit(GPU, 2900) is None


def test_known_games_and_forget(store):
    store.record_best(GPU, "a.exe", "balanced", {"voltage_mv": -100}, 0.5)
    store.record_observation(GPU, "a.exe", "balanced", {"voltage_mv": -100}, 0.5)
    assert [g["exe"] for g in store.known_games(GPU)] == ["a.exe"]

    store.forget_game(GPU, "a.exe")
    assert store.known_games(GPU) == []
    assert store.observations(GPU, "a.exe") == []


def test_stats_summarise_the_store(store):
    store.record_observation(GPU, "a.exe", "balanced", {"voltage_mv": -100}, 0.5)
    store.record_observation(GPU, "b.exe", "balanced", {"voltage_mv": -90}, 0.3)
    store.mark_unsafe(GPU, {"voltage_mv": -190}, "tdr")
    store.record_failure(GPU, -190, 2900)

    stats = store.stats(GPU)
    assert stats["observations"] == 2
    assert stats["games"] == 2
    assert stats["unsafe"] == 1
    assert stats["frontier_bands"] == 1


def test_age_reduces_prior_weight(store):
    store.record_observation(GPU, "game.exe", "balanced", {"voltage_mv": -100}, 0.4)
    # Backdate the row by a year; it should still be present but count much less.
    with store._lock:
        store._conn.execute("UPDATE observations SET ts = ?",
                            (time.time() - 365 * 86400,))
        store._conn.commit()
    priors = store.prior_observations(GPU, "game.exe", "balanced")
    assert priors == [] or priors[0].weight < 0.1
