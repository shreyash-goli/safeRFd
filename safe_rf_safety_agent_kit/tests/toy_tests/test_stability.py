"""SR-06 tests: adversarial numeric cases for toy.stability. Abstract numbers only;
no biological content and no claim about any real system."""
import copy
import functools
import inspect
import math
import sys
import types
import unittest
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
_DOCSTRINGS_PRESENT = st.__doc__ is not None


def _doc(obj):
    """`inspect.cleandoc(obj.__doc__)`, or None when docstrings are stripped (`python -OO`)."""
    d = getattr(obj, "__doc__", None)
    return None if d is None else inspect.cleandoc(d)


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

    `__float__`/`__int__` are deliberately NOT overridden: `check_finite_scalar` is documented to
    return `float(value)`, so a lying conversion is a value this module is documented to take at its
    word, and a test that wrapped it would be asserting something the module never claimed. What the
    module DOES claim is the invariant asserted below: a liar that converts honestly cannot change any
    outcome, because no guard is decided by the caller's object."""
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
    ("check_gradient", "fn"): "a caller-supplied callable: its RETURN value is normalised where it is "
                              "consumed (check_finite_scalar), and the callable itself is documented as "
                              "outside any boundary here",
    ("check_gradient", "grad_fn"): "a caller-supplied callable: same reason as fn",
    ("require_parameter_gradient", "name"): "a str label in a message, not a number",
    ("require_parameter_gradient", "input_grad"): "accepted only to phrase a message and documented as "
                                                  "never evidence; it decides nothing",
    ("check_params_changed", "name"): "a str label in a message, not a number",
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
        # a Real with no exact rational reading stays INSIDE the error family (no escaping TypeError)
        try:
            import numpy as _np
        except Exception:
            _np = None
        if _np is not None:
            self.assertAlmostEqual(st.masked_squared_error_mean([_np.float32(1e-40)], [_np.float32(0.0)],
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
        """The derived sweep. Every bound argument, every element, every sub-element, every shape."""
        shapes = _BROKEN_ITER + _BROKEN_ITER_OTHER + _BROKEN_GETATTR
        swept = 0
        for name in sorted(_CASES):
            fn, sig = getattr(st, name), inspect.signature(getattr(st, name))
            for args, kwargs, why in _CASES[name]:
                b0 = sig.bind(*args, **kwargs)
                for pname, given in list(b0.arguments.items()):
                    if (name, pname) in _NOT_A_LYING_NUMBER:
                        continue        # str labels, bool flags, and the two documented callables
                    for label, make in shapes:
                        for where, variant in _with_broken(given, make):
                            b = sig.bind(*args, **kwargs)
                            b.arguments[pname] = variant
                            with self.subTest(function=name, parameter=pname, at=where, shape=label):
                                try:
                                    out = fn(*b.args, **b.kwargs)
                                except st.StabilityError:
                                    swept += 1
                                    continue
                                except BaseException as e:
                                    self.fail(f"{type(e).__name__} escaped the declared family "
                                              f"from {name}({pname}=...) at {where} with a "
                                              f"{label}: {e}")
                                self.fail(f"{name}({pname}=...) RETURNED {out!r} at {where} with "
                                          f"a {label}: an object that cannot be iterated must not "
                                          "produce a number")
        self.assertGreater(swept, 400, "the sweep collapsed to almost nothing: it is supposed to "
                                       "reach every intake position of every case")

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
        """The STRUCTURAL half: `_materialised` and `_is_row_like` are the only two places that
        probe or materialise caller-supplied input, so a fifth site cannot be HALF-fixed the way
        the third was. Derived from the module's own AST, not from a list of names.

        This project's recurring pattern is the half-fix -- `benchmark.py` had the same thing 145
        lines apart in the same round -- and the thing that makes it recur is that each site is
        spelled out by hand. This test fails if any function outside the two helpers spells the
        probe itself.
        """
        import ast
        src = inspect.getsource(st)
        offenders = []
        for fn in [n for n in ast.walk(ast.parse(src)) if isinstance(n, ast.FunctionDef)]:
            if fn.name in ("_materialised", "_is_row_like"):
                continue
            for node in ast.walk(fn):
                if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                        and node.func.id == "hasattr" and len(node.args) == 2
                        and isinstance(node.args[1], ast.Constant)
                        and node.args[1].value == "__iter__"):
                    offenders.append(f"{fn.name}() line {node.lineno}: hasattr(_, '__iter__')")
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


class FiguresAndDocPinInventory(unittest.TestCase):
    """The figures that were merely WRITTEN, asserted; and the doc-pin counts, derived."""

    _WORD = {0: "No", 1: "One", 2: "Two", 3: "Three", 4: "Four", 5: "Five", 6: "Six", 7: "Seven"}

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
        """
        passages = {k: v for k, v in vars(LoadBearingSentences).items()
                    if k.startswith("D") and isinstance(v, str)}
        withdrawn = {k for k in passages if k.endswith("_WITHDRAWN")}
        positive = {k for k in passages if k not in withdrawn}
        self.assertEqual(len(positive), 4, f"positive passages: {sorted(positive)}")
        self.assertEqual(len(withdrawn), 1, f"withdrawn passages: {sorted(withdrawn)}")
        src = inspect.getsource(LoadBearingSentences)
        self.assertEqual(src.count("assertIn("), 5, "cleandoc'd assertIn doc pins")
        self.assertEqual(src.count("assertNotIn("), 1)
        doc = _doc(LoadBearingSentences)
        if doc is not None:
            self.assertIn(f"{self._WORD[len(positive)]} passages", doc,
                          "the figure in the docstring disagrees with the class")
            self.assertIn(f"{self._WORD[len(withdrawn)].lower()} withdrawn sentence", doc)

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
        self.assertEqual(_DOCSTRINGS_PRESENT, sys.flags.optimize < 2)
        for obj in (st, st.check_gradient, st.check_finite_scalar, st.masked_mean_checked,
                    st.check_mask, st.check_finite_sequence, LoadBearingSentences):
            with self.subTest(obj=getattr(obj, "__name__", obj)):
                self.assertIs(_doc(obj) is None, sys.flags.optimize >= 2)
        if sys.flags.optimize < 2:
            self.assertIn("Exception design", _doc(st))
            self.assertIn("Rejected before comparing", _doc(st.check_gradient))

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
        """The suite's own test count (72 before this round) appears in neither source file; it
        lives in `scripts/test_baseline.txt`, which the orchestrator owns and regenerates.

        Left that way DELIBERATELY, stated rather than overlooked: asserting the count inside the
        file whose contents determine it creates a second source of truth that drifts on every
        legitimate addition, and the baseline file already fails a run that loses tests. What this
        test does assert is the property the count was standing in for -- that no test class here
        is empty and every one is collected -- which is what a dropped case would actually break.
        """
        classes = [o for o in globals().values()
                   if isinstance(o, type) and issubclass(o, unittest.TestCase)]
        self.assertGreaterEqual(len(classes), 10)
        for c in classes:
            tests = [n for n in dir(c) if n.startswith("test")]
            with self.subTest(cls=c.__name__):
                self.assertGreater(len(tests), 0, f"{c.__name__} contains no tests")


class LoadBearingSentences(unittest.TestCase):
    """Four passages that were wider than their mechanism, each pinned to its own passage, plus
    one withdrawn sentence pinned ABSENT.

    Both figures are ASSERTED, not merely written: `FiguresAndDocPinInventory` re-derives them
    from this class and fails when the words here and the class disagree. The figure used to read
    "Three sentences", which was wrong and tied to nothing -- there were 3 `D` constants but 4
    cleandoc'd `assertIn` pins (D1, D2, D3 and "Rejected before comparing") plus 1 `assertNotIn`.

    Each test asserts the exact narrowed passage AND the behaviour it claims, so a doc-only edit to
    that passage fails this test (verified by mutating each passage and watching it fail), and so does
    a code-only regression. The passages are quoted in full rather than by keyword: a keyword pin in
    this project was itself found evadable by rewording around it."""

    D1 = inspect.cleandoc("""Nothing in
this module warns or returns a sentinel, and no guard here is decided by the
caller's object: every one of them compares, and divides by, the NORMALISED
value (`_plain_real`, or the float a `check_finite_*` validator already
returned), so an overridden `__eq__`, `__ne__`, `__ge__` or `__rmul__` cannot
talk a guard out of raising.""")
    D1_WITHDRAWN = "warns, returns a sentinel, or returns a number computed from bad"
    D2 = inspect.cleandoc("""The mismatch check and the division both use
    `_plain_real(denominator)`, the int the object STORES, so an `int` subclass
    whose `__eq__`/`__ne__`/`__int__` is overridden cannot carry a divisor past
    this check""")
    D3 = inspect.cleandoc("""`step`, `rtol`, `atol` and `zero_tol` are normalised to plain floats ONCE, immediately after
    validation, and every use below is of those floats""")
    D4 = inspect.cleandoc("""`sum()` is used for accumulation elsewhere in this module and relies on
    CPython 3.12+ compensated float summation (sum([1e16, 1.0, -1e16]) is
    1.0 there, not 0.0); masked means can differ in the last bits on
    older Pythons.""")

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
            self.assertIn("Rejected before comparing (none counts as evidence of a working gradient)",
                          doc)
        with self.assertRaises(st.DegenerateGradientError):
            st.check_gradient(_F_FLAT, _G_ZERO, [1.0, 2.0], zero_tol=_liar(0.0))
        r = st.check_gradient(_F_QUAD, _G_QUAD, [1.0, 2.0], step=_liar(1e-6), rtol=_liar(1e-4),
                              atol=_liar(1e-6), zero_tol=_liar(0.0))
        self.assertEqual(r, st.check_gradient(_F_QUAD, _G_QUAD, [1.0, 2.0]))
        self.assertEqual((type(r.step), type(r.rtol), type(r.atol)), (float, float, float))

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
