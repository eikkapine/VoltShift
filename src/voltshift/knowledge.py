"""What VoltShift has learned, and remembers.

Three kinds of memory, in increasing order of how widely they apply:

  Per game      Which configuration scored best in this executable, under
                which goal. Reused directly next time you launch it.
  Per silicon   The stability frontier of *this physical card* — the least
                aggressive voltage that has ever misbehaved, per clock band.
                Games come and go; the card's limits do not, so this is the
                memory that compounds.
  Transfer      When a game is seen for the first time there is no history
                for it, but there is history for other games on the same
                card. Those observations seed the optimiser at reduced
                weight, so a new title starts from an educated guess instead
                of from scratch.

SQLite, one file, no server, safe across concurrent processes.
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from dataclasses import dataclass
from typing import Optional

from . import paths

DB_FILE = "voltshift_knowledge.db"

# Clock band width for the stability frontier, in MHz. Silicon behaviour
# changes with frequency, but not so sharply that finer bands would carry
# more signal than noise.
CLOCK_BUCKET_MHZ = 100

# Down-weighting applied to borrowed observations.
WEIGHT_SAME_GAME = 1.0
WEIGHT_SAME_GAME_OTHER_GOAL = 0.25
WEIGHT_OTHER_GAME = 0.35

# Observations older than this contribute less; drivers and games change.
HALF_LIFE_DAYS = 60.0

SCHEMA = """
CREATE TABLE IF NOT EXISTS observations (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    gpu_key    TEXT NOT NULL,
    exe        TEXT NOT NULL,
    goal       TEXT NOT NULL,
    ts         REAL NOT NULL,
    config     TEXT NOT NULL,
    score      REAL NOT NULL,
    fps_avg    REAL,
    fps_p1     REAL,
    board_w    REAL,
    hotspot_c  REAL,
    stable     INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS idx_obs_lookup ON observations (gpu_key, exe, goal);

CREATE TABLE IF NOT EXISTS unsafe (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    gpu_key  TEXT NOT NULL,
    config   TEXT NOT NULL,
    kind     TEXT NOT NULL,
    ts       REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_unsafe_gpu ON unsafe (gpu_key);

CREATE TABLE IF NOT EXISTS best (
    gpu_key  TEXT NOT NULL,
    exe      TEXT NOT NULL,
    goal     TEXT NOT NULL,
    config   TEXT NOT NULL,
    score    REAL NOT NULL,
    ts       REAL NOT NULL,
    PRIMARY KEY (gpu_key, exe, goal)
);

CREATE TABLE IF NOT EXISTS frontier (
    gpu_key       TEXT NOT NULL,
    clock_bucket  INTEGER NOT NULL,
    failed_mv     INTEGER NOT NULL,
    failures      INTEGER NOT NULL DEFAULT 1,
    ts            REAL NOT NULL,
    PRIMARY KEY (gpu_key, clock_bucket)
);

CREATE TABLE IF NOT EXISTS knob_support (
    gpu_key    TEXT NOT NULL,
    knob       TEXT NOT NULL,
    supported  INTEGER NOT NULL,
    ts         REAL NOT NULL,
    PRIMARY KEY (gpu_key, knob)
);
"""


def db_path() -> str:
    return os.path.join(paths.app_dir(), DB_FILE)


def gpu_key(info: dict) -> str:
    """A stable identity for one physical card.

    Device id plus unique id, so two identical models in one machine keep
    separate frontiers — silicon quality varies between samples, which is the
    entire reason undervolting is a per-card exercise.
    """
    device = str(info.get("deviceId", "") or "unknown")
    unique = str(info.get("uniqueId", "") or "")
    name = str(info.get("name", "gpu") or "gpu").replace(" ", "_")
    return f"{name}:{device}:{unique}"


@dataclass(frozen=True)
class StoredObservation:
    config: dict
    score: float
    weight: float
    exe: str
    goal: str
    ts: float


class KnowledgeStore:
    def __init__(self, path: Optional[str] = None):
        self._path = path or db_path()
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(self._path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.executescript(SCHEMA)
            self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def _age_weight(self, ts: float) -> float:
        age_days = max(0.0, (time.time() - ts) / 86400.0)
        return 0.5 ** (age_days / HALF_LIFE_DAYS)

    # ── observations ─────────────────────────────────────────────────────────

    def record_observation(self, gpu: str, exe: str, goal: str, config: dict,
                           score: float, stable: bool = True,
                           fps_avg: Optional[float] = None,
                           fps_p1: Optional[float] = None,
                           board_w: Optional[float] = None,
                           hotspot_c: Optional[float] = None) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO observations (gpu_key, exe, goal, ts, config, score,"
                " fps_avg, fps_p1, board_w, hotspot_c, stable)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (gpu, exe, goal, time.time(), json.dumps(config, sort_keys=True),
                 float(score), fps_avg, fps_p1, board_w, hotspot_c, int(stable)))
            self._conn.commit()

    def observations(self, gpu: str, exe: Optional[str] = None,
                     goal: Optional[str] = None, limit: int = 500
                     ) -> list[StoredObservation]:
        query = "SELECT * FROM observations WHERE gpu_key = ?"
        args: list = [gpu]
        if exe is not None:
            query += " AND exe = ?"
            args.append(exe)
        if goal is not None:
            query += " AND goal = ?"
            args.append(goal)
        query += " ORDER BY ts DESC LIMIT ?"
        args.append(limit)
        with self._lock:
            rows = self._conn.execute(query, args).fetchall()
        return [StoredObservation(json.loads(r["config"]), r["score"], 1.0,
                                  r["exe"], r["goal"], r["ts"]) for r in rows]

    def prior_observations(self, gpu: str, exe: str, goal: str,
                           limit: int = 60) -> list[StoredObservation]:
        """Observations to warm-start a new optimisation, already weighted.

        Same game and goal count fully. Same game under a different goal, or
        a different game on the same card, count partially — the hardware's
        response is shared even when the objective is not.
        """
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM observations WHERE gpu_key = ? AND stable = 1"
                " ORDER BY ts DESC LIMIT ?", (gpu, limit * 3)).fetchall()

        out: list[StoredObservation] = []
        for row in rows:
            if row["exe"] == exe and row["goal"] == goal:
                weight = WEIGHT_SAME_GAME
            elif row["exe"] == exe:
                weight = WEIGHT_SAME_GAME_OTHER_GOAL
            elif row["goal"] == goal:
                weight = WEIGHT_OTHER_GAME
            else:
                weight = WEIGHT_OTHER_GAME * 0.5
            weight *= self._age_weight(row["ts"])
            if weight < 0.02:
                continue
            out.append(StoredObservation(json.loads(row["config"]), row["score"],
                                         weight, row["exe"], row["goal"], row["ts"]))
            if len(out) >= limit:
                break
        return out

    # ── best-known configurations ────────────────────────────────────────────

    def record_best(self, gpu: str, exe: str, goal: str, config: dict,
                    score: float) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO best (gpu_key, exe, goal, config, score, ts)"
                " VALUES (?,?,?,?,?,?)"
                " ON CONFLICT(gpu_key, exe, goal) DO UPDATE SET"
                "   config = excluded.config, score = excluded.score, ts = excluded.ts"
                " WHERE excluded.score > best.score",
                (gpu, exe, goal, json.dumps(config, sort_keys=True), float(score),
                 time.time()))
            self._conn.commit()

    def best_config(self, gpu: str, exe: str, goal: str) -> Optional[dict]:
        with self._lock:
            row = self._conn.execute(
                "SELECT config FROM best WHERE gpu_key = ? AND exe = ? AND goal = ?",
                (gpu, exe, goal)).fetchone()
        return json.loads(row["config"]) if row else None

    def known_games(self, gpu: str) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT exe, goal, score, ts FROM best WHERE gpu_key = ?"
                " ORDER BY ts DESC", (gpu,)).fetchall()
        return [dict(r) for r in rows]

    def forget_game(self, gpu: str, exe: str) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM best WHERE gpu_key = ? AND exe = ?",
                               (gpu, exe))
            self._conn.execute("DELETE FROM observations WHERE gpu_key = ? AND exe = ?",
                               (gpu, exe))
            self._conn.commit()

    # ── unsafe configurations ────────────────────────────────────────────────

    def mark_unsafe(self, gpu: str, config: dict, kind: str = "unknown") -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO unsafe (gpu_key, config, kind, ts) VALUES (?,?,?,?)",
                (gpu, json.dumps(config, sort_keys=True), kind, time.time()))
            self._conn.commit()

    def unsafe_configs(self, gpu: str, limit: int = 200) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT config FROM unsafe WHERE gpu_key = ? ORDER BY ts DESC LIMIT ?",
                (gpu, limit)).fetchall()
        return [json.loads(r["config"]) for r in rows]

    def unsafe_count(self, gpu: str) -> int:
        with self._lock:
            row = self._conn.execute(
                "SELECT COUNT(*) AS n FROM unsafe WHERE gpu_key = ?", (gpu,)).fetchone()
        return int(row["n"]) if row else 0

    # ── stability frontier ───────────────────────────────────────────────────

    def record_failure(self, gpu: str, voltage_mv: Optional[int],
                       clock_mhz: Optional[float],
                       stock_mv: Optional[int] = None) -> None:
        """Teach the frontier that this voltage failed at this clock.

        Only the *least aggressive* failure per band is kept: if -150 mV once
        misbehaved, the fact that -180 mV also did adds nothing — -150 is
        already the binding constraint.

        A failure at or above stock voltage is deliberately *not* recorded.
        Undervolting cannot be the cause of something that happened without
        one, and recording it would set the frontier at or above stock — which
        is above every value the knob can take, banning the whole search space
        permanently. `stock_mv` defaults to 0 because on the offset-style
        interfaces stock is exactly 0.
        """
        if voltage_mv is None:
            return
        ceiling = 0 if stock_mv is None else stock_mv
        if voltage_mv >= ceiling:
            return
        bucket = int((clock_mhz or 0) // CLOCK_BUCKET_MHZ)
        with self._lock:
            self._conn.execute(
                "INSERT INTO frontier (gpu_key, clock_bucket, failed_mv, failures, ts)"
                " VALUES (?,?,?,1,?)"
                " ON CONFLICT(gpu_key, clock_bucket) DO UPDATE SET"
                "   failed_mv = MAX(frontier.failed_mv, excluded.failed_mv),"
                "   failures = frontier.failures + 1,"
                "   ts = excluded.ts",
                (gpu, bucket, int(voltage_mv), time.time()))
            self._conn.commit()

    def frontier_limit(self, gpu: str, clock_mhz: Optional[float] = None
                       ) -> Optional[int]:
        """The most conservative voltage known to have failed near this clock.

        Falls back to neighbouring bands, then to the worst failure anywhere
        on the card, because a card that hung once is telling you something
        that is not confined to one clock band.
        """
        with self._lock:
            rows = self._conn.execute(
                "SELECT clock_bucket, failed_mv FROM frontier WHERE gpu_key = ?",
                (gpu,)).fetchall()
        if not rows:
            return None
        if clock_mhz is None:
            return max(r["failed_mv"] for r in rows)

        bucket = int(clock_mhz // CLOCK_BUCKET_MHZ)
        nearby = [r["failed_mv"] for r in rows if abs(r["clock_bucket"] - bucket) <= 1]
        if nearby:
            return max(nearby)
        return max(r["failed_mv"] for r in rows)

    def reset_frontier(self, gpu: str) -> int:
        """Forget the learned voltage frontier for one card.

        Needed because the frontier is deliberately permanent: a single bad
        entry would otherwise constrain the search forever, and a driver
        update or a fixed cooling problem can make an old failure obsolete.
        """
        with self._lock:
            cursor = self._conn.execute(
                "DELETE FROM frontier WHERE gpu_key = ?", (gpu,))
            self._conn.execute("DELETE FROM unsafe WHERE gpu_key = ?", (gpu,))
            self._conn.commit()
            return cursor.rowcount

    def frontier(self, gpu: str) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT clock_bucket, failed_mv, failures, ts FROM frontier"
                " WHERE gpu_key = ? ORDER BY clock_bucket", (gpu,)).fetchall()
        return [{"clock_mhz": r["clock_bucket"] * CLOCK_BUCKET_MHZ,
                 "failed_mv": r["failed_mv"], "failures": r["failures"],
                 "ts": r["ts"]} for r in rows]

    # ── verified control support ─────────────────────────────────────────────

    def record_knob_support(self, gpu: str, support: dict[str, bool]) -> None:
        """Cache which tuning controls this card was measured to honour."""
        now = time.time()
        with self._lock:
            self._conn.executemany(
                "INSERT INTO knob_support (gpu_key, knob, supported, ts)"
                " VALUES (?,?,?,?)"
                " ON CONFLICT(gpu_key, knob) DO UPDATE SET"
                "   supported = excluded.supported, ts = excluded.ts",
                [(gpu, knob, int(ok), now) for knob, ok in support.items()])
            self._conn.commit()

    def knob_support(self, gpu: str) -> dict[str, bool]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT knob, supported FROM knob_support WHERE gpu_key = ?",
                (gpu,)).fetchall()
        return {r["knob"]: bool(r["supported"]) for r in rows}

    def clear_knob_support(self, gpu: str) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM knob_support WHERE gpu_key = ?", (gpu,))
            self._conn.commit()

    # ── maintenance ──────────────────────────────────────────────────────────

    def stats(self, gpu: Optional[str] = None) -> dict:
        where, args = ("WHERE gpu_key = ?", (gpu,)) if gpu else ("", ())
        with self._lock:
            observations = self._conn.execute(
                f"SELECT COUNT(*) AS n FROM observations {where}", args).fetchone()["n"]
            games = self._conn.execute(
                f"SELECT COUNT(DISTINCT exe) AS n FROM observations {where}",
                args).fetchone()["n"]
            unsafe = self._conn.execute(
                f"SELECT COUNT(*) AS n FROM unsafe {where}", args).fetchone()["n"]
            frontier = self._conn.execute(
                f"SELECT COUNT(*) AS n FROM frontier {where}", args).fetchone()["n"]
        return {"observations": observations, "games": games,
                "unsafe": unsafe, "frontier_bands": frontier}

    def export(self) -> dict:
        with self._lock:
            tables = {}
            for table in ("observations", "unsafe", "best", "frontier"):
                rows = self._conn.execute(f"SELECT * FROM {table}").fetchall()
                tables[table] = [dict(r) for r in rows]
        return tables
