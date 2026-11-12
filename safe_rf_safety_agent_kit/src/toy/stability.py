"""SR-06: strict, generic numeric validators for the toy pipeline.

TOY / TEST-SUPPORT module. Standard library only. Abstract numbers only: this
says nothing about RFdiffusion, any real model, or any safety property.

Purpose: make numerical failure patterns loud and immediate. (`toy.failure_modes`
*demonstrates* defect patterns; this module is the defensive counterpart.)
"Fail safely" here means: raise a specific, informative exception. Nothing in
this module warns or returns a sentinel, and no guard here is decided by the
caller's object: every one of them compares, and divides by, the NORMALISED
value (`_plain_real`, or the float a `check_finite_*` validator already
returned), so an overridden `__eq__`, `__ne__`, `__ge__` or `__rmul__` cannot
talk a guard out of raising. What that does NOT cover, stated rather than left
to be discovered: a number a caller's own `__float__`/`__int__` or a
caller-supplied CALLABLE returns is taken as the value, by protocol -- this
module cannot see behind it, and `check_finite_scalar` is documented to return
`float(value)`. TAKEN AT ITS WORD IS ABOUT LYING, NOT ABOUT RAISING: a
conversion protocol that RAISES produces no value to take at anyone's word, so
it is a failed READ of a data argument and is converted to this module's family
(NonNumericError, with the original chained) rather than escaping it -- see the
conversion enumeration below, which decides every coercion protocol this module
applies to caller data. Validators never mutate their arguments and return fresh
immutable copies (tuples) of validated data.

Exception design: every error derives from `StabilityError`, which derives from
`ValueError`. Existing callers that already catch ValueError (as
`toy.teacher_student` and `toy.erasure_demo` raise it) keep working, while
new code can catch the narrow subclass it expects. Subclasses are distinct per
failure so a caller (or test) can tell "empty mask" from "non-bool mask".

Not covered, deliberately: gradient clipping or any clamp. Clipping bounds a
step size; it neither detects nor proves numerical stability, and a clipped NaN
is still NaN. No function here treats clipping as evidence of anything.

Masked-out elements (history): at commit e436d93 `toy.erasure_demo.masked_mse`
checked finiteness of the *selected* elements only, so a NaN hidden by the mask
was silently ignored and could surface when the mask changed. It was hardened
following QA and now rejects non-finite values in ALL elements, masked-out ones
included, and requires strictly bool mask entries. Failing closed is the right
policy: the audited source multiplies by the mask, and NaN * 0 stays NaN in
torch, so a lenient toy would be more permissive than the thing it mimics. The
helpers here default to the same strict policy (`strict_masked_out=True`) and
are independent of that file. Pass
`strict_masked_out=False` to opt into the lenient behaviour explicitly.
"""
from __future__ import annotations

import math
from collections.abc import Mapping
from fractions import Fraction
from dataclasses import dataclass
from numbers import Real
from typing import Callable, Sequence


# ------------------------------------------------------------- exceptions
class StabilityError(ValueError):
    """Base class: a numeric validity check failed. Subclasses ValueError for
    compatibility with existing `except ValueError` handling."""


class NonNumericError(StabilityError):
    """A value is not a real number (None, str, bool, nested sequence, ...)."""


class NonFiniteError(StabilityError):
    """NaN, +inf or -inf found (or produced, e.g. by overflow)."""


class ShapeError(StabilityError):
    """Ragged / empty / mismatched data shapes."""


class MaskTypeError(StabilityError):
    """Mask is not a sequence of strict `bool` entries."""


class MaskLengthError(StabilityError):
    """Mask length does not match the data length."""


class EmptyMaskError(StabilityError):
    """Mask selects nothing (empty or all False); no loss may be produced."""


class NormalizationMismatchError(StabilityError):
    """Divisor does not equal the number of elements actually summed."""


class GradientMismatchError(StabilityError):
    """Analytic gradient disagrees with the finite-difference estimate."""


class DegenerateGradientError(StabilityError):
    """Gradient is identically zero: not evidence of a working gradient path."""


class MissingGradientError(StabilityError):
    """A required gradient is absent (None)."""


class UnderflowError(StabilityError):
    """A nonzero quantity collapsed to exactly 0.0 (floating-point underflow)."""


class NoOpUpdateError(StabilityError):
    """A parameter update changed nothing."""


# ------------------------------------------------------------- normalisation
def _plain_real(v):
    """The plain `int`/`float` value `v` STORES, for a guard to decide on.

    ARITHMETIC NORMALISES; A BARE COMPARISON DOES NOT. `atol + rtol * max(...)`
    collapses to a plain float before the `>` that uses it, which is why a lying
    `atol`/`rtol` changes nothing -- but `denominator != n_elements`,
    `max(abs(x) for x in g) <= zero_tol` and `a != b` put the caller's object on
    one side of a BARE operator, where its own `__ne__`/`__ge__`/`__eq__` decides
    (as the right operand, its REFLECTED dunder wins even against a plain float).
    Every guard in this module therefore compares, and divides by, what this
    function returns -- or the float a `check_finite_*` validator already
    returned, which is the same normalisation done by conversion.

    `int.__int__` / `float.__float__` rather than `int()` / `float()`,
    DELIBERATELY: they read the value the object stores, so an overridden
    `__int__`/`__float__` is not consulted and the value a guard inspected cannot
    differ from the value it used. Measured: `int(L(1)) == 2` for
    `class L(int): __int__ = lambda s: 2`, while `int.__int__(L(1)) == 1`.
    (`toy.schema._plain_value` reaches the same rule for the same reason; it is
    re-derived here rather than imported, to keep this module
    standard-library-only and to avoid depending on another module's private
    helper for this one's guards.)

    WHAT THIS DOES NOT REACH, by construction:
      * `bool` is returned UNCHANGED. The gates that must refuse a bool
        (`check_finite_scalar`, `_finite_at`, `check_mask`, the `denominator`
        type check) do so with `isinstance(v, bool)`, and collapsing True to 1
        would launder it past them.
      * any other `Real` -- a `Fraction`, a `numpy` scalar -- is returned
        unchanged, because it stores no `int`/`float` to read. There the
        caller's `__float__` is the only reading there is, and the
        `check_finite_*` validators consult it by protocol.
    """
    if isinstance(v, bool):
        return v
    if isinstance(v, int):
        return int.__int__(v)
    if isinstance(v, float):
        return float.__float__(v)
    return v


# ------------------------------------------------------- finite-value checks
def check_finite_scalar(value, name: str = "value") -> float:
    """Return `float(value)` if it is a finite real number, else raise.

    bool is rejected (True is not a measurement). -0.0 is finite and is
    returned unchanged (sign preserved, not normalised to +0.0) by the
    `check_finite_*` validators. Arithmetic results are NOT covered by that
    promise: `masked_mean_checked` sums from int 0, so an all `-0.0` input
    yields `0.0` (numerically equal; the sign of zero is not preserved).
    """
    if isinstance(value, bool) or not isinstance(value, Real):
        raise NonNumericError(f"{name} is not a real number: {_shown(value)} ({_type_name(value)})")
    try:
        f = _as_float(value, name)          # a RAISING __float__ stays in family (NonNumericError)
    except OverflowError:
        raise NonFiniteError(f"{name} is not representable as a finite float: too large") from None
    if not math.isfinite(f):
        raise NonFiniteError(f"{name} is non-finite: {_shown(f)}")
    return f


def check_finite_sequence(values: Sequence[float], name: str = "values") -> tuple[float, ...]:
    """Validate a flat, nonempty sequence; the error names the first offending
    index and value. Returns a tuple of floats (input untouched)."""
    items = _as_flat_items(values, name)
    if not items:
        raise ShapeError(f"{name} is empty")
    out = []
    for i, v in enumerate(items):
        out.append(_finite_at(v, f"{name}[{i}]"))
    return tuple(out)


def check_finite_matrix(m: Sequence[Sequence[float]], name: str = "matrix") -> tuple[tuple[float, ...], ...]:
    """Validate a nonempty rectangular 2D array; the error names the first
    offending (row, col) and its value. Returns a tuple of tuples of floats."""
    rows = _as_rows(m, name)
    return tuple(tuple(_finite_at(v, f"{name}[{i}][{j}]") for j, v in enumerate(r)) for i, r in enumerate(rows))


def _finite_at(v, where: str) -> float:
    if isinstance(v, bool) or not isinstance(v, Real):
        raise NonNumericError(f"{where} is not a real number: {_shown(v)} ({_type_name(v)})")
    return check_finite_scalar(v, where)


# ------------------------------------------------------ caller-input intake
# THE ENUMERATION of sites where caller-supplied input is materialised or probed. DERIVED, not
# listed: a site exists wherever the ITERATOR PROTOCOL or an ATTRIBUTE LOOKUP is applied to an
# object the CALLER handed over -- as opposed to a tuple this module already built. Deriving it
# mechanically (`tests/toy_tests/test_stability.py`, the C-series tests re-derive it) found FIVE
# candidates and discharged ONE. (That figure read "discharged two" while the list below marks one
# discharge and four intake points, and nothing asserted it;
# `test_the_derived_figures_in_these_comments_match_their_lists` now counts the end-of-row markers
# in this comment block and fails when a word here and the list disagree.)
#
#   _as_flat_items  -- every outer sequence: values, mask-bearing data, prediction, target,
#                      point, param_grad, before/after, the analytic gradient     [intake]
#   _as_rows        -- each ROW of a 2D argument                                  [intake]
#   check_mask      -- the mask                                                   [intake]
#   _is_nested / _split_values -- the flat-vs-2D attribute probe on an ELEMENT    [intake]
#   check_gradient's inner `call()` -- DISCHARGED: `list(p)` is reached only as `call(grad_fn,
#                      ..., p0)` and `call(fn, ..., q)`, where `p0` is `check_finite_sequence`'s
#                      tuple of floats and `q` is a `list(p0)` copy. `p` is never a caller object.
#
# The first three used to spell the probe and the materialisation as two separate statements, and
# only two of the three wrapped the materialisation; the third (`_as_rows`' per-ROW `tuple(r)`)
# did not, so a bare TypeError escaped the declared family on documented input. Wrapping a third
# call the same way would have left a fourth to be found, so BOTH operations now go through the
# two helpers below and every site calls one of them.
#
# Deriving the set surfaced a FOURTH site that had not been reported: the `hasattr(x, "__iter__")`
# that PRECEDES each materialisation is itself an attribute lookup on the caller's object, so a
# `__getattr__` raising anything but AttributeError escaped from the OUTER position too -- the
# position the earlier fix believed it had closed. It is inside the same `try` now.
#
# NOT in this enumeration, each for a stated reason:
#   * `len()`, `float()`, `int()`, `bool()`, `repr()`, `Fraction()` -- CONVERSION protocols rather
#     than intake, so they have their own derived enumeration, immediately below, which decides
#     each one. The reason this line used to give -- "the conversion protocol is documented above
#     as taken at its word" -- did not reach them: taken at its word is about LYING and says
#     nothing about RAISING. Measured while that line stood: a raising `__float__` produced 45
#     out-of-family outcomes and a raising `__repr__` nine more.
#   * `isinstance()` against a lying or RAISING `__class__` -- a different class of channel: it
#     reaches every `isinstance` in this module (and its siblings), not the intake points, so it
#     is not closed here and must not be assumed closed. MEASURED SCOPE at this commit, because
#     this sentence is what the next owner reads about an open finding: with a `@property
#     __class__` that raises RuntimeError, the OUTER positions (`values`, `mask`, `point`,
#     `before`/`after`, `param_grad`) and the ROW position come out IN FAMILY -- the outer ones
#     because `_materialised` keeps `isinstance(obj, _NOT_A_SEQUENCE)` inside its `try`, the row
#     one because `_is_row_like` absorbs it -- while the ELEMENT positions, `denominator` and
#     `expected_len` still escape as a bare RuntimeError. So it is NOT absorbed "at the nestedness
#     probe" alone, which is what this comment claimed, and it is NOT closed.
_NOT_A_SEQUENCE = (str, bytes, Mapping, set, frozenset)

# Exceptions from a caller's object that are NOT converted into this module's family: they report
# the state of the interpreter, not the shape of the input, and a ShapeError would misdescribe
# them. (The BaseException-only exits -- KeyboardInterrupt, SystemExit, GeneratorExit -- are
# already outside `except Exception`.)
_UNCONVERTED = (MemoryError, RecursionError, SystemError)


# ------------------------------------------------- caller-input conversion protocols
# THE SECOND ENUMERATION, derived the same mechanical way and for the same reason: the intake set
# above covers what happens when the ITERATOR PROTOCOL or an ATTRIBUTE LOOKUP on a caller's object
# raises, and left the next protocol over -- CONVERSION -- catching exactly one class
# (`OverflowError`) at three sites. A site exists wherever this module applies a BUILT-IN COERCION
# to an object the CALLER handed over, as opposed to a float, int, tuple or list this module
# produced. DERIVED by walking this file's own AST for every application of
# `float`/`int`/`bool`/`len`/`repr` (the `{...!r}` conversion included), `type(x).__name__` and
# `Fraction`, then deciding each by the PROVENANCE of its operand.
# `tests/toy_tests/test_stability.py::test_g2d_...` re-derives the set from the AST and fails
# closed when a new site appears. SEVEN protocols; FOUR have reachable sites, and all four are
# closed here:
#
#   float()            -- 4 calls in 3 statements: check_finite_scalar,
#                         _validated_masked_values, _sq (both operands). Every one of them goes
#                         through `_as_float`, and `float()` itself is spelled once, there.
#                                                                                   [converted]
#   repr(), as `{x!r}` -- 22 interpolations, every one of them in an error message, and the
#                         operand is the caller's own object at 9 reachable positions -- one of
#                         them on VALID input: `_sq`'s underflow message shows `prediction=` and
#                         `target=`, so a raising `__repr__` replaced an in-family UnderflowError
#                         with a bare RuntimeError. All go through `_shown`.         [converted]
#   type(x).__name__   -- 14 interpolations. A metaclass with a raising `__name__` property
#                         reaches every one. This is NOT the `__class__` channel above: `type()`
#                         ignores a `__class__` property, so it is a separate and closable site.
#                         All go through `_type_name`.                               [converted]
#   Fraction(...)      -- 2 calls in 1 statement, `_distinct_values`, which READS a Rational's
#                         `numerator` and `denominator`.                             [converted]
#   int()              -- 0 calls. `_plain_real` calls `int.__int__(v)`, a type-level call an
#                         override cannot intercept, and every int-ness decision here is an
#                         `isinstance`, never a conversion.                          DISCHARGED
#   bool()             -- 1 call, `_is_nested`'s `bool(outer)`, on a tuple this module built. A
#                         mask entry's own `__bool__` is never consulted: the strict-bool gate
#                         runs before `any(items)` (measured: an `int` subclass whose `__bool__`
#                         raises is refused with MaskTypeError).                     DISCHARGED
#   len()              -- 24 calls, every one on a tuple or list this module built (a
#                         `_materialised` result, or `list(p)`), so a raising or lying `__len__`
#                         cannot reach one. MEASURED, including the one behaviour change in this
#                         fix: a `tuple` subclass whose `__len__` raises is now ACCEPTED and read
#                         correctly, where HEAD refused it in family -- `_materialised` reads
#                         through `iter(obj)` so that a lazy producer's failure can be described
#                         truthfully, and `tuple(iterator)` no longer consults the object's own
#                         `__len__`/`__length_hint__`. Accepting it is right: such an object IS
#                         usable as a sequence, its elements are read verbatim, and every `len()`
#                         that decides anything is taken on this module's copy. DISCHARGED
#
# NOT conversion, so deliberately not re-decided here: the ARITHMETIC and COMPARISON dunders.
# They are the module docstring's own claim, closed by `_plain_real` at every guard and swept by
# the derived liar sweep in the tests. `_same`'s bare `==` is the one of them whose left operand
# comes back from a caller's CALLABLE, and `_plain_real` closes it there too (measured: a callable
# that swaps in a value whose `__eq__` raises still gets "mutated its input in place"). A `name=`
# label's `__format__`/`__str__` is also outside: that parameter is annotated `str`, and the
# message is the only thing it reaches.
#
# WHY CONVERTED RATHER THAN EXEMPTED: see the module docstring. Taken at its word is about LYING.
# Measured before this fix, identically on 3.12.4 and 3.13.5: a caller-defined `numbers.Real`
# whose `__float__` raises gave 45/45 outcomes outside StabilityError (5 exception classes x 9
# public entry points), 36 of them outside ValueError entirely; a raising `__repr__` escaped from
# 9 positions; a Rational with a raising `numerator` escaped from 3 of 6. Not one of the three
# permitted test modules noticed any of it.
def _shown(v) -> str:
    """`repr(v)` for a message, degraded to a placeholder when the caller's `__repr__` raises.

    A message is DIAGNOSTIC, so this does not raise: losing the real refusal because the object
    being refused cannot describe itself would be strictly worse than losing the description, and
    the exception TYPE -- which is what a caller branches on -- is unaffected either way. The
    BaseException-only exits and `_UNCONVERTED` still propagate, as everywhere else here.
    """
    try:
        return repr(v)
    except _UNCONVERTED:
        raise
    except Exception as e:
        return f"<unshowable {_type_name(v)}: its __repr__ raised {_type_name(e)}>"


def _type_name(v) -> str:
    """`type(v).__name__` for a message, degraded the same way `_shown` is.

    `type(v)` is safe (it ignores a `__class__` property), but `__name__` on the resulting class is
    an attribute lookup that a metaclass can answer with an exception. Same policy, same reason.
    """
    try:
        return type(v).__name__
    except _UNCONVERTED:
        raise
    except Exception:
        return "<unnamed type>"


def _as_float(v, what: str) -> float:
    """`float(v)` with a RAISING conversion kept inside this module's family.

    `OverflowError` is re-raised UNCONVERTED on purpose: it is not a failed conversion but a
    representability answer, and each of the three call sites has its own policy for it (a
    NonFiniteError here, `math.inf` in `_validated_masked_values` and `_sq`). Everything else means
    the object declared itself `Real` and then could not produce a number, which is a failed read
    of a data argument: NonNumericError, with the original chained.
    """
    try:
        return float(v)
    except OverflowError:
        raise
    except _UNCONVERTED:
        raise
    except StabilityError:
        raise
    except Exception as e:
        raise NonNumericError(f"{what} is not usable as a real number: float({_shown(v)}) raised "
                              f"{_type_name(e)}") from e


def _materialised(obj, exc, what: str) -> tuple:
    """Probe `obj` for sequence-hood and materialise it, with BOTH steps inside ONE `try`.

    WHY EVERY EXCEPTION AND NOT ONLY `TypeError`, decided on the carve-out's own text rather than
    left to disagree with it: the unwrapped-propagation carve-out in `check_gradient` names `fn`
    and `grad_fn` -- CALLABLES the caller supplies for this module to invoke. A DATA argument
    (`values`, `mask`, `prediction`, `target`, `point`, a row) is read, not called, and the
    exception-design paragraph above says every error here derives from `StabilityError`.
    Measured before this: an `__iter__` raising ValueError escaped as a BARE ValueError (inside
    ValueError, outside StabilityError) and one raising RuntimeError or KeyError escaped ValueError
    entirely -- from the two sites that DID wrap, so widening the catch is what matches the policy
    those wrappers were written for. The original exception is chained (`from e`) and named in the
    message, so widening loses no diagnostic.

    THE COST OF THAT WIDENING, stated here because this is where a caller reads about it: the
    module docstring's "existing callers that already catch ValueError keep working" has a flip
    side. A caller running `except ValueError: skip_batch()` now ABSORBS an exception of its own
    making -- a `ZeroDivisionError` in the generator it passed as `values`, say -- as a shape
    complaint about that argument, and carries on. That is a real loss: an unrelated caller bug
    becomes an expected-and-handled condition. It is accepted deliberately, because the module
    cannot tell "this object is not a sequence" from "this sequence's producer failed" without
    guessing, and the alternative (letting it through) is the out-of-family escape this helper
    exists to prevent. `__cause__` carries the original, so the diagnosis is not lost; a caller
    that needs to tell the two apart must inspect `__cause__` rather than the class.

    WHICH HALF FAILED is tracked and said, because the message used to assert the wrong one: a
    LAZY producer (a generator, a genexp, a `map()`) raises from its BODY during `tuple(it)`,
    not from `__iter__` or an attribute lookup, and such an object IS usable as a sequence.
    `reading` separates the two without splitting the `try` -- splitting it is what left the
    row site half-fixed in the first place.
    """
    reading = False
    try:
        if not isinstance(obj, _NOT_A_SEQUENCE) and hasattr(obj, "__iter__"):
            it = iter(obj)
            reading = True
            return tuple(it)
    except _UNCONVERTED:
        raise
    except StabilityError:
        raise
    except Exception as e:
        if reading:
            raise exc(f"{what}, got {_type_name(obj)} (it is iterable, but reading its elements "
                      f"raised {_type_name(e)}: the failure is its producer's, which this module "
                      f"cannot tell apart from a shape problem -- see __cause__)") from e
        raise exc(f"{what}, got {_type_name(obj)} (its __iter__ or attribute lookup raised "
                  f"{_type_name(e)}, so it is not usable as a sequence)") from e
    raise exc(f"{what}, got {_type_name(obj)}")


def _is_row_like(v) -> bool:
    """Is `v` a ROW rather than a scalar element? This is an ATTRIBUTE LOOKUP on the caller's
    object, so a hostile `__getattr__` is answered here instead of escaping the family: a `v` that
    cannot be probed is not a row, and the element validators then refuse it in family
    (NonNumericError, because it is not a `Real`)."""
    try:
        return hasattr(v, "__iter__") and not isinstance(v, (str, bytes))
    except _UNCONVERTED:
        raise
    except Exception:
        return False


def _as_flat_items(values, name: str) -> tuple:
    return _materialised(values, ShapeError, f"{name} must be a sequence of numbers")


def _as_rows(m, name: str) -> tuple[tuple, ...]:
    outer = _as_flat_items(m, name)
    if not outer:
        raise ShapeError(f"{name} is empty")
    rows = []
    for i, r in enumerate(outer):
        # The ROW site. It was the one intake point of the three whose `tuple()` was unguarded
        # while both siblings wrapped the identical call.
        row = _materialised(r, ShapeError,
                            f"{name}[{i}] is not a row (sets/mappings have no defined order)")
        if not row:
            raise ShapeError(f"{name}[{i}] is an empty row")
        rows.append(row)
    w = len(rows[0])
    for i, r in enumerate(rows):
        if len(r) != w:
            raise ShapeError(f"{name} is ragged: row {i} has width {len(r)}, row 0 has width {w}")
    return tuple(rows)


# ---------------------------------------------------------- mask validation
def check_mask(mask: Sequence[bool], expected_len: int | None = None, name: str = "mask") -> tuple[bool, ...]:
    """Validate a mask and return it as a tuple of bool.

    Checks, each with its own exception type:
      * entries are strictly `bool` (0/1/None/truthy objects, and numpy
        scalars such as np.bool_/np.int64, are rejected: relying on truthiness
        is the pattern being guarded against)        -> MaskTypeError
      * length equals `expected_len` when given      -> MaskLengthError
      * at least one entry is True (an empty or all-False mask raises rather
        than letting a caller produce a loss)        -> EmptyMaskError
    """
    items = _materialised(mask, MaskTypeError, f"{name} must be a sequence of bool")
    for i, b in enumerate(items):
        if not isinstance(b, bool):
            raise MaskTypeError(f"{name}[{i}] must be a strict bool, got {_shown(b)} ({_type_name(b)}); "
                                "truthiness is not accepted")
    if expected_len is not None:
        want = _plain_real(expected_len)
        if isinstance(want, bool) or not isinstance(want, int):
            raise MaskLengthError(f"expected_len must be an int element count, got {_shown(expected_len)} "
                                  f"({_type_name(expected_len)})")
        if len(items) != want:
            raise MaskLengthError(f"{name} length {len(items)} != data length {want}")
    if not any(items):
        raise EmptyMaskError(f"{name} selects nothing ({'empty' if not items else 'all False'}); "
                             "refusing to compute a loss")
    return items


# ----------------------------------------------------- masked-loss validation
def _split_values(values, mask: tuple[bool, ...], name: str):
    """Return (rows, width). Flat sequences are treated as width-1 'rows'."""
    outer = _as_flat_items(values, name)
    nested = _is_nested(outer)
    if nested:
        rows = _as_rows(outer, name)
        return rows, len(rows[0])
    return tuple((v,) for v in outer), 1


def _validated_masked_values(values, mask, name: str, strict: bool):
    """Validate mask against `values` (length), apply finiteness policy, and
    return (masked_in_rows_as_float_tuples, mask_tuple, width)."""
    outer = _as_flat_items(values, name)
    mk = check_mask(mask, expected_len=len(outer), name="mask")
    rows, width = _split_values(outer, mk, name)
    kept = []
    for i, (r, use) in enumerate(zip(rows, mk)):
        # ONE float() per element, and the value SUMMED is the value VALIDATED: `float(v)` used to be
        # called twice per masked-in element (once here, once in the `kept` row below), so a stateful
        # `__float__` was validated on one answer and summed on another -- fail-closed only because the
        # result-level finiteness backstop in `masked_mean_checked` caught it afterwards.
        row = []
        for j, v in enumerate(r):
            where = f"{name}[{i}][{j}]" if width > 1 or _is_nested(outer) else f"{name}[{i}]"
            if isinstance(v, bool) or not isinstance(v, Real):
                raise NonNumericError(f"{where} is not a real number: {_shown(v)} ({_type_name(v)})")
            if use or strict:
                try:
                    fv = _as_float(v, where)
                except OverflowError:  # huge int: not representable, never a bare OverflowError
                    fv = math.inf
                if not math.isfinite(fv):
                    tag = "" if use else " (masked OUT; strict_masked_out=True rejects hidden non-finite values)"
                    raise NonFiniteError(f"{where} is non-finite or not representable as a float: "
                                         f"{_shown(fv)}{tag}")
                row.append(fv)
        if use:
            kept.append(tuple(row))
    return tuple(kept), mk, width


def _is_nested(outer) -> bool:
    return bool(outer) and all(_is_row_like(v) for v in outer)


def masked_mean_checked(values, mask: Sequence[bool], denominator: int, *,
                        strict_masked_out: bool = True, name: str = "values") -> float:
    """Sum the masked-in elements of `values` and divide by `denominator`,
    which the caller must state explicitly and which must equal the number of
    elements actually summed.

    `values` is a flat sequence (one mask entry per element) or a 2D matrix
    (one mask entry per ROW; every element of a selected row is summed, so the
    count is `sum(mask) * width`). A divisor that equals only `sum(mask)` for a
    matrix is the audited "off by the row width" normalization mismatch and
    raises NormalizationMismatchError. `denominator` must be a positive int
    (bool rejected). The mismatch check and the division both use
    `_plain_real(denominator)`, the int the object STORES, so an `int` subclass
    whose `__eq__`/`__ne__`/`__int__` is overridden cannot carry a divisor past
    this check (measured before that: `EqInt(1)` returned 4.0 against an honest
    2.0, and `EqInt(8)` returned 0.5 -- the very defect this function exists to
    catch, through its own public MSE wrapper).

    strict_masked_out (default True): masked-out elements must also be finite,
    because a NaN hidden by today's mask surfaces when the mask changes.
    the default matches the current, hardened `toy.erasure_demo.masked_mse`.
    (At commit e436d93 that function ignored masked-out values; False
    reproduces that old lenient policy as an explicit, discouraged opt-in.)

    The result must be finite (an overflowing sum raises NonFiniteError).
    Rows must be real sequences: sets and mappings are rejected (no defined
    order / they would sum keys). `values` and `mask` may be one-shot iterables;
    each is materialised exactly once.
    """
    if isinstance(denominator, bool) or not isinstance(denominator, int):
        raise NormalizationMismatchError("denominator must be an int element count, got "
                                         f"{_shown(denominator)}")
    denom = _plain_real(denominator)    # decide AND divide on the stored int, never on the object
    kept, mk, width = _validated_masked_values(values, mask, name, strict_masked_out)
    n_entries = sum(mk)
    n_elements = n_entries * width
    if denom != n_elements:
        hint = ""
        if width > 1 and denom == n_entries:
            hint = (f"; denominator equals the number of masked rows, i.e. per-mask-entry normalization "
                    f"off by the row width {width}")
        raise NormalizationMismatchError(
            f"denominator {denom} != summed element count {n_elements} "
            f"({n_entries} masked entries x width {width}){hint}")
    total = sum(v for r in kept for v in r)
    result = total / denom
    if not math.isfinite(result):
        raise NonFiniteError(f"masked mean overflowed or became non-finite: {_shown(result)}")
    return result


def masked_squared_error_mean(prediction, target, mask: Sequence[bool], denominator: int, *,
                              strict_masked_out: bool = True) -> float:
    """Checked masked MSE for flat vectors or 2D matrices (row mask).

    Same shape rules as `masked_mean_checked`; prediction and target must have
    identical shape. For `toy.teacher_student` matrices the correct divisor is
    `sum(mask) * width` (its "per_masked_element" normalization); its
    "per_mask_entry" divisor `sum(mask)` is rejected here.
    """
    p_outer, t_outer = _as_flat_items(prediction, "prediction"), _as_flat_items(target, "target")
    if len(p_outer) != len(t_outer):
        raise ShapeError(f"prediction length {len(p_outer)} != target length {len(t_outer)}")
    if _is_nested(p_outer) != _is_nested(t_outer):
        raise ShapeError("prediction and target must both be flat or both be 2D")
    if _is_nested(p_outer):
        pr, tr = _as_rows(p_outer, "prediction"), _as_rows(t_outer, "target")
        if len(pr[0]) != len(tr[0]):
            raise ShapeError(f"prediction width {len(pr[0])} != target width {len(tr[0])}")
        errs = tuple(tuple(_sq(a, b) for a, b in zip(ra, rb)) for ra, rb in zip(pr, tr))
    else:
        errs = tuple(_sq(a, b) for a, b in zip(p_outer, t_outer))
    return masked_mean_checked(errs, mask, denominator, strict_masked_out=strict_masked_out,
                               name="squared_error")


def _distinct_values(a, b, fa: float, fb: float) -> bool:
    """True if `a` and `b` are different values: the second half of `_sq`'s underflow condition.

    TWO PROPERTIES THAT PULL IN OPPOSITE DIRECTIONS, kept together here deliberately, because each
    obvious one-liner loses the other and both were measured:
      * `a != b` is a BARE comparison on the caller's objects, so an `__eq__`/`__ne__` override
        decides it. Measured on the previous spelling: a `float` subclass returning False from
        `__ne__` made `masked_squared_error_mean([x], [0.0], [True], 1)` return 0.0 for
        x = 1e-200 -- precisely the "silent zero" the message below refuses.
      * `float(a) != float(b)` normalises, but collapses `Fraction(1, 10**400)` to 0.0 and so
        loses the tiny-exact-input case this guard exists for. Measured: that spelling fails
        `test_underflow_to_zero_raises` twice.
    So: compare the EXACT rational value each object stores (`_plain_real` first, so a `float`/`int`
    subclass cannot answer for itself). A `Real` with no exact rational reading falls back to the
    floats `_sq` already converted, rather than escaping the documented error family -- measured:
    `Fraction(np.float32(1e-40))` raises TypeError, and a numpy `float32` pair must not do that here.

    EVERY exception and not those four classes: `Fraction(x)` READS a `Rational`'s `numerator` and
    `denominator`, which are the caller's properties, so the enumerated tuple (TypeError,
    ValueError, OverflowError, ZeroDivisionError) left the rest of them escaping this module's
    family from a guard that was in the middle of refusing an underflow. Measured at the previous
    spelling, both interpreters: a `Rational` whose `numerator` raises RuntimeError, KeyError or
    AttributeError came out as that bare class, while the same object raising one of the four
    enumerated classes was refused with UnderflowError. The fallback is the right answer for all
    of them -- "no exact rational reading, use the floats `_sq` already converted".
    """
    try:
        return Fraction(_plain_real(a)) != Fraction(_plain_real(b))
    except _UNCONVERTED:
        raise
    except Exception:
        return fa != fb


def _sq(a, b):
    for label, v in (("prediction", a), ("target", b)):
        if isinstance(v, bool) or not isinstance(v, Real):
            raise NonNumericError(f"{label} element is not a real number: {_shown(v)} ({_type_name(v)})")
    try:
        fa, fb = _as_float(a, "prediction element"), _as_float(b, "target element")
        d = fa - fb
        sq = d * d
    except OverflowError:
        return math.inf
    # Deliberate policy: a nonzero input that becomes exactly 0.0 is an error, not a
    # zero loss. This applies to every element, masked-out ones included, because
    # `_sq` runs before the mask is applied. Genuinely equal inputs are fine. (Inputs that
    # themselves round to 0.0, e.g. a tiny Fraction, are caught because they are not EQUAL --
    # see `_distinct_values`, which is where the two halves of that sentence are kept together.)
    if sq == 0.0 and _distinct_values(a, b, fa, fb):
        raise UnderflowError(f"squared error underflowed to 0.0 from nonzero input "
                             f"(prediction={_shown(a)}, target={_shown(b)}); refusing a silent zero")
    return sq


# ------------------------------------------------------ gradient validity
@dataclass(frozen=True)
class GradientCheckReport:
    """Returned only when the check PASSES (failures raise)."""
    analytic: tuple[float, ...]
    numeric: tuple[float, ...]
    max_abs_error: float
    max_rel_error: float
    step: float
    rtol: float
    atol: float


def check_gradient(fn: Callable[[list], float], grad_fn: Callable[[list], Sequence[float]],
                   point: Sequence[float], *, step: float = 1e-6, rtol: float = 1e-4,
                   atol: float = 1e-6, zero_tol: float = 0.0) -> GradientCheckReport:
    """Compare an analytic gradient to a central finite-difference estimate.

    fn(point) -> scalar; grad_fn(point) -> sequence of len(point). Each call
    receives a FRESH list copy; if either callable mutates it, that is detected
    and raises (in-place mutation of inputs). `point` itself is never modified.

    Per coordinate i, numeric_i = (fn(p + h e_i) - fn(p - h e_i)) / (2h) with
    h = `step` (absolute). Pass iff |analytic_i - numeric_i| <=
    atol + rtol * max(|analytic_i|, |numeric_i|) for every i. Defaults
    (h=1e-6, rtol=1e-4, atol=1e-6) are tuned for O(1)-scale smooth functions.

    SMALL-SCALE BLIND SPOT (worked example): `atol` is absolute, so when the
    true gradient is comparable to or below `atol` the check is nearly vacuous.
    For f(x) = 1e-9 * x**2 at x = 1 (true gradient 2e-9) a claimed gradient
    100x too large (2e-7) PASSES at the defaults; 2e-6 is caught. A loss that
    carries a small constant factor (e.g. 0.01 squared-error weights on small
    errors) can land in this regime. A pass on a small-scale loss is therefore
    NOT evidence: rescale the problem, or set `atol` well below the expected
    gradient magnitude (e.g. atol=1e-12 catches the 100x error above).

    `sum()` is used for accumulation elsewhere in this module and relies on
    CPython 3.12+ compensated float summation (sum([1e16, 1.0, -1e16]) is
    1.0 there, not 0.0); masked means can differ in the last bits on
    older Pythons.

    `step`, `rtol`, `atol` and `zero_tol` are normalised to plain floats ONCE, immediately after
    validation, and every use below is of those floats: the rejection that follows is a bare `<=`
    against `zero_tol`, where the caller's object would otherwise be the right operand and its own
    reflected `__ge__` would decide whether an identically-zero gradient is "zero" (measured before
    this: a `float` subclass returning False from `__ge__` obtained a PASS report for
    `analytic=(0.0, 0.0)`). `2.0 * step` likewise consulted `step.__rmul__`, and a zero from it
    raised a ZeroDivisionError that is outside both StabilityError and ValueError.

    Rejected before comparing (none counts as evidence of a working gradient):
      * analytic gradient with any NaN/inf (NonFiniteError),
      * analytic gradient with max |g_i| <= zero_tol, default exactly zero
        (DegenerateGradientError): a zero gradient matches a flat function and
        also a severed gradient path, so agreement proves nothing. Choose a
        point where the true gradient is nonzero. A genuinely tiny gradient is
        not "zero" unless you raise zero_tol above it.
      * non-finite fn values during differencing (NonFiniteError).
    Mismatch raises GradientMismatchError naming the coordinate.

    Other behaviour: an exception the caller's `fn`/`grad_fn` raises WHILE THIS
    MODULE CALLS IT (e.g. ZeroDivisionError) propagates unwrapped; it is not a
    StabilityError. That carve-out is about CALLABLES this module INVOKES, and
    it reaches the call itself and nothing else -- in particular it does NOT
    reach a LAZY return value. `grad_fn` may return a generator, a generator
    expression or a `map()`, all of which are supported input and all of which
    return a full report here; a generator whose BODY raises does so later,
    while this module materialises that returned DATA, so it is converted to
    this module's family like any other data read. Measured: a generator
    `grad_fn` whose body raises ZeroDivisionError yields ShapeError, not
    ZeroDivisionError. The carve-out used to say "about CALLABLES ... and it
    covers nothing else", which was false exactly where its two halves meet: a
    `grad_fn` is a callable whose return value is a data argument, and for a
    lazy one the data half decides. An exception raised while a DATA argument is
    probed, materialised or produced -- a broken `__iter__`, a `__getattr__`
    that raises, a lazy producer's body, a `__float__` that raises -- is
    converted to this module's family instead, whatever its class, and the
    original is chained as `__cause__`.
    `point`, like every sequence argument in this module, is materialised once
    (generators are consumed a single time at validation).

    HONEST LIMITS: central differences have truncation error ~ h^2 f'''/6 and
    round-off error ~ eps*|f|/h (eps ~ 2.2e-16). Too large an h biases the
    estimate; too small an h lets round-off dominate; the best h is roughly
    eps^(1/3) * scale ~ 6e-6 * scale. This check CAN FAIL FOR A CORRECT
    gradient if h is mis-set, |f| is huge, f is non-smooth (kinks, abs, relu)
    within h of `point`, or rtol/atol are tighter than the achievable accuracy.
    Conversely it can PASS an incorrect gradient whose error is below
    atol + rtol*|g|, and it only tests one point: agreement there is not a proof
    of correctness elsewhere, and says nothing about learning.
    """
    config = []
    for label, v in (("step", step), ("rtol", rtol), ("atol", atol), ("zero_tol", zero_tol)):
        f = check_finite_scalar(_plain_real(v), label)
        if f < 0 or (label == "step" and f == 0):
            raise StabilityError(f"{label} must be {'> 0' if label == 'step' else '>= 0'}, got {_shown(v)}")
        config.append(f)
    # The normalised floats REPLACE the caller's objects for the rest of this function. The validated
    # value used to sit in `f` and be discarded, which is what left the `<= zero_tol` rejection and the
    # `2.0 * step` differencing to the caller's dunders (F3/F4 of the SR-06 re-attestation).
    step, rtol, atol, zero_tol = config
    p0 = check_finite_sequence(point, "point")
    n = len(p0)
    for i, x in enumerate(p0):
        if x + step == x or x - step == x:
            raise StabilityError(f"step {_shown(step)} is too small to change point[{i}]={_shown(x)} "
                                 "(below float resolution); finite differences would be meaningless")

    def call(func, label, p):
        arg = list(p)
        snap = tuple(arg)
        out = func(arg)
        if len(arg) != len(snap) or not all(_same(a, b) for a, b in zip(arg, snap)):
            raise StabilityError(f"{label} mutated its input in place")
        return out

    g_raw = call(grad_fn, "grad_fn", p0)
    if g_raw is None:
        raise MissingGradientError("grad_fn returned None")
    g_items = _as_flat_items(g_raw, "analytic gradient")
    if len(g_items) != n:
        raise ShapeError(f"analytic gradient length {len(g_items)} != point length {n}")
    g = check_finite_sequence(g_items, "analytic gradient")
    if max(abs(x) for x in g) <= zero_tol:
        raise DegenerateGradientError(
            "analytic gradient is identically zero (|g| <= zero_tol): not evidence of a working gradient path")

    num = []
    for i in range(n):
        vals = []
        for sgn in (+1.0, -1.0):
            q = list(p0)
            q[i] += sgn * step
            vals.append(check_finite_scalar(call(fn, "fn", q), f"fn(point {'+' if sgn > 0 else '-'} h e_{i})"))
        num.append((vals[0] - vals[1]) / (2.0 * step))
    num = tuple(num)
    for i, (a, d) in enumerate(zip(g, num)):
        if not math.isfinite(d):
            raise NonFiniteError(f"numeric gradient[{i}] is non-finite: {_shown(d)}")
        if abs(a - d) > atol + rtol * max(abs(a), abs(d)):
            raise GradientMismatchError(
                f"gradient mismatch at index {i}: analytic={_shown(a)}, finite-difference={_shown(d)}, "
                f"|diff|={abs(a - d):.3e} > atol {atol} + rtol {rtol} * max(|a|,|d|) (step {step})")
    abs_err = max(abs(a - d) for a, d in zip(g, num))
    rel_err = max(abs(a - d) / max(abs(a), abs(d), 1e-300) for a, d in zip(g, num))
    return GradientCheckReport(g, num, abs_err, rel_err, step, rtol, atol)   # already plain floats


def _same(a, b) -> bool:
    """`a` comes back from the caller's callable and `b` is this module's snapshot, so `a` is the LEFT
    operand of a bare `==` and answers for itself: `_plain_real` first, or a callable that swaps a
    point coordinate for a `float` subclass with a lying `__eq__` hides its own in-place mutation."""
    a = _plain_real(a)
    return a == b or (a != a and b != b)


# --------------------------------------------- "does not prove learning" guard
def require_parameter_gradient(param_grad, *, input_grad=None, name: str = "parameter gradient") -> tuple[float, ...]:
    """Require evidence that a gradient reached the PARAMETERS.

    A non-None, finite gradient with respect to an INPUT says nothing about
    whether gradient reaches the parameters: the two are different paths (an
    input can be differentiable while parameters are detached, frozen, or
    absent from the loss). So `input_grad` is accepted only to give a precise
    message; it is never used as evidence. This function:
      * raises MissingGradientError if `param_grad` is None (naming the
        misleading case when `input_grad` is present and finite),
      * raises NonFiniteError if it has NaN/inf,
      * raises DegenerateGradientError if it is identically zero.
    Even a passing result shows only that a finite nonzero number exists. It
    does not show the loss decreases, that an optimizer used it, or learning.
    """
    if param_grad is None:
        extra = ""
        if input_grad is not None:
            try:
                check_finite_sequence(input_grad if not isinstance(input_grad, Real) else (input_grad,), "input_grad")
                extra = ("; a finite input gradient was provided but is NOT evidence that gradient "
                         "reaches the parameters")
            except StabilityError:
                pass
        raise MissingGradientError(f"{name} is None{extra}")
    g = check_finite_sequence(param_grad, name)
    if all(x == 0.0 for x in g):
        raise DegenerateGradientError(f"{name} is identically zero: parameters receive no signal")
    return g


def check_params_changed(before: Sequence[float], after: Sequence[float], *,
                         min_abs_change: float = 0.0, name: str = "parameters") -> float:
    """Raise NoOpUpdateError if an update left `after` equal to `before`
    (max |after - before| <= min_abs_change). Returns the max absolute change.
    A silent no-op step is the failure guarded; a nonzero change still does
    not prove learning (it may be the wrong direction or noise)."""
    b, a = check_finite_sequence(before, f"{name} before"), check_finite_sequence(after, f"{name} after")
    if len(a) != len(b):
        raise ShapeError(f"{name} length changed: {len(b)} -> {len(a)}")
    mc = check_finite_scalar(_plain_real(min_abs_change), "min_abs_change")
    if mc < 0:
        raise StabilityError("min_abs_change must be >= 0")
    delta = max(abs(x - y) for x, y in zip(a, b))
    if not math.isfinite(delta):
        raise NonFiniteError(f"{name} change overflowed to {_shown(delta)}")
    if delta <= mc:
        raise NoOpUpdateError(f"{name} unchanged by update: max |change| {_shown(delta)} <= {_shown(mc)}")
    return delta
