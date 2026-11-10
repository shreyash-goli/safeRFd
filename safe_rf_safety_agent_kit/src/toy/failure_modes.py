"""SR-03: executable reproductions of generic numerical/software defect PATTERNS.

PATTERN DEMONSTRATIONS ONLY (abstract numbers; non-biological; no safety claim).

Each function below reproduces, in isolation and on abstract objects, one *class*
of defect that the SR-02 audit (docs/METHOD_AUDIT.md) identified in the audited
fork script by reading its text. Showing that a pattern misbehaves in isolation
does NOT establish that the audited program misbehaves at runtime: that would
require executing it, which is out of scope. Nothing here imports, runs,
simulates or models RFdiffusion, and nothing here says the method is broken or
safe. See docs/ERROR_REGISTER.md for classifications and limits.

Standard library by default. Functions needing autograd use torch, imported under
a guard so this module imports cleanly without it; those functions raise
`TorchUnavailable` when torch is absent. There is deliberately NO function for the
unrestricted-pickle-load concern (register entry ER-08): it is described in
prose only, and no payload is constructed or executed anywhere in this kit.
"""
from __future__ import annotations

import itertools
import math
from fractions import Fraction
from typing import Any, Sequence

try:  # guarded: a clean clone without torch must still import and pass.
    import torch  # type: ignore
    TORCH_AVAILABLE = True
except ImportError:  # includes ModuleNotFoundError and a blocked import
    torch = None  # type: ignore
    TORCH_AVAILABLE = False

LABEL = "PATTERN DEMONSTRATION (abstract numbers; not a statement about the audited program)"


class TorchUnavailable(RuntimeError):
    """Raised by torch-dependent demonstrations when torch cannot be imported."""


def _require_torch() -> None:
    if not TORCH_AVAILABLE:
        raise TorchUnavailable("torch is not importable; this demonstration needs autograd")


# ------------------------------------------------------------------ 1
def _loss_bare_exception(valid_count: int) -> float:
    if valid_count > 0:
        loss = 1.0
    else:
        RuntimeError  # noqa: B018 -- bare name, no `raise`: the defect pattern
    return loss


def _loss_with_raise(valid_count: int) -> float:
    if valid_count > 0:
        loss = 1.0
    else:
        raise RuntimeError("empty mask")
    return loss


def bare_exception_statement_is_a_no_op() -> dict[str, Any]:
    """`else: RuntimeError` (no `raise`) does nothing; the later use fails differently.

    Returns the exception types/messages actually observed for (a) the bare
    pattern with an empty mask, (b) a control that uses `raise`, (c) a positive
    control with a non-empty mask, and (d) evaluating the bare name / an
    un-raised exception object on its own.
    """
    out: dict[str, Any] = {"label": LABEL}

    # (d) the statement itself
    raised = False
    try:
        exec("RuntimeError", {})
        exec("RuntimeError('never raised')", {})
    except BaseException:  # pragma: no cover - would contradict the claim
        raised = True
    out["bare_statements_raised"] = raised

    # (a) the pattern
    try:
        _loss_bare_exception(0)
        out["bare_pattern_exception_type"] = None
        out["bare_pattern_message"] = None
    except Exception as exc:  # noqa: BLE001 - we record whatever type occurs
        out["bare_pattern_exception_type"] = type(exc).__name__
        out["bare_pattern_message"] = str(exc)
        out["bare_pattern_is_runtime_error"] = isinstance(exc, RuntimeError)
    # `except RuntimeError` would NOT catch it:
    out["unbound_local_is_subclass_of_runtime_error"] = issubclass(UnboundLocalError, RuntimeError)

    # (b) control
    try:
        _loss_with_raise(0)
        out["control_exception_type"] = None
        out["control_message"] = None
    except Exception as exc:  # noqa: BLE001
        out["control_exception_type"] = type(exc).__name__
        out["control_message"] = str(exc)

    # (c) positive control
    out["nonempty_mask_value"] = _loss_bare_exception(3)
    return out


# ------------------------------------------------------------------ 2
def nan_times_zero_is_nan(values: Sequence[float] = (1.0, float("nan"), 3.0),
                          keep: Sequence[bool] = (True, False, True)) -> dict[str, Any]:
    """Masking by multiplication keeps NaN (0*nan = nan); selection removes it.

    Also shows 0*inf = nan. `keep[i]` True means include element i.
    """
    if len(values) != len(keep):
        raise ValueError("values and keep must have equal length")
    weights = [1.0 if k else 0.0 for k in keep]
    nan = float("nan")
    by_multiplication = sum(v * w for v, w in zip(values, weights))
    by_selection = sum(v for v, k in zip(values, keep) if k)
    return {
        "label": LABEL,
        "zero_times_nan_is_nan": math.isnan(0.0 * nan),
        "zero_times_inf_is_nan": math.isnan(0.0 * float("inf")),
        "masked_element_product": [v * w for v, w in zip(values, weights)],
        "sum_by_multiplication": by_multiplication,
        "sum_by_multiplication_is_nan": math.isnan(by_multiplication),
        "sum_by_selection": by_selection,
        "sum_by_selection_is_nan": math.isnan(by_selection),
    }


# ------------------------------------------------------------------ 3
def detach_severs_gradient() -> dict[str, Any]:
    """A detached branch contributes no gradient to the parameter that made it (torch)."""
    _require_torch()
    x = torch.tensor([1.0, 2.0])
    w_detached = torch.tensor([0.5, 0.5], requires_grad=True)
    w_live = torch.tensor([0.5, 0.5], requires_grad=True)
    out = (w_detached * x).detach().sum() + (w_live * x).sum()
    out.backward()
    return {
        "label": LABEL,
        "out_requires_grad": bool(out.requires_grad),
        "detached_param_grad": None if w_detached.grad is None else w_detached.grad.tolist(),
        "live_param_grad": None if w_live.grad is None else w_live.grad.tolist(),
        "detached_branch_requires_grad": bool((w_detached * x).detach().requires_grad),
    }


# ------------------------------------------------------------------ 4
def _param_has_nonzero_grad(params: Sequence[Any]) -> bool:
    """The discriminating check: some parameter has a non-None, non-zero .grad."""
    return any(p.grad is not None and bool(p.grad.abs().sum() > 0) for p in params)


def input_leaf_requires_grad_does_not_prove_parameter_gradient() -> dict[str, Any]:
    """`out.requires_grad` can be True purely because an INPUT leaf requires grad (torch).

    Three tiny graphs, each with an input leaf `x` (requires_grad=True) and a
    parameter `w`:
      severed : w's contribution goes through .detach()  -> w.grad is None
      zeroed  : w is multiplied by 0.0                   -> w.grad is all zeros
      control : w genuinely feeds the output             -> w.grad nonzero
    In all three `out.requires_grad` is True, so an assertion of that form does
    not discriminate; `_param_has_nonzero_grad` does.
    """
    _require_torch()

    def build(kind: str):
        x = torch.tensor([1.0, 2.0], requires_grad=True)   # input leaf
        w = torch.tensor([0.5, 0.5], requires_grad=True)   # "parameter"
        if kind == "severed":
            out = (x * 2.0).sum() + (w * 3.0).detach().sum()
        elif kind == "zeroed":
            out = (x * 2.0).sum() + (0.0 * w).sum()
        elif kind == "control":
            out = (x * w).sum()
        else:  # pragma: no cover
            raise ValueError(kind)
        naive = bool(out.requires_grad)
        out.backward()
        return {
            "out_requires_grad": naive,
            "input_grad": None if x.grad is None else x.grad.tolist(),
            "param_grad": None if w.grad is None else w.grad.tolist(),
            "param_has_nonzero_grad": _param_has_nonzero_grad([w]),
        }

    return {"label": LABEL, **{k: build(k) for k in ("severed", "zeroed", "control")}}


# ------------------------------------------------------------------ 5
def normalization_mismatch_scale_factor(leading: int = 4,
                                        trailing: Sequence[int] = (14, 3)) -> dict[str, Any]:
    """Sum over leading*prod(trailing) elements, divide by `leading` only.

    The result equals the true per-element mean times prod(trailing), exactly
    (computed with Fractions so the equality is exact, not approximate).
    """
    if leading < 1 or any(t < 1 for t in trailing):
        raise ValueError("dimensions must be >= 1")
    k = 1
    for t in trailing:
        k *= t
    # deterministic integer "squared error" values, not all equal
    vals = [Fraction(1 + (i % 5)) for i in range(leading * k)]
    total = sum(vals, Fraction(0))
    divisor_omits_trailing = total / leading
    true_elem_mean = total / (leading * k)
    return {
        "label": LABEL,
        "leading": leading,
        "trailing": tuple(trailing),
        "expected_factor": k,
        "observed_factor": divisor_omits_trailing / true_elem_mean,
        "observed_factor_equals_expected_exactly": divisor_omits_trailing / true_elem_mean == k,
        "inflated_mean": divisor_omits_trailing,
        "true_element_mean": true_elem_mean,
    }


# ------------------------------------------------------------------ 6
def mask_polarity_inversion(squared_errors: Sequence[float] = (1.0, 4.0, 9.0, 16.0),
                            mask: Sequence[bool] = (True, False, True, False)) -> dict[str, Any]:
    """The same boolean mask read with opposite polarity selects the complement.

    Neither reading raises: with a non-degenerate mask both are valid-looking,
    so a polarity error is silent. (A mask that is all-True or all-False makes
    one reading empty; that is reported, not raised.)
    """
    if len(squared_errors) != len(mask):
        raise ValueError("squared_errors and mask must have equal length")
    idx_true_selects = [i for i, m in enumerate(mask) if m]
    idx_false_selects = [i for i, m in enumerate(mask) if not m]

    def mean_over(idx: list[int]) -> float | None:
        return sum(squared_errors[i] for i in idx) / len(idx) if idx else None

    return {
        "label": LABEL,
        "true_means_include_indices": idx_true_selects,
        "false_means_include_indices": idx_false_selects,
        "index_sets_disjoint": not set(idx_true_selects) & set(idx_false_selects),
        "index_sets_cover_all": sorted(idx_true_selects + idx_false_selects) == list(range(len(mask))),
        "loss_true_means_include": mean_over(idx_true_selects),
        "loss_false_means_include": mean_over(idx_false_selects),
        "losses_differ": mean_over(idx_true_selects) != mean_over(idx_false_selects),
        "raised": False,
    }


# ------------------------------------------------------------------ 7
def _global_norm(g: Sequence[float]) -> float:
    return math.sqrt(sum(v * v for v in g))


def gradient_clipping_hides_magnitude(max_norm: float = 1.0,
                                      raw_scales: Sequence[float] = (1e1, 1e3, 1e6, 1e9)
                                      ) -> dict[str, Any]:
    """Post-clip norm is bounded by `max_norm` however large the raw gradient is.

    Clips the vector (3, 4)*scale to global norm <= max_norm (stdlib). All post-
    clip norms are ~max_norm, so a logged post-clip norm cannot distinguish a
    benign problem from an exploding one. If torch is present, also records that
    `torch.nn.utils.clip_grad_norm_` RETURNS the pre-clip norm (so which value a
    log records matters); otherwise that field is None.
    """
    rows = []
    for s in raw_scales:
        g = [3.0 * s, 4.0 * s]
        pre = _global_norm(g)
        factor = min(1.0, max_norm / (pre + 1e-6))
        post = _global_norm([v * factor for v in g])
        rows.append({"raw_scale": s, "pre_clip_norm": pre, "post_clip_norm": post})
    torch_check = None
    if TORCH_AVAILABLE:
        p = torch.nn.Parameter(torch.zeros(2))
        p.grad = torch.tensor([3e3, 4e3])
        returned = float(torch.nn.utils.clip_grad_norm_([p], max_norm))
        torch_check = {"returned_by_clip_grad_norm": returned,
                       "norm_after_clipping": float(p.grad.norm())}
    return {
        "label": LABEL,
        "max_norm": max_norm,
        "rows": rows,
        "post_clip_norms_all_bounded": all(r["post_clip_norm"] <= max_norm + 1e-9 for r in rows),
        "pre_clip_norm_span": rows[-1]["pre_clip_norm"] / rows[0]["pre_clip_norm"],
        "torch_check": torch_check,
        "note": "bounded post-clip norm is not evidence of a well-conditioned problem",
    }


# ------------------------------------------------------------------ 8
# Intentionally absent: `unrestricted_load_executes_arbitrary_code`. Per charter
# and task constraints it is documented statically only (docs/ERROR_REGISTER.md,
# ER-08); no payload is constructed and no file that executes on load is written.

PATTERN_FUNCTIONS = {
    "ER-01": "bare_exception_statement_is_a_no_op",
    "ER-02": "nan_times_zero_is_nan",
    "ER-03": "detach_severs_gradient",
    "ER-04": "input_leaf_requires_grad_does_not_prove_parameter_gradient",
    "ER-05": "normalization_mismatch_scale_factor",
    "ER-06": "mask_polarity_inversion",
    "ER-07": "gradient_clipping_hides_magnitude",
}
