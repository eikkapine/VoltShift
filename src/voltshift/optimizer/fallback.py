"""Optimiser of last resort, for installs without numpy.

A pattern search: keep the best configuration found so far, propose
neighbours of it, and shrink the neighbourhood each time a round fails to
improve. It has none of the GP's sample efficiency and no notion of
uncertainty, but it converges on something reasonable and — more to the point
— it means a broken numpy install downgrades the tuning quality instead of
breaking the feature.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Optional, Sequence


@dataclass
class Observation:
    config: dict
    score: float
    weight: float = 1.0


class LocalSearchOptimizer:
    def __init__(self, space, n_random: int = 4, seed: Optional[int] = None,
                 initial_scale: float = 0.28, **_ignored):
        self.space = space
        self.n_random = n_random
        self.observations: list[Observation] = []
        self._rng = random.Random(seed)
        self._scale = initial_scale
        self._best_score: Optional[float] = None
        self._misses = 0

    def observe(self, config: dict, score: float, weight: float = 1.0) -> None:
        self.observations.append(Observation(dict(config), float(score), float(weight)))
        if self._best_score is None or score > self._best_score:
            self._best_score = score
            self._misses = 0
        else:
            self._misses += 1
            if self._misses >= 3:
                self._scale = max(0.04, self._scale * 0.6)
                self._misses = 0

    def seed_prior(self, observations: Sequence[Observation]) -> None:
        self.observations = list(observations) + self.observations
        scored = [o.score for o in observations]
        if scored:
            self._best_score = max(scored)

    @property
    def trial_count(self) -> int:
        return sum(1 for o in self.observations if o.weight >= 1.0)

    @property
    def best(self) -> Optional[Observation]:
        if not self.observations:
            return None
        return max(self.observations, key=lambda o: o.score)

    def suggest(self, reject=None) -> dict:
        if self.space.dimensions == 0:
            return {}
        best = self.best
        for _ in range(300):
            if best is None or self.trial_count < self.n_random:
                config = self.space.random_config(self._rng)
            else:
                config = self.space.perturb(best.config, self._scale, self._rng)
            if reject is None or not reject(config):
                return config
        return self.space.default_config()

    def predict_config(self, config: dict) -> tuple[float, float]:
        best = self.best
        return (best.score if best else 0.0), 1.0
