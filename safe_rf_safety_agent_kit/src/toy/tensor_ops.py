"""SR-07: non-in-place numerical operations, a mutation detector, an autograd
in-place probe, and device/precision comparison scaffolding.

GENERIC NUMERIC TOOLING (abstract tensors; not a statement about the audited
program, RFdiffusion, or any safety property). Nothing here imports, runs or
models RFdiffusion. Nothing here patches or improves any generation or
fine-tuning code; it is test support for the audit (docs/ERROR_REGISTER.md ER-09
cross-device variance and ER-11 in-place mutation).

torch is OPTIONAL and imported under a guard, as in `toy.failure_modes`:
* the pure operations, the mutation detector (on lists/dicts/tuples) and the
  report types work without torch;
* `probe_inplace_autograd` needs torch and raises `TorchUnavailable` without it;
* `compare_across_*` without torch return an explicit UNMEASURED report (they do
  not raise and never fabricate a difference).

Evidence conventions
--------------------
A measured quantity is a `toy.schema.MetricValue.measured(x)`; a quantity that
could not be measured is `MetricValue.unmeasured(reason)`. An unmeasured
comparison is therefore never readable as a measured zero difference.

Autograd-safety summary of the pure ops (all verified in tests/toy_tests/test_tensor_ops.py)
-------------------------------------------------------------------------------------------
* `set_indices`  : `Tensor.index_put` (out-of-place). Autograd-safe: it records a
  new graph node; the input is neither modified nor version-bumped. Gradient to
  the input is zero at replaced positions; gradient to `values` flows if it
  requires grad.
* `masked_fill`  : `Tensor.masked_fill` (out-of-place). Autograd-safe; gradient
  to the input is zero at masked positions.
* `accumulate`   : `x + delta` (not `x += delta`). Autograd-safe; the input is
  not a modified saved tensor, so no version-counter error at backward().
* `normalize`    : overflow/underflow-safe `x / max(norm, eps)`. Autograd-safe. With
  eps == 0 an all-zero (or non-finite) input raises instead of yielding NaN.
* `clamp`        : `torch.clamp` (out-of-place). Autograd-safe, BUT the gradient
  is exactly zero for entries strictly outside the bounds (and 1 at x == bound):
  a clamp can silently kill gradient. NaN passes through unchanged (it is not clamped).
Each is non-mutating because it allocates its result; "does not mutate the
input" is checked by `detect_mutation` in the tests, not just asserted here.
"""
from __future__ import annotations

import copy
import math
from dataclasses import dataclass
from typing import Any, Callable, Optional, Sequence

try:  # guarded: a clean clone without torch must still import and pass.
    import torch  # type: ignore
    TORCH_AVAILABLE = True
except ImportError:  # includes ModuleNotFoundError and a blocked import
    torch = None  # type: ignore
    TORCH_AVAILABLE = False

from .schema import MetricValue

LABEL = "GENERIC NUMERIC CHECK (abstract tensors; not a statement about the audited program or any safety property)"


class TorchUnavailable(RuntimeError):
    """Raised by torch-only functions when torch cannot be imported."""


class TensorOpError(ValueError):
    """Invalid argument to a pure operation (bad mask, bad index, zero norm, ...)."""


def _require_torch() -> None:
    if not TORCH_AVAILABLE:
        raise TorchUnavailable("torch is not importable; this function needs it")


def _is_tensor(x: Any) -> bool:
    return TORCH_AVAILABLE and isinstance(x, torch.Tensor)


def _is_seq(x: Any) -> bool:
    return isinstance(x, (list, tuple))


def _rebuild(like: Any, items: list) -> Any:
    return tuple(items) if isinstance(like, tuple) else items


# =========================================================================
# 1. Pure (non-in-place) operations. Every one allocates and returns a new
#    object and leaves every argument untouched.
# =========================================================================
def _norm_indices(indices: Sequence[int], n: int) -> list[int]:
    out: list[int] = []
    for i in indices:
        if isinstance(i, bool) or not isinstance(i, int):
            raise TensorOpError(f"index must be int, got {type(i).__name__}")
        j = i + n if i < 0 else i
        if not 0 <= j < n:
            raise TensorOpError(f"index {i} out of range for length {n}")
        out.append(j)
    if len(set(out)) != len(out):
        # With duplicates, which value wins is unspecified in torch (and
        # nondeterministic on some devices), so refuse rather than guess.
        raise TensorOpError("duplicate indices: the winning value would be unspecified")
    return out


def _checked_cast(v: "torch.Tensor", dtype: "torch.dtype") -> "torch.Tensor":
    """Cast `v` to `dtype` or raise TensorOpError if the cast is lossy in kind or
    range: float -> int/bool (truncation), complex -> real, int out of the target
    range, or a finite value becoming inf. Ordinary rounding (0.1 -> float32) is
    allowed. Keeps autograd history of `v`."""
    if v.dtype == dtype:
        return v
    d = v.detach()
    if d.is_complex() and not dtype.is_complex:
        raise TensorOpError(f"refusing complex -> {dtype}")
    if dtype.is_floating_point or dtype.is_complex:
        c = d.to(dtype)
        if bool((torch.isfinite(d) & ~torch.isfinite(c)).any()):
            raise TensorOpError(f"value overflows {dtype} (finite became inf)")
        return v.to(dtype)
    if dtype == torch.bool:
        if d.dtype != torch.bool:
            raise TensorOpError(f"refusing {d.dtype} -> bool")
        return v
    if d.is_floating_point():
        raise TensorOpError(f"refusing silent truncation {d.dtype} -> {dtype}")
    c = d.to(dtype)
    if not bool((c.to(d.dtype) == d).all()):
        raise TensorOpError(f"value out of range for {dtype}")
    return v.to(dtype)


def set_indices(x: Any, indices: Sequence[int], values: Any) -> Any:
    """Out-of-place equivalent of `x[indices] = values` (first dimension).

    Works on list/tuple (returns a new list/tuple) and torch tensors (returns a
    new tensor). `values` is a scalar or has leading length len(indices).
    Raises TensorOpError on out-of-range, non-int or duplicate indices, on a
    length/shape mismatch, and on a lossy cast of `values` into the tensor's
    dtype (float -> int truncation, finite -> inf overflow, out-of-range int) (so an indexing error cannot become a silent no-op).
    An empty `indices` is legal and returns an equal copy.
    Autograd-safe for tensors: uses `index_put` (new graph node, no version bump).
    """
    if _is_tensor(x):
        if x.dim() == 0:
            raise TensorOpError("cannot index a 0-dim tensor")
        idx = _norm_indices(indices, x.shape[0])
        if _is_tensor(values):
            v = values
        else:
            try:
                v = torch.as_tensor(values)   # natural dtype, so a lossy cast is visible below
            except (RuntimeError, TypeError, ValueError, OverflowError) as e:
                raise TensorOpError(f"values not convertible to a tensor: {e}") from None
        if v.dim() > 0 and v.shape[0] != len(idx):
            raise TensorOpError(f"values length {v.shape[0]} != number of indices {len(idx)}")
        v = _checked_cast(v, x.dtype).to(x.device)
        target = (len(idx),) + tuple(x.shape[1:])
        try:
            v = v.expand(target)
        except RuntimeError:
            raise TensorOpError(f"values shape {tuple(v.shape)} not broadcastable to {target}") from None
        it = torch.as_tensor(idx, dtype=torch.long, device=x.device)
        return x.index_put((it,), v)
    if _is_seq(x):
        idx = _norm_indices(indices, len(x))
        out = list(x)
        if _is_seq(values):
            if len(values) != len(idx):
                raise TensorOpError(f"values length {len(values)} != number of indices {len(idx)}")
            for j, v in zip(idx, values):
                out[j] = v
        else:
            for j in idx:
                out[j] = values
        return _rebuild(x, out)
    raise TensorOpError(f"unsupported container {type(x).__name__}")


def _check_mask_list(mask: Any, n: int) -> None:
    if not _is_seq(mask) or any(not isinstance(m, bool) for m in mask):
        raise TensorOpError("mask must be a sequence of strict bool entries")
    if len(mask) != n:
        raise TensorOpError(f"mask length {len(mask)} != data length {n}")


def masked_fill(x: Any, mask: Any, value: Any) -> Any:
    """Out-of-place equivalent of `x[mask] = value` / `x.masked_fill_(mask, value)`.

    Mask must be strictly bool and have exactly the data's shape/length (no
    broadcasting, so a wrong-shaped mask raises instead of silently matching).
    An all-False mask is legal and returns an equal copy (a no-op that is
    reported by the *caller* if it matters; see `toy.stability` for strict
    empty-mask policy). Autograd-safe: gradient to `x` is zero where masked.
    """
    if _is_tensor(x):
        if not _is_tensor(mask) or mask.dtype != torch.bool:
            raise TensorOpError("mask must be a torch.bool tensor")
        if mask.shape != x.shape:
            raise TensorOpError(f"mask shape {tuple(mask.shape)} != data shape {tuple(x.shape)}")
        return x.masked_fill(mask, value)
    if _is_seq(x):
        _check_mask_list(mask, len(x))
        return _rebuild(x, [value if m else v for m, v in zip(mask, x)])
    raise TensorOpError(f"unsupported container {type(x).__name__}")


def accumulate(x: Any, delta: Any) -> Any:
    """Out-of-place equivalent of `x += delta`: returns `x + delta`.

    Shapes/lengths must match exactly unless `delta` is a Python scalar (no
    silent broadcasting). Autograd-safe: no tensor that autograd saved is
    modified, so no version-counter error at backward().
    """
    if _is_tensor(x):
        if _is_tensor(delta):
            if delta.shape != x.shape:
                raise TensorOpError(f"shape mismatch {tuple(x.shape)} vs {tuple(delta.shape)}")
        elif isinstance(delta, bool) or not isinstance(delta, (int, float)):
            raise TensorOpError(f"delta must be a tensor or a real scalar, got {type(delta).__name__}")
        return x + delta
    if _is_seq(x):
        if _is_seq(delta):
            if len(delta) != len(x):
                raise TensorOpError(f"length mismatch {len(x)} vs {len(delta)}")
            try:
                return _rebuild(x, [a + b for a, b in zip(x, delta)])
            except TypeError as e:
                raise TensorOpError(str(e)) from None
        try:
            return _rebuild(x, [a + delta for a in x])
        except TypeError as e:
            raise TensorOpError(str(e)) from None
    raise TensorOpError(f"unsupported container {type(x).__name__}")


def normalize(x: Any, eps: float = 0.0) -> Any:
    """Out-of-place equivalent of `x /= norm(x)` (L2 over the last dim / the list).

    The norm is computed after rescaling by the largest |element|, so a finite
    input never fails because of overflow (`[1e200, 1e200]`, f32 `1e30`) or
    underflow (`[1e-200, 1e-200]`, f32 `1e-25`) of the squared sum: those give
    the correct unit vector. eps == 0: the only thing that raises is a genuinely
    all-zero vector ("all-zero input") or a non-finite input; the in-place
    pattern would give NaN silently. eps > 0: the divisor is max(norm, eps), so
    a vector with 0 <= norm < eps is divided by eps (a zero vector maps to zeros,
    with gradient exactly 1/eps per element -- finite but large, 1e6 for
    eps=1e-6). Floating dtypes only for tensors; non-real list entries raise.
    Autograd-safe: the scale factor is a detached constant, which is exact
    because x/||x|| is scale invariant. The zero/finite check inspects
    `x.detach()` and forces a device sync on GPU.
    """
    if not isinstance(eps, (int, float)) or isinstance(eps, bool) or not eps >= 0 or math.isinf(eps):
        raise TensorOpError("eps must be a finite float >= 0")
    if _is_tensor(x):
        if not x.is_floating_point():
            raise TensorOpError(f"normalize needs a floating dtype, got {x.dtype}")
        if x.dim() == 0 or x.shape[-1] == 0:
            raise TensorOpError("normalize needs a non-empty last dimension")
        if not bool(torch.isfinite(x.detach()).all()):
            raise TensorOpError("non-finite input")
        m = x.detach().abs().amax(dim=-1, keepdim=True)
        if eps == 0.0 and bool((m == 0).any()):
            raise TensorOpError("all-zero input with eps=0 (norm is exactly zero)")
        m_safe = torch.where(m == 0, torch.ones_like(m), m)
        xs = x / m_safe
        n = torch.linalg.vector_norm(xs, dim=-1, keepdim=True).clamp_min(1.0)  # >= 1 whenever m > 0
        unit = xs / n
        if eps == 0.0:
            return unit
        small = (n.detach() * m) < eps          # true norm < eps (inf-safe: overflow compares False)
        x_small = torch.where(small, x, torch.zeros_like(x)) / eps   # no inf in the untaken branch
        return torch.where(small, x_small, unit)
    if _is_seq(x):
        if len(x) == 0:
            raise TensorOpError("empty vector")
        for v in x:
            if isinstance(v, bool) or not isinstance(v, (int, float)):
                raise TensorOpError(f"entries must be real numbers, got {type(v).__name__}")
        if any(not math.isfinite(v) for v in x):
            raise TensorOpError("non-finite input")
        m = max(abs(v) for v in x)
        if m == 0:
            if eps == 0.0:
                raise TensorOpError("all-zero input with eps=0 (norm is exactly zero)")
            return _rebuild(x, [v / eps for v in x])
        xs = [v / m for v in x]
        n = math.hypot(*xs)
        if eps > 0.0 and n * m < eps:
            return _rebuild(x, [v / eps for v in x])
        return _rebuild(x, [v / n for v in xs])
    raise TensorOpError(f"unsupported container {type(x).__name__}")


def clamp(x: Any, lo: Optional[float] = None, hi: Optional[float] = None) -> Any:
    """Out-of-place equivalent of `x.clamp_(lo, hi)`.

    At least one bound is required; lo > hi or a NaN bound raises. NaN entries
    pass through unchanged (so clamping does not hide NaN). Autograd-safe, with
    the caveat that the gradient is exactly 0 for entries STRICTLY outside
    [lo, hi] (clamped away) and exactly 1 for entries inside or ON a bound
    (x == lo or x == hi): with lo=0, hi=1 the gradients for [0, .5, 1, 2, -1]
    are [1, 1, 1, 0, 0] (measured on torch 2.7.1; boundary convention is a torch
    detail, not a guarantee).
    """
    if lo is None and hi is None:
        raise TensorOpError("clamp needs at least one bound")
    for b in (lo, hi):
        if b is not None and (isinstance(b, bool) or not isinstance(b, (int, float)) or math.isnan(b)):
            raise TensorOpError("bounds must be non-NaN real numbers")
    if lo is not None and hi is not None and lo > hi:
        raise TensorOpError(f"lo {lo} > hi {hi}")
    if _is_tensor(x):
        return torch.clamp(x, min=lo, max=hi)
    if _is_seq(x):
        def one(v):
            if isinstance(v, float) and math.isnan(v):
                return v
            if lo is not None and v < lo:
                v = lo
            if hi is not None and v > hi:
                v = hi
            return v
        return _rebuild(x, [one(v) for v in x])
    raise TensorOpError(f"unsupported container {type(x).__name__}")


# =========================================================================
# 2. In-place mutation detector
# =========================================================================
@dataclass(frozen=True)
class MutationFinding:
    location: str   # e.g. "args[0]", "kwargs['mask']", "args[1][2]"
    kind: str       # values_changed | version_bumped | values_changed+version_bumped |
                    # shape_changed | dtype_changed | structure_changed | object_changed
    detail: str


@dataclass(frozen=True)
class MutationReport:
    mutated: bool
    findings: tuple
    unchecked: tuple      # locations that could not be snapshotted/compared (honest gaps)
    raised: Optional[str]  # repr of an exception fn raised (mutation is still reported)
    result: Any
    label: str = LABEL

    @property
    def locations(self) -> tuple:
        return tuple(f.location for f in self.findings)


_MAX_DEPTH = 32
_SCALARS = (int, float, bool, complex, str, bytes, type(None))


def _bits(t: Any) -> "torch.Tensor":
    """Exact byte image (uint8 copy) of a tensor's values: distinguishes -0.0/+0.0
    and NaN payloads. Does not need numpy."""
    flat = t.detach().cpu().contiguous().reshape(-1).clone()
    return flat.view(torch.uint8) if flat.numel() else torch.zeros(0, dtype=torch.uint8)


def _tensor_meta(t: Any) -> tuple:
    """Autograd/metadata state that value+version snapshots cannot see."""
    hooks = getattr(t, "_backward_hooks", None)
    g = t.grad if t.is_leaf or t.retains_grad else None
    try:
        gsnap = None if g is None else (id(g), g._version, tuple(g.shape), _bits(g))
    except Exception:  # noqa: BLE001
        gsnap = (id(g), None, None, None)
    try:
        names = t.names
    except Exception:  # noqa: BLE001
        names = None
    try:
        ptr = t.untyped_storage().data_ptr()
    except Exception:  # noqa: BLE001
        ptr = None
    return {"requires_grad": t.requires_grad, "grad": gsnap, "hooks": len(hooks) if hooks else 0,
            "grad_fn": t.grad_fn, "names": names, "stride": tuple(t.stride()) if t.layout == torch.strided else None,
            "storage_ptr": ptr, "device": str(t.device)}


def _snap(obj: Any, path: str, out: dict, unchecked: list, depth: int = 0, seen: Optional[set] = None) -> None:
    seen = set() if seen is None else seen
    if depth > _MAX_DEPTH or id(obj) in seen:
        unchecked.append(path + " (depth limit or cycle: not walked)")
        return
    if _is_tensor(obj):
        try:
            version = obj._version
        except RuntimeError:  # inference tensors have no version counter
            version = None
        try:
            data = _bits(obj)
        except Exception:  # noqa: BLE001 - exotic dtypes/devices: record the gap
            data = None
            unchecked.append(path + " (values not snapshotable)")
        out[path] = ("tensor", version, tuple(obj.shape), obj.dtype, data, _tensor_meta(obj))
        return
    if isinstance(obj, _SCALARS):
        # type + repr, NOT ==: distinguishes 1 / 1.0 / True and 0.0 / -0.0, and NaN == NaN
        out[path] = ("scalar", type(obj), repr(obj))
        return
    if isinstance(obj, (list, tuple)):
        seen = seen | {id(obj)}
        out[path] = ("seq", type(obj), len(obj))
        for i, v in enumerate(obj):
            _snap(v, f"{path}[{i}]", out, unchecked, depth + 1, seen)
        return
    if isinstance(obj, dict):
        seen = seen | {id(obj)}
        out[path] = ("dict", tuple(map(repr, obj.keys())))
        for k, v in obj.items():
            _snap(v, f"{path}[{k!r}]", out, unchecked, depth + 1, seen)
        return
    if type(obj).__eq__ is object.__eq__:
        # No value equality to compare with (plain classes, nn.Module, iterators...):
        # say so instead of guessing "changed" or "clean".
        unchecked.append(path + f" (opaque {type(obj).__name__}: no value equality, not compared)")
        return
    try:
        out[path] = ("object", copy.deepcopy(obj))
        unchecked.append(path + f" ({type(obj).__name__} compared with == only: may miss type/sign-of-zero changes)")
    except Exception:  # noqa: BLE001
        unchecked.append(path + " (not copyable)")


def _diff(before: dict, after: dict, live: dict, unchecked: list) -> list:
    findings = []
    for path, b in before.items():
        a = after.get(path)
        if a is None:
            findings.append(MutationFinding(path, "structure_changed", "element removed"))
            continue
        if b[0] != a[0]:
            findings.append(MutationFinding(path, "structure_changed", f"{b[0]} became {a[0]}"))
        elif b[0] == "tensor":
            _, v0, s0, d0, x0, m0 = b
            _, v1, s1, d1, x1, m1 = a
            if s0 != s1:
                findings.append(MutationFinding(path, "shape_changed", f"{s0} -> {s1}"))
            elif d0 != d1:
                findings.append(MutationFinding(path, "dtype_changed", f"{d0} -> {d1}"))
            else:
                vals = x0 is not None and x1 is not None and not torch.equal(x0, x1)
                ver = v0 is not None and v1 is not None and v0 != v1
                if vals and ver:
                    findings.append(MutationFinding(path, "values_changed+version_bumped", f"_version {v0} -> {v1}"))
                elif vals:
                    findings.append(MutationFinding(path, "values_changed", "values differ; _version unchanged"))
                elif ver:
                    findings.append(MutationFinding(path, "version_bumped",
                                                    f"_version {v0} -> {v1}; values identical (value-neutral or restored write)"))
            changed = []
            for k in m0:
                if k == "grad":
                    g0, g1 = m0[k], m1[k]
                    same = (g0 is None and g1 is None) or (
                        g0 is not None and g1 is not None and g0[0] == g1[0] and g0[1] == g1[1] and g0[2] == g1[2]
                        and (g0[3] is None or g1[3] is None or torch.equal(g0[3], g1[3])))
                elif k == "grad_fn":
                    same = m0[k] is m1[k]
                else:
                    same = m0[k] == m1[k]
                if not same:
                    changed.append(k)
            if changed:
                findings.append(MutationFinding(path, "metadata_changed", "changed: " + ", ".join(changed)))
        elif b[0] == "scalar":
            if b[1:] != a[1:]:
                findings.append(MutationFinding(path, "object_changed", f"{b[1].__name__} {b[2]} -> {a[1].__name__} {a[2]}"))
        elif b[0] == "seq":
            if b[1:] != a[1:]:
                findings.append(MutationFinding(path, "structure_changed", f"{b[1:]} -> {a[1:]}"))
        elif b[0] == "dict":
            if b[1] != a[1]:
                findings.append(MutationFinding(path, "structure_changed", "dict keys changed"))
        else:  # object with custom __eq__: pre-call deep copy vs the live object after
            try:
                same = b[1] == live[path]
                if not isinstance(same, bool):
                    raise TypeError("ambiguous comparison")
            except Exception:  # noqa: BLE001
                unchecked.append(path + " (== not usable)")
                continue
            if not same:
                findings.append(MutationFinding(path, "object_changed", "== comparison differs from pre-call copy"))
    changed = [f.location for f in findings if f.kind == "structure_changed"]
    for path in after:
        if path not in before and not any(path.startswith(c + "[") for c in changed):
            findings.append(MutationFinding(path, "structure_changed", "element added"))
    return findings


def _collect_live(obj: Any, path: str, live: dict, depth: int = 0) -> None:
    if depth > _MAX_DEPTH or _is_tensor(obj) or isinstance(obj, _SCALARS):
        return
    if isinstance(obj, (list, tuple)):
        for i, v in enumerate(obj):
            _collect_live(v, f"{path}[{i}]", live, depth + 1)
    elif isinstance(obj, dict):
        for k, v in obj.items():
            _collect_live(v, f"{path}[{k!r}]", live, depth + 1)
    else:
        live[path] = obj


def detect_mutation(fn: Callable[..., Any], *args: Any, **kwargs: Any) -> MutationReport:
    """Call `fn(*args, **kwargs)` and report which inputs it mutated and how.

    Signals for torch tensors, and their LIMITS (all exercised in the tests):
    * `_version` counter: bumped by every in-place op through the autograd-aware
      API, even one that writes identical values or is later undone
      (`x.mul_(2).div_(2)`). NOT bumped by writes through `x.data`, by writes
      through a `.numpy()` view, or on inference tensors (no counter).
    * value snapshot (exact byte image taken before the call): catches any value
      change however it was made (`.data`, numpy view), distinguishing -0.0 and
      NaN payloads. It does NOT see a write that stores identical bytes, nor a
      mutate-then-restore. It costs a copy of every tensor input.
    * metadata snapshot (`metadata_changed`): `requires_grad`, `.grad` (identity,
      version and values: catches `x.grad = None`, `x.grad = fresh`,
      `x.grad.zero_()`), number of tensor backward hooks (`register_hook`),
      `grad_fn` identity (`detach_`), dim names (`rename_`), strides, storage
      pointer and device.
    Using these, `version_bumped` alone means "an in-place op ran, values equal";
    `values_changed` alone means "changed behind autograd's back".
    Shape/dtype changes (`resize_`, `set_`) are reported separately.
    Lists/tuples/dicts are walked recursively (tuples can't be mutated but the
    tensors inside them can). Builtin scalars (int, float, bool, complex, str,
    bytes, None) are compared by type AND repr, so 1 -> 1.0, 1 -> True and
    0.0 -> -0.0 are changes and NaN is equal to itself.
    NOT DETECTED / listed in `unchecked` instead of called clean:
    * objects with no value equality (plain classes, nn.Module, iterators): not
      compared at all;
    * other objects that define `==`: compared with `==` only (can miss
      type or sign-of-zero changes) and flagged as such;
    * cycles and nesting deeper than 32;
    * tensors reachable only through attributes of objects, global state, hooks
      registered on `grad_fn`, and anything fn does after returning.
    If fn raises, the exception is recorded in `raised` and mutation that
    happened before the raise is still reported (it is not re-raised).
    """
    unchecked: list = []
    before: dict = {}
    roots = [(f"args[{i}]", a) for i, a in enumerate(args)] + [(f"kwargs[{k!r}]", v) for k, v in kwargs.items()]
    for path, obj in roots:
        _snap(obj, path, before, unchecked)
    raised = None
    result = None
    try:
        result = fn(*args, **kwargs)
    except Exception as exc:  # noqa: BLE001 - recorded, see docstring
        raised = f"{type(exc).__name__}: {exc}"
    after: dict = {}
    live: dict = {}
    scratch: list = []
    for path, obj in roots:
        _snap(obj, path, after, scratch)
        _collect_live(obj, path, live)
    findings = _diff(before, after, live, unchecked)
    return MutationReport(mutated=bool(findings), findings=tuple(findings),
                          unchecked=tuple(dict.fromkeys(unchecked)), raised=raised, result=result)


# =========================================================================
# 3. Autograd in-place probe
# =========================================================================
@dataclass(frozen=True)
class ProbeCase:
    name: str
    target_is_leaf: bool
    target_requires_grad: bool
    write_raised: bool
    write_exception: Optional[str]
    write_message: Optional[str]
    version_before: int
    version_after: int
    backward_raised: Optional[bool]       # None: backward not attempted (write raised)
    backward_exception: Optional[str]
    backward_message: Optional[str]
    grad: Optional[tuple]                 # leaf .grad after backward, if it succeeded
    note: str


@dataclass(frozen=True)
class InplaceAutogradEvidence:
    torch_version: str
    cases: tuple
    label: str = LABEL

    def case(self, name: str) -> ProbeCase:
        for c in self.cases:
            if c.name == name:
                return c
        raise KeyError(name)


def _first_line(exc: BaseException) -> str:
    return (str(exc).splitlines() or [""])[0][:240]


def probe_inplace_autograd() -> InplaceAutogradEvidence:
    """Structured evidence on in-place writes versus autograd, on abstract tensors.

    Relation to the audit: ER-11 (in-place mutation relevant to autograd) and
    SR-02's finding that `x_t_student` is a grad-requiring LEAF that
    `_preprocess` modifies in place, cloning only in the `else` branch. This
    probe reproduces only the generic rule, not the program: writing in place
    into a grad-requiring leaf (or a view of one) RAISES RuntimeError at the
    write, whereas the same write on a non-leaf does not raise at the write and
    is only caught later, at backward(), if a tensor autograd saved was
    modified. Whether the audited code reaches the raising path depends on how
    its tensor was produced; this module cannot decide that and does not run it.

    Cases (each is recorded, none asserted here; tests assert them):
      leaf_setitem / leaf_add_          raise at the write.
      leaf_view_setitem                 a view of a leaf is itself non-leaf yet still raises.
      leaf_inplace_under_no_grad        write allowed (the optimizer pattern) and silently
                                        changes the leaf; a graph built before it then fails at backward().
      nonleaf_inplace_not_saved         no error anywhere; gradient still correct.
      nonleaf_inplace_saved             no error at the write; RuntimeError at backward().
      clone_then_setitem_on_leaf        the safe pattern (clone, then write): no error, leaf untouched.
    Exception text is torch-version dependent; `torch_version` is recorded.
    """
    _require_torch()
    cases: list[ProbeCase] = []

    def leaf() -> "torch.Tensor":
        return torch.tensor([1.0, 2.0, 3.0], requires_grad=True)

    def run(name, target, write, build_graph=None, note="", leaf_ref=None):
        v0 = target._version
        w_exc = None
        try:
            write()
        except RuntimeError as e:
            w_exc = e
        v1 = target._version
        b_raised: Optional[bool] = None
        b_exc = None
        grad = None
        if w_exc is None and build_graph is not None:
            b_raised = False
            try:
                build_graph().backward()
            except RuntimeError as e:
                b_raised, b_exc = True, e
            if not b_raised and leaf_ref is not None and leaf_ref.grad is not None:
                grad = tuple(leaf_ref.grad.tolist())
        cases.append(ProbeCase(
            name=name, target_is_leaf=target.is_leaf, target_requires_grad=target.requires_grad,
            write_raised=w_exc is not None, write_exception=type(w_exc).__name__ if w_exc else None,
            write_message=_first_line(w_exc) if w_exc else None,
            version_before=v0, version_after=v1, backward_raised=b_raised,
            backward_exception=type(b_exc).__name__ if b_exc else None,
            backward_message=_first_line(b_exc) if b_exc else None, grad=grad, note=note))

    x = leaf()
    run("leaf_setitem", x, lambda: x.__setitem__(0, 5.0), note="in-place index write into a grad-requiring leaf")
    x = leaf()
    run("leaf_add_", x, lambda: x.add_(1.0), note="in-place add on a grad-requiring leaf")
    x = leaf()
    view = x[:2]
    run("leaf_view_setitem", view, lambda: view.__setitem__(0, 5.0),
        note="view of a leaf: not a leaf itself, still rejected")

    x = leaf()
    z_graph = (x * x).sum()

    def under_no_grad():
        with torch.no_grad():
            x.add_(1.0)
    run("leaf_inplace_under_no_grad", x, under_no_grad, build_graph=lambda: z_graph, leaf_ref=x,
        note="no_grad bypasses the leaf check; the earlier graph saved x, which was then modified")

    x = leaf()
    y = x * 2
    z = y.sum()
    run("nonleaf_inplace_not_saved", y, lambda: y.add_(1.0), build_graph=lambda: z, leaf_ref=x,
        note="sum() saves nothing from y, so modifying y is not detected (and not harmful here)")

    x = leaf()
    y = x * 2
    z = (y * y).sum()
    run("nonleaf_inplace_saved", y, lambda: y.add_(1.0), build_graph=lambda: z, leaf_ref=x,
        note="mul saved y; y modified afterwards -> version-counter error at backward")

    x = leaf()
    c = x.clone()
    run("clone_then_setitem_on_leaf", c, lambda: c.__setitem__(0, 5.0),
        build_graph=lambda: c.sum(), leaf_ref=x,
        note="clone first: write targets a non-leaf copy; the leaf is untouched")
    return InplaceAutogradEvidence(torch_version=torch.__version__, cases=tuple(cases))


# =========================================================================
# 4. Device / dtype comparison scaffolding
# =========================================================================
def device_status(device: str) -> tuple[bool, str]:
    """(available, reason). 'mps' is reported available only if a tiny op really
    runs on it; 'cuda' only if torch reports a device."""
    if not TORCH_AVAILABLE:
        return False, "torch not installed"
    try:
        kind = torch.device(device).type
    except (RuntimeError, TypeError, ValueError) as e:
        return False, f"invalid device {device!r}: {e}"
    if kind == "cpu":
        return True, "cpu always available"
    if kind == "cuda":
        if torch.cuda.is_available():
            return True, "cuda reported available"
        return False, "CUDA not available on this machine (ER-09 CPU-vs-CUDA comparison is UNKNOWN)"
    if kind == "mps":
        if not (hasattr(torch.backends, "mps") and torch.backends.mps.is_available()):
            return False, "MPS not available on this machine"
        try:
            ok = bool((torch.ones(2, device=device) * 2).sum().item() == 4.0)
        except Exception as e:  # noqa: BLE001
            return False, f"MPS reported available but a probe op failed: {e}"
        return (True, "mps available (tiny op verified)") if ok else (False, "MPS probe op gave wrong value")
    return False, f"device type {kind!r} not supported by this scaffold"


def device_available(device: str) -> bool:
    return device_status(device)[0]


@dataclass(frozen=True)
class PairComparison:
    reference: str
    candidate: str
    measured: bool
    max_abs_diff: MetricValue
    max_rel_diff: MetricValue   # max|a-b| / max|reference| (max-norm relative; see compare docs)
    bitwise_identical: Optional[bool]  # None when not measured
    reason: Optional[str]              # why not measured, or a caveat


@dataclass(frozen=True)
class ComparisonReport:
    kind: str                  # "device" | "dtype"
    reference: Optional[str]
    pairs: tuple               # PairComparison
    skipped: tuple             # (label, reason) pairs for configs that could not run
    unmeasured_reason: Optional[str] = None  # set when nothing at all was measured
    label: str = LABEL

    @property
    def n_measured(self) -> int:
        return sum(1 for p in self.pairs if p.measured)

    @property
    def measured(self) -> bool:
        return self.n_measured > 0

    def _agg(self, attr: str) -> MetricValue:
        vals = [getattr(p, attr).value for p in self.pairs if p.measured]
        if not vals:
            return MetricValue.unmeasured(self.unmeasured_reason or "no comparison pair was measured")
        return MetricValue.measured(float(max(vals)))

    @property
    def max_abs_diff(self) -> MetricValue:
        return self._agg("max_abs_diff")

    @property
    def max_rel_diff(self) -> MetricValue:
        return self._agg("max_rel_diff")

    @property
    def bitwise_identical(self) -> Optional[bool]:
        """None when nothing was measured (NOT False and NOT True)."""
        ms = [p.bitwise_identical for p in self.pairs if p.measured]
        return all(ms) if ms else None


def _unmeasured_report(kind: str, reference: Optional[str], reason: str, skipped=(), pairs=()) -> ComparisonReport:
    return ComparisonReport(kind=kind, reference=reference, pairs=tuple(pairs), skipped=tuple(skipped),
                            unmeasured_reason=reason)


def _flat_one(o: Any) -> "torch.Tensor":
    if not _is_tensor(o):
        raise TensorOpError(f"output element must be a tensor, got {type(o).__name__}")
    if o.is_complex():
        # .to(float64) would silently drop the imaginary part
        raise TensorOpError("complex output not supported: the imaginary part would be lost")
    if not o.is_floating_point():
        # int64 > 2**53 would lose low bits in float64, bool/int are not 'numeric' comparisons here
        raise TensorOpError(f"non-floating output dtype {o.dtype} not supported (cast would hide differences)")
    return o.detach().cpu().to(torch.float64).reshape(-1)


def _flatten64(out: Any) -> "torch.Tensor":
    """Real floating, non-empty outputs only; anything else raises TensorOpError
    (callers record that as an unmeasured configuration, never as a zero difference)."""
    if _is_tensor(out):
        flat = _flat_one(out)
    elif _is_seq(out) and out:
        flat = torch.cat([_flat_one(o) for o in out])
    else:
        raise TensorOpError(f"fn must return a tensor or a non-empty sequence of tensors, got {type(out).__name__}")
    if flat.numel() == 0:
        raise TensorOpError("empty output: nothing to compare")
    return flat


def _prepare(inputs: Sequence[Any], device: Any = None, dtype: Any = None) -> list:
    out = []
    for a in inputs:
        if _is_tensor(a):
            t = a.detach().clone()   # clone so a same-device .to() can never alias the caller's tensor
            if dtype is not None and t.is_floating_point():
                t = t.to(dtype)
            if device is not None:
                t = t.to(device)
            out.append(t)
        else:
            out.append(copy.deepcopy(a))
    return out


def _compare_pair(ref_label: str, cand_label: str, ref: "torch.Tensor", cand: "torch.Tensor") -> PairComparison:
    def unm(reason):
        return PairComparison(ref_label, cand_label, False, MetricValue.unmeasured(reason),
                              MetricValue.unmeasured(reason), None, reason)
    if ref.numel() == 0 or cand.numel() == 0:
        return unm("empty output: nothing to compare")
    if ref.shape != cand.shape:
        return unm(f"output shape mismatch {tuple(ref.shape)} vs {tuple(cand.shape)}")
    if not (bool(torch.isfinite(ref).all()) and bool(torch.isfinite(cand).all())):
        return unm("non-finite values in an output; difference not computed")
    diff = (ref - cand).abs()
    max_abs = float(diff.max()) if diff.numel() else 0.0
    scale = float(ref.abs().max()) if ref.numel() else 0.0
    if max_abs == 0.0:
        rel = 0.0
    elif scale == 0.0:
        return unm("reference is identically zero but outputs differ; relative difference undefined")
    else:
        rel = max_abs / scale
    identical = bool(torch.equal(ref.view(torch.int64), cand.view(torch.int64)))
    return PairComparison(ref_label, cand_label, True, MetricValue.measured(max_abs),
                          MetricValue.measured(rel), identical, None)


def _compare_generic(kind: str, fn, inputs, configs: list, make_inputs) -> ComparisonReport:
    """configs: list of (label, availability_reason_or_None, kwargs-for-make_inputs)."""
    results: list = []   # (label, flat64 tensor)
    skipped: list = []
    for label, unavailable, kw in configs:
        if unavailable is not None:
            skipped.append((label, unavailable))
            continue
        try:
            out = fn(*make_inputs(**kw))
            results.append((label, _flatten64(out)))
        except Exception as e:  # noqa: BLE001 - reported, not swallowed silently
            skipped.append((label, f"fn raised {type(e).__name__}: {_first_line(e)}"))
    ref_label = configs[0][0]
    if not results or results[0][0] != ref_label:
        return _unmeasured_report(kind, ref_label, f"reference {ref_label!r} could not be run", skipped)
    if len(results) < 2:
        why = "; ".join(f"{l}: {r}" for l, r in skipped) or "no other configuration requested"
        return _unmeasured_report(kind, ref_label, f"no cross-{kind} comparison possible ({why})", skipped)
    pairs = [_compare_pair(ref_label, lab, results[0][1], r) for lab, r in results[1:]]
    return ComparisonReport(kind=kind, reference=ref_label, pairs=tuple(pairs), skipped=tuple(skipped),
                            unmeasured_reason=None if any(p.measured for p in pairs) else
                            "; ".join(p.reason or "" for p in pairs))


def compare_across_devices(fn: Callable[..., Any], inputs: Sequence[Any], devices: Sequence[str]) -> ComparisonReport:
    """Run `fn(*inputs)` on each device and compare each result to the FIRST device's.

    Inputs are detached, cloned and moved per device (the caller's tensors are
    never touched or aliased). Differences are computed in float64 on CPU:
    max_abs_diff = max|a-b|; max_rel_diff = max|a-b| / max|reference|
    (max-norm relative, which stays finite where an elementwise ratio would not);
    bitwise_identical = identical float64 byte images of the results.

    Honesty rules: duplicate devices collapse to one; an unavailable device, or
    one where `fn` raises (for example float64 on MPS), is listed in `.skipped`
    with a reason and is NOT compared; with fewer than two comparable devices
    the report is UNMEASURED (`max_abs_diff` is MetricValue.unmeasured,
    `bitwise_identical` is None), never a zero difference. If the first
    (reference) device cannot run, nothing is measured. Without torch the
    report is unmeasured too. Non-finite outputs make that pair unmeasured.
    """
    seen: list = []
    for d in devices:
        if d not in seen:
            seen.append(d)
    if not seen:
        return _unmeasured_report("device", None, "no devices requested")
    if not TORCH_AVAILABLE:
        return _unmeasured_report("device", seen[0], "torch not installed",
                                  skipped=[(d, "torch not installed") for d in seen])
    configs = []
    for d in seen:
        ok, why = device_status(d)
        configs.append((d, None if ok else why, {"device": d}))
    return _compare_generic("device", fn, inputs, configs, lambda device: _prepare(inputs, device=device))


def compare_across_dtypes(fn: Callable[..., Any], inputs: Sequence[Any], dtypes: Sequence[Any],
                          device: str = "cpu") -> ComparisonReport:
    """Run `fn` with floating inputs cast to each dtype; compare to the FIRST dtype.

    List the higher-precision dtype first (e.g. float64, float32) so it is the
    reference. Dtypes may be torch dtypes or names ('float32'). Input rounding
    (casting float64 inputs down) is part of the measured difference, by design.
    Everything in `compare_across_devices` about reporting applies. A float32 vs
    float64 gap is NOT a defect by itself: it is a quantified sensitivity of
    `fn` to precision on these inputs. A large gap marks an ill-conditioned
    computation; a small one on one fixture says nothing about another.
    """
    if not TORCH_AVAILABLE:
        return _unmeasured_report("dtype", None, "torch not installed")
    resolved = []
    for d in dtypes:
        dt = getattr(torch, d) if isinstance(d, str) else d
        if not isinstance(dt, torch.dtype) or not dt.is_floating_point:
            raise TensorOpError(f"not a floating torch dtype: {d!r}")
        if dt not in resolved:
            resolved.append(dt)
    if not resolved:
        return _unmeasured_report("dtype", None, "no dtypes requested")
    ok, why = device_status(device)
    configs = [(str(dt).replace("torch.", ""), None if ok else why, {"dtype": dt}) for dt in resolved]
    return _compare_generic("dtype", fn, inputs, configs, lambda dtype: _prepare(inputs, device=device, dtype=dtype))


# =========================================================================
# 5. Precision fixtures (generic; chosen so the float32/float64 gap is real
#    for the first two and small for the control)
# =========================================================================
def cancellation_inputs(n: int = 64) -> list:
    """float64 values spaced in [1e-9, 1e-7]."""
    _require_torch()
    return [torch.linspace(1e-9, 1e-7, n, dtype=torch.float64)]


def fixture_cancellation(x: "torch.Tensor") -> "torch.Tensor":
    """(1 + x) - 1. Mathematically x. In float32 (eps ~ 1.2e-7) 1 + x for
    x < 6e-8 rounds to exactly 1, so the result is 0 for the smallest entries
    and quantised in steps of ~1.2e-7 elsewhere: catastrophic cancellation."""
    return (x + 1.0) - 1.0


def accumulation_inputs(n: int = 50000) -> list:
    _require_torch()
    return [torch.full((n, 1), 0.1, dtype=torch.float64)]


def fixture_sequential_accumulation(x: "torch.Tensor") -> "torch.Tensor":
    """Left-to-right running sum of the rows (explicit order, so the result
    does not depend on a library's reduction tree). Rounding error grows as the
    accumulator grows; float32 drifts visibly from float64 after ~5e4 terms."""
    acc = torch.zeros(x.shape[1], dtype=x.dtype, device=x.device)
    for row in x.unbind(0):
        acc = acc + row
    return acc


def wellconditioned_inputs(n: int = 1000) -> list:
    _require_torch()
    return [torch.sin(torch.arange(n, dtype=torch.float64) * 0.37)]


def fixture_wellconditioned(x: "torch.Tensor") -> "torch.Tensor":
    """Control: sum of squares of O(1) values. Positive terms, no cancellation:
    float32 and float64 should agree to ~1e-6 relative."""
    return (x * x).sum().reshape(1)


def kabsch_rotation(p: "torch.Tensor", q: "torch.Tensor") -> "torch.Tensor":
    """Generic Procrustes/Kabsch rotation R minimising ||(p - mean) R^T - (q - mean)||
    for (N, 3) point sets, via SVD with a determinant sign fix. This is the
    battery item ER-09 asks for, on abstract point sets. Returns R (3x3), which is
    unique when the sets are well spread; for (near-)collinear sets it is
    ill-determined and float32/float64 (or devices) may legitimately disagree."""
    pc = p - p.mean(0, keepdim=True)
    qc = q - q.mean(0, keepdim=True)
    u, _, vh = torch.linalg.svd(pc.T @ qc)
    d = torch.sign(torch.linalg.det(u @ vh))
    d = torch.where(d == 0, torch.ones_like(d), d)
    s = torch.diag(torch.stack([torch.ones_like(d), torch.ones_like(d), d]))
    return (u @ s @ vh).T


def kabsch_inputs(n: int = 20, collinear: bool = False) -> list:
    """Deterministic point sets (no RNG): a fixed spread set and a rotated copy."""
    _require_torch()
    i = torch.arange(n, dtype=torch.float64)
    if collinear:
        p = torch.stack([i, 0.5 * i + 1e-7 * torch.sin(i), 0.25 * i], dim=1)
    else:
        p = torch.stack([torch.sin(i * 1.3), torch.cos(i * 0.7) * 2.0, torch.sin(i * 0.31 + 1.0) * 0.5 + i * 0.05], dim=1)
    a, b = 0.6, 0.4
    rz = torch.tensor([[math.cos(a), -math.sin(a), 0], [math.sin(a), math.cos(a), 0], [0, 0, 1]], dtype=torch.float64)
    rx = torch.tensor([[1, 0, 0], [0, math.cos(b), -math.sin(b)], [0, math.sin(b), math.cos(b)]], dtype=torch.float64)
    return [p, p @ (rz @ rx).T]


# =========================================================================
# 6. Determinism
# =========================================================================
@dataclass(frozen=True)
class RepeatabilityResult:
    runs: int
    bitwise_identical_all_runs: bool
    max_abs_spread: float


def check_repeatability(fn: Callable[..., Any], inputs: Sequence[Any], runs: int = 5,
                        device: str = "cpu") -> RepeatabilityResult:
    """Run `fn` `runs` times on identical inputs in this process and compare
    results bitwise. This is an EMPIRICAL observation of run-to-run repeatability
    for one process, thread count and machine. It is not a proof of determinism
    and says nothing about other machines, thread counts, torch builds or devices.
    Only REAL FLOATING outputs are accepted: complex, integer/bool and empty
    outputs raise TensorOpError. (An earlier version cast complex outputs to
    float64, dropping the imaginary part, and could certify a non-repeatable
    function as repeatable; the repeatability claims in DETERMINISM_CLAIMS were
    all established on float32 outputs and never relied on that path.)"""
    _require_torch()
    if runs < 2:
        raise TensorOpError("runs must be >= 2")
    outs = [_flatten64(fn(*_prepare(inputs, device=device))) for _ in range(runs)]
    if any(o.shape != outs[0].shape for o in outs[1:]):
        return RepeatabilityResult(runs, False, float("inf"))
    same = all(torch.equal(outs[0].view(torch.int64), o.view(torch.int64)) for o in outs[1:])
    spread = max(float((o - outs[0]).abs().max()) for o in outs[1:]) if outs[0].numel() else 0.0
    return RepeatabilityResult(runs, same, spread)


@dataclass(frozen=True)
class DeterminismClaim:
    op: str
    status: str        # "REPEATABLE_TESTED_ON_CPU" | "NOT_GUARANTEED"
    tested_here: bool  # True only if tests run check_repeatability (or a measurement) for it
    note: str


def _elementwise(x):
    return torch.exp(x) * 3.0 + x


def _reduce_sum(x):
    return x.sum().reshape(1)


def _matmul(a):
    return a @ a.T


def _svd_values(a):
    return torch.linalg.svdvals(a)


def _cumsum(x):
    return torch.cumsum(x, 0)


def _wide(n=4096) -> list:
    _require_torch()
    return [torch.sin(torch.arange(n * 4, dtype=torch.float32) * 0.01).reshape(n, 4)]


def _vec() -> list:
    _require_torch()
    return [torch.sin(torch.arange(100000, dtype=torch.float32) * 0.01)]


def determinism_cases() -> dict:
    """op -> (fn, inputs) for every claim marked tested_here with check_repeatability."""
    _require_torch()
    sq = [torch.sin(torch.arange(64 * 64, dtype=torch.float32).reshape(64, 64) * 0.01)]
    return {
        "elementwise_exp_mul_add": (_elementwise, _vec()),
        "sum_reduction_fixed_threads": (_reduce_sum, _vec()),
        "cumsum": (_cumsum, _vec()),
        "matmul_fixed_shape": (_matmul, sq),
        "svdvals": (_svd_values, sq),
    }


DETERMINISM_CLAIMS: tuple = (
    DeterminismClaim("elementwise_exp_mul_add", "REPEATABLE_TESTED_ON_CPU", True,
                     "bitwise identical across repeated runs in one process on this CPU; not claimed for other machines/builds"),
    DeterminismClaim("sum_reduction_fixed_threads", "REPEATABLE_TESTED_ON_CPU", True,
                     "repeatable at a fixed thread count; equality ACROSS thread counts is not guaranteed (tests measure it but do not require bit equality)"),
    DeterminismClaim("cumsum", "REPEATABLE_TESTED_ON_CPU", True, "repeatable run to run on this CPU"),
    DeterminismClaim("matmul_fixed_shape", "REPEATABLE_TESTED_ON_CPU", True,
                     "repeatable for a fixed shape/thread count; different shapes or BLAS builds may reorder sums"),
    DeterminismClaim("svdvals", "REPEATABLE_TESTED_ON_CPU", True,
                     "singular VALUES repeat run to run; singular VECTOR signs/ordering across devices or builds are not guaranteed (Kabsch uses sign-invariant U@Vh with a det fix)"),
    DeterminismClaim("sum_reduction_across_thread_counts", "NOT_GUARANTEED", True,
                     "reduction order may depend on thread count; the test records whether results happened to match, and bounds the difference"),
    DeterminismClaim("index_put_duplicate_indices", "NOT_GUARANTEED", False,
                     "which duplicate write wins is unspecified; set_indices rejects duplicates. Documented behaviour, not tested here"),
    DeterminismClaim("scatter_add_or_index_add_on_gpu", "NOT_GUARANTEED", False,
                     "GPU atomics make accumulation order nondeterministic (documented, not tested: no CUDA here)"),
    DeterminismClaim("any_op_across_devices_or_dtypes", "NOT_GUARANTEED", True,
                     "see compare_across_devices / compare_across_dtypes; only CPU float32/float64 and, if present, MPS are measured here"),
)
