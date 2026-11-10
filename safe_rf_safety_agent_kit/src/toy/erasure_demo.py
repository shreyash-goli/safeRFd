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


def _real(name: str, v) -> float:
    """Strict real-number coercion: bool/str/other raise ValueError; huge ints raise ValueError."""
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise ValueError(f"{name} must be a real number (bool and non-numeric types are not accepted), got {type(v).__name__}")
    try:
        return float(v)
    except OverflowError:
        raise ValueError(f"{name} is too large to represent as a finite float") from None


def toy_target(reference: ToyPrediction, strength: float) -> tuple[float, ...]:
    strength = _real("strength", strength)
    if not isfinite(strength) or strength < 0:
        raise ValueError("strength must be finite and nonnegative")
    if not reference.conditioned or len(reference.conditioned) != len(reference.unconditioned):
        raise ValueError("reference vectors must be nonempty and same length")
    cond = tuple(_real("reference value", v) for v in reference.conditioned)
    unc = tuple(_real("reference value", v) for v in reference.unconditioned)
    if not all(isfinite(v) for v in cond + unc):
        raise ValueError("reference values must be finite")
    out = tuple(u - strength * (c - u) for c, u in zip(cond, unc))
    if not all(isfinite(v) for v in out):
        raise ValueError("target overflowed to a non-finite value")
    return out


def masked_mse(prediction: tuple[float, ...], target: tuple[float, ...], mask: tuple[bool, ...]) -> float:
    if len(prediction) != len(target) or len(target) != len(mask):
        raise ValueError("shapes must match")
    if not all(isinstance(m, bool) for m in mask):
        raise ValueError("mask entries must be strictly bool")
    prediction = tuple(_real("prediction value", v) for v in prediction)
    target = tuple(_real("target value", v) for v in target)
    if not all(isfinite(p) and isfinite(t) for p, t in zip(prediction, target)):
        raise ValueError("nonfinite values")
    selected = [(p, t) for p, t, use in zip(prediction, target, mask) if use]
    if not selected:
        raise ValueError("empty loss mask")
    loss = sum((p - t) * (p - t) for p, t in selected) / len(selected)
    if not isfinite(loss):
        raise ValueError("loss overflowed to a non-finite value")
    return loss
