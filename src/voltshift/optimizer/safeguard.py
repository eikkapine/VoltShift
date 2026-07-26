"""The layer that stands between the optimiser and the hardware.

The Bayesian optimiser is a search algorithm. It has no concept of a card
that stops responding, and it should not — mixing "what scores well" with
"what is allowed" makes both harder to reason about. So the optimiser
proposes, and this module disposes: every configuration passes four checks
before it can reach the GPU.

  Bounds      Inside the ranges ADLX reported for this card.
  Step limit  No knob moves further than its per-application cap.
  Tabu        Not at, or next to, a configuration already known to be unsafe.
  Frontier    Not below the learned stability frontier for this silicon.

The frontier is the interesting one. Stability is a property of the physical
card, not of any game, so every failure ever recorded teaches VoltShift
something that applies to every future session on the same GPU.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from .space import VOLTAGE, SearchSpace

# How close, in normalised space, a candidate may come to a known-unsafe
# config. Instability is not a point property — if -180 mV hung the card,
# -178 mV is not a discovery worth making.
TABU_RADIUS = 0.06

# Safety margin held back from the learned frontier, in millivolts.
FRONTIER_MARGIN_MV = 15


@dataclass(frozen=True)
class Verdict:
    ok: bool
    reason: str = ""

    def __bool__(self) -> bool:
        return self.ok


ALLOWED = Verdict(True)


class Safeguard:
    def __init__(self, space: SearchSpace, knowledge=None, gpu_key: str = "",
                 tabu_radius: float = TABU_RADIUS,
                 frontier_margin_mv: int = FRONTIER_MARGIN_MV):
        self.space = space
        self.knowledge = knowledge
        self.gpu_key = gpu_key
        self.tabu_radius = tabu_radius
        self.frontier_margin_mv = frontier_margin_mv
        self._session_tabu: list[dict] = []

    # ── tabu set ─────────────────────────────────────────────────────────────

    def mark_unsafe(self, config: dict, kind: str = "unknown") -> None:
        """Record a config as unsafe for this session and, if a knowledge
        store is attached, for every future session on this card."""
        self._session_tabu.append(dict(config))
        if self.knowledge is not None and self.gpu_key:
            self.knowledge.mark_unsafe(self.gpu_key, config, kind)

    def _tabu_configs(self) -> list[dict]:
        stored = []
        if self.knowledge is not None and self.gpu_key:
            stored = self.knowledge.unsafe_configs(self.gpu_key)
        return self._session_tabu + stored

    # ── checks ───────────────────────────────────────────────────────────────

    def check_bounds(self, config: dict) -> Verdict:
        for knob in self.space.knobs:
            value = config.get(knob.name)
            if value is None:
                continue
            if value < knob.low or value > knob.high:
                return Verdict(False, f"{knob.name}={value} outside "
                                      f"{knob.low}..{knob.high}{knob.unit}")
        return ALLOWED

    def check_step(self, config: dict, current: Optional[dict]) -> Verdict:
        if not current:
            return ALLOWED
        for knob in self.space.knobs:
            if knob.max_delta is None:
                continue
            want, have = config.get(knob.name), current.get(knob.name)
            if want is None or have is None:
                continue
            if abs(want - have) > knob.max_delta:
                return Verdict(False, f"{knob.name} moves {abs(want - have)}{knob.unit} "
                                      f"in one step (cap {knob.max_delta}{knob.unit})")
        return ALLOWED

    def check_tabu(self, config: dict) -> Verdict:
        for unsafe in self._tabu_configs():
            if self.space.distance(config, unsafe) <= self.tabu_radius:
                return Verdict(False, "too close to a configuration that "
                                      "previously destabilised this GPU")
        return ALLOWED

    def check_frontier(self, config: dict, clock_mhz: Optional[float] = None) -> Verdict:
        if self.knowledge is None or not self.gpu_key:
            return ALLOWED
        voltage = config.get(VOLTAGE)
        if voltage is None:
            return ALLOWED
        limit = self.knowledge.frontier_limit(self.gpu_key, clock_mhz)
        if limit is None:
            return ALLOWED

        floor = limit + self.frontier_margin_mv
        knob = self.space.knob(VOLTAGE)
        if knob is not None and floor >= knob.high:
            # A frontier at or above the highest voltage the knob can reach
            # would reject every possible configuration, leaving the card
            # untunable with no way back. A frontier that forbids everything
            # is not information, so it is ignored rather than obeyed.
            return ALLOWED

        if voltage < floor:
            return Verdict(False, f"{voltage}mV is below the learned stability "
                                  f"frontier for this card ({floor}mV with margin)")
        return ALLOWED

    def check(self, config: dict, current: Optional[dict] = None,
              clock_mhz: Optional[float] = None) -> Verdict:
        """Run every check; the first failure wins."""
        for verdict in (self.check_bounds(config),
                        self.check_step(config, current),
                        self.check_tabu(config),
                        self.check_frontier(config, clock_mhz)):
            if not verdict.ok:
                return verdict
        return ALLOWED

    def rejects(self, current: Optional[dict] = None,
                clock_mhz: Optional[float] = None):
        """A predicate for `BayesianOptimizer.suggest`."""
        def reject(config: dict) -> bool:
            return not self.check(config, current, clock_mhz).ok
        return reject

    def sanitise(self, config: dict, current: Optional[dict] = None) -> dict:
        """Clamp a config into bounds and within one step of `current`.

        Used for configs that came from elsewhere — a saved profile, a
        transferred prior — where rejecting outright would be unhelpful but
        applying verbatim would not be safe.
        """
        clamped = self.space.clamp_config(config)
        if current:
            clamped = self.space.limit_step(clamped, current)
        return clamped
