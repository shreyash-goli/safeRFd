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
talk a guard out of raising. THAT HOLDS FOR A VALUE A CALLER'S CALLABLE PLACED
AS WELL AS FOR ONE IT PASSED, and holding it there took a SECOND rule, because
`_plain_real` normalises only `bool`/`int`/`float` and is the IDENTITY on
everything else: where the left operand of a bare `==` is whatever `fn` or
`grad_fn` wrote into the list this module handed it, the guard decides on the
plain `int`/`float` normalisation produced and REPORTS ANY OTHER OBJECT AS A
WRITE instead of asking that object whether it is equal (`_same`). Measured
over 5 operand bases x 3 comparison shapes x 2 callable positions = 30 cells,
identically on both interpreters: without that rule 12 of the 30 left this
module as a bare RuntimeError and 3 were PASS REPORTS WITH THE MUTATION
UNDETECTED; with it, 30 of 30 are refused in family.
What that does NOT cover, stated rather than left
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

    The returned object's type is exactly `float`, never a `float` subclass: a caller's subclass
    does not survive this validator, and `toy.robustness.mse_fsum` relies on that when it feeds the
    result to `math.fsum`. The contract was protected only INCIDENTALLY -- through the compensated-
    summation figure -- until a test asserted the type directly.

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
#     reaches every `isinstance` in this module (19 of them, derived from this file's AST over
#     every scope), not the intake points, so it is not closed here and must not be assumed
#     closed. MEASURED SCOPE at this commit, because this sentence is what the next owner reads
#     about an open finding, and it is written from a POSITION-BY-POSITION sweep rather than from
#     a shape: with a `@property __class__` that raises RuntimeError, 44 driven positions over the
#     nine public functions give 16 IN FAMILY and 28 escaping as a bare RuntimeError, identically
#     on 3.12.4 and 3.13.5 and with numpy present and absent.
#     A POSITION HERE IS A ROUTE, not a parameter, and that distinction is this round's correction.
#     The sweep used to read 38 positions, 13 and 25, and the three it was missing were all ROUTES
#     OF PARAMETERS IT ALREADY NAMED -- `fn` and `grad_fn`, listed for their return values alone.
#     An accounting that keys on the PARAMETER cannot see such a route: it needs no row and gets no
#     excuse. So the test that pins this sentence keys on (function, parameter, ROUTE).
#     IN FAMILY (16), and only these: every OUTER SEQUENCE position -- `values` (of
#     `check_finite_sequence` and of `masked_mean_checked`), `m`, `mask` (of all three functions
#     that take one), `prediction`, `target`, `point`, `param_grad`, `before`, `after` -- because
#     `_materialised` keeps `isinstance(obj, _NOT_A_SEQUENCE)` inside its `try`; plus
#     `check_finite_matrix`'s ROW position, because that row goes through `_materialised` too; plus
#     `masked_squared_error_mean`'s TWO ROW positions, `prediction`'s and `target`'s, for a reason
#     worth stating separately because it is not the row machinery at all: `_is_row_like`'s probe
#     ABSORBS the hostile `__class__` and answers "not a row", so one side of the comparison reads
#     FLAT and the other reads 2D, and the function refuses the disagreement. The refusal is in
#     family, and its message names the shapes rather than the object that caused them -- a
#     DIAGNOSTIC cost recorded here rather than a different verdict; plus
#     the SEQUENCE OBJECT `grad_fn` RETURNS, which `_as_flat_items` materialises exactly like a
#     sequence argument and which therefore comes out as ShapeError.
#     ESCAPING (28), which the wording before this sentence understated three ways: every
#     ELEMENT position -- including `masked_squared_error_mean`'s `mask` ELEMENT route, which
#     this class covered in words while the table behind the figure had no row for it, so the
#     count read 41 and not 42 until this round; every SCALAR position, which is `value`,
#     `expected_len`, `denominator`,
#     `step`, `rtol`, `atol`, `zero_tol` and `min_abs_change` and NOT just the two that sentence
#     used to name; `input_grad` at BOTH its positions, an OUTER argument of a public function
#     that escapes while the older sentence said outer positions come out in family (its other four
#     hostile shapes -- `__iter__`, `__getattr__`, `__float__`, `__repr__` raising -- are all
#     refused as MissingGradientError, so the `__class__` channel is the only one that escapes
#     there); `masked_mean_checked`'s ROW position, which is NOT in family although
#     `check_finite_matrix`'s is, because `_is_nested`'s probe absorbs the hostile `__class__`,
#     answers "not a row" and so hands the object to the ELEMENT check -- and although
#     `masked_squared_error_mean`'s two ROW positions are not either, which is the sharper
#     contrast: the SAME absorbed probe runs there, but there is a SECOND argument for the
#     answer to disagree with, so the object is refused on shape before it is ever read as a
#     number. `masked_mean_checked` has nothing to disagree with and reads it; `fn`'s RETURN VALUE, and
#     the ELEMENTS of the sequence `grad_fn` returns but NOT that sequence itself -- which is what
#     the previous wording ("the RETURN values of `fn` and `grad_fn`") got wrong, in the one
#     direction a test asserting only the in-family rows could not catch; and the SLOT A CALLABLE
#     WROTE, which is `_same`'s left operand, where `fn` or `grad_fn` has replaced a coordinate of
#     the list this module handed it with an object whose `__class__` raises. That last route
#     arrives through `_plain_real`'s own first statement, `isinstance(v, bool)`, and it was in
#     NEITHER half of this sentence while both its parameters stood in the escaping half for their
#     return values -- a reason that covers two routes of three reading like a reason that covers
#     the position, which is the defect of the round before this one recurring one table over. The
#     sixteen other hostile shapes at that same slot (`__getattr__`, `__float__`, `__repr__`,
#     `__iter__`, `__eq__`, `__bool__`, `__len__`, `__index__` raising, at both callable positions)
#     are all refused in family, so there too the `__class__` channel is the only escape.
#     So it is NOT absorbed "at the nestedness probe" alone, it is NOT closed,
#     and the fix is the three owners' joint decision rather than this module's -- which is why
#     the test that pins this sentence asserts the 16 in family, accounts for all 44 positions AT
#     ROUTE GRANULARITY, and asserts NOTHING about the 28, because a test that pinned the escape
#     would pin a defect and fail on the eventual fix. WHAT THAT ACCOUNTING CLOSES, exactly, and
#     by which derivation, because the sentence that used to stand here claimed more than its
#     mechanism: (i) the PARAMETER set is derived from the nine signatures, so a parameter in
#     neither the table nor its excuse table fails; (ii) a CALLABLE-PLACED position's three
#     routes -- call, return value, written slot -- are cross-checked against the tests'
#     `_CALLABLE_PLACED`; (iii) a DATA parameter's OUTER route must have an ELEMENT sibling and
#     vice versa, or be declined in writing in an excuse table; (iv) and since FINDING S a DATA
#     parameter has a ROW route exactly when THIS MODULE MATERIALISES ROWS out of it, which the
#     test derives by spying on `_as_rows` while a benign nested value is driven through each
#     outer data parameter -- so `row` is not a kind the test answers by hand any more either.
#     WHAT IS STILL HELD BY HAND, shrunk by exactly what (iv) closes, and it is one ROW and one
#     CLASS: the ELEMENTS of the sequence `grad_fn` returns, which nothing requires but the kind
#     enumeration `_ROUTE_KINDS` -- delete that row and only the kind-set equality notices; and
#     a route kind this module has no machinery for at all, which is in no table because nothing
#     drives it. The SCALAR routes are a smaller case than they look: the parameter accounting
#     already requires every scalar parameter to carry SOME route, so only the CHOICE of kind is
#     by hand there. That is not a quibble. The
#     claim this paragraph used to make, that the accounting covers every position at route
#     granularity "so a new one cannot be missing from BOTH halves", was FALSE FOR DATA
#     PARAMETERS for exactly that reason -- (ii) existed and (iii) and (iv) did not -- and
#     `masked_squared_error_mean`'s `mask` ELEMENT route, a real escape, had no row, no excuse
#     and no measurement behind the figure for as long as that claim stood.
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
# closed when a new site appears -- over EVERY SCOPE (module body, class bodies and lambda bodies
# included: it used to walk `ast.FunctionDef` only, so a coercion in any of those three was
# invisible to it and to this table alike) and against a decided list of every CALLABLE THIS MODULE
# CALLS BY NAME, so a protocol missing from BOTH this table and the walker fails too. BY NAME means
# bare (`len(x)`), DOTTED (`math.isfinite(f)`, `float.__float__(v)`, `rows.append(r)`) or through an
# IMPORT ALIAS (`from builtins import len as _len`, `import builtins` then `builtins.len(x)`), all
# canonicalised to one spelling: that reach is this round's correction, and it is the SCOPE
# correction's defect one axis over -- the scope was widened and the SPELLING was not, so an aliased
# or dotted coercion was invisible to the walker and to this table at once. Measured while the
# matcher was bare-name-only: `builtins.len(rows)` and `_len(rows)` were each unkilled by all three
# permitted suites on both interpreters, while the identical bare `len(rows)` was killed. EIGHT protocols;
# FIVE have reachable sites, FOUR of them converted here and ONE declared:
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
#   __format__ as `{x}` -- 111 interpolations, 80 of them module-produced, 31 on the label chain.
#                         The 80 interpolate a value this module itself produced (a float, an int,
#                         a `_shown` or `_type_name` result) and reach no caller protocol. The 31
#                         interpolate the `name`, `what` or `where` LABEL, whose root is the public
#                         `name=` parameter: that parameter is annotated `str`, but an annotation is
#                         not a boundary, and a `str` subclass with a raising `__format__` is
#                         accepted and its exception leaves this module. NOT CONVERTED. DECLARED
#                         instead, and declared in a ROW rather than in prose below the table,
#                         because a protocol that has reachable caller-data sites and no row is
#                         invisible to the walker and to this table at once -- which is how this one
#                         went three rounds without either. The reason for leaving it: the label
#                         reaches the MESSAGE and nothing else. It decides no guard, changes no
#                         value and cannot alter an exception TYPE, which is what a caller branches
#                         on. What that reason UNDERSTATES, corrected here rather than left to be
#                         re-measured: `where = f"{name}[{i}][{j}]"` and the `what` strings are
#                         built EAGERLY, on the SUCCESS path, so the channel fires on fully valid
#                         input and not only while a refusal is being phrased.         [declared]
#
# NOT conversion, so deliberately not re-decided here: the ARITHMETIC and COMPARISON dunders.
# They are the module docstring's own claim, closed by `_plain_real` at every guard and swept by
# the derived liar sweep in the tests. `_same`'s bare `==` is the one of them whose left operand
# comes back from a caller's CALLABLE rather than from a caller's ARGUMENT, and `_plain_real` is
# NOT on its own enough there -- the correction this round makes, because the sentence that used to
# stand here ("`_plain_real` closes it there too (measured: a callable that swaps in a value whose
# `__eq__` raises still gets 'mutated its input in place')") was TRUE ONLY FOR THE `float` SUBCLASS
# THAT MEASUREMENT USED, which was also the only base the test fixture asserting it used.
# `_plain_real` normalises `bool`/`int`/`float` and returns everything else UNCHANGED, so for a
# plain object, a `numbers.Real` subclass or a `Fraction` subclass the bare `==` was still the
# caller's. THE MEASUREMENT THAT ESTABLISHED THAT HAS ONE HOME, the module docstring at the top of
# this file, and is deliberately not restated here. It used to be written out in three places -- the
# module docstring, this comment and `_same`'s docstring -- of which only the first was pinned, so
# the other two were free to drift: measured, a `30` edited to `29` in either of them, and this
# comment's `12` and `15` edited by one, were each unkilled by all three permitted suites on both
# interpreters, while the identical edit inside the module docstring died. A figure in three places
# needs three pins or one home. `_same` now decides on the NORMALISED value or not at all; see
# there, and see the module docstring for the cell counts.
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
    and raises (in-place mutation of inputs) -- WITH ONE QUALIFIER, stated here
    because this is the only sentence about that guard a caller reads. What is
    compared is VALUE, not identity: a callable that writes back a plain `int`,
    a `float` subclass or a `numpy` `float64` storing the number that was
    already in the slot is NOT reported as a mutation and still gets a PASS
    report. Anything else in the slot is a write, whatever it says about its
    own equality (`_same`). `point` itself is never modified.

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
    """Is the post-call slot `a` still the snapshot value `b`? Decided on PLAIN NUMBERS or not at all.

    `b` is always a plain `float` this module put in the list (`check_finite_sequence`'s tuple, or a
    coordinate stepped by a validated float). `a` is whatever the caller's CALLABLE left in the slot,
    which makes it the LEFT operand of a bare `==` -- the one operand position in this module that a
    caller's own callable fills -- so without normalisation it answers for itself.

    TWO RULES, and the second is what the round that wrote the first one missed. `_plain_real` is the
    first: a `float`/`int` subclass with a lying `__eq__` cannot claim to be unchanged, because what
    is compared is the `int`/`float` it STORES. But `_plain_real` normalises only `bool`/`int`/`float`
    and its own docstring says so: a plain object, a `numbers.Real` subclass and a `Fraction` subclass
    come back UNCHANGED (measured: `_plain_real(o) is o`), and for those three the bare `==` was still
    theirs. The cell-by-cell measurement of what that cost is in the MODULE DOCSTRING, which is its
    one home; it is not restated here, because it was restated in three places and only one of those
    copies was pinned, which left the other two free to drift.

    So the second rule: anything normalisation cannot reduce to exactly `int` or `float` is REPORTED AS
    A WRITE. IT IS NOT ASKED WHETHER IT IS EQUAL. That is correct as well as closed -- `b` is a plain
    `float`, so a slot now holding a `Fraction`, a `bool`, an arbitrary object or a `numpy` scalar
    THAT IS NOT A `float` SUBCLASS HAS been written to, whatever that object says about
    equality -- and it is what makes the module
    docstring's "no guard here is decided by the caller's object" true at this operand. `type(...) is`
    and not `isinstance`, deliberately: `bool` is an `int` subclass that `_plain_real` deliberately
    does not collapse, and `isinstance` would let `True` pass for the `1.0` it replaced (measured
    before this: it did).

    THE QUALIFIER THAT RULE NEEDS, corrected here rather than left to be re-measured: this docstring
    used to say "It is not asked", flat, and that was wider than the mechanism. The object is not
    asked whether it is EQUAL -- which is the claim that matters, and is the claim the module
    docstring makes -- but ONE question is still put to it, and it is the `__class__` channel this
    module declares OPEN. `_plain_real`'s own first statement is `isinstance(v, bool)`, and
    `isinstance` consults `__class__`: measured, three `__class__` reads per `_same` call when the
    reads SUCCEED, and exactly ONE when the first of them raises -- the distinction matters because
    a read count is how a test tells a driven route from a fixture that refused before reaching the
    object. A slot holding an object whose `__class__` RAISES takes that exception out of
    `check_gradient` unconverted, byte-identically on 3.12.4 and 3.13.5 with numpy present and
    absent. That is the
    route this round added to the MEASURED SCOPE sentence above, where it is one of the 28 escapes;
    it is NOT closed here, because closing it is the three owners' joint fix, and every other hostile
    shape at this operand -- sixteen of them, at both callable positions -- is refused in family.
    That figure was TYPED and unpinned until now; it is eight dunder-raising shapes at two callable
    positions, derived and swept cell by cell in `test_h1`, which also checks that the list of eight
    named in the MEASURED SCOPE comment above is the list it sweeps.

    THE ONE BEHAVIOUR CHANGE, stated because it is a real narrowing: a callable that replaces a
    coordinate with a value-EQUAL object of another type -- `True`, `Fraction(1, 1)`, a `numpy`
    `float32` -- now gets "mutated its input in place" where it used to pass. A plain `int` and a
    `float` subclass storing the same value still pass, because both normalise to a plain number and
    the comparison is then between two plain numbers.

    WHICH NUMPY SCALARS, because "a `numpy` float" was WRONG here and contradicted the sentence
    after it in this same paragraph: `np.float64` IS a Python `float` subclass, so it normalises and
    a value-equal `float64` write-back still PASSES -- measured, `_same(np.float64(1.0), 1.0)` is
    True. `float32`, `float16` and `int64` are not `float` subclasses and those ARE writes.
    `check_gradient`'s own docstring says this correctly, naming `float64`, and the suite pins the
    split; it was only this private docstring's unqualified phrase that was false.
    """
    a = _plain_real(a)
    if type(a) is not float and type(a) is not int:
        return False                 # not normalisable: a different object is in the slot, full stop
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
