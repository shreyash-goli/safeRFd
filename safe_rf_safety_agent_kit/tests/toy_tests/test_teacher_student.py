"""SR-05 tests. TOY RESULT only: abstract numbers, no biological content, no safety claims."""
import dataclasses
import re
from datetime import datetime, timezone
import math
import random
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from toy.erasure_demo import ToyPrediction, toy_target
from toy.schema import EvidenceClass
from toy.teacher_student import (Student, erasure_target, make_inputs, make_teacher,
                                 masked_mse_loss_and_grad, train)

# Hand fixture. x=((1,2),(3,4)), params scale=(1,1), bias=(0,0) so pred == x.
# target=((0,1),(3,2)); errors = ((1,1),(0,2)); squared = ((1,1),(0,4)).
X = ((1.0, 2.0), (3.0, 4.0))
P = (1.0, 1.0, 0.0, 0.0)
T = ((0.0, 1.0), (3.0, 2.0))
TS = "2025-01-02T03:04:05Z"  # pinned so content_hash is reproducible


class Determinism(unittest.TestCase):
    def test_same_seed_identical(self):
        a, b = train(seed=3, timestamp_utc=TS), train(seed=3, timestamp_utc=TS)
        self.assertEqual(a.history, b.history)
        self.assertEqual(a.final_params, b.final_params)
        self.assertEqual(a.record.content_hash(), b.record.content_hash())

    def test_different_seed_differs(self):
        a, b = train(seed=3, timestamp_utc=TS), train(seed=4, timestamp_utc=TS)
        self.assertNotEqual(a.history, b.history)
        self.assertNotEqual(a.record.content_hash(), b.record.content_hash())

    def test_global_rng_untouched(self):
        random.seed(99)
        expected = random.random()
        random.seed(99)
        train(seed=3, timestamp_utc=TS)
        self.assertEqual(random.random(), expected)

    def test_pinned_timestamp_gives_identical_hash_and_is_verbatim(self):
        a, b = train(seed=3, timestamp_utc=TS), train(seed=3, timestamp_utc=TS)
        self.assertEqual(a.record.provenance.timestamp_utc, TS)
        self.assertEqual(a.record.content_hash(), b.record.content_hash())
        c = train(seed=3, timestamp_utc="2025-01-02T03:04:06Z")
        self.assertNotEqual(a.record.content_hash(), c.record.content_hash())

    def test_default_timestamp_is_real_now(self):
        ts = train(seed=3).record.provenance.timestamp_utc
        self.assertRegex(ts, r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
        parsed = datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ")
        self.assertGreaterEqual(parsed.year, 2025)
        self.assertNotEqual(ts, "1970-01-01T00:00:00Z")
        self.assertLess(abs((datetime.now(timezone.utc).replace(tzinfo=None) - parsed).total_seconds()), 120)

    def test_record_is_toy_result(self):
        r = train(seed=3, timestamp_utc=TS).record
        self.assertEqual(r.evidence_class, EvidenceClass.TOY_RESULT)
        self.assertTrue(r.provenance.toy_only)
        self.assertIn("TOY RESULT", r.to_dict()["label"])
        self.assertIn("TOY RESULT", r.notes)


class FrozenTeacher(unittest.TestCase):
    def test_mutation_raises(self):
        t = make_teacher(1)
        with self.assertRaises(TypeError):
            t.params["cond_scale"] = (9.0, 9.0, 9.0)
        with self.assertRaises(dataclasses.FrozenInstanceError):
            t.params = {}
        with self.assertRaises(TypeError):
            t.params["cond_scale"][0] = 9.0  # tuple is immutable

    def test_outputs_unchanged_by_training(self):
        res = train(seed=5, steps=100, timestamp_utc=TS)
        self.assertEqual(res.teacher_before, res.teacher_after)
        t = make_teacher(5)
        x = make_inputs(5)
        self.assertEqual(t.outputs(x), res.teacher_before)
        # actual values are nontrivial and equal after a second call
        self.assertNotEqual(res.teacher_before.conditioned, res.teacher_before.unconditioned)
        self.assertEqual(t.outputs(x).conditioned, res.teacher_after.conditioned)

    def test_param_copy_is_isolated_from_input(self):
        src = {"cond_scale": [1.0], "cond_bias": [0.0], "uncond_scale": [1.0], "uncond_bias": [0.0]}
        from toy.teacher_student import Teacher
        t = Teacher(src)
        src["cond_scale"][0] = 7.0
        self.assertEqual(t.params["cond_scale"], (1.0,))


class MutableStudent(unittest.TestCase):
    def test_params_change_and_loss_decreases(self):
        res = train(seed=2, steps=200, lr=0.05)
        # student init is reproduced via a 0-step run
        start = train(seed=2, steps=0).final_params
        self.assertNotEqual(start, res.final_params)
        losses = [h[1] for h in res.history]
        # Linear student, linear targets, convex quadratic loss, small lr => monotone decrease.
        self.assertTrue(all(b <= a for a, b in zip(losses, losses[1:])))
        self.assertLess(losses[-1], losses[0] * 0.5)

    def test_step_is_in_place_gd(self):
        s = Student([1.0, 2.0])
        s.step((0.5, -1.0), 0.1)
        self.assertEqual(s.params, [1.0 - 0.05, 2.0 + 0.1])

    def test_nonfinite_lr_raises(self):
        for lr in (math.nan, math.inf, -math.inf):
            with self.assertRaisesRegex(ValueError, "finite"):
                train(seed=1, lr=lr)
            with self.assertRaisesRegex(ValueError, "finite"):
                Student([0.0, 0.0]).step((0.0, 0.0), lr)

    def test_nonpositive_lr_raises(self):
        for lr in (-0.05, -1e-12, 0.0, 0):
            with self.assertRaisesRegex(ValueError, "strictly positive"):
                train(seed=1, lr=lr)
            with self.assertRaisesRegex(ValueError, "strictly positive"):
                Student([0.0, 0.0]).step((0.0, 0.0), lr)

    def test_default_settings_loss_monotone_nonincreasing(self):
        # Regression guard against a sign error (negative lr would make loss rise).
        losses = [h[1] for h in train(seed=2, timestamp_utc=TS).history]
        self.assertTrue(all(b <= a for a, b in zip(losses, losses[1:])), losses)
        self.assertLess(losses[-1], losses[0])


class Target(unittest.TestCase):
    def test_matches_erasure_demo(self):
        rng = random.Random(11)
        for _ in range(20):
            c = tuple(rng.uniform(-3, 3) for _ in range(5))
            u = tuple(rng.uniform(-3, 3) for _ in range(5))
            eta = rng.uniform(0, 4)
            demo = toy_target(ToyPrediction(c, u), eta)
            ours = erasure_target((c,), (u,), eta)
            self.assertEqual(ours, (demo,))  # bit-identical

    def test_eta_zero_is_uncond(self):
        c, u = ((1.5, -2.0),), ((0.25, 4.0),)
        self.assertEqual(erasure_target(c, u, 0.0), u)

    def test_eta_validation(self):
        c = ((1.0,),)
        for eta in (-0.1, math.nan, math.inf):
            with self.assertRaisesRegex(ValueError, "eta"):
                erasure_target(c, c, eta)


class Rescale(unittest.TestCase):
    def norm(self, m):
        return math.sqrt(sum(v * v for r in m for v in r))

    def test_off_by_default(self):
        c, u = ((0.0, 0.0),), ((3.0, 4.0),)
        self.assertEqual(erasure_target(c, u, 1.0), ((6.0, 8.0),))  # unscaled: u - (c-u) = 2u

    def test_on_moves_toward_uncond_norm(self):
        c, u = ((0.0, 0.0),), ((3.0, 4.0),)  # target 2u, norm 10 vs uncond norm 5; s = 0.5
        t = erasure_target(c, u, 1.0, rescale=True)
        self.assertAlmostEqual(t[0][0], 3.0, places=6)
        self.assertAlmostEqual(t[0][1], 4.0, places=6)
        self.assertLess(abs(self.norm(t) - 5.0), abs(10.0 - 5.0))

    def test_clamp_upper(self):
        # eta=0.99: target = (0.03, 0.04), norm 0.05, raw s = 100 -> clamped to 2.0
        t = erasure_target(((6.0, 8.0),), ((3.0, 4.0),), 0.99, rescale=True)
        self.assertAlmostEqual(t[0][0], 0.06, places=9)
        self.assertAlmostEqual(t[0][1], 0.08, places=9)

    def test_clamp_lower(self):
        # eta=10: target = 11u, norm 55, raw s = 5/55 ~ 0.0909 -> clamped to 0.1
        t = erasure_target(((0.0, 0.0),), ((3.0, 4.0),), 10.0, rescale=True)
        self.assertAlmostEqual(t[0][0], 3.3, places=9)
        self.assertAlmostEqual(t[0][1], 4.4, places=9)

    def test_train_flag_changes_result(self):
        self.assertNotEqual(train(seed=1, rescale=True, eta=2.0).history, train(seed=1, eta=2.0).history)


class Normalization(unittest.TestCase):
    def test_hand_computed_values(self):
        # Full mask (True, True): sse = 1+1+0+4 = 6.
        #   per_masked_element = 6 / (mask_sum 2 * width 2) = 1.5
        #   per_mask_entry     = 6 / mask_sum 2            = 3.0   (ratio = width = 2)
        l1, _ = masked_mse_loss_and_grad(P, X, T, (True, True))
        l2, _ = masked_mse_loss_and_grad(P, X, T, (True, True), "per_mask_entry")
        self.assertEqual(l1, 1.5)
        self.assertEqual(l2, 3.0)
        # Mask (True, False): sse = 1+1 = 2.  per_masked_element = 2/(1*2) = 1.0; per_mask_entry = 2/1 = 2.0
        m1, _ = masked_mse_loss_and_grad(P, X, T, (True, False))
        m2, _ = masked_mse_loss_and_grad(P, X, T, (True, False), "per_mask_entry")
        self.assertEqual((m1, m2), (1.0, 2.0))

    def test_ratio_is_exactly_row_width_and_gradient_too(self):
        for width in (1, 2, 3, 5):
            x = make_inputs(1, rows=3, width=width)
            t = make_inputs(2, rows=3, width=width)
            p = tuple(0.1 * i for i in range(2 * width))
            a, ga = masked_mse_loss_and_grad(p, x, t, (True, False, True))
            b, gb = masked_mse_loss_and_grad(p, x, t, (True, False, True), "per_mask_entry")
            self.assertAlmostEqual(b / a, width, places=12)
            for u, v in zip(ga, gb):
                self.assertAlmostEqual(v, u * width, places=12)

    def test_default_is_correct_count(self):
        self.assertEqual(masked_mse_loss_and_grad(P, X, T, (True, True))[0], 1.5)

    def test_unknown_normalization_raises(self):
        with self.assertRaisesRegex(ValueError, "normalization"):
            masked_mse_loss_and_grad(P, X, T, (True, True), "mean")

    def test_masked_out_row_does_not_contribute(self):
        t2 = ((0.0, 1.0), (100.0, -100.0))
        a = masked_mse_loss_and_grad(P, X, T, (True, False))
        b = masked_mse_loss_and_grad(P, X, t2, (True, False))
        self.assertEqual(a, b)


class Validation(unittest.TestCase):
    def test_all_false_mask_raises(self):
        with self.assertRaisesRegex(ValueError, "empty mask"):
            masked_mse_loss_and_grad(P, X, T, (False, False))
        with self.assertRaisesRegex(ValueError, "empty mask"):
            train(seed=1, mask=(False,) * 4)

    def test_mask_wrong_length_raises(self):
        with self.assertRaisesRegex(ValueError, "one entry per row"):
            masked_mse_loss_and_grad(P, X, T, (True,))

    def test_ragged_raises(self):
        with self.assertRaisesRegex(ValueError, "ragged"):
            masked_mse_loss_and_grad(P, ((1.0, 2.0), (3.0,)), T, (True, True))
        with self.assertRaisesRegex(ValueError, "ragged"):
            erasure_target(((1.0, 2.0), (3.0,)), ((1.0, 2.0), (3.0, 4.0)), 1.0)

    def test_shape_mismatch_raises(self):
        with self.assertRaisesRegex(ValueError, "shape mismatch"):
            erasure_target(((1.0, 2.0),), ((1.0, 2.0), (3.0, 4.0)), 1.0)
        with self.assertRaisesRegex(ValueError, "shape mismatch"):
            masked_mse_loss_and_grad(P, X, ((0.0, 1.0),), (True, True))

    def test_nonfinite_raises(self):
        for bad in (math.nan, math.inf, -math.inf):
            with self.assertRaisesRegex(ValueError, "non-finite"):
                masked_mse_loss_and_grad(P, ((bad, 1.0), (3.0, 4.0)), T, (True, True))
            with self.assertRaisesRegex(ValueError, "non-finite"):
                masked_mse_loss_and_grad(P, X, ((bad, 1.0), (3.0, 2.0)), (True, True))
            with self.assertRaisesRegex(ValueError, "non-finite"):
                erasure_target(((bad,),), ((1.0,),), 1.0)
            with self.assertRaisesRegex(ValueError, "finite"):
                masked_mse_loss_and_grad((bad, 1.0, 0.0, 0.0), X, T, (True, True))

    def test_empty_raises(self):
        with self.assertRaises(ValueError):
            erasure_target((), (), 1.0)
        with self.assertRaises(ValueError):
            erasure_target(((),), ((),), 1.0)


class Gradient(unittest.TestCase):
    def test_matches_central_difference(self):
        x = make_inputs(7, rows=4, width=3)
        t = make_inputs(8, rows=4, width=3)
        mask = (True, False, True, True)
        p = [0.3, -0.2, 0.7, 0.1, 0.0, -0.4]
        for norm in ("per_masked_element", "per_mask_entry"):
            _, g = masked_mse_loss_and_grad(p, x, t, mask, norm)
            h = 1e-6
            for i in range(len(p)):
                up, dn = list(p), list(p)
                up[i] += h
                dn[i] -= h
                fd = (masked_mse_loss_and_grad(up, x, t, mask, norm)[0]
                      - masked_mse_loss_and_grad(dn, x, t, mask, norm)[0]) / (2 * h)
                self.assertAlmostEqual(g[i], fd, delta=1e-7)  # quadratic loss: error ~ roundoff only


if __name__ == "__main__":
    unittest.main()
