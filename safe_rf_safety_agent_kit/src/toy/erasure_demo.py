"""Entirely non-biological deterministic toy illustration of a teacher/student target.

This illustrates data contracts and test behavior, not RFdiffusion training, not
protein generation, and not empirical evidence of biological safety.

SR-05 rework (after QA): this module now FAILS CLOSED. Strength must be a real
(non-bool) finite nonnegative number, mask entries must be strictly bool, every
element is checked for finiteness (including masked-out ones, because the
audited source multiplies by the mask and NaN * 0 is NaN), and computed outputs
and losses must be finite.
"""
from dataclasses import dataclass
from math import isfinite


@dataclass(frozen=True)
class ToyPrediction:
    conditioned: tuple[float, ...]
    unconditioned: tuple[float, ...]


def toy_target(reference: ToyPrediction, strength: float) -> tuple[float, ...]:
    if isinstance(strength, bool) or not isinstance(strength, (int, float)):
        raise ValueError("strength must be a real number (bool is not accepted)")
    if not isfinite(strength) or strength < 0:
        raise ValueError("strength must be finite and nonnegative")
    if not reference.conditioned or len(reference.conditioned) != len(reference.unconditioned):
        raise ValueError("reference vectors must be nonempty and same length")
    if not all(isfinite(v) for v in reference.conditioned + reference.unconditioned):
        raise ValueError("reference values must be finite")
    out = tuple(u - strength * (c - u) for c, u in zip(reference.conditioned, reference.unconditioned))
    if not all(isfinite(v) for v in out):
        raise ValueError("target overflowed to a non-finite value")
    return out


def masked_mse(prediction: tuple[float, ...], target: tuple[float, ...], mask: tuple[bool, ...]) -> float:
    if len(prediction) != len(target) or len(target) != len(mask):
        raise ValueError("shapes must match")
    if not all(isinstance(m, bool) for m in mask):
        raise ValueError("mask entries must be strictly bool")
    if not all(isfinite(p) and isfinite(t) for p, t in zip(prediction, target)):
        raise ValueError("nonfinite values")
    selected = [(p, t) for p, t, use in zip(prediction, target, mask) if use]
    if not selected:
        raise ValueError("empty loss mask")
    loss = sum((p - t) * (p - t) for p, t in selected) / len(selected)
    if not isfinite(loss):
        raise ValueError("loss overflowed to a non-finite value")
    return loss
