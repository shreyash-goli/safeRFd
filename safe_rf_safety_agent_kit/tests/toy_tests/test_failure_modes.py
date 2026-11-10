"""SR-03 tests: each asserts that a defect PATTERN behaves as documented, on abstract
objects. They say nothing about the audited program at runtime and make no safety claim."""
import math
import os
import re
import subprocess
import sys
import unittest
from fractions import Fraction
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from toy import failure_modes as fm  # noqa: E402

requires_torch = unittest.skipUnless(fm.TORCH_AVAILABLE, "torch not installed; autograd demonstration skipped")


class TestStdlibPatterns(unittest.TestCase):
    def test_bare_exception_is_noop_and_unboundlocalerror(self):
        r = fm.bare_exception_statement_is_a_no_op()
        self.assertFalse(r["bare_statements_raised"])
        self.assertEqual(r["bare_statements_evaluated"], 2)  # the exec demos really ran
        self.assertEqual(r["bare_pattern_exception_type"], "UnboundLocalError")
        self.assertIn("loss", r["bare_pattern_message"])
        self.assertFalse(r["bare_pattern_is_runtime_error"])
        self.assertFalse(r["unbound_local_is_subclass_of_runtime_error"])
        # control with `raise` really raises RuntimeError with its message
        self.assertEqual(r["control_exception_type"], "RuntimeError")
        self.assertEqual(r["control_message"], "empty mask")
        self.assertEqual(r["nonempty_mask_value"], 1.0)
        with self.assertRaises(UnboundLocalError):
            fm._loss_bare_exception(0)
        try:
            fm._loss_bare_exception(0)
        except RuntimeError:
            self.fail("except RuntimeError must not catch the bare-name pattern")
        except UnboundLocalError:
            pass

    def test_nan_times_zero_is_nan(self):
        r = fm.nan_times_zero_is_nan()
        self.assertTrue(r["zero_times_nan_is_nan"])
        self.assertTrue(r["zero_times_inf_is_nan"])
        self.assertTrue(math.isnan(r["masked_element_product"][1]))
        self.assertTrue(r["sum_by_multiplication_is_nan"])
        self.assertFalse(r["sum_by_selection_is_nan"])
        self.assertEqual(r["sum_by_selection"], 4.0)
        # finite input: both agree (the pattern is only wrong when non-finite values hide under the mask)
        f = fm.nan_times_zero_is_nan((1.0, 2.0, 3.0), (True, False, True))
        self.assertEqual(f["sum_by_multiplication"], f["sum_by_selection"])
        with self.assertRaises(ValueError):
            fm.nan_times_zero_is_nan((1.0,), (True, False))
        if fm.TORCH_AVAILABLE:
            tc = r["torch_check"]
            self.assertTrue(tc["mult_sum_is_nan"])
            self.assertEqual(tc["selection_sum"], 4.0)
            self.assertTrue(tc["clamp_preserves_nan"])
        else:
            self.assertIsNone(r["torch_check"])

    def test_normalization_mismatch_factor(self):
        for leading, trailing, k in [(4, (14, 3), 42), (1, (2,), 2), (7, (5, 1, 3), 15),
                                     (3, (), 1), (2, (14, 3), 42)]:
            with self.subTest(leading=leading, trailing=trailing):
                r = fm.normalization_mismatch_scale_factor(leading, trailing)
                self.assertEqual(r["expected_factor"], k)
                self.assertEqual(r["observed_factor"], k)
                self.assertTrue(r["observed_factor_equals_expected_exactly"])
                self.assertEqual(r["inflated_mean"], r["true_element_mean"] * k)
        # configurations where the identity is NOT exact in plain floats: kills a float mutant
        for leading, trailing, k in [(7, (14, 3), 42), (1, (7,), 7), (9, (3, 3, 3), 27)]:
            with self.subTest(inexact_in_float=(leading, trailing)):
                r = fm.normalization_mismatch_scale_factor(leading, trailing)
                self.assertIsInstance(r["observed_factor"], Fraction)
                self.assertEqual(r["observed_factor"], k)
                self.assertTrue(r["observed_factor_equals_expected_exactly"])
        with self.assertRaises(ValueError):
            fm.normalization_mismatch_scale_factor(0, (2,))
        with self.assertRaises(ValueError):
            fm.normalization_mismatch_scale_factor(2, (3, 0))

    def test_mask_polarity_inversion_is_silent(self):
        r = fm.mask_polarity_inversion()
        self.assertEqual(r["true_means_include_indices"], [0, 2])
        self.assertEqual(r["false_means_include_indices"], [1, 3])
        self.assertTrue(r["index_sets_disjoint"])
        self.assertTrue(r["index_sets_cover_all"])
        self.assertEqual(r["loss_true_means_include"], 5.0)    # (1+9)/2
        self.assertEqual(r["loss_false_means_include"], 10.0)  # (4+16)/2
        self.assertTrue(r["losses_differ"])
        self.assertFalse(r["raised"])
        # degenerate mask: one reading is empty, reported as None rather than raised
        d = fm.mask_polarity_inversion((1.0, 2.0), (True, True))
        self.assertIsNone(d["loss_false_means_include"])
        with self.assertRaises(ValueError):
            fm.mask_polarity_inversion((1.0, 2.0, 3.0), (True, False))
        # equal losses under both readings: losses_differ must be False
        e = fm.mask_polarity_inversion((2.0, 2.0), (True, False))
        self.assertEqual((e["loss_true_means_include"], e["loss_false_means_include"]), (2.0, 2.0))
        self.assertFalse(e["losses_differ"])

    def test_gradient_clipping_hides_magnitude(self):
        r = fm.gradient_clipping_hides_magnitude()
        pre = [x["pre_clip_norm"] for x in r["rows"]]
        post = [x["post_clip_norm"] for x in r["rows"]]
        self.assertEqual(pre[0], 50.0)
        self.assertEqual(pre[-1], 5e9)
        self.assertTrue(r["post_clip_norms_all_bounded"])
        self.assertAlmostEqual(r["pre_clip_norm_span"], 1e8)
        for p in post:
            self.assertAlmostEqual(p, 1.0, places=4)
        # post-clip values are indistinguishable across eight orders of magnitude of raw gradient
        self.assertLess(max(post) - min(post), 1e-4)
        # below the threshold nothing is clipped
        small = fm.gradient_clipping_hides_magnitude(max_norm=100.0, raw_scales=(1.0,))
        self.assertAlmostEqual(small["rows"][0]["post_clip_norm"], 5.0, places=6)
        if fm.TORCH_AVAILABLE:
            self.assertAlmostEqual(r["torch_check"]["returned_by_clip_grad_norm"], 5000.0, places=2)
            self.assertAlmostEqual(r["torch_check"]["norm_after_clipping"], 1.0, places=4)
        else:
            self.assertIsNone(r["torch_check"])

    def test_no_function_exists_for_unrestricted_load(self):
        # ER-08 is static-only by design: no executable demo may be added.
        names = [n for n in dir(fm) if not n.startswith("__") and "load" in n.lower() or "pickle" in n.lower()]
        self.assertEqual(names, [])
        src = Path(fm.__file__).read_text()
        for banned in ("import pickle", "pickle.", "torch.load(", "__reduce__", "os.system"):
            self.assertNotIn(banned, src)


@requires_torch
class TestTorchPatterns(unittest.TestCase):
    def test_detach_severs_gradient(self):
        r = fm.detach_severs_gradient()
        self.assertTrue(r["out_requires_grad"])
        self.assertIsNone(r["detached_param_grad"])
        self.assertEqual(r["live_param_grad"], [1.0, 2.0])
        self.assertFalse(r["detached_branch_requires_grad"])

    def test_input_leaf_requires_grad_does_not_prove_parameter_gradient(self):
        r = fm.input_leaf_requires_grad_does_not_prove_parameter_gradient()
        for kind in ("severed", "zeroed", "control"):
            self.assertTrue(r[kind]["out_requires_grad"], kind)  # naive check passes in every case
        self.assertEqual(r["severed"]["input_grad"], [2.0, 2.0])
        self.assertIsNone(r["severed"]["param_grad"])
        self.assertFalse(r["severed"]["param_has_nonzero_grad"])
        self.assertEqual(r["zeroed"]["input_grad"], [2.0, 2.0])
        self.assertEqual(r["zeroed"]["param_grad"], [0.0, 0.0])
        self.assertFalse(r["zeroed"]["param_has_nonzero_grad"])
        self.assertEqual(r["control"]["param_grad"], [1.0, 2.0])  # == x
        self.assertTrue(r["control"]["param_has_nonzero_grad"])


class TestTorchGuardWiring(unittest.TestCase):
    def test_skip_decorator_matches_availability(self):
        skip_flag = getattr(TestTorchPatterns, "__unittest_skip__", False)
        self.assertEqual(skip_flag, not fm.TORCH_AVAILABLE)
        if skip_flag:
            self.assertIn("torch not installed", TestTorchPatterns.__unittest_skip_why__)

    def test_torch_functions_raise_when_unavailable(self):
        if fm.TORCH_AVAILABLE:
            self.skipTest("torch present; unavailable path is exercised in the subprocess test")
        with self.assertRaises(fm.TorchUnavailable):
            fm.detach_severs_gradient()

    @unittest.skipIf(os.environ.get("SR03_CHILD") == "1", "inside blocked-torch child process")
    def test_blocked_torch_import_skips_torch_tests_and_passes_rest(self):
        """Child process with torch import blocked: module imports, torch tests are SKIPPED."""
        code = (
            "import os, sys, unittest\n"
            "sys.modules['torch'] = None\n"            # makes `import torch` raise ImportError
            f"sys.path[:0] = [{str(ROOT / 'src')!r}, {str(ROOT / 'tests')!r}]\n"
            "from toy import failure_modes as fm\n"
            "assert fm.TORCH_AVAILABLE is False\n"
            "from toy_tests import test_failure_modes as t\n"
            "L = unittest.defaultTestLoader\n"
            "suite = unittest.TestSuite([L.loadTestsFromTestCase(t.TestStdlibPatterns),\n"
            "                            L.loadTestsFromTestCase(t.TestTorchPatterns)])\n"
            "res = unittest.TextTestRunner(stream=open(os.devnull, 'w')).run(suite)\n"
            "print('RESULT', res.testsRun, len(res.skipped), len(res.failures), len(res.errors))\n"
        )
        env = dict(os.environ, SR03_CHILD="1")
        p = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=env, timeout=60)
        m = re.search(r"RESULT (\d+) (\d+) (\d+) (\d+)", p.stdout)
        self.assertIsNotNone(m, p.stdout + p.stderr)
        run, skipped, failures, errors = map(int, m.groups())
        self.assertEqual((failures, errors), (0, 0), p.stdout + p.stderr)
        # child runs only the stdlib and torch pattern classes: exactly the 2 torch tests skip
        self.assertEqual(skipped, 2)


    @unittest.skipIf(os.environ.get("SR03_CHILD") == "1", "inside child process")
    def test_broken_torch_install_non_importerror_still_imports_module(self):
        """A torch whose import raises OSError/RuntimeError (ABI mismatch) must not break import."""
        for exc in ("OSError", "RuntimeError"):
            with self.subTest(exc=exc):
                code = (
                    "import sys, importlib.abc\n"
                    "class F(importlib.abc.MetaPathFinder):\n"
                    "    def find_spec(self, name, path, target=None):\n"
                    f"        if name == 'torch': raise {exc}('simulated broken install')\n"
                    "sys.meta_path.insert(0, F())\n"
                    f"sys.path[:0] = [{str(ROOT / 'src')!r}]\n"
                    "from toy import failure_modes as fm\n"
                    "assert fm.TORCH_AVAILABLE is False\n"
                    "try:\n    fm.detach_severs_gradient()\nexcept fm.TorchUnavailable:\n    print('OK')\n"
                )
                p = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=60)
                self.assertEqual(p.stdout.strip(), "OK", p.stdout + p.stderr)


class TestRegisterConsistency(unittest.TestCase):
    SECTION_FIELDS = ("**Where:**", "**Classification:**", "**Severity", "**Does not establish:**",
                      "**To settle:**")
    LABELS = ("CONFIRMED-IN-SOURCE", "PATTERN-DEMONSTRATED", "UNKNOWN-NEEDS-EXECUTION",
              "STATIC-ANALYSIS-ONLY")

    def _sections(self):
        doc = (ROOT / "docs" / "ERROR_REGISTER.md").read_text()
        parts = re.split(r"^## (ER-\d\d)[: ]", doc, flags=re.M)
        return doc, dict(zip(parts[1::2], parts[2::2]))

    def test_pattern_function_keys_pinned(self):
        self.assertEqual(set(fm.PATTERN_FUNCTIONS), {f"ER-0{i}" for i in range(1, 8)})

    def test_register_structure(self):
        doc, secs = self._sections()
        self.assertEqual(set(secs), {f"ER-{i:02d}" for i in range(1, 12)})
        for er, body in secs.items():
            for field in self.SECTION_FIELDS:
                self.assertIn(field, body, f"{er} missing {field}")
            cls = body.split("**Classification:**")[1].split("\n")[0]
            self.assertTrue(any(l in cls for l in self.LABELS), er)
        self.assertIn("UNKNOWN-NEEDS-EXECUTION", secs["ER-09"].split("**Classification:**")[1].split("\n")[0])
        self.assertIn("STATIC-ANALYSIS-ONLY", secs["ER-08"].split("**Classification:**")[1].split("\n")[0])
        # sentence-initial overclaims only (the register legitimately says "no claim that the method is broken")
        self.assertIsNone(re.search(r"(^|[.!?]\s+|\n\s*)the method is (broken|safe)", doc.lower()))

    def test_every_function_and_test_is_named_in_the_register(self):
        doc = (ROOT / "docs" / "ERROR_REGISTER.md").read_text()
        for er_id, fn in fm.PATTERN_FUNCTIONS.items():
            self.assertTrue(callable(getattr(fm, fn)), fn)
            self.assertIn(er_id, doc)
            self.assertIn(fn, doc)
        for label in ("CONFIRMED-IN-SOURCE", "PATTERN-DEMONSTRATED", "UNKNOWN-NEEDS-EXECUTION",
                      "STATIC-ANALYSIS-ONLY"):
            self.assertIn(label, doc)
        self.assertIn("does not establish", doc.lower())


if __name__ == "__main__":
    unittest.main()
