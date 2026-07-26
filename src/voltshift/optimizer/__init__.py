"""Closed-loop tuning: search space, objective, model, safety, orchestration."""

from .applier import RecordingApplier, TuningApplier
from .benchsession import (BenchmarkConfig, BenchmarkReport, BenchmarkSession,
                           BenchmarkTrial, seed_candidates)
from .objective import DEFAULT_GOAL, GOALS, GoalWeights, Score, goal_choices, score_trial
from .safeguard import Safeguard, Verdict
from .session import (AutoTuneSession, SessionConfig, SessionReport, SessionState,
                      TrialResult)
from .space import (MAX_CLOCK, MIN_CLOCK, POWER_LIMIT, VOLTAGE, VRAM_CLOCK, Knob,
                    SearchSpace)

__all__ = [
    "TuningApplier", "RecordingApplier",
    "BenchmarkSession", "BenchmarkConfig", "BenchmarkReport", "BenchmarkTrial",
    "seed_candidates",
    "GOALS", "DEFAULT_GOAL", "GoalWeights", "Score", "score_trial", "goal_choices",
    "Safeguard", "Verdict",
    "AutoTuneSession", "SessionConfig", "SessionReport", "SessionState", "TrialResult",
    "SearchSpace", "Knob", "VOLTAGE", "POWER_LIMIT", "MAX_CLOCK", "MIN_CLOCK",
    "VRAM_CLOCK",
]


def make_optimizer(space, **kwargs):
    """Build the Bayesian optimiser, or a local-search stand-in without numpy.

    numpy is a listed dependency, so the fallback exists only so that a
    partial install degrades to something that still tunes rather than to a
    crash on the one button the whole app is built around.
    """
    try:
        from .gp import BayesianOptimizer

        return BayesianOptimizer(space, **kwargs)
    except ImportError:
        from .fallback import LocalSearchOptimizer

        return LocalSearchOptimizer(space, **kwargs)
