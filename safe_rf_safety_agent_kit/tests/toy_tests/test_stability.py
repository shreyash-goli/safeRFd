"""SR-06 tests: adversarial numeric cases for toy.stability. Abstract numbers only;
no biological content and no claim about any real system."""
import copy
import inspect
import math
import sys
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
        self.assertIn("100x too large", st.check_gradient.__doc__)

    # D-S2: docstring claim matches behaviour
    def test_negative_zero_claim_scope(self):
        self.assertEqual(math.copysign(1.0, st.check_finite_sequence([-0.0])[0]), -1.0)
        self.assertEqual(math.copysign(1.0, st.masked_mean_checked([-0.0], [True], 1)), 1.0)
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


class NormalisationIsDerivedNotEnumerated(unittest.TestCase):
    """The fail-closed half of the per-site fix for F1-F4.

    A per-site fix is only as good as what makes the NEXT un-normalised site fail. These tests derive
    the subject list from `inspect` -- the public functions of `toy.stability` and the parameters of
    their signatures -- so a new public function, or a new parameter on an old one, fails here until it
    is swept; and the invariant swept is the one the module docstring now claims."""

    def _public(self):
        return {n for n, o in vars(st).items()
                if inspect.isfunction(o) and not n.startswith("_") and o.__module__ == st.__name__}

    def test_every_public_function_and_parameter_is_swept_or_exempt(self):
        self.assertEqual(self._public(), set(_CASES), "a public function of toy.stability was added or "
                         "removed: give it a row in _CASES so the normalisation sweep covers it")
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
        iterables as supported input. Normalising at the site reaches both; a wrapper does not."""
        for name in sorted(_CASES):
            fn, sig = getattr(st, name), inspect.signature(getattr(st, name))
            for args, kwargs, why in _CASES[name]:
                b0 = sig.bind(*args, **kwargs)
                honest = _outcome(lambda: fn(*b0.args, **b0.kwargs))
                for pname, given in list(b0.arguments.items()):
                    if (name, pname) in _NOT_A_LYING_NUMBER or not isinstance(given, (list, tuple)):
                        continue
                    b = sig.bind(*args, **kwargs)
                    b.arguments[pname] = iter(_liars_in(given))
                    with self.subTest(function=name, parameter=pname, case=why):
                        got = _outcome(lambda: fn(*b.args, **b.kwargs))
                        self.assertEqual(got, honest, f"{name}({pname}=iter(<liars>)) diverged: {why}")


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
                try:
                    report = st.check_gradient(_F_QUAD, _G_QUAD, [1.0, 2.0], step=step)
                except st.StabilityError:
                    continue                      # refusing is in family and acceptable
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
        call, so a broken `__iter__` escaped as TypeError from one and ShapeError from the other."""
        for bad in (type("BadIter", (), {"__iter__": 5})(),
                    type("RaiseIter", (), {"__iter__": lambda s: (_ for _ in ()).throw(TypeError("x"))})()):
            with self.subTest(bad=type(bad).__name__):
                with self.assertRaises(st.MaskTypeError):
                    st.check_mask(bad, 2)
                with self.assertRaises(st.ShapeError):          # the sibling, unchanged
                    st.check_finite_sequence(bad)
                with self.assertRaises(st.StabilityError):      # and through the loss route
                    st.masked_mean_checked([1.0, 2.0], bad, 2)

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


class LoadBearingSentences(unittest.TestCase):
    """Three sentences that were wider than their mechanism, each pinned to its own passage.

    Each test asserts the exact narrowed passage AND the behaviour it claims, so a doc-only edit to
    that passage fails this test (verified by mutating each passage and watching it fail), and so does
    a code-only regression. The passages are quoted in full rather than by keyword: a keyword pin in
    this project was itself found evadable by rewording around it."""

    D1 = ("""Nothing in
this module warns or returns a sentinel, and no guard here is decided by the
caller's object: every one of them compares, and divides by, the NORMALISED
value (`_plain_real`, or the float a `check_finite_*` validator already
returned), so an overridden `__eq__`, `__ne__`, `__ge__` or `__rmul__` cannot
talk a guard out of raising.""")
    D1_WITHDRAWN = "warns, returns a sentinel, or returns a number computed from bad"
    D2 = ("""The mismatch check and the division both use
    `_plain_real(denominator)`, the int the object STORES, so an `int` subclass
    whose `__eq__`/`__ne__`/`__int__` is overridden cannot carry a divisor past
    this check""")
    D3 = ("""`step`, `rtol`, `atol` and `zero_tol` are normalised to plain floats ONCE, immediately after
    validation, and every use below is of those floats""")

    def test_d1_module_headline_matches_its_mechanism(self):
        self.assertIn(self.D1, st.__doc__)
        self.assertNotIn(self.D1_WITHDRAWN, st.__doc__,
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
        self.assertIn(self.D2, st.masked_mean_checked.__doc__)
        m = [[1.0, 3.0], [9.0, 9.0]]
        self.assertEqual(st.masked_mean_checked(m, [True, False], 2), 2.0)
        for d in (1, _liar(1), _liar(8)):
            with self.subTest(d=repr(d)):
                with self.assertRaisesRegex(st.NormalizationMismatchError, "summed element count"):
                    st.masked_mean_checked(m, [True, False], d)

    def test_d3_rejected_before_comparing_claim_matches_its_guard(self):
        self.assertIn(self.D3, st.check_gradient.__doc__)
        self.assertIn("Rejected before comparing (none counts as evidence of a working gradient)",
                      st.check_gradient.__doc__)
        with self.assertRaises(st.DegenerateGradientError):
            st.check_gradient(_F_FLAT, _G_ZERO, [1.0, 2.0], zero_tol=_liar(0.0))
        r = st.check_gradient(_F_QUAD, _G_QUAD, [1.0, 2.0], step=_liar(1e-6), rtol=_liar(1e-4),
                              atol=_liar(1e-6), zero_tol=_liar(0.0))
        self.assertEqual(r, st.check_gradient(_F_QUAD, _G_QUAD, [1.0, 2.0]))
        self.assertEqual((type(r.step), type(r.rtol), type(r.atol)), (float, float, float))


if __name__ == "__main__":
    unittest.main()
