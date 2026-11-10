"""Entirely non-biological deterministic toy illustration of a teacher/student target.

This illustrates data contracts and test behavior, not RFdiffusion training, not
protein generation, and not empirical evidence of biological safety.
"""
from dataclasses import dataclass
from math import isfinite


@dataclass(frozen=True)
class ToyPrediction:
    conditioned: tuple[float, ...]
    unconditioned: tuple[float, ...]


def toy_target(reference: ToyPrediction, strength: float) -> tuple[float, ...]:
    if not isfinite(strength) or strength < 0:
        raise ValueError("strength must be finite and nonnegative")
    if not reference.conditioned or len(reference.conditioned) != len(reference.unconditioned):
        raise ValueError("reference vectors must be nonempty and same length")
    if not all(isfinite(v) for v in reference.conditioned + reference.unconditioned):
        raise ValueError("reference values must be finite")
    return tuple(u - strength * (c - u) for c, u in zip(reference.conditioned, reference.unconditioned))


def masked_mse(prediction: tuple[float, ...], target: tuple[float, ...], mask: tuple[bool, ...]) -> float:
    if len(prediction) != len(target) or len(target) != len(mask):
        raise ValueError("shapes must match")
    selected = [(p, t) for p, t, use in zip(prediction, target, mask) if use]
    if not selected:
        raise ValueError("empty loss mask")
    if not all(isfinite(p) and isfinite(t) for p, t in selected):
        raise ValueError("nonfinite values")
    return sum((p-t)**2 for p,t in selected)/len(selected)
