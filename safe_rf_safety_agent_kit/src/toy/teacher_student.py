"""SR-05: abstract teacher/student demo on small 2D numeric arrays.

TOY RESULT module. Standard library only. Everything here is a *structural
analogue* on abstract numbers: it is not a protein model, not a model of the
audited method's behaviour, and not evidence of any safety property.

A 2D array is a tuple of tuples of floats (rows of equal width).

Structure mirrored (abstractly):
  * frozen Teacher -> fixed `conditioned` / `unconditioned` outputs per input
  * mutable Student -> small parameter vector, explicit gradient descent
  * erasure_target  -> uncond - eta * (cond - uncond)
  * optional magnitude rescale (off by default)
  * masked MSE with a per-row mask and two named normalizations

Norm difference (stated explicitly): the toy rescale uses ONE Frobenius norm
over the whole matrix, whereas the audited source takes per-atom norms along
dim=-1. This is a structural analogue only, not a faithful reproduction.

Reproducibility vs honesty of time: `train()` records the real UTC time by
default, so an unpinned record's `content_hash` differs between runs (it is
honest about when it ran). Pass `timestamp_utc=` explicitly to get a
reproducible `content_hash`. This is deliberate; the caller must choose.
"""
from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime, timezone
from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping, Sequence

from toy.schema import (TOY_LABEL, EvidenceClass, ExperimentRecord, MetricValue, RunProvenance,
                        current_python_version, derive_seed, make_rng)

Matrix = tuple[tuple[float, ...], ...]
NORMALIZATIONS = ("per_masked_element", "per_mask_entry")
RESCALE_MIN, RESCALE_MAX, RESCALE_EPS = 0.1, 2.0, 1e-8
CODE_VERSION = "toy-teacher-student-v1"


# ------------------------------------------------------------ 2D helpers
def as_matrix(name: str, m: Sequence[Sequence[float]]) -> Matrix:
    """Validate and normalise to a tuple-of-tuples of finite floats."""
    if isinstance(m, (str, bytes)) or not hasattr(m, "__len__") or len(m) == 0:
        raise ValueError(f"{name} must be a nonempty 2D array")
    rows = []
    for row in m:
        if isinstance(row, (str, bytes)) or not hasattr(row, "__len__") or len(row) == 0:
            raise ValueError(f"{name} has an empty or non-sequence row")
        rows.append(tuple(row))
    width = len(rows[0])
    if any(len(r) != width for r in rows):
        raise ValueError(f"{name} is ragged: rows must all have the same width")
    out = []
    for r in rows:
        conv = []
        for v in r:
            if isinstance(v, bool) or not isinstance(v, (int, float)):
                raise ValueError(f"{name} contains a non-numeric value {v!r}")
            try:
                f = float(v)
            except OverflowError:
                raise ValueError(f"{name} contains a non-finite value (integer too large for float)") from None
            if not math.isfinite(f):
                raise ValueError(f"{name} contains a non-finite value")
            conv.append(f)
        out.append(tuple(conv))
    return tuple(out)


def _same_shape(a_name: str, a: Matrix, b_name: str, b: Matrix) -> None:
    if len(a) != len(b) or len(a[0]) != len(b[0]):
        raise ValueError(f"shape mismatch: {a_name} is {len(a)}x{len(a[0])}, {b_name} is {len(b)}x{len(b[0])}")


def elementwise(fn, a: Matrix, b: Matrix) -> Matrix:
    """Apply fn(x, y) elementwise to two same-shaped matrices."""
    _same_shape("a", a, "b", b)
    return tuple(tuple(fn(x, y) for x, y in zip(ra, rb)) for ra, rb in zip(a, b))


def frobenius_norm(m: Matrix) -> float:
    return math.sqrt(sum(v * v for r in m for v in r))


def _check_lr(lr) -> float:
    if isinstance(lr, bool) or not isinstance(lr, (int, float)) or not math.isfinite(lr):
        raise ValueError("learning rate must be finite")
    if lr <= 0:
        raise ValueError("learning rate must be strictly positive (lr <= 0 would stall or ascend the loss)")
    return float(lr)


def _check_eta(eta: float) -> float:
    if isinstance(eta, bool) or not isinstance(eta, (int, float)) or not math.isfinite(eta) or eta < 0:
        raise ValueError("eta must be finite and nonnegative")
    return float(eta)


def _check_mask(mask: Sequence[bool], n_rows: int) -> tuple[bool, ...]:
    if not hasattr(mask, "__len__") or len(mask) != n_rows:
        raise ValueError(f"mask must have one entry per row ({n_rows})")
    if not all(isinstance(b, bool) for b in mask):
        raise ValueError("mask entries must be bool")
    if not any(mask):
        raise ValueError("empty mask: no rows selected; refusing to compute a loss")
    return tuple(mask)


# --------------------------------------------------------------- teacher
_TEACHER_KEYS = ("cond_scale", "cond_bias", "uncond_scale", "uncond_bias")


@dataclass(frozen=True)
class TeacherOutput:
    conditioned: Matrix
    unconditioned: Matrix


@dataclass(frozen=True)
class Teacher:
    """Frozen teacher. Parameters live in a read-only mapping of tuples and the
    dataclass is frozen, so any mutation attempt raises (TypeError for the
    mapping, FrozenInstanceError for attributes). Per-column affine maps:
    conditioned = x*cond_scale + cond_bias, unconditioned likewise."""
    params: Mapping[str, tuple[float, ...]]

    def __post_init__(self) -> None:
        if set(self.params) != set(_TEACHER_KEYS):
            raise ValueError(f"teacher params must have exactly keys {list(_TEACHER_KEYS)}")
        cleaned = {}
        for k in _TEACHER_KEYS:
            v = tuple(self.params[k])
            if not v or any(isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x) for x in v):
                raise ValueError(f"teacher param {k} must be nonempty and finite")
            cleaned[k] = tuple(float(x) for x in v)
        if len({len(v) for v in cleaned.values()}) != 1:
            raise ValueError("teacher params must all have the same length (the row width)")
        object.__setattr__(self, "params", MappingProxyType(cleaned))

    @property
    def width(self) -> int:
        return len(self.params["cond_scale"])

    def outputs(self, x: Sequence[Sequence[float]]) -> TeacherOutput:
        xm = as_matrix("x", x)
        if len(xm[0]) != self.width:
            raise ValueError(f"x width {len(xm[0])} != teacher width {self.width}")
        p = self.params
        cond = tuple(tuple(v * p["cond_scale"][j] + p["cond_bias"][j] for j, v in enumerate(r)) for r in xm)
        unc = tuple(tuple(v * p["uncond_scale"][j] + p["uncond_bias"][j] for j, v in enumerate(r)) for r in xm)
        return TeacherOutput(cond, unc)


def make_teacher(seed: int, width: int = 3) -> Teacher:
    """Deterministic teacher from a seed (independent RNG; global state untouched)."""
    if isinstance(width, bool) or not isinstance(width, int) or width < 1:
        raise ValueError("width must be a positive int")
    rng = make_rng(derive_seed(seed, "teacher"))
    def vec(lo, hi):
        return tuple(rng.uniform(lo, hi) for _ in range(width))
    return Teacher({"cond_scale": vec(0.5, 1.5), "cond_bias": vec(-0.5, 0.5),
                    "uncond_scale": vec(0.5, 1.5), "uncond_bias": vec(-0.5, 0.5)})


# ---------------------------------------------------------------- target
def erasure_target(cond: Sequence[Sequence[float]], uncond: Sequence[Sequence[float]], eta: float,
                   rescale: bool = False) -> Matrix:
    """target = uncond - eta * (cond - uncond); same formula as
    `toy.erasure_demo.toy_target` (eta there is called `strength`).

    rescale (opt-in, default False): multiply the target by
    clamp(||uncond|| / (||target|| + 1e-8), 0.1, 2.0), a structural analogue of
    the source's scale_factor. NOTE: this rescale partially counteracts the
    displacement it is applied to, since it pulls the target's magnitude back
    toward the unconditioned magnitude. Norm is Frobenius.

    F8 -- THIS PROPERTY DOES NOT CARRY OVER, and the sentence above is about the
    TOY only. "Partially counteracts" is true here because the toy multiplies by
    ONE non-negative Frobenius-norm ratio, so the target can only be shortened or
    lengthened along its own direction. The audited source applies a PER-ATOM map
    (`docs/METHOD_AUDIT.md` rows 7-8): it replaces the displacement with
    `||u|| * (t_hat - u_hat)`, which is origin-dependent, can change DIRECTION,
    and can FLIP SIGN through the origin -- none of which a single positive scalar
    can do. So a reader must not infer from this toy that the source's rescale
    merely damps the erasure signal; whether it preserves that signal at all is
    INFERENCE in row 7 and is not established. Same shape as the disclosure one
    function away in `masked_mse_loss_and_grad`.
    """
    c, u = as_matrix("cond", cond), as_matrix("uncond", uncond)
    _same_shape("cond", c, "uncond", u)
    eta = _check_eta(eta)
    t = tuple(tuple(uv - eta * (cv - uv) for cv, uv in zip(rc, ru)) for rc, ru in zip(c, u))
    if rescale:
        s = frobenius_norm(u) / (frobenius_norm(t) + RESCALE_EPS)
        s = min(max(s, RESCALE_MIN), RESCALE_MAX)
        t = tuple(tuple(v * s for v in r) for r in t)
    return t


# ---------------------------------------------------------------- student
@dataclass
class Student:
    """Mutable student: per-column affine model pred = x*scale + bias.
    `params` is a flat list [scale_0..scale_{w-1}, bias_0..bias_{w-1}]."""
    params: list

    @property
    def width(self) -> int:
        return len(self.params) // 2

    def predict(self, x: Sequence[Sequence[float]]) -> Matrix:
        return predict(tuple(self.params), as_matrix("x", x))

    def step(self, grad: Sequence[float], lr: float) -> None:
        """Explicit gradient descent: params -= lr * grad (in place)."""
        lr = _check_lr(lr)
        if len(grad) != len(self.params):
            raise ValueError(f"grad length {len(grad)} != params length {len(self.params)}")
        if not all(math.isfinite(g) for g in grad):
            raise ValueError("grad must be finite")
        new = [p - lr * g for p, g in zip(self.params, grad)]
        if not all(math.isfinite(p) for p in new):
            raise ValueError("diverged: update produced non-finite parameters (learning rate too large?)")
        self.params[:] = new


def predict(params: Sequence[float], x: Matrix) -> Matrix:
    w = len(x[0])
    if len(params) != 2 * w:
        raise ValueError(f"params length {len(params)} != 2 * row width {w}")
    return tuple(tuple(v * params[j] + params[w + j] for j, v in enumerate(r)) for r in x)


# ------------------------------------------------------------------- loss
def masked_mse_loss_and_grad(params: Sequence[float], x: Sequence[Sequence[float]],
                             target: Sequence[Sequence[float]], mask: Sequence[bool],
                             normalization: str = "per_masked_element") -> tuple[float, tuple[float, ...]]:
    """Masked MSE (mask per row) and its analytic gradient w.r.t. `params`.

    Returns (loss, grad) with grad a tuple the same length as params, ordered
    [d/dscale_0.., d/dbias_0..]. Model: pred[i][j] = x[i][j]*params[j] + params[w+j].
    The target is treated as a constant (no gradient flows into it).

    normalization:
      "per_masked_element" (default): sum of squared errors over masked rows /
          (mask_sum * row_width). This divisor counts EVERY SUMMED ELEMENT, which
          is what makes the two options differ by exactly the row width.
          F7: this line used to end by calling that divisor the *correct* one,
          and that is a judgement this project's own register declines to make --
          (the phrase itself is deliberately not repeated here: a test forbids it
          in this docstring, and a guard that quotes the string it bans defeats
          itself) --
          `docs/ERROR_REGISTER.md:98` says it "does not establish ... that any
          particular loss scale is wrong for the method's purpose (the choice may
          be intentional)", and `docs/METHOD_AUDIT.md:131` concludes only that the
          mismatch "by itself does not explain a high gradient". Which divisor
          suits the method is the author's call and is not decided here.
      "per_mask_entry": divided by mask_sum only. Analogue of the normalization
          mismatch noted in the audited source (TOY reproduction of an audited
          numerical concern, not a claim about the real code's impact). It
          inflates the loss, and the gradient, by exactly the row width.

          THE SIGN DOES NOT CARRY OVER, and the analogy is misleading if read
          without this paragraph. Here the mismatch is the whole effect, so the
          toy INFLATES. In the audited source the same mismatch is a constant
          factor of 42 (= 14 atoms * 3 coords), but it sits beside a 0.01
          multiplier that more than cancels it: the net multiplier relative to
          a per-element MSE is 0.42, a DEFLATION (METHOD_AUDIT 2.2, claim 10).
          So the toy's gradient goes up where the source's net goes down. The
          toy reproduces the *shape* of the defect -- a denominator that counts
          mask entries rather than elements -- not its magnitude and not its
          direction. Nothing here says the source's net 0.42 is harmful, or
          that it explains the author's "gradient is high" note; METHOD_AUDIT
          records that cause as UNKNOWN.
    An empty / all-False mask raises ValueError; it never returns a loss.
    """
    if normalization not in NORMALIZATIONS:
        raise ValueError(f"normalization must be one of {NORMALIZATIONS}, got {normalization!r}")
    xm, tm = as_matrix("x", x), as_matrix("target", target)
    _same_shape("x", xm, "target", tm)
    mk = _check_mask(mask, len(xm))
    if not all(isinstance(p, (int, float)) and not isinstance(p, bool) and math.isfinite(p) for p in params):
        raise ValueError("params must be finite numbers")
    w = len(xm[0])
    pred = predict(params, xm)
    mask_sum = sum(mk)
    denom = float(mask_sum * w) if normalization == "per_masked_element" else float(mask_sum)
    sse = 0.0
    grad = [0.0] * (2 * w)
    for i, use in enumerate(mk):
        if not use:
            continue
        for j in range(w):
            e = pred[i][j] - tm[i][j]
            sse += e * e
            grad[j] += 2.0 * e * xm[i][j]
            grad[w + j] += 2.0 * e
    loss, grad = sse / denom, tuple(g / denom for g in grad)
    if not math.isfinite(loss) or not all(math.isfinite(g) for g in grad):
        raise ValueError("non-finite loss or gradient (numeric overflow)")
    return loss, grad


# ------------------------------------------------------------------ train
@dataclass(frozen=True)
class TrainResult:
    history: tuple  # tuple of (step, loss, grad_norm); step 0 is before any update
    final_params: tuple
    teacher_before: TeacherOutput
    teacher_after: TeacherOutput
    record: ExperimentRecord
    loss_increased: bool = False  # True when final loss > initial loss (runaway-but-finite lr, etc.)


def _hash_json(obj) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _finite_metric(name: str, v: float) -> MetricValue:
    if not math.isfinite(v):
        raise ValueError(f"metric {name} is non-finite: input or parameter magnitudes are too large for float64")
    return MetricValue.measured(float(v))


def make_inputs(seed: int, rows: int = 4, width: int = 3) -> Matrix:
    rng = make_rng(derive_seed(seed, "inputs"))
    return tuple(tuple(rng.uniform(-1.0, 1.0) for _ in range(width)) for _ in range(rows))


def train(seed: int, steps: int = 50, lr: float = 0.05, eta: float = 0.5, rescale: bool = False,
          normalization: str = "per_masked_element", rows: int | None = None, width: int | None = None,
          mask: Sequence[bool] | None = None, x: Sequence[Sequence[float]] | None = None,
          teacher: Teacher | None = None,
          timestamp_utc: str | None = None) -> TrainResult:
    """Deterministic TOY training loop. Student params are initialised from a
    seed-derived RNG; teacher is never updated. history[k] = (k, loss, grad_norm)
    evaluated before update k; history has steps+1 entries (last = after final update).
    lr must be finite and > 0. Returns a TrainResult whose `record` has evidence_class TOY_RESULT.

    timestamp_utc: None (default) records the REAL current UTC time as
    YYYY-MM-DDTHH:MM:SSZ, so the record is honest about when it ran but its
    `content_hash` is NOT reproducible across runs. A caller-supplied value is
    used verbatim (schema-validated); pin it to get a reproducible
    `content_hash`. This is deliberate: the caller must choose."""
    if timestamp_utc is None:
        timestamp_utc = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    if isinstance(steps, bool) or not isinstance(steps, int) or steps < 0:
        raise ValueError("steps must be a nonnegative int")
    lr = _check_lr(lr)
    eta = _check_eta(eta)
    if x is not None:
        xm = as_matrix("x", x)
        if rows is not None and rows != len(xm):
            raise ValueError(f"rows={rows} contradicts supplied x with {len(xm)} rows")
        if width is not None and width != len(xm[0]):
            raise ValueError(f"width={width} contradicts supplied x with width {len(xm[0])}")
    else:
        rows, width = 4 if rows is None else rows, 3 if width is None else width
        for nm, v in (("rows", rows), ("width", width)):
            if isinstance(v, bool) or not isinstance(v, int) or v < 1:
                raise ValueError(f"{nm} must be a positive int")
        xm = make_inputs(seed, rows, width)
    if teacher is None:
        teacher = make_teacher(seed, len(xm[0]))
    elif not isinstance(teacher, Teacher):
        raise ValueError(f"teacher must be a Teacher instance, got {type(teacher).__name__}")
    params_snapshot = {k: tuple(v) for k, v in teacher.params.items()}
    mk = _check_mask(mask if mask is not None else (True,) * len(xm), len(xm))
    before = teacher.outputs(xm)
    target = erasure_target(before.conditioned, before.unconditioned, eta, rescale=rescale)
    rng = make_rng(derive_seed(seed, "student_init"))
    student = Student([rng.uniform(-0.5, 0.5) for _ in range(2 * len(xm[0]))])
    init_params = tuple(student.params)
    history = []
    for k in range(steps + 1):
        try:
            loss, grad = masked_mse_loss_and_grad(student.params, xm, target, mk, normalization)
        except ValueError as e:
            if k == 0:
                raise
            raise ValueError(f"training diverged at step {k} (numeric overflow: learning rate or input magnitude too large?): {e}") from None
        history.append((k, loss, math.hypot(*grad)))
        if k < steps:
            try:
                student.step(grad, lr)
            except ValueError as e:
                if str(e).startswith("diverged"):
                    raise ValueError(f"training diverged at step {k + 1} (non-finite parameters: learning rate or input magnitude too large?)") from None
                raise
    after = teacher.outputs(xm)
    # Tripwire: a frozen teacher cannot change; a stateful subclass could. Never record such a run.
    if after != before or {k: tuple(v) for k, v in teacher.params.items()} != params_snapshot:
        raise ValueError("teacher changed during training; the teacher must be frozen. Refusing to record this run")
    loss_increased = history[-1][1] > history[0][1]
    metrics = {"initial_loss": _finite_metric("initial_loss", history[0][1]),
               "final_loss": _finite_metric("final_loss", history[-1][1]),
               "final_grad_norm": _finite_metric("final_grad_norm", history[-1][2]),
               "loss_increased": MetricValue.measured(1.0 if loss_increased else 0.0)}
    config = _hash_json(
        {"steps": steps, "lr": lr, "eta": eta, "rescale": rescale, "normalization": normalization,
         "mask": list(mk), "teacher": {k: list(v) for k, v in teacher.params.items()}})
    prov = RunProvenance(
        # run_id embeds a config digest so differing configs of one seed do not share a run_id.
        run_id=f"toy-teacher-student-seed{seed}-{config[:12]}", timestamp_utc=timestamp_utc, seed=seed,
        code_version=CODE_VERSION, python_version=current_python_version(), toy_only=True,
        input_hashes={"x": _hash_json(xm), "config": config})
    record = ExperimentRecord(
        name="toy-teacher-student", provenance=prov, metrics=metrics,
        evidence_class=EvidenceClass.TOY_RESULT,
        notes=TOY_LABEL + " Abstract numeric analogue only; no claim about any real system."
        + (" WARNING: final loss exceeds initial loss (loss_increased=1.0); this run diverged or"
           " was not a converged training result." if loss_increased else ""))
    return TrainResult(tuple(history), tuple(student.params), before, after, record, loss_increased)
