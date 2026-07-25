"""Gaussian process regression with expected-improvement search.

This is the "light local AI": roughly 200 lines of numpy, no model download,
no GPU, no network. It is the right family of model for the problem — tuning
trials are expensive (tens of seconds each) and noisy (a game's load moves
under you), which is exactly the regime Bayesian optimisation was built for.
A neural network would need thousands of samples to say anything; a GP says
something useful after five, and says how sure it is.

How it is used: observations are (config vector, score). The GP fits a
posterior over the score surface, and expected improvement picks where to
look next, balancing "near the best thing so far" against "somewhere we know
nothing about". Hyperparameters are chosen by maximising the log marginal
likelihood over a small grid, which is stable and needs no gradients.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional, Sequence

import numpy as np

SQRT5 = math.sqrt(5.0)
_ERF = np.vectorize(math.erf, otypes=[float])


def _norm_cdf(z: np.ndarray) -> np.ndarray:
    return 0.5 * (1.0 + _ERF(z / math.sqrt(2.0)))


def _norm_pdf(z: np.ndarray) -> np.ndarray:
    return np.exp(-0.5 * z * z) / math.sqrt(2.0 * math.pi)


def matern52(a: np.ndarray, b: np.ndarray, lengthscale: float,
             signal_var: float) -> np.ndarray:
    """Matérn 5/2 covariance — smooth, but not the implausible infinite
    smoothness of a squared-exponential kernel. Hardware response curves have
    kinks; this kernel tolerates them."""
    diff = a[:, None, :] - b[None, :, :]
    dist = np.sqrt(np.maximum(np.sum(diff * diff, axis=-1), 1e-24))
    scaled = SQRT5 * dist / max(lengthscale, 1e-6)
    return signal_var * (1.0 + scaled + (scaled ** 2) / 3.0) * np.exp(-scaled)


@dataclass
class GaussianProcess:
    """Zero-mean GP over standardised observations."""

    lengthscale: float = 0.35
    signal_var: float = 1.0
    noise_var: float = 0.05

    _X: Optional[np.ndarray] = field(default=None, repr=False)
    _y: Optional[np.ndarray] = field(default=None, repr=False)
    _L: Optional[np.ndarray] = field(default=None, repr=False)
    _alpha: Optional[np.ndarray] = field(default=None, repr=False)
    _y_mean: float = 0.0
    _y_std: float = 1.0

    # ── fitting ──────────────────────────────────────────────────────────────

    def fit(self, X: Sequence[Sequence[float]], y: Sequence[float],
            weights: Optional[Sequence[float]] = None,
            tune_hyperparams: bool = True) -> "GaussianProcess":
        """Condition on observations. `weights` below 1 inflate a point's
        noise, which is how transferred observations from other games are
        included without being trusted as much as this game's own."""
        Xa = np.asarray(X, dtype=float)
        ya = np.asarray(y, dtype=float)
        if Xa.ndim != 2 or len(Xa) == 0:
            self._X = self._y = self._L = self._alpha = None
            return self

        self._y_mean = float(ya.mean())
        self._y_std = float(ya.std()) or 1.0
        y_std = (ya - self._y_mean) / self._y_std

        if weights is None:
            noise = np.full(len(ya), self.noise_var)
        else:
            w = np.clip(np.asarray(weights, dtype=float), 1e-3, 1.0)
            noise = self.noise_var / w

        if tune_hyperparams and len(ya) >= 4:
            self._tune(Xa, y_std, noise)

        self._X, self._y = Xa, y_std
        self._L, self._alpha = self._factorise(Xa, y_std, noise,
                                               self.lengthscale, self.signal_var)
        self._noise = noise
        return self

    def _factorise(self, X: np.ndarray, y: np.ndarray, noise: np.ndarray,
                   lengthscale: float, signal_var: float):
        K = matern52(X, X, lengthscale, signal_var) + np.diag(noise)
        # Jitter until Cholesky succeeds: duplicate trials make K singular,
        # and duplicates are common when the optimiser revisits a good config.
        jitter = 1e-9
        for _ in range(8):
            try:
                L = np.linalg.cholesky(K + jitter * np.eye(len(X)))
                alpha = np.linalg.solve(L.T, np.linalg.solve(L, y))
                return L, alpha
            except np.linalg.LinAlgError:
                jitter *= 10
        return None, None

    def _log_marginal_likelihood(self, X: np.ndarray, y: np.ndarray,
                                 noise: np.ndarray, lengthscale: float,
                                 signal_var: float) -> float:
        L, alpha = self._factorise(X, y, noise, lengthscale, signal_var)
        if L is None:
            return -np.inf
        return float(-0.5 * y @ alpha
                     - np.sum(np.log(np.diag(L)))
                     - 0.5 * len(y) * math.log(2 * math.pi))

    def _tune(self, X: np.ndarray, y: np.ndarray, noise: np.ndarray) -> None:
        """Grid search the kernel hyperparameters. A grid beats gradient
        descent here: the surface is cheap to evaluate at these sizes and a
        grid cannot diverge."""
        best = (-np.inf, self.lengthscale, self.signal_var)
        for lengthscale in (0.12, 0.2, 0.3, 0.45, 0.7, 1.0):
            for signal_var in (0.5, 1.0, 2.0):
                score = self._log_marginal_likelihood(X, y, noise, lengthscale, signal_var)
                if score > best[0]:
                    best = (score, lengthscale, signal_var)
        _, self.lengthscale, self.signal_var = best

    # ── prediction ───────────────────────────────────────────────────────────

    @property
    def fitted(self) -> bool:
        return self._alpha is not None

    def predict(self, X: Sequence[Sequence[float]]) -> tuple[np.ndarray, np.ndarray]:
        """Posterior mean and standard deviation, in original score units."""
        Xs = np.asarray(X, dtype=float)
        if not self.fitted:
            mean = np.zeros(len(Xs))
            std = np.full(len(Xs), math.sqrt(self.signal_var) * self._y_std)
            return mean + self._y_mean, std

        Ks = matern52(Xs, self._X, self.lengthscale, self.signal_var)
        mean = Ks @ self._alpha
        v = np.linalg.solve(self._L, Ks.T)
        var = self.signal_var - np.sum(v * v, axis=0)
        var = np.maximum(var, 1e-12)
        return (mean * self._y_std + self._y_mean, np.sqrt(var) * self._y_std)


def expected_improvement(mean: np.ndarray, std: np.ndarray, best: float,
                         xi: float = 0.01) -> np.ndarray:
    """EI for maximisation. `xi` buys a little extra exploration."""
    std = np.maximum(std, 1e-12)
    improvement = mean - best - xi
    z = improvement / std
    return improvement * _norm_cdf(z) + std * _norm_pdf(z)


@dataclass
class Observation:
    config: dict
    score: float
    weight: float = 1.0


class BayesianOptimizer:
    """Proposes the next configuration to try.

    The first `n_random` proposals are quasi-random, because a GP fitted to
    two points will confidently recommend nonsense. After that, candidates are
    drawn from three pools — uniform samples, perturbations of the best known
    config, and perturbations of every observation — and ranked by expected
    improvement.
    """

    def __init__(self, space, n_random: int = 4, candidates: int = 2000,
                 xi: float = 0.01, seed: Optional[int] = None):
        self.space = space
        self.n_random = n_random
        self.candidates = candidates
        self.xi = xi
        self.gp = GaussianProcess()
        self.observations: list[Observation] = []
        self._rng = np.random.default_rng(seed)

    # ── observations ─────────────────────────────────────────────────────────

    def observe(self, config: dict, score: float, weight: float = 1.0) -> None:
        self.observations.append(Observation(dict(config), float(score), float(weight)))

    def seed_prior(self, observations: Sequence[Observation]) -> None:
        """Warm-start from other sessions' results, down-weighted."""
        self.observations = list(observations) + self.observations

    @property
    def trial_count(self) -> int:
        return sum(1 for o in self.observations if o.weight >= 1.0)

    @property
    def best(self) -> Optional[Observation]:
        if not self.observations:
            return None
        return max(self.observations, key=lambda o: o.score)

    def _fit(self) -> None:
        X = [self.space.to_vector(o.config) for o in self.observations]
        y = [o.score for o in self.observations]
        w = [o.weight for o in self.observations]
        self.gp.fit(X, y, w)

    # ── proposal ─────────────────────────────────────────────────────────────

    def _candidate_pool(self) -> np.ndarray:
        dims = self.space.dimensions
        n = self.candidates
        pool = [self._rng.random((n // 2, dims))]

        best = self.best
        if best is not None:
            centre = np.asarray(self.space.to_vector(best.config))
            for sigma in (0.05, 0.15, 0.3):
                pool.append(np.clip(
                    centre + self._rng.normal(0, sigma, (n // 8, dims)), 0.0, 1.0))

        if self.observations:
            centres = np.asarray([self.space.to_vector(o.config)
                                  for o in self.observations])
            picks = centres[self._rng.integers(0, len(centres), n // 8)]
            pool.append(np.clip(picks + self._rng.normal(0, 0.12, picks.shape), 0.0, 1.0))

        return np.vstack(pool)

    def suggest(self, reject=None) -> dict:
        """Next config to try. `reject(config) -> bool` filters unsafe ones."""
        if self.space.dimensions == 0:
            return {}

        if self.trial_count < self.n_random or not self.observations:
            for _ in range(200):
                config = self.space.from_vector(self._rng.random(self.space.dimensions))
                if reject is None or not reject(config):
                    return config
            return self.space.default_config()

        self._fit()
        pool = self._candidate_pool()
        mean, std = self.gp.predict(pool)
        best_score = max(o.score for o in self.observations)
        ei = expected_improvement(mean, std, best_score, self.xi)

        for index in np.argsort(-ei):
            config = self.space.from_vector(pool[index])
            if reject is None or not reject(config):
                return config
        return self.space.default_config()

    def predict_config(self, config: dict) -> tuple[float, float]:
        """Posterior mean and sigma for one config, for the UI to display."""
        if not self.observations:
            return 0.0, 1.0
        self._fit()
        mean, std = self.gp.predict([self.space.to_vector(config)])
        return float(mean[0]), float(std[0])
