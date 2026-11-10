"""SR-05 tests. TOY RESULT only: abstract numbers, no biological content, no safety claims."""
import copy
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
from toy.schema import EvidenceClass, derive_seed, make_rng
from toy.teacher_student import (Student, Teacher, TeacherOutput, predict, as_matrix, erasure_target, make_inputs, make_teacher,
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
        # Explicit teacher + independent snapshot taken BEFORE training, compared AFTER.
        teacher = Teacher({"cond_scale": (2.0, 1.0), "cond_bias": (0.0, 1.0),
                           "uncond_scale": (1.0, 0.5), "uncond_bias": (0.5, 0.0)})
        x = ((1.0, 2.0), (3.0, -4.0))
        params_snap = copy.deepcopy(dict(teacher.params))
        out_snap = copy.deepcopy(teacher.outputs(x))
        # hand-computed literals: cond = x*scale+bias, uncond = x*scale+bias
        self.assertEqual(out_snap.conditioned, ((2.0, 3.0), (6.0, -3.0)))
        self.assertEqual(out_snap.unconditioned, ((1.5, 1.0), (3.5, -2.0)))
        res = train(seed=5, steps=100, x=x, teacher=teacher, timestamp_utc=TS)
        self.assertEqual(dict(teacher.params), params_snap)
        self.assertEqual(teacher.outputs(x), out_snap)
        self.assertEqual(res.teacher_before, out_snap)
        self.assertEqual(res.teacher_after, out_snap)
        self.assertNotEqual(out_snap.conditioned, out_snap.unconditioned)

    def test_param_copy_is_isolated_from_input(self):
        src = {"cond_scale": [1.0], "cond_bias": [0.0], "uncond_scale": [1.0], "uncond_bias": [0.0]}
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


class DefaultsAndInternals(unittest.TestCase):
    def test_default_normalization_is_per_masked_element(self):
        # T1: the default a caller silently gets must be the correct count.
        res = train(seed=2, timestamp_utc=TS)
        teacher, x = make_teacher(2, 3), make_inputs(2)
        out = teacher.outputs(x)
        target = erasure_target(out.conditioned, out.unconditioned, 0.5)
        rng = make_rng(derive_seed(2, "student_init"))
        p0 = [rng.uniform(-0.5, 0.5) for _ in range(6)]
        mask = (True,) * 4
        good, _ = masked_mse_loss_and_grad(p0, x, target, mask, "per_masked_element")
        bad, _ = masked_mse_loss_and_grad(p0, x, target, mask, "per_mask_entry")
        self.assertEqual(res.history[0][1], good)
        self.assertNotEqual(res.history[0][1], bad)
        self.assertAlmostEqual(bad / good, 3.0, places=12)
        self.assertEqual(train(seed=2, normalization="per_mask_entry", timestamp_utc=TS).history[0][1], bad)

    def test_history_grad_norm_is_l2_and_step_index(self):
        res = train(seed=2, steps=5, timestamp_utc=TS)
        teacher, x = make_teacher(2, 3), make_inputs(2)
        out = teacher.outputs(x)
        target = erasure_target(out.conditioned, out.unconditioned, 0.5)
        rng = make_rng(derive_seed(2, "student_init"))
        s = Student([rng.uniform(-0.5, 0.5) for _ in range(6)])
        self.assertEqual([h[0] for h in res.history], [0, 1, 2, 3, 4, 5])
        for k, (step, loss, gn) in enumerate(res.history):
            l, g = masked_mse_loss_and_grad(s.params, x, target, (True,) * 4)
            self.assertEqual(loss, l)
            self.assertAlmostEqual(gn, math.sqrt(sum(v * v for v in g)), places=12)
            self.assertGreater(abs(sum(abs(v) for v in g) - gn), 1e-6)  # L1 would differ
            if k < 5:
                s.step(g, 0.05)
        self.assertEqual(res.final_params, tuple(s.params))

    def test_config_hash_covers_every_field(self):
        base = dict(seed=2, steps=5, lr=0.05, eta=0.5, rescale=False, normalization="per_masked_element",
                    mask=(True, True, True, True), timestamp_utc=TS)
        h0 = train(**base).record.provenance.input_hashes["config"]
        self.assertEqual(h0, train(**base).record.provenance.input_hashes["config"])
        variants = dict(steps=6, lr=0.04, eta=0.6, rescale=True, normalization="per_mask_entry",
                        mask=(True, True, True, False),
                        teacher=Teacher({"cond_scale": (1.0,) * 3, "cond_bias": (0.0,) * 3,
                                         "uncond_scale": (1.0,) * 3, "uncond_bias": (0.1,) * 3}))
        for k, v in variants.items():
            h = train(**{**base, k: v}).record.provenance.input_hashes["config"]
            self.assertNotEqual(h, h0, k)
        # input x is hashed separately
        x2 = make_inputs(9)
        self.assertNotEqual(train(**{**base, "x": x2}).record.provenance.input_hashes["x"],
                            train(**base).record.provenance.input_hashes["x"])


class _StatefulTeacher(Teacher):
    """Probe: a Teacher subclass whose outputs drift after the first call (violates freezing)."""
    calls = 0

    def outputs(self, x):
        type(self).calls += 1
        out = super().outputs(x)
        if type(self).calls > 1:
            return TeacherOutput(tuple(tuple(v + 1.0 for v in r) for r in out.conditioned), out.unconditioned)
        return out


class _DuckTeacher:
    params = {}

    def outputs(self, x):
        return None


class Integrity(unittest.TestCase):
    P = {"cond_scale": (2.0, 1.0), "cond_bias": (0.0, 1.0), "uncond_scale": (1.0, 0.5), "uncond_bias": (0.5, 0.0)}
    X = ((1.0, 2.0), (3.0, -4.0))

    def test_non_teacher_object_rejected(self):
        for bad in (_DuckTeacher(), object(), {"cond_scale": (1.0,)}):
            with self.assertRaisesRegex(ValueError, "must be a Teacher"):
                train(seed=1, x=self.X, teacher=bad)

    def test_mutating_teacher_is_caught_not_recorded(self):
        _StatefulTeacher.calls = 0
        with self.assertRaisesRegex(ValueError, "teacher changed during training"):
            train(seed=1, x=self.X, teacher=_StatefulTeacher(self.P), timestamp_utc=TS)

    def test_well_behaved_subclass_still_accepted(self):
        class Plain(Teacher):
            pass
        self.assertEqual(len(train(seed=1, x=self.X, teacher=Plain(self.P)).history), 51)

    def test_eta_int_and_float_agree(self):
        a, b = train(seed=2, eta=1, timestamp_utc=TS), train(seed=2, eta=1.0, timestamp_utc=TS)
        self.assertEqual(a.history, b.history)
        self.assertEqual(a.record.content_hash(), b.record.content_hash())
        self.assertEqual(a.record.provenance.input_hashes, b.record.provenance.input_hashes)

    def test_run_id_distinguishes_configs(self):
        a = train(seed=2, lr=0.05, timestamp_utc=TS).record.provenance.run_id
        b = train(seed=2, lr=0.04, timestamp_utc=TS).record.provenance.run_id
        self.assertNotEqual(a, b)
        self.assertEqual(a, train(seed=2, lr=0.05, timestamp_utc=TS).record.provenance.run_id)
        self.assertTrue(a.startswith("toy-teacher-student-seed2-"))

    def test_runaway_finite_lr_is_flagged(self):
        bad = train(seed=2, lr=3.0, timestamp_utc=TS)
        self.assertGreater(bad.history[-1][1], bad.history[0][1])
        self.assertTrue(bad.loss_increased)
        self.assertEqual(bad.record.metrics["loss_increased"].value, 1.0)
        self.assertIn("WARNING", bad.record.notes)
        good = train(seed=2, timestamp_utc=TS)
        self.assertFalse(good.loss_increased)
        self.assertEqual(good.record.metrics["loss_increased"].value, 0.0)
        self.assertNotIn("WARNING", good.record.notes)

    def test_huge_finite_x_gives_named_cause(self):
        for big in (1e100, 1e160):
            with self.assertRaises(ValueError) as cm:
                train(seed=1, x=((big, 1.0, 2.0), (1.0, 1.0, 1.0)), timestamp_utc=TS)
            self.assertRegex(str(cm.exception), "overflow|too large")
            self.assertNotIn("metric value must be finite", str(cm.exception))


class Hardening(unittest.TestCase):
    def test_bad_rows_width_steps(self):
        for kw in ({"rows": 0}, {"rows": -1}, {"width": 0}, {"rows": True}):
            with self.assertRaises(ValueError):
                train(seed=1, **kw)
        for steps in (-1, True, 1.5):
            with self.assertRaisesRegex(ValueError, "steps"):
                train(seed=1, steps=steps)

    def test_zero_steps_ok(self):
        self.assertEqual(len(train(seed=1, steps=0).history), 1)

    def test_huge_int_is_validation_error(self):
        with self.assertRaisesRegex(ValueError, "non-finite"):
            as_matrix("x", [[10 ** 400]])

    def test_width_rows_contradicting_x_raise(self):
        x = ((1.0, 2.0), (3.0, 4.0))
        teacher = make_teacher(1, 2)
        with self.assertRaisesRegex(ValueError, "width=3 contradicts"):
            train(seed=1, x=x, width=3, teacher=teacher)
        with self.assertRaisesRegex(ValueError, "rows=4 contradicts"):
            train(seed=1, x=x, rows=4, teacher=teacher)
        self.assertEqual(len(train(seed=1, x=x, width=2, rows=2, teacher=teacher).history), 51)

    def test_divergence_reported_honestly(self):
        with self.assertRaisesRegex(ValueError, "diverged"):
            train(seed=1, lr=1e200, steps=50)
        with self.assertRaisesRegex(ValueError, "diverged"):
            Student([1e300, 1e300]).step((1e300, 1e300), 1e10)
        try:
            train(seed=1, lr=1e200, steps=50)
        except ValueError as e:
            self.assertNotIn("match params length", str(e))

    def test_mask_must_be_bool(self):
        for bad in ((1, 1, 1, 1), (True, True, True, "no"), (True, True, True, None)):
            with self.assertRaisesRegex(ValueError, "must be bool"):
                train(seed=1, mask=bad)
        with self.assertRaisesRegex(ValueError, "must be bool"):
            masked_mse_loss_and_grad(P, X, T, (1, True))

    def test_predict_width_check(self):
        with self.assertRaisesRegex(ValueError, "params length"):
            predict((1.0, 0.0, 0.0), as_matrix("x", X))
        with self.assertRaisesRegex(ValueError, "params length"):
            masked_mse_loss_and_grad((1.0,) * 3, X, T, (True, True))

    def test_step_grad_length_check(self):
        s = Student([1.0, 2.0])
        with self.assertRaisesRegex(ValueError, "grad length"):
            s.step((0.1,), 0.1)
        with self.assertRaisesRegex(ValueError, "grad length"):
            s.step((0.1, 0.1, 0.1), 0.1)
        with self.assertRaisesRegex(ValueError, "grad must be finite"):
            s.step((math.nan, 0.0), 0.1)
        self.assertEqual(s.params, [1.0, 2.0])  # failed steps leave state untouched

    def test_label_is_schema_label(self):
        import toy.schema as sch, toy.teacher_student as ts
        self.assertIs(ts.TOY_LABEL, sch.TOY_LABEL)


if __name__ == "__main__":
    unittest.main()
