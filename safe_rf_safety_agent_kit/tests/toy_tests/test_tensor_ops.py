"""SR-07 tests: generic numeric behaviour of non-in-place ops, the mutation
detector, the autograd in-place probe, and device/precision comparison.

Abstract tensors only. No statement about the audited program or any safety
property. torch-dependent tests are SKIPPED (with a reason) when torch is
absent; CUDA tests are SKIPPED here because no CUDA device exists on this
machine; MPS tests run only if an MPS op genuinely executes.
"""
import math
import os
import re
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from toy import tensor_ops as T  # noqa: E402

if T.TORCH_AVAILABLE:
    import torch

CUDA_OK = T.device_available("cuda")
MPS_OK = T.device_available("mps")

requires_torch = unittest.skipUnless(T.TORCH_AVAILABLE, "torch not installed; torch tensor tests skipped")
_WHY = "torch not installed" if not T.TORCH_AVAILABLE else None
requires_cuda = unittest.skipUnless(
    CUDA_OK, (f"{_WHY}; " if _WHY else "") + "CUDA not available: CPU-vs-CUDA comparison (ER-09) is UNKNOWN, not passed")
requires_mps = unittest.skipUnless(
    MPS_OK, (f"{_WHY}; " if _WHY else "") + "MPS not available (or probe op failed): CPU-vs-MPS comparison is UNKNOWN, not passed")


def _t(vals, **kw):
    return torch.tensor(vals, dtype=kw.pop("dtype", torch.float32), **kw)


# ------------------------------------------------------------------ pure ops, lists (no torch)
class TestPureOpsLists(unittest.TestCase):
    def test_set_indices_does_not_mutate(self):
        x = [1.0, 2.0, 3.0]
        y = T.set_indices(x, [0, -1], [9.0, 8.0])
        self.assertEqual(y, [9.0, 2.0, 8.0])
        self.assertEqual(x, [1.0, 2.0, 3.0])
        self.assertIsNot(x, y)
        self.assertEqual(T.set_indices((1, 2), [0], 7), (7, 2))  # tuple stays tuple

    def test_set_indices_rejects_bad_input(self):
        for idx, vals in [([3], 0.0), ([-4], 0.0), ([0, 0], [1, 2]), ([True], 0.0), ([0.0], 0.0), ([0, 1], [1.0])]:
            with self.assertRaises(T.TensorOpError, msg=str((idx, vals))):
                T.set_indices([1.0, 2.0, 3.0], idx, vals)

    def test_set_indices_empty_is_equal_copy(self):
        x = [1.0, 2.0]
        y = T.set_indices(x, [], 0.0)
        self.assertEqual(y, x)
        self.assertIsNot(y, x)

    def test_masked_fill(self):
        x = [1.0, 2.0, 3.0]
        self.assertEqual(T.masked_fill(x, [True, False, True], 0.0), [0.0, 2.0, 0.0])
        self.assertEqual(x, [1.0, 2.0, 3.0])
        for bad in ([1, 0, 1], [True, False], [True, False, True, True], "tft"):
            with self.assertRaises(T.TensorOpError, msg=repr(bad)):
                T.masked_fill(x, bad, 0.0)

    def test_accumulate(self):
        x = [1.0, 2.0]
        self.assertEqual(T.accumulate(x, [0.5, 0.5]), [1.5, 2.5])
        self.assertEqual(T.accumulate(x, 1.0), [2.0, 3.0])
        self.assertEqual(x, [1.0, 2.0])
        with self.assertRaises(T.TensorOpError):
            T.accumulate(x, [1.0])

    def test_normalize(self):
        x = [3.0, 4.0]
        self.assertEqual(T.normalize(x), [0.6, 0.8])
        self.assertEqual(x, [3.0, 4.0])
        with self.assertRaises(T.TensorOpError):
            T.normalize([0.0, 0.0])
        self.assertEqual(T.normalize([0.0, 0.0], eps=1e-6), [0.0, 0.0])  # explicit eps -> zeros, not NaN
        for bad in ([], [float("nan"), 1.0], [float("inf")]):
            with self.assertRaises(T.TensorOpError):
                T.normalize(bad)
        with self.assertRaises(T.TensorOpError):
            T.normalize([1.0], eps=-1.0)

    def test_clamp(self):
        x = [-2.0, 0.5, 9.0, float("nan")]
        y = T.clamp(x, 0.0, 1.0)
        self.assertEqual(y[:3], [0.0, 0.5, 1.0])
        self.assertTrue(math.isnan(y[3]), "NaN must pass through clamp, not be hidden")
        self.assertEqual(x[:3], [-2.0, 0.5, 9.0])
        self.assertEqual(T.clamp([5.0], lo=None, hi=1.0), [1.0])
        for lo, hi in [(None, None), (2.0, 1.0), (float("nan"), 1.0)]:
            with self.assertRaises(T.TensorOpError):
                T.clamp(x, lo, hi)


# ------------------------------------------------------------------ pure ops, torch
@requires_torch
class TestPureOpsTorch(unittest.TestCase):
    def _unchanged(self, fn, *args, **kw):
        """Run fn through the detector and require 'clean' plus the exact input values."""
        rep = T.detect_mutation(fn, *args, **kw)
        self.assertFalse(rep.mutated, rep.findings)
        self.assertIsNone(rep.raised)
        return rep.result

    def test_set_indices(self):
        x = _t([1.0, 2.0, 3.0], requires_grad=True)
        y = self._unchanged(T.set_indices, x, [0, 2], _t([9.0, 8.0]))
        self.assertEqual(y.tolist(), [9.0, 2.0, 8.0])
        self.assertEqual(x.tolist(), [1.0, 2.0, 3.0])
        self.assertEqual(x._version, 0)
        y.sum().backward()
        self.assertEqual(x.grad.tolist(), [0.0, 1.0, 0.0])  # zero where replaced
        with self.assertRaises(T.TensorOpError):
            T.set_indices(x, [5], 0.0)
        with self.assertRaises(T.TensorOpError):
            T.set_indices(x, [0, 1], _t([1.0, 2.0, 3.0]))

    def test_set_indices_value_grad_flows(self):
        x = _t([1.0, 2.0, 3.0])
        v = _t([5.0], requires_grad=True)
        T.set_indices(x, [1], v).sum().backward()
        self.assertEqual(v.grad.tolist(), [1.0])

    def test_masked_fill(self):
        x = _t([1.0, 2.0, 3.0], requires_grad=True)
        m = torch.tensor([True, False, True])
        y = self._unchanged(T.masked_fill, x, m, 0.0)
        self.assertEqual(y.tolist(), [0.0, 2.0, 0.0])
        self.assertEqual(x.tolist(), [1.0, 2.0, 3.0])
        self.assertEqual(m.tolist(), [True, False, True])
        y.sum().backward()
        self.assertEqual(x.grad.tolist(), [0.0, 1.0, 0.0])
        for bad in (torch.tensor([1, 0, 1]), torch.tensor([True, False]), [True, False, True]):
            with self.assertRaises(T.TensorOpError):
                T.masked_fill(x, bad, 0.0)

    def test_accumulate(self):
        x = _t([1.0, 2.0], requires_grad=True)
        d = _t([0.5, 0.5])
        y = self._unchanged(T.accumulate, x, d)
        self.assertEqual(y.tolist(), [1.5, 2.5])
        self.assertEqual((x.tolist(), d.tolist()), ([1.0, 2.0], [0.5, 0.5]))
        # autograd: reuse x after accumulate; backward must work (no saved tensor modified)
        (T.accumulate(x, d) * x).sum().backward()
        self.assertEqual(x.grad.tolist(), [2.0 * 1.0 + 0.5, 2.0 * 2.0 + 0.5])
        with self.assertRaises(T.TensorOpError):
            T.accumulate(x, _t([1.0]))  # no silent broadcast

    def test_normalize(self):
        x = _t([[3.0, 4.0], [0.0, 2.0]], requires_grad=True)
        y = self._unchanged(T.normalize, x)
        torch.testing.assert_close(y, _t([[0.6, 0.8], [0.0, 1.0]]))
        self.assertEqual(x.tolist(), [[3.0, 4.0], [0.0, 2.0]])
        y.sum().backward()
        self.assertTrue(bool(torch.isfinite(x.grad).all()))
        with self.assertRaises(T.TensorOpError):
            T.normalize(_t([[0.0, 0.0]]))
        with self.assertRaises(T.TensorOpError):
            T.normalize(_t([float("nan"), 1.0]))
        with self.assertRaises(T.TensorOpError):
            T.normalize(torch.tensor([1, 2]))

    def test_normalize_eps_zero_vector_has_finite_value_and_grad(self):
        z = _t([[0.0, 0.0]], requires_grad=True)
        y = T.normalize(z, eps=1e-6)
        self.assertEqual(y.tolist(), [[0.0, 0.0]])
        y.sum().backward()
        # x/eps in the 0 <= norm < eps branch: gradient is exactly 1/eps per element (finite but large)
        torch.testing.assert_close(z.grad, torch.full((1, 2), 1e6), rtol=1e-6, atol=0)

    def test_clamp_values_nan_and_gradient_kill(self):
        x = _t([-2.0, 0.5, 9.0, float("nan")], requires_grad=True)
        y = self._unchanged(T.clamp, x, 0.0, 1.0)
        self.assertEqual(y[:3].tolist(), [0.0, 0.5, 1.0])
        self.assertTrue(bool(torch.isnan(y[3])))
        self.assertTrue(bool(torch.isnan(x[3])))
        y[:3].sum().backward()
        self.assertEqual(x.grad[:3].tolist(), [0.0, 1.0, 0.0])  # zero strictly outside the bounds

    def test_clamp_gradient_at_the_bound_is_one(self):
        x = _t([0.0, 0.5, 1.0, 2.0, -1.0], requires_grad=True)
        T.clamp(x, 0.0, 1.0).sum().backward()
        self.assertEqual(x.grad.tolist(), [1.0, 1.0, 1.0, 0.0, 0.0])


# ------------------------------------------------------------------ mutation detector
class TestDetectorNoTorch(unittest.TestCase):
    def test_pure_is_clean_and_mutating_is_caught_on_lists(self):
        data = [1, 2, 3]
        rep = T.detect_mutation(lambda a: sorted(a), data)
        self.assertFalse(rep.mutated)
        self.assertEqual(rep.result, [1, 2, 3])

        def mutate(a):
            a.append(4)
        rep = T.detect_mutation(mutate, data)
        self.assertTrue(rep.mutated)
        self.assertEqual(rep.locations, ("args[0]",))
        self.assertEqual(rep.findings[0].kind, "structure_changed")

    def test_nested_and_kwarg_locations(self):
        cfg = {"a": [1, 2], "b": {"c": 0.5}}

        def mutate(*, cfg):
            cfg["b"]["c"] = 9.0
        rep = T.detect_mutation(mutate, cfg=cfg)
        self.assertTrue(rep.mutated)
        self.assertEqual(rep.locations, ("kwargs['cfg']['b']['c']",))
        self.assertEqual(rep.findings[0].kind, "object_changed")

    def test_exception_is_recorded_not_raised_and_prior_mutation_seen(self):
        data = [1]

        def mutate_then_fail(a):
            a.append(2)
            raise KeyError("boom")
        rep = T.detect_mutation(mutate_then_fail, data)
        self.assertTrue(rep.mutated)
        self.assertIn("KeyError", rep.raised)

    def test_uncomparable_object_is_listed_unchecked_not_called_clean(self):
        class Weird:
            def __eq__(self, other):
                raise TypeError("no comparison")
            __hash__ = None
        rep = T.detect_mutation(lambda w: None, Weird())
        self.assertFalse(rep.mutated)
        self.assertTrue(rep.unchecked, "a location that cannot be compared must be reported as unchecked")


@requires_torch
class TestDetectorTorch(unittest.TestCase):
    def test_pure_callable_cleared(self):
        x = _t([1.0, 2.0])
        rep = T.detect_mutation(lambda a: a * 2 + 1, x)
        self.assertFalse(rep.mutated)
        self.assertEqual(rep.result.tolist(), [3.0, 5.0])

    def test_inplace_callable_caught_by_value_and_version(self):
        x = _t([1.0, 2.0])
        rep = T.detect_mutation(lambda a: a.add_(1.0), x)
        self.assertTrue(rep.mutated)
        self.assertEqual(rep.findings[0].kind, "values_changed+version_bumped")
        self.assertEqual(rep.locations, ("args[0]",))
        self.assertEqual(x.tolist(), [2.0, 3.0])  # genuinely mutated

    def test_which_input_is_reported(self):
        a, b = _t([1.0]), _t([1.0])
        rep = T.detect_mutation(lambda p, q: q.mul_(3.0), a, b)
        self.assertEqual(rep.locations, ("args[1]",))

    def test_tensor_inside_container_is_found(self):
        a = [_t([1.0]), _t([2.0])]
        rep = T.detect_mutation(lambda lst: lst[1].zero_(), a)
        self.assertEqual(rep.locations, ("args[0][1]",))

    def test_limit_data_write_changes_values_without_version(self):
        x = _t([1.0, 2.0])

        def sneaky(a):
            a.data.add_(1.0)  # bypasses the version counter
        rep = T.detect_mutation(sneaky, x)
        self.assertEqual([f.kind for f in rep.findings], ["values_changed"])
        self.assertEqual(x._version, 0)

    def test_limit_same_value_write_bumps_version_only(self):
        x = _t([0.0, 0.0])
        rep = T.detect_mutation(lambda a: a.zero_(), x)
        self.assertEqual([f.kind for f in rep.findings], ["version_bumped"])
        self.assertTrue(rep.mutated)

    def test_limit_mutate_and_restore_is_version_only(self):
        x = _t([1.0, 2.0])
        rep = T.detect_mutation(lambda a: a.mul_(2.0).div_(2.0), x)
        self.assertEqual([f.kind for f in rep.findings], ["version_bumped"])
        self.assertEqual(x.tolist(), [1.0, 2.0])

    def test_signed_zero_and_nan_payload_distinguished(self):
        x = _t([0.0, float("nan")])
        rep = T.detect_mutation(lambda a: a.__setitem__(0, -0.0), x)
        self.assertEqual([f.kind for f in rep.findings], ["values_changed+version_bumped"])
        y = _t([0.0])
        rep_d = T.detect_mutation(lambda a: a.data.__setitem__(0, -0.0), y)
        self.assertEqual([f.kind for f in rep_d.findings], ["values_changed"])  # value signal alone, no version
        self.assertEqual(y._version, 0)
        rep2 = T.detect_mutation(lambda a: a.__setitem__(1, float("nan")), x)
        # rewriting NaN with the same payload is value-identical: version bump at most
        self.assertTrue(all(f.kind != "values_changed" for f in rep2.findings))

    def test_shape_change_reported(self):
        x = _t([1.0, 2.0])
        rep = T.detect_mutation(lambda a: a.resize_(3), x)
        self.assertEqual(rep.findings[0].kind, "shape_changed")

    def test_ops_leave_all_inputs_untouched_per_detector(self):
        x = _t([1.0, -2.0, 3.0])
        m = torch.tensor([True, False, False])
        for fn, args in [(T.set_indices, (x, [1], 0.0)), (T.masked_fill, (x, m, 0.0)),
                         (T.accumulate, (x, x)), (T.normalize, (x,)), (T.clamp, (x, 0.0, 1.0))]:
            rep = T.detect_mutation(fn, *args)
            self.assertFalse(rep.mutated, (fn.__name__, rep.findings))
            self.assertEqual(x.tolist(), [1.0, -2.0, 3.0])


# ------------------------------------------------------------------ autograd probe
@requires_torch
class TestAutogradProbe(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ev = T.probe_inplace_autograd()

    def test_leaf_write_raises_runtimeerror(self):
        for name in ("leaf_setitem", "leaf_add_"):
            c = self.ev.case(name)
            self.assertTrue(c.target_requires_grad)
            self.assertTrue(c.write_raised, name)
            self.assertEqual(c.write_exception, "RuntimeError")
            self.assertIn("leaf Variable that requires grad", c.write_message)
            self.assertEqual(c.version_before, c.version_after)  # nothing was written

    def test_leaf_setitem_message_may_be_view_form(self):
        # x[0] = v goes through a view of x, so the message names "a view of a leaf Variable"
        self.assertTrue(self.ev.case("leaf_setitem").target_is_leaf)

    def test_view_of_leaf_is_nonleaf_but_still_raises(self):
        c = self.ev.case("leaf_view_setitem")
        self.assertFalse(c.target_is_leaf)
        self.assertTrue(c.write_raised)
        self.assertIn("view of a leaf Variable", c.write_message)

    def test_nonleaf_write_does_not_raise(self):
        for name in ("nonleaf_inplace_not_saved", "nonleaf_inplace_saved", "clone_then_setitem_on_leaf"):
            c = self.ev.case(name)
            self.assertFalse(c.target_is_leaf, name)
            self.assertFalse(c.write_raised, name)
            self.assertEqual(c.version_after, c.version_before + 1)

    def test_nonleaf_saved_tensor_caught_only_at_backward(self):
        c = self.ev.case("nonleaf_inplace_saved")
        self.assertTrue(c.backward_raised)
        self.assertEqual(c.backward_exception, "RuntimeError")
        self.assertIn("modified by an inplace operation", c.backward_message)

    def test_nonleaf_unsaved_is_silent_and_gradient_correct(self):
        c = self.ev.case("nonleaf_inplace_not_saved")
        self.assertFalse(c.backward_raised)
        self.assertEqual(c.grad, (2.0, 2.0, 2.0))

    def test_no_grad_bypasses_leaf_check_but_not_saved_check(self):
        c = self.ev.case("leaf_inplace_under_no_grad")
        self.assertFalse(c.write_raised)
        self.assertTrue(c.target_is_leaf)
        self.assertEqual(c.version_after, c.version_before + 1)
        self.assertTrue(c.backward_raised)

    def test_clone_first_is_the_safe_pattern(self):
        c = self.ev.case("clone_then_setitem_on_leaf")
        self.assertFalse(c.backward_raised)
        self.assertEqual(c.grad, (0.0, 1.0, 1.0))  # replaced position gets zero gradient

    def test_records_torch_version(self):
        self.assertEqual(self.ev.torch_version, torch.__version__)


# ------------------------------------------------------------------ comparison scaffolding
class TestUnmeasuredSemantics(unittest.TestCase):
    def test_empty_device_list_is_unmeasured(self):
        r = T.compare_across_devices(lambda x: x, [], [])
        self.assertFalse(r.measured)
        self.assertFalse(r.max_abs_diff.is_measured)

    @requires_torch
    def test_single_device_is_unmeasured_not_zero(self):
        x = _t([1.0, 2.0])
        for devs in (["cpu"], ["cpu", "cpu"]):
            r = T.compare_across_devices(lambda a: a * 2, [x], devs)
            self.assertFalse(r.measured)
            self.assertEqual(r.n_measured, 0)
            self.assertIsNone(r.max_abs_diff.value)
            self.assertIsNone(r.max_rel_diff.value)
            self.assertIsNone(r.bitwise_identical)  # neither True nor False
            self.assertNotEqual(r.max_abs_diff, T.MetricValue.measured(0.0))
            self.assertEqual(r.max_abs_diff.render(), "UNKNOWN")
            self.assertIn("no cross-device comparison possible", r.max_abs_diff.reason)

    @requires_torch
    def test_unavailable_device_is_skipped_with_reason_not_compared(self):
        r = T.compare_across_devices(lambda a: a * 2, [_t([1.0])], ["cpu", "no_such_device"])
        self.assertFalse(r.measured)
        self.assertEqual([s[0] for s in r.skipped], ["no_such_device"])
        self.assertIn("invalid device", r.skipped[0][1])

    @requires_torch
    def test_measured_zero_is_distinguishable_from_unmeasured(self):
        # Two identical dtype configs collapse; use a deterministic fn on float64 vs float64-equivalent pair
        x = _t([1.0, 2.0], dtype=torch.float64)
        r = T.compare_across_dtypes(lambda a: a + 0.0, [x], ["float64", "float32"])  # exactly representable
        self.assertTrue(r.measured)
        self.assertEqual(r.max_abs_diff.value, 0.0)
        self.assertTrue(r.bitwise_identical)
        self.assertTrue(r.max_abs_diff.is_measured)

    @requires_torch
    def test_reference_failure_gives_unmeasured(self):
        def boom(a):
            raise ValueError("nope")
        r = T.compare_across_dtypes(boom, [_t([1.0])], ["float64", "float32"])
        self.assertFalse(r.measured)
        self.assertEqual(len(r.skipped), 2)

    @requires_torch
    def test_nonfinite_output_is_unmeasured(self):
        r = T.compare_across_dtypes(lambda a: a / 0.0, [_t([1.0])], ["float64", "float32"])
        self.assertFalse(r.measured)
        self.assertIn("non-finite", r.pairs[0].reason)

    @requires_torch
    def test_compare_does_not_touch_caller_inputs(self):
        x = _t([1.0, 2.0])
        rep = T.detect_mutation(lambda a: T.compare_across_devices(lambda z: z.add_(1.0), [a], ["cpu", "cpu"]), x)
        self.assertFalse(rep.mutated, rep.findings)  # fn mutates its own copy, never the caller's
        self.assertEqual(x.tolist(), [1.0, 2.0])


@requires_torch
class TestFloat32VsFloat64(unittest.TestCase):
    """Measured divergence on CPU. A gap is a quantified sensitivity, not a defect."""

    def _cmp(self, fn, inputs):
        r = T.compare_across_dtypes(fn, inputs, [torch.float64, torch.float32])
        self.assertTrue(r.measured, r.unmeasured_reason)
        return r

    def test_cancellation_gap_is_real(self):
        r = self._cmp(T.fixture_cancellation, T.cancellation_inputs())
        self.assertFalse(r.bitwise_identical)
        # measured on this machine: rel ~ 0.59, abs ~ 5.9e-8. Bounds are generous but exclude 'no gap'.
        self.assertGreater(r.max_rel_diff.value, 0.1)
        self.assertLess(r.max_rel_diff.value, 1.5)
        self.assertGreater(r.max_abs_diff.value, 1e-8)
        self.assertLess(r.max_abs_diff.value, 2e-7)

    def test_cancellation_exact_case_is_total_loss(self):
        # (1 + 1e-8) - 1 : float64 keeps ~1e-8, float32 returns exactly 0 -> 100% relative error
        r = self._cmp(T.fixture_cancellation, [torch.tensor([1e-8], dtype=torch.float64)])
        self.assertAlmostEqual(r.max_rel_diff.value, 1.0, places=6)
        self.assertAlmostEqual(r.max_abs_diff.value, 1e-8, delta=1e-9)

    def test_long_accumulation_gap_is_real(self):
        r = self._cmp(T.fixture_sequential_accumulation, T.accumulation_inputs())
        # measured: abs ~ 2.5 on a true sum of 5000.0000..., rel ~ 5e-4
        self.assertGreater(r.max_rel_diff.value, 1e-4)
        self.assertLess(r.max_rel_diff.value, 1e-2)
        self.assertGreater(r.max_abs_diff.value, 0.5)

    def test_wellconditioned_control_has_small_but_nonzero_gap(self):
        r = self._cmp(T.fixture_wellconditioned, T.wellconditioned_inputs())
        self.assertLess(r.max_rel_diff.value, 1e-5)
        self.assertFalse(r.bitwise_identical)  # float32 is not float64, even when the gap is tiny

    def test_control_is_far_smaller_than_stressed_fixtures(self):
        ctrl = self._cmp(T.fixture_wellconditioned, T.wellconditioned_inputs()).max_rel_diff.value
        canc = self._cmp(T.fixture_cancellation, T.cancellation_inputs()).max_rel_diff.value
        acc = self._cmp(T.fixture_sequential_accumulation, T.accumulation_inputs()).max_rel_diff.value
        self.assertGreater(canc, 1000 * ctrl)
        self.assertGreater(acc, 1000 * ctrl)

    def test_kabsch_well_spread_agrees_collinear_does_not(self):
        spread = self._cmp(T.kabsch_rotation, T.kabsch_inputs()).max_rel_diff.value
        coll = self._cmp(T.kabsch_rotation, T.kabsch_inputs(collinear=True)).max_rel_diff.value
        self.assertLess(spread, 1e-4)
        self.assertGreater(coll, 1e-2)  # ill-determined rotation: precision changes the answer

    def test_kabsch_returns_proper_rotation(self):
        p, q = T.kabsch_inputs()
        R = T.kabsch_rotation(p, q)
        torch.testing.assert_close(R @ R.T, torch.eye(3, dtype=torch.float64), atol=1e-9, rtol=0)
        self.assertAlmostEqual(float(torch.linalg.det(R)), 1.0, places=9)

    def test_bad_dtype_rejected(self):
        with self.assertRaises(T.TensorOpError):
            T.compare_across_dtypes(lambda a: a, [_t([1.0])], [torch.int32])


# ------------------------------------------------------------------ devices
@requires_torch
class TestDeviceAvailability(unittest.TestCase):
    def test_cpu_always_available(self):
        self.assertEqual(T.device_status("cpu")[0], True)

    def test_flags_agree_with_torch(self):
        self.assertEqual(CUDA_OK, torch.cuda.is_available())
        if not torch.backends.mps.is_available():
            self.assertFalse(MPS_OK)

    def test_unavailable_cuda_reason_names_er09(self):
        if CUDA_OK:
            self.skipTest("CUDA present")
        self.assertIn("ER-09", T.device_status("cuda")[1])


@requires_mps
class TestCpuVsMps(unittest.TestCase):
    """MPS is a genuine second device here (Apple GPU); float32 only (MPS has no float64).
    linalg.svd falls back to CPU on MPS, so an SVD comparison would NOT be a GPU test and is not made."""

    def test_float32_battery_agrees_within_tolerance_and_is_measured(self):
        a = torch.sin(torch.arange(300, dtype=torch.float32)).reshape(100, 3)
        v = torch.sin(torch.arange(1000, dtype=torch.float32))
        cases = [("sum_squares", T.fixture_wellconditioned, [v]),
                 ("matmul", lambda z: z @ z.T, [a]),
                 ("normalize", lambda z: T.normalize(z), [a])]
        for name, fn, inp in cases:
            r = T.compare_across_devices(fn, inp, ["cpu", "mps"])
            self.assertTrue(r.measured, (name, r.skipped))
            self.assertEqual(r.reference, "cpu")
            self.assertLess(r.max_rel_diff.value, 1e-5, name)

    def test_float64_on_mps_is_skipped_with_reason_not_zero(self):
        r = T.compare_across_devices(lambda z: z * 2, [_t([1.0], dtype=torch.float64)], ["cpu", "mps"])
        self.assertFalse(r.measured)
        self.assertEqual(r.skipped[0][0], "mps")
        self.assertIn("float64", r.skipped[0][1])
        self.assertIsNone(r.bitwise_identical)

    def test_cpu_mps_report_has_unknown_cuda_leg(self):
        r = T.compare_across_devices(lambda z: z * 2, [_t([1.0])], ["cpu", "mps", "cuda"])
        self.assertTrue(r.measured)
        if not CUDA_OK:
            self.assertEqual([s[0] for s in r.skipped], ["cuda"])


@requires_cuda
class TestCpuVsCuda(unittest.TestCase):
    """Runs only where CUDA exists (never on this machine). ER-09 battery on CPU vs CUDA float32."""

    def test_battery(self):
        p, q = T.kabsch_inputs()
        for name, fn, inp in [("sum", T.fixture_wellconditioned, T.wellconditioned_inputs()),
                              ("kabsch", T.kabsch_rotation, [p, q])]:
            inp = [i.float() for i in inp]
            r = T.compare_across_devices(fn, inp, ["cpu", "cuda"])
            self.assertTrue(r.measured, name)
            self.assertLess(r.max_rel_diff.value, 1e-4, name)



# ------------------------------------------------------------------ QA round: hardening tests
class TestNormalizeRange(unittest.TestCase):
    def test_list_overflow_and_underflow_inputs_normalize_correctly(self):
        r = math.sqrt(0.5)
        for big in (1e200, 1e308, 1e-200, 1e-320):
            out = T.normalize([big, big])
            self.assertAlmostEqual(out[0], r, places=12, msg=str(big))
            self.assertAlmostEqual(out[1], r, places=12, msg=str(big))

    def test_list_all_zero_message_names_cause(self):
        with self.assertRaises(T.TensorOpError) as cm:
            T.normalize([0.0, 0.0])
        self.assertIn("all-zero", str(cm.exception))

    def test_list_eps_floor_applies_when_norm_below_eps(self):
        # norm 5e-7 < eps 1e-6 -> divide by eps, NOT by the norm
        out = T.normalize([3e-7, 4e-7], eps=1e-6)
        self.assertAlmostEqual(out[0], 0.3, places=9)
        self.assertAlmostEqual(out[1], 0.4, places=9)
        out2 = T.normalize([3.0, 4.0], eps=1e-6)   # norm above eps: ordinary unit vector
        self.assertEqual(out2, [0.6, 0.8])

    def test_list_non_real_entries_raise_tensorop_error(self):
        for bad in (["a"], [True, 1.0], [1.0, None], [1j]):
            with self.assertRaises(T.TensorOpError, msg=repr(bad)):
                T.normalize(bad)


@requires_torch
class TestNormalizeRangeTorch(unittest.TestCase):
    def test_float32_overflow_and_underflow_inputs(self):
        r = math.sqrt(0.5)
        for big in (1e30, 3e38, 1e-25, 1e-40):
            y = T.normalize(torch.tensor([big, big], dtype=torch.float32))
            torch.testing.assert_close(y, torch.tensor([r, r]), rtol=1e-6, atol=0, msg=str(big))
        y = T.normalize(torch.tensor([1e200, 1e200], dtype=torch.float64))
        torch.testing.assert_close(y, torch.tensor([r, r], dtype=torch.float64))

    def test_all_zero_row_raises_with_cause_but_eps_gives_zeros(self):
        with self.assertRaises(T.TensorOpError) as cm:
            T.normalize(_t([[1.0, 0.0], [0.0, 0.0]]))
        self.assertIn("all-zero", str(cm.exception))
        self.assertEqual(T.normalize(_t([[0.0, 0.0]]), eps=1e-6).tolist(), [[0.0, 0.0]])

    def test_eps_floor_applies_when_norm_below_eps(self):
        y = T.normalize(_t([[3e-7, 4e-7]]), eps=1e-6)
        torch.testing.assert_close(y, _t([[0.3, 0.4]]), rtol=1e-5, atol=0)
        y2 = T.normalize(_t([[3.0, 4.0]]), eps=1e-6)
        torch.testing.assert_close(y2, _t([[0.6, 0.8]]))

    def test_large_inputs_with_eps_have_no_nan_gradient(self):
        x = _t([[3e38, 3e38], [0.0, 0.0]], requires_grad=True)
        T.normalize(x, eps=1e-6).sum().backward()
        self.assertTrue(bool(torch.isfinite(x.grad).all()))

    def test_gradient_matches_float64_reference(self):
        x32 = _t([[3.0, 4.0, 1.0]], requires_grad=True)
        T.normalize(x32).pow(2).mul(_t([[1.0, 2.0, 3.0]])).sum().backward()
        x64 = torch.tensor([[3.0, 4.0, 1.0]], dtype=torch.float64, requires_grad=True)
        (x64 / torch.linalg.vector_norm(x64, dim=-1, keepdim=True)).pow(2).mul(
            torch.tensor([[1.0, 2.0, 3.0]], dtype=torch.float64)).sum().backward()
        torch.testing.assert_close(x32.grad.double(), x64.grad, rtol=1e-5, atol=1e-7)


@requires_torch
class TestSetIndicesCasts(unittest.TestCase):
    def test_float_into_int_tensor_raises_and_does_not_truncate(self):
        x = torch.tensor([1, 2, 3])
        with self.assertRaises(T.TensorOpError):
            T.set_indices(x, [0], 2.7)
        self.assertEqual(x.tolist(), [1, 2, 3])

    def test_overflow_into_float32_raises(self):
        with self.assertRaises(T.TensorOpError):
            T.set_indices(_t([1.0, 2.0]), [0], torch.tensor(1e300, dtype=torch.float64))
        with self.assertRaises(T.TensorOpError):
            T.set_indices(_t([1.0, 2.0]), [0], 1e300)

    def test_out_of_range_int_and_bool_cases(self):
        with self.assertRaises(T.TensorOpError):
            T.set_indices(torch.tensor([1, 2], dtype=torch.int8), [0], 300)
        with self.assertRaises(T.TensorOpError):
            T.set_indices(torch.tensor([True, False]), [0], 1)
        with self.assertRaises(T.TensorOpError):
            T.set_indices(_t([1.0]), [0], 1 + 2j)

    def test_legal_casts_still_work(self):
        self.assertEqual(T.set_indices(torch.tensor([1, 2, 3]), [0], 7).tolist(), [7, 2, 3])
        y = T.set_indices(_t([1.0, 2.0]), [1], 0.1)   # ordinary rounding is allowed
        self.assertAlmostEqual(y[1].item(), 0.1, places=6)
        self.assertEqual(T.set_indices(_t([1.0, 2.0]), [0], 3).tolist(), [3.0, 2.0])  # int -> float ok
        self.assertTrue(math.isnan(T.set_indices(_t([1.0]), [0], float("nan"))[0].item()))

    def test_value_shape_mismatch_is_tensorop_error(self):
        x = torch.zeros(3, 2)
        with self.assertRaises(T.TensorOpError):
            T.set_indices(x, [0], torch.zeros(1, 5))
        with self.assertRaises(T.TensorOpError):
            T.set_indices(x, [0, 1], torch.zeros(3, 2))
        self.assertEqual(T.set_indices(x, [0], torch.ones(1, 2))[0].tolist(), [1.0, 1.0])

    def test_accumulate_wrong_delta_type_is_tensorop_error(self):
        for bad in ([1.0, 2.0], "a", None, True):
            with self.assertRaises(T.TensorOpError, msg=repr(bad)):
                T.accumulate(_t([1.0, 2.0]), bad)
        with self.assertRaises(T.TensorOpError):
            T.accumulate([1.0, 2.0], ["a", "b"])


@requires_torch
class TestFlattenRejections(unittest.TestCase):
    """D-T1/D-T2/D-T3: a comparison that compared nothing must never be a measured zero."""

    def _dt(self, fn, x=None):
        x = _t([1.0, 2.0], dtype=torch.float64) if x is None else x
        return T.compare_across_dtypes(fn, [x], ["float64", "float32"])

    def _assert_unmeasured(self, r):
        self.assertFalse(r.measured)
        self.assertIsNone(r.max_abs_diff.value)
        self.assertIsNone(r.max_rel_diff.value)
        self.assertIsNone(r.bitwise_identical)
        self.assertTrue(r.skipped)

    def test_empty_output_is_unmeasured(self):
        r = self._dt(lambda a: a[:0])
        self._assert_unmeasured(r)
        self.assertIn("empty", r.skipped[0][1])

    def test_sequence_of_empty_tensors_is_unmeasured(self):
        self._assert_unmeasured(self._dt(lambda a: (a[:0], a[:0])))
        self._assert_unmeasured(self._dt(lambda a: []))

    def test_empty_with_nonempty_sibling_still_measured(self):
        r = self._dt(lambda a: (a[:0], a * 1.0))
        self.assertTrue(r.measured)

    def test_int64_above_2_53_not_cast_away(self):
        r = T.compare_across_devices(lambda a: a + (1 if a.dtype == torch.int64 else 0),
                                     [torch.tensor([2 ** 60], dtype=torch.int64)], ["cpu", "cpu"])
        self.assertFalse(r.measured)
        r = self._dt(lambda a: torch.tensor([2 ** 60 + (1 if a.dtype == torch.float64 else 2)]))
        self._assert_unmeasured(r)
        self.assertIn("non-floating", r.skipped[0][1])

    def test_bool_output_is_unmeasured(self):
        self._assert_unmeasured(self._dt(lambda a: a > 0))

    def test_complex_output_is_unmeasured_not_zero(self):
        # imaginary parts differ (1 vs 2) while real parts agree; the old code reported measured 0.0
        r = self._dt(lambda a: torch.complex(a, torch.ones_like(a) * (1.0 if a.dtype == torch.float64 else 2.0)))
        self._assert_unmeasured(r)
        self.assertIn("imaginary", r.skipped[0][1])

    def test_check_repeatability_rejects_complex_int_empty(self):
        counter = {"n": 0}

        def nonrepeatable_complex(a):
            counter["n"] += 1
            return torch.complex(a, a * 0 + float(counter["n"]))   # real part constant, imag part drifts
        with self.assertRaises(T.TensorOpError):
            T.check_repeatability(nonrepeatable_complex, [_t([1.0])], runs=3)
        with self.assertRaises(T.TensorOpError):
            T.check_repeatability(lambda a: torch.tensor([2 ** 60]), [_t([1.0])], runs=2)
        with self.assertRaises(T.TensorOpError):
            T.check_repeatability(lambda a: a[:0], [_t([1.0])], runs=2)

    def test_check_repeatability_catches_shape_change(self):
        state = {"n": 0}

        def f(a):
            state["n"] += 1
            return torch.ones(state["n"])
        self.assertFalse(T.check_repeatability(f, [_t([1.0])], runs=3).bitwise_identical_all_runs)

    def test_shape_mismatch_between_configs_is_unmeasured_not_broadcast(self):
        r = self._dt(lambda a: torch.ones(1) if a.dtype == torch.float64 else torch.ones(2))
        self.assertFalse(r.measured)
        self.assertIn("shape mismatch", r.pairs[0].reason)
        self.assertIsNone(r.pairs[0].bitwise_identical)

    def test_zero_reference_with_nonzero_candidate_is_unmeasured(self):
        r = self._dt(lambda a: torch.zeros(1, dtype=a.dtype) if a.dtype == torch.float64 else torch.ones(1))
        self.assertFalse(r.measured)
        self.assertIn("identically zero", r.pairs[0].reason)
        self.assertIsNone(r.max_rel_diff.value)
        # but zero vs zero is a genuine measured zero
        r0 = self._dt(lambda a: torch.zeros(2, dtype=a.dtype))
        self.assertTrue(r0.measured)
        self.assertEqual((r0.max_abs_diff.value, r0.max_rel_diff.value, r0.bitwise_identical), (0.0, 0.0, True))

    def test_multi_candidate_aggregation(self):
        # 1 + 2^-12 is exact in float32, rounded in float16 (11-bit significand)
        x = torch.tensor([1.0 + 2.0 ** -12], dtype=torch.float64)
        r = T.compare_across_dtypes(lambda a: a + 0.0, [x], ["float64", "float32", "float16"])
        self.assertEqual(r.n_measured, 2)
        by = {p.candidate: p for p in r.pairs}
        self.assertTrue(by["float32"].bitwise_identical)
        self.assertEqual(by["float32"].max_abs_diff.value, 0.0)
        self.assertFalse(by["float16"].bitwise_identical)
        self.assertGreater(by["float16"].max_abs_diff.value, 1e-4)
        self.assertEqual(r.max_abs_diff.value, by["float16"].max_abs_diff.value)  # max, not min
        self.assertEqual(r.max_rel_diff.value, by["float16"].max_rel_diff.value)
        self.assertFalse(r.bitwise_identical)  # all(), not any()

    def test_kabsch_actually_aligns_not_just_rotation_shaped(self):
        p, q = T.kabsch_inputs()
        R = T.kabsch_rotation(p, q)
        pc, qc = p - p.mean(0), q - q.mean(0)
        self.assertLess(float((pc @ R.T - qc).norm()), 1e-9)
        self.assertGreater(float((pc @ R - qc).norm()), 0.1)   # the transpose does NOT align


class TestDetectorOpaque(unittest.TestCase):
    def test_pure_callable_on_plain_object_is_clean_with_unchecked(self):
        class Plain:
            def __init__(self):
                self.v = 1
        obj = Plain()
        rep = T.detect_mutation(lambda o: o.v + 1, obj)
        self.assertFalse(rep.mutated)
        self.assertTrue(any("opaque Plain" in u for u in rep.unchecked))

    def test_consumed_iterator_listed_not_called_changed(self):
        it = iter([1, 2, 3])
        rep = T.detect_mutation(lambda i: next(i), it)
        self.assertFalse(rep.mutated)       # honest: we cannot see it
        self.assertTrue(any("opaque" in u for u in rep.unchecked))

    def test_list_with_nan_is_clean_when_pure(self):
        rep = T.detect_mutation(lambda a: len(a), [float("nan"), 1.0])
        self.assertFalse(rep.mutated)
        self.assertEqual(rep.unchecked, ())

    def test_scalar_replacements_that_equality_would_miss(self):
        for before, after in [(1, 1.0), (1, True), (0.0, -0.0), (1.0, 1), ("a", b"a")]:
            data = [before]

            def swap(d, after=after):
                d[0] = after
            rep = T.detect_mutation(swap, data)
            self.assertTrue(rep.mutated, (before, after))
            self.assertEqual(rep.findings[0].kind, "object_changed")
        d = {"k": 0.0}
        self.assertTrue(T.detect_mutation(lambda m: m.__setitem__("k", -0.0), d).mutated)

    def test_cycle_and_depth_are_listed_unchecked(self):
        a = [1]
        a.append(a)
        rep = T.detect_mutation(lambda z: None, a)
        self.assertTrue(any("cycle" in u for u in rep.unchecked))
        deep = cur = []
        for _ in range(40):
            nxt = []
            cur.append(nxt)
            cur = nxt
        rep = T.detect_mutation(lambda z: None, deep)
        self.assertTrue(any("depth limit" in u for u in rep.unchecked))

    def test_custom_eq_object_flagged_as_weak_comparison(self):
        class Box:
            def __init__(self, v): self.v = v
            def __eq__(self, o): return self.v == o.v
            __hash__ = None
        b = Box(1)
        rep = T.detect_mutation(lambda o: setattr(o, "v", 2), b)
        self.assertTrue(rep.mutated)
        self.assertTrue(any("== only" in u for u in rep.unchecked))


@requires_torch
class TestDetectorTorchMetadata(unittest.TestCase):
    def _kinds(self, fn, x):
        rep = T.detect_mutation(fn, x)
        return [(f.kind, f.detail) for f in rep.findings]

    def test_tensor_inside_tuple_is_found(self):
        tup = (_t([1.0]), _t([2.0]))
        rep = T.detect_mutation(lambda t: t[0].add_(1.0), tup)
        self.assertEqual(rep.locations, ("args[0][0]",))
        self.assertFalse(T.detect_mutation(lambda t: t[0] + t[1], tup).mutated)

    def test_requires_grad_flip(self):
        x = _t([1.0])
        k = self._kinds(lambda a: a.requires_grad_(), x)
        self.assertEqual(k[0][0], "metadata_changed")
        self.assertIn("requires_grad", k[0][1])

    def test_grad_zeroed_replaced_or_cleared(self):
        def fresh():
            x = _t([1.0, 2.0], requires_grad=True)
            (x * 3).sum().backward()
            return x
        x = fresh()
        self.assertEqual(self._kinds(lambda a: a.grad.zero_(), x)[0][0], "metadata_changed")
        x = fresh()
        self.assertIn("grad", self._kinds(lambda a: setattr(a, "grad", None), x)[0][1])
        x = fresh()
        self.assertIn("grad", self._kinds(lambda a: setattr(a, "grad", torch.ones(2)), x)[0][1])
        x = fresh()
        self.assertFalse(T.detect_mutation(lambda a: (a * 2).sum(), x).mutated)  # reading .grad-bearing tensor is clean

    def test_register_hook_and_rename(self):
        x = _t([1.0], requires_grad=True)
        k = self._kinds(lambda a: a.register_hook(lambda g: g), x)
        self.assertIn("hooks", k[0][1])
        y = torch.zeros(2, 3)
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")   # named tensors are flagged experimental by torch
            k = self._kinds(lambda a: a.rename_("r", "c"), y)
        self.assertIn("names", k[0][1])

    def test_detach_inplace_and_data_swap(self):
        y = _t([1.0], requires_grad=True) * 2
        k = self._kinds(lambda a: a.detach_(), y)
        self.assertTrue(any("grad_fn" in d for _, d in k))
        z = _t([1.0, 2.0])
        rep = T.detect_mutation(lambda a: setattr(a, "data", torch.tensor([5.0, 6.0])), z)
        self.assertTrue(rep.mutated)

    def test_pure_ops_on_grad_tensors_stay_clean(self):
        x = _t([1.0, 2.0], requires_grad=True)
        (x * 2).sum().backward()
        for fn in (lambda a: a * 2, lambda a: a.clone(), lambda a: T.normalize(a)):
            self.assertFalse(T.detect_mutation(fn, x).mutated)


class TestSkipWiring(unittest.TestCase):
    def test_cuda_class_skip_flag_matches_availability(self):
        self.assertEqual(getattr(TestCpuVsCuda, "__unittest_skip__", False), not CUDA_OK)
        if not CUDA_OK:
            self.assertIn("UNKNOWN", TestCpuVsCuda.__unittest_skip_why__)
            self.assertIn("CUDA", TestCpuVsCuda.__unittest_skip_why__)

    def test_mps_class_skip_flag_matches_availability(self):
        self.assertEqual(getattr(TestCpuVsMps, "__unittest_skip__", False), not MPS_OK)
        if not MPS_OK:
            self.assertIn("MPS", TestCpuVsMps.__unittest_skip_why__)

    def test_torch_class_skip_flag_matches_availability(self):
        for cls in (TestPureOpsTorch, TestDetectorTorch, TestAutogradProbe, TestFloat32VsFloat64):
            self.assertEqual(getattr(cls, "__unittest_skip__", False), not T.TORCH_AVAILABLE, cls.__name__)
            if not T.TORCH_AVAILABLE:
                self.assertIn("torch not installed", cls.__unittest_skip_why__)

    def test_this_machine_status_is_stated(self):
        # Not an assertion about hardware in general: pins down what this run knew.
        self.assertIsInstance(CUDA_OK, bool)
        self.assertIsInstance(MPS_OK, bool)

    @unittest.skipIf(os.environ.get("SR07_CHILD") == "1", "inside blocked-torch child process")
    def test_blocked_torch_import_module_works_and_torch_tests_skip(self):
        code = (
            "import sys, unittest\n"
            "sys.modules['torch'] = None\n"
            f"sys.path[:0] = [{str(ROOT / 'src')!r}, {str(ROOT / 'tests')!r}]\n"
            "from toy import tensor_ops as T\n"
            "assert T.TORCH_AVAILABLE is False\n"
            "assert T.device_available('cuda') is False and T.device_available('mps') is False\n"
            "assert T.device_available('cpu') is False  # no torch -> nothing to run on\n"
            "assert T.set_indices([1, 2], [0], 9) == [9, 2]\n"
            "r = T.compare_across_devices(lambda x: x, [], ['cpu', 'cuda'])\n"
            "assert not r.measured and r.max_abs_diff.value is None and r.bitwise_identical is None\n"
            "assert 'torch' in r.max_abs_diff.reason\n"
            "assert not T.compare_across_dtypes(lambda x: x, [], ['float32']).measured\n"
            "try:\n"
            "    T.probe_inplace_autograd(); raise SystemExit('no raise')\n"
            "except T.TorchUnavailable: pass\n"
            "from toy_tests import test_tensor_ops as t\n"
            "assert 'torch not installed' in t.TestCpuVsMps.__unittest_skip_why__\n"
            "assert 'torch not installed' in t.TestCpuVsCuda.__unittest_skip_why__\n"
            "res = unittest.TextTestRunner(stream=open('/dev/null','w')).run(\n"
            "    unittest.defaultTestLoader.loadTestsFromModule(t))\n"
            "print('RESULT', res.testsRun, len(res.skipped), len(res.failures), len(res.errors))\n"
        )
        env = dict(os.environ, SR07_CHILD="1")
        p = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=env, timeout=120)
        m = re.search(r"RESULT (\d+) (\d+) (\d+) (\d+)", p.stdout)
        self.assertIsNotNone(m, p.stdout + p.stderr)
        run, skipped, failures, errors = map(int, m.groups())
        self.assertEqual((failures, errors), (0, 0), p.stdout + p.stderr)
        self.assertGreater(run, 20)
        self.assertGreater(skipped, 5)  # torch classes + CUDA + MPS reported as skipped, not passed


# ------------------------------------------------------------------ determinism
@requires_torch
class TestDeterminism(unittest.TestCase):
    def test_every_tested_repeatable_claim_has_a_case_and_holds(self):
        cases = T.determinism_cases()
        claimed = {c.op for c in T.DETERMINISM_CLAIMS if c.status == "REPEATABLE_TESTED_ON_CPU"}
        self.assertEqual(claimed, set(cases), "claims and executable cases must match exactly")
        for op, (fn, inputs) in cases.items():
            res = T.check_repeatability(fn, inputs, runs=5)
            self.assertTrue(res.bitwise_identical_all_runs, op)
            self.assertEqual(res.max_abs_spread, 0.0, op)

    def test_no_untested_claim_is_labelled_repeatable(self):
        for c in T.DETERMINISM_CLAIMS:
            if c.status == "REPEATABLE_TESTED_ON_CPU":
                self.assertTrue(c.tested_here, c.op)
            if not c.tested_here:
                self.assertEqual(c.status, "NOT_GUARANTEED", c.op)

    def test_repeatability_detector_can_say_no(self):
        # A function whose output changes each call must be reported as non-repeatable.
        state = {"n": 0}

        def drifting(x):
            state["n"] += 1
            return x + state["n"]
        res = T.check_repeatability(drifting, [_t([1.0])], runs=3)
        self.assertFalse(res.bitwise_identical_all_runs)
        self.assertGreater(res.max_abs_spread, 0.0)

    def test_sum_across_thread_counts_is_bounded_not_required_identical(self):
        fn, inputs = T.determinism_cases()["sum_reduction_fixed_threads"]
        old = torch.get_num_threads()
        outs = []
        try:
            for n in sorted({1, max(1, old)}):
                torch.set_num_threads(n)
                outs.append(fn(*inputs).double())
        finally:
            torch.set_num_threads(old)
        rel = float((outs[0] - outs[-1]).abs().max() / outs[0].abs().max())
        self.assertLess(rel, 1e-5)  # bound only; bit equality across thread counts is NOT claimed

    def test_duplicate_index_write_is_refused_rather_than_left_unspecified(self):
        with self.assertRaises(T.TensorOpError):
            T.set_indices(_t([1.0, 2.0]), [0, 0], _t([5.0, 6.0]))


class TestModuleLabelAndImport(unittest.TestCase):
    def test_label_present_and_no_safety_claim_words(self):
        self.assertIn("not a statement about the audited program", T.LABEL)
        src = (ROOT / "src" / "toy" / "tensor_ops.py").read_text().lower()
        for banned in ("import rfdiffusion", "from rfdiffusion", "pickle", "torch.load(", "urllib", "requests"):
            self.assertNotIn(banned, src)


if __name__ == "__main__":
    unittest.main()
