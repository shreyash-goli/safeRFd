"""SR-06 tests: adversarial numeric cases for toy.stability. Abstract numbers only;
no biological content and no claim about any real system."""
import copy
import dataclasses
import functools
import inspect
import math
import sys
import types
import unittest
from fractions import Fraction
from numbers import Rational, Real
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from toy import stability as st
from toy.teacher_student import masked_mse_loss_and_grad

try:
    import numpy as np
except Exception:  # numpy is optional; never required
    np = None

NAN, INF, NINF = float("nan"), float("inf"), float("-inf")
X = ((1.0, 2.0), (3.0, 4.0), (0.5, -1.0))
T = ((0.0, 1.0), (3.0, 2.0), (0.0, 0.0))
P = (0.7, 0.9, 0.1, -0.2)
M = (True, False, True)


class Truthy:
    def __bool__(self):
        return True


# --------------------------------------------------------------------------- NOTE E
# `python -OO` strips docstrings, so `inspect.cleandoc(None)` raised
# `AttributeError: 'NoneType' object has no attribute 'expandtabs'` and the doc pins came out as
# ERRORS: Ran 72, FAILED (errors=5) on BOTH 3.12.4 and 3.13.5. Symmetric across interpreters, so
# NOT the asymmetric class that got this module unmarked, and `-OO` is not a mode this project
# runs -- but an error is the wrong report for "the pins cannot run". The guard is this helper
# plus a plain `if` at each pin, DELIBERATELY NOT `skipUnless`: a guard that can SKIP is the
# failure mode to avoid, because one that fired in the mode the project does run would hide a
# pin. This shape cannot skip anything in any mode. It drops only the doc half of a pin and
# leaves every BEHAVIOURAL assertion running, and
# `test_e_the_docstring_guard_is_inert_in_a_normal_run` asserts it is inert whenever docstrings
# exist, which is every run this project makes.
#
# A module-level `_DOCSTRINGS_PRESENT = st.__doc__ is not None` used to sit here. It had exactly
# one consumer -- the first assertion of that test -- and that assertion is now written there
# directly against `st.__doc__`, which is what it was always about. A constant whose only purpose
# is to be asserted equal to its own definition is residue, and residue in a file about
# load-bearing sentences is the wrong kind of example.
#
# THE ONE REAL `skipIf` IN THIS FILE, reconciled with the paragraph above rather than left to
# look like a contradiction: `Masks.test_numpy_scalars_rejected` is guarded by
# `@unittest.skipIf(np is None)`. Note E's hazard is a guard that can skip a pin whose SUBJECT
# STILL EXISTS -- `-OO` strips docstrings but leaves every behaviour assertable, so skipping
# there would hide a pin and still report OK. The numpy guard is the other case: without numpy
# there is no `np.bool_`/`np.int64` to hand `check_mask`, so there is nothing to assert, and the
# alternatives are a skip or a silently vacuous pass. The skip is better because it is COUNTED:
# `scripts/test_baseline.txt`'s bare-environment column records exactly this one skip, and
# `scripts/run_tests.sh` fails a bare run that reports fewer. An UNCOUNTED skip is the hazard;
# this one is the project's only skip here and
# `test_the_only_skip_in_this_file_is_the_counted_numpy_one` asserts it stays the only one.
# Every other numpy-dependent assertion in this file is behind a plain `if np is not None`, and
# that sentence is now true AS TO SPELLING as well as in substance: one of those guards used to be
# spelled `if _np is not None:` behind a function-local `import numpy as _np`, so the assertion
# that counted the guards could not see it, while the assertion that counted them was itself a
# `src.count("if np is not None:")` -- a self-count, of whose two hits ONE WAS THE ASSERTION'S OWN
# STRING LITERAL. The local import is gone (the module-level `np` was already there), and the count
# is derived from this file's AST over `ast.If` tests, which cannot include a string literal and
# cannot miss a respelling: `test_the_only_skip_in_this_file_is_the_counted_numpy_one` fails on any
# `if <word>np is not None:` it does not expect.


def _doc(obj):
    """`inspect.cleandoc(obj.__doc__)`, or None when the docstring is stripped or SUBSTITUTED.

    Two ways a docstring can be absent, and the second one is not None. `python -OO` strips them, so
    `inspect.cleandoc(None)` used to raise and the pins came out as ERRORS -- that is NOTE E above.
    The other way is this module's single `@dataclass`: `dataclasses` SUBSTITUTES a synthesised
    signature string for a class with no docstring of its own, so under `-OO`
    `GradientCheckReport.__doc__` is not None, it is
    `"GradientCheckReport(analytic: 'tuple[float, ...]', ...)"`. Measured on both interpreters;
    `GradientCheckReport` is this module's ONLY dataclass and the ONLY one of its 14 classes whose
    `__doc__` survives `-OO`. A None check cannot see that: the docstring is present and wrong, and
    the first pin anyone writes on this class would compare its needle against a signature string.

    No pin reads it today, so there is NO consequence at this commit -- this is the latent half,
    adopted from `test_robustness`, which grew the detector for three live sites. The substitution is
    detected by RECONSTRUCTING it with the expression `dataclasses` itself evaluates, not by
    pattern-matching the text: if a real docstring ever equals its own synthesised signature there is
    nothing to pin anyway, and if `dataclasses` changes that expression this helper STOPS
    suppressing and the pin fails LOUDLY rather than passing for the wrong reason.
    `test_e_the_docstring_guard_is_inert_in_a_normal_run` asserts both halves in both modes.
    """
    d = getattr(obj, "__doc__", None)
    if d is None:
        return None
    if isinstance(obj, type) and dataclasses.is_dataclass(obj) and d == _dataclass_signature_doc(obj):
        return None
    return inspect.cleandoc(d)


def _dataclass_signature_doc(cls):
    """The docstring `@dataclass` synthesises for a class that has none: the class name plus its own
    signature with the `-> None` stripped, which is the expression `dataclasses.py` itself evaluates."""
    return cls.__name__ + str(inspect.signature(cls)).replace(" -> None", "")


# --------------------------------------------------------------------------- FINDING C
# Objects for which `hasattr(o, "__iter__")` is True while `tuple(o)` raises. Each is a FACTORY,
# because an intake site may legitimately consume its argument.
#
# The FIRST shape is the one that needs no `object.__setattr__`, no metaclass and no exotic
# machinery: `__iter__` assigned on the INSTANCE. Special-method lookup is on the TYPE, so
# `hasattr` says yes and `tuple()` says no. That is CLAUDE.md's rule-9 smell in its plainest
# form, which is why it leads the table.
def _instance_attr_iter():
    class Plain:
        pass
    o = Plain()
    o.__iter__ = lambda: iter([1.0, 2.0])     # instance attribute: never consulted by tuple()
    return o


def _iter_raises(exc):
    return lambda: type(f"IterRaises{exc.__name__}", (),
                        {"__iter__": lambda s: (_ for _ in ()).throw(exc("boom"))})()


def _getattr_raises(exc):
    """A hostile `__getattr__`: `hasattr(o, "__iter__")` PROPAGATES anything but AttributeError.
    This is the fourth intake site, which deriving the set surfaced and no report had named."""
    return lambda: type(f"GetattrRaises{exc.__name__}", (),
                        {"__getattr__": lambda s, n: (_ for _ in ()).throw(exc("ga"))})()


_BROKEN_ITER = (
    ("instance-attribute __iter__", _instance_attr_iter),
    ("class attribute __iter__ = 5", lambda: type("BadIter", (), {"__iter__": 5})()),
    ("__iter__ raises TypeError", _iter_raises(TypeError)),
    ("__iter__ returns a non-iterator", lambda: type("NonIter", (), {"__iter__": lambda s: 42})()),
)

# NOTE D: the same broken `__iter__`, raising classes OTHER than TypeError. Measured at HEAD from
# the two sites that DID wrap: ValueError escaped as a BARE ValueError (inside ValueError, outside
# StabilityError) and RuntimeError / KeyError escaped ValueError entirely.
_BROKEN_ITER_OTHER = tuple((f"__iter__ raises {e.__name__}", _iter_raises(e))
                           for e in (ValueError, RuntimeError, KeyError, ZeroDivisionError))

# The fourth site's shapes.
_BROKEN_GETATTR = tuple((f"__getattr__ raises {e.__name__}", _getattr_raises(e))
                        for e in (RuntimeError, ValueError, TypeError, KeyError))

# FINDING G2. The same defect class one protocol over: a CONVERSION this module invokes on the
# caller's data raises. `_iter_raises` is to the iterator protocol what `_float_raises` is to the
# conversion protocol, and the shapes join the sibling table above so that the derived sweep
# (`test_c1`) reaches the `float()` sites at every data position instead of a hand-written list of
# three. Measured at the commit before this one, identically on 3.12.4 and 3.13.5: 5 exception
# classes x 9 public entry points = 45/45 outcomes outside StabilityError, 36 of them outside
# ValueError entirely, because each `float()` site caught exactly `OverflowError`.
#
# The object has to be a `numbers.Real`: the type gate runs first, so a non-Real never reaches a
# conversion. These are the stub implementations `Real`'s abstract set requires, nothing more.
_REAL_STUBS = {"__trunc__": lambda s: 0, "__floor__": lambda s: 0, "__ceil__": lambda s: 0,
               "__round__": lambda s, n=None: 0, "__abs__": lambda s: s, "__neg__": lambda s: s,
               "__pos__": lambda s: s, "__add__": lambda s, o: s, "__radd__": lambda s, o: s,
               "__mul__": lambda s, o: s, "__rmul__": lambda s, o: s,
               "__truediv__": lambda s, o: s, "__rtruediv__": lambda s, o: s,
               "__pow__": lambda s, o: s, "__rpow__": lambda s, o: s, "__mod__": lambda s, o: s,
               "__rmod__": lambda s, o: s, "__floordiv__": lambda s, o: s,
               "__rfloordiv__": lambda s, o: s, "__lt__": lambda s, o: False,
               "__le__": lambda s, o: False, "__eq__": lambda s, o: False, "__hash__": lambda s: 0}


def _float_raises(exc):
    """A caller-defined `numbers.Real` whose `__float__` raises `exc`. A FACTORY, like the intake
    shapes, because a site may legitimately consume its argument."""
    return lambda: type(f"FloatRaises{exc.__name__}", (Real,),
                        dict(_REAL_STUBS,
                             __float__=lambda s: (_ for _ in ()).throw(exc("float() boom"))))()


_FLOAT_EXCS = (ZeroDivisionError, KeyError, RuntimeError, TypeError, ValueError)
_BROKEN_FLOAT = tuple((f"__float__ raises {e.__name__}", _float_raises(e)) for e in _FLOAT_EXCS)


def _repr_raises(exc):
    """A caller object whose `__repr__` raises: the protocol every error MESSAGE here invokes on
    the value it is refusing. Not a `Real`, so it is refused for being non-numeric -- and the
    refusal used to be replaced by this exception while the message was being built."""
    return lambda: type(f"ReprRaises{exc.__name__}", (),
                        {"__repr__": lambda s: (_ for _ in ()).throw(exc("repr boom"))})()


class Finite(unittest.TestCase):
    def test_scalars_bad(self):
        for bad in (NAN, INF, NINF):
            with self.assertRaisesRegex(st.NonFiniteError, "non-finite"):
                st.check_finite_scalar(bad, "loss")
        with self.assertRaisesRegex(st.NonFiniteError, "too large"):
            st.check_finite_scalar(10 ** 400)
        for bad in (None, "1.0", True, [1.0]):
            with self.assertRaisesRegex(st.NonNumericError, "not a real number"):
                st.check_finite_scalar(bad)

    def test_sequence_positions(self):
        for bad in (NAN, INF, NINF):
            for idx in (0, 2, 4):
                v = [1.0] * 5
                v[idx] = bad
                with self.assertRaises(st.NonFiniteError) as cm:
                    st.check_finite_sequence(v, "v")
                self.assertIn(f"v[{idx}]", str(cm.exception))
                self.assertIn(repr(bad), str(cm.exception))

    def test_matrix_positions(self):
        for bad in (NAN, INF, NINF):
            for (i, j) in ((0, 0), (1, 1), (2, 2)):
                m = [[1.0] * 3 for _ in range(3)]
                m[i][j] = bad
                with self.assertRaises(st.NonFiniteError) as cm:
                    st.check_finite_matrix(m, "m")
                self.assertIn(f"m[{i}][{j}]", str(cm.exception))

    def test_shape_and_type_errors(self):
        with self.assertRaisesRegex(st.ShapeError, "empty"):
            st.check_finite_sequence([])
        with self.assertRaisesRegex(st.ShapeError, "ragged"):
            st.check_finite_matrix([[1.0, 2.0], [3.0]])
        with self.assertRaisesRegex(st.ShapeError, "empty"):
            st.check_finite_matrix([])
        with self.assertRaisesRegex(st.ShapeError, "empty row"):
            st.check_finite_matrix([[]])
        with self.assertRaisesRegex(st.ShapeError, "not a row"):
            st.check_finite_matrix([1.0, 2.0])
        with self.assertRaisesRegex(st.ShapeError, "sequence"):
            st.check_finite_sequence("abc")
        with self.assertRaisesRegex(st.NonNumericError, r"v\[1\]"):
            st.check_finite_sequence([1.0, None], "v")

    def test_negative_zero_accepted_and_preserved(self):
        self.assertEqual(math.copysign(1.0, st.check_finite_scalar(-0.0)), -1.0)
        self.assertEqual(math.copysign(1.0, st.check_finite_sequence([-0.0, 1.0])[0]), -1.0)
        self.assertEqual(math.copysign(1.0, st.check_finite_matrix([[-0.0]])[0][0]), -1.0)
        self.assertEqual(st.masked_mean_checked([-0.0, -0.0], [True, True], 2), 0.0)

    def test_is_valueerror(self):
        with self.assertRaises(ValueError):
            st.check_finite_scalar(NAN)


class Masks(unittest.TestCase):
    def test_non_bool_entries(self):
        for bad in (0, 1, None, Truthy(), "yes", 1.0):
            with self.assertRaisesRegex(st.MaskTypeError, r"strict bool"):
                st.check_mask([True, bad], 2)

    @unittest.skipIf(np is None, "numpy not installed (optional)")
    def test_numpy_scalars_rejected(self):
        for bad in (np.int64(1), np.bool_(True)):
            with self.assertRaisesRegex(st.MaskTypeError, "strict bool"):
                st.check_mask([True, bad], 2)

    def test_non_sequence_mask(self):
        for bad in (None, 5, "TT", {True: 1}):
            with self.assertRaisesRegex(st.MaskTypeError, "sequence of bool"):
                st.check_mask(bad, 1)

    def test_length_mismatch(self):
        with self.assertRaisesRegex(st.MaskLengthError, "length 2 != data length 3"):
            st.check_mask([True, True], 3)

    def test_all_false_and_empty(self):
        with self.assertRaisesRegex(st.EmptyMaskError, "all False"):
            st.check_mask([False, False], 2)
        with self.assertRaisesRegex(st.EmptyMaskError, "empty"):
            st.check_mask([])
        with self.assertRaises(st.EmptyMaskError):
            st.masked_mean_checked([1.0, 2.0], [False, False], 1)

    def test_distinct_errors(self):
        classes = {st.MaskTypeError, st.MaskLengthError, st.EmptyMaskError}
        self.assertEqual(len(classes), 3)
        for a in classes:
            for b in classes - {a}:
                self.assertFalse(issubclass(a, b))

    def test_valid(self):
        self.assertEqual(st.check_mask([True, False], 2), (True, False))
        self.assertEqual(st.check_mask((False, True)), (False, True))


class MaskedLoss(unittest.TestCase):
    def test_flat_mean(self):
        self.assertEqual(st.masked_mean_checked([1.0, 100.0, 3.0], [True, False, True], 2), 2.0)

    def test_matrix_correct_denominator(self):
        sq = ((1.0, 1.0), (9.0, 9.0), (2.0, 2.0))
        self.assertEqual(st.masked_mean_checked(sq, M, 4), 6.0 / 4)

    def test_off_by_row_width(self):
        sq = ((1.0, 1.0, 1.0), (9.0, 9.0, 9.0))
        with self.assertRaises(st.NormalizationMismatchError) as cm:
            st.masked_mean_checked(sq, [True, True], 2)  # sum(mask), not sum(mask)*3
        self.assertIn("denominator 2 != summed element count 6", str(cm.exception))
        self.assertIn("off by the row width 3", str(cm.exception))

    def test_other_mismatches(self):
        for d in (0, 1, 3, -2):
            with self.assertRaises(st.NormalizationMismatchError):
                st.masked_mean_checked([1.0, 2.0], [True, True], d)
        for d in (2.0, True, None, "2"):
            with self.assertRaisesRegex(st.NormalizationMismatchError, "int element count"):
                st.masked_mean_checked([1.0, 2.0], [True, True], d)

    def test_matches_teacher_student(self):
        for norm, denom in (("per_masked_element", 4),):
            loss, _ = masked_mse_loss_and_grad(P, X, T, M, norm)
            pred = tuple(tuple(v * P[j] + P[2 + j] for j, v in enumerate(r)) for r in X)
            self.assertAlmostEqual(st.masked_squared_error_mean(pred, T, M, denom), loss, places=12)
            # ts "per_mask_entry" uses divisor sum(mask) -> the audited mismatch; rejected here.
            with self.assertRaisesRegex(st.NormalizationMismatchError, "row width"):
                st.masked_squared_error_mean(pred, T, M, sum(M))

    def test_masked_out_nan_strict_default(self):
        for bad in (NAN, INF, NINF):
            with self.assertRaisesRegex(st.NonFiniteError, "masked OUT") as cm:
                st.masked_mean_checked([1.0, bad], [True, False], 1)
            _ = cm
        # lenient policy is an explicit opt-in (historical behaviour of erasure_demo.masked_mse
        # at e436d93, since hardened); this test does not depend on that file
        self.assertEqual(st.masked_mean_checked([1.0, NAN], [True, False], 1, strict_masked_out=False), 1.0)

    def test_masked_in_nonfinite_always_rejected(self):
        for strict in (True, False):
            with self.assertRaisesRegex(st.NonFiniteError, r"\[1\]\[0\]"):
                st.masked_mean_checked(((1.0,), (NAN,)), [True, True], 2, strict_masked_out=strict)

    def test_masked_out_non_numeric_rejected_even_lenient(self):
        with self.assertRaises(st.NonNumericError):
            st.masked_mean_checked([1.0, None], [True, False], 1, strict_masked_out=False)

    def test_length_and_shape(self):
        with self.assertRaises(st.MaskLengthError):
            st.masked_mean_checked([1.0, 2.0, 3.0], [True, True], 2)
        with self.assertRaisesRegex(st.ShapeError, "length"):
            st.masked_squared_error_mean([1.0], [1.0, 2.0], [True], 1)
        with self.assertRaisesRegex(st.ShapeError, "width"):
            st.masked_squared_error_mean(((1.0, 2.0),), ((1.0,),), [True], 2)
        with self.assertRaisesRegex(st.ShapeError, "flat or both"):
            st.masked_squared_error_mean([1.0], [[1.0]], [True], 1)

    def test_overflow_is_loud(self):
        with self.assertRaises(st.NonFiniteError):
            st.masked_squared_error_mean([1e200], [-1e200], [True], 1)
        with self.assertRaisesRegex(st.NonFiniteError, "overflow"):
            st.masked_mean_checked([1e308, 1e308], [True, True], 2)


class Gradient(unittest.TestCase):
    def setUp(self):
        self.p = [0.7, 0.9, 0.1, -0.2]
        self.fn = lambda p: masked_mse_loss_and_grad(p, X, T, M)[0]
        self.gf = lambda p: masked_mse_loss_and_grad(p, X, T, M)[1]

    def test_correct_passes(self):
        r = st.check_gradient(self.fn, self.gf, self.p)
        self.assertLess(r.max_abs_error, 1e-6)
        self.assertEqual(len(r.analytic), 4)

    def test_wrong_gradients_caught(self):
        wrong = {
            "sign flip": lambda p: [-g for g in self.gf(p)],
            "scale by 2": lambda p: [2 * g for g in self.gf(p)],
            "one coordinate off": lambda p: [self.gf(p)[0] + 0.5] + list(self.gf(p)[1:]),
            "per_mask_entry norm": lambda p: masked_mse_loss_and_grad(p, X, T, M, "per_mask_entry")[1],
        }
        for label, g in wrong.items():
            with self.subTest(label), self.assertRaisesRegex(st.GradientMismatchError, "mismatch at index"):
                st.check_gradient(self.fn, g, self.p)

    def test_zero_gradient_rejected(self):
        with self.assertRaisesRegex(st.DegenerateGradientError, "identically zero"):
            st.check_gradient(self.fn, lambda p: [0.0] * 4, self.p)
        # a flat function with its (correct) zero gradient is still not evidence
        with self.assertRaises(st.DegenerateGradientError):
            st.check_gradient(lambda p: 1.0, lambda p: [0.0] * 4, self.p)
        # -0.0 counts as zero
        with self.assertRaises(st.DegenerateGradientError):
            st.check_gradient(self.fn, lambda p: [-0.0] * 4, self.p)

    def test_nonfinite_gradient_rejected(self):
        for bad in (NAN, INF, NINF):
            g = lambda p, b=bad: [1.0, b, 1.0, 1.0]
            with self.assertRaisesRegex(st.NonFiniteError, r"analytic gradient\[1\]"):
                st.check_gradient(self.fn, g, self.p)

    def test_missing_and_wrong_length(self):
        with self.assertRaises(st.MissingGradientError):
            st.check_gradient(self.fn, lambda p: None, self.p)
        with self.assertRaisesRegex(st.ShapeError, "length"):
            st.check_gradient(self.fn, lambda p: [1.0], self.p)

    def test_nonfinite_function_value(self):
        with self.assertRaises(st.NonFiniteError):
            st.check_gradient(lambda p: NAN, lambda p: [1.0] * 4, self.p)

    def test_bad_config(self):
        for kw in ({"step": 0.0}, {"step": -1e-6}, {"step": NAN}, {"rtol": -1.0}, {"atol": INF}):
            with self.assertRaises(st.StabilityError):
                st.check_gradient(self.fn, self.gf, self.p, **kw)
        with self.assertRaises(st.NonFiniteError):
            st.check_gradient(self.fn, self.gf, [NAN, 0, 0, 0])

    def test_tolerance_is_real(self):
        # a tiny perturbation passes a loose tolerance and fails a tight one
        g = lambda p: [x * 1.001 for x in self.gf(p)]
        st.check_gradient(self.fn, g, self.p, rtol=1e-2)
        with self.assertRaises(st.GradientMismatchError):
            st.check_gradient(self.fn, g, self.p, rtol=1e-5)

    def test_misconfigured_step_fails_correct_gradient(self):
        # documented limit: a huge step biases a correct gradient on a cubic
        f = lambda p: p[0] ** 3
        g = lambda p: [3 * p[0] ** 2]
        st.check_gradient(f, g, [1.0])
        with self.assertRaises(st.GradientMismatchError):
            st.check_gradient(f, g, [1.0], step=0.5)

    def test_mutating_callable_detected(self):
        def evil(p):
            p[0] += 1.0
            return 1.0
        with self.assertRaisesRegex(st.StabilityError, "mutated its input"):
            st.check_gradient(self.fn, lambda p: (p.append(0.0), [1.0] * 4)[1], self.p)
        with self.assertRaisesRegex(st.StabilityError, "mutated its input"):
            st.check_gradient(evil, self.gf, self.p)


class ParameterGuard(unittest.TestCase):
    def test_none_param_grad_with_finite_input_grad(self):
        with self.assertRaises(st.MissingGradientError) as cm:
            st.require_parameter_gradient(None, input_grad=[0.3, 0.2])
        self.assertIn("NOT evidence", str(cm.exception))
        with self.assertRaisesRegex(st.MissingGradientError, "is None"):
            st.require_parameter_gradient(None)

    def test_bad_param_grads(self):
        with self.assertRaises(st.DegenerateGradientError):
            st.require_parameter_gradient([0.0, -0.0])
        with self.assertRaises(st.NonFiniteError):
            st.require_parameter_gradient([1.0, NAN])
        self.assertEqual(st.require_parameter_gradient([0.0, 2.0]), (0.0, 2.0))

    def test_noop_update(self):
        with self.assertRaisesRegex(st.NoOpUpdateError, "unchanged"):
            st.check_params_changed([1.0, 2.0], [1.0, 2.0])
        with self.assertRaises(st.NoOpUpdateError):
            st.check_params_changed([1.0], [1.0 + 1e-12], min_abs_change=1e-9)
        with self.assertRaises(st.ShapeError):
            st.check_params_changed([1.0], [1.0, 2.0])
        with self.assertRaises(st.NonFiniteError):
            st.check_params_changed([1.0], [NAN])
        self.assertEqual(st.check_params_changed([1.0, 2.0], [1.0, 2.5]), 0.5)


class NoMutationAndNoSilentPass(unittest.TestCase):
    def test_inputs_unchanged(self):
        vec, mat, mask = [1.0, -0.0, 3.0], [[1.0, 2.0], [3.0, 4.0]], [True, False]
        pt = [0.7, 0.9, 0.1, -0.2]
        snaps = [copy.deepcopy(o) for o in (vec, mat, mask, pt)]
        st.check_finite_scalar(1.0)
        st.check_finite_sequence(vec)
        st.check_finite_matrix(mat)
        st.check_mask(mask, 2)
        st.masked_mean_checked(mat, mask, 2)
        st.masked_squared_error_mean(mat, mat, mask, 2)
        st.check_gradient(lambda p: masked_mse_loss_and_grad(p, X, T, M)[0],
                          lambda p: masked_mse_loss_and_grad(p, X, T, M)[1], pt)
        st.require_parameter_gradient(vec)
        st.check_params_changed(vec, [9.0, 9.0, 9.0])
        self.assertEqual([vec, mat, mask, pt], snaps)

    def test_inputs_unchanged_on_failure(self):
        mat, mask = [[1.0, NAN], [3.0, 4.0]], [True, True]
        snap = copy.deepcopy((mat, mask))
        for call in (lambda: st.check_finite_matrix(mat), lambda: st.masked_mean_checked(mat, mask, 4)):
            with self.assertRaises(st.StabilityError):
                call()
        self.assertEqual(repr((mat, mask)), repr(snap))

    def test_every_bad_input_raises_not_returns(self):
        bad_calls = [
            lambda: st.check_finite_scalar(NAN), lambda: st.check_finite_sequence([INF]),
            lambda: st.check_finite_matrix([[NINF]]), lambda: st.check_mask([1]),
            lambda: st.check_mask([False]), lambda: st.check_mask([True], 2),
            lambda: st.masked_mean_checked([1.0], [True], 2),
            lambda: st.masked_squared_error_mean([NAN], [1.0], [True], 1),
            lambda: st.check_gradient(lambda p: p[0], lambda p: [0.0], [1.0]),
            lambda: st.check_gradient(lambda p: p[0], lambda p: [2.0], [1.0]),
            lambda: st.require_parameter_gradient(None),
            lambda: st.check_params_changed([1.0], [1.0]),
        ]
        import warnings
        for i, c in enumerate(bad_calls):
            with self.subTest(i), warnings.catch_warnings():
                warnings.simplefilter("error")  # a bare warning would also surface as an error
                with self.assertRaises(st.StabilityError):
                    c()


class QAHardening(unittest.TestCase):
    """Tests added after QA mutation testing (SR-06 round 2)."""

    def setUp(self):
        self.p = [0.7, 0.9, 0.1, -0.2]
        self.fn = lambda p: masked_mse_loss_and_grad(p, X, T, M)[0]
        self.gf = lambda p: masked_mse_loss_and_grad(p, X, T, M)[1]

    # M-S1: the comparison loop must cover every coordinate
    def test_error_only_at_one_coordinate_is_caught(self):
        for bad_idx in (1, 2, 3):  # index 1, interior 2, last 3 (index 0 is correct in each)
            for label, tweak in (("offset", lambda a: a + 0.5), ("sign", lambda a: -a), ("x2", lambda a: 2 * a)):
                def g(p, k=bad_idx, tw=tweak):
                    out = list(self.gf(p))
                    out[k] = tw(out[k])
                    return out
                with self.subTest(index=bad_idx, kind=label):
                    with self.assertRaises(st.GradientMismatchError) as cm:
                        st.check_gradient(self.fn, g, self.p)
                    self.assertIn(f"index {bad_idx}", str(cm.exception))

    # M-S2: a correct gradient with one zero component must pass
    def test_correct_gradient_with_a_zero_component_passes(self):
        f = lambda p: p[0] ** 2 + p[1] ** 2
        r = st.check_gradient(f, lambda p: [2 * p[0], 2 * p[1]], [0.0, 1.0])
        self.assertEqual(r.analytic, (0.0, 2.0))

    # D-S1: huge ints raise StabilityError (a ValueError), never bare OverflowError
    def test_huge_int_is_stability_error(self):
        for call in (lambda: st.masked_mean_checked([10 ** 400], [True], 1),
                     lambda: st.masked_mean_checked([1.0, 10 ** 400], [True, False], 1),
                     lambda: st.masked_mean_checked([[1.0, 10 ** 400]], [True], 2),
                     lambda: st.masked_squared_error_mean([10 ** 400], [0.0], [True], 1),
                     lambda: st.masked_squared_error_mean([0.0], [10 ** 400], [True], 1)):
            with self.assertRaises(st.NonFiniteError):
                try:
                    call()
                except OverflowError:
                    self.fail("bare OverflowError escaped")
        # lenient policy: a masked-out huge int is simply not used
        self.assertEqual(st.masked_mean_checked([1.0, 10 ** 400], [True, False], 1, strict_masked_out=False), 1.0)

    # M-S3: mask longer than data
    def test_mask_longer_than_data(self):
        with self.assertRaises(st.MaskLengthError):
            st.check_mask([True, True, True], 2)
        with self.assertRaises(st.MaskLengthError):
            st.masked_mean_checked([1.0, 2.0], [True, True, True], 2)

    # M-S4 / M-S6: bool is not a number in the masked path
    def test_bool_values_rejected(self):
        for strict in (True, False):
            with self.assertRaises(st.NonNumericError):
                st.masked_mean_checked([True, 1.0], [True, True], 2, strict_masked_out=strict)
            with self.assertRaises(st.NonNumericError):
                st.masked_mean_checked([1.0, False], [True, False], 1, strict_masked_out=strict)
        with self.assertRaises(st.NonNumericError):
            st.masked_squared_error_mean([True], [0.0], [True], 1)
        with self.assertRaises(st.NonNumericError):
            st.masked_squared_error_mean([1.0], [False], [True], 1)

    # M-S5: an overflowing difference must never become 0.0
    def test_squared_error_overflow_not_zero(self):
        for strict in (True, False):
            with self.assertRaises(st.NonFiniteError):
                st.masked_squared_error_mean([10 ** 400], [0.0], [True], 1, strict_masked_out=strict)
        with self.assertRaises(st.NonFiniteError):
            st.masked_squared_error_mean([1.0, 10 ** 400], [1.0, 0.0], [True, False], 1)  # strict, masked out

    # M-S7: Mapping/set are not sequences on the value path either
    def test_mapping_and_set_values_rejected(self):
        for bad in ({1.0: 1}, {1.0}, frozenset({1.0})):
            with self.assertRaises(st.ShapeError):
                st.check_finite_sequence(bad)
            with self.assertRaises(st.ShapeError):
                st.masked_mean_checked(bad, [True], 1)
            with self.assertRaises(st.ShapeError):
                st.check_finite_matrix(bad)

    # M-S11: negative min_abs_change would disable the no-op guard
    def test_negative_min_abs_change_rejected(self):
        with self.assertRaisesRegex(st.StabilityError, ">= 0"):
            st.check_params_changed([1.0], [1.0], min_abs_change=-1.0)

    # M-S8/9/10: tolerance is neither loosened nor unreported
    def test_default_tolerance_is_tight_and_report_populated(self):
        r = st.check_gradient(self.fn, self.gf, self.p)
        self.assertEqual((r.step, r.rtol, r.atol), (1e-6, 1e-4, 1e-6))
        self.assertEqual(r.analytic, tuple(self.gf(self.p)))
        self.assertGreater(r.max_abs_error, 0.0)
        self.assertGreater(r.max_rel_error, 0.0)
        self.assertLess(r.max_abs_error, 1e-6)
        # 3e-4 relative error is > rtol (1e-4) but < 10x looser rtol (1e-3): must fail
        with self.assertRaises(st.GradientMismatchError):
            st.check_gradient(self.fn, lambda p: [a * 1.0003 for a in self.gf(p)], self.p)
        st.check_gradient(self.fn, lambda p: [a * 1.00005 for a in self.gf(p)], self.p)

    # documented limitation: atol dominates at small scale
    def test_small_scale_blind_spot_is_real_and_documented(self):
        f = lambda p: 1e-9 * p[0] ** 2  # true gradient 2e-9 at 1.0
        st.check_gradient(f, lambda p: [2e-7], [1.0])  # 100x too large PASSES at defaults (the limitation)
        with self.assertRaises(st.GradientMismatchError):
            st.check_gradient(f, lambda p: [2e-6], [1.0])
        with self.assertRaises(st.GradientMismatchError):  # a tight atol closes the gap
            st.check_gradient(f, lambda p: [2e-7], [1.0], atol=1e-12)
        st.check_gradient(f, lambda p: [2e-9], [1.0], atol=1e-12)
        if _doc(st.check_gradient) is not None:
            self.assertIn("100x too large", st.check_gradient.__doc__)

    # D-S2: docstring claim matches behaviour
    def test_negative_zero_claim_scope(self):
        self.assertEqual(math.copysign(1.0, st.check_finite_sequence([-0.0])[0]), -1.0)
        self.assertEqual(math.copysign(1.0, st.masked_mean_checked([-0.0], [True], 1)), 1.0)
        if _doc(st.check_finite_scalar) is not None:
            self.assertIn("NOT covered", st.check_finite_scalar.__doc__)

    # D-S3: sets / dicts are not rows
    def test_set_and_dict_rows_rejected(self):
        for bad_row in ({1.0, 2.0}, {1.0: 0, 2.0: 0}, frozenset({1.0, 2.0})):
            with self.assertRaisesRegex(st.ShapeError, "not a row"):
                st.check_finite_matrix([bad_row])
            with self.assertRaisesRegex(st.ShapeError, "not a row"):
                st.masked_mean_checked([bad_row, (3.0, 4.0)], [True, True], 4)
            with self.assertRaises(st.ShapeError):
                st.masked_squared_error_mean([bad_row], [(0.0, 0.0)], [True], 2)
            with self.assertRaises(st.ShapeError):
                st.masked_squared_error_mean([(0.0, 0.0)], [bad_row], [True], 2)

    # D-S4: silent underflow to zero is an error (deliberate policy)
    def test_underflow_to_zero_raises(self):
        from fractions import Fraction
        for pred, targ in ((1e-200, 0.0), (0.0, 1e-200), (Fraction(1, 10 ** 400), 0.0),
                           (0.0, Fraction(1, 10 ** 400)), (1e-170, -1e-170)):
            with self.subTest(pred=pred):
                with self.assertRaises(st.UnderflowError):
                    st.masked_squared_error_mean([pred], [targ], [True], 1)
        # equal inputs and genuine zeros are NOT underflow
        self.assertEqual(st.masked_squared_error_mean([1e-200, 0.0], [1e-200, 0.0], [True, True], 2), 0.0)
        self.assertEqual(st.masked_squared_error_mean([0.0], [0.0], [True], 1), 0.0)
        # still a ValueError
        with self.assertRaises(ValueError):
            st.masked_squared_error_mean([1e-200], [0.0], [True], 1)

    # report fields pinned exactly on a known fixture (true gradient [2, 6])
    def test_report_fields_exact(self):
        f = lambda p: p[0] ** 2 + 3 * p[1] ** 2
        claimed = [2.0, 6.0 * (1 + 5e-5)]
        r = st.check_gradient(f, lambda p: list(claimed), [1.0, 1.0])
        self.assertEqual(r.analytic, tuple(claimed))
        self.assertNotEqual(r.numeric, r.analytic)  # numeric is its own estimate
        self.assertAlmostEqual(r.numeric[0], 2.0, delta=1e-6)
        self.assertAlmostEqual(r.numeric[1], 6.0, delta=1e-6)
        self.assertAlmostEqual(r.max_abs_error, 3e-4, delta=1e-6)  # index 1, not index 0 (~0), max not min
        self.assertAlmostEqual(r.max_rel_error, 5e-5, delta=1e-6)

    # tolerance uses max(|a|,|d|), not min
    def test_tolerance_uses_max_of_magnitudes(self):
        f = lambda p: 10.0 * p[0]
        st.check_gradient(f, lambda p: [16.0], [1.0], rtol=0.5, atol=0.0)  # |diff|=6 <= 0.5*16, > 0.5*10
        with self.assertRaises(st.GradientMismatchError):
            st.check_gradient(f, lambda p: [21.0], [1.0], rtol=0.5, atol=0.0)

    # low-severity handling
    def test_overflowing_change_raises(self):
        with self.assertRaises(st.NonFiniteError):
            st.check_params_changed([-1e308], [1e308])

    def test_step_below_float_resolution(self):
        with self.assertRaisesRegex(st.StabilityError, "too small"):
            st.check_gradient(lambda p: p[0] ** 2, lambda p: [2e8], [1e8], step=1e-12)

    def test_the_validators_return_plain_floats_and_not_a_callers_subclass(self):
        """The return TYPE, asserted directly for the first time.

        `check_finite_scalar` is documented to return `float(value)`, and `toy.robustness.mse_fsum`
        relies on getting a plain `float` when it feeds this module's output to `math.fsum`. The
        contract WAS protected -- measured, a `_as_float` that returns the caller's subclass
        unchanged is killed by 4 failures here and 7 in test_robustness -- but only INCIDENTALLY,
        through the compensated-summation figure, with no assertion anywhere on the type itself.
        It is cheap, it is a contract another module depends on, so it is asserted.
        """
        sub = type("SubFloat", (float,), {"__hash__": float.__hash__})(2.5)
        self.assertIs(type(st.check_finite_scalar(sub)), float)
        self.assertIs(type(st.check_finite_scalar(2)), float, "an int is returned as a float")
        for v in st.check_finite_sequence([sub, 2]):
            self.assertIs(type(v), float)
        for row in st.check_finite_matrix([[sub, 2]]):
            for v in row:
                self.assertIs(type(v), float)
        for v in st.require_parameter_gradient([sub, 2]):
            self.assertIs(type(v), float)
        self.assertIs(type(st.masked_mean_checked([sub], [True], 1)), float)
        self.assertIs(type(st.masked_squared_error_mean([sub], [0.0], [True], 1)), float)
        self.assertIs(type(st.check_params_changed([sub], [3.5])), float)
        r = st.check_gradient(_F_QUAD, _G_QUAD, [1.0, 2.0])
        for f in (r.max_abs_error, r.max_rel_error, r.step, r.rtol, r.atol):
            self.assertIs(type(f), float)
        for v in r.analytic + r.numeric:
            self.assertIs(type(v), float)

    def test_fn_exceptions_propagate_unwrapped_and_generators_materialised_once(self):
        with self.assertRaises(ZeroDivisionError):
            st.check_gradient(lambda p: 1 / 0, lambda p: [1.0], [1.0])
        self.assertEqual(st.masked_mean_checked(iter([1.0, 3.0]), iter([True, True]), 2), 2.0)


# ---------------------------------------------------------------------------
# SR-06 re-attestation fix (F1-F4): every guard decides on the NORMALISED value.
#
# The structural half of this fix is below, not in a wrapper: `_plain_real` is applied per site, and
# `NormalisationIsDerivedNotEnumerated` DERIVES the sweep from `inspect.signature` of every public
# function, so the NEXT un-normalised site fails closed here instead of waiting for an attester.
# ---------------------------------------------------------------------------
def _liar(value):
    """An `int`/`float` subclass STORING `value` that lies through every comparison and arithmetic
    dunder a guard might be written in, while telling the truth through the conversion protocol.

    `__float__`/`__int__` are deliberately NOT overridden HERE, and the scope of that avoidance has
    been narrowed twice, because as written it was CLAUDE.md's rule-9 smell and it hid two defects:

      * a LYING conversion (an honest-looking float from a `__float__` that answers something else)
        is a value `check_finite_scalar` is documented to return, so this sweep does not wrap it --
        but `test_f5` does, in the other direction, and found a real defect: a `NanFloat` whose
        `__float__` answered innocuously while the object STORED nan obtained a PASS report for a
        wrong gradient. So "the module never claimed it" was already only half true.
      * a RAISING conversion was never swept at all, in either direction, and that is FINDING G2:
        a `__float__` that raises is not a value to take at anyone's word, it is a failed read, and
        it escaped the declared family 45 times. It is swept now, by `_BROKEN_FLOAT` through the
        derived `test_c1` sweep and by `ConversionIsDerivedNotEnumerated` position by position.

    What this liar asserts is the remaining invariant: a liar that converts HONESTLY cannot change
    any outcome, because no guard is decided by the caller's object."""
    base = int if isinstance(value, int) else float
    ns = {"__eq__": lambda s, o: True, "__ne__": lambda s, o: False,
          "__lt__": lambda s, o: True, "__le__": lambda s, o: True,
          "__gt__": lambda s, o: False, "__ge__": lambda s, o: False,
          "__bool__": lambda s: False, "__hash__": lambda s: 0, "__abs__": lambda s: 0.0,
          "__add__": lambda s, o: 0.0, "__radd__": lambda s, o: 0.0,
          "__sub__": lambda s, o: 0.0, "__rsub__": lambda s, o: 0.0,
          "__mul__": lambda s, o: 0.0, "__rmul__": lambda s, o: 0.0,
          "__truediv__": lambda s, o: 0.0, "__rtruediv__": lambda s, o: 0.0,
          "__neg__": lambda s: 0.0, "__pos__": lambda s: 0.0}
    return type(f"Liar_{base.__name__}", (base,), ns)(value)


def _liars_in(obj):
    """`obj` with every int/float replaced by a liar storing it (recursively through list/tuple)."""
    if isinstance(obj, bool):
        return obj                      # `bool` cannot be subclassed; mask entries stay strict bools
    if isinstance(obj, (int, float)):
        return _liar(obj)
    if isinstance(obj, (list, tuple)):
        return type(obj)(_liars_in(v) for v in obj)
    return obj


def _outcome(call):
    """('returned', value) or ('raised', ExceptionType) -- a comparable outcome."""
    try:
        return ("returned", call())
    except BaseException as e:            # noqa: BLE001 - an ESCAPE is exactly what must be compared
        return ("raised", type(e))


_F_QUAD = lambda p: p[0] ** 2 + 3.0 * p[1]
_G_QUAD = lambda p: [2.0 * p[0], 3.0]
_F_FLAT = lambda p: 1.0
_G_ZERO = lambda p: [0.0, 0.0]

# Each case sits ON a guard, so a bypass changes the OUTCOME and not merely a digit. (args, kwargs, why)
_CASES = {
    "check_finite_scalar": [((2.5,), {}, "returns the validated float")],
    "check_finite_sequence": [(([1.0, 2.5],), {}, "returns a tuple of floats")],
    "check_finite_matrix": [(([[1.0, 2.5], [3.0, 4.0]],), {}, "returns a tuple of tuples")],
    "check_mask": [(([True, False], 3), {}, "MaskLengthError: len 2 != 3 (N2)"),
                   (([True, False], 2), {}, "returns the mask")],
    "masked_mean_checked": [(([[1.0, 3.0], [9.0, 9.0]], [True, False], 1), {},
                             "F1: NormalizationMismatchError, off by the row width"),
                            (([[1.0, 3.0], [9.0, 9.0]], [True, False], 2), {}, "returns 2.0")],
    "masked_squared_error_mean": [(([1e-200, 2.0], [0.0, 1.0], [True, True], 2), {},
                                   "F2: UnderflowError, a nonzero input that squared to 0.0"),
                                  (([[1.0, 1.0], [0.0, 0.0]], [[0.0, 0.0], [0.0, 0.0]], [True, False], 1), {},
                                   "F1 through the public MSE wrapper: the per_mask_entry divisor")],
    "check_gradient": [((_F_FLAT, _G_ZERO, [1.0, 2.0]), {"zero_tol": 0.0},
                        "F3: DegenerateGradientError for an identically-zero analytic gradient"),
                       ((_F_QUAD, _G_QUAD, [1.0, 2.0]),
                        {"step": 1e-6, "rtol": 1e-4, "atol": 1e-6, "zero_tol": 0.0},
                        "F4: a PASS report; `2.0 * step` must not consult step.__rmul__"),
                       ((_F_QUAD, lambda p: [99.0, 3.0], [1.0, 2.0]), {"rtol": 1e-4, "atol": 1e-6},
                        "GradientMismatchError: atol/rtol decide it")],
    "require_parameter_gradient": [(([0.0, 0.0],), {}, "DegenerateGradientError"),
                                   (([2.0, 0.0],), {}, "returns the gradient")],
    "check_params_changed": [(([1.0, 2.0], [1.0, 2.0]), {"min_abs_change": 0.0}, "NoOpUpdateError"),
                             (([1.0, 2.0], [1.0, 2.5]), {"min_abs_change": 0.1}, "returns 0.5")],
}

# Parameters the sweep does NOT wrap, each with the reason it cannot be a lying number. A parameter
# absent from both this table and the bound arguments of `_CASES` FAILS the derived test below.
_NOT_A_LYING_NUMBER = {
    ("check_finite_scalar", "name"): "a str label in a message, not a number",
    ("check_finite_sequence", "name"): "a str label in a message, not a number",
    ("check_finite_matrix", "name"): "a str label in a message, not a number",
    ("check_mask", "name"): "a str label in a message, not a number",
    ("masked_mean_checked", "name"): "a str label in a message, not a number",
    ("masked_mean_checked", "strict_masked_out"): "a bool policy flag; bool cannot be subclassed",
    ("masked_squared_error_mean", "strict_masked_out"): "a bool policy flag; bool cannot be subclassed",
    ("check_gradient", "fn"): "a caller-supplied callable, which opens THREE routes, and this row "
                              "excuses exactly TWO of them: its RETURN value is normalised where it "
                              "is consumed (check_finite_scalar), and the CALL itself is the "
                              "documented unwrapped-propagation carve-out. Its SIDE EFFECT on the "
                              "list this module hands it is NOT excused here -- it is swept by "
                              "TheFifthAxisIsACallablePlacedOperand (test_h1/test_h2/test_h3), "
                              "because the reason this row used to give named the return value and "
                              "the callable and READ as though it covered all three, which is how "
                              "1785 derived refusals never reached the one operand `_same` inspects",
    ("check_gradient", "grad_fn"): "the same three routes as fn and the same two excused: the CALL "
                                   "and the RETURN value, whose lazy half is additionally covered by "
                                   "TheCarveOutWhereItsHalvesMeet. Its SIDE EFFECT on the list this "
                                   "module hands it is NOT excused here and is swept by test_h1",
    ("require_parameter_gradient", "name"): "a str label in a message, not a number",
    ("require_parameter_gradient", "input_grad"): "accepted only to phrase a message and documented as "
                                                  "never evidence; it decides nothing",
    ("check_params_changed", "name"): "a str label in a message, not a number",
}


# --------------------------------------------------------------------------- FINDING H
# THE FIFTH AXIS: an operand a caller's CALLABLE PLACED, as against one a caller PASSED.
#
# Four axes were closed in earlier rounds, all of them about a value the caller hands over as an
# ARGUMENT: its comparison and arithmetic dunders (`_plain_real` at every guard, swept by `_liar`),
# the iterator protocol (`_materialised`), the conversion protocols (`_as_float`, `_shown`,
# `_type_name`, `_distinct_values`' fallback), and the carve-out where a callable's RETURN VALUE is
# itself a data argument. The fifth is none of those. `check_gradient` hands its callables a LIST
# THIS MODULE BUILT, and `_same` then compares each slot of that list against this module's
# snapshot -- so the left operand of that bare `==` is whatever `fn` or `grad_fn` WROTE THERE.
#
# WHY NO DERIVED SWEEP REACHED IT -- the finding, not a footnote. `_NOT_A_LYING_NUMBER` excuses
# ("check_gradient", "fn") and ("check_gradient", "grad_fn"), and `test_c1`,
# `test_a_liar_that_converts_honestly_cannot_change_an_outcome` and
# `test_the_same_sweep_through_a_one_shot_iterable` all `continue` on that table. The reason the
# table gave covered the callable's RETURN VALUE and the CALL ITSELF: two of the three routes a
# callable parameter opens. The third is its SIDE EFFECT on the argument, which is the one thing
# `_same` inspects. A REASON THAT COVERS TWO ROUTES OF THREE READS LIKE A REASON THAT COVERS THE
# POSITION, and that is what kept 1785 swept refusals away from this operand while all three
# suites stayed green on both interpreters. The reason text is as much of the fix as `_same` is,
# which is why it is narrowed in the table above and names the sweep below.
#
# Third time in SR-06 that an avoidance-with-a-reason hid a real defect (`_liar`'s `__float__` note
# was the second), and CLAUDE.md's rule-9 smell in its documented form: the reason held for the
# shapes the fixture used and the range was unswept.
_CMP_BASES = ((object, "plain object"), (Real, "numbers.Real subclass"), (Fraction, "Fraction subclass"),
              (float, "float subclass"), (int, "int subclass"))
_CMP_SHAPES = ("raises from __eq__", "raises from __ne__", "lies: __eq__ -> True")


def _cmp_hostile(base, shape):
    """A `base` instance storing 99 whose EQUALITY protocol is hostile in one of three ways.

    The BASE is the whole point. `_plain_real` normalises `bool`/`int`/`float` and is the IDENTITY on
    everything else -- measured, `_plain_real(o) is o` for a plain object, a `numbers.Real` subclass
    and a `Fraction` subclass -- so only the last two rows of `_CMP_BASES` are the shapes the older
    fixture (`type("EqBoom", (float,), ...)`) could express, and those two were the 15 in-family
    cells of the 30.
    """
    boom = lambda s, o: (_ for _ in ()).throw(RuntimeError("comparison boom"))
    ns = {"__hash__": lambda s: 0}
    if shape == "raises from __eq__":
        ns["__eq__"] = boom
    elif shape == "raises from __ne__":
        ns["__eq__"] = lambda s, o: False
        ns["__ne__"] = boom
    else:
        ns["__eq__"] = lambda s, o: True
    if base is Real:
        return type("RealCmpHostile", (Real,),
                    dict(_REAL_STUBS, __float__=lambda s: 99.0, **ns))()
    if base is object:
        return type("ObjectCmpHostile", (), ns)()
    if base is Fraction:
        return type("FractionCmpHostile", (Fraction,), dict(ns, __hash__=Fraction.__hash__))(99)
    return type(base.__name__.capitalize() + "CmpHostile", (base,),
                dict(ns, __hash__=base.__hash__))(99)


def _writer(position, obj):
    """`(fn, grad_fn)` for `check_gradient` in which `position` WRITES `obj` into the list it is
    handed. Both callables are otherwise honest: `_F_QUAD`/`_G_QUAD` at [1.0, 2.0] agree, so a PASS
    report is what the module produces if the write goes unnoticed."""
    def write(p):
        p[0] = obj
    if position == "grad_fn":
        return _F_QUAD, (lambda p: (write(p), [2.0, 3.0])[1])
    return (lambda p: (write(p), 1.0)[1]), _G_QUAD


# The positions a caller's CALLABLE occupies, DERIVED from `_CASES` below (any bound argument that is
# callable), with the three routes each one opens written out. A new callable parameter on a public
# function fails `test_h3` until it has a row here.
_CALLABLE_PLACED = {
    ("check_gradient", "fn"): "called with a fresh `list(q)`; routes are (1) the call, carved out and "
                              "propagated unwrapped, (2) the returned scalar, normalised by "
                              "check_finite_scalar, (3) the SIDE EFFECT on that list, decided by _same",
    ("check_gradient", "grad_fn"): "called with a fresh `list(p0)`; the same three routes -- the "
                                   "call, the returned sequence, and the SIDE EFFECT on that list "
                                   "decided by _same -- with route (2) additionally covered lazily "
                                   "by TheCarveOutWhereItsHalvesMeet",
}


# FINDING A. Public names of `toy.stability` that carry NO guard, each with the reason it cannot.
# A public name absent from BOTH this table and `_CASES` fails the derived test below. That is the
# point of the table: the enumeration used to be `inspect.isfunction`, which silently dropped
# three shapes of addition, and a filter that drops things silently is replaced here by one that
# admits everything the module defines and makes each exclusion say why in writing.
_NOT_A_GUARD = {
    "StabilityError": "the base exception class: it does not carry a guard, it IS the family",
    "NonNumericError": "an exception class RAISED BY a guard, not a guard",
    "NonFiniteError": "an exception class raised by a guard",
    "ShapeError": "an exception class raised by a guard",
    "MaskTypeError": "an exception class raised by a guard",
    "MaskLengthError": "an exception class raised by a guard",
    "EmptyMaskError": "an exception class raised by a guard",
    "NormalizationMismatchError": "an exception class raised by a guard",
    "GradientMismatchError": "an exception class raised by a guard",
    "DegenerateGradientError": "an exception class raised by a guard",
    "MissingGradientError": "an exception class raised by a guard",
    "UnderflowError": "an exception class raised by a guard",
    "NoOpUpdateError": "an exception class raised by a guard",
    "GradientCheckReport": "the frozen dataclass check_gradient RETURNS on success; a record "
                           "built from values its guards already validated, not a guard itself",
}


def _definition_modules(o):
    """Every module name on `o`'s unwrap chain.

    `functools.partial` has NO `__module__` at all, so the usual `o.__module__ == st.__name__`
    filter drops a partial alias silently -- one of the three shapes measured bypassing the
    enumeration. Accepting when ANY link names the module handles the partial, the `lru_cache`
    wrapper (whose `__wrapped__` is the real function) and a `staticmethod` object. Taking only
    the LAST link instead was measured to move a decorated function OUT of the module whenever
    the decorator came from elsewhere, which is the same failure in the other direction.
    """
    out, seen = set(), set()
    while True:
        out.add(getattr(o, "__module__", None))
        if id(o) in seen:
            break
        seen.add(id(o))
        if isinstance(o, functools.partial):
            o = o.func
        elif isinstance(o, (staticmethod, classmethod)):
            o = o.__func__
        elif getattr(o, "__wrapped__", None) is not None:
            o = o.__wrapped__
        elif getattr(o, "__func__", None) is not None:
            o = o.__func__
        else:
            break
    return out


class NormalisationIsDerivedNotEnumerated(unittest.TestCase):
    """The fail-closed half of the per-site fix for F1-F4.

    A per-site fix is only as good as what makes the NEXT un-normalised site fail. These tests derive
    the subject list from `inspect` -- the public functions of `toy.stability` and the parameters of
    their signatures -- so a new public function, or a new parameter on an old one, fails here until it
    is swept; and the invariant swept is the one the module docstring now claims."""

    def _public(self, ns=None, modname=None):
        """Every public name the module DEFINES: plain function, decorated function, callable
        wrapper, partial alias, class or record alike.

        FINDING A. This was `inspect.isfunction`, which is shaped like exactly the thing it has to
        catch. Measured, each addition carrying a live F1-shaped defect -- a bare
        `if denominator != len(items)` on the caller's object:

            plain `def`                     seen (9 -> 10)  test_stability FAILED f=1  fails closed
            identity-decorated `def`        seen (10)       test_stability FAILED f=1  fails closed
            `@functools.lru_cache(None)`    NOT seen (9)    Ran 72 OK                  BYPASSED
            `functools.partial(...)` alias  NOT seen (9)    Ran 72 OK                  BYPASSED
            public class + @staticmethod    NOT seen (9)    Ran 72 OK                  BYPASSED
            new parameter on an old one     --              test_stability FAILED f=1  fails closed
            stale exemption row             --              test_stability FAILED f=1  fails closed

        In each BYPASSED case the injected defect was live: an honest divisor gave 2.0 and
        `EqInt(1)` gave 4.0 where a NormalizationMismatchError is required. A miss is SILENT
        rather than loud because the assertion below is a set EQUALITY -- a name invisible here is
        also absent from `_CASES`, so the equality holds. Triggers 2 and 3 only range over names
        already in `_CASES`, so trigger 1 ("add a public function") is the responsible one, and
        `inspect.isfunction` is precisely what defeats it.

        So membership is by DEFINITION, not by TYPE: everything public that this module defines is
        in, and `_NOT_A_GUARD` is where a non-guard is excused in writing. `callable(o) and not
        inspect.isclass(o)` would catch the `lru_cache` wrapper and the partial but still miss the
        public class, so classes are admitted too and excused by name.

        SCOPE, kept honest: this changes nothing about `stability.py`'s behaviour at HEAD. All
        nine public guard functions ARE plain functions and the sweep covered all nine before.
        This is a finding against the fail-closed MECHANISM, not against the numerics.
        """
        ns = vars(st) if ns is None else ns
        modname = st.__name__ if modname is None else modname
        return {n for n, o in ns.items()
                if not n.startswith("_") and not inspect.ismodule(o)
                and modname in _definition_modules(o)}

    def test_every_public_function_and_parameter_is_swept_or_exempt(self):
        public = self._public()
        self.assertEqual(public - set(_NOT_A_GUARD), set(_CASES),
                         "a public name of toy.stability was added or removed: give it a row in "
                         "_CASES so the normalisation sweep covers it, or a reason in _NOT_A_GUARD")
        self.assertEqual(len(public - set(_NOT_A_GUARD)), 9,
                         "the widened enumeration must still yield exactly the nine guard "
                         "functions at HEAD")
        self.assertEqual(len(public), 23, "23 public names at HEAD: the 9 guards, the 13 exception "
                                          "classes and GradientCheckReport")
        for n in _NOT_A_GUARD:                       # a stale exemption is a stale reason
            self.assertIn(n, public, f"_NOT_A_GUARD excuses {n}, which toy.stability no longer "
                                     "defines as a public name")
        for name in sorted(_CASES):
            fn, sig = getattr(st, name), inspect.signature(getattr(st, name))
            bound = set()
            for args, kwargs, _why in _CASES[name]:
                b = sig.bind(*args, **kwargs)
                bound |= set(b.arguments)
            for pname in sig.parameters:
                with self.subTest(function=name, parameter=pname):
                    self.assertTrue(pname in bound or (name, pname) in _NOT_A_LYING_NUMBER,
                                    f"{name}({pname}=...) is neither swept by _CASES nor listed in "
                                    "_NOT_A_LYING_NUMBER with a reason: a parameter that no test passes "
                                    "a lying number to is exactly the next F1")
        for (fname, pname) in _NOT_A_LYING_NUMBER:      # a stale exemption is a stale reason
            self.assertIn(fname, _CASES)
            self.assertIn(pname, inspect.signature(getattr(st, fname)).parameters,
                          f"_NOT_A_LYING_NUMBER names {fname}({pname}), which no longer exists")

    def test_a1_the_enumeration_sees_the_shapes_inspect_isfunction_missed(self):
        """FINDING A's fail-closed claim, pinned. This class's docstring says "a new public
        function, or a new parameter on an old one, fails here until it is swept" -- measurably
        FALSE for three shapes before this test existed, and itself unpinned, so CLAUDE.md's "pin
        each load-bearing sentence with a test whose doc-only mutant dies" was unmet for it.

        This test DIES if the enumeration narrows back to `inspect.isfunction`, and it dies if it
        narrows to a bare `o.__module__ == st.__name__` filter, which drops the partial.
        """
        mod = types.ModuleType(st.__name__)
        src = ("import functools, dataclasses\n"
               "def _impl(values, denominator): return 0.0\n"
               "def plain_guard(values, denominator): return 0.0\n"
               "@(lambda f: f)\n"
               "def decorated_guard(values, denominator): return 0.0\n"
               "@functools.lru_cache(maxsize=None)\n"
               "def cached_guard(values, denominator): return 0.0\n"
               "partial_guard = functools.partial(_impl)\n"
               "class GuardHolder:\n"
               "    @staticmethod\n"
               "    def check_new_mean(values, denominator): return 0.0\n"
               "@dataclasses.dataclass(frozen=True)\n"
               "class NewRecord:\n"
               "    x: float = 0.0\n")
        exec(compile(src, f"<{st.__name__} addition shapes>", "exec"), mod.__dict__)
        seen = self._public(mod.__dict__, st.__name__)
        narrow = {n for n, o in mod.__dict__.items()
                  if inspect.isfunction(o) and not n.startswith("_")
                  and getattr(o, "__module__", None) == st.__name__}
        for shape in ("plain_guard", "decorated_guard", "cached_guard", "partial_guard",
                      "GuardHolder", "NewRecord"):
            with self.subTest(shape=shape):
                self.assertIn(shape, seen,
                              f"{shape} is invisible to _public(), so an addition of that shape "
                              "carries its defect past the whole sweep: the set equality in "
                              "test_every_public_function_and_parameter_is_swept_or_exempt holds "
                              "because the name is missing from BOTH sides")
        for bypassed in ("cached_guard", "partial_guard", "GuardHolder"):
            with self.subTest(previously_bypassing=bypassed):
                self.assertNotIn(bypassed, narrow, "this is the shape inspect.isfunction missed")
                self.assertIn(bypassed, seen)
        self.assertEqual(seen & {"functools", "dataclasses", "_impl"}, set(),
                         "the module filter must still exclude imports and private names")

    def test_a_liar_that_converts_honestly_cannot_change_an_outcome(self):
        """F1-F4 in one assertion, one argument position at a time: wrap exactly one bound parameter's
        numbers in objects that lie through every comparison and arithmetic dunder, and require the
        outcome -- the value returned, or the exception type raised -- to be the honest one."""
        for name in sorted(_CASES):
            fn = getattr(st, name)
            sig = inspect.signature(fn)
            for args, kwargs, why in _CASES[name]:
                honest = _outcome(lambda: fn(*args, **kwargs))
                self.assertIn(honest[0], ("returned", "raised"))
                if honest[0] == "raised":
                    self.assertTrue(issubclass(honest[1], st.StabilityError),
                                    f"{name}: honest case {why!r} raised {honest[1].__name__}, outside "
                                    "StabilityError; the case is not sitting on a guard")
                for pname in sig.bind(*args, **kwargs).arguments:
                    if (name, pname) in _NOT_A_LYING_NUMBER:
                        continue
                    b = sig.bind(*args, **kwargs)
                    b.arguments[pname] = _liars_in(b.arguments[pname])
                    with self.subTest(function=name, parameter=pname, case=why):
                        got = _outcome(lambda: fn(*b.args, **b.kwargs))
                        self.assertEqual(got, honest, f"{name}({pname}=<liar>) diverged: {why}")

    def test_the_same_sweep_through_a_one_shot_iterable(self):
        """The element positions again, with every top-level sequence handed over as a generator.

        This is the measurement that decided the structure of this fix. A parameter-boundary wrapper of
        the kind `toy.robustness` installs collapses `list`/`tuple`/`Mapping` arguments, so it closes
        F2 for `[EqFloat(1e-200)]` and leaves it OPEN for `iter([EqFloat(1e-200)])` -- measured 0.0,
        against the UnderflowError the honest input raises -- while this module documents one-shot
        iterables as supported input. Normalising at the site reaches both; a wrapper does not.

        `map()` is swept alongside `iter()`. It is a one-shot iterable that no test covered, and
        `_plain_real(map(...))` is identity exactly as it is for `iter()` and for a genexp, so
        HEAD's per-site treatment has to reach it too. Measured: it does -- `list`, `iter([...])`,
        a generator expression and `map()` all refuse F2 with UnderflowError."""
        for name in sorted(_CASES):
            fn, sig = getattr(st, name), inspect.signature(getattr(st, name))
            for args, kwargs, why in _CASES[name]:
                b0 = sig.bind(*args, **kwargs)
                honest = _outcome(lambda: fn(*b0.args, **b0.kwargs))
                for pname, given in list(b0.arguments.items()):
                    if (name, pname) in _NOT_A_LYING_NUMBER or not isinstance(given, (list, tuple)):
                        continue
                    for route, wrap in (("iter", iter), ("map", lambda v: map(lambda x: x, v))):
                        b = sig.bind(*args, **kwargs)
                        b.arguments[pname] = wrap(_liars_in(given))
                        with self.subTest(function=name, parameter=pname, case=why, route=route):
                            got = _outcome(lambda: fn(*b.args, **b.kwargs))
                            self.assertEqual(got, honest,
                                             f"{name}({pname}={route}(<liars>)) diverged: {why}")


class ReAttestationRegressions(unittest.TestCase):
    """F1-F4 pinned as themselves, with the exact objects the SR-06 re-attestation measured."""

    @staticmethod
    def _eq_int(v):
        return type("EqInt", (int,), {"__eq__": lambda s, o: True, "__ne__": lambda s, o: False,
                                      "__hash__": lambda s: 0})(v)

    @staticmethod
    def _eq_float(v):
        return type("EqFloat", (float,), {"__eq__": lambda s, o: True, "__ne__": lambda s, o: False,
                                          "__hash__": lambda s: 0})(v)

    def test_f1_lying_denominator_cannot_pass_the_normalization_check(self):
        m = [[1.0, 3.0], [9.0, 9.0]]
        self.assertEqual(st.masked_mean_checked(m, [True, False], 2), 2.0)      # honest divisor
        for d in (self._eq_int(1), self._eq_int(8),
                  type("IntLie", (int,), {"__int__": lambda s: 2})(1)):         # `int()` would consult this
            with self.subTest(d=type(d).__name__):
                with self.assertRaises(st.NormalizationMismatchError):
                    st.masked_mean_checked(m, [True, False], d)
        # and through the public MSE wrapper, with the divisor toy.teacher_student explicitly rejects
        with self.assertRaises(st.NormalizationMismatchError):
            st.masked_squared_error_mean([[1.0, 1.0], [0.0, 0.0]], [[0.0, 0.0], [0.0, 0.0]],
                                         [True, False], self._eq_int(1))

    def test_f2_lying_equality_cannot_buy_a_silent_zero(self):
        from fractions import Fraction
        for pred, targ in ((self._eq_float(1e-200), 0.0), (1e-200, self._eq_float(0.0))):
            with self.subTest(pred=repr(pred)):
                with self.assertRaises(st.UnderflowError):
                    st.masked_squared_error_mean([pred], [targ], [True], 1)
                with self.assertRaises(st.UnderflowError):      # and through a one-shot iterable
                    st.masked_squared_error_mean(iter([pred]), iter([targ]), iter([True]), 1)
        # the property the obvious float() fix loses, kept: an exact tiny Fraction is still refused
        with self.assertRaises(st.UnderflowError):
            st.masked_squared_error_mean([Fraction(1, 10 ** 400)], [0.0], [True], 1)
        # a Real with no exact rational reading stays INSIDE the error family (no escaping TypeError).
        # This used to re-import numpy locally as `_np`, which made its guard invisible to the
        # assertion that counts the numpy guards in this file; the module-level `np` was already here.
        if np is not None:
            self.assertAlmostEqual(st.masked_squared_error_mean([np.float32(1e-40)], [np.float32(0.0)],
                                                               [True], 1), 1e-80, delta=1e-81)
        self.assertEqual(st.masked_squared_error_mean([1e-200], [1e-200], [True], 1), 0.0)   # equal: fine
        # FINDING B (round-13 re-attestation): `Fraction(x)` for a float instance reads
        # `x.as_integer_ratio()`, so that is a THIRD channel into this guard -- neither a comparison
        # dunder nor a conversion dunder, which is why the derived sweep's `_liar` cannot express it
        # (it leaves the conversion protocol honest by design). `_plain_real` is what closes it, and
        # without this subTest the mutant `Fraction(a) != Fraction(b)` was UNKILLED by all three
        # suites while silently reopening F2.
        class _AirLiar(float):
            def as_integer_ratio(self):
                return (0, 1)
            __hash__ = float.__hash__

        for pred, targ in ((_AirLiar(1e-200), 0.0), (1e-200, _AirLiar(0.0))):
            with self.subTest(air=repr(pred)):
                with self.assertRaises(st.UnderflowError):
                    st.masked_squared_error_mean([pred], [targ], [True], 1)
                with self.assertRaises(st.UnderflowError):
                    st.masked_squared_error_mean(iter([pred]), iter([targ]), iter([True]), 1)


    def test_f3_no_pass_report_for_a_zero_gradient_whatever_zero_tol_is(self):
        """A PASS certificate for a severed gradient path is the most consequential of the four."""
        liars = [type("GeFalse", (float,), {"__ge__": lambda s, o: False, "__hash__": float.__hash__})(0.0),
                 type("GeFalseGtTrue", (float,), {"__ge__": lambda s, o: False, "__gt__": lambda s, o: True,
                                                  "__hash__": float.__hash__})(0.0),
                 _liar(0.0)]
        for zt in [0.0] + liars:
            for g in (lambda p: [0.0, 0.0], lambda p: [-0.0, 0.0], lambda p: [0.0, -0.0]):
                with self.subTest(zero_tol=type(zt).__name__):
                    with self.assertRaises(st.DegenerateGradientError):
                        st.check_gradient(lambda p: 1.0, g, [1.0, 2.0], zero_tol=zt)

    def test_f4_lying_step_arithmetic_stays_in_family(self):
        honest = st.check_gradient(_F_QUAD, _G_QUAD, [1.0, 2.0], step=1e-6)
        for ns in ({"__rmul__": lambda s, o: 0.0}, {"__rmul__": lambda s, o: NAN},
                   {"__radd__": lambda s, o: o}, {"__mul__": lambda s, o: 0.0}):
            step = type("StepLiar", (float,), dict(ns, __hash__=float.__hash__))(1e-6)
            with self.subTest(dunder=sorted(ns)[0]):
                # NOTE F: this was `except st.StabilityError: continue`. Instrumented at HEAD,
                # all 4/4 `StepLiar` variants RETURN a report, so `continue` was taken 0/4 times:
                # the branch was unreachable, and a future regression that made `check_gradient`
                # REFUSE these inputs would have made this test pass silently. A tolerant
                # `except ... continue` is how a test survives its own subject being fixed, and is
                # the exact shape that produced a vacuous test here last round. No dunder in this
                # list is expected to refuse, so the refusal is ASSERTED AGAINST rather than
                # tolerated; a change that makes one refuse has to come here and say so.
                try:
                    report = st.check_gradient(_F_QUAD, _G_QUAD, [1.0, 2.0], step=step)
                except st.StabilityError as e:
                    self.fail(f"check_gradient REFUSED step with {sorted(ns)[0]} "
                              f"({type(e).__name__}: {e}). At HEAD all four variants return the "
                              "honest report; a refusal is a behaviour change to be re-pinned, "
                              "not absorbed by this test")
                except Exception as e:            # ZeroDivisionError escaped both StabilityError and
                    self.fail(f"{type(e).__name__} escaped the documented family: {e}")  # ValueError
                self.assertEqual(report, honest)
        self.assertIs(type(honest.step), float)   # the report carries plain floats, not the caller's object
        self.assertIs(type(honest.rtol), float)
        self.assertIs(type(honest.atol), float)

    def test_a_callable_cannot_hide_its_mutation_behind_a_lying_eq(self):
        """`_same` compares the post-call list against this module's snapshot, so the caller's object is
        the LEFT operand of a bare `==` and answers for itself unless it is normalised first."""
        def swap(p):
            p[0] = self._eq_float(99.0)      # a different value, claiming equality to anything
            return 1.0
        with self.assertRaisesRegex(st.StabilityError, "mutated its input"):
            st.check_gradient(swap, _G_QUAD, [1.0, 2.0])
        with self.assertRaisesRegex(st.StabilityError, "mutated its input"):
            st.check_gradient(_F_QUAD, lambda p: (swap(p), [2.0, 3.0])[1], [1.0, 2.0])
        # an honest float subclass storing the SAME value is not a mutation
        st.check_gradient(lambda p: (p.__setitem__(0, self._eq_float(p[0])), _F_QUAD(p))[1],
                          _G_QUAD, [1.0, 2.0])

    def test_f5_a_config_scalar_is_validated_on_the_value_it_stores(self):
        """F5, found while verifying the F3/F4 fix: a `float` subclass that STORES nan while its
        `__float__` answers innocuously. The re-attestation's adversaries lied through `__float__`
        AWAY from a finite stored value, so this direction was unswept -- and it is the worst of the
        five: measured on HEAD, `rtol` and `atol` built this way PASSED a wrong analytic gradient
        (analytic=(99.0, 3.0) against a true (2.0, 3.0)), and `zero_tol` built this way returned a
        PASS report for an identically-zero gradient. Reading the STORED value before validating is
        what closes all of them at once: `float(v)` in `_plain_real` would not."""
        def nan_behind(answer):
            return type("NanFloat", (float,), {"__float__": lambda s: answer,
                                               "__hash__": float.__hash__})(NAN)
        for kw, answer in (("step", 1e-6), ("rtol", 1e-4), ("atol", 1e-6), ("zero_tol", 0.0)):
            with self.subTest(parameter=kw):
                with self.assertRaisesRegex(st.NonFiniteError, f"{kw} is non-finite"):
                    st.check_gradient(_F_QUAD, lambda p: [99.0, 3.0], [1.0, 2.0],
                                      **{kw: nan_behind(answer)})
                with self.assertRaisesRegex(st.NonFiniteError, f"{kw} is non-finite"):
                    st.check_gradient(lambda p: 1.0, _G_ZERO, [1.0, 2.0], **{kw: nan_behind(answer)})
        with self.assertRaisesRegex(st.NonFiniteError, "min_abs_change is non-finite"):
            st.check_params_changed([1.0, 2.0], [1.0, 2.0], min_abs_change=nan_behind(0.0))
        # a zero STORED behind a positive-looking __float__ is refused as the zero it is
        with self.assertRaisesRegex(st.StabilityError, "step must be > 0"):
            st.check_gradient(_F_QUAD, _G_QUAD, [1.0, 2.0],
                              step=type("ZeroFloat", (float,), {"__float__": lambda s: 1e-6,
                                                                "__hash__": float.__hash__})(0.0))

    def test_n1_a_broken_iter_on_a_mask_stays_in_family(self):
        """`check_mask`'s `tuple(mask)` was bare while the sibling `_as_flat_items` wrapped the identical
        call, so a broken `__iter__` escaped as TypeError from one and ShapeError from the other.

        FINDING C -- N1's own defect, found and pinned on the OUTER object and left unfinished on
        the ROW. The policy sentence above is what this test writes down, and the row path violated
        it: a THIRD `tuple()`-on-caller-input site, `_as_rows`' per-ROW `tuple(r)`, was never
        wrapped while both siblings were. Measured on HEAD, 3.12.4 and 3.13.5 alike: each of the
        four shapes below escaped as a bare `TypeError` from the ROW position of
        `check_finite_matrix`, of `masked_mean_checked`, and of BOTH argument positions of
        `masked_squared_error_mean` -- 16 reproductions on documented input, with all three
        permitted suites reporting 72 / 181 / 48 OK both before and after the fix. "Fail safely"
        is SR-06's literal acceptance phrase, so this blocked.

        The row positions are swept here, across all four shapes, including the
        instance-attribute `__iter__` that needs no `object.__setattr__`.
        """
        for label, make in _BROKEN_ITER:
            with self.subTest(shape=label):
                with self.assertRaises(st.MaskTypeError):
                    st.check_mask(make(), 2)
                with self.assertRaises(st.ShapeError):          # the sibling OUTER site
                    st.check_finite_sequence(make())
                with self.assertRaises(st.StabilityError):      # and through the loss route
                    st.masked_mean_checked([1.0, 2.0], make(), 2)
                # ---- the ROW position: four escapes per shape before the fix
                with self.assertRaises(st.ShapeError):
                    st.check_finite_matrix([make()])
                with self.assertRaises(st.ShapeError):
                    st.masked_mean_checked([make(), (3.0, 4.0)], [True, True], 4)
                with self.assertRaises(st.ShapeError):
                    st.masked_squared_error_mean([make()], [(0.0, 0.0)], [True], 2)
                with self.assertRaises(st.ShapeError):
                    st.masked_squared_error_mean([(0.0, 0.0)], [make()], [True], 2)

    def test_n2_expected_len_is_an_int_element_count(self):
        with self.assertRaises(st.MaskLengthError):
            st.check_mask([True, False], self._eq_int(3))
        for bad in (2.0, "2", type("D", (), {"__index__": lambda s: 2})()):
            with self.subTest(bad=repr(bad)):
                with self.assertRaises(st.MaskLengthError):
                    st.check_mask([True, False], bad)
        self.assertEqual(st.check_mask([True, False], 2), (True, False))

    def test_n3_the_value_summed_is_the_value_validated(self):
        """`float(v)` ran twice per masked-in element, so a stateful `__float__` was validated on one
        answer and summed on another -- fail-closed only via the result-level finiteness backstop."""
        calls = []

        class Stateful(float):
            def __float__(self):
                calls.append(len(calls))
                return [2.5, 1e308][min(len(calls) - 1, 1)]

        self.assertEqual(st.masked_mean_checked([Stateful(2.5)], [True], 1), 2.5)
        self.assertEqual(len(calls), 1, "one float() per masked-in element")
        with self.assertRaises(st.NonFiniteError):          # the backstop itself is untouched
            st.masked_mean_checked([1e308, 1e308], [True, True], 2)


class TheFifthAxisIsACallablePlacedOperand(unittest.TestCase):
    """FINDING H, closed as a CLASS: the operand of a bare guard that a caller's CALLABLE placed.

    `check_gradient.call()` hands `fn`/`grad_fn` a list THIS MODULE built and then asks `_same(a, b)`
    whether each slot still holds the snapshot value. `a` is therefore the one left operand in this
    module that a caller's own callable fills, and `_plain_real` -- which normalises `bool`, `int` and
    `float` and is the IDENTITY on everything else, as its own docstring says three lines away -- was
    not on its own enough there.

    MEASURED AT THE COMMIT BEFORE THIS ONE, byte-identically on 3.12.4 and 3.13.5, over 5 operand
    bases x 3 comparison shapes x 2 callable positions = 30 cells:
    {OUT-OF-FAMILY 12, PASS-report-with-mutation-undetected 3, IN-FAMILY 15}. The 12 were a raising
    `__eq__`/`__ne__` on a plain object, a `numbers.Real` subclass or a `Fraction` subclass, at the
    `fn` AND the `grad_fn` position, coming out as a bare RuntimeError. The 3 were a LYING
    `__eq__ -> True` on those same bases via `grad_fn`: a GradientCheckReport, with the in-place
    mutation guard silent. The 15 in family were the `float` and `int` subclass bases -- which are
    exactly the shapes the suite's own fixture used, in `test_g2e`'s last block and in
    `test_a_callable_cannot_hide_its_mutation_behind_a_lying_eq`. The fixture's base was the whole
    difference between a pinned claim and a false one.

    FULLY PUBLIC TIER: no `object.__setattr__`, no metaclass. `grad_fn` is a positional public
    parameter and in-place mutation is a documented, tested shape.
    """

    def test_h1_every_callable_placed_operand_is_refused_in_family(self):
        """The 30 cells, all of them, with the two ways out counted at zero.

        The property is uniform now: whatever the base, whatever the comparison protocol, whichever
        callable did the writing, the answer is "<label> mutated its input in place" -- because
        `_same` decides on the plain number normalisation produced, or reports a write and does not
        ask the object anything. `escaped` and `returned` are pinned at zero because those are the
        only two ways out, and the 30 is pinned as a product so a shrunken factor fails here.
        """
        outcomes = {"in_family": 0, "escaped": 0, "returned": 0}
        for base, bname in _CMP_BASES:
            for shape in _CMP_SHAPES:
                for position in ("fn", "grad_fn"):
                    f, g = _writer(position, _cmp_hostile(base, shape))
                    with self.subTest(base=bname, shape=shape, position=position):
                        try:
                            out = st.check_gradient(f, g, [1.0, 2.0])
                        except st.StabilityError as e:
                            outcomes["in_family"] += 1
                            self.assertIn(f"{position} mutated its input in place", str(e))
                            continue
                        except BaseException as e:            # noqa: BLE001 - the escape is the subject
                            outcomes["escaped"] += 1
                            self.fail(f"{type(e).__name__} escaped the declared family from "
                                      f"check_gradient when {position} wrote a {bname} whose "
                                      f"comparison {shape}: {e}")
                            continue
                        outcomes["returned"] += 1
                        self.fail(f"check_gradient RETURNED {out!r} when {position} wrote a {bname} "
                                  f"that {shape}: an in-place mutation went undetected")
        self.assertEqual(outcomes, {"in_family": 30, "escaped": 0, "returned": 0})
        self.assertEqual(len(_CMP_BASES) * len(_CMP_SHAPES) * 2, 30, "5 bases x 3 shapes x 2 positions")
        self.assertEqual(len(_CMP_BASES), 5)
        self.assertEqual(len(_CMP_SHAPES), 3)
        # the identity half of the finding: `_plain_real` cannot normalise three of the five bases
        identity = {bname: st._plain_real(_cmp_hostile(base, "lies: __eq__ -> True"))
                    for base, bname in _CMP_BASES}
        self.assertEqual({k for k, v in identity.items() if type(v) in (float, int)},
                         {"float subclass", "int subclass"},
                         "_plain_real normalises only int/float: that is why the base decides")
        # and the figures this module quotes about those 30 cells are these 30 cells
        msrc = inspect.getsource(st)
        self.assertIn("5 operand bases x 3 comparison shapes x 2 callable positions = 30 cells", msrc)
        self.assertIn("12 bare RuntimeErrors escaped `check_gradient` and 3 were PASS", msrc)

    def test_h2_the_rule_is_a_plain_number_or_a_write_and_the_narrowing_is_stated(self):
        """What `_same` now does with each shape of write, INCLUDING the one behaviour change.

        The rule is statable in one line: anything `_plain_real` cannot reduce to exactly `int` or
        `float` is reported as a write, not asked. `type(...) is` and not `isinstance`, because
        `bool` is an `int` subclass that `_plain_real` deliberately does not collapse and
        `isinstance` would let `True` pass for the `1.0` it replaced -- measured before this fix: it
        did, and so did `Fraction(1, 1)`, at the `grad_fn` position, with a PASS report.

        THE NARROWING, stated rather than discovered later: a callable that swaps a coordinate for a
        value-EQUAL object of another type now gets "mutated its input in place" where it used to
        pass. That is right -- the snapshot is a plain `float` this module put there, so the slot HAS
        been written to -- and it is the price of not consulting the caller's `__eq__`. A plain `int`
        and a `float` subclass storing the same value still pass, because both normalise to a plain
        number and the comparison is then between two plain numbers. `numpy` splits along exactly
        that line and is asserted below: `float64` IS a `float` subclass and normalises; `float32`
        is not and is a write.
        """
        eq_float = type("EqFloatSame", (float,), {"__eq__": lambda s, o: True,
                                                  "__ne__": lambda s, o: False,
                                                  "__hash__": float.__hash__})
        rows = (("the same plain float", 1.0, False),
                ("a plain int of the same value", 1, False),
                ("a float subclass storing the same value", type("PlainSubFloat", (float,), {})(1.0), False),
                ("a float subclass with a lying __eq__, same value", eq_float(1.0), False),
                ("an int subclass with a lying __int__, same value",
                 type("IntLieSame", (int,), {"__int__": lambda s: 7})(1), False),
                ("a different plain float", 99.0, True),
                ("True for 1.0", True, True),
                ("Fraction(1, 1) for 1.0", Fraction(1, 1), True))
        for label, obj, is_write in rows:
            f, g = _writer("grad_fn", obj)
            with self.subTest(wrote=label):
                if is_write:
                    with self.assertRaisesRegex(st.StabilityError, "grad_fn mutated its input in place"):
                        st.check_gradient(f, g, [1.0, 2.0])
                else:
                    self.assertEqual(st.check_gradient(f, g, [1.0, 2.0]).analytic, (2.0, 3.0))
        if np is not None:                              # a plain `if`, never a skip
            f32, g32 = _writer("grad_fn", np.float32(1.0))
            with self.assertRaisesRegex(st.StabilityError, "grad_fn mutated its input in place"):
                st.check_gradient(f32, g32, [1.0, 2.0])
            self.assertTrue(isinstance(np.float64(1.0), float), "float64 is a float subclass")
            f64, g64 = _writer("grad_fn", np.float64(1.0))
            self.assertEqual(st.check_gradient(f64, g64, [1.0, 2.0]).analytic, (2.0, 3.0))
        # the unit, directly: the gate, and the reason it is `type(...) is` and not `isinstance`
        self.assertIs(st._same(1.0, 1.0), True)
        self.assertIs(st._same(1, 1.0), True)
        self.assertIs(st._same(eq_float(1.0), 1.0), True)
        for not_a_number in (True, Fraction(1, 1), _cmp_hostile(object, "lies: __eq__ -> True")):
            self.assertIs(st._same(not_a_number, 1.0), False)
        self.assertIs(st._same(2.0, 1.0), False)
        # the narrowing is written where a caller reads it
        doc = _doc(st._same)
        if doc is not None:
            self.assertIn("THE ONE BEHAVIOUR CHANGE", doc)

    def test_h3_the_class_is_derived_and_the_derivation_states_its_own_reach(self):
        """The fail-closed half, and -- the lesson `test_c4` paid for -- its REACH, stated exactly.

        WHAT THE DERIVED HALF DERIVES: the callable POSITIONS, from `_CASES` (every bound argument
        that is callable), so a new callable parameter on any public function fails here until it has
        a row in `_CALLABLE_PLACED` and a narrowed reason in `_NOT_A_LYING_NUMBER`.

        WHAT THE AST HALF MATCHES, exactly: inside `call()` -- the function that invokes a caller's
        callable -- every `ast.Compare` whose operands mention the handed-over list `arg` or the
        snapshot `snap` must have `len(...)` on BOTH sides. An element-level comparison spelled
        there directly is an offender; the only permitted element comparison is the `_same(a, b)`
        call. WHAT IT DOES NOT MATCH, and nothing here pretends otherwise: a comparison moved into a
        new helper that `call()` merely invokes, a `sorted()`/`set()`/`in` test on `arg`, a hash of
        its elements, or a callable position in some future function that does not pass its list
        through `call()`. Watched to FAIL, which is the only evidence that a derivation derives:
        `arg[0] != snap[0]` added beside the existing check is killed here, and a `_same` reverted to
        a bare `==` is killed by `test_h1`/`test_h2` (12 escapes and 3 PASS reports) and by this
        test's structural assertion, three ways.

        WHAT ACTUALLY PROTECTS THE PROPERTY IS BEHAVIOURAL, AND IT IS `test_h1`. The AST half's job
        is the narrower one of stopping the comparison from being RESPELLED by hand next to the one
        that is already there -- which is precisely how the row intake site came to be half-fixed,
        and how this operand came to be excused by a reason that fitted two routes of three.
        """
        import ast
        derived = set()
        for name in sorted(_CASES):
            sig = inspect.signature(getattr(st, name))
            for args, kwargs, _why in _CASES[name]:
                for pname, given in sig.bind(*args, **kwargs).arguments.items():
                    if callable(given) and not isinstance(given, type):
                        derived.add((name, pname))
        self.assertEqual(derived, set(_CALLABLE_PLACED),
                         "a public function takes a callable this class does not sweep: give it a "
                         "row in _CALLABLE_PLACED and narrow its _NOT_A_LYING_NUMBER reason, or the "
                         "side-effect route is unswept exactly as fn/grad_fn's was")
        for key, why in sorted(_CALLABLE_PLACED.items()):
            with self.subTest(position=key):
                self.assertIn("SIDE EFFECT", why.upper(), f"{key} does not name the third route")
                self.assertIn(key, _NOT_A_LYING_NUMBER)
                reason = _NOT_A_LYING_NUMBER[key]
                self.assertIn("side effect", reason.lower(),
                              "the exclusion reason must say what it does NOT cover: a reason that "
                              "covers two routes of three is how this survived")
                self.assertIn("test_h1", reason, "the reason must name the sweep that does cover it")
        # the AST half
        tree = ast.parse(inspect.getsource(st))
        calls = [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "call"]
        self.assertEqual(len(calls), 1, "call() is the function that invokes a caller's callable")
        offenders = []
        for node in ast.walk(calls[0]):
            if not isinstance(node, ast.Compare):
                continue
            operands = [node.left] + list(node.comparators)
            if not any(isinstance(x, ast.Name) and x.id in ("arg", "snap")
                       for o in operands for x in ast.walk(o)):
                continue
            if not all(isinstance(o, ast.Call) and isinstance(o.func, ast.Name)
                       and o.func.id == "len" for o in operands):
                offenders.append(ast.unparse(node))
        self.assertEqual(offenders, [],
                         "a value a caller's callable placed is compared bare inside call(): route "
                         "it through _same, which decides on the normalised value")
        self.assertIn("_same(a, b) for a, b in zip(arg, snap)", inspect.getsource(st.check_gradient))
        same_src = inspect.getsource(st._same)
        self.assertIn("type(a) is not float and type(a) is not int", same_src)
        self.assertNotIn("isinstance(a,", same_src,
                         "isinstance would admit bool, which _plain_real deliberately does not "
                         "collapse: True would pass for the 1.0 it replaced")


def _with_broken(obj, make):
    """Yield (where, variant): `make()` put in place of `obj` itself, of each ELEMENT of `obj`, and
    of each element of each element -- which is how the ROW position is reached without naming it."""
    yield ("the argument itself", make())
    if isinstance(obj, (list, tuple)):
        for i in range(len(obj)):
            v = list(obj)
            v[i] = make()
            yield (f"element [{i}]", type(obj)(v))
            if isinstance(obj[i], (list, tuple)):
                for j in range(len(obj[i])):
                    inner = list(obj[i])
                    inner[j] = make()
                    outer = list(obj)
                    outer[i] = type(obj[i])(inner)
                    yield (f"element [{i}][{j}]", type(obj)(outer))


class IntakeIsDerivedNotEnumerated(unittest.TestCase):
    """FINDING C, closed as a CLASS rather than as an instance.

    Three `tuple()`-on-caller-input sites existed and two were wrapped; the third -- `_as_rows`'
    per-ROW `tuple(r)` -- was not, so a bare `TypeError` escaped the declared
    `StabilityError < ValueError` family on documented input. Measured on HEAD, identically on
    3.12.4 and 3.13.5: 16 escapes, being 4 object shapes through the ROW position of
    `check_finite_matrix`, of `masked_mean_checked`, and of BOTH argument positions of
    `masked_squared_error_mean`. All three permitted suites reported 72 / 181 / 48 OK both before
    and after the fix, so a change in behaviour on 16 inputs was invisible to every test. These
    tests are what make that false.

    They do NOT enumerate the three sites. They DERIVE the subject list from `_CASES` the way the
    normalisation sweep does, and push a broken object into every bound argument position and into
    every element and sub-element of every sequence argument, so a FOURTH unguarded intake point
    fails here instead of waiting for an attester. Deriving the set is also what found the fourth
    site: see `test_c3_...`.
    """

    def test_c1_every_intake_position_keeps_its_failure_in_family(self):
        """The derived sweep. Every bound argument, every element, every sub-element, every shape --
        of the iterator protocol AND, since G2, of the conversion protocol.

        THE FIGURE IS PINNED, NOT FLOORED. This assertion used to read
        `assertGreater(swept, 400)` while the sweep performed 1260 in-family refusals over 105
        (case, parameter, position) triples: 3x slack, so a regression that silently dropped two
        thirds of the sweep passed. That is the `assertGreaterEqual(swept, 100)` defect which hid
        29 cases two rounds ago, reproduced in the test written to replace it.

        THE FLOOR'S BLINDNESS, PERFORMED rather than asserted, two ways, both measured against
        this file with only the floor restored:
          * `shapes` truncated to its first four entries: 420 refusals -- `assertGreater(swept,
            400)` reports OK, the figures below FAIL (`len(shapes)` 4 != 17).
          * the element and sub-element positions dropped while all 17 shapes are kept: 663
            refusals over 21 positions instead of 61 -- two thirds of the sweep gone, and again
            `assertGreater(swept, 400)` reports OK while the figures below FAIL.
        (The same instrumentation reproduces the figure the attester measured at HEAD: with
        HEAD's 12 shapes the sweep performs 1260 refusals over the same 105 triples.)

        So the exact product is pinned, the two failure counters are pinned at zero (that is the
        property), and the position and triple counts are pinned separately, because a regression
        can shrink either factor while keeping `swept == triples * shapes` true.
        """
        shapes = _BROKEN_ITER + _BROKEN_ITER_OTHER + _BROKEN_GETATTR + _BROKEN_FLOAT
        swept = returned = escaped = 0
        positions, triples = set(), set()
        for name in sorted(_CASES):
            fn, sig = getattr(st, name), inspect.signature(getattr(st, name))
            for ci, (args, kwargs, why) in enumerate(_CASES[name]):
                b0 = sig.bind(*args, **kwargs)
                for pname, given in list(b0.arguments.items()):
                    if (name, pname) in _NOT_A_LYING_NUMBER:
                        continue        # str labels, bool flags, and the two documented callables
                    for label, make in shapes:
                        for where, variant in _with_broken(given, make):
                            positions.add((name, pname, where))
                            triples.add((name, ci, pname, where))
                            b = sig.bind(*args, **kwargs)
                            b.arguments[pname] = variant
                            with self.subTest(function=name, parameter=pname, at=where, shape=label):
                                try:
                                    out = fn(*b.args, **b.kwargs)
                                except st.StabilityError:
                                    swept += 1
                                    continue
                                except BaseException as e:
                                    escaped += 1
                                    self.fail(f"{type(e).__name__} escaped the declared family "
                                              f"from {name}({pname}=...) at {where} with a "
                                              f"{label}: {e}")
                                    continue
                                returned += 1
                                self.fail(f"{name}({pname}=...) RETURNED {out!r} at {where} with "
                                          f"a {label}: an object that cannot be iterated or "
                                          "converted must not produce a number")
        self.assertEqual((returned, escaped), (0, 0),
                         "every swept position must REFUSE, in family: these are the two ways out")
        self.assertEqual(len(shapes), 17, "4 broken-__iter__ shapes + 4 other raising classes + "
                                          "4 hostile __getattr__ + 5 raising __float__")
        self.assertEqual(len(positions), 61, "distinct (function, parameter, position) "
                                             "combinations the sweep reaches")
        self.assertEqual(len(triples), 105, "distinct (function, case, parameter, position) "
                                            "triples: a lost _CASES row shows up here")
        self.assertEqual(swept, len(triples) * len(shapes))
        self.assertEqual(swept, 1785, "the measured sweep at this commit: 105 triples x 17 shapes. "
                                      "A regression that drops two thirds of it fails HERE, which "
                                      "a `> 400` floor did not")

    def test_c2_note_d_a_broken_iter_stays_in_family_whatever_it_raises(self):
        """NOTE D. The two sibling wrappers caught only `TypeError`, so the SAME broken `__iter__`
        raising something else escaped anyway: measured at HEAD, ValueError came out as a BARE
        ValueError (inside ValueError, outside StabilityError) and RuntimeError, KeyError and
        ZeroDivisionError came out outside ValueError entirely -- from `check_finite_sequence`,
        `check_mask` AND the row path.

        DECIDED BY MOVING THE CATCH, not the carve-out. The module's unwrapped-propagation
        carve-out names `fn` and `grad_fn` -- CALLABLES the caller supplies for this module to
        INVOKE. A data argument is read, not called. Widening the carve-out to name `__iter__`
        instead would have made the module's own `_as_flat_items` and `check_mask` wrappers (the
        N1 fix) contradict it, so honest widening of the carve-out would have required DELETING
        the N1 fix -- weakening, not fixing. So the catch moved, and `check_gradient`'s carve-out
        paragraph now says in writing that it covers callables and nothing else.
        """
        for label, make in _BROKEN_ITER + _BROKEN_ITER_OTHER:
            with self.subTest(shape=label):
                with self.assertRaises(st.ShapeError):
                    st.check_finite_sequence(make())
                with self.assertRaises(st.MaskTypeError):
                    st.check_mask(make(), 2)
                with self.assertRaises(st.ShapeError):
                    st.check_finite_matrix([make()])
                with self.assertRaises(st.StabilityError):
                    st.masked_mean_checked([1.0, 2.0], make(), 2)
                with self.assertRaises(st.ShapeError):
                    st.masked_squared_error_mean([make()], [(0.0, 0.0)], [True], 2)
        # still a ValueError, which is what existing `except ValueError` callers rely on
        for label, make in _BROKEN_ITER + _BROKEN_ITER_OTHER:
            with self.subTest(shape=label, family="ValueError"):
                with self.assertRaises(ValueError):
                    st.check_finite_matrix([make()])
        # and the original is not lost: it is chained as __cause__
        with self.assertRaises(st.ShapeError) as cm:
            st.check_finite_matrix([_iter_raises(RuntimeError)()])
        self.assertIsInstance(cm.exception.__cause__, RuntimeError)
        self.assertIn("RuntimeError", str(cm.exception))

    def test_c3_the_fourth_site_is_the_probe_that_precedes_the_materialisation(self):
        """The site nobody had reported, which deriving the set is what found.

        `hasattr(x, "__iter__")` is itself an ATTRIBUTE LOOKUP on the caller's object, and
        `hasattr` swallows only `AttributeError`. So a `__getattr__` raising anything else escaped
        from the OUTER position as well -- the position the earlier fix believed it had closed,
        because N1 wrapped the `tuple()` and not the probe that guards it. Measured at HEAD:
        RuntimeError and KeyError escaped ValueError entirely and ValueError escaped as a bare
        ValueError, from `check_finite_sequence`, `check_mask`, the row path and the flat-vs-2D
        probe in `_is_nested` / `_split_values`, on both interpreters.

        Wrapping a third `tuple()` by hand would have left this one standing, which is why the
        probe and the materialisation now sit inside one `try` in one helper.
        """
        for label, make in _BROKEN_GETATTR:
            with self.subTest(shape=label):
                with self.assertRaises(st.ShapeError):              # outer, _as_flat_items
                    st.check_finite_sequence(make())
                with self.assertRaises(st.MaskTypeError):           # outer, check_mask
                    st.check_mask(make(), 2)
                with self.assertRaises(st.ShapeError):              # row, _as_rows
                    st.check_finite_matrix([make()])
                with self.assertRaises(st.StabilityError):          # element, _is_nested
                    st.masked_mean_checked([make(), (3.0, 4.0)], [True, True], 4)
                with self.assertRaises(st.StabilityError):
                    st.masked_squared_error_mean([make()], [(0.0, 0.0)], [True], 2)
                with self.assertRaises(st.StabilityError):
                    st.check_gradient(lambda p: 1.0, lambda p: [1.0], make())
        # a `__getattr__` that raises AttributeError is the ORDINARY case and must still mean
        # "no __iter__", i.e. a plain refusal rather than the broken-probe message
        plain = type("NoIter", (), {"__getattr__": lambda s, n: (_ for _ in ()).throw(
            AttributeError(n))})()
        with self.assertRaisesRegex(st.ShapeError, "must be a sequence of numbers"):
            st.check_finite_sequence(plain)

    def test_c4_the_intake_points_are_the_only_places_that_probe_or_materialise(self):
        """The STRUCTURAL half, stated as narrowly as the mechanism actually is.

        WHAT THE AST HALF MATCHES, exactly: a call to the NAME `hasattr` or `getattr` whose second
        argument is the literal constant `"__iter__"`, or a call to the name `iter`, in a function
        other than `_materialised` / `_is_row_like`. WHAT IT DOES NOT MATCH, and nothing here
        pretends otherwise: a non-literal spelling (`probe = "__iter__"; hasattr(x, probe)`), a
        `tuple(x)` / `list(x)` with no probe at all, a `for` loop over caller input, or any
        materialisation reached through another module. This docstring used to claim the two
        helpers were "the only two places that probe or materialise caller-supplied input" -- a
        reach claim three spellings wider than its matcher, which is this project's single
        recurring defect (a correction in round 10 replaced exactly such a claim with a driven
        enumeration under the heading "the enumeration is the claim").

        WHAT ACTUALLY PROTECTS THE PROPERTY IS BEHAVIOURAL, AND IT IS `test_c1`. Measured: a
        brand-new `_eager()` helper that materialises `values` in `masked_mean_checked` with no
        `hasattr`, no `iter` and no `_materialised` is KILLED by `test_c1` (9 failures) while this
        test stays silent. So the credit belongs to the derived sweep; the AST half's job is the
        narrower one of stopping the probe from being RESPELLED by hand at a site that already
        exists, which is how the row site came to be half-fixed.

        The textual half below is this test's real structural teeth: five named derived intake
        points must each still route through their helper, and the discharged candidate must still
        be discharged by the code rather than by argument.
        """
        import ast
        src = inspect.getsource(st)
        offenders = []
        for fn in [n for n in ast.walk(ast.parse(src)) if isinstance(n, ast.FunctionDef)]:
            if fn.name in ("_materialised", "_is_row_like"):
                continue
            for node in ast.walk(fn):
                if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)):
                    continue
                if node.func.id == "iter":
                    offenders.append(f"{fn.name}() line {node.lineno}: iter(_)")
                if (node.func.id in ("hasattr", "getattr") and len(node.args) >= 2
                        and isinstance(node.args[1], ast.Constant)
                        and node.args[1].value == "__iter__"):
                    offenders.append(f"{fn.name}() line {node.lineno}: "
                                     f"{node.func.id}(_, '__iter__')")
        self.assertEqual(offenders, [], "an intake probe is spelled outside the two helpers; route "
                                        "it through _materialised / _is_row_like instead")
        for helper in ("_materialised", "_is_row_like"):
            self.assertTrue(callable(getattr(st, helper, None)), f"{helper} is gone")
        for f, helper in (("_as_flat_items", "_materialised"), ("_as_rows", "_materialised"),
                          ("check_mask", "_materialised"), ("_is_nested", "_is_row_like"),
                          ("_split_values", "_is_nested")):
            with self.subTest(site=f):
                self.assertIn(helper, inspect.getsource(getattr(st, f)),
                              f"{f} is a derived intake point and must go through {helper}")
        # the discharged candidate, asserted as discharged rather than merely argued: the inner
        # `call()` only ever receives data this module built.
        g_src = inspect.getsource(st.check_gradient)
        self.assertIn('call(grad_fn, "grad_fn", p0)', g_src)
        self.assertIn('call(fn, "fn", q)', g_src)
        self.assertIn('p0 = check_finite_sequence(point, "point")', g_src)


# FINDING G2. The conversion-protocol sites of `toy.stability`, DERIVED from its AST the way the
# intake sites were, with one row per (function, protocol, operand) and the decision in writing.
# The test below re-derives the set and compares; a new `float()`, `repr()`, `len()`, `bool()` or
# `Fraction()` fails here until it is decided -- in ANY SCOPE: a function body, the module body, a
# class body or a lambda body. That reach is the Finding I correction and is now true rather than
# written: the walker was `ast.FunctionDef`-only and skipped lambda bodies, so three of those four
# scopes were unvisited and a coercion in any of them was unkilled by all three suites on both
# interpreters. `int()` is in the candidate set the walker looks for and has no site, which is why
# it is DISCHARGED in the module's table rather than absent from it.
_CONVERSION_SITES = {
    ("_as_float", "float", "v"):
        "THE one float() in the module. The three conversion sites all call this helper, which "
        "turns a raising __float__ into NonNumericError and re-raises OverflowError unconverted",
    ("_shown", "repr", "v"):
        "THE one repr() in the module. Every error message interpolates through this helper, "
        "which degrades a raising __repr__ to a placeholder instead of losing the refusal",
    ("_distinct_values", "Fraction", "_plain_real(a)"):
        "Fraction() READS a Rational's numerator/denominator, which are the caller's properties; "
        "the handler is `except Exception` -> the float fallback, so a raising one stays in family",
    ("_distinct_values", "Fraction", "_plain_real(b)"):
        "the same statement, the other operand",
    ("_is_nested", "bool", "outer"):
        "`outer` is a tuple this module built (`_materialised`'s return), so no caller __bool__",
    ("_as_rows", "len", "r"): "a `_materialised` row tuple",
    ("_as_rows", "len", "rows[0]"): "a tuple of `_materialised` row tuples",
    ("_split_values", "len", "rows[0]"): "a tuple `_as_rows` built",
    ("_validated_masked_values", "len", "outer"): "a tuple `_as_flat_items` built",
    ("check_mask", "len", "items"): "a tuple `_materialised` built",
    ("check_params_changed", "len", "a"): "a tuple of floats `check_finite_sequence` returned",
    ("check_params_changed", "len", "b"): "a tuple of floats `check_finite_sequence` returned",
    ("masked_squared_error_mean", "len", "p_outer"): "a tuple `_as_flat_items` built",
    ("masked_squared_error_mean", "len", "t_outer"): "a tuple `_as_flat_items` built",
    ("masked_squared_error_mean", "len", "pr[0]"): "a tuple `_as_rows` built",
    ("masked_squared_error_mean", "len", "tr[0]"): "a tuple `_as_rows` built",
    ("check_gradient", "len", "p0"): "a tuple of floats `check_finite_sequence` returned",
    ("check_gradient", "len", "g_items"): "a tuple `_as_flat_items` built",
    ("call", "len", "arg"): "`arg = list(p)`, built here; the caller's callable may MUTATE it, "
                            "which is the point of the comparison, but it is still a list",
    ("call", "len", "snap"): "`snap = tuple(arg)`, built here",
}


# The OTHER SIDE of the conversion check, and the half that was missing. `_CONVERSION_SITES` above
# and the module's prose table are both HAND-WRITTEN, and the only walker was `test_g2d`'s: so
# membership WITHIN a protocol was cross-checked, while PROTOCOL coverage and SCOPE coverage were
# not. A protocol the walker never looks for, or a scope it never walks, is absent from both sides
# and the set EQUALITY passes -- which is how FINDING I (three unwalked scopes) and the missing
# `__format__` row both arose, and it is `toy.robustness`' four-public-positions-behind-a-green-check
# failure in another module. So coverage is two-sided now too: every BUILTIN this module calls must
# be either in the coercion candidate set that `test_g2d` walks for, or excused here in writing.
_NOT_A_COERCION = {
    "abs": "arithmetic on a float this module already validated, not a coercion of caller data",
    "all": "truth-tests a generator of this module's own bools (`_is_row_like`, `_same`, `x == 0.0`)",
    "any": "truth-tests the mask tuple AFTER the strict-bool gate, so no caller __bool__ is reached",
    "enumerate": "indexes a tuple this module built; reads no protocol on the elements",
    "hasattr": "the INTAKE probe, not a conversion: it has its own enumeration and _materialised",
    "isinstance": "a TYPE test, not a coercion; it is the open `__class__` channel, declared above "
                  "and scoped by test_the_open_class_channel_sentence_is_its_measured_scope",
    "iter": "the INTAKE protocol, enumerated and wrapped by _materialised",
    "list": "copies a tuple this module built (`list(p)`, `list(p0)`), never a caller object",
    "max": "arithmetic over floats `check_finite_*` already returned",
    "range": "over `n = len(p0)`, an int this module computed",
    "sum": "adds floats this module validated; the compensated-summation figure is pinned separately",
    "tuple": "inside _materialised it consumes an ITERATOR (the intake protocol); everywhere else it "
             "copies this module's own list",
    "type": "`type(x)` ignores a `__class__` property and is safe; the `__name__` lookup on its "
            "result IS a protocol and is the _type_name row of the table",
    "zip": "pairs tuples this module built",
}


class ConversionIsDerivedNotEnumerated(unittest.TestCase):
    """FINDING G2, closed as a CLASS: a CONVERSION protocol this module invokes on caller data.

    This is FINDING C's defect one protocol over. There, a protocol the module consults
    (`__iter__`) raised and a bare exception left the declared family; here the protocol is
    `__float__`, and `float()` caught exactly `OverflowError` at all three sites -- the same
    shape as NOTE D, whose sibling wrappers caught exactly `TypeError`. Measured at the commit
    before this one, identically on 3.12.4 and 3.13.5: a caller-defined `numbers.Real` whose
    `__float__` raises produced 45/45 outcomes outside StabilityError (5 exception classes x 9
    public entry points), 36 of them outside ValueError entirely. The equivalent invisibility was
    measured too: adding `except Exception -> NonNumericError` at `check_finite_scalar`'s
    `float()` was unkilled by test_stability (84 OK), test_robustness (181 OK) and test_checkpoint
    (48 OK). These tests are what make that false.

    Deriving the set rather than fixing the three reported sites found THREE MORE protocols with
    reachable sites, none of them in any report: `repr()` through every `{...!r}` in every error
    message (including one on VALID input, `_sq`'s underflow message, where a raising `__repr__`
    replaced an in-family UnderflowError with a bare RuntimeError), `type(x).__name__` through a
    metaclass, and `Fraction()` in `_distinct_values`, which reads a Rational's own `numerator`.
    """

    @staticmethod
    def _positions(o):
        """The nine public entry points a caller's value reaches a conversion through."""
        return (("check_finite_scalar", lambda: st.check_finite_scalar(o)),
                ("check_finite_sequence", lambda: st.check_finite_sequence([o])),
                ("check_finite_matrix", lambda: st.check_finite_matrix([[o]])),
                ("masked_mean_checked", lambda: st.masked_mean_checked([o], [True], 1)),
                ("masked_squared_error_mean",
                 lambda: st.masked_squared_error_mean([o], [0.0], [True], 1)),
                ("require_parameter_gradient", lambda: st.require_parameter_gradient([o])),
                ("check_params_changed", lambda: st.check_params_changed([o], [1.0])),
                ("check_gradient(point)",
                 lambda: st.check_gradient(lambda p: 1.0, lambda p: [1.0], [o])),
                ("check_gradient(step)",
                 lambda: st.check_gradient(lambda p: p[0] ** 2, lambda p: [2.0], [1.0], step=o)))

    def test_g2a_a_raising_float_stays_in_family_at_every_position(self):
        """The 45, position by position and class by class. Each must be in family, each must
        still be a ValueError (what existing callers catch), and each must chain the original."""
        seen = 0
        for exc in _FLOAT_EXCS:
            make = _float_raises(exc)
            for label, call in self._positions(make()):
                with self.subTest(raises=exc.__name__, position=label):
                    with self.assertRaises(st.NonNumericError) as cm:
                        call()
                    self.assertIsInstance(cm.exception, ValueError)
                    self.assertIn("not usable as a real number", str(cm.exception))
                    self.assertIn(exc.__name__, str(cm.exception))
                    self.assertIsInstance(cm.exception.__cause__, exc)
                    seen += 1
        self.assertEqual(seen, 45, "5 exception classes x 9 public entry points: the measurement "
                                   "this test exists to invert")
        # OverflowError keeps its own policy at each of the three sites, unconverted by the helper
        with self.assertRaises(st.NonFiniteError):
            st.check_finite_scalar(10 ** 400)
        self.assertEqual(st.masked_mean_checked([1.0, 10 ** 400], [True, False], 1,
                                                strict_masked_out=False), 1.0)
        with self.assertRaises(st.NonFiniteError):
            st.masked_squared_error_mean([10 ** 400], [0.0], [True], 1)

    def test_g2b_a_raising_repr_cannot_replace_the_refusal_it_describes(self):
        """The site nobody reported, and the worst of the three: the module is already RAISING an
        in-family error and the message formatting replaces it with a foreign exception.

        The last position is the one that matters most: the input there is VALID (a float subclass
        storing a tiny value), `_sq` has decided to refuse an underflow, and a raising `__repr__`
        turned that UnderflowError into a bare RuntimeError.
        """
        for exc in (RuntimeError, KeyError, ZeroDivisionError):
            make = _repr_raises(exc)
            rows = (("check_finite_scalar", st.NonNumericError,
                     lambda o: st.check_finite_scalar(o)),
                    ("check_finite_sequence element", st.NonNumericError,
                     lambda o: st.check_finite_sequence([o])),
                    ("check_mask entry", st.MaskTypeError, lambda o: st.check_mask([True, o], 2)),
                    ("check_mask expected_len", st.MaskLengthError,
                     lambda o: st.check_mask([True, False], o)),
                    ("denominator", st.NormalizationMismatchError,
                     lambda o: st.masked_mean_checked([1.0], [True], o)),
                    ("masked_mean element", st.NonNumericError,
                     lambda o: st.masked_mean_checked([o], [True], 1)),
                    ("_sq element", st.NonNumericError,
                     lambda o: st.masked_squared_error_mean([o], [0.0], [True], 1)),
                    ("check_gradient step", st.StabilityError,
                     lambda o: st.check_gradient(lambda p: 1.0, lambda p: [1.0], [1.0], step=o)))
            for label, want, call in rows:
                with self.subTest(raises=exc.__name__, position=label):
                    with self.assertRaises(want) as cm:
                        call(make())
                    self.assertIn("unshowable", str(cm.exception))
                    self.assertIn(exc.__name__, str(cm.exception))
            # the step position needs a NEGATIVE value to reach its message
            class _Neg(float):
                def __repr__(self):
                    raise exc("repr boom")
                __hash__ = float.__hash__
            with self.subTest(raises=exc.__name__, position="step must be > 0 message"):
                with self.assertRaisesRegex(st.StabilityError, "step must be > 0"):
                    st.check_gradient(lambda p: 1.0, lambda p: [1.0], [1.0], step=_Neg(-1.0))
            # VALID input, a refusal already decided: the UnderflowError must survive its message
            class _Tiny(float):
                def __repr__(self):
                    raise exc("repr boom")
                __hash__ = float.__hash__
            with self.subTest(raises=exc.__name__, position="_sq underflow message on VALID input"):
                with self.assertRaises(st.UnderflowError) as cm:
                    st.masked_squared_error_mean([_Tiny(1e-200)], [0.0], [True], 1)
                self.assertIn("unshowable", str(cm.exception))
        # an honest object is still shown by `repr`, so no message text changed for anyone else
        with self.assertRaises(st.NonNumericError) as cm:
            st.check_finite_sequence([1.0, None], "v")
        self.assertIn(repr(None), str(cm.exception))

    def test_g2c_a_rational_whose_numerator_raises_stays_in_family(self):
        """`_distinct_values` names four exception classes in its handler, and `Fraction(x)` READS
        a Rational's `numerator`/`denominator`. Measured before the widening: `RuntimeError`,
        `KeyError` and `AttributeError` came out bare, while the four enumerated classes were
        refused with UnderflowError -- 3 of 6 escaping from the same statement."""
        def tiny_rational(exc):
            ns = {"numerator": property(lambda s: (_ for _ in ()).throw(exc("numerator boom"))),
                  "denominator": property(lambda s: 1),
                  "__float__": lambda s: 1e-200}
            return type(f"RatRaises{exc.__name__}", (Rational,), dict(_REAL_STUBS, **ns))()
        for exc in (RuntimeError, KeyError, AttributeError, ZeroDivisionError, TypeError,
                    ValueError):
            with self.subTest(numerator_raises=exc.__name__):
                with self.assertRaises(st.UnderflowError):
                    st.masked_squared_error_mean([tiny_rational(exc)], [0.0], [True], 1)
        # the property the widening must not lose: an honest exact tiny Fraction is still refused
        from fractions import Fraction as _F
        with self.assertRaises(st.UnderflowError):
            st.masked_squared_error_mean([_F(1, 10 ** 400)], [0.0], [True], 1)
        self.assertEqual(st.masked_squared_error_mean([1e-200], [1e-200], [True], 1), 0.0)

    def test_g2d_the_conversion_enumeration_is_derived_not_written(self):
        """The fail-closed half, and the module's own figures re-derived from its AST.

        The intake enumeration's stated exclusion of `float()`/`int()` was "the conversion
        protocol is documented above as taken at its word" -- unswept, because taken at its word
        is about LYING and says nothing about RAISING. So the exclusion is replaced by a derived
        enumeration with the same fail-closed property the intake set has: a new coercion applied
        anywhere in the module fails HERE until someone decides it in writing.

        FINDING I: "anywhere in the module" WAS FALSE IN THREE SCOPES, and so was the identical
        phrase in the comment above `_CONVERSION_SITES`. The walker was
        `[n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]` and `own_nodes` skipped
        `ast.Lambda` bodies, so the MODULE body, every CLASS body and every LAMBDA body were
        unvisited. Measured, one added raw `len()` coercion per scope: in a function body, FAILED
        (192 failures, 39 errors); in the module body, in `GradientCheckReport`'s class body, and in
        a lambda body, UNKILLED by test_stability, test_robustness and test_checkpoint on both
        interpreters. HEAD has zero coercion sites in those three scopes, so there was no
        behavioural consequence -- the finding is against the derivation's stated fail-closed
        property, which IS the claim this test makes.

        `test_c4` is the model for what to do, and round 16 did it there: either state the reach
        exactly or widen the matcher. Widening was clean here, so the walker is widened -- all four
        scope kinds, with decorators, default values, annotations and base classes attributed to the
        ENCLOSING scope, which is where they are evaluated. (`ShiftSpec`-style module-level lambdas
        are what bit `toy.robustness`; this module has none at HEAD, which is exactly why nothing
        noticed.) And the widening is itself checked from BOTH sides, below: every `ast.Call` and
        `ast.FormattedValue` in the tree must be attributed to exactly one scope, so a scope kind
        the walker does not know about fails instead of being silently empty.
        """
        import ast, builtins, re
        src = inspect.getsource(st)
        tree = ast.parse(src)
        SCOPED = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)

        def scopes(tree):
            """EVERY scope, not only `ast.FunctionDef`: the module body, each class body and each
            lambda body as well. This is the Finding I widening."""
            yield "<module>", list(tree.body)
            for n in ast.walk(tree):
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    yield n.name, list(n.body)
                elif isinstance(n, ast.Lambda):
                    yield "<lambda>", [n.body]

        def own_nodes(body):
            """`body`'s own nodes. A nested scope is its own subject, but the expressions evaluated
            in THIS scope on its behalf are not: a decorator, a default value, an annotation and a
            base-class expression all run here, so they stay attributed here. Without that, one
            `dataclass(frozen=True)` call was reachable by no scope at all."""
            stack = list(body)
            while stack:
                n = stack.pop()
                if isinstance(n, SCOPED):
                    if not isinstance(n, ast.Lambda):
                        stack.extend(n.decorator_list)
                    if isinstance(n, ast.ClassDef):
                        stack.extend(n.bases)
                        stack.extend(k.value for k in n.keywords)
                    else:
                        a = n.args
                        stack.extend(x for x in a.defaults if x is not None)
                        stack.extend(x for x in a.kw_defaults if x is not None)
                        if not isinstance(n, ast.Lambda):
                            if n.returns is not None:
                                stack.append(n.returns)
                            for arg in a.posonlyargs + a.args + a.kwonlyargs:
                                if arg.annotation is not None:
                                    stack.append(arg.annotation)
                            for arg in (a.vararg, a.kwarg):
                                if arg is not None and arg.annotation is not None:
                                    stack.append(arg.annotation)
                    continue
                yield n
                stack.extend(ast.iter_child_nodes(n))

        coercions = ("float", "int", "bool", "len", "repr", "Fraction")
        derived, by_proto, shown, typed = set(), {}, 0, 0
        as_float_calls, as_float_lines = 0, set()
        attributed, bare_fmt, label_fmt = [], 0, 0
        for scope, body in scopes(tree):
            for node in own_nodes(body):
                if isinstance(node, (ast.Call, ast.FormattedValue)):
                    attributed.append(id(node))
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                    if node.func.id in coercions:
                        arg = ast.unparse(node.args[0]) if node.args else ""
                        derived.add((scope, node.func.id, arg))
                        by_proto[node.func.id] = by_proto.get(node.func.id, 0) + 1
                    elif node.func.id == "_shown":
                        shown += 1
                    elif node.func.id == "_type_name":
                        typed += 1
                    elif node.func.id == "_as_float":
                        as_float_calls += 1
                        as_float_lines.add(node.lineno)
                if isinstance(node, ast.FormattedValue):
                    if node.conversion == ord("r"):
                        derived.add((scope, "!r", ast.unparse(node.value)))
                    elif node.conversion == -1:
                        bare_fmt += 1
                        label_fmt += ast.unparse(node.value) in ("name", "what", "where")
        # SIDE ONE of the coverage check: the walker's scopes partition the tree. A scope kind it
        # does not know is not silently empty, it is a mismatch here.
        everything = [n for n in ast.walk(tree) if isinstance(n, (ast.Call, ast.FormattedValue))]
        self.assertEqual(len(attributed), len(everything),
                         "the scope walker does not reach every call/interpolation in the module: "
                         "a scope kind it ignores is absent from the derived set AND from "
                         "_CONVERSION_SITES, so the set equality below would pass vacuously")
        self.assertEqual(len(set(attributed)), len(attributed), "a node attributed to two scopes")
        self.assertIn("<module>", {s for s, _ in scopes(tree)})
        self.assertIn("GradientCheckReport", {s for s, _ in scopes(tree)})
        # SIDE TWO: protocol coverage. Every builtin this module CALLS is either a coercion the
        # walker looks for, or excused in writing. A protocol in neither is the Finding I defect one
        # axis over: invisible to the walker and to the table at once.
        called = {n.func.id for n in everything
                  if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
        builtin_called = {n for n in called if hasattr(builtins, n)}
        self.assertEqual(builtin_called - set(coercions), set(_NOT_A_COERCION),
                         "a builtin this module calls is neither in the coercion candidate set this "
                         "test walks for nor excused in _NOT_A_COERCION: decide it in writing")
        for n, why in _NOT_A_COERCION.items():
            with self.subTest(builtin=n):
                self.assertIn(n, builtin_called,
                              f"_NOT_A_COERCION excuses {n}(), which this module no longer calls")
                self.assertTrue(why.strip())
        self.assertEqual(derived, set(_CONVERSION_SITES),
                         "a coercion protocol is applied at a site this enumeration does not "
                         "decide: give it a row in _CONVERSION_SITES with the reason it is safe, "
                         "or route it through _as_float / _shown / _type_name")
        for key, why in _CONVERSION_SITES.items():
            with self.subTest(site=key):
                self.assertTrue(why.strip(), f"{key} has no decision written")
        # the structural claim, stated exactly: float() and repr() are spelled ONCE each, in their
        # helper, and no `{...!r}` conversion survives anywhere in the module
        self.assertEqual([k for k in derived if k[1] == "float"], [("_as_float", "float", "v")])
        self.assertEqual([k for k in derived if k[1] == "repr"], [("_shown", "repr", "v")])
        self.assertEqual([k for k in derived if k[1] == "!r"], [])
        self.assertEqual([k for k in derived if k[1] == "int"], [],
                         "int() has no site: _plain_real calls int.__int__ at type level")
        # and the figures the comment block quotes are this AST's figures
        block = src.split("caller-input conversion protocols")[1].split("def _shown")[0]
        fig = dict(float_calls=r"float\(\)\s+-- (\d+) calls in (\d+) statements",
                   shown=r"repr\(\), as `\{x!r\}` -- (\d+) interpolations",
                   typed=r"type\(x\)\.__name__\s+-- (\d+) interpolations",
                   frac=r"Fraction\(\.\.\.\)\s+-- (\d+) calls in (\d+) statement",
                   ints=r"int\(\)\s+-- (\d+) calls", bools=r"bool\(\)\s+-- (\d+) call",
                   lens=r"len\(\)\s+-- (\d+) calls")
        m = {k: re.search(v, block) for k, v in fig.items()}
        for k, mm in m.items():
            self.assertIsNotNone(mm, f"the conversion enumeration no longer quotes its {k} figure")
        self.assertEqual((int(m["float_calls"].group(1)), int(m["float_calls"].group(2))),
                         (as_float_calls, len(as_float_lines)),
                         "the float() figure: calls to _as_float, and the statements holding them")
        self.assertEqual(int(m["shown"].group(1)), shown, "_shown interpolations")
        self.assertEqual(int(m["typed"].group(1)), typed, "_type_name interpolations")
        self.assertEqual(int(m["frac"].group(1)), by_proto.get("Fraction", 0))
        self.assertEqual(int(m["ints"].group(1)), by_proto.get("int", 0))
        self.assertEqual(int(m["bools"].group(1)), by_proto.get("bool", 0))
        self.assertEqual(int(m["lens"].group(1)), by_proto.get("len", 0))
        for helper in ("_as_float", "_shown", "_type_name"):
            self.assertTrue(callable(getattr(st, helper, None)), f"{helper} is gone")
        # the EIGHTH protocol, which had no row: `__format__` through a bare `{x}`. It is DECLARED
        # rather than converted, so it has no `_CONVERSION_SITES` rows -- 111 of them would say
        # nothing -- but its three figures are derived from this same AST and read out of the row.
        fmt = re.search(r"__format__ as `\{x\}` -- (\d+) interpolations, (\d+) of them "
                        r"module-produced, (\d+) on the label chain", block)
        self.assertIsNotNone(fmt, "the conversion enumeration no longer gives __format__ a row")
        self.assertEqual((int(fmt.group(1)), int(fmt.group(2)), int(fmt.group(3))),
                         (bare_fmt, bare_fmt - label_fmt, label_fmt),
                         "the __format__ row's figures are not this AST's figures")
        self.assertEqual(len([k for k in derived if k[1] == "!r"]), 0,
                         "every repr goes through _shown, so no `{x!r}` interpolation is left")
        # and the correction that row makes to its own reason: the label is formatted EAGERLY, on
        # the SUCCESS path. Asserted by OBSERVING the format rather than by letting one raise -- an
        # assertion that the raise escapes would pin a defect in a channel that is declared, not
        # closed, and would fail on the eventual fix.
        seen = []

        class CountingLabel(str):
            def __format__(self, spec):
                seen.append(spec)
                return str(self)

        self.assertEqual(st.check_finite_sequence([1.0, 2.0], CountingLabel("values")), (1.0, 2.0))
        self.assertTrue(seen, "the `where` label is interpolated only while phrasing a refusal, so "
                              "the row's 'built EAGERLY, on the SUCCESS path' is wrong")

    def test_g2f_a_type_whose_name_raises_cannot_replace_the_refusal_either(self):
        """`type(x).__name__` is the other protocol every message here invokes on caller data.

        `type(x)` itself is safe -- it ignores a `__class__` property, which is exactly why this is
        NOT the kit-wide `__class__` finding and IS closable in this file -- but `__name__` on the
        resulting class is an attribute lookup a METACLASS can answer with an exception. Measured
        before `_type_name` existed: a bare RuntimeError out of `check_finite_scalar` and
        `check_finite_sequence`. Pinned because the fix was invisible without it: reverting
        `_type_name` to re-raise was unkilled by the whole of test_stability until this test.
        """
        meta = type("NameBoom", (type,), {"__name__": property(
            lambda cls: (_ for _ in ()).throw(RuntimeError("name boom")))})
        hidden = meta("Hidden", (), {})
        rows = (("check_finite_scalar", lambda: st.check_finite_scalar(hidden()), True),
                ("sequence element", lambda: st.check_finite_sequence([hidden()]), True),
                ("outer argument", lambda: st.check_finite_sequence(hidden()), True),
                ("mask entry", lambda: st.check_mask([True, hidden()], 2), True),
                ("expected_len", lambda: st.check_mask([True], hidden()), True),
                ("masked element", lambda: st.masked_mean_checked([hidden()], [True], 1), True),
                ("_sq element",
                 lambda: st.masked_squared_error_mean([hidden()], [0.0], [True], 1), True),
                # `masked_mean_checked`'s divisor message shows the value and not the type name,
                # so there is nothing for `_type_name` to reach there: in family is the whole claim
                ("denominator", lambda: st.masked_mean_checked([1.0], [True], hidden()), False))
        for label, call, names_the_type in rows:
            with self.subTest(position=label):
                with self.assertRaises(st.StabilityError) as cm:
                    call()
                if names_the_type:
                    self.assertIn("<unnamed type>", str(cm.exception))
        # the EXCEPTION class `_materialised` names in its message goes through it as well
        hidden_exc = meta("HiddenExc", (Exception,), {})
        broken = type("IterHiddenExc", (), {
            "__iter__": lambda s: (_ for _ in ()).throw(hidden_exc("boom"))})()
        with self.assertRaises(st.ShapeError) as cm:
            st.check_finite_sequence(broken)
        self.assertIn("<unnamed type>", str(cm.exception))

    def test_g2g_the_unconverted_trio_still_propagates_through_every_helper(self):
        """`_UNCONVERTED` -- MemoryError, RecursionError, SystemError -- reports the state of the
        interpreter rather than the shape of the input, so all four helpers re-raise it instead of
        describing it. That policy was written in `stability.py` and asserted nowhere, which made
        every `except _UNCONVERTED: raise` line a free mutation; it is asserted here for the
        intake helper and for the three conversion helpers alike."""
        for exc in (MemoryError, RecursionError, SystemError):
            with self.subTest(exc=exc.__name__):
                with self.assertRaises(exc):                     # _materialised
                    st.check_finite_sequence(_iter_raises(exc)())
                with self.assertRaises(exc):                     # _as_float
                    st.check_finite_scalar(_float_raises(exc)())
                with self.assertRaises(exc):                     # _shown, inside a refusal message
                    st.check_finite_scalar(_repr_raises(exc)())
                meta = type("NameExplodes", (type,), {"__name__": property(
                    lambda cls, e=exc: (_ for _ in ()).throw(e("name boom")))})
                with self.assertRaises(exc):                     # _type_name
                    st.check_finite_scalar(meta("H", (), {})())

    def test_g2e_the_discharged_protocols_are_discharged_by_measurement(self):
        """Three protocols the enumeration DISCHARGES, each probed rather than argued, because a
        discharge believed rather than measured is how the `call()` candidate nearly slipped."""
        hostile = type("IndexBoom", (), {
            "__index__": lambda s: (_ for _ in ()).throw(RuntimeError("index")),
            "__int__": lambda s: (_ for _ in ()).throw(RuntimeError("int")),
            "__bool__": lambda s: (_ for _ in ()).throw(RuntimeError("bool")),
            "__len__": lambda s: (_ for _ in ()).throw(RuntimeError("len"))})
        with self.assertRaises(st.MaskLengthError):          # int()/__index__ are never consulted
            st.check_mask([True, False], hostile())
        with self.assertRaises(st.NormalizationMismatchError):
            st.masked_mean_checked([1.0], [True], hostile())
        # a mask entry's own __bool__ is never consulted: the strict-bool gate precedes any()
        with self.assertRaises(st.MaskTypeError):
            st.check_mask([type("BoolBoom", (int,), {
                "__bool__": lambda s: (_ for _ in ()).throw(RuntimeError("bool"))})(1)], 1)
        # len() is taken on this module's copy, never on the caller's object. The behaviour change
        # this fix makes, pinned as the enumeration describes it: such an object is now ACCEPTED
        # and read verbatim (HEAD refused it, incidentally, via `tuple(obj)`).
        lying_len = type("LenBoom", (tuple,), {
            "__len__": lambda s: (_ for _ in ()).throw(RuntimeError("len"))})
        self.assertEqual(st.check_finite_sequence(lying_len((1.0, 2.0))), (1.0, 2.0))
        self.assertEqual(st.check_mask(lying_len((True, False)), 2), (True, False))
        with self.assertRaises(st.NormalizationMismatchError):   # and `len` still decides on the copy
            st.masked_mean_checked(lying_len((1.0, 2.0)), [True, True], 1)
        # `_same`'s bare `==` is the one comparison whose operand a caller's CALLABLE places. This
        # block used to assert it with ONE base -- `type("EqBoom", (float,), ...)` -- and the base
        # was the whole difference: `_plain_real` normalises only int/float, so the same shape on a
        # plain object, a `numbers.Real` subclass or a `Fraction` subclass left this module as a
        # bare RuntimeError, 12 of 30 cells, with 3 more returning a PASS report. FINDING H. The
        # base is swept over here, and the full 5 x 3 x 2 matrix is
        # `TheFifthAxisIsACallablePlacedOperand`.
        for base, bname in _CMP_BASES:
            with self.subTest(base=bname):
                f, g = _writer("fn", _cmp_hostile(base, "raises from __eq__"))
                with self.assertRaisesRegex(st.StabilityError, "mutated its input"):
                    st.check_gradient(f, g, [1.0, 2.0])


class TheCarveOutWhereItsHalvesMeet(unittest.TestCase):
    """FINDING G1. `grad_fn` is a CALLABLE whose RETURN VALUE is a data argument, and when it is
    lazy the data half decides -- so "an exception raised inside the caller's `fn`/`grad_fn`
    propagates unwrapped ... that carve-out is about CALLABLES ... and it covers nothing else" was
    false exactly where its two halves meet.

    Measured: a plain generator-function `grad_fn` is SUPPORTED input (HEAD returns a full
    `GradientCheckReport` for it, and for a genexp and a `map()`), while the same generator raising
    `ZeroDivisionError` mid-body -- the carve-out's own example class, inside the caller's own
    `grad_fn` -- yields a `ShapeError`. Both halves of the old message were also wrong: neither
    `__iter__` nor an attribute lookup raised (the body did, during `__next__`), and the generator
    IS usable as a sequence. The paragraph was unpinned as well: deleting it, and inverting it to
    say data exceptions propagate unwrapped too, were both unkilled by all three permitted modules
    on both interpreters.
    """

    _F = staticmethod(lambda p: p[0] ** 2 + 3.0 * p[1])

    class _Dom(Exception):
        """a caller's own domain exception: the class the module can know nothing about"""

    def test_g1a_a_lazy_grad_fn_is_supported_input_and_its_body_is_a_data_read(self):
        def honest(p):
            yield 2.0 * p[0]
            yield 3.0
        for label, gf in (("generator function", honest),
                          ("generator expression", lambda p: (v for v in (2.0 * p[0], 3.0))),
                          ("map()", lambda p: map(float, [2.0 * p[0], 3.0]))):
            with self.subTest(supported=label):
                r = st.check_gradient(self._F, gf, [1.0, 2.0])
                self.assertIsInstance(r, st.GradientCheckReport)
                self.assertEqual(r.analytic, (2.0, 3.0))
        for exc in (ZeroDivisionError, KeyError, AttributeError, self._Dom, ValueError,
                    RuntimeError):
            def bad(p, e=exc):
                yield 2.0 * p[0]
                raise e("the caller's own grad_fn body")
            with self.subTest(lazy_body_raises=exc.__name__):
                with self.assertRaises(st.ShapeError) as cm:
                    st.check_gradient(self._F, bad, [1.0, 2.0])
                self.assertIsInstance(cm.exception.__cause__, exc)
        # the EAGER half of the carve-out is unchanged: the call itself propagates unwrapped
        with self.assertRaises(ZeroDivisionError):
            st.check_gradient(self._F, lambda p: 1 / 0, [1.0, 2.0])
        with self.assertRaises(ZeroDivisionError):
            st.check_gradient(lambda p: 1 / 0, lambda p: [2.0, 3.0], [1.0, 2.0])
        # and the same lazy producer at the other data positions
        def gx(exc, vals=(1.0, 2.0)):
            return (v if i == 0 else (_ for _ in ()).throw(exc("body"))
                    for i, v in enumerate(vals))
        for exc in (ZeroDivisionError, KeyError, self._Dom):
            for label, call in (("values", lambda e=exc: st.check_finite_sequence(gx(e))),
                                ("row", lambda e=exc: st.check_finite_matrix([gx(e)])),
                                ("masked values",
                                 lambda e=exc: st.masked_mean_checked(gx(e), [True, True], 2)),
                                ("point", lambda e=exc: st.check_gradient(
                                    lambda p: p[0] ** 2, lambda p: [2 * p[0], 0.1], gx(e))),
                                ("param_grad",
                                 lambda e=exc: st.require_parameter_gradient(gx(e)))):
                with self.subTest(position=label, raises=exc.__name__):
                    with self.assertRaises(st.StabilityError):
                        call()

    def test_g1b_the_materialised_message_blames_the_half_that_failed(self):
        """The message asserted `__iter__` had raised when the producer's BODY had, and asserted
        the object was "not usable as a sequence" when it was. One `try`, two descriptions."""
        def bad(p):
            yield 2.0 * p[0]
            raise ZeroDivisionError("body")
        with self.assertRaises(st.ShapeError) as cm:
            st.check_gradient(self._F, bad, [1.0, 2.0])
        msg = str(cm.exception)
        self.assertIn("it is iterable, but reading its elements raised ZeroDivisionError", msg)
        self.assertIn("the failure is its producer's", msg)
        self.assertNotIn("__iter__ or attribute lookup raised", msg)
        self.assertNotIn("not usable as a sequence", msg)
        # the OTHER half still says what it always said, and must not be relabelled
        with self.assertRaises(st.ShapeError) as cm2:
            st.check_finite_sequence(_iter_raises(RuntimeError)())
        self.assertIn("its __iter__ or attribute lookup raised RuntimeError", str(cm2.exception))
        self.assertNotIn("reading its elements", str(cm2.exception))
        with self.assertRaises(st.ShapeError) as cm3:
            st.check_finite_sequence(_getattr_raises(KeyError)())
        self.assertIn("its __iter__ or attribute lookup raised KeyError", str(cm3.exception))
        # and the ordinary refusal, with nothing raised at all, keeps the plain message
        with self.assertRaises(st.ShapeError) as cm4:
            st.check_finite_sequence(5)
        self.assertEqual(str(cm4.exception), "values must be a sequence of numbers, got int")

    def test_g1c_the_cost_of_the_widening_is_real_and_disclosed(self):
        """The flip side of "existing callers that already catch ValueError keep working", which
        was written nowhere: a caller's own `ZeroDivisionError`, raised in the generator it passed,
        now arrives as this module's shape complaint and is absorbed by `except ValueError`.

        The classification is defensible -- the module genuinely cannot tell "not a sequence" from
        "this sequence's producer failed" -- so what is asserted here is the COST and its
        mitigation (`__cause__`), not a different behaviour.
        """
        def caller_bug():
            yield 1.0
            raise ZeroDivisionError("the caller's own bug, not a shape problem")
        absorbed = False
        try:
            st.check_finite_sequence(caller_bug())
        except ValueError as e:                 # the caller's `except ValueError: skip_batch()`
            absorbed = True
            self.assertIsInstance(e, st.ShapeError)
            self.assertIsInstance(e.__cause__, ZeroDivisionError)   # the diagnosis is not lost
        self.assertTrue(absorbed, "the documented cost is that this IS absorbed as a ValueError")


# --------------------------------------------------------------------------- FINDING J
# The `__class__` channel's MEASURED SCOPE, position by position. The module's sentence about it is
# what the NEXT OWNER reads about an open finding, which is what makes it load-bearing -- and the
# test that pinned it asserted only the SIX in-family positions it happened to name, so it could not
# notice an OMISSION FROM THE ESCAPE LIST. `require_parameter_gradient(input_grad=...)` was exactly
# that omission: an OUTER argument position of a public function that escapes, while the sentence
# said outer positions come out in family. It is in neither of the sentence's two lists, it is
# absent from `_CASES` (no row passes `param_grad=None`) and it is excluded by
# `_NOT_A_LYING_NUMBER`, so no derived sweep reached it either.
#
# The asymmetry is fixed by ACCOUNTING FOR EVERY POSITION rather than by asserting one half: the
# (function, parameter) set is DERIVED from the signatures of the nine public functions, every pair
# must appear in this table or be excused below, and each row says which half of the sentence it
# belongs to. Behaviour is asserted for the IN-FAMILY rows only. The escaping rows are asserted
# about NOTHING: the `__class__` channel reaches every `isinstance` in three files and the fix is
# those owners' joint decision, so a test that pinned an escape would pin a defect and fail on the
# eventual fix.
#
# REACH, stated exactly rather than implied: the PARAMETER set is derived and fails closed; the
# POSITION KINDS (outer / row / element / scalar / a callable's return value) are enumerated here by
# hand, one row per kind that was driven. A position kind nobody drives is not in this table.
def _class_boom():
    """A caller object whose `__class__` is a property that raises: iterable, so it reaches past the
    sequence probe wherever one exists."""
    class C:
        @property
        def __class__(self):
            raise RuntimeError("class boom")

        def __iter__(self):
            return iter([1.0, 2.0])
    return C()


_IN_FAMILY, _ESCAPES = "in family", "escapes"
_CLASS_CHANNEL_POSITIONS = (
    ("check_finite_scalar", "value", "scalar", _ESCAPES,
     lambda h: st.check_finite_scalar(h)),
    ("check_finite_sequence", "values", "outer", _IN_FAMILY,
     lambda h: st.check_finite_sequence(h)),
    ("check_finite_sequence", "values", "element", _ESCAPES,
     lambda h: st.check_finite_sequence([h])),
    ("check_finite_matrix", "m", "outer", _IN_FAMILY,
     lambda h: st.check_finite_matrix(h)),
    ("check_finite_matrix", "m", "row", _IN_FAMILY,
     lambda h: st.check_finite_matrix([h])),
    ("check_finite_matrix", "m", "element", _ESCAPES,
     lambda h: st.check_finite_matrix([[h]])),
    ("check_mask", "mask", "outer", _IN_FAMILY, lambda h: st.check_mask(h, 2)),
    ("check_mask", "mask", "element", _ESCAPES, lambda h: st.check_mask([h], 1)),
    ("check_mask", "expected_len", "scalar", _ESCAPES, lambda h: st.check_mask([True], h)),
    ("masked_mean_checked", "values", "outer", _IN_FAMILY,
     lambda h: st.masked_mean_checked(h, [True, True], 2)),
    ("masked_mean_checked", "values", "row", _ESCAPES,
     lambda h: st.masked_mean_checked([h], [True], 2)),
    ("masked_mean_checked", "values", "element", _ESCAPES,
     lambda h: st.masked_mean_checked([h], [True], 1)),
    ("masked_mean_checked", "mask", "outer", _IN_FAMILY,
     lambda h: st.masked_mean_checked([1.0], h, 1)),
    ("masked_mean_checked", "mask", "element", _ESCAPES,
     lambda h: st.masked_mean_checked([1.0], [h], 1)),
    ("masked_mean_checked", "denominator", "scalar", _ESCAPES,
     lambda h: st.masked_mean_checked([1.0], [True], h)),
    ("masked_squared_error_mean", "prediction", "outer", _IN_FAMILY,
     lambda h: st.masked_squared_error_mean(h, [1.0, 2.0], [True, True], 2)),
    ("masked_squared_error_mean", "prediction", "element", _ESCAPES,
     lambda h: st.masked_squared_error_mean([h], [1.0], [True], 1)),
    ("masked_squared_error_mean", "target", "outer", _IN_FAMILY,
     lambda h: st.masked_squared_error_mean([1.0, 2.0], h, [True, True], 2)),
    ("masked_squared_error_mean", "target", "element", _ESCAPES,
     lambda h: st.masked_squared_error_mean([1.0], [h], [True], 1)),
    ("masked_squared_error_mean", "mask", "outer", _IN_FAMILY,
     lambda h: st.masked_squared_error_mean([1.0], [2.0], h, 1)),
    ("masked_squared_error_mean", "denominator", "scalar", _ESCAPES,
     lambda h: st.masked_squared_error_mean([1.0], [2.0], [True], h)),
    ("check_gradient", "point", "outer", _IN_FAMILY,
     lambda h: st.check_gradient(_F_FLAT, lambda p: [1.0, 1.0], h)),
    ("check_gradient", "point", "element", _ESCAPES,
     lambda h: st.check_gradient(_F_FLAT, lambda p: [1.0, 1.0], [h, 1.0])),
    ("check_gradient", "step", "scalar", _ESCAPES,
     lambda h: st.check_gradient(_F_QUAD, _G_QUAD, [1.0, 2.0], step=h)),
    ("check_gradient", "rtol", "scalar", _ESCAPES,
     lambda h: st.check_gradient(_F_QUAD, _G_QUAD, [1.0, 2.0], rtol=h)),
    ("check_gradient", "atol", "scalar", _ESCAPES,
     lambda h: st.check_gradient(_F_QUAD, _G_QUAD, [1.0, 2.0], atol=h)),
    ("check_gradient", "zero_tol", "scalar", _ESCAPES,
     lambda h: st.check_gradient(_F_QUAD, _G_QUAD, [1.0, 2.0], zero_tol=h)),
    ("check_gradient", "fn", "return value", _ESCAPES,
     lambda h: st.check_gradient(lambda p: h, lambda p: [2.0], [1.0])),
    ("check_gradient", "grad_fn", "return element", _ESCAPES,
     lambda h: st.check_gradient(lambda p: p[0] ** 2, lambda p: [h], [1.0])),
    ("require_parameter_gradient", "param_grad", "outer", _IN_FAMILY,
     lambda h: st.require_parameter_gradient(h)),
    ("require_parameter_gradient", "param_grad", "element", _ESCAPES,
     lambda h: st.require_parameter_gradient([h])),
    # THE OMISSION. An OUTER argument position of a public function that ESCAPES, which the old
    # sentence's "the OUTER positions come out IN FAMILY" contradicts, and which its escape list did
    # not name. Its other four hostile shapes all come out as MissingGradientError.
    ("require_parameter_gradient", "input_grad", "outer", _ESCAPES,
     lambda h: st.require_parameter_gradient(None, input_grad=h)),
    ("require_parameter_gradient", "input_grad", "element", _ESCAPES,
     lambda h: st.require_parameter_gradient(None, input_grad=[h])),
    ("check_params_changed", "before", "outer", _IN_FAMILY,
     lambda h: st.check_params_changed(h, [1.0, 2.0])),
    ("check_params_changed", "before", "element", _ESCAPES,
     lambda h: st.check_params_changed([h], [1.0])),
    ("check_params_changed", "after", "outer", _IN_FAMILY,
     lambda h: st.check_params_changed([1.0, 2.0], h)),
    ("check_params_changed", "after", "element", _ESCAPES,
     lambda h: st.check_params_changed([1.0], [h])),
    ("check_params_changed", "min_abs_change", "scalar", _ESCAPES,
     lambda h: st.check_params_changed([1.0], [2.0], min_abs_change=h)),
)

# Parameters of the nine public functions that the `__class__` channel cannot reach, each with the
# reason. A parameter in neither this table nor `_CLASS_CHANNEL_POSITIONS` fails the test below.
_NOT_A_CLASS_CHANNEL_POSITION = {
    ("check_finite_scalar", "name"): "a str label: no isinstance is applied to it",
    ("check_finite_sequence", "name"): "a str label: no isinstance is applied to it",
    ("check_finite_matrix", "name"): "a str label: no isinstance is applied to it",
    ("check_mask", "name"): "a str label: no isinstance is applied to it",
    ("masked_mean_checked", "name"): "a str label: no isinstance is applied to it",
    ("require_parameter_gradient", "name"): "a str label: no isinstance is applied to it",
    ("check_params_changed", "name"): "a str label: no isinstance is applied to it",
    ("masked_mean_checked", "strict_masked_out"): "a bool policy flag, truth-tested and never "
                                                  "isinstance-tested",
    ("masked_squared_error_mean", "strict_masked_out"): "a bool policy flag, truth-tested and never "
                                                        "isinstance-tested",
}


class FiguresAndDocPinInventory(unittest.TestCase):
    """The figures that were merely WRITTEN, asserted; and the doc-pin counts, derived."""

    _WORD = {0: "No", 1: "One", 2: "Two", 3: "Three", 4: "Four", 5: "Five", 6: "Six", 7: "Seven",
             8: "Eight"}

    def test_the_compensated_summation_figure_is_this_interpreters_behaviour(self):
        """`sum([1e16, 1.0, -1e16])` is 1.0, not 0.0 -- `stability.py`'s `check_gradient`
        docstring. It was UNPINNED and `1e16` appeared nowhere in this file.

        This is the one figure in the module that is a two-interpreter PORTABILITY promise, sitting
        unasserted in the module that was unmarked for a two-interpreter failure, so it is pinned
        first. Measured 1.0 on 3.12.4 and 1.0 on 3.13.5. The claim is about THIS module's
        accumulation, so `masked_mean_checked` is asserted too, flat and 2D: without the
        compensation the sum is 0.0 and the mean 0.0 instead of 1/3.
        """
        self.assertEqual(sum([1e16, 1.0, -1e16]), 1.0)
        self.assertNotEqual(sum([1e16, 1.0, -1e16]), 0.0)
        self.assertGreaterEqual(sys.version_info[:2], (3, 12), "the docstring says CPython 3.12+")
        self.assertEqual(st.masked_mean_checked([1e16, 1.0, -1e16], [True, True, True], 3), 1.0 / 3)
        self.assertEqual(st.masked_mean_checked([[1e16, 1.0, -1e16]], [True], 3), 1.0 / 3)
        # naive left-to-right accumulation is what the sentence contrasts itself with
        total = 0.0
        for v in (1e16, 1.0, -1e16):
            total += v
        self.assertEqual(total, 0.0)

    def test_the_error_family_is_twelve_subclasses_and_one_base(self):
        """"Subclasses are distinct per failure" was neither written as a numeral nor asserted as a
        count, and `test_distinct_errors` asserted distinctness for only the THREE mask classes --
        the other nine had no distinctness and no count assertion at all.

        Measured: 13 classes including the base, 12 strict `StabilityError` subclasses. Both
        figures are derived here, and distinctness is asserted for all twelve.
        """
        classes = {n: o for n, o in vars(st).items()
                   if isinstance(o, type) and issubclass(o, st.StabilityError)}
        strict = {n: o for n, o in classes.items() if o is not st.StabilityError}
        self.assertEqual(len(classes), 13, f"13 expected, got {sorted(classes)}")
        self.assertEqual(len(strict), 12, f"12 strict subclasses expected, got {sorted(strict)}")
        self.assertTrue(issubclass(st.StabilityError, ValueError))
        self.assertEqual(set(classes) - set(strict), {"StabilityError"})
        for a in strict.values():
            for b in strict.values():
                if a is not b:
                    self.assertFalse(issubclass(a, b),
                                     f"{a.__name__} is a subclass of {b.__name__}: the twelve are "
                                     "documented as distinct per failure")
        # every one of the twelve is public and excused in _NOT_A_GUARD as an exception class
        for n in strict:
            self.assertIn(n, _NOT_A_GUARD)

    def test_the_load_bearing_sentence_count_is_derived_not_written(self):
        """The class docstring read "Three sentences that were wider than their mechanism" and the
        count was wrong AND untied to anything: there were 3 `D` constants but 4 cleandoc'd
        `assertIn` pins (D1, D2, D3 and "Rejected before comparing") plus 1 `assertNotIn`.

        A previous correction in this project put its replacement figure in a docstring and a
        comment -- which is the error the correction was about -- so this one is a count derived
        from the class and compared against the word written in its docstring.

        It fired as intended when FINDING G1 and G2 added D5, D6 and D7: the figure moved from
        four to seven and this test failed until the docstring said so. It fired again when FINDING
        K promoted the one keyword pin to D8.
        """
        passages = {k: v for k, v in vars(LoadBearingSentences).items()
                    if k.startswith("D") and isinstance(v, str)}
        withdrawn = {k for k in passages if k.endswith("_WITHDRAWN")}
        positive = {k for k in passages if k not in withdrawn}
        self.assertEqual(len(positive), 8, f"positive passages: {sorted(positive)}")
        self.assertEqual(len(withdrawn), 1, f"withdrawn passages: {sorted(withdrawn)}")
        src = inspect.getsource(LoadBearingSentences)
        self.assertEqual(src.count("assertIn("), 8, "cleandoc'd assertIn doc pins")
        self.assertEqual(src.count("assertNotIn("), 2)
        doc = _doc(LoadBearingSentences)
        if doc is not None:
            self.assertIn(f"{self._WORD[len(positive)]} passages", doc,
                          "the figure in the docstring disagrees with the class")
            self.assertIn(f"{self._WORD[len(withdrawn)].lower()} withdrawn sentence", doc)

    def test_the_derived_figures_in_these_comments_match_their_lists(self):
        """The policing of derived figures, EXTENDED from docstrings to the two comment blocks.

        `test_the_load_bearing_sentence_count_is_derived_not_written` polices one figure, in one
        class docstring. The intake enumeration's own figure was outside that reach and was wrong:
        it said the derivation "found FIVE candidates and discharged two" while its list marks four
        intake points and ONE discharge -- a derived figure in a comment, asserted by nothing,
        which is the exact category that test exists for. So the policing is extended here to
        count the end-of-row markers in both comment blocks and compare them with the words the
        blocks write. `inspect.getsource` reads the file, so this works under `-OO` too, where a
        docstring pin cannot.
        """
        src = inspect.getsource(st)
        intake = src.split("# THE ENUMERATION of sites where caller-supplied input")[1]
        intake = intake.split("_NOT_A_SEQUENCE = (")[0]
        self.assertEqual(intake.count("[intake]"), 4, "intake rows in the first enumeration")
        self.assertEqual(intake.count("DISCHARGED"), 1, "discharged candidates")
        total = intake.count("[intake]") + intake.count("DISCHARGED")
        self.assertIn(f"found {self._WORD[total].upper()}", intake,
                      "the candidate figure disagrees with the list below it")
        self.assertIn(f"candidates and discharged {self._WORD[intake.count('DISCHARGED')].upper()}",
                      intake, "the discharge figure disagrees with the list below it")
        conv = src.split("caller-input conversion protocols")[1].split("def _shown")[0]
        converted, discharged = conv.count("[converted]"), conv.count("DISCHARGED")
        declared = conv.count("[declared]")
        self.assertEqual((converted, discharged, declared), (4, 3, 1),
                         "the conversion enumeration's rows: the third figure is `__format__`, "
                         "which had no row at all until this round although it has 111 reachable "
                         "sites -- a protocol with no row is invisible to the walker and to the "
                         "table at the same time")
        self.assertIn(f"{self._WORD[converted + discharged + declared].upper()} protocols", conv)
        self.assertIn(f"{self._WORD[converted + declared].upper()} have reachable sites", conv)
        self.assertIn(f"{self._WORD[converted].upper()} of them converted here", conv)
        self.assertIn(f"{self._WORD[declared].upper()} declared", conv)

    def test_the_open_class_channel_sentence_is_its_measured_scope(self):
        """The sentence the NEXT OWNER reads about an open finding, which makes it load-bearing.

        FINDING J, and it is an asymmetry in this very test as much as in the sentence. The sentence
        listed the in-family positions as "(`values`, `mask`, `point`, `before`/`after`,
        `param_grad`)" and the escaping ones as "the ELEMENT positions, `denominator` and
        `expected_len`", and this test asserted the six in-family ones -- so it COULD NOT NOTICE AN
        OMISSION FROM THE ESCAPE LIST. Three omissions were there:

          * `require_parameter_gradient(input_grad=...)` escapes at `isinstance(input_grad, Real)`,
            at BOTH its positions. It is an OUTER argument of a public function, which the sentence's
            own "the OUTER positions come out IN FAMILY" contradicts, and it appeared in neither
            list. Its other four hostile shapes (`__iter__`, `__getattr__`, `__float__`, `__repr__`
            raising) are all MissingGradientError, so this channel is the only one that escapes
            there -- and it is absent from `_CASES` and excused by `_NOT_A_LYING_NUMBER`, so no
            derived sweep reached it either.
          * EVERY SCALAR position escapes, not only the two named: `value`, `step`, `rtol`, `atol`,
            `zero_tol` and `min_abs_change` as well as `denominator` and `expected_len`.
          * "the ROW position" is in family for `check_finite_matrix` and NOT for
            `masked_mean_checked`, where the nestedness probe absorbs the hostile `__class__`,
            answers "not a row", and hands the object to the ELEMENT check.

        So the sentence is rewritten from a POSITION-BY-POSITION sweep: 38 driven positions, 13 in
        family and 25 escaping, identical on 3.12.4 and 3.13.5. The fix to the asymmetry is to
        ACCOUNT for all 38 instead of asserting 6 -- the (function, parameter) set is derived from
        the signatures and every pair must be in the table or excused -- while still asserting
        BEHAVIOUR for the in-family rows only. The escaping rows are asserted about nothing: the
        channel reaches every `isinstance` in this module (19, derived below) and more in its two
        importers, the fix is those owners' joint decision, and a test that pinned an escape would
        pin a defect and fail on that fix. The figure this docstring used to quote -- "~85
        `isinstance` sites across three files" -- is not reproducible: it reconciles only with a
        robustness figure that round 18 retired, so it is replaced by this module's own count,
        derived, with the other two modules' counts left to their owners rather than inherited.
        """
        import ast
        src = inspect.getsource(st)
        self.assertIn("MEASURED SCOPE at this commit", src)
        self.assertIn("escaping as a bare RuntimeError", src)
        self.assertNotIn("happens to absorb it at", src)     # the withdrawn, false claim
        self.assertIn("it is NOT closed", src)
        # this module's own isinstance count, derived over EVERY scope and quoted in the sentence
        sites = [n for n in ast.walk(ast.parse(src)) if isinstance(n, ast.Call)
                 and isinstance(n.func, ast.Name) and n.func.id == "isinstance"]
        self.assertEqual(len(sites), 19, "the isinstance sites in this module")
        self.assertIn(f"({len(sites)} of them, derived from this file's AST over", src,
                      "the sentence must quote this module's own derived count, not a sum that "
                      "silently inherits another module's retired figure")
        # EVERY parameter of the nine public functions is accounted for, in one table or the other
        params = {(n, p) for n in _CASES for p in inspect.signature(getattr(st, n)).parameters}
        covered = {(f, p) for f, p, _k, _v, _c in _CLASS_CHANNEL_POSITIONS}
        self.assertEqual(params - covered, set(_NOT_A_CLASS_CHANNEL_POSITION),
                         "a public parameter is in neither _CLASS_CHANNEL_POSITIONS nor "
                         "_NOT_A_CLASS_CHANNEL_POSITION: that is how input_grad came to be missing "
                         "from BOTH halves of the sentence while this test stayed green")
        for key in _NOT_A_CLASS_CHANNEL_POSITION:
            self.assertIn(key, params, f"{key} is excused but no longer exists")
        self.assertEqual(len(_CLASS_CHANNEL_POSITIONS), 38, "the driven positions")
        verdicts = [v for _f, _p, _k, v, _c in _CLASS_CHANNEL_POSITIONS]
        self.assertEqual((verdicts.count(_IN_FAMILY), verdicts.count(_ESCAPES)), (13, 25),
                         "the measured split the sentence is written from")
        self.assertIn("13 IN FAMILY and 25 escaping", src)
        self.assertIn("38 driven positions", src)
        # and the sentence names each half's members
        in_family_half = src.split("IN FAMILY (13)")[1].split("ESCAPING (25)")[0]
        escaping_half = src.split("ESCAPING (25)")[1].split("_NOT_A_SEQUENCE = (")[0]
        # The two kinds the sentence enumerates BY PARAMETER NAME are the outer and the scalar ones;
        # the row, element and return-value kinds it describes as classes, in prose, and they are
        # checked by the split figures above rather than by name. `input_grad` is the row this makes
        # fail if it is dropped from the escape list again.
        for f, p, kind, verdict, _call in _CLASS_CHANNEL_POSITIONS:
            if kind not in ("outer", "scalar"):
                continue
            half = in_family_half if verdict == _IN_FAMILY else escaping_half
            with self.subTest(sentence_names=(f, p, kind)):
                self.assertIn(f"`{p}`", half,
                              f"{f}({p}=...) at its {kind} position is measured {verdict!r} and "
                              f"the sentence's {verdict!r} list does not name it")
        # BEHAVIOUR: asserted for the 13 in family, and for nothing else.
        for f, p, kind, verdict, call in _CLASS_CHANNEL_POSITIONS:
            if verdict != _IN_FAMILY:
                continue
            with self.subTest(in_family_at=(f, p, kind)):
                with self.assertRaises(st.StabilityError):
                    call(_class_boom())
        # input_grad's other four shapes DO come out in family, which is the contrast that makes the
        # `__class__` channel the only escape there. This half is a behaviour claim, so it is pinned.
        for label, make in (_BROKEN_ITER_OTHER[:1] + _BROKEN_GETATTR[:1] + _BROKEN_FLOAT[:1]
                            + (("__repr__ raises RuntimeError", _repr_raises(RuntimeError)),)):
            for where, call in (("outer", lambda o: st.require_parameter_gradient(None, input_grad=o)),
                                ("element", lambda o: st.require_parameter_gradient(None, input_grad=[o]))):
                with self.subTest(input_grad=label, at=where):
                    with self.assertRaises(st.MissingGradientError):
                        call(make())

    def test_the_only_skip_in_this_file_is_the_counted_numpy_one(self):
        """NOTE E's principle versus the one real `@unittest.skipIf` in this file, reconciled.

        The hazard Note E names is a guard that can skip a pin whose SUBJECT STILL EXISTS: under
        `-OO` every behaviour is still assertable, so skipping there hides a pin and reports OK.
        `test_numpy_scalars_rejected` is the other case -- without numpy there is no `np.bool_` or
        `np.int64` to hand `check_mask`, so there is nothing to assert, and the alternatives are a
        skip or a silently vacuous pass. The skip is the better one because it is COUNTED:
        `scripts/test_baseline.txt` records exactly one bare-environment skip for this module and
        `scripts/run_tests.sh` fails a bare run reporting fewer. The hazard is an UNCOUNTED skip,
        so what this test pins is that this stays the only skip in the file, and that no test
        skips itself from inside -- either would change the counted figure or hide a pin.
        """
        import ast
        src = inspect.getsource(sys.modules[__name__])
        tree = ast.parse(src)
        decorated = [(n.name, ast.unparse(d)) for n in ast.walk(tree)
                     if isinstance(n, ast.FunctionDef) for d in n.decorator_list
                     if "skip" in ast.unparse(d)]
        self.assertEqual(len(decorated), 1, f"skip decorators in this file: {decorated}")
        self.assertEqual(decorated[0][0], "test_numpy_scalars_rejected")
        self.assertIn("np is None", decorated[0][1])
        self.assertIn("numpy not installed", decorated[0][1])
        inline = [n for n in ast.walk(tree) if isinstance(n, ast.Call)
                  and isinstance(n.func, ast.Attribute) and n.func.attr in ("skipTest", "skip")]
        self.assertEqual(inline, [], "a test that skips itself is an uncounted skip")
        # Every OTHER numpy-dependent assertion is behind a plain `if`, which cannot skip. DERIVED
        # from the AST, not counted in the text: this was
        # `assertEqual(src.count("if np is not None:"), 2)` -- a SELF-COUNT, of whose two hits ONE
        # WAS THIS ASSERTION'S OWN STRING LITERAL, so it described one real guard as two. It also
        # could not see a THIRD numpy guard that existed, spelled `if _np is not None:` behind a
        # function-local `import numpy as _np`, which made the comment at NOTE E inaccurate AS TO
        # SPELLING. An `ast.If` test cannot be a string literal and cannot be respelled past this.
        import re as _re
        np_guards = [ast.unparse(n.test) for n in ast.walk(tree)
                     if isinstance(n, ast.If) and _re.search(r"\b[A-Za-z_]*np\b", ast.unparse(n.test))]
        self.assertEqual(np_guards, ["np is not None"] * 3,
                         "a numpy-dependent guard in this file is spelled some other way, so it is "
                         "counted by nothing: use the module-level `np`")
        # DERIVED, not counted in the text: `src.count("import numpy as ")` would be a self-count
        # again -- it matches this file's own prose about the defect it describes.
        np_imports = [ast.unparse(n) for n in ast.walk(tree)
                      if isinstance(n, (ast.Import, ast.ImportFrom)) and "numpy" in ast.unparse(n)]
        self.assertEqual(np_imports, ["import numpy as np"],
                         "numpy is imported once, at module level, so every guard reads the same name")

    def test_e_the_docstring_guard_is_inert_in_a_normal_run(self):
        """NOTE E. `python -OO` strips docstrings, so `inspect.cleandoc(None)` raised
        `AttributeError: 'NoneType' object has no attribute 'expandtabs'` and five pins came out as
        ERRORS: Ran 72, FAILED (errors=5) on BOTH 3.12.4 and 3.13.5 (test_d1_, test_d2_, test_d3_,
        test_negative_zero_claim_scope, test_small_scale_blind_spot_is_real_and_documented). That
        is SYMMETRIC across interpreters, so not the asymmetric class that got this module
        unmarked, and `-OO` is not a mode this project runs.

        Chosen guard: `_doc()` returning None plus a plain `if` at each doc assertion -- NOT
        `skipUnless`. A guard that can SKIP is the hazard the brief named: one firing in the mode
        the project DOES run would hide a pin and report OK. This shape cannot skip anything in any
        mode, and it drops only the doc half of a pin while every BEHAVIOURAL assertion keeps
        running, including under `-OO`. This test asserts the guard is inert whenever docstrings
        exist, which is every run this project makes.
        """
        self.assertEqual(st.__doc__ is not None, sys.flags.optimize < 2)
        for obj in (st, st.check_gradient, st.check_finite_scalar, st.masked_mean_checked,
                    st.check_mask, st.check_finite_sequence, st._same, st._plain_real,
                    st.GradientCheckReport, LoadBearingSentences):
            with self.subTest(obj=getattr(obj, "__name__", obj)):
                self.assertIs(_doc(obj) is None, sys.flags.optimize >= 2)
        if sys.flags.optimize < 2:
            self.assertIn("Exception design", _doc(st))
            self.assertIn("Rejected before comparing", _doc(st.check_gradient))
        # THE SECOND WAY A DOCSTRING CAN BE ABSENT, which a None check cannot see: `@dataclass`
        # SUBSTITUTES its synthesised signature for a stripped class docstring, so under `-OO`
        # `GradientCheckReport.__doc__` is PRESENT AND WRONG. `GradientCheckReport` was absent from
        # the object list above, which is the only reason the `assertIs(... is None, optimize >= 2)`
        # line was green; it is in the list now, and `_doc` reconstructs the substitution with the
        # expression `dataclasses` itself evaluates so that a change THERE fails loudly here
        # instead of silently suppressing a real docstring.
        report = st.GradientCheckReport
        klasses = [o for o in vars(st).values()
                   if isinstance(o, type) and getattr(o, "__module__", None) == st.__name__]
        self.assertEqual(len(klasses), 14, "14 classes at HEAD")
        self.assertEqual([c.__name__ for c in klasses if dataclasses.is_dataclass(c)],
                         ["GradientCheckReport"], "the module's only dataclass")
        self.assertIsNotNone(report.__doc__, "__doc__ is never None here: stripped, it is substituted")
        self.assertIs(report.__doc__ == _dataclass_signature_doc(report), sys.flags.optimize >= 2)
        if sys.flags.optimize >= 2:
            self.assertEqual([c.__name__ for c in klasses if c.__doc__ is not None],
                             ["GradientCheckReport"],
                             "the only class whose __doc__ survives -OO, by substitution")
            self.assertIn("analytic:", report.__doc__)       # the signature, not the docstring
        else:
            self.assertIn("Returned only when the check PASSES", _doc(report))

    def test_the_figures_the_docstrings_quote_are_this_interpreters_figures(self):
        """Four figures `stability.py` quotes as measurements, asserted where each is claimed.

        An independent attester verified all four, so they are PINNED here rather than re-derived:
        a figure nobody asserts is a figure that drifts.

          * `_distinct_values`: "that spelling fails `test_underflow_to_zero_raises` twice" --
            exactly 2 of that test's 5 subTests, and BOTH are the `Fraction(1, 10**400)`
            positions, which is the property the sentence is really about.
          * `_distinct_values`: `Fraction(np.float32(1e-40))` raises TypeError, so the float
            fallback is what keeps a numpy pair in family. Measured on numpy 1.26.4, 2.4.4
            and 2.4.6.
          * `_plain_real`: `int(L(1)) == 2` while `int.__int__(L(1)) == 1` -- the whole reason the
            dunder is called directly.
          * the one-shot sweep: `_plain_real` is the IDENTITY on `iter()`, a generator expression
            and `map()`, which is why a collapse-only parameter boundary would leave F2 open on
            those three routes and HEAD's per-site treatment is what reaches them.
        """
        from fractions import Fraction
        pairs = ((1e-200, 0.0), (0.0, 1e-200), (Fraction(1, 10 ** 400), 0.0),
                 (0.0, Fraction(1, 10 ** 400)), (1e-170, -1e-170))
        lost = [(p, t) for p, t in pairs if float(p) == float(t)]
        self.assertEqual(len(lost), 2, "the docstring says that spelling fails twice")
        self.assertEqual([isinstance(p, Fraction) or isinstance(t, Fraction) for p, t in lost],
                         [True, True], "both losses are the exact-tiny-Fraction positions")
        for p, t in pairs:                                  # and HEAD refuses all five
            with self.subTest(pred=repr(p)[:24]):
                with self.assertRaises(st.UnderflowError):
                    st.masked_squared_error_mean([p], [t], [True], 1)
        if np is not None:                                  # a plain `if`, never a skip
            with self.assertRaises(TypeError):
                Fraction(np.float32(1e-40))
            self.assertAlmostEqual(
                st.masked_squared_error_mean([np.float32(1e-40)], [np.float32(0.0)], [True], 1),
                1e-80, delta=1e-81)
        L = type("L", (int,), {"__int__": lambda s: 2})
        self.assertEqual(int(L(1)), 2)
        self.assertEqual(int.__int__(L(1)), 1)
        self.assertEqual(st._plain_real(L(1)), 1)
        for label, obj in (("iter", iter([1.0])), ("genexp", (x for x in [1.0])),
                           ("map", map(float, [1.0]))):
            with self.subTest(route=label):
                self.assertIs(st._plain_real(obj), obj)

    def test_the_test_count_is_deliberately_not_asserted_here(self):
        """The suite's own test count appears in neither source file; it lives in
        `scripts/test_baseline.txt`, which the orchestrator owns and regenerates.

        Left that way DELIBERATELY, stated rather than overlooked: asserting the count inside the
        file whose contents determine it creates a second source of truth that drifts on every
        legitimate addition, and the baseline file already fails a run that loses tests. What this
        test does assert is the property the count was standing in for -- that no test class here
        is empty and every one is collected -- which is what a dropped case would actually break.

        AND THIS DOCSTRING NOW QUOTES NO FIGURE AT ALL, by construction and by the assertion below.
        It used to carry a parenthetical count "before this round" that was STALE BY TWO ROUNDS --
        derived over history, the suite went from fifty-seven to seventy-two, stayed, rose to
        eighty-four, then to its present size, so the parenthetical named a figure two rounds old --
        and it did so in the test whose entire subject is that count, which makes it the latest
        instance of this project's recurring figure-in-prose defect. The deliberate NON-assertion
        of the count is settled and correct; it was the history written beside it that rotted. So
        the parenthetical is gone, and no digit may appear here.
        """
        doc = _doc(self.test_the_test_count_is_deliberately_not_asserted_here)
        if doc is not None:
            self.assertEqual([c for c in doc if c.isdigit()], [],
                             "this docstring quotes a figure about the suite's own size, which is "
                             "the one thing it exists to say nobody should write down")
        classes = [o for o in globals().values()
                   if isinstance(o, type) and issubclass(o, unittest.TestCase)]
        self.assertGreaterEqual(len(classes), 10)
        for c in classes:
            tests = [n for n in dir(c) if n.startswith("test")]
            with self.subTest(cls=c.__name__):
                self.assertGreater(len(tests), 0, f"{c.__name__} contains no tests")


class LoadBearingSentences(unittest.TestCase):
    """Eight passages that were wider than their mechanism, each pinned to its own passage, plus
    one withdrawn sentence pinned ABSENT.

    Both figures are ASSERTED, not merely written: `FiguresAndDocPinInventory` re-derives them
    from this class and fails when the words here and the class disagree. The figure used to read
    "Three sentences", which was wrong and tied to nothing -- there were 3 `D` constants but 4
    cleandoc'd `assertIn` pins (D1, D2, D3 and "Rejected before comparing") plus 1 `assertNotIn`.

    Each test asserts the exact narrowed passage AND the behaviour it claims, so a doc-only edit to
    that passage fails this test (verified by mutating each passage and watching it fail), and so does
    a code-only regression. The passages are quoted in full rather than by keyword: a keyword pin in
    this project was itself found evadable by rewording around it.

    FINDING K, which was a violation of that last sentence by this class itself. Re-running the
    settled pins against the file, all seven `D` passages DIED on a relative-indent mutant on both
    interpreters -- and the EIGHTH `assertIn`, `"Rejected before comparing (none counts as evidence
    of a working gradient)"`, was UNKILLED by all three suites on both interpreters, because it was
    a single-line needle with no leading whitespace: `cleandoc` re-renders the line with four extra
    spaces and `assertIn` still finds it. It was the one keyword pin here and it was the weak one.
    It is D8 now, the whole "Rejected before comparing" block, and it dies on the same mutant its
    siblings die on.

    D8 is spelled with a LEADING NEWLINE inside `cleandoc` rather than flush like D1 and D7,
    because its bullet list has to keep its relative indentation: `cleandoc` strips the common
    margin of every line after the first, so a flush first line would make the bullets -- the
    least-indented of the remaining lines -- come out at column zero and never match the module's
    two-space rendering. D6 is spelled the same way, for the same reason."""

    # FINDING H: the headline was falsified by the one operand a caller's CALLABLE fills, and the
    # three PASS reports measured there were an overridden `__eq__` talking a guard out of raising --
    # the exact thing this sentence says cannot happen. The passage now states the second rule that
    # makes it true at that operand, and quotes the 30-cell measurement.
    D1 = inspect.cleandoc("""Nothing in
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
UNDETECTED; with it, 30 of 30 are refused in family.""")
    D1_WITHDRAWN = "warns, returns a sentinel, or returns a number computed from bad"
    D2 = inspect.cleandoc("""The mismatch check and the division both use
    `_plain_real(denominator)`, the int the object STORES, so an `int` subclass
    whose `__eq__`/`__ne__`/`__int__` is overridden cannot carry a divisor past
    this check""")
    D3 = inspect.cleandoc("""`step`, `rtol`, `atol` and `zero_tol` are normalised to plain floats ONCE, immediately after
    validation, and every use below is of those floats""")
    # FINDING K: promoted from the one keyword `assertIn` in this class, which was also the only
    # one of the eight that a relative-indent mutant did not kill.
    D8 = inspect.cleandoc("""
    Rejected before comparing (none counts as evidence of a working gradient):
      * analytic gradient with any NaN/inf (NonFiniteError),
      * analytic gradient with max |g_i| <= zero_tol, default exactly zero
        (DegenerateGradientError): a zero gradient matches a flat function and
        also a severed gradient path, so agreement proves nothing. Choose a
        point where the true gradient is nonzero. A genuinely tiny gradient is
        not "zero" unless you raise zero_tol above it.
      * non-finite fn values during differencing (NonFiniteError).""")
    D4 = inspect.cleandoc("""`sum()` is used for accumulation elsewhere in this module and relies on
    CPython 3.12+ compensated float summation (sum([1e16, 1.0, -1e16]) is
    1.0 there, not 0.0); masked means can differ in the last bits on
    older Pythons.""")
    # FINDING G1: the carve-out, narrowed to the eagerly-raised case and with the lazy case named.
    # The previous wording ended "and it covers nothing else", which a lazy `grad_fn` falsified.
    D5 = inspect.cleandoc("""Other behaviour: an exception the caller's `fn`/`grad_fn` raises WHILE THIS
    MODULE CALLS IT (e.g. ZeroDivisionError) propagates unwrapped; it is not a
    StabilityError. That carve-out is about CALLABLES this module INVOKES, and
    it reaches the call itself and nothing else -- in particular it does NOT
    reach a LAZY return value.""")
    # FINDING G1: the cost of the widening, which was written nowhere.
    D6 = inspect.cleandoc("""
    A caller running `except ValueError: skip_batch()` now ABSORBS an exception of its own
    making -- a `ZeroDivisionError` in the generator it passed as `values`, say -- as a shape
    complaint about that argument, and carries on. That is a real loss: an unrelated caller bug
    becomes an expected-and-handled condition.""")
    # FINDING G2: lying versus raising, the distinction the old exclusion did not make.
    D7 = inspect.cleandoc("""TAKEN AT ITS WORD IS ABOUT LYING, NOT ABOUT RAISING: a
conversion protocol that RAISES produces no value to take at anyone's word, so
it is a failed READ of a data argument and is converted to this module's family
(NonNumericError, with the original chained) rather than escaping it""")

    def test_d1_module_headline_matches_its_mechanism(self):
        doc = _doc(st)
        if doc is not None:
            self.assertIn(self.D1, doc)
            self.assertNotIn(self.D1_WITHDRAWN, doc,
                             "the withdrawn, wider sentence is back: it was violated three ways (F1/F2/F3)")
        # the mechanism, exercised: `_plain_real` reads what the object stores, and bool is not laundered
        self.assertIs(type(st._plain_real(_liar(2.5))), float)
        self.assertEqual(st._plain_real(_liar(2.5)), 2.5)
        self.assertIs(type(st._plain_real(_liar(7))), int)
        self.assertEqual(st._plain_real(_liar(7)), 7)
        self.assertIs(st._plain_real(True), True)
        self.assertIs(type(st._plain_real(True)), bool)
        self.assertEqual(st._plain_real(type("IntLie", (int,), {"__int__": lambda s: 2})(1)), 1)
        # and the three guards the headline used to overclaim about
        with self.assertRaises(st.NormalizationMismatchError):
            st.masked_mean_checked([[1.0, 3.0], [9.0, 9.0]], [True, False], _liar(1))
        with self.assertRaises(st.UnderflowError):
            st.masked_squared_error_mean([_liar(1e-200)], [0.0], [True], 1)
        with self.assertRaises(st.DegenerateGradientError):
            st.check_gradient(lambda p: 1.0, lambda p: [0.0], [1.0], zero_tol=_liar(0.0))

    def test_d2_divisor_claim_matches_its_guard(self):
        doc = _doc(st.masked_mean_checked)
        if doc is not None:
            self.assertIn(self.D2, doc)
        m = [[1.0, 3.0], [9.0, 9.0]]
        self.assertEqual(st.masked_mean_checked(m, [True, False], 2), 2.0)
        for d in (1, _liar(1), _liar(8)):
            with self.subTest(d=repr(d)):
                with self.assertRaisesRegex(st.NormalizationMismatchError, "summed element count"):
                    st.masked_mean_checked(m, [True, False], d)

    def test_d3_rejected_before_comparing_claim_matches_its_guard(self):
        doc = _doc(st.check_gradient)
        if doc is not None:
            self.assertIn(self.D3, doc)
            self.assertIn(self.D8, doc)       # FINDING K: was a single-line keyword needle
        with self.assertRaises(st.DegenerateGradientError):
            st.check_gradient(_F_FLAT, _G_ZERO, [1.0, 2.0], zero_tol=_liar(0.0))
        r = st.check_gradient(_F_QUAD, _G_QUAD, [1.0, 2.0], step=_liar(1e-6), rtol=_liar(1e-4),
                              atol=_liar(1e-6), zero_tol=_liar(0.0))
        self.assertEqual(r, st.check_gradient(_F_QUAD, _G_QUAD, [1.0, 2.0]))
        self.assertEqual((type(r.step), type(r.rtol), type(r.atol)), (float, float, float))

    def test_d5_the_carve_out_covers_the_call_and_not_a_lazy_return_value(self):
        """The passage, plus both halves of the behaviour it now describes: eager raises propagate
        unwrapped, a lazy producer's body is a data read and is converted."""
        doc = _doc(st.check_gradient)
        if doc is not None:
            self.assertIn(self.D5, doc)
            self.assertNotIn("INVOKE, and it covers nothing else", doc,
                             "the wider sentence is back: a lazy grad_fn falsifies it")
        with self.assertRaises(ZeroDivisionError):               # the call itself
            st.check_gradient(_F_QUAD, lambda p: 1 / 0, [1.0, 2.0])

        def lazy_bad(p):
            yield 2.0 * p[0]
            raise ZeroDivisionError("the caller's own grad_fn body")
        with self.assertRaises(st.ShapeError):                   # the returned DATA
            st.check_gradient(_F_QUAD, lazy_bad, [1.0, 2.0])

        def lazy_good(p):
            yield 2.0 * p[0]
            yield 3.0
        self.assertEqual(st.check_gradient(_F_QUAD, lazy_good, [1.0, 2.0]).analytic, (2.0, 3.0))

    def test_d6_the_cost_of_converting_a_data_read_is_disclosed(self):
        """The passage, plus the cost itself: a caller's own exception absorbed by their own
        `except ValueError`, with `__cause__` as the stated mitigation."""
        doc = _doc(st._materialised)
        if doc is not None:
            self.assertIn(self.D6, doc)

        def caller_bug():
            yield 1.0
            raise ZeroDivisionError("the caller's own bug")
        with self.assertRaises(ValueError) as cm:
            st.check_finite_sequence(caller_bug())
        self.assertIsInstance(cm.exception, st.ShapeError)
        self.assertIsInstance(cm.exception.__cause__, ZeroDivisionError)

    def test_d7_lying_and_raising_conversions_are_different_claims(self):
        """The passage, plus the two directions it separates: a LYING `__float__` is still taken
        at its word, a RAISING one is a failed read and stays in family."""
        doc = _doc(st)
        if doc is not None:
            self.assertIn(self.D7, doc)
        lying = type("LyingReal", (Real,), dict(_REAL_STUBS, __float__=lambda s: 2.5))()
        self.assertEqual(st.check_finite_scalar(lying), 2.5)      # taken at its word
        for exc in _FLOAT_EXCS:
            with self.subTest(raises=exc.__name__):
                with self.assertRaises(st.NonNumericError):
                    st.check_finite_scalar(_float_raises(exc)())

    def test_d4_compensated_summation_claim_matches_its_accumulation(self):
        """The fourth passage. It was the one load-bearing figure with no pin at all, and it is a
        PORTABILITY promise across the two interpreters this module is measured on -- in the module
        that was unmarked for a two-interpreter failure. The behavioural half lives in
        `FiguresAndDocPinInventory`; this is the passage itself plus the accumulation it describes.
        """
        doc = _doc(st.check_gradient)
        if doc is not None:
            self.assertIn(self.D4, doc)
        self.assertEqual(sum([1e16, 1.0, -1e16]), 1.0)
        self.assertEqual(st.masked_mean_checked([1e16, 1.0, -1e16], [True, True, True], 3), 1.0 / 3)


if __name__ == "__main__":
    unittest.main()
