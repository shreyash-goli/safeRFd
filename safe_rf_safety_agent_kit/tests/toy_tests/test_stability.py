"""SR-06 tests: adversarial numeric cases for toy.stability. Abstract numbers only;
no biological content and no claim about any real system."""
import copy
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


if __name__ == "__main__":
    unittest.main()
