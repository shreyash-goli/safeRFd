"""D3: pin CURRENT behaviour of toy.erasure_demo edge cases. TOY data only. Source is unchanged."""
import math
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from toy.erasure_demo import ToyPrediction, masked_mse, toy_target

REF = ToyPrediction((1.0, 2.0), (0.5, 1.0))


class ToyTargetEdges(unittest.TestCase):
    def test_negative_strength_raises(self):
        with self.assertRaisesRegex(ValueError, "nonnegative"):
            toy_target(REF, -0.1)

    def test_nonfinite_strength_raises(self):
        for s in (math.nan, math.inf, -math.inf):
            with self.assertRaisesRegex(ValueError, "finite"):
                toy_target(REF, s)

    def test_length_mismatch_raises(self):
        with self.assertRaisesRegex(ValueError, "same length"):
            toy_target(ToyPrediction((1.0, 2.0), (0.5,)), 1.0)

    def test_empty_reference_raises(self):
        with self.assertRaises(ValueError):
            toy_target(ToyPrediction((), ()), 1.0)


class MaskedMseEdges(unittest.TestCase):
    def test_shape_mismatch_raises(self):
        with self.assertRaisesRegex(ValueError, "shapes must match"):
            masked_mse((1.0, 2.0), (1.0,), (True, True))
        with self.assertRaisesRegex(ValueError, "shapes must match"):
            masked_mse((1.0, 2.0), (1.0, 2.0), (True,))

    def test_all_false_mask_raises(self):
        with self.assertRaisesRegex(ValueError, "empty loss mask"):
            masked_mse((1.0,), (1.0,), (False,))

    def test_nonfinite_under_true_mask_raises(self):
        with self.assertRaisesRegex(ValueError, "nonfinite"):
            masked_mse((math.nan, 1.0), (0.0, 1.0), (True, True))

    # CHANGED in SR-05 rework following QA: these tests originally PINNED lenient behaviour
    # (NaN under a False mask ignored; truthy non-bool mask entries accepted; overflow to
    # inf from finite inputs). That was more lenient than the audited source, which
    # multiplies by the mask so NaN * 0 stays NaN. erasure_demo now fails closed.
    def test_nonfinite_under_false_mask_now_raises(self):
        with self.assertRaisesRegex(ValueError, "nonfinite"):
            masked_mse((math.nan, 3.0), (0.0, 1.0), (False, True))
        with self.assertRaisesRegex(ValueError, "nonfinite"):
            masked_mse((1.0, 3.0), (math.inf, 1.0), (False, True))

    def test_non_bool_mask_entries_raise(self):
        for bad in ((0, "no"), (1, 1), (True, None), ("x", True)):
            with self.assertRaisesRegex(ValueError, "strictly bool"):
                masked_mse((1.0, 2.0), (1.0, 0.0), bad)

    def test_loss_overflow_raises(self):
        with self.assertRaisesRegex(ValueError, "overflow"):
            masked_mse((1e200,), (-1e200,), (True,))


class ToyTargetFailClosed(unittest.TestCase):
    def test_bool_strength_rejected(self):
        for s in (True, False):
            with self.assertRaisesRegex(ValueError, "bool"):
                toy_target(REF, s)

    def test_output_overflow_from_finite_inputs_raises(self):
        with self.assertRaisesRegex(ValueError, "overflow"):
            toy_target(ToyPrediction((1e308,), (-1e308,)), 10.0)

    def test_valid_case_unchanged(self):
        self.assertEqual(toy_target(ToyPrediction((3.0, 1.0), (1.0, 2.0)), 0.5), (0.0, 2.5))


if __name__ == "__main__":
    unittest.main()
