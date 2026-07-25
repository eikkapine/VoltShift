import pytest

from voltshift import paths, watchdog
from voltshift.watchdog import GuardedApply, Watchdog


@pytest.fixture(autouse=True)
def isolated_app_dir(tmp_path, monkeypatch):
    """Point the watchdog's on-disk state at a scratch directory."""
    monkeypatch.setattr(paths, "app_dir", lambda: str(tmp_path))
    monkeypatch.setattr(watchdog.paths, "app_dir", lambda: str(tmp_path))
    return tmp_path


def test_clean_start_reports_no_recovery():
    assert Watchdog().check_previous_session() is None


def test_journal_then_verify_promotes_to_known_good():
    dog = Watchdog(probation_sec=0.0)
    dog.journal({"voltage_mv": -120}, "test change")
    assert dog.pending == {"voltage_mv": -120}
    assert dog.verify() is True
    assert dog.known_good() == {"voltage_mv": -120}
    assert dog.pending is None


def test_verify_waits_for_probation():
    dog = Watchdog(probation_sec=60.0)
    dog.journal({"voltage_mv": -120})
    assert dog.verify() is False
    assert dog.probation_remaining > 0
    assert dog.verify(force=True) is True


def test_unverified_journal_is_found_by_the_next_session():
    # Simulates a hang: journal written, machine dies, new process starts.
    dying = Watchdog(probation_sec=60.0)
    dying.journal({"voltage_mv": -200}, "aggressive undervolt")

    report = Watchdog().check_previous_session()
    assert report is not None
    assert report.config == {"voltage_mv": -200}
    assert "aggressive undervolt" in report.reason
    assert "unsafe" in report.summary()


def test_recovery_is_reported_once_then_cleared():
    Watchdog(probation_sec=60.0).journal({"voltage_mv": -200})
    assert Watchdog().check_previous_session() is not None
    assert Watchdog().check_previous_session() is None


def test_recovery_offers_the_last_known_good_config():
    settled = Watchdog(probation_sec=0.0)
    settled.set_known_good({"voltage_mv": -50})
    Watchdog(probation_sec=60.0).journal({"voltage_mv": -200})

    report = Watchdog().check_previous_session()
    assert report.known_good == {"voltage_mv": -50}


def test_abandoned_journal_is_not_blamed_later():
    dog = Watchdog(probation_sec=60.0)
    dog.journal({"voltage_mv": -200})
    dog.abandon()
    assert Watchdog().check_previous_session() is None


def test_guarded_apply_reverts_on_exception():
    dog = Watchdog(probation_sec=60.0)
    applied = []

    with pytest.raises(RuntimeError):
        with GuardedApply(dog, {"voltage_mv": -180}, {"voltage_mv": 0},
                          applied.append, "risky"):
            raise RuntimeError("driver said no")

    assert applied == [{"voltage_mv": -180}, {"voltage_mv": 0}]
    # The revert cleared the journal, so the next launch blames nothing.
    assert Watchdog().check_previous_session() is None


def test_guarded_apply_leaves_journal_pending_on_success():
    dog = Watchdog(probation_sec=60.0)
    applied = []
    with GuardedApply(dog, {"voltage_mv": -100}, {"voltage_mv": 0}, applied.append):
        pass
    assert applied == [{"voltage_mv": -100}]
    assert dog.pending == {"voltage_mv": -100}
