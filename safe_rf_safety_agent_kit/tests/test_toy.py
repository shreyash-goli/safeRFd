import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from toy.erasure_demo import ToyPrediction, toy_target, masked_mse

class ToyContractTests(unittest.TestCase):
    def test_deterministic_target(self):
        sample = ToyPrediction((3.0, 1.0), (1.0, 2.0))
        self.assertEqual(toy_target(sample, 0.5), (0.0, 2.5))

    def test_nonfinite_rejected(self):
        with self.assertRaises(ValueError):
            toy_target(ToyPrediction((float('nan'),), (1.0,)), 1.0)

    def test_empty_mask_rejected(self):
        with self.assertRaises(ValueError):
            masked_mse((1.,2.), (0.,0.), (False,False))

    def test_masked_loss(self):
        self.assertAlmostEqual(masked_mse((3.,9.), (1.,0.), (True,False)), 4.0)

if __name__ == "__main__":
    unittest.main()
