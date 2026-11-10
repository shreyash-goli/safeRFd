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

    def test_nonfinite_under_false_mask_is_ignored_current_behaviour(self):
        # Pins ACTUAL behaviour: masked-out elements are filtered BEFORE the finiteness
        # check, so a NaN/inf under a False mask is silently ignored.
        # Opinion: defensible for a loss (masked-out values do not enter it), but it can
        # hide an upstream NaN that later becomes unmasked; reported to the orchestrator as
        # a low-severity observation, not changed here.
        self.assertEqual(masked_mse((math.nan, 3.0), (0.0, 1.0), (False, True)), 4.0)
        self.assertEqual(masked_mse((1.0, 3.0), (math.inf, 1.0), (False, True)), 4.0)


if __name__ == "__main__":
    unittest.main()
