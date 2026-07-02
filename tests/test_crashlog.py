import time

from voltshift.crashlog import analyse_crash


def _point(ts, clock, volt, temp=60.0, hot=75.0):
    return {"ts": ts, "clock_mhz": clock, "voltage_mv": volt,
            "temp_c": temp, "hotspot_c": hot}


def _iso(ts):
    from datetime import datetime, timezone
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%S.0000000Z")


class TestCrashClassification:
    def test_no_telemetry(self):
        code, _ = analyse_crash([], [], _iso(time.time()), "")
        assert code == "NO_TELEMETRY"

    def test_thermal(self):
        now = time.time()
        telemetry = [_point(now, 2800, -100, temp=93.0)]
        code, _ = analyse_crash(telemetry, [], _iso(now), "")
        assert code == "THERMAL"

    def test_thermal_hotspot(self):
        now = time.time()
        telemetry = [_point(now, 2800, -100, temp=80.0, hot=105.0)]
        code, _ = analyse_crash(telemetry, [], _iso(now), "")
        assert code == "THERMAL_HOTSPOT"

    def test_rapid_voltage_swing(self):
        now = time.time()
        telemetry = [_point(now, 3050, -120)]
        changes = [{"ts": now - d, "old_mv": -100, "new_mv": -140} for d in (2, 5, 9)]
        code, _ = analyse_crash(telemetry, changes, _iso(now), "")
        assert code == "RAPID_VOLTAGE_SWING"

    def test_undervolt_too_aggressive(self):
        now = time.time()
        telemetry = [_point(now, 3142, -160)]
        code, _ = analyse_crash(telemetry, [], _iso(now), "")
        assert code == "UNDERVOLT_TOO_AGGRESSIVE"

    def test_peak_boost_insufficient_voltage(self):
        now = time.time()
        telemetry = [_point(now, 3250, -140)]
        code, _ = analyse_crash(telemetry, [], _iso(now), "")
        assert code == "VOLTAGE_INSUFFICIENT_FOR_CLOCK"

    def test_crash_shortly_after_voltage_change(self):
        now = time.time()
        telemetry = [_point(now, 3050, -120)]
        changes = [{"ts": now - 3, "old_mv": -100, "new_mv": -120}]
        code, _ = analyse_crash(telemetry, changes, _iso(now), "")
        assert code == "CRASH_AFTER_VOLTAGE_CHANGE"

    def test_unknown_fallback(self):
        now = time.time()
        telemetry = [_point(now, 2500, -80)]
        code, _ = analyse_crash(telemetry, [], _iso(now), "")
        assert code == "UNKNOWN"
