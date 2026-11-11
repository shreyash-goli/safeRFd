"""SR-11 tests for toy.robustness: tests of MEASUREMENT-PROCEDURE PROBES on synthetic fixtures.

TOY ONLY. Nothing here runs the experiment of docs/EVALUATION_PROTOCOL.md, produces a finding, or says
anything about RFdiffusion or any real model. Every number is a property of a measure or of the probe
machinery on a synthetic fixture. A probe that cannot fail is worthless, so each failure path is exercised
with a deliberately broken measure and asserted to fire."""
import ast
import dataclasses
import functools
import inspect
import json
import math
import random
import struct
import sys
import types
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from toy import benchmark as bm
from toy import robustness as rb
from toy import stability
from toy.benchmark import fixture_oracle_gated
from toy.robustness import ProbeStatus as PS
from toy.robustness import ShiftKind as SK
from toy.schema import (SCHEMA_VERSION, TOY_LABEL, EvidenceClass, ExperimentRecord, MetricValue,
                        canonical_json, derive_seed)

# The field-coverage probe is shared with `test_schema` ON PURPOSE: two copies of it would be two things
# to keep in step, which is the exact failure mode the probe exists to end. A RELATIVE import, so it
# resolves both as `tests.toy_tests.test_robustness` (an owner's targeted run) and as
# `toy_tests.test_robustness` (`unittest discover -s tests`, whose top-level dir is `tests`).
from . import test_schema as ts

SEEDS = tuple(derive_seed(11, f"s{k}") for k in range(12))
SEEDS_B = tuple(derive_seed(12, f"s{k}") for k in range(12))
CFG = rb.ProbeConfig(10)
PY312 = sys.version_info >= (3, 12)
EPS = sys.float_info.epsilon
TS = "2000-01-01T00:00:00Z"


def sc_simple(seeds=SEEDS, f=lambda s: float(s % 1000)):
    return rb.seed_sensitivity_probe(f, seeds, CFG, probe_id="demo")


# ---- deliberately broken measures: each violates exactly one declared property ----
def row_weighted_mse(p, t, m):
    """Weights rows by their position: NOT permutation invariant (defect)."""
    P, T, M = (stability.check_finite_matrix(p), stability.check_finite_matrix(t), stability.check_mask(m, len(p)))
    num = sum((i + 1) * (a - b) ** 2 for i, (pr, tr, u) in enumerate(zip(P, T, M)) if u for a, b in zip(pr, tr))
    return num / (sum(M) * len(P[0]))


def mask_ignoring_mse(p, t, m):
    """Averages over ALL rows, ignoring the mask: masked-out rows leak into the result (defect)."""
    return rb.mse_fsum(p, t, (True,) * len(p))


def offset_mse(p, t, m):
    """Adds a constant: not scale-covariant (defect for the 2**10 scale invariance)."""
    return rb.mse_fsum(p, t, m) + 1.0


def amplified_mse(p, t, m):
    """Amplifies everything 1000x: perturbation response far exceeds the Lipschitz cap derived for MSE."""
    return rb.mse_fsum(p, t, m) * 1000.0 * 1000.0


def quantizing_mse(p, t, m):
    """Rounds inputs to float32 first (24-bit mantissa): after translating by 1000 the low-order bits of
    p - t are gone, far beyond the 64-bit rounding the bound allows (lossy measure)."""
    f32 = lambda x: struct.unpack("f", struct.pack("f", x))[0]
    q = lambda M_: tuple(tuple(f32(x) for x in r) for r in M_)
    return rb.mse_fsum(q(p), q(t), m)


def zero_on_failure(p, t, m):
    """Silent substitution: any rejection becomes 0.0."""
    try:
        return rb.mse_fsum(p, t, m)
    except (ValueError, TypeError):
        return 0.0


def default_on_all_false(p, t, m):
    """Substitutes 1.0 only for the all-False mask."""
    if isinstance(m, tuple) and m and not any(m):
        return 1.0
    return rb.mse_fsum(p, t, m)


def lenient_truthiness(p, t, m):
    """Accepts truthy non-bool mask entries (the pattern check_mask refuses)."""
    return rb.mse_fsum(p, t, tuple(bool(x) for x in m) if isinstance(m, tuple) and m else m)


class TestMinimumSeedRule(unittest.TestCase):
    def test_floor_not_configurable_below(self):
        for bad in (0, 1, 2, -5, True, 3.0):
            with self.assertRaises(ValueError):
                rb.ProbeConfig(bad)
        self.assertEqual(rb.ProbeConfig(3).min_seeds, 3)

    def test_summary_cannot_be_built_from_fewer_than_floor(self):
        for n in (0, 1, 2):
            with self.assertRaises(ValueError):
                rb.SeedSummary.from_values([1.0] * n)
        # direct construction with a forged single-value summary
        with self.assertRaises(ValueError):
            rb.SeedSummary(1, 1.0, 0.0, 1.0, 1.0, 0.0, 1.0, 1.0, (1.0,))
        with self.assertRaises(ValueError):
            rb.SeedSummary(2, 1.0, 0.0, 1.0, 1.0, 0.0, 1.0, 1.0, (1.0, 1.0))

    def test_forged_statistics_rejected(self):
        good = rb.SeedSummary.from_values([1.0, 2.0, 3.0, 4.0])
        with self.assertRaises(ValueError):
            dataclasses.replace(good, mean=99.0)
        with self.assertRaises(ValueError):
            rb.SeedSummary(4, good.mean, good.sd, good.q1, good.q3, good.iqr, good.minimum, good.maximum,
                           (1.0, 2.0, 3.0, 5.0))

    def test_one_seed_gives_insufficient_never_a_scalar(self):
        r = rb.summarize_seeds([MetricValue.measured(3.0)], 10)
        self.assertIsInstance(r, rb.InsufficientEvidence)
        for attr in ("mean", "sd", "iqr", "minimum", "maximum", "values", "q1", "q3"):
            self.assertFalse(hasattr(r, attr), attr)
        with self.assertRaises(rb.InsufficientEvidenceError):
            rb.require_summary(r)

    def test_threshold_boundary(self):
        mk = lambda n: [MetricValue.measured(float(i)) for i in range(n)]
        self.assertIsInstance(rb.summarize_seeds(mk(9), 10), rb.InsufficientEvidence)
        self.assertIsInstance(rb.summarize_seeds(mk(10), 10), rb.SeedSummary)
        self.assertIsInstance(rb.summarize_seeds(mk(3), 3), rb.SeedSummary)
        with self.assertRaises(ValueError):
            rb.summarize_seeds(mk(10), 2)   # min below the floor refused even here

    def test_hand_computed_statistics(self):
        s = rb.summarize_seeds([MetricValue.measured(float(i)) for i in range(1, 11)], 10)
        self.assertEqual(s.n, 10)
        self.assertEqual(s.mean, 5.5)
        self.assertAlmostEqual(s.sd, math.sqrt(82.5 / 9), places=12)   # sum (x-5.5)^2 = 82.5
        self.assertEqual((s.q1, s.q3, s.iqr), (3.25, 7.75, 4.5))      # type-7: pos 2.25 and 6.75
        self.assertEqual((s.minimum, s.maximum), (1.0, 10.0))
        self.assertEqual(s.values, tuple(float(i) for i in range(1, 11)))

    def test_unmeasured_seeds_do_not_count(self):
        pm = [MetricValue.measured(1.0 + i) for i in range(7)] + [MetricValue.unmeasured("x")] * 5
        r = rb.summarize_seeds(pm, 10)
        self.assertIsInstance(r, rb.InsufficientEvidence)
        self.assertEqual((r.n_measured, r.n_required), (7, 10))

    def test_per_seed_must_be_metricvalues(self):
        with self.assertRaises(ValueError):
            rb.summarize_seeds([1.0] * 12, 10)

    def test_duplicate_seeds_rejected(self):
        with self.assertRaises(ValueError):
            rb.seed_sensitivity_probe(lambda s: 1.0, (5,) * 12, CFG)
        with self.assertRaises(ValueError):
            rb.seed_sensitivity_probe(lambda s: 1.0, (1, 2, 3, 2), CFG)

    def test_probe_with_one_seed_is_insufficient_scorecard(self):
        sc = rb.seed_sensitivity_probe(lambda s: 7.0, (1,), CFG)
        self.assertIs(sc.status, PS.INSUFFICIENT_EVIDENCE)
        self.assertIsNone(sc.summary)
        self.assertIsNotNone(sc.insufficient)
        self.assertIn(EvidenceClass.UNKNOWN, sc.evidence_labels)
        self.assertNotIn(EvidenceClass.TOY_RESULT, sc.evidence_labels)
        self.assertEqual(len(sc.per_seed), 1)           # the vector is kept; no statistic derived from it

    def test_scorecard_cannot_carry_summary_below_minimum(self):
        sc = sc_simple()
        small = rb.SeedSummary.from_values([1.0, 2.0, 3.0])
        with self.assertRaises(ValueError):
            dataclasses.replace(sc, summary=small)                       # mismatches per-seed values
        three = rb.seed_sensitivity_probe(lambda s: float(s % 7), SEEDS[:3], rb.ProbeConfig(3))
        self.assertIsNotNone(three.summary)
        with self.assertRaises(ValueError):
            dataclasses.replace(three, min_seeds=10)                      # 3 measured < 10 required
        with self.assertRaises(ValueError):
            dataclasses.replace(sc, summary=None)                         # neither summary nor insufficient
        with self.assertRaises(ValueError):
            dataclasses.replace(sc, insufficient=rb.InsufficientEvidence(1, 10, "forged"))   # both set
        with self.assertRaises(ValueError):
            dataclasses.replace(sc, status=PS.INSUFFICIENT_EVIDENCE)      # status contradicts summary

    def test_every_probe_refuses_one_and_two_seeds(self):
        """The rule is enforced across the whole API, not only in the seed probe."""
        for n in (0, 1, 2):
            seeds = SEEDS[:n]
            cards = [rb.seed_sensitivity_probe(lambda s: 1.0, seeds, CFG),
                     rb.probe_missing_inputs(rb.mse_fsum, seeds, CFG)]
            cards += [rb.probe_shift(rb.mse_fsum, sp, seeds, CFG) for sp in rb.standard_shifts()]
            cards += [rb.probe_precision(k, p, seeds, CFG) for k, p in
                      (("magnitude", 0), ("cancellation", 8), ("accumulation", 100))]
            for c in cards:
                self.assertIs(c.status, PS.INSUFFICIENT_EVIDENCE, c.probe_id)
                self.assertIsNone(c.summary, c.probe_id)
                self.assertNotIn("n_violations", c.details)             # no verdict-like facts from <min seeds
                self.assertNotIn("max_rel_dev", c.details)
                self.assertNotIn("max_stability_rel_err", c.details)

    def test_unmeasured_outcomes_are_recorded_not_defaulted(self):
        def flaky(seed):
            if seed % 2:
                raise ValueError("no outcome")
            return 1.0 + (seed % 5)
        sc = rb.seed_sensitivity_probe(flaky, SEEDS, CFG)
        n_bad = sum(not m.is_measured for m in sc.per_seed)
        self.assertGreater(n_bad, 0)
        for m in sc.per_seed:
            if not m.is_measured:
                self.assertIn("no outcome", m.reason)
                self.assertNotEqual(m, MetricValue.measured(0.0))
        self.assertIn(EvidenceClass.UNKNOWN, sc.evidence_labels)
        for bad in (lambda s: 1, lambda s: True, lambda s: math.nan, lambda s: None):
            c = rb.seed_sensitivity_probe(bad, SEEDS, CFG)
            self.assertTrue(all(not m.is_measured for m in c.per_seed))
            self.assertIs(c.status, PS.INSUFFICIENT_EVIDENCE)

    def test_seed_probe_distribution_and_zero_variance_flag(self):
        sc = sc_simple(f=lambda s: float(s % 5))
        self.assertEqual(sc.summary.n, 12)
        self.assertEqual(sc.summary.values, tuple(float(s % 5) for s in SEEDS))
        const = rb.seed_sensitivity_probe(lambda s: 2.5, SEEDS, CFG)
        self.assertEqual(const.summary.sd, 0.0)
        self.assertTrue(const.details["zero_variance_warning"])      # a seed-insensitive outcome is flagged
        self.assertFalse(sc.details.get("zero_variance_warning", False))

    def test_benchmark_backed_outcome(self):
        out = rb.benchmark_outcome(fixture_oracle_gated, "S")
        sc = rb.seed_sensitivity_probe(out, SEEDS[:10], CFG)
        self.assertIs(sc.status, PS.MEASURED)
        self.assertGreater(sc.details["n_distinct_values"], 1)         # S varies with the seed
        again = rb.seed_sensitivity_probe(out, SEEDS[:10], CFG)
        self.assertEqual(sc.content_hash(), again.content_hash())     # repeatable


class TestDeterminism(unittest.TestCase):
    def test_same_seeds_bit_identical(self):
        a, b = sc_simple(), sc_simple()
        self.assertEqual(a.to_json(), b.to_json())
        self.assertEqual(a.content_hash(), b.content_hash())
        self.assertEqual(a, b)
        self.assertEqual(hash(a), hash(b))
        for sp in rb.standard_shifts():
            x = rb.probe_shift(rb.mse_naive, sp, SEEDS, CFG)
            y = rb.probe_shift(rb.mse_naive, sp, SEEDS, CFG)
            self.assertEqual(x.content_hash(), y.content_hash(), sp.name)

    def test_different_seeds_differ(self):
        self.assertNotEqual(sc_simple().content_hash(), sc_simple(SEEDS_B).content_hash())
        x = rb.probe_shift(rb.mse_fsum, rb.shift_jitter(1e-6), SEEDS, CFG)
        y = rb.probe_shift(rb.mse_fsum, rb.shift_jitter(1e-6), SEEDS_B, CFG)
        self.assertNotEqual(x.content_hash(), y.content_hash())
        self.assertNotEqual(x.seed_digest, y.seed_digest)

    def test_global_rng_untouched(self):
        random.seed(1234)
        before = random.getstate()
        sc_simple()
        for sp in rb.standard_shifts():
            rb.probe_shift(rb.mse_naive, sp, SEEDS, CFG)
        rb.probe_missing_inputs(rb.mse_naive, SEEDS, CFG)
        rb.probe_precision("accumulation", 100, SEEDS, CFG)
        self.assertEqual(random.getstate(), before)

    def test_fixture_deterministic_and_valid(self):
        self.assertEqual(rb.make_measure_fixture(5), rb.make_measure_fixture(5))
        self.assertNotEqual(rb.make_measure_fixture(5), rb.make_measure_fixture(6))
        for s in range(200):
            fx = rb.make_measure_fixture(s)
            self.assertGreaterEqual(sum(fx.mask), 2)
            self.assertLess(sum(fx.mask), len(fx.mask))       # at least one masked-out row exists


class TestImmutability(unittest.TestCase):
    def setUp(self):
        self.src = {"a": {"b": [1, {"c": 2}], "s": "x"}, "n": 3.5}
        self.sc = rb.build_scorecard(probe_id="imm", probe_kind="demo", seeds=SEEDS,
                                     per_seed=[MetricValue.measured(float(i)) for i in range(12)], cfg=CFG,
                                     status_if_summarized=PS.MEASURED, details_always=self.src)

    def test_direct_assignment_and_deletion_raise(self):
        for name, val in (("probe_id", "z"), ("status", PS.MEASURED), ("details", {}), ("seeds", ()),
                          ("summary", None), ("per_seed", ())):
            with self.assertRaises(dataclasses.FrozenInstanceError, msg=name):
                setattr(self.sc, name, val)
        with self.assertRaises(dataclasses.FrozenInstanceError):
            delattr(self.sc, "probe_id")
        with self.assertRaises(dataclasses.FrozenInstanceError):
            self.sc.summary.mean = 0.0
        with self.assertRaises(AttributeError):
            self.sc.new_attribute = 1          # frozen + no instance dict path for new attrs via setattr

    def test_mapping_mutation_raises(self):
        with self.assertRaises(TypeError):
            self.sc.details["n"] = 1.0
        with self.assertRaises(TypeError):
            self.sc.details["new"] = 1
        with self.assertRaises(TypeError):
            del self.sc.details["n"]
        self.assertFalse(hasattr(self.sc.details, "update"))
        self.assertFalse(hasattr(self.sc.details, "setdefault"))

    def test_nested_containers_mutation_raises(self):
        a = self.sc.details["a"]
        with self.assertRaises(TypeError):
            a["x"] = 1                          # nested mapping
        with self.assertRaises(TypeError):
            a["s"] = "y"
        lst = a["b"]
        self.assertIsInstance(lst, tuple)       # list became a tuple
        with self.assertRaises(AttributeError):
            lst.append(3)
        with self.assertRaises(TypeError):
            lst[0] = 9
        with self.assertRaises(TypeError):
            lst[1]["c"] = 3                     # mapping nested inside the sequence nested inside the mapping
        for coll in (self.sc.seeds, self.sc.per_seed, self.sc.evidence_labels, self.sc.does_not_establish,
                     self.sc.summary.values):
            self.assertIsInstance(coll, tuple)
            with self.assertRaises(TypeError):
                coll[0] = coll[0]

    def test_defensive_copy_on_construction(self):
        h = self.sc.content_hash()
        self.src["a"]["b"].append(99)
        self.src["a"]["b"][1]["c"] = -1
        self.src["new"] = 1
        self.assertEqual(self.sc.content_hash(), h)
        self.assertEqual(self.sc.details["a"]["b"][1]["c"], 2)
        self.assertNotIn("new", self.sc.details)
        seeds = list(SEEDS)
        sc2 = rb.build_scorecard(probe_id="d", probe_kind="demo", seeds=seeds,
                                 per_seed=[MetricValue.measured(1.0 + i) for i in range(12)], cfg=CFG,
                                 status_if_summarized=PS.MEASURED, details_always={})
        seeds.append(1)
        self.assertEqual(len(sc2.seeds), 12)

    def test_replace_with_invalid_values_raises(self):
        sc = self.sc
        bad = [dict(probe_id=""), dict(probe_id="  "), dict(probe_kind=""), dict(status="MEASURED"),
               dict(seed_digest="0" * 64), dict(seeds=SEEDS[:11]), dict(seeds=(1, 1) + SEEDS[2:]),
               dict(min_seeds=2), dict(min_seeds=True),
               dict(per_seed=sc.per_seed[:5]), dict(per_seed=tuple(1.0 for _ in sc.seeds)),
               dict(evidence_labels=(EvidenceClass.SOURCE_OBSERVED, EvidenceClass.NOT_VALIDATED,
                                     EvidenceClass.TOY_RESULT)),
               dict(evidence_labels=(EvidenceClass.TOY_RESULT,)),          # drops NOT_VALIDATED
               dict(evidence_labels=(EvidenceClass.NOT_VALIDATED,)),       # drops TOY_RESULT though summary exists
               dict(evidence_labels=("TOY_RESULT", "NOT_VALIDATED", "NOT_AN_ENUM")),
               dict(does_not_establish=()), dict(does_not_establish=("only one",)),
               dict(details={"s": {1, 2}}), dict(details={"f": math.nan}), dict(details={"f": math.inf}),
               dict(details={1: "int key"}), dict(details={"o": object()})]
        for kw in bad:
            with self.assertRaises((ValueError, TypeError), msg=str(kw)[:80]):
                dataclasses.replace(sc, **kw)

    def test_replace_with_valid_value_gives_new_object_original_unchanged(self):
        h = self.sc.content_hash()
        sc2 = dataclasses.replace(self.sc, probe_id="other")
        self.assertEqual(sc2.probe_id, "other")
        self.assertEqual(self.sc.probe_id, "imm")
        self.assertEqual(self.sc.content_hash(), h)
        self.assertNotEqual(sc2.content_hash(), h)

    def test_object_setattr_bypass_is_honestly_detectable_not_impossible(self):
        """Python cannot prevent object.__setattr__. The freeze is 'no supported API path'; tampering is
        detectable because content_hash is recomputed from content, not cached."""
        sc = sc_simple()
        h = sc.content_hash()
        object.__setattr__(sc, "probe_id", "tampered")      # this DOES succeed; we do not claim otherwise
        self.assertEqual(sc.probe_id, "tampered")
        self.assertNotEqual(sc.content_hash(), h)
        # and the tamper is not re-validated: a frozen dataclass has no hook for that (documented limit)

    def test_serialization_consistent_with_schema(self):
        sc = sc_simple()
        d = sc.to_dict()
        self.assertEqual(sc.to_json(), canonical_json(d))
        self.assertEqual(json.loads(sc.to_json()), d)
        self.assertEqual(d["label"], TOY_LABEL)
        # Reference the symbol, not a literal. This assertion was hard-coded to "1" and went red
        # when SCHEMA_VERSION became "2" (the TOY_LABEL wording change). The point of the check is
        # that the card serializes the SAME version the schema module declares, which a literal
        # cannot express.
        self.assertEqual(d["schema_version"], SCHEMA_VERSION)
        self.assertRegex(sc.content_hash(), r"^[0-9a-f]{64}$")
        self.assertEqual(d["seed_digest"], sc.seed_digest)
        self.assertEqual(d["evidence_labels"], sorted(d["evidence_labels"]))
        self.assertIsInstance(d["details"], dict)             # thawed copy: mutating it cannot reach the card
        d["details"]["x"] = 1
        d["seeds"].append(0)
        self.assertEqual(sc.content_hash(), sc_simple().content_hash())

    def test_labels_and_non_claims_on_every_card(self):
        cards = [sc_simple(), rb.seed_sensitivity_probe(lambda s: 1.0, (1,), CFG),
                 rb.probe_shift(rb.mse_fsum, rb.shift_reorder_rows(), SEEDS, CFG),
                 rb.probe_missing_inputs(rb.mse_fsum, SEEDS, CFG), rb.probe_precision("accumulation", 50, SEEDS, CFG)]
        for c in cards:
            self.assertIn(EvidenceClass.NOT_VALIDATED, c.evidence_labels)
            self.assertNotIn(EvidenceClass.SOURCE_OBSERVED, c.evidence_labels)
            for std in rb.STANDARD_NON_CLAIMS:
                self.assertIn(std, c.does_not_establish)
            self.assertTrue(any("RFdiffusion" in s for s in c.does_not_establish))
            self.assertEqual(EvidenceClass.TOY_RESULT in c.evidence_labels, c.summary is not None)


class TestRecordMapping(unittest.TestCase):
    def test_summarized_maps_to_toy_result(self):
        sc = sc_simple()
        rec = rb.scorecard_to_record(sc, run_id="r1", timestamp_utc=TS)
        self.assertIs(rec.evidence_class, EvidenceClass.TOY_RESULT)
        self.assertEqual(rec.metrics["mean"], MetricValue.measured(sc.summary.mean))
        self.assertEqual(rec.metrics["n_seeds"], MetricValue.measured(12.0))
        self.assertEqual(rec.provenance.input_hashes["seed_list"], sc.seed_digest)
        self.assertEqual(rec.provenance.input_hashes["scorecard"], sc.content_hash())
        self.assertEqual(ExperimentRecord.from_json(rec.to_json()), rec)
        self.assertIn("must not be parsed", rec.notes)

    def test_insufficient_maps_to_unknown_with_unmeasured_stats(self):
        sc = rb.seed_sensitivity_probe(lambda s: 0.0, SEEDS[:2], CFG)
        rec = rb.scorecard_to_record(sc, run_id="r2", timestamp_utc=TS)
        self.assertIs(rec.evidence_class, EvidenceClass.UNKNOWN)
        for k in ("mean", "sd", "iqr", "min", "max"):
            self.assertFalse(rec.metrics[k].is_measured)
            self.assertEqual(rec.metrics[k].render(), "UNKNOWN")
            self.assertIn("INSUFFICIENT_EVIDENCE", rec.metrics[k].reason)
            self.assertNotEqual(rec.metrics[k], MetricValue.measured(0.0))
        self.assertEqual(rec.metrics["n_measured"], MetricValue.measured(2.0))   # a count of 2 is genuinely known

    def test_no_seed_scorecard_has_no_record(self):
        sc = rb.seed_sensitivity_probe(lambda s: 1.0, (), CFG)
        with self.assertRaises(ValueError):
            rb.scorecard_to_record(sc, run_id="r", timestamp_utc=TS)

    def test_status_is_structured_not_parsed_from_notes(self):
        sc = rb.probe_shift(row_weighted_mse, rb.shift_reorder_rows(), SEEDS, CFG)
        self.assertIsInstance(sc.status, PS)
        self.assertIs(sc.status, PS.INVARIANCE_DEFECT)
        rec = rb.scorecard_to_record(sc, run_id="r3", timestamp_utc=TS)
        self.assertEqual(rec.provenance.input_hashes["scorecard"], sc.content_hash())   # structured linkage


class TestInvariancesAndSensitivities(unittest.TestCase):
    def test_exact_invariances_hold_for_both_real_measures(self):
        for m in (rb.mse_fsum, rb.mse_naive):
            for sp in (rb.shift_reorder_rows(), rb.shift_masked_out_rows(), rb.shift_scale(2.0 ** 10)):
                if m is rb.mse_naive and sp.name == "reorder_rows" and not PY312:
                    continue   # environmental: needs CPython >= 3.12 compensated sum(); QA confirmed a plain loop flips it
                sc = rb.probe_shift(m, sp, SEEDS, CFG)
                self.assertIs(sc.status, PS.INVARIANCE_HOLDS, (m.__name__, sp.name))
                self.assertEqual(sc.details["n_violations"], 0)
                self.assertEqual(sc.details["n_bitwise_equal"], 12)      # exactly equal, not merely close
                self.assertEqual(sc.details["max_abs_dev"], 0.0)
                self.assertIs(sp.kind, SK.INVARIANCE_EXACT)

    def test_power_of_two_scaling_is_classified_exact_other_is_bounded(self):
        self.assertIs(rb.shift_scale(1024.0).kind, SK.INVARIANCE_EXACT)
        self.assertIs(rb.shift_scale(0.25).kind, SK.INVARIANCE_EXACT)
        self.assertIs(rb.shift_scale(1.7).kind, SK.SENSITIVITY_BOUNDED)
        self.assertIs(rb.shift_scale(3.0).kind, SK.SENSITIVITY_BOUNDED)

    def test_fsum_reorder_exact_even_on_adversarial_fixture(self):
        # fsum is correctly rounded, hence independent of order: bitwise equal by construction
        for big in (1e8, 1e16):
            ff = lambda s, b=big: rb.make_order_sensitive_fixture(s, b)
            sc = rb.probe_shift(rb.abs_bias_fsum if big == 1e16 else rb.mse_fsum, rb.shift_reorder_rows(), SEEDS,
                                CFG, fixture_factory=ff)
            self.assertIs(sc.status, PS.INVARIANCE_HOLDS)
            self.assertEqual(sc.details["n_bitwise_equal"], 12)

    def test_naive_signed_sum_reorder_depends_on_python_version_not_on_design(self):
        """CPython >= 3.12 sum() is compensated, so the stability path happens to be order-invariant on this
        fixture; the plain-loop reference is NOT, and is flagged as a DEFECT. Holding here is not a proof."""
        ff = lambda s: rb.make_order_sensitive_fixture(s, 1e16)
        plain = rb.probe_shift(rb.abs_bias_plain, rb.shift_reorder_rows(), SEEDS, CFG, fixture_factory=ff)
        self.assertIs(plain.status, PS.INVARIANCE_DEFECT)
        self.assertGreater(plain.details["n_violations"], 0)
        self.assertTrue(set(plain.details["violating_seeds"]) <= set(SEEDS))
        # hand reasoning: mean of [B, -B, six values in (0.5,1.5)] is ~0.6; a plain loop that adds small values
        # onto B ~ 1e16 (ulp 2) loses them, so some orders return a mean off by a large fraction of itself
        self.assertGreater(plain.details["max_rel_dev"], 0.05)
        if PY312:
            stab = rb.probe_shift(rb.abs_bias_naive, rb.shift_reorder_rows(), SEEDS, CFG, fixture_factory=ff)
            self.assertIs(stab.status, PS.INVARIANCE_HOLDS)

    def test_broken_measures_violating_invariance_are_detected(self):
        cases = [(row_weighted_mse, rb.shift_reorder_rows()),
                 (mask_ignoring_mse, rb.shift_masked_out_rows()),
                 (offset_mse, rb.shift_scale(2.0 ** 10))]
        for m, sp in cases:
            sc = rb.probe_shift(m, sp, SEEDS, CFG)
            self.assertIs(sc.status, PS.INVARIANCE_DEFECT, m.__name__)
            self.assertEqual(sc.details["n_violations"], 12, m.__name__)
            self.assertGreater(sc.details["max_abs_dev"], 0.0)

    def test_tolerance_tier_accepts_ulp_noise_but_rejects_real_defect(self):
        ok = rb.probe_shift(rb.mse_naive, rb.shift_reorder_rows(SK.INVARIANCE_TOLERANCE, 1e-12), SEEDS, CFG)
        self.assertIs(ok.status, PS.INVARIANCE_HOLDS)
        bad = rb.probe_shift(row_weighted_mse, rb.shift_reorder_rows(SK.INVARIANCE_TOLERANCE, 1e-12), SEEDS, CFG)
        self.assertIs(bad.status, PS.INVARIANCE_DEFECT)

    def test_expected_sensitivities_measured_nonzero_and_bounded(self):
        # Hand-reasoned caps (see robustness._cast_bound):
        #  translate 1000: element rounding <= 2^-53 * 1001 ~ 1.1e-13, so d=p-t carries <= 2.2e-13 absolute;
        #    relative MSE error <= 2 * 2.2e-13 / rms(d); rms(d) ~ 0.06  =>  <= ~7e-12 (x4 slack in the code).
        #  scale 1.7: relative error ~ few EPS / (rms/maxabs) ~ 1e-14 at most.
        #  jitter 1e-6: |rms' - rms| <= 1e-6 so relative MSE change <= 2e-6/rms ~ 3e-5.
        for m in (rb.mse_fsum, rb.mse_naive):
            caps = {"translate_1000.0": 1e-10, "scale_1.7": 1e-13, "column_offsets_3": 1e-11, "jitter_1e-06": 1e-4}
            for sp in rb.standard_shifts():
                if sp.name not in caps:
                    continue
                sc = rb.probe_shift(m, sp, SEEDS, CFG)
                d = sc.details
                self.assertIs(sc.status, PS.SENSITIVITY_WITHIN_BOUND, (m.__name__, sp.name))
                self.assertEqual(d["n_violations"], 0)
                self.assertLess(d["max_dev_over_bound"], 1.0)
                self.assertLess(d["max_rel_dev"], caps[sp.name], (m.__name__, sp.name))
                self.assertGreater(d["max_abs_dev"], 0.0, f"{sp.name}: expected a real, nonzero movement")
                self.assertLess(d["n_bitwise_equal"], d["n_measured"], sp.name)
        jit = rb.probe_shift(rb.mse_fsum, rb.shift_jitter(1e-6), SEEDS, CFG)
        self.assertGreater(jit.details["max_rel_dev"], 1e-8)             # jitter is a genuine perturbation

    def test_sensitivity_grows_with_perturbation_size(self):
        small = rb.probe_shift(rb.mse_fsum, rb.shift_jitter(1e-8), SEEDS, CFG).details["max_rel_dev"]
        large = rb.probe_shift(rb.mse_fsum, rb.shift_jitter(1e-4), SEEDS, CFG).details["max_rel_dev"]
        self.assertGreater(large, 100 * small)

    def test_bounded_sensitivity_failure_paths_fire(self):
        amp = rb.probe_shift(amplified_mse, rb.shift_jitter(1e-6), SEEDS, CFG)
        self.assertIs(amp.status, PS.SENSITIVITY_EXCEEDS_BOUND)
        self.assertGreater(amp.details["n_violations"], 0)
        self.assertGreater(amp.details["max_dev_over_bound"], 1.0)
        q = rb.probe_shift(quantizing_mse, rb.shift_translate(1000.0), SEEDS, CFG)
        self.assertIs(q.status, PS.SENSITIVITY_EXCEEDS_BOUND)
        self.assertGreater(q.details["max_rel_dev"], 1e-6)   # float32 rounding of x+1000 (~6e-5 abs) dwarfs the cap

    def test_measure_that_raises_on_shifted_input_is_unmeasured_not_zero(self):
        def fragile(p, t, m):
            if any(abs(x) > 500 for r in p for x in r):
                raise ValueError("too large")
            return rb.mse_fsum(p, t, m)
        sc = rb.probe_shift(fragile, rb.shift_translate(1000.0), SEEDS, CFG)
        self.assertTrue(all(not m.is_measured and "too large" in m.reason for m in sc.per_seed))
        self.assertIs(sc.status, PS.INSUFFICIENT_EVIDENCE)
        self.assertIn(EvidenceClass.UNKNOWN, sc.evidence_labels)

    def test_expected_value_must_be_positive(self):
        sc = rb.probe_shift(lambda p, t, m: 0.0 + 0.0, rb.shift_reorder_rows(), SEEDS, CFG)
        self.assertTrue(all(not m.is_measured for m in sc.per_seed))   # relative deviation undefined => unmeasured

    def test_error_register_cross_references_present(self):
        self.assertTrue(any("ER-09" in x for x in
                            rb.probe_shift(rb.mse_fsum, rb.shift_reorder_rows(), SEEDS, CFG).details["error_register"]))
        self.assertTrue(any("ER-02" in x for x in
                            rb.probe_shift(rb.mse_fsum, rb.shift_masked_out_rows(), SEEDS, CFG).details["error_register"]))


class TestMissingInputs(unittest.TestCase):
    def test_real_measures_reject_every_case(self):
        for m in (rb.mse_naive, rb.mse_fsum):
            sc = rb.probe_missing_inputs(m, SEEDS, CFG)
            self.assertIs(sc.status, PS.MISSING_INPUT_HANDLED, m.__name__)
            self.assertEqual(sc.details["n_silent_value_total"], 0)
            self.assertEqual(sc.summary.maximum, 0.0)
            table = sc.details["case_table"]
            self.assertEqual(set(table), set(rb.missing_input_cases(rb.make_measure_fixture(0))))
            for case, row in table.items():
                self.assertEqual(row["raised"], 12, case)
                self.assertEqual(row["silent_value"], 0, case)
            self.assertTrue(all(sc.details["structural_checks"].values()))
            rb.assert_no_silent_default(m)                       # returns None, does not raise

    def test_each_named_absence_is_covered(self):
        cases = set(rb.missing_input_cases(rb.make_measure_fixture(0)))
        for needed in ("absent_rows", "absent_columns", "all_false_mask", "empty_mask", "ragged_columns",
                       "absent_rows_prediction_only", "missing_value_none", "nan_in_masked_out_row"):
            self.assertIn(needed, cases)

    def test_guarded_gives_unmeasured_with_reason_never_zero(self):
        fx = rb.make_measure_fixture(1)
        g = rb.guarded(rb.mse_fsum)
        for name, args in rb.missing_input_cases(fx).items():
            r = g(*args)
            self.assertFalse(r.is_measured, name)
            self.assertTrue(r.reason, name)
            self.assertNotEqual(r, MetricValue.measured(0.0), name)
            self.assertEqual(r.render(), "UNKNOWN")
            self.assertIsNone(r.value)
        # a genuine zero is a measured zero and is distinguishable from absence
        zero = g(fx.target, fx.target, fx.mask)
        self.assertTrue(zero.is_measured)
        self.assertEqual(zero, MetricValue.measured(0.0))
        self.assertNotEqual(zero, g(fx.pred, fx.target, (False,) * len(fx.mask)))

    def test_all_false_mask_is_loud_in_the_stability_validator(self):
        fx = rb.make_measure_fixture(1)
        with self.assertRaises(stability.EmptyMaskError):                 # ER-01 analogue: never a loss of 0
            rb.mse_naive(fx.pred, fx.target, (False,) * len(fx.mask))

    def test_empty_seed_list_is_explicit(self):
        sc = rb.seed_sensitivity_probe(lambda s: 1.0, (), CFG)
        self.assertIs(sc.status, PS.INSUFFICIENT_EVIDENCE)
        self.assertIsNone(sc.summary)
        self.assertEqual(sc.insufficient.n_measured, 0)
        self.assertEqual(sc.per_seed, ())
        with self.assertRaises(rb.InsufficientEvidenceError):
            rb.require_summary(rb.summarize_seeds([], 10))

    def test_missing_arm(self):
        arms = {"C0": MetricValue.measured(1.0), "E": MetricValue.measured(1.0), "U": MetricValue.unmeasured("no run")}
        absent = rb.arm_difference(arms, "X", "C0")
        self.assertFalse(absent.is_measured)
        self.assertIn("'X'", absent.reason)
        self.assertNotEqual(absent, MetricValue.measured(0.0))
        self.assertIn("absent", rb.arm_difference(arms, "E", "Y").reason)
        un = rb.arm_difference(arms, "U", "C0")
        self.assertFalse(un.is_measured)
        self.assertIn("no run", un.reason)
        same = rb.arm_difference(arms, "E", "C0")                          # equal arms: a measured zero
        self.assertEqual(same, MetricValue.measured(0.0))
        self.assertNotEqual(same, absent)
        with self.assertRaises(ValueError):
            rb.arm_difference({"E": 1.0, "C0": 2.0}, "E", "C0")            # bare floats are refused

    def test_silent_default_is_detected_and_fails_loudly(self):
        with self.assertRaises(rb.SilentDefaultError) as cm:
            rb.assert_no_silent_default(zero_on_failure)
        self.assertIn("SILENT ZERO", str(cm.exception))
        with self.assertRaises(rb.SilentDefaultError) as cm2:
            rb.assert_no_silent_default(default_on_all_false)
        self.assertIn("all_false_mask", str(cm2.exception))
        self.assertNotIn("absent_rows", str(cm2.exception))                # only the one substituted case is named
        with self.assertRaises(rb.SilentDefaultError):
            rb.assert_no_silent_default(lenient_truthiness)

    def test_probe_scorecard_reports_defect_for_silent_defaults(self):
        sc = rb.probe_missing_inputs(zero_on_failure, SEEDS, CFG)
        self.assertIs(sc.status, PS.SILENT_DEFAULT_DEFECT)
        n_cases = len(sc.details["case_table"])
        self.assertEqual(sc.details["n_silent_value_total"], 12 * n_cases)
        self.assertEqual(sc.summary.minimum, float(n_cases))
        one = rb.probe_missing_inputs(default_on_all_false, SEEDS, CFG)
        self.assertIs(one.status, PS.SILENT_DEFAULT_DEFECT)
        self.assertEqual(one.details["n_silent_value_total"], 12)
        self.assertEqual(one.details["case_table"]["all_false_mask"]["silent_value"], 12)
        self.assertEqual(one.details["case_table"]["absent_rows"]["silent_value"], 0)


class TestNumericalStability(unittest.TestCase):
    def test_unknown_kind_raises(self):
        with self.assertRaises(ValueError):
            rb.probe_precision("nonsense", 1, SEEDS, CFG)

    def test_moderate_magnitudes_are_accurate(self):
        # <= 24 terms, each with <= 2 roundings of relative size 2^-53, sum of positives: relative error
        # <= ~ (2 + 24) * 2^-53 ~ 3e-15; observed ~2e-16
        for e in (0, 100, -100, 150):
            sc = rb.probe_precision("magnitude", e, SEEDS, CFG)
            self.assertIs(sc.status, PS.PRECISION_OK, e)
            self.assertLess(sc.details["max_stability_rel_err"], 3e-15, e)

    def test_subnormal_range_loses_precision_quantified(self):
        # Squares fall below 2.2e-308 when |d| ~ 1e-154. Spacing of subnormals is 4.9e-324, so each square
        # carries absolute error <= 2.5e-324. mean(d^2) ~ 3.3e-3 * 10^(2e), hence relative error
        # <~ 2.5e-324 / (3.3e-3 * 10^(2e)) up to a seed-dependent factor ~3: e=-156 -> ~7e-10..2e-9;
        # e=-158 -> ~7e-6..2e-5. Each 2 decades of e costs ~4 decades of accuracy.
        e156 = rb.probe_precision("magnitude", -156, SEEDS, CFG)
        e158 = rb.probe_precision("magnitude", -158, SEEDS, CFG)
        a, b = e156.details["max_stability_rel_err"], e158.details["max_stability_rel_err"]
        self.assertIs(e156.status, PS.PRECISION_LOSS)
        self.assertTrue(1e-12 < a < 1e-7, a)
        self.assertTrue(1e-8 < b < 1e-3, b)
        self.assertTrue(1e2 < b / a < 1e6, b / a)

    def test_overflow_is_loud_not_silent(self):
        # |d| ~ 0.1 * 1e155 squares to ~1e308 > 1.8e308 for the sum: validators raise NonFiniteError
        sc = rb.probe_precision("magnitude", 155, SEEDS, CFG)
        self.assertIs(sc.status, PS.INSUFFICIENT_EVIDENCE)
        self.assertTrue(all(not m.is_measured and "NonFinite" in m.reason for m in sc.per_seed))
        self.assertIn(EvidenceClass.UNKNOWN, sc.evidence_labels)

    def test_deep_underflow_is_not_a_silent_zero_in_the_validators(self):
        sc = rb.probe_precision("magnitude", -170, SEEDS, CFG)
        if hasattr(stability, "UnderflowError"):
            # d ~ 1e-171, d^2 ~ 1e-342 < 4.9e-324: current validators refuse instead of returning 0.0
            self.assertIs(sc.status, PS.INSUFFICIENT_EVIDENCE)
            self.assertTrue(all("Underflow" in m.reason for m in sc.per_seed))
        else:   # older tree: the same input silently returned 0.0, i.e. 100% relative error with no signal
            self.assertEqual(sc.details["n_silent_zero"], 12)
            self.assertEqual(sc.details["max_stability_rel_err"], 1.0)

    def test_silent_zero_detector_fires_on_a_measure_without_the_guard(self):
        def unguarded(p, t, m):
            tot, n = 0.0, 0
            for pr, tr, u in zip(p, t, m):
                if u:
                    for a, b in zip(pr, tr):
                        tot += (a - b) * (a - b)
                        n += 1
            return tot / n
        sc = rb.probe_precision("magnitude", -170, SEEDS, CFG, measure=unguarded)
        self.assertIs(sc.status, PS.PRECISION_LOSS)
        self.assertEqual(sc.details["n_silent_zero"], 12)
        self.assertEqual(sc.details["max_stability_rel_err"], 1.0)       # returned 0.0, exact value > 0
        self.assertTrue(all(m.value == 1.0 for m in sc.per_seed))

    def test_cancellation_plain_loop_loss_quantified_and_within_worst_case(self):
        # values [M, b, -M], b in (0.5,1.5): the single rounding fl(M+b) has error <= u*(M+b), the second add
        # is exact (Sterbenz), so rel error <= u*(M+b)/b (+2u for the division) -- the bound in the code.
        # Loss becomes total once ulp(M)/2 > b, i.e. M > ~2^53 ~ 9e15.
        errs = {}
        for e in (0, 8, 12, 15, 16, 17):
            sc = rb.probe_precision("cancellation", e, SEEDS, CFG)
            errs[e] = sc.details["max_plain_loop_rel_err"]
            self.assertLessEqual(sc.details["max_plain_over_bound"], 1.0, e)       # never exceeds worst case
            self.assertLessEqual(sc.details["max_fsum_rel_err"], EPS, e)           # exact sum is b: 1 rounding
        self.assertLess(errs[0], 1e-15)
        self.assertTrue(1e-10 < errs[8] < 1e-6, errs[8])
        self.assertTrue(1e-6 < errs[12] < 1e-2, errs[12])
        self.assertTrue(errs[8] < errs[12] < errs[15] < errs[16])
        self.assertGreaterEqual(errs[16], 0.5)           # beyond 2^53 the unit-sized term is (mostly) lost
        self.assertGreaterEqual(errs[17], 0.5)
        sc16 = rb.probe_precision("cancellation", 16, SEEDS, CFG)
        self.assertIs(sc16.status, PS.PRECISION_OK if PY312 else PS.PRECISION_LOSS)

    @unittest.skipUnless(PY312, "sum() is compensated from CPython 3.12; older versions behave like the plain loop")
    def test_stability_path_is_compensated_on_312_but_that_is_environmental(self):
        for e in (8, 16, 20):
            sc = rb.probe_precision("cancellation", e, SEEDS, CFG)
            self.assertLess(sc.details["max_stability_rel_err"], 1e-15)
            self.assertEqual(sc.details["python_version"], ".".join(map(str, sys.version_info[:3])))

    def test_long_accumulation_growth(self):
        # positive summands: worst-case relative error of a plain left-to-right sum <= n*u/(1-n*u) (the bound
        # in the code); random-walk behaviour typically ~ sqrt(n)*u, far below worst case, and growing with n.
        res = {}
        for n in (10, 1000, 10000):
            sc = rb.probe_precision("accumulation", n, SEEDS, CFG)
            res[n] = sc.details
            self.assertLessEqual(res[n]["max_plain_over_bound"], 1.0, n)
            self.assertLessEqual(res[n]["max_fsum_rel_err"], EPS, n)
            self.assertIs(sc.status, PS.PRECISION_OK if PY312 else sc.status)
        self.assertGreater(res[10000]["max_plain_loop_rel_err"], res[10]["max_plain_loop_rel_err"])
        self.assertGreater(res[10000]["max_plain_loop_rel_err"], 1e-15)    # real, quantified loss for the plain loop
        self.assertLess(res[10000]["max_plain_over_bound"], 0.1)           # worst case is not what happens
        if PY312:
            self.assertLess(res[10000]["max_stability_rel_err"], 4 * EPS)

    def test_tolerance_parameter_changes_status_only(self):
        loose = rb.probe_precision("magnitude", -156, SEEDS, CFG, tol=1e-6)
        tight = rb.probe_precision("magnitude", -156, SEEDS, CFG, tol=1e-12)
        self.assertIs(loose.status, PS.PRECISION_OK)
        self.assertIs(tight.status, PS.PRECISION_LOSS)
        self.assertEqual(loose.per_seed, tight.per_seed)

    def test_error_register_cross_references_and_sweep(self):
        sweep = rb.precision_sweep("cancellation", (0, 8, 12), SEEDS, CFG)
        self.assertEqual(len(sweep), 3)
        self.assertIsInstance(sweep, tuple)
        self.assertEqual(len({s.probe_id for s in sweep}), 3)
        for s in sweep:
            self.assertTrue(any("ER-09" in x for x in s.details["error_register"]))
        self.assertTrue(any("ER-02" in x for x in
                            rb.probe_precision("magnitude", 0, SEEDS, CFG).details["error_register"]))

    def test_exact_reference_helpers(self):
        from fractions import Fraction
        self.assertEqual(rb._exact_sum([0.1] * 3), 3 * Fraction(0.1))
        self.assertEqual(rb._exact_sum([1e16, 1.0, -1e16]), Fraction(1))   # the float sum is 0.0 in a plain loop
        self.assertEqual(rb.plain_loop_mean([1e16, 1.0, -1e16]), 0.0)
        self.assertEqual(rb.exact_masked_mse(((1.0,), (3.0,)), ((0.0,), (0.0,)), (True, True)), Fraction(5))
        with self.assertRaises(ValueError):
            rb._rel_err(1.0, Fraction(0))


class TestQAHardening(unittest.TestCase):
    """Pins the structural guards (mutants that survived the first QA) and the documented limits."""

    def insufficient_card(self):
        return rb.seed_sensitivity_probe(lambda s: 4.0, SEEDS[:1], CFG)

    # --- InsufficientEvidence and seed validation
    def test_insufficient_evidence_requires_n_below_required(self):
        for n, req in ((5, 5), (6, 5), (10, 3)):
            with self.assertRaises(ValueError):
                rb.InsufficientEvidence(n, req, "r")
        with self.assertRaises(ValueError):
            rb.InsufficientEvidence(1, 5, "  ")
        rb.InsufficientEvidence(4, 5, "ok")

    def test_seed_type_validation(self):
        for bad in (True, 5.0, -1, "3", None, 2 ** 64):
            with self.assertRaises(ValueError, msg=repr(bad)):
                rb.seed_sensitivity_probe(lambda s: 1.0, (bad, 2, 3), CFG)
        with self.assertRaises(ValueError):
            rb.probe_shift(rb.mse_fsum, rb.shift_reorder_rows(), (1, 2, True), CFG)
        with self.assertRaises(ValueError):
            rb.build_scorecard(probe_id="x", probe_kind="k", seeds=(1.5,), per_seed=[MetricValue.measured(1.0)],
                               cfg=CFG, status_if_summarized=PS.MEASURED, details_always={})

    # --- Scorecard consistency checks for insufficient / unmeasured cards
    def test_insufficient_card_counts_status_and_labels_are_checked(self):
        c = self.insufficient_card()
        self.assertEqual(c.insufficient.n_measured, 1)
        for kw in (dict(insufficient=rb.InsufficientEvidence(0, 10, "wrong count")),
                   dict(insufficient=rb.InsufficientEvidence(1, 9, "wrong required")),
                   dict(status=PS.MEASURED), dict(status=PS.INVARIANCE_HOLDS),
                   dict(evidence_labels=(EvidenceClass.NOT_VALIDATED,)),                  # drops UNKNOWN
                   dict(evidence_labels=(EvidenceClass.NOT_VALIDATED, EvidenceClass.TOY_RESULT))):
            with self.assertRaises(ValueError, msg=str(kw)):
                dataclasses.replace(c, **kw)

    def test_unknown_label_required_when_any_seed_unmeasured(self):
        def flaky(seed):
            if seed == SEEDS[0]:
                raise ValueError("gone")
            return float(seed % 9)
        c = rb.seed_sensitivity_probe(flaky, SEEDS, rb.ProbeConfig(3))
        self.assertIsNotNone(c.summary)
        self.assertIn(EvidenceClass.UNKNOWN, c.evidence_labels)
        with self.assertRaises(ValueError):
            dataclasses.replace(c, evidence_labels=(EvidenceClass.NOT_VALIDATED, EvidenceClass.TOY_RESULT))

    # --- nested validation: replace() laundering, subclass skipping
    def test_replace_cannot_launder_a_tampered_summary(self):
        card = sc_simple()
        object.__setattr__(card.summary, "mean", 42.0)      # honest bypass; now the nested object is forged
        with self.assertRaises(ValueError):
            dataclasses.replace(card)
        with self.assertRaises(ValueError):
            dataclasses.replace(card, probe_id="other")
        fresh = sc_simple()
        object.__setattr__(fresh.summary, "values", fresh.summary.values[:2])
        with self.assertRaises(ValueError):
            dataclasses.replace(fresh)

    def test_tampered_insufficient_object_is_revalidated(self):
        c = self.insufficient_card()
        object.__setattr__(c.insufficient, "n_measured", 99)
        with self.assertRaises(ValueError):
            dataclasses.replace(c)

    def test_subclass_can_skip_its_own_check_but_scorecard_refuses_it(self):
        @dataclasses.dataclass(frozen=True)
        class Sub(rb.SeedSummary):
            def __post_init__(self):          # documented bypass: subclass skips validation
                pass
        lone = Sub(1, 3.0, 0.0, 3.0, 3.0, 0.0, 3.0, 3.0, (3.0,))     # a 1-value "summary" DOES exist
        self.assertEqual(lone.n, 1)
        card = sc_simple()
        with self.assertRaises(ValueError):
            dataclasses.replace(card, summary=lone)
        good_vals = card.summary.values
        sub_ok = Sub(*[getattr(card.summary, f) for f in ("n", "mean", "sd", "q1", "q3", "iqr", "minimum", "maximum")],
                     values=good_vals)                                # statistically correct but wrong type
        with self.assertRaises(ValueError):
            dataclasses.replace(card, summary=sub_ok)

        @dataclasses.dataclass(frozen=True)
        class SubI(rb.InsufficientEvidence):
            def __post_init__(self):
                pass
        with self.assertRaises(ValueError):
            dataclasses.replace(self.insufficient_card(), insufficient=SubI(1, 10, "sub"))

    # --- documented narrower truths
    def test_repeated_values_are_counted_not_deduplicated_by_summary_functions(self):
        """Documented limit: summarize_seeds/from_values see values, not seeds. Only the probe path rejects
        duplicate SEEDS. This pins the narrower claim so the module cannot silently drift to the wider one."""
        s = rb.summarize_seeds([MetricValue.measured(0.5)] * 10, 10)
        self.assertIsInstance(s, rb.SeedSummary)
        self.assertEqual(s.sd, 0.0)
        self.assertIsInstance(rb.SeedSummary.from_values([1.0] * 3), rb.SeedSummary)
        with self.assertRaises(ValueError):                       # ...whereas the probe path refuses repeats
            rb.seed_sensitivity_probe(lambda s: 0.5, (7,) * 10, CFG)

    def test_constant_outcome_is_not_downgraded_but_flagged(self):
        c = rb.seed_sensitivity_probe(lambda s: 0.5, SEEDS[:10], CFG)
        self.assertIs(c.status, PS.MEASURED)
        self.assertEqual(c.summary.sd, 0.0)
        self.assertTrue(c.details["zero_variance_warning"])
        self.assertIn(EvidenceClass.TOY_RESULT, c.evidence_labels)     # deliberate: see module doc

    def test_insufficient_card_keeps_raw_per_seed_but_no_statistic_or_verdict(self):
        c = rb.probe_missing_inputs(zero_on_failure, SEEDS[:1], CFG)
        self.assertIs(c.status, PS.INSUFFICIENT_EVIDENCE)
        self.assertEqual(len(c.per_seed), 1)
        self.assertTrue(c.per_seed[0].is_measured)                    # the lone raw datum is retained (documented)
        d = c.to_dict()
        self.assertIsNone(d["summary"])
        self.assertNotIn("n_silent_value_total", d["details"])        # nothing derived from it
        self.assertNotIn("case_table", d["details"])
        self.assertIn(rb.STANDARD_NON_CLAIMS[-1], c.does_not_establish)

    def test_python_version_recorded_on_every_card(self):
        cards = [sc_simple(), self.insufficient_card(),
                 rb.probe_shift(rb.mse_fsum, rb.shift_reorder_rows(), SEEDS, CFG),
                 rb.probe_missing_inputs(rb.mse_fsum, SEEDS, CFG), rb.probe_precision("accumulation", 20, SEEDS, CFG)]
        for c in cards:
            self.assertEqual(c.details["python_version"], ".".join(map(str, sys.version_info[:3])))

    def test_structural_checks_are_labelled_as_library_checks(self):
        d = rb.probe_missing_inputs(zero_on_failure, SEEDS, CFG).details
        self.assertIn("NOT the measure", d["structural_checks_scope"])
        self.assertTrue(all(d["structural_checks"].values()))         # true even for a defective measure

    # --- +-inf in the missing-input cases
    def test_infinities_are_enumerated_and_substitution_is_caught(self):
        cases = rb.missing_input_cases(rb.make_measure_fixture(0))
        for k in ("inf_in_selected_row", "neg_inf_in_selected_row", "inf_in_masked_out_row"):
            self.assertIn(k, cases)
            self.assertTrue(any(math.isinf(x) for r in cases[k][0] for x in r))

        def zero_on_inf(p, t, m):
            if any(isinstance(x, float) and math.isinf(x) for r in p for x in r):
                return 0.0
            return rb.mse_fsum(p, t, m)
        sc = rb.probe_missing_inputs(zero_on_inf, SEEDS, CFG)
        self.assertIs(sc.status, PS.SILENT_DEFAULT_DEFECT)
        tab = sc.details["case_table"]
        for k in ("inf_in_selected_row", "neg_inf_in_selected_row", "inf_in_masked_out_row"):
            self.assertEqual(tab[k]["silent_value"], 12, k)
        self.assertEqual(tab["nan_in_selected_row"]["silent_value"], 0)
        with self.assertRaises(rb.SilentDefaultError):
            rb.assert_no_silent_default(zero_on_inf)
        for m in (rb.mse_naive, rb.mse_fsum):                         # real measures reject infinities
            self.assertEqual(rb.probe_missing_inputs(m, SEEDS, CFG).details["case_table"]["inf_in_masked_out_row"]["raised"], 12)

    # --- mse_fsum guards (mutants: underflow guard and finite check removed)
    def test_mse_fsum_refuses_underflow_overflow_and_sum_overflow(self):
        with self.assertRaises(stability.StabilityError) as cm:
            rb.mse_fsum(((1e-170,), (1.0,)), ((2e-170,), (1.0,)), (True, False))   # d^2 ~ 1e-340 -> 0.0
        self.assertIn("underflow", str(cm.exception).lower())
        if hasattr(stability, "UnderflowError"):
            with self.assertRaises(stability.UnderflowError):
                rb.mse_fsum(((1e-170,),), ((2e-170,),), (True,))
        with self.assertRaises(stability.NonFiniteError):                # d = 1e200 -> d*d = inf
            rb.mse_fsum(((1e200,), (0.0,)), ((0.0,), (0.0,)), (True, True))
        with self.assertRaises(stability.NonFiniteError):                # each square 1e308 finite; sum of 4 overflows
            rb.mse_fsum(((1e154,),) * 4, ((0.0,),) * 4, (True,) * 4)
        # equal nonzero inputs are a genuine 0.0, not underflow
        self.assertEqual(rb.mse_fsum(((1e-170,), (2.0,)), ((1e-170,), (2.0,)), (True, True)), 0.0)

    # --- fixture invariants (mutant: all-True mask possible)
    def test_fixture_always_has_a_masked_out_row_even_for_few_rows(self):
        for rows in (4, 5):
            for s in range(1500):
                fx = rb.make_measure_fixture(s, rows=rows)
                self.assertTrue(any(not b for b in fx.mask), (rows, s))
                self.assertGreaterEqual(sum(fx.mask), 2, (rows, s))

    # --- bound tightness (mutant: cast bound loosened by 1e6)
    def test_cast_bounds_are_tight_enough_to_be_informative(self):
        # observed deviation is 1-30% of the hand-derived cap; a cap 1e6 looser would give ratios ~1e-8
        for sp in (rb.shift_scale(1.7), rb.shift_translate(1000.0), rb.shift_column_offsets((3.0, -7.0, 0.5)),
                   rb.shift_jitter(1e-6)):
            r = rb.probe_shift(rb.mse_fsum, sp, SEEDS, CFG).details["max_dev_over_bound"]
            self.assertTrue(1e-3 < r < 1.0, (sp.name, r))

    def test_insufficient_ordering_guard(self):
        """A forged card claiming INSUFFICIENT while holding >= min_seeds measured values is refused (the only
        guard for that state), at the object level and inside a card."""
        c = self.insufficient_card()
        for n, req in ((10, 10), (11, 10)):
            forged = rb.InsufficientEvidence(1, 10, "x")
            object.__setattr__(forged, "n_measured", n)
            object.__setattr__(forged, "n_required", req)
            with self.assertRaises(ValueError):
                rb._recheck_insufficient(forged)
            with self.assertRaises(ValueError):
                dataclasses.replace(c, insufficient=forged)
        full = rb.seed_sensitivity_probe(lambda s: float(s % 5), SEEDS, CFG)
        forged = rb.InsufficientEvidence(1, 10, "x")
        object.__setattr__(forged, "n_measured", 12)
        with self.assertRaises(ValueError):
            dataclasses.replace(full, summary=None, insufficient=forged, status=PS.INSUFFICIENT_EVIDENCE,
                                evidence_labels=(EvidenceClass.NOT_VALIDATED, EvidenceClass.UNKNOWN))

    def test_raw_observation_non_claim_is_pinned(self):
        self.assertIn("raw observations only", rb.STANDARD_NON_CLAIMS[-1])
        self.assertIn("support no claim", rb.STANDARD_NON_CLAIMS[-1])
        self.assertIn("INSUFFICIENT_EVIDENCE", rb.STANDARD_NON_CLAIMS[-1])
        self.assertEqual(len(rb.STANDARD_NON_CLAIMS), 6)
        for c in (self.insufficient_card(), sc_simple()):
            self.assertIn(rb.STANDARD_NON_CLAIMS[-1], c.does_not_establish)
        with self.assertRaises(ValueError):   # dropping that entry from a card is refused
            c = self.insufficient_card()
            dataclasses.replace(c, does_not_establish=tuple(x for x in c.does_not_establish
                                                                if x != rb.STANDARD_NON_CLAIMS[-1]))

    def test_extreme_mixed_sign_input_raises_valueerror_family(self):
        big = ((1.7e308,), (1.7e308,), (-1.7e308,))
        for m in (rb.abs_bias_fsum, rb.abs_bias_naive, rb.mse_fsum, rb.mse_naive):
            with self.assertRaises(ValueError, msg=m.__name__):
                m(big, ((0.0,),) * 3, (True,) * 3)

    def test_from_values_wraps_unrepresentable_and_bad_types_in_valueerror(self):
        for bad in ([10 ** 400] * 3, [-10 ** 400, 1.0, 2.0], [None, 1.0, 2.0], [object(), 1.0, 2.0]):
            with self.assertRaises(ValueError, msg=repr(bad)[:30]):
                rb.SeedSummary.from_values(bad)
            try:
                rb.SeedSummary.from_values(bad)
            except ValueError as e:
                self.assertNotIsInstance(e, OverflowError)
        with self.assertRaises(ValueError):          # same via summarize_seeds' inputs is MetricValue-only
            rb.summarize_seeds([10 ** 400] * 3, 3)

    def test_zero_variance_warning_is_exact_set_test_not_sd_and_scale_independent(self):
        tiny = 5e-324     # smallest subnormal
        c = rb.seed_sensitivity_probe(lambda s: tiny, SEEDS[:10], CFG)
        self.assertTrue(c.details["zero_variance_warning"])
        steps = {s: tiny * (1 + i % 3) for i, s in enumerate(SEEDS[:10])}
        d = rb.seed_sensitivity_probe(lambda s: steps[s], SEEDS[:10], CFG)
        self.assertFalse(d.details["zero_variance_warning"])        # non-constant sample is never flagged
        self.assertEqual(d.details["n_distinct_values"], 3)
        self.assertIn("2.47e-324", rb.SeedSummary.__doc__)
        self.assertIn("zero_variance_warning", rb.SeedSummary.__doc__)

    def test_zero_variance_warning_distinct_from_sd_at_the_subnormal_floor(self):
        """Regression pin (cross-task, benchmark.sample_sd floor): 29 zeros plus one smallest subnormal is NOT
        constant, so the warning must be False, yet the SD underflows to exactly 0.0 (true SD ~ 9e-325 is below
        half the smallest subnormal, 2.47e-324). A warning implemented as `sd == 0.0` would say True."""
        seeds = tuple(derive_seed(5, f"z{k}") for k in range(30))
        odd = seeds[-1]
        c = rb.seed_sensitivity_probe(lambda s: 5e-324 if s == odd else 0.0, seeds, CFG)
        self.assertEqual(c.summary.sd, 0.0)                         # the floor is real here
        self.assertFalse(c.details["zero_variance_warning"])        # ...and the warning does not consult the SD
        self.assertEqual(c.details["n_distinct_values"], 2)
        const = rb.seed_sensitivity_probe(lambda s: 5e-324, seeds, CFG)
        self.assertEqual(const.summary.sd, 0.0)
        self.assertTrue(const.details["zero_variance_warning"])

    def test_negative_outcomes_keep_their_sign(self):
        s = rb.SeedSummary.from_values([-1, -2.5, -3])
        self.assertEqual(s.values, (-1.0, -2.5, -3.0))
        self.assertEqual((s.minimum, s.maximum), (-3.0, -1.0))
        self.assertLess(s.mean, 0.0)
        c = rb.seed_sensitivity_probe(lambda sd: -1.0 - (sd % 7), SEEDS, CFG)
        self.assertTrue(all(m.value < 0 for m in c.per_seed))
        self.assertEqual(c.summary.values, tuple(-1.0 - (sd % 7) for sd in SEEDS))
        self.assertLess(c.summary.maximum, 0.0)
        self.assertLess(c.summary.mean, 0.0)
        mixed = rb.summarize_seeds([MetricValue.measured(v) for v in (-2.0, 1.0, -0.5, 3.0)], 3)
        self.assertEqual((mixed.minimum, mixed.maximum), (-2.0, 3.0))

    def test_wrapped_errors_do_not_chain_a_context(self):
        for bad in ([10 ** 400] * 3, [None, 1.0, 2.0]):
            try:
                rb.SeedSummary.from_values(bad)
            except ValueError as e:
                self.assertIsNone(e.__cause__)
                self.assertTrue(e.__suppress_context__)   # `from None`: original traceback hidden

    def test_from_values_numeric_type_contract(self):
        """SR-11 items 8 and 9. `from_values` had NO stated contract on the types it accepts, and the two it
        silently accepted contradicted the rest of the kit:
          * `[True, False, True]` SUCCEEDED, coercing to 1.0/0.0, while `SeedSummary.__post_init__` rejects
            `isinstance(v, bool)` and `_to_metric` records a bool outcome as UNMEASURED -- three places, three
            answers.
          * `["1", "2", "3"]` SUCCEEDED too (`float("1")` works). Not reported by QA; found while deciding
            this contract.
        The contract now: accepted iff `type(v)` provides `__float__` or `__index__` and is not `bool`."""
        from decimal import Decimal
        from fractions import Fraction
        for good in ([1.0, 2.0, 3.0], [1, 2, 3], [Decimal("1"), Decimal("2"), Decimal("3")],
                     [Fraction(1, 2), Fraction(1, 3), Fraction(1, 4)], [1, 2.5, Decimal("3")]):
            s = rb.SeedSummary.from_values(good)
            self.assertEqual(s.n, 3, good)
            self.assertTrue(all(type(v) is float for v in s.values), good)
        # Decimal is the case that distinguishes the shipped `float(v)` cast from the `v * 1.0` mutant (R3):
        # `Decimal * float` raises TypeError, so this call is what makes that mutant non-equivalent.
        self.assertEqual(rb.SeedSummary.from_values([Decimal("1"), Decimal("2"), Decimal("3")]).values,
                         (1.0, 2.0, 3.0))
        with self.assertRaises(TypeError):
            Decimal("1") * 1.0                       # the mutant's arithmetic, shown to fail on its own
        for bad, why in (([True, False, True], "bool"), ([1.0, True, 2.0], "bool"),
                         (["1", "2", "3"], "str"), ([1.0, "2", 3.0], "str"),
                         ([b"1", b"2", b"3"], "bytes"), ([1 + 0j, 2 + 0j, 3 + 0j], "complex"),
                         ([None, 1.0, 2.0], "NoneType"), ([object(), 1.0, 2.0], "object")):
            with self.assertRaises(ValueError, msg=why) as cm:
                rb.SeedSummary.from_values(bad)
            self.assertNotIsInstance(cm.exception, (TypeError, OverflowError), why)
            self.assertIsNone(cm.exception.__cause__, why)
            self.assertTrue(cm.exception.__suppress_context__, why)
        # the three judgements now agree that a boolean is not a measurement
        self.assertFalse(rb._to_metric(lambda s: True, 0).is_measured)
        with self.assertRaises(ValueError):
            rb.SeedSummary(3, 1.0, 0.0, 1.0, 1.0, 0.0, 1.0, 1.0, (True, True, True))
        with self.assertRaises(ValueError):
            rb.SeedSummary.from_values([True, True, True])
        # ... and the probe path could never deliver one anyway: MetricValue refuses non-floats
        with self.assertRaises(ValueError):
            MetricValue.measured(True)
        doc = " ".join(rb.SeedSummary.from_values.__doc__.split())
        for needle in ("ACCEPTED NUMERIC CONTRACT", "`__float__` or `__index__`", "is not a `bool`",
                       "A boolean is never a measurement anywhere in this kit",
                       "number parsed out of text is not a measurement either"):
            self.assertIn(needle, doc)

    def test_mappingproxy_is_a_view_not_a_copy_and_that_limit_is_stated(self):
        """SR-11 item 7: an undocumented immutability bypass. `gc.get_referents(card.details)[0]` hands back
        the WRITABLE dict behind the MappingProxyType. It grants nothing `object.__setattr__` does not already
        grant and is equally detectable against a previously recorded hash -- but the Scorecard docstring
        listed only `object.__setattr__`, and this project's standard is that such routes are stated."""
        import gc
        sc = sc_simple()
        before = sc.content_hash()
        self.assertIsInstance(sc.details, type(rb.MappingProxyType({})))
        with self.assertRaises(TypeError):                       # the documented, supported-API story
            sc.details["injected"] = 1
        backing = gc.get_referents(sc.details)[0]
        self.assertIsInstance(backing, dict)
        backing["injected"] = 1
        self.assertIn("injected", sc.details)                    # the card really changed ...
        self.assertNotEqual(sc.content_hash(), before)           # ... and so did its content hash
        self.assertIn("injected", sc.to_dict()["details"])
        del backing["injected"]
        self.assertEqual(sc.content_hash(), before)              # detectable against a hash recorded EARLIER
        # to_dict() by contrast IS a true defensive copy
        d = sc.to_dict()
        d["details"]["injected"] = 1
        d["seeds"].append(999)
        self.assertNotIn("injected", sc.details)
        self.assertEqual(sc.content_hash(), before)
        doc = " ".join(rb.Scorecard.__doc__.split())
        for needle in ("HONEST LIMITS -- the routes THIS MODULE KNOWS OF, which is not a claim that "
                       "they are all of them",
                       "gc.get_referents(card.details)[0]", "`to_dict()` is a true defensive copy"):
            self.assertIn(needle, doc)
        # THE CLAIM THAT USED TO BE HERE, and why its own test needle had to move. This docstring said
        # "HONEST LIMITS, the complete list of routes known to this module" and this assertion PINNED
        # that wording, so the sentence was protected by a test while being false: a round-6 attestation
        # produced a third route (a `MetricValue` SUBCLASS accepted onto a card, because `per_seed` was
        # checked with `isinstance` where its two sibling checks demand `type(x) is ...`). The route is
        # closed and named as limit (3); the word "complete" is gone, and it may not come back, because
        # a list of routes is an assertion about ABSENCE and sweeping for routes cannot establish absence.
        # The falsified wording may appear ONLY as an attributed correction, never as the docstring's own
        # claim -- the convention `test_benchmark` and `ThePolicyParametersAreThemselvesPinned` both use.
        self.assertNotIn("HONEST LIMITS, the complete list of routes", doc)
        self.assertIn('this sentence used to say "the complete list of routes known to this module"', doc)
        with self.assertRaises(ValueError):          # limit (3), closed: subclasses are refused
            class Sub(MetricValue):
                pass
            rb.build_scorecard(probe_id="p", probe_kind="seed_sensitivity", seeds=tuple(range(1, 11)),
                               per_seed=tuple(Sub(float(i), None) for i in range(1, 11)),
                               cfg=rb.ProbeConfig(10), status_if_summarized=PS.MEASURED,
                               details_always={})
        self.assertIn("gc.get_referents", " ".join(rb.__doc__.split()))

    def test_probe_config_defaults_are_constructed_per_call(self):
        """Same defect class the dashboard owner found in `benchmark.analyze_scores`: a literal
        `cfg = ProbeConfig()` default is one instance shared by every no-argument call, and
        `object.__setattr__` reaches through the frozen dataclass into it.

        CORRECTED STAKE. This docstring used to say "one forged `min_seeds = 1` would license
        single-example claims process-wide". **That is false, and QA measured it.** `summarize_seeds`
        re-constructs `ProbeConfig(min_seeds)` at the point of use, so a forged value below
        `SEED_FLOOR` RAISES rather than taking effect. The real exposure is narrower and worth
        stating accurately: silently lowering the *policy* minimum from 10 to somewhere in 3-9, which
        weakens the evidence bar without ever tripping the floor. That exposure is now closed too, by
        `test_default_min_seeds_is_pinned_by_value`; it had been identified here and left unpinned,
        so a 10 -> 3 mutant passed every test in this file.

        TWO FIGURES IN THIS DOCSTRING WERE WRONG AND ARE CORRECTED HERE, because they did not
        reproduce on the fixture beside them. It said `3 -> summary n=4`; `5, 9, 10 ->
        INSUFFICIENT_EVIDENCE`. Those hold only for a fixture with exactly FOUR measured values,
        which this test does not use and did not name. On the 12-seed `SEEDS` fixture, passed as a
        SEQUENCE of `MetricValue`s, the measurement is:
            min_seeds 1, 2        -> ValueError (the floor, raised by `ProbeConfig`)
            min_seeds 3, 5, 9, 10, 12 -> SeedSummary n=12
            min_seeds 13          -> InsufficientEvidence n_measured=12
        Worse, the two `assertRaises` lines below used to pass a **dict** as `per_seed`, so
        `tuple(dict)` yielded the int keys and EVERY min_seeds from 3 upward also raised -- from the
        "must be MetricValues" check, not from the floor. The assertion offered as the measurement
        therefore did not pin the mechanism it named: with the `ProbeConfig(min_seeds)` call deleted,
        the dict form still raised. The lines now pass a list, so the floor is what raises, and they
        assert the floor's own message."""
        import inspect
        probes = (rb.seed_sensitivity_probe, rb.probe_shift, rb.probe_missing_inputs, rb.probe_precision,
                  rb.precision_sweep)
        for fn in probes:
            self.assertIsNone(inspect.signature(fn).parameters["cfg"].default, fn.__name__)
        a = rb.seed_sensitivity_probe(lambda s: float(s % 7), SEEDS)
        b = rb.seed_sensitivity_probe(lambda s: float(s % 7), SEEDS)
        self.assertEqual(a.min_seeds, rb.DEFAULT_MIN_SEEDS)
        self.assertEqual(b.min_seeds, rb.DEFAULT_MIN_SEEDS)
        # The resolver really constructs per call. Asserted on the object `_pcfg(None)` ACTUALLY
        # RETURNS -- the stand-in forgery below cannot detect a singleton, which is why QA's
        # `_pcfg`-returns-a-singleton mutant survived all 307 tests while the equivalent `Margins`
        # mutant died: that guard forged the live resolved object and this one did not.
        self.assertIsNot(rb._pcfg(None), rb._pcfg(None))
        self.assertEqual(rb._pcfg(None), rb._pcfg(None))        # equal by value, distinct by identity
        given = rb.ProbeConfig(7)
        self.assertIs(rb._pcfg(given), given)                   # an explicit cfg passes through
        live = rb._pcfg(None)
        object.__setattr__(live, "min_seeds", 1)                 # forge the LIVE resolved object
        self.assertEqual(rb._pcfg(None).min_seeds, rb.DEFAULT_MIN_SEEDS)
        # forging a field of one call's resolved config cannot reach a later call
        forged = rb.ProbeConfig()
        object.__setattr__(forged, "min_seeds", 1)
        self.assertEqual(forged.min_seeds, 1)
        self.assertEqual(rb.ProbeConfig().min_seeds, rb.DEFAULT_MIN_SEEDS)
        c = rb.seed_sensitivity_probe(lambda s: float(s % 7), SEEDS)
        self.assertEqual(c.min_seeds, rb.DEFAULT_MIN_SEEDS)
        # The corrected stake, measured on a LIST of MetricValues so that the floor is what raises --
        # with a dict the "must be MetricValues" check fired first and these lines proved nothing about
        # the floor. The message is asserted so that deleting the `ProbeConfig(min_seeds)` call in
        # `summarize_seeds` fails here instead of silently passing.
        per_seed = [rb.MetricValue.measured(float(s)) for s in SEEDS]
        for sub in (1, 2, rb.SEED_FLOOR - 1):
            with self.assertRaises(ValueError, msg=sub) as cm:
                rb.summarize_seeds(per_seed, min_seeds=sub)
            self.assertIn("absolute floor", str(cm.exception), sub)
        # the figures this docstring now quotes, on this fixture, so they cannot drift again
        self.assertEqual(len(per_seed), 12)
        for m in (rb.SEED_FLOOR, 5, 9, rb.DEFAULT_MIN_SEEDS, 12):
            r = rb.summarize_seeds(per_seed, min_seeds=m)
            self.assertIsInstance(r, rb.SeedSummary, m)
            self.assertEqual(r.n, 12, m)
        self.assertIsInstance(rb.summarize_seeds(per_seed, min_seeds=13), rb.InsufficientEvidence)
        self.assertEqual(rb.summarize_seeds(per_seed, min_seeds=13).n_measured, 12)
        # and the floor is still refused at construction
        with self.assertRaises(ValueError):
            rb.ProbeConfig(rb.SEED_FLOOR - 1)
        self.assertIn("FRESHLY CONSTRUCTED `ProbeConfig()`", " ".join(rb._pcfg.__doc__.split()))

    def test_build_scorecard_has_no_shared_container_default(self):
        """QA found the last container default in this module: `details_if_summarized` defaulted to a
        literal `MappingProxyType({})`. The proxy is read-only, but the dict BEHIND it is reachable
        via `gc.get_referents` -- the route `Scorecard` lists among its honest limits -- so writes
        persisted into every later no-argument call. Low stakes (descriptive `details` only, never a
        status or `min_seeds`), which is exactly why it would have survived indefinitely."""
        import gc
        import inspect
        d = inspect.signature(rb.build_scorecard).parameters["details_if_summarized"].default
        self.assertIsNone(d, "a container default is shared by every call that omits the argument")
        # the defect, demonstrated against the shape it used to have, so the test states a mechanism
        # rather than just a signature fact
        proxy = rb.MappingProxyType({})
        backing = [o for o in gc.get_referents(proxy) if isinstance(o, dict)]
        self.assertTrue(backing, "a MappingProxyType exposes its backing dict to gc.get_referents")
        backing[0]["injected"] = 1
        self.assertEqual(dict(proxy), {"injected": 1})   # read-only wrapper, mutated through the back
        # and a real no-argument call is unaffected by any such poisoning
        kw = dict(probe_id="p", probe_kind="k", seeds=SEEDS,
                  per_seed=tuple(rb.MetricValue.measured(float(s)) for s in SEEDS),
                  cfg=rb.ProbeConfig(), status_if_summarized=rb.ProbeStatus.MEASURED,
                  details_always={"a": 1})
        first = rb.build_scorecard(**kw)
        self.assertNotIn("injected", first.details)
        second = rb.build_scorecard(**kw)
        self.assertNotIn("injected", second.details)
        self.assertEqual(dict(first.details), dict(second.details))

    def test_documented_corner_extreme_summary_is_accepted(self):
        s = rb.SeedSummary.from_values([1.7e308] * 3)      # documented, unguarded: see SeedSummary docstring
        self.assertEqual(s.n, 3)
        self.assertIn("1.7e308", rb.SeedSummary.__doc__)

    # --- independent oracle check for exact_masked_mse
    def test_exact_masked_mse_against_independent_decimal_arithmetic(self):
        import decimal
        ctx = decimal.Context(prec=6000)
        for s in range(30):
            fx = rb.make_measure_fixture(s, magnitude_spread=6)
            tot, cnt = decimal.Decimal(0), 0
            for pr, tr, use in zip(fx.pred, fx.target, fx.mask):
                if use:
                    for a, b in zip(pr, tr):
                        d = ctx.subtract(decimal.Decimal(a), decimal.Decimal(b))   # Decimal(float) is exact
                        tot = ctx.add(tot, ctx.multiply(d, d))
                        cnt += 1
            n, den = tot.as_integer_ratio()
            from fractions import Fraction
            self.assertEqual(rb.exact_masked_mse(fx.pred, fx.target, fx.mask), Fraction(n, den * cnt), s)
        # hand value: (0.1 - 0)^2 with the exact binary value of 0.1
        from fractions import Fraction
        self.assertEqual(rb.exact_masked_mse(((0.1,),), ((0.0,),), (True,)), Fraction(0.1) ** 2)


def forge(mv, value):
    """Install `value` into a built `MetricValue` -- route (b) of `toy.benchmark`'s threat model, and the
    state every stored metric can be in after a serialisation round trip."""
    object.__setattr__(mv, "value", value)
    return mv


class EveryMetricReadSiteIsPinnedByItsConsequence(unittest.TestCase):
    """SR-11 ROUND 5, LAYER 2: one test per stored-metric read site in `robustness.py`, each forging the
    metric BEHIND that site and asserting the CONSEQUENCE -- the probe STATUS, the evidence labels and the
    structured `insufficient` / `details`, never an intermediate count.

    WHY THIS CLASS EXISTS. A reroute experiment replaced each of this module's nine stored-metric read
    sites in turn with a fully unchecked read and ran the whole suite: ALL NINE STAYED GREEN. One of them
    turned `InsufficientEvidence(9 of 10)` into `SeedSummary(n=10)` -- that is this module's "no claims
    based on single examples" criterion failing by exactly the mechanism it was written against, and no
    test noticed, because every existing test asserted that the HONEST case works. A consequence test
    does not depend on how the read is spelled or on which paths a probe's run happens to touch, so it is
    the only one of the three layers in
    `test_benchmark.TheCheckedReaderIsTheOnlyWayToReadAStoredMetric` that covers a forged metric
    installed by `object.__setattr__` and read back through `object.__getattribute__`.

    The honest control is asserted in every test, so none of them can pass by refusing everything."""

    FORGED = (math.inf, -math.inf, math.nan, True, False, 0, 1, "1.0", "", [1.0], {}, None, object())
    JSON_SAFE = (True, False, 0, 1, None)          # forged values a scorecard can still serialize

    def ten(self):
        return [MetricValue.measured(float(i)) for i in range(10)]

    def test_R_summarize_a_forged_value_is_not_a_measured_value(self):
        """`summarize_seeds`'s `measured` comprehension. THE SITE WHOSE REROUTE BREACHED THE MODULE'S OWN
        CRITERION: with 9 of 10 honestly measured and one forged, an unchecked read returned
        `SeedSummary(n=10)` -- a mean, SD and IQR over a value that is not a number -- where the contract
        is `InsufficientEvidence`. Asserted on the TYPE (which has no statistic fields at all), the two
        counts and the reason string."""
        honest = rb.summarize_seeds(self.ten(), 10)
        self.assertIsInstance(honest, rb.SeedSummary)              # the control: it CAN summarize
        self.assertEqual(honest.n, 10)
        for bad in self.FORGED:
            ps = self.ten()
            forge(ps[3], bad)
            got = rb.summarize_seeds(ps, 10)
            self.assertIsInstance(got, rb.InsufficientEvidence, repr(bad))
            self.assertEqual((got.n_measured, got.n_required), (9, 10), repr(bad))
            self.assertEqual(got.reason, "9 measured of 10 seeds; minimum is 10", repr(bad))
            self.assertFalse(hasattr(got, "mean"), repr(bad))      # no statistic exists to be quoted
            with self.assertRaises(rb.InsufficientEvidenceError, msg=repr(bad)):
                rb.require_summary(got)

    def test_R_build_unknown_a_forged_value_downgrades_the_whole_card(self):
        """`build_scorecard`'s two reads -- `summarize_seeds(per_seed, ...)` and the `_metric_ok` label
        test. The consequence is the CARD: status INSUFFICIENT_EVIDENCE, no summary, the UNKNOWN label,
        and the structured `insufficient` object. An unchecked read produced a MEASURED card with a
        TOY_RESULT label over a forged number."""
        ok = rb.build_scorecard(probe_id="p", probe_kind="seed_sensitivity", seeds=tuple(range(1, 11)),
                                per_seed=self.ten(), cfg=CFG, status_if_summarized=PS.MEASURED,
                                details_always={"outcome_name": "o"})
        self.assertIs(ok.status, PS.MEASURED)                      # the control
        self.assertEqual({e.value for e in ok.evidence_labels}, {"NOT_VALIDATED", "TOY_RESULT"})
        self.assertEqual(ok.summary.n, 10)
        self.assertIsNone(ok.insufficient)
        for bad in self.FORGED:
            ps = self.ten()
            forge(ps[3], bad)
            card = rb.build_scorecard(probe_id="p", probe_kind="seed_sensitivity",
                                      seeds=tuple(range(1, 11)), per_seed=ps, cfg=CFG,
                                      status_if_summarized=PS.MEASURED,
                                      details_always={"outcome_name": "o"})
            why = repr(bad)
            self.assertIs(card.status, PS.INSUFFICIENT_EVIDENCE, why)
            self.assertIsNone(card.summary, why)
            self.assertEqual((card.insufficient.n_measured, card.insufficient.n_required), (9, 10), why)
            self.assertEqual({e.value for e in card.evidence_labels}, {"NOT_VALIDATED", "UNKNOWN"}, why)
            self.assertNotIn(EvidenceClass.TOY_RESULT, card.evidence_labels, why)
            # and the descriptive details that only exist for a summarized card are absent, so nothing
            # downstream can quote a deviation count computed over a forged value
            self.assertNotIn("n_distinct_values", card.details, why)

    def test_R_card_measured_a_card_cannot_be_relaunched_around_a_forged_value(self):
        """`Scorecard.__post_init__`'s `measured` tuple, which is what makes the card self-consistent.
        Forging a per-seed metric AFTER construction and then laundering the card through
        `dataclasses.replace` -- which does not re-run nested validators -- must be refused."""
        card = rb.build_scorecard(probe_id="p", probe_kind="seed_sensitivity", seeds=tuple(range(1, 11)),
                                  per_seed=self.ten(), cfg=CFG, status_if_summarized=PS.MEASURED,
                                  details_always={})
        self.assertIsNotNone(dataclasses.replace(card, probe_id="p2"))     # the control: replace works
        for bad in self.JSON_SAFE + (math.inf, math.nan, "1.0"):
            c = rb.build_scorecard(probe_id="p", probe_kind="seed_sensitivity",
                                   seeds=tuple(range(1, 11)), per_seed=self.ten(), cfg=CFG,
                                   status_if_summarized=PS.MEASURED, details_always={})
            forge(c.per_seed[2], bad)
            with self.assertRaisesRegex(ValueError, "summary does not match the measured per-seed values",
                                        msg=repr(bad)):
                dataclasses.replace(c, probe_id="p2")

    def test_R_card_unknown_label_a_forged_value_forces_the_UNKNOWN_label(self):
        """`Scorecard.__post_init__`'s `any(not _metric_ok(m) ...)` label test, reached only when the
        summary itself is consistent -- so the card is built with a summary over the NINE honest values
        and `min_seeds=9`, which is the shape an unchecked read would have produced. The label is the
        consequence: a card holding an unusable observation may not be labelled as if every seed were
        measured."""
        seeds = tuple(range(1, 11))
        nine = rb.SeedSummary.from_values([float(i) for i in range(10) if i != 3])
        for bad in self.JSON_SAFE + (math.inf, math.nan, "1.0"):
            ps = self.ten()
            forge(ps[3], bad)
            with self.assertRaisesRegex(ValueError, "must carry UNKNOWN", msg=repr(bad)):
                rb.Scorecard("p", "k", PS.MEASURED, 9, seeds, rb.seed_list_digest(seeds), tuple(ps),
                             nine, None, (EvidenceClass.NOT_VALIDATED, EvidenceClass.TOY_RESULT),
                             {}, rb.STANDARD_NON_CLAIMS)
            card = rb.Scorecard("p", "k", PS.MEASURED, 9, seeds, rb.seed_list_digest(seeds), tuple(ps),
                                nine, None, (EvidenceClass.NOT_VALIDATED, EvidenceClass.TOY_RESULT,
                                             EvidenceClass.UNKNOWN), {}, rb.STANDARD_NON_CLAIMS)
            self.assertIn(EvidenceClass.UNKNOWN, card.evidence_labels, repr(bad))
        # the control: with all ten honest, UNKNOWN is NOT required and TOY_RESULT alone is accepted
        ten = rb.SeedSummary.from_values([float(i) for i in range(10)])
        clean = rb.Scorecard("p", "k", PS.MEASURED, 10, seeds, rb.seed_list_digest(seeds),
                             tuple(self.ten()), ten, None,
                             (EvidenceClass.NOT_VALIDATED, EvidenceClass.TOY_RESULT), {},
                             rb.STANDARD_NON_CLAIMS)
        self.assertNotIn(EvidenceClass.UNKNOWN, clean.evidence_labels)

    def test_R_record_nmeas_the_recorded_count_excludes_a_forged_value(self):
        """`scorecard_to_record`'s `n_measured`. The consequence is the RECORD: the count must be 9, the
        statistics must be explicitly unmeasured with the INSUFFICIENT_EVIDENCE reason, and the record's
        evidence class must be UNKNOWN -- not TOY_RESULT with a mean over a forged number."""
        ok = rb.build_scorecard(probe_id="p", probe_kind="seed_sensitivity", seeds=tuple(range(1, 11)),
                                per_seed=self.ten(), cfg=CFG, status_if_summarized=PS.MEASURED,
                                details_always={})
        rec = rb.scorecard_to_record(ok, run_id="r", timestamp_utc=TS)
        self.assertEqual(rec.metrics["n_measured"], MetricValue.measured(10.0))     # the control
        self.assertIs(rec.evidence_class, EvidenceClass.TOY_RESULT)
        for bad in self.JSON_SAFE:
            ps = self.ten()
            forge(ps[3], bad)
            card = rb.build_scorecard(probe_id="p", probe_kind="seed_sensitivity",
                                      seeds=tuple(range(1, 11)), per_seed=ps, cfg=CFG,
                                      status_if_summarized=PS.MEASURED, details_always={})
            r = rb.scorecard_to_record(card, run_id="r", timestamp_utc=TS)
            why = repr(bad)
            self.assertEqual(r.metrics["n_measured"], MetricValue.measured(9.0), why)
            self.assertEqual(r.metrics["n_seeds"], MetricValue.measured(10.0), why)
            self.assertIs(r.evidence_class, EvidenceClass.UNKNOWN, why)
            for key in ("mean", "sd", "iqr", "min", "max"):
                self.assertFalse(rb._metric_ok(r.metrics[key]), (key, why))
                self.assertIn("INSUFFICIENT_EVIDENCE", r.metrics[key].reason, (key, why))
        # a forged NON-SERIALISABLE value fails closed LOUDLY instead, at the content hash
        ps = self.ten()
        forge(ps[3], math.inf)
        card = rb.build_scorecard(probe_id="p", probe_kind="seed_sensitivity", seeds=tuple(range(1, 11)),
                                  per_seed=ps, cfg=CFG, status_if_summarized=PS.MEASURED, details_always={})
        with self.assertRaises(ValueError):
            rb.scorecard_to_record(card, run_id="r", timestamp_utc=TS)

    def test_R_seedsens_vals_an_unmeasurable_outcome_is_counted_as_unmeasured(self):
        """`seed_sensitivity_probe`'s `vals` comprehension, which feeds `n_unmeasured` and
        `n_distinct_values`. `_to_metric` guarantees `per_seed` is honest, so this site's whole job is to
        COUNT -- and the consequence of miscounting is a card that reports a distinct-value spread over
        observations it never had, plus a missing UNKNOWN label."""
        seeds = tuple(range(1, 13))
        card = rb.seed_sensitivity_probe(lambda s: float(s % 7), seeds, CFG)
        self.assertIs(card.status, PS.MEASURED)                               # the control
        self.assertEqual(card.details["n_unmeasured"], 0)
        self.assertEqual(card.details["n_distinct_values"], 7)
        self.assertNotIn(EvidenceClass.UNKNOWN, card.evidence_labels)
        for bad_outcome, n_bad in ((lambda s: math.nan if s < 3 else float(s % 7), 2),
                                   (lambda s: True if s < 3 else float(s % 7), 2),
                                   (lambda s: math.inf if s < 4 else float(s % 7), 3)):
            c = rb.seed_sensitivity_probe(bad_outcome, seeds, rb.ProbeConfig(3))
            self.assertIs(c.status, PS.MEASURED, n_bad)
            self.assertEqual(c.details["n_unmeasured"], n_bad, n_bad)
            self.assertEqual(c.summary.n, 12 - n_bad, n_bad)
            self.assertIn(EvidenceClass.UNKNOWN, c.evidence_labels, n_bad)
            self.assertEqual(len(c.per_seed), 12, n_bad)          # the observations are still recorded
            self.assertEqual(sum(1 for m in c.per_seed if not rb._metric_ok(m)), n_bad, n_bad)

    def test_R_shift_unmeas_a_seed_whose_deviation_is_unmeasurable_is_named(self):
        """`probe_shift`'s `unmeasured_seeds` detail. A seed whose relative deviation cannot be computed
        must be NAMED and must drag the UNKNOWN label onto the card; the failure mode an unchecked read
        buys is a silent pass -- a seed counted as "within bound" because its deviation read as a number
        that is not one."""
        seeds = tuple(range(1, 13))
        spec = rb.shift_reorder_rows()
        clean = rb.probe_shift(rb.mse_fsum, spec, seeds, rb.ProbeConfig(3))
        self.assertEqual(tuple(clean.details["unmeasured_seeds"]), ())          # the control
        self.assertNotIn(EvidenceClass.UNKNOWN, clean.evidence_labels)
        self.assertEqual(clean.details["n_measured"], 12)

        # A measure that is unmeasurable on exactly the first TWO seeds. Driven by a call counter rather
        # than by fixture content so the split cannot drift with the fixture generator: `probe_shift`
        # calls the measure once for the base and once for the shifted fixture, and a base failure skips
        # the second call -- so the first two calls are the first two seeds.
        calls = []

        def flaky(p, t, m):
            calls.append(1)
            if len(calls) <= 2:
                raise ValueError("deliberately unmeasurable on this fixture")
            return rb.mse_fsum(p, t, m)
        flaky.__name__ = "flaky"
        card = rb.probe_shift(flaky, spec, seeds, rb.ProbeConfig(3))
        bad = list(card.details["unmeasured_seeds"])
        self.assertEqual(bad, list(seeds[:2]), "the broken measure's seed split moved")
        self.assertEqual(sorted(bad), sorted(sd for sd, m in zip(seeds, card.per_seed)
                                             if not rb._metric_ok(m)))
        self.assertEqual(card.details["n_measured"] + len(bad), 12)
        self.assertIn(EvidenceClass.UNKNOWN, card.evidence_labels)
        self.assertEqual(card.summary.n, 12 - len(bad))

    def test_R_arm_diff_an_unusable_arm_gives_unmeasured_never_zero(self):
        """`arm_difference`'s two reads. The consequence is the returned `MetricValue`: explicitly
        unmeasured WITH a reason, and in particular NEVER `measured(0.0)` -- a missing arm reading as a
        zero contrast is the single most dangerous substitution in this kit, and
        `probe_missing_inputs` asserts exactly that as a structural check.

        THIS TEST NAMED THAT OUTCOME AS FORBIDDEN AND THEN SWEPT THE WRONG AXIS, for five rounds. It
        forged the arms' VALUES (`forge(arms[which], bad)`) and left the arms' NAMES untouched -- and the
        names are where the defect was. `nm not in arms` is `__hash__` plus `__eq__` on the caller's name
        against the caller's keys, neither type-checked nor normalised. MEASURED in the unmodified tree,
        no `object.__setattr__`: with ten seeds and the treatment arm NEVER RECORDED, a `str` subclass
        holding "E" that hashes as "C0" and answers True to `__eq__` turned the honest
        `MetricValue(value=None, reason="arm 'E' absent")` into `MetricValue(value=0.0, reason=None)`, and
        the card recording it went INSUFFICIENT_EVIDENCE -> MEASURED with
        `summary={"n": 10, "mean": 0.0, "sd": 0.0, ...}` and the UNKNOWN evidence label GONE. The names
        axis is swept below, in this test rather than in a parallel one, because a test that forbids an
        outcome in prose while sweeping one of its two inputs is worse than no test: it is a reason not to
        look again. `arm_difference`'s names are function PARAMETERS, so the
        `toy.schema._normalise_fields` boundary cannot reach them; they are normalised where they bind."""
        self.assertEqual(rb.arm_difference({"C0": MetricValue.measured(1.0),
                                            "E": MetricValue.measured(5.0)}, "E", "C0"),
                         MetricValue.measured(4.0))                            # the control
        for bad in self.FORGED:
            for which in ("E", "C0"):
                arms = {"C0": MetricValue.measured(1.0), "E": MetricValue.measured(5.0)}
                forge(arms[which], bad)
                got = rb.arm_difference(arms, "E", "C0")
                why = (which, repr(bad))
                self.assertFalse(rb._metric_ok(got), why)
                self.assertNotEqual(got, MetricValue.measured(0.0), why)
                self.assertIn(f"arm {which!r} unmeasured", got.reason, why)

        # ---- THE NAMES AXIS, the one this test used to leave unswept ----
        def liar(text, hashes_as):
            class Name(str):
                def __hash__(self):
                    return hash(hashes_as)

                def __eq__(self, other):
                    return True

                def __ne__(self, other):
                    return False
            return Name(text)
        present = {"C0": MetricValue.measured(3.0)}
        honest = rb.arm_difference(present, "E", "C0")
        self.assertEqual(honest, MetricValue(value=None, reason="arm 'E' absent"))      # the control
        for pos, args, absent in (("treatment", (liar("E", "C0"), "C0"), "E"),
                                  ("control", ("C0", liar("Ctrl", "C0")), "Ctrl")):
            got = rb.arm_difference(present, *args)
            why = (pos, absent)
            self.assertFalse(rb._metric_ok(got), why)
            self.assertNotEqual(got, MetricValue.measured(0.0), why)
            self.assertIsNone(got.value, why)
            self.assertEqual(got.reason, f"arm {absent!r} absent", why)
        # a name that is not a usable name at all is a loud ValueError, not a zero
        for bad in (None, 7, b"E", "", "  ", ["E"]):
            with self.assertRaises(ValueError, msg=repr(bad)):
                rb.arm_difference(present, bad, "C0")
            with self.assertRaises(ValueError, msg=repr(bad)):
                rb.arm_difference(present, "C0", bad)
        with self.assertRaises(ValueError):
            rb.arm_difference([("C0", MetricValue.measured(3.0))], "E", "C0")     # not a Mapping
        # the ARMS KEYS are the other half of the same membership test
        keyed = {liar("C0", "C0"): MetricValue.measured(3.0)}
        g = rb.arm_difference(keyed, "E", "C0")
        self.assertIsNone(g.value)
        self.assertIn("arm 'E' absent", g.reason)
        # an honest name that IS present still reads as a measurement, so the fix adds no false absence
        self.assertEqual(rb.arm_difference({"C0": MetricValue.measured(1.0),
                                            "E": MetricValue.measured(5.0)},
                                           liar("E", "E"), liar("C0", "C0")),
                         MetricValue.measured(4.0))

        # ---- THE CARD, which is where a reader meets the consequence ----
        def card_for(treatment):
            arms = {"C0": MetricValue.measured(3.0)}
            return rb.build_scorecard(
                probe_id="armdiff", probe_kind="seed_sensitivity", seeds=tuple(range(1, 11)),
                per_seed=tuple(rb.arm_difference(arms, treatment, "C0") for _ in range(10)),
                cfg=rb.ProbeConfig(10), status_if_summarized=PS.MEASURED, details_always={})
        base = card_for("E")
        self.assertIs(base.status, PS.INSUFFICIENT_EVIDENCE)                   # the honest card
        self.assertIsNone(base.summary)
        self.assertIn(EvidenceClass.UNKNOWN, base.evidence_labels)
        forged_card = card_for(liar("E", "C0"))
        self.assertIs(forged_card.status, PS.INSUFFICIENT_EVIDENCE)
        self.assertIsNone(forged_card.summary)
        self.assertIn(EvidenceClass.UNKNOWN, forged_card.evidence_labels)
        self.assertNotIn(EvidenceClass.TOY_RESULT, forged_card.evidence_labels)
        self.assertEqual(forged_card.content_hash(), base.content_hash())
        # and the structural check that reports it is itself asserted, on a real probe card
        card = rb.probe_missing_inputs(rb.mse_fsum, tuple(range(1, 13)), rb.ProbeConfig(3))
        self.assertTrue(card.details["structural_checks"]["absent_arm_gives_unmeasured"])

    def test_R_bench_outcome_a_forged_benchmark_metric_becomes_an_unmeasured_seed(self):
        """`benchmark_outcome`'s two reads. It is an ADAPTER onto SR-10, so its consequence is what the
        SR-11 probe records: a seed whose benchmark metric is unusable must become an UNMEASURED
        observation with the reason attached, never a number. Driven through the real probe, so the
        assertion is on the card rather than on the adapter's return value."""
        tiny = bm.BenchmarkConfig(steps=20, steps_conv=25, n_boot=50, n_train=16, n_eval=16)
        deg = bm.fixture_global_degrader(0.5)
        good = rb.benchmark_outcome(deg, "S", tiny)
        self.assertIsInstance(good(1), float)                                  # the control
        card = rb.seed_sensitivity_probe(good, (1, 2, 3), rb.ProbeConfig(3))
        self.assertIs(card.status, PS.MEASURED)
        self.assertEqual(card.details["n_unmeasured"], 0)
        # an honestly unmeasured metric: the adapter must raise, and the probe must record the reason
        unm = rb.benchmark_outcome(deg, "E_loss_ratio", tiny)
        with self.assertRaisesRegex(ValueError, "E_loss_ratio unmeasured"):
            unm(1)
        insuf = rb.seed_sensitivity_probe(unm, (1, 2, 3), rb.ProbeConfig(3))
        self.assertIs(insuf.status, PS.INSUFFICIENT_EVIDENCE)
        self.assertIsNone(insuf.summary)
        self.assertEqual((insuf.insufficient.n_measured, insuf.insufficient.n_required), (0, 3))
        self.assertIn(EvidenceClass.UNKNOWN, insuf.evidence_labels)
        for m in insuf.per_seed:
            self.assertIn("E_loss_ratio unmeasured", m.reason)
        # a FORGED metric takes the same route, through the same read
        real = bm.score_seed

        def forging(seed, factory, cfg, _r=real):
            s = _r(seed, factory, cfg)
            forge(s.metrics["S"], math.inf)
            return s
        with mock.patch.object(bm, "score_seed", forging):
            c = rb.seed_sensitivity_probe(rb.benchmark_outcome(deg, "S", tiny), (1, 2, 3),
                                          rb.ProbeConfig(3))
        self.assertIs(c.status, PS.INSUFFICIENT_EVIDENCE)
        self.assertIsNone(c.summary)
        self.assertEqual(c.insufficient.n_measured, 0)
        self.assertIn(EvidenceClass.UNKNOWN, c.evidence_labels)

    def test_the_nine_read_sites_are_counted_from_the_source_not_listed_here(self):
        """The class above has one test per read site. THE NUMBER OF SITES IS MEASURED, so a tenth site
        added without a consequence test fails here rather than being noticed by a reviewer -- which is
        the whole failure mode of the previous four rounds, in which a hand-maintained list of consumers
        went stale inside one round every time."""
        tree = ast.parse(Path(rb.__file__).read_text())
        owner = {}
        for fn in ast.walk(tree):
            if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for sub in ast.walk(fn):
                    owner.setdefault(id(sub), fn.name)
        readers = {"_metric_read", "_metric_ok"}
        sites = sorted({(n.lineno, owner.get(id(n), "<module>")) for n in ast.walk(tree)
                        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                        and n.func.id in readers})
        functions = sorted({f for _, f in sites})
        self.assertEqual(functions, ["__post_init__", "arm_difference", "benchmark_outcome",
                                     "build_scorecard", "probe_missing_inputs", "probe_shift",
                                     "scorecard_to_record", "seed_sensitivity_probe",
                                     "summarize_seeds"],
                         f"the stored-metric read sites in robustness.py moved: {sites}")
        self.assertEqual(len(functions), 9, functions)       # NINE reading functions ...
        self.assertEqual(len(sites), 11, sites)              # ... at ELEVEN call sites
        tested = [m for m in dir(self) if m.startswith("test_R_")]
        self.assertEqual(len(tested), 9, sorted(tested))


class ThePolicyParametersAreThemselvesPinned(unittest.TestCase):
    """SR-15 D7 / the `SEED_FLOOR` count. `DEFAULT_MIN_SEEDS` is this module's only PROTOCOL PARAMETER
    and it was pinned by NOTHING: all five of its test references were self-referential
    (`assertEqual(x.min_seeds, rb.DEFAULT_MIN_SEEDS)`), so a 10 -> 3 mutant passed every test in this
    file. `SEED_FLOOR = 3` still held, so n=1/n=2 stayed refused and SR-11's single-example criterion
    was not breached; the exposure was the one the corrected docstring in
    `test_probe_config_defaults_are_constructed_per_call` had already NAMED and left open --
    "silently lowering the policy minimum from 10 into 3-9". `toy.benchmark` pins its equivalents by
    value and type; these now match."""

    def test_default_min_seeds_is_pinned_by_value(self):
        self.assertEqual(rb.DEFAULT_MIN_SEEDS, 10)
        self.assertIsInstance(rb.DEFAULT_MIN_SEEDS, int)
        self.assertNotIsInstance(rb.DEFAULT_MIN_SEEDS, bool)
        self.assertGreater(rb.DEFAULT_MIN_SEEDS, rb.SEED_FLOOR)      # a policy minimum above the floor
        self.assertEqual(rb.ProbeConfig().min_seeds, 10)
        self.assertEqual(rb._pcfg(None).min_seeds, 10)

    def test_an_int_subclass_cannot_lower_the_floor_or_the_configured_minimum(self):
        """N1 IN THIS MODULE, found by the same sweep that found `toy.benchmark._check_margin`'s ordering
        defect, and worse here because it is this module's STRUCTURAL guarantee: `self.min_seeds <
        SEED_FLOOR` is `type(min_seeds).__lt__`, so an `int` SUBCLASS returning False from `__lt__` passed
        `ProbeConfig` through the PUBLIC constructor holding 1, with no `object.__setattr__` anywhere.
        MEASURED before the fix: `ProbeConfig(Sneaky(1)).min_seeds == 1`, and
        `summarize_seeds([3 measured of 10], Sneaky(1))` returned `SeedSummary(n=3)` -- "no claims from
        single examples" reduced to "no claims from fewer than three". `SEED_FLOOR` itself still held,
        because `SeedSummary.from_values` compares a `len()` and a `len()` is not overridable; the
        CONFIGURED minimum did not hold at all.
        The fix is `int.__int__` before the comparison, and STORING the normalised value so that
        `summarize_seeds`'s own `len(measured) < min_seeds` is on the same number."""
        class Sneaky(int):
            def __lt__(self, other):
                return False

            def __le__(self, other):
                return False

            def __int__(self):
                return 10 ** 6

            def __index__(self):
                return 10 ** 6
        class SneakyGt(int):
            """The variant that matters for `summarize_seeds`'s OWN comparison. `len(measured) <
            min_seeds` with an `int` subclass on the right resolves to the REFLECTED operator, so a lying
            `__gt__` -- not a lying `__lt__` -- is what makes 9 measured of 10 read as "enough". Measured:
            with `summarize_seeds` taking `min_seeds` straight from the caller instead of from the
            normalising `ProbeConfig`, this returned `SeedSummary(n=9)` with a configured minimum of 10,
            and a first version of this test MISSED IT because it only overrode `__lt__`."""
            def __gt__(self, other):
                return False

            def __ge__(self, other):
                return True
        for bad in (1, 2, 0, -5):
            with self.assertRaises(ValueError, msg=repr(bad)):
                rb.ProbeConfig(Sneaky(bad))
            with self.assertRaises(ValueError, msg=repr(bad)):
                rb.summarize_seeds([MetricValue.measured(float(i)) for i in range(10)], Sneaky(bad))
        # the reflected-comparison variant: the floor is satisfied, the CONFIGURED minimum is the attack
        for n_measured, n_total in ((9, 10), (3, 10), (0, 10)):
            ps = [MetricValue.measured(float(i)) for i in range(n_total)]
            for i in range(n_measured, n_total):
                forge(ps[i], math.inf)
            got = rb.summarize_seeds(ps, SneakyGt(10))
            self.assertIsInstance(got, rb.InsufficientEvidence, (n_measured, n_total))
            self.assertEqual((got.n_measured, got.n_required), (n_measured, 10), (n_measured, n_total))
            card = rb.build_scorecard(probe_id="p", probe_kind="seed_sensitivity",
                                      seeds=tuple(range(1, n_total + 1)), per_seed=ps,
                                      cfg=rb.ProbeConfig(SneakyGt(10)),
                                      status_if_summarized=PS.MEASURED, details_always={})
            self.assertIs(card.status, PS.INSUFFICIENT_EVIDENCE, (n_measured, n_total))
            self.assertIsNone(card.summary, (n_measured, n_total))
            self.assertIn(EvidenceClass.UNKNOWN, card.evidence_labels, (n_measured, n_total))
        self.assertIsInstance(rb.summarize_seeds(
            [MetricValue.measured(float(i)) for i in range(10)], SneakyGt(10)), rb.SeedSummary)
        # an IN-RANGE subclass is accepted and STORED AS A PLAIN INT, so nothing downstream re-converts
        cfg = rb.ProbeConfig(Sneaky(10))
        self.assertIs(type(cfg.min_seeds), int)
        self.assertEqual(cfg.min_seeds, 10)
        # ... and the consequence: 9 of 10 measured is still InsufficientEvidence, not a summary
        ps = [MetricValue.measured(float(i)) for i in range(10)]
        forge(ps[0], math.inf)
        got = rb.summarize_seeds(ps, Sneaky(10))
        self.assertIsInstance(got, rb.InsufficientEvidence)
        self.assertEqual((got.n_measured, got.n_required), (9, 10))
        self.assertIsInstance(rb.summarize_seeds(
            [MetricValue.measured(float(i)) for i in range(10)], Sneaky(10)), rb.SeedSummary)

    def test_a_float_subclass_cannot_launder_a_summarys_statistics(self):
        """The same pattern on `SeedSummary`: the "statistics match the values" invariant is written in
        `!=`, so a `float` subclass with a lying `__eq__` among the VALUES or the STATISTICS would satisfy
        it while storing something else, and `to_dict` / `canonical_json` would then consult `__float__`.
        `_plain_summary_fields` collapses every field to the value it stores, before the comparison."""
        class Lying(float):
            def __eq__(self, other):
                return True

            def __ne__(self, other):
                return False

            def __float__(self):
                return 1e308

            def __hash__(self):
                return 0
        vals = (1.0, 2.0, 3.0)
        good = rb.SeedSummary.from_values(vals)
        with self.assertRaises(ValueError):          # a lying mean no longer satisfies the invariant
            rb.SeedSummary(3, Lying(99.0), good.sd, good.q1, good.q3, good.iqr, 1.0, 3.0, vals)
        # a float subclass holding the RIGHT number is accepted and stored plain, so to_dict is honest
        ok = rb.SeedSummary(3, Lying(2.0), good.sd, good.q1, good.q3, good.iqr, 1.0, 3.0, vals)
        self.assertIs(type(ok.mean), float)
        self.assertEqual(ok.mean, 2.0)
        self.assertEqual(ok.to_dict()["mean"], 2.0)
        self.assertEqual(json.loads(canonical_json(ok.to_dict()))["mean"], 2.0)
        # and in the VALUES, where it would reach every statistic
        sub = rb.SeedSummary.from_values([Lying(1.0), Lying(2.0), Lying(3.0)])
        self.assertEqual([type(v) for v in sub.values], [float, float, float])
        self.assertEqual(sub.to_dict(), good.to_dict())

    def test_seed_floor_is_pinned_by_value(self):
        self.assertEqual(rb.SEED_FLOOR, 3)
        self.assertIsInstance(rb.SEED_FLOOR, int)
        self.assertNotIsInstance(rb.SEED_FLOOR, bool)
        # the floor's consequence, not just its value: 2 values can never become a summary
        with self.assertRaises(ValueError):
            rb.SeedSummary.from_values([1.0, 2.0])
        self.assertIsInstance(rb.SeedSummary.from_values([1.0, 2.0, 3.0]), rb.SeedSummary)

    def test_the_number_of_seed_floor_defences_is_counted_not_claimed(self):
        """THE TRUE COUNTS, BOTH derived from the source rather than remembered. FIVE numbers have been in
        circulation: a test docstring said "defended three times over", `docs/PROGRESS.md` says "five
        independent points", and the module docstring written to STOP that drift said "four direct
        comparisons and SIX paths" -- of which the four was right and the six was wrong, because it
        counted only `Scorecard.__post_init__`'s two delegations and dropped `_pcfg`'s and
        `summarize_seeds`'s. There are FOUR direct comparisons and EIGHT paths.
        THE REASON THE WRONG NUMBER SURVIVED is the shape of the previous version of this test: it
        MEASURED the 4 from the AST and merely TEXT-pinned the 6 in a comment. Both are measured now."""
        src = Path(rb.__file__).read_text()
        tree = ast.parse(src)
        # every executable comparison against SEED_FLOOR, with the function that owns it. Deduplicated BY
        # LINE NUMBER: `ProbeConfig.__post_init__` and `SeedSummary.__post_init__` are both spelled
        # "__post_init__", so a set of owner names would silently collapse two of the four into one.
        owner = {}
        for fn in ast.walk(tree):
            if isinstance(fn, ast.FunctionDef):
                for sub in ast.walk(fn):
                    owner.setdefault(id(sub), fn.name)
        spans = [(fn.lineno, fn.end_lineno, f"{cls.name}.{fn.name}")
                 for cls in ast.walk(tree) if isinstance(cls, ast.ClassDef)
                 for fn in cls.body if isinstance(fn, ast.FunctionDef)]

        def qualify(lineno, name):
            return next((q for a, b, q in spans if a <= lineno <= b), name)
        sites = sorted({(n.lineno, owner.get(id(n), "<module>"))
                        for n in ast.walk(tree) if isinstance(n, ast.Compare)
                        for sub in ast.walk(n)
                        if isinstance(sub, ast.Name) and sub.id == "SEED_FLOOR"})
        self.assertEqual([f for _, f in sites],
                         ["__post_init__", "__post_init__", "from_values", "_recheck_summary"],
                         f"the SEED_FLOOR comparison sites moved: {sites}")
        self.assertEqual(len(sites), 4, f"SEED_FLOOR is compared at {len(sites)} sites, not 4: {sites}")
        self.assertEqual(len({ln for ln, _ in sites}), 4)            # the line-number dedup is the point
        # and the two "__post_init__" entries really are two DIFFERENT functions. Qualified FROM THE
        # SITES' OWN LINE NUMBERS, not from a census of every `__post_init__` in the module: the census
        # version broke the moment the subclass-normalisation boundary gave `MeasureFixture` and
        # `ShiftSpec` a `__post_init__` apiece, which compare nothing against `SEED_FLOOR` and were
        # never what this assertion was about. A test of "the four sites" must be derived from the four
        # sites.
        classes = sorted({qualify(ln, f) for ln, f in sites if f == "__post_init__"})
        self.assertEqual(classes, ["ProbeConfig.__post_init__", "SeedSummary.__post_init__"])
        # ---- THE PATH COUNT, MEASURED (this is what the previous version only text-pinned): the four
        # direct sites plus every DELEGATION, i.e. every call to a gatekeeper outside its own definition.
        gates = {"ProbeConfig", "_recheck_summary"}
        delegations = sorted({(n.lineno, owner.get(id(n), "<module>"), ast.unparse(n))
                              for n in ast.walk(tree) if isinstance(n, ast.Call)
                              and isinstance(n.func, ast.Name) and n.func.id in gates})
        self.assertEqual([(f, t) for _, f, t in delegations],
                         [("_pcfg", "ProbeConfig()"),
                          ("summarize_seeds", "ProbeConfig(min_seeds)"),
                          ("__post_init__", "ProbeConfig(self.min_seeds)"),
                          ("__post_init__", "_recheck_summary(self.summary)")],
                         f"the SEED_FLOOR delegation sites moved: {delegations}")
        self.assertEqual(len(delegations), 4, f"4 delegations expected, got {delegations}")
        self.assertEqual(len(sites) + len(delegations), 8,
                         "the module docstring quotes EIGHT paths; the AST must agree")
        self.assertIn("EIGHT paths reach", " ".join(rb.__doc__.split()))
        self.assertNotIn("six paths reach them", " ".join(rb.__doc__.split()))
        # Each path is exercised below so the count is not merely syntactic.
        self.assertEqual(len(rb.SeedSummary.from_values([1.0, 2.0, 3.0]).values), 3)
        self.assertEqual(rb._pcfg(None).min_seeds, rb.DEFAULT_MIN_SEEDS)     # delegation 1
        with self.assertRaises(ValueError):                                  # delegation 2
            rb.summarize_seeds([rb.MetricValue.measured(1.0)] * 3, rb.SEED_FLOOR - 1)
        with self.assertRaises(ValueError):                       # ProbeConfig.__post_init__
            rb.ProbeConfig(rb.SEED_FLOOR - 1)
        with self.assertRaises(ValueError):                       # SeedSummary.from_values
            rb.SeedSummary.from_values([1.0, 2.0])
        with self.assertRaises(ValueError):                       # SeedSummary.__post_init__
            rb.SeedSummary(2, 1.5, 0.7071067811865476, 1.25, 1.75, 0.5, 1.0, 2.0, (1.0, 2.0))
        short = rb.SeedSummary.from_values([1.0, 2.0, 3.0])
        object.__setattr__(short, "values", (1.0, 2.0))
        with self.assertRaises(ValueError):                       # _recheck_summary
            rb._recheck_summary(short)
        card = rb.build_scorecard(
            probe_id="p", probe_kind="seed_sensitivity", seeds=SEEDS,
            per_seed=[rb.MetricValue.measured(float(i)) for i in range(12)],
            cfg=rb.ProbeConfig(rb.SEED_FLOOR), status_if_summarized=PS.MEASURED,
            details_always={}, non_claims=("x",))
        with self.assertRaises(ValueError):                       # Scorecard -> ProbeConfig
            dataclasses.replace(card, min_seeds=rb.SEED_FLOOR - 1)
        with self.assertRaises(ValueError):                       # Scorecard -> _recheck_summary
            dataclasses.replace(card, summary=short)

    def test_the_corrected_count_is_stated_wherever_a_number_is_quoted(self):
        """The circulating numbers, reconciled in the places this owner controls. `docs/PROGRESS.md`
        is NOT in this owner's files; its "five independent points" is reported for routing, not edited."""
        mine = " ".join(self.test_the_number_of_seed_floor_defences_is_counted_not_claimed.__doc__.split())
        self.assertIn("There are FOUR direct comparisons and EIGHT paths", mine)
        self.assertIn("MEASURED the 4 from the AST and merely TEXT-pinned the 6", mine)
        # the stale "three times over" is gone from the docstring that carried it
        stale = " ".join(
            TestQAHardening.test_probe_config_defaults_are_constructed_per_call.__doc__.split())
        self.assertNotIn("defended three times over", stale)
        # The wrong figure (D8) may appear ONLY as an attributed correction, never as the docstring's
        # own measurement -- the same convention `test_benchmark` uses for a falsified claim.
        self.assertIn("It said `3 -> summary n=4`", stale)
        self.assertIn("Those hold only for a fixture with exactly FOUR measured values", stale)
        self.assertIn("min_seeds 3, 5, 9, 10, 12 -> SeedSummary n=12", stale)
        self.assertIn("used to pass a **dict** as `per_seed`", stale)
        mod = " ".join(rb.__doc__.split())
        self.assertIn("FOUR direct comparisons against `SEED_FLOOR`", mod)
        self.assertIn("EIGHT paths reach", mod)
        self.assertIn('"SIX" WAS WRONG', mod)
        self.assertNotIn("six paths reach them", mod)


class OneExampleCannotBeRepeatedPastTheSeedGuard(unittest.TestCase):
    """F2. The module docstring names ONE defence against a single example dressed as n of them --
    "Duplicate SEEDS are rejected only on the probe path (`_check_seeds`...)" -- and that defence was
    `len(set(seeds)) != len(seeds)`, i.e. `__hash__` and `__eq__` on the caller's own objects.

    MEASURED, with no `object.__setattr__` and through every public probe: three instances of an `int`
    subclass with `__hash__ = id` and identity `__eq__`, each storing 7, were ACCEPTED where the plain
    list `[7, 7, 7]` is refused. `probe_shift` returned status INVARIANCE_HOLDS with n=3 and
    `violating_seeds=()`; `seed_sensitivity_probe` returned MEASURED with n=3, mean 0.25 and SD 0.0;
    the `outcome` callback really was called three times with 7; and `make_measure_fixture(Seed(7))` is
    the identical fixture. `SEED_FLOOR = 3` -- the whole point of which is "no claims from single
    examples" -- was satisfied by ONE seed.
    `test_duplicate_seeds_rejected` used plain ints only, and this module's `int`-subclass hardening
    class (`ThePolicyParametersAreThemselvesPinned`) pointed at `ProbeConfig`, never at `_check_seeds`.
    The honest limit the fix does NOT remove: the card was already self-incriminating (it serialises
    `[7, 7, 7]` and its `seed_digest` matches), so a reader who recomputed could detect it. The guard
    whose job was to refuse it did not, and the decisive status was produced."""

    class Seed(int):
        def __hash__(self):
            return id(self)

        def __eq__(self, o):
            return self is o

        def __ne__(self, o):
            return self is not o

    class StrSeed(int):
        """Distinct stored values; a lying `__str__`, which is what `derive_seed` formats."""
        def __str__(self):
            return "7"

        def __format__(self, spec):
            return "7"

    def test_every_probe_refuses_a_repeated_seed_however_it_is_spelled(self):
        three = [self.Seed(7), self.Seed(7), self.Seed(7)]
        self.assertEqual([int.__int__(s) for s in three], [7, 7, 7])     # the stored values really repeat
        self.assertNotEqual(three[0], three[1])                          # ... and the subclass denies it
        self.assertEqual(len(set(three)), 3)
        cfg3 = rb.ProbeConfig(3)
        probes = {
            "seed_sensitivity": lambda s: rb.seed_sensitivity_probe(lambda x: 0.25, s, cfg3),
            "shift": lambda s: rb.probe_shift(rb.mse_fsum, rb.shift_reorder_rows(), s, cfg3),
            "missing_inputs": lambda s: rb.probe_missing_inputs(rb.mse_fsum, s, cfg3),
            "precision": lambda s: rb.probe_precision("accumulation", 10, s, cfg3),
            "no_silent_default": lambda s: rb.assert_no_silent_default(rb.mse_fsum, s),
            "build_scorecard": lambda s: rb.build_scorecard(
                probe_id="p", probe_kind="k", seeds=s, per_seed=[MetricValue.measured(1.0)] * 3,
                cfg=cfg3, status_if_summarized=PS.MEASURED, details_always={}),
        }
        for name, fn in probes.items():
            with self.subTest(probe=name):
                for seeds in ([7, 7, 7], three, [self.Seed(7), 7, self.Seed(7)]):
                    with self.assertRaisesRegex(ValueError, "duplicate seeds are rejected"):
                        fn(seeds)
                fn([self.Seed(11), self.Seed(12), self.Seed(13)])        # the honest control still runs

    def test_an_accepted_subclass_seed_is_stored_hashed_and_used_as_a_plain_int(self):
        a = rb.seed_sensitivity_probe(lambda s: float(s % 5), [self.Seed(k) for k in (11, 12, 13)],
                                      rb.ProbeConfig(3), probe_id="p")
        b = rb.seed_sensitivity_probe(lambda s: float(s % 5), (11, 12, 13), rb.ProbeConfig(3),
                                      probe_id="p")
        self.assertEqual({type(s) for s in a.seeds}, {int})
        self.assertEqual(a.to_dict()["seeds"], [11, 12, 13])
        self.assertEqual(a.content_hash(), b.content_hash())     # byte-identical to the plain-int card
        self.assertEqual(a.seed_digest, bm.seed_list_digest((11, 12, 13)))

    def test_two_distinct_seeds_cannot_be_one_fixture(self):
        """F2b's consequence here: `derive_seed` FORMATS the seed into the string it hashes, so a lying
        `__str__` made `derive_seed(StrSeed(9), ...) == derive_seed(7, ...)`. Two seeds that
        `_check_seeds` correctly sees as DISTINCT then produced the same fixture and the same outcome --
        one example n times, with no repeated value anywhere on the card to give it away. Fixed in
        `toy.schema._check_seed`, which returns the plain int every caller then uses."""
        self.assertNotEqual(rb.make_measure_fixture(self.StrSeed(9)).pred,
                            rb.make_measure_fixture(7).pred)
        self.assertEqual(rb.make_measure_fixture(self.StrSeed(9)).pred,
                         rb.make_measure_fixture(9).pred)
        seeds = (7, self.StrSeed(9), 20, 21, 22)
        card = rb.seed_sensitivity_probe(
            lambda s: rb.mse_fsum(*((f := rb.make_measure_fixture(s)).pred, f.target, f.mask)),
            seeds, rb.ProbeConfig(3))
        self.assertIs(card.status, PS.MEASURED)
        self.assertEqual(card.details["n_distinct_values"], 5)     # five fixtures, five outcomes
        self.assertEqual(card.to_dict()["seeds"], [7, 9, 20, 21, 22])


class ACardCannotAssertAMinimumItDoesNotMeet(unittest.TestCase):
    """F3 and the string half of the same sweep.

    `Scorecard.__post_init__` called `ProbeConfig(self.min_seeds)` and THREW THE RESULT AWAY -- the only
    `ProbeConfig(...)` in the module whose result was discarded, 135 lines below `summarize_seeds`'s own
    call, whose comment states the lesson ("The returned object is USED, not discarded") that this site
    did not apply. The field therefore kept the caller's object and `len(measured) < self.min_seeds`,
    sixteen lines below, ran on it with the subclass as the RIGHT operand, so the REFLECTED `__gt__`
    decided -- the same variant the suite had already found for `summarize_seeds` and fixed THERE ONLY.

    The same class of defect in this class's text guards: `self.seed_digest != seed_list_digest(seeds)`
    and `for std in STANDARD_NON_CLAIMS: if std not in dne` are `str` comparisons on fields a caller
    supplies, and a `str` subclass with a lying `__eq__` passes both. Measured consequences: a card
    whose `seed_digest` was "0"*64 over a real seed list (and `scorecard_to_record` then wrote that into
    the record's `input_hashes["seed_list"]`, the provenance anchor), and a card whose entire
    `does_not_establish` tuple was the single string "THIS IS A SAFETY FINDING." while satisfying the
    guard that requires every STANDARD_NON_CLAIMS entry."""

    class Lo(int):
        def __gt__(self, o):
            return False

        def __ge__(self, o):
            return False

    class LoInt(Lo):
        def __int__(self):
            return 999

        def __index__(self):
            return 999

    class LieStr(str):
        def __eq__(self, o):
            return True

        def __ne__(self, o):
            return False

        def __hash__(self):
            return 0

    def three(self):
        return rb.seed_sensitivity_probe(lambda s: float(s % 7), (101, 102, 103), rb.ProbeConfig(3))

    def test_a_forged_min_seeds_cannot_be_laundered_onto_a_card(self):
        three = self.three()
        self.assertEqual(three.summary.n, 3)                         # the control: a real 3-seed card
        for v in (10, self.Lo(10), self.LoInt(10), self.Lo(4), self.LoInt(10 ** 6)):
            with self.subTest(min_seeds=type(v).__name__ + repr(int.__int__(v))):
                with self.assertRaisesRegex(ValueError, "fewer measured seeds than min_seeds"):
                    dataclasses.replace(three, min_seeds=v)
        # below the absolute floor the ProbeConfig delegation must still raise, subclass or not
        for v in (2, self.Lo(2), self.LoInt(0)):
            with self.assertRaises(ValueError, msg=repr(int.__int__(v))):
                dataclasses.replace(three, min_seeds=v)
        # an in-range subclass is accepted and STORED PLAIN, so nothing downstream re-converts it
        ok = dataclasses.replace(three, min_seeds=self.LoInt(3))
        self.assertIs(type(ok.min_seeds), int)
        self.assertEqual(ok.min_seeds, 3)
        self.assertEqual(ok.to_dict()["min_seeds"], 3)
        rec = rb.scorecard_to_record(ok, run_id="r", timestamp_utc=TS)
        self.assertEqual(rec.metrics["min_seeds_required"].value, 3.0)   # NOT 999.0 from __int__
        self.assertIs(type(rec.metrics["min_seeds_required"].value), float)
        self.assertEqual(ok.content_hash(), dataclasses.replace(three, min_seeds=3).content_hash())

    def test_an_insufficient_card_counts_cannot_disagree_with_their_own_minimum(self):
        card = rb.seed_sensitivity_probe(lambda s: 4.0, SEEDS[:5], rb.ProbeConfig(10))
        self.assertIs(card.status, PS.INSUFFICIENT_EVIDENCE)
        self.assertEqual((card.insufficient.n_measured, card.insufficient.n_required), (5, 10))
        self.assertEqual({type(card.insufficient.n_measured), type(card.insufficient.n_required)},
                         {int})
        # the counts are normalised where they are checked, so a subclass cannot assert a false order
        class Ge(int):
            def __ge__(self, o):
                return False

            def __gt__(self, o):
                return False
        with self.assertRaises(ValueError):
            rb.InsufficientEvidence(Ge(10), Ge(3), "forged")
        ok = rb.InsufficientEvidence(Ge(3), Ge(10), "honest")
        self.assertEqual({type(ok.n_measured), type(ok.n_required)}, {int})
        with self.assertRaises(ValueError):
            dataclasses.replace(card, insufficient=rb.InsufficientEvidence(5, Ge(11), "wrong required"))

    def test_a_card_cannot_drop_the_non_claims_it_is_required_to_carry(self):
        card = self.three()
        for bad in ((self.LieStr("THIS IS A SAFETY FINDING."),),
                    (self.LieStr("validated safe"),) + rb.STANDARD_NON_CLAIMS[1:],
                    tuple(self.LieStr("x") for _ in rb.STANDARD_NON_CLAIMS)):
            with self.subTest(dne=bad[0]):
                with self.assertRaisesRegex(ValueError, "STANDARD_NON_CLAIMS"):
                    dataclasses.replace(card, does_not_establish=bad)
        # the honest control: the real entries are accepted and stored as plain strings
        ok = dataclasses.replace(card, does_not_establish=rb.STANDARD_NON_CLAIMS + ("extra",))
        self.assertEqual({type(s) for s in ok.does_not_establish}, {str})
        for std in rb.STANDARD_NON_CLAIMS:
            self.assertIn(std, ok.to_dict()["does_not_establish"])

    def test_a_card_cannot_carry_a_digest_that_is_not_its_seed_lists(self):
        card = self.three()
        for bad in (self.LieStr("0" * 64), self.LieStr(bm.seed_list_digest((1, 2, 3))),
                    self.LieStr("")):
            with self.subTest(digest=bad[:8]):
                with self.assertRaisesRegex(ValueError, "seed_digest does not match"):
                    dataclasses.replace(card, seed_digest=bad)
        ok = dataclasses.replace(card, seed_digest=self.LieStr(bm.seed_list_digest((101, 102, 103))))
        self.assertIs(type(ok.seed_digest), str)
        self.assertEqual(ok.seed_digest, bm.seed_list_digest((101, 102, 103)))
        rec = rb.scorecard_to_record(ok, run_id="r", timestamp_utc=TS)
        self.assertEqual(rec.provenance.input_hashes["seed_list"], ok.seed_digest)
        self.assertEqual(ok.content_hash(), card.content_hash())

    def test_the_module_docstring_states_what_these_guards_now_do(self):
        doc = " ".join(rb.__doc__.split())
        self.assertIn('THAT SENTENCE NAMES THE ONLY DEFENCE, AND THE DEFENCE WAS DEFEATABLE', doc)
        self.assertIn('THE "COUNTS" HALF OF THAT SENTENCE WAS FALSE', doc)
        self.assertIn("ONE OF THE EIGHT USED TO DEFEND LESS THAN THE COUNT IMPLIED", doc)
        self.assertIn("`SEED_FLOOR = 3` was satisfied by ONE seed", doc)


class AMeasureCannotDecideItsOwnProbe(unittest.TestCase):
    """The data-intake points of SR-11's two numeric probes, swept rather than reported one at a time.

    `probe_shift`'s `measure` IS the probe's subject: the module exists to probe arbitrary measures, and
    everything that decides the status is arithmetic on the measure's RETURN VALUE (`dev = abs(val -
    exp)`, then `dev > bound`). MEASURED on a measure that genuinely violates permutation invariance
    (row-position weighting), with ONLY `__sub__` / `__rsub__` overridden to return 0.0 and every
    comparison left honest:
        honest -> INVARIANCE_DEFECT, n_violations=12, max_abs_dev=1.47e-02
        lying  -> INVARIANCE_HOLDS,  n_violations=0,  max_abs_dev=0.0, n_bitwise_equal=12
    i.e. the measure under probe decided that it passes, and the module's own asymmetry ("one failing
    seed refutes an invariance") became unenforceable from the inside.
    `probe_precision`'s `tol` is the same shape one level up: `worst > tol` with `tol` as the right
    operand, so a `float` subclass's reflected `__lt__` reported PRECISION_OK on a worst relative error
    of 5.49e-17 while `details["tolerance"]` serialized the honest 1e-20 -- a card whose declared
    tolerance contradicts its own status."""

    class Hold(float):
        def __sub__(self, o):
            return 0.0

        def __rsub__(self, o):
            return 0.0

    class HoldAll(Hold):
        def __abs__(self):
            return 0.0

        def __gt__(self, o):
            return False

        def __lt__(self, o):
            return True

    class WTol(float):
        def __lt__(self, o):
            return False

        def __gt__(self, o):
            return False

        def __float__(self):
            return 10.0 ** 9

    def test_a_lying_measure_still_reports_its_own_invariance_defect(self):
        honest = rb.probe_shift(row_weighted_mse, rb.shift_reorder_rows(), SEEDS, CFG)
        self.assertIs(honest.status, PS.INVARIANCE_DEFECT)      # the control: the defect IS detected
        for cls in (self.Hold, self.HoldAll):
            def lying(p, t, m, _c=cls):
                return _c(row_weighted_mse(p, t, m))
            lying.__name__ = "row_weighted_mse"
            with self.subTest(sneak=cls.__name__):
                card = rb.probe_shift(lying, rb.shift_reorder_rows(), SEEDS, CFG)
                self.assertIs(card.status, PS.INVARIANCE_DEFECT)
                self.assertEqual(card.details["n_violations"], honest.details["n_violations"])
                self.assertEqual(card.details["violating_seeds"], honest.details["violating_seeds"])
                self.assertEqual(card.details["max_abs_dev"], honest.details["max_abs_dev"])
                self.assertEqual(card.details["n_bitwise_equal"], 0)
                self.assertEqual(card.content_hash(), honest.content_hash())
        # and a measure whose returns are not usable numbers at all is unmeasured, never 0.0
        class NotANumber(float):
            def __float__(self):
                return float("nan")
        for bad in (lambda p, t, m: float("nan"), lambda p, t, m: None, lambda p, t, m: "0.0"):
            card = rb.probe_shift(bad, rb.shift_reorder_rows(), SEEDS, CFG)
            self.assertIs(card.status, PS.INSUFFICIENT_EVIDENCE)
            self.assertTrue(all(not m.is_measured for m in card.per_seed))

    def test_a_lying_declared_expectation_cannot_hide_a_deviation(self):
        """`ShiftSpec.expected` is the other public callable on this path: `exp = spec.expected(base)`
        feeds `exp > 0`, `dev = abs(val - exp)` and the per-seed headline `dev / exp`. A spec whose
        `expected` returns a float subclass therefore chooses its own deviation, even when the measure
        is honest."""
        honest_spec = rb.shift_reorder_rows()
        honest = rb.probe_shift(row_weighted_mse, honest_spec, SEEDS, CFG)
        self.assertIs(honest.status, PS.INVARIANCE_DEFECT)
        lying_spec = dataclasses.replace(honest_spec, expected=lambda b: self.HoldAll(b))
        card = rb.probe_shift(row_weighted_mse, lying_spec, SEEDS, CFG)
        self.assertIs(card.status, PS.INVARIANCE_DEFECT)
        self.assertEqual(card.details["n_violations"], honest.details["n_violations"])
        self.assertEqual(card.details["max_abs_dev"], honest.details["max_abs_dev"])
        # an expectation that is not a usable number at all is unmeasured with a reason, never 0.0
        for bad in (None, "1.0", float("inf")):
            c = rb.probe_shift(rb.mse_fsum, dataclasses.replace(honest_spec, expected=lambda b, _v=bad: _v),
                               SEEDS, CFG)
            self.assertIs(c.status, PS.INSUFFICIENT_EVIDENCE)
            self.assertTrue(all(not m.is_measured for m in c.per_seed))

    def test_the_baseline_value_a_declared_expectation_is_computed_from_is_the_stored_one(self):
        """The third intake on this path, and the one whose mutant SURVIVED the first measurement.

        `base` reaches the decision only through `spec.expected(base)` and `spec.bound(base, exp, fx)`,
        and the result of each is normalised -- so normalising `base` itself is invisible for a spec
        whose `expected` is the identity (every INVARIANCE spec). It is NOT invisible for a spec that
        COMPUTES from the baseline: `shift_scale`'s `expected = lambda b: b * factor ** degree` runs
        `type(base).__mul__`. Measured here on `offset_mse`, which is genuinely not scale-covariant
        (it adds a constant, so scaling by 2**10 must be an EXACT-invariance DEFECT), with a measure
        whose returned value supplies a `__mul__` that reproduces exactly what the measure will return
        on the SHIFTED fixture: the deviation then computes as 0.0 and the defect reads as
        INVARIANCE_HOLDS. Without the normalisation this test fails; with it, `expected` is computed
        from the plain double the measure stored, and the defect is reported."""
        spec = rb.shift_scale(2.0 ** 10)
        honest = rb.probe_shift(offset_mse, spec, SEEDS, CFG)
        self.assertIs(honest.status, PS.INVARIANCE_DEFECT)      # the control: offset_mse IS a defect

        class Arranged(float):
            """`__mul__` answers with the value `offset_mse` returns on the scaled fixture."""
            def __mul__(self, o):
                return (float.__float__(self) - 1.0) * o + 1.0

            def __rmul__(self, o):
                return self.__mul__(o)

        def arranged_measure(p, t, m):
            return Arranged(offset_mse(p, t, m))

        arranged_measure.__name__ = "offset_mse"
        card = rb.probe_shift(arranged_measure, spec, SEEDS, CFG)
        self.assertIs(card.status, PS.INVARIANCE_DEFECT)
        self.assertEqual(card.details["n_violations"], honest.details["n_violations"])
        self.assertEqual(card.content_hash(), honest.content_hash())

    def test_an_exact_invariance_that_really_holds_is_unaffected(self):
        """The normalisation must not turn a holding invariance into a defect: the bit-for-bit case is
        where any spurious conversion would show up first."""
        plain = rb.probe_shift(rb.mse_fsum, rb.shift_reorder_rows(), SEEDS, CFG)
        self.assertIs(plain.status, PS.INVARIANCE_HOLDS)
        self.assertEqual(plain.details["n_bitwise_equal"], len(SEEDS))
        self.assertEqual(plain.details["max_abs_dev"], 0.0)

    def test_a_lying_tolerance_cannot_report_precision_ok(self):
        honest = rb.probe_precision("cancellation", 12, SEEDS, CFG, tol=1e-20)
        self.assertIs(honest.status, PS.PRECISION_LOSS)         # the control: the loss IS reported
        card = rb.probe_precision("cancellation", 12, SEEDS, CFG, tol=self.WTol(1e-20))
        self.assertIs(card.status, PS.PRECISION_LOSS)
        self.assertEqual(card.details["tolerance"], 1e-20)
        self.assertIs(type(card.details["tolerance"]), float)
        self.assertEqual(card.content_hash(), honest.content_hash())
        # the honest direction: a tolerance the error really meets still reads PRECISION_OK
        loose = rb.probe_precision("cancellation", 12, SEEDS, CFG, tol=self.WTol(1e-6))
        self.assertIs(loose.status, PS.PRECISION_OK)
        self.assertEqual(loose.details["tolerance"], 1e-6)

    def test_a_lying_reorder_tolerance_cannot_report_an_invariance_that_failed(self):
        """ROUND-6 FINDING 4: `shift_reorder_rows`'s `rel_tol`, the UN-SWEPT SIBLING of the `tol` the
        test above pins. The two are the same shape one level apart -- a caller-supplied number that is
        the right operand of the comparison deciding the status -- and round 5 fixed `tol`, wrote the
        lesson into `probe_precision`'s comment, and left `rel_tol` alone. That is the failure mode of a
        hand-maintained list of normalisation sites, and it is why the fix of this round is a boundary
        and not a thirteenth call site.
        `rel_tol` is captured in the `bound` closure and MULTIPLIED there (`rel_tol * abs(e)`), i.e.
        `type(rel_tol).__mul__`. MEASURED through the public factory, no `object.__setattr__`, on a
        measure that genuinely violates permutation invariance:
            honest -> INVARIANCE_DEFECT, n_violations=12, max_abs_dev=9.11e-03
            forged -> INVARIANCE_HOLDS,  n_violations=0,  max_abs_dev=9.11e-03
        The forged card SELF-CONTRADICTS -- it serialises a nonzero worst deviation beside a violation
        count of zero -- which is the signature this kit keeps producing when a comparison and a stored
        number come from two different objects."""
        class BigTol(float):
            """Stores 0.0, multiplies to 1e9. Lies in ONE dunder, and in neither comparison."""
            def __mul__(self, other):
                return 1e9

            def __rmul__(self, other):
                return 1e9

        seeds, tol_kind = SEEDS, SK.INVARIANCE_TOLERANCE
        honest = rb.probe_shift(row_weighted_mse, rb.shift_reorder_rows(tol_kind, 0.0), seeds, CFG)
        self.assertIs(honest.status, PS.INVARIANCE_DEFECT)      # the control: the defect IS detected
        self.assertEqual(honest.details["n_violations"], len(seeds))
        card = rb.probe_shift(row_weighted_mse, rb.shift_reorder_rows(tol_kind, BigTol(0.0)), seeds, CFG)
        self.assertIs(card.status, PS.INVARIANCE_DEFECT)
        self.assertEqual(card.details["n_violations"], honest.details["n_violations"])
        self.assertEqual(card.details["violating_seeds"], honest.details["violating_seeds"])
        self.assertEqual(card.details["max_abs_dev"], honest.details["max_abs_dev"])
        self.assertEqual(card.content_hash(), honest.content_hash())
        # the honest direction: a tolerance the deviation really meets still reads INVARIANCE_HOLDS, and
        # it does so for a SUBCLASS holding that tolerance -- the fix must not refuse a legitimate value
        loose = rb.probe_shift(row_weighted_mse, rb.shift_reorder_rows(tol_kind, 1.0), seeds, CFG)
        self.assertIs(loose.status, PS.INVARIANCE_HOLDS)

        class PlainSub(float):
            pass
        same = rb.probe_shift(row_weighted_mse, rb.shift_reorder_rows(tol_kind, PlainSub(1.0)), seeds, CFG)
        self.assertEqual(same.content_hash(), loose.content_hash())
        # and `standard_shifts`, the public path that forwards this parameter, forwards the fix with it
        spec = next(s for s in rb.standard_shifts(tol_kind, BigTol(0.0)) if s.name == "reorder_rows")
        self.assertIs(rb.probe_shift(row_weighted_mse, spec, seeds, CFG).status, PS.INVARIANCE_DEFECT)

    def test_a_lying_deviation_bound_cannot_report_an_invariance_that_failed(self):
        """The GENERAL FORM of the finding above, and the last un-normalised number on this path:
        `bound = 0.0 if exact_kind else float(spec.bound(base, exp, fx2))`. A bare `float()` consults a
        `__float__` OVERRIDE, while `measure`'s and `spec.expected`'s returns -- four and seven lines up
        in the same `try` -- both go through `_plain_measure`. `spec.bound` is public: a caller supplies
        the spec, and every built-in `ShiftSpec` computes its bound from caller-supplied numbers.
        `ShiftSpec.bound` is exempt from the field-normalisation boundary BECAUSE it is a callable, and
        its exemption reason names this call site as where its return is normalised instead."""
        class LyingBound(float):
            def __float__(self):
                return 1e9

        base = rb.shift_reorder_rows(SK.INVARIANCE_TOLERANCE, 0.0)
        honest = rb.probe_shift(row_weighted_mse, base, SEEDS, CFG)
        self.assertIs(honest.status, PS.INVARIANCE_DEFECT)                      # the control
        card = rb.probe_shift(row_weighted_mse,
                              dataclasses.replace(base, bound=lambda b, e, fx: LyingBound(0.0)),
                              SEEDS, CFG)
        self.assertIs(card.status, PS.INVARIANCE_DEFECT)
        self.assertEqual(card.details["n_violations"], honest.details["n_violations"])
        self.assertEqual(card.content_hash(), honest.content_hash())
        # a bound that is not a usable number at all makes the seed unmeasured with a reason -- the
        # fail-closed outcome this probe already uses for a measure that rejects its input -- never 0.0
        for bad in (None, "0.0", float("inf"), float("nan"), [0.0]):
            c = rb.probe_shift(rb.mse_fsum, dataclasses.replace(base, bound=lambda b, e, fx, _v=bad: _v),
                               SEEDS, CFG)
            self.assertIs(c.status, PS.INSUFFICIENT_EVIDENCE, repr(bad))
            self.assertTrue(all(not m.is_measured for m in c.per_seed), repr(bad))
            self.assertIn("deviation bound", c.per_seed[0].reason, repr(bad))
        # the exemption is declared, and its reason names where the return is normalised
        self.assertIn("_plain_measure", rb.ShiftSpec._NORMALISE_EXEMPT["bound"])
        # an INVARIANCE_EXACT spec ignores the bound entirely, which must stay true
        exact = rb.probe_shift(rb.mse_fsum, rb.shift_reorder_rows(), SEEDS, CFG)
        self.assertIs(exact.status, PS.INVARIANCE_HOLDS)
        self.assertIs(rb.probe_shift(rb.mse_fsum,
                                     dataclasses.replace(rb.shift_reorder_rows(),
                                                         bound=lambda b, e, fx: LyingBound(0.0)),
                                     SEEDS, CFG).status, PS.INVARIANCE_HOLDS)

    def test_a_lying_param_cannot_make_the_card_describe_another_probe(self):
        """`param` was used as `int(param)` (how many values are accumulated) and recorded as
        `float(param)`: two independently overridable conversions of one never-normalised argument, so
        `details["param"]` and `probe_id` said 3.0 while 400 values were summed."""
        class PSub(float):
            def __int__(self):
                return 400

            def __index__(self):
                return 400

            def __float__(self):
                return 3.0
        honest = rb.probe_precision("accumulation", 40.0, SEEDS, CFG)
        card = rb.probe_precision("accumulation", PSub(40.0), SEEDS, CFG)
        self.assertEqual(card.details["param"], 40.0)
        self.assertEqual(card.probe_id, honest.probe_id)
        self.assertEqual(card.content_hash(), honest.content_hash())
        # an int param keeps its int spelling, so no probe_id or stored hash moved for the fix
        self.assertEqual(rb.probe_precision("accumulation", 40, SEEDS, CFG).probe_id,
                         "precision:accumulation:40")


class AForgedOutcomeCannotBecomeAZeroVarianceMeasurement(unittest.TestCase):
    """F1's SR-11 entry point, asserted on the probe's own output.

    `_to_metric` -- the data-intake point for the user-supplied `outcome` callback, which is this
    probe's INTENDED extension point -- hands the callback's return straight to
    `MetricValue.measured(v)`. The schema's `value == 0.0` normalisation then asked that object whether
    it was zero, and a `float` subclass with a lying `__eq__` answered yes and had its value REPLACED:
        seed_sensitivity_probe(honest_outcome, range(1, 11)) -> MEASURED mean=7.55 sd=0.303 zvw=False
        seed_sensitivity_probe(forged_outcome, range(1, 11)) -> MEASURED mean=0.0  sd=0.0  zvw=True
    Fixed at the schema (see `test_schema.AMetricStoresTheNumberItChecked`), not at `_to_metric`, and
    this class is the consequence test that makes the schema fix observable from SR-11: the probe's
    status, statistics, per-seed vector and content hash must all be those of the honest outcome."""

    class EqZero(float):
        def __eq__(self, o):
            return True

        def __ne__(self, o):
            return False

        def __hash__(self):
            return 0

    def test_the_probe_reports_the_outcome_it_was_given(self):
        def honest(seed):
            return 7.0 + (seed % 100) / 100.0

        def forged(seed):
            return AForgedOutcomeCannotBecomeAZeroVarianceMeasurement.EqZero(honest(seed))

        forged.__name__ = "honest"
        a = rb.seed_sensitivity_probe(honest, range(1, 11), CFG)
        b = rb.seed_sensitivity_probe(forged, range(1, 11), CFG)
        self.assertIs(a.status, PS.MEASURED)
        self.assertIs(b.status, PS.MEASURED)
        self.assertEqual(b.summary.mean, a.summary.mean)
        self.assertEqual(b.summary.sd, a.summary.sd)
        self.assertEqual(b.summary.values, a.summary.values)
        self.assertNotEqual(b.summary.sd, 0.0)
        self.assertFalse(b.details["zero_variance_warning"])
        self.assertEqual(b.details["n_distinct_values"], 10)
        self.assertEqual({type(m.value) for m in b.per_seed}, {float})
        self.assertEqual(b.content_hash(), a.content_hash())

    def test_a_genuinely_constant_outcome_is_still_flagged(self):
        """The control for the control: the zero-variance flag must still fire when it should, or the
        test above could pass on a probe that never flags anything."""
        c = rb.seed_sensitivity_probe(lambda s: 2.5, range(1, 11), CFG)
        self.assertIs(c.status, PS.MEASURED)
        self.assertEqual(c.summary.sd, 0.0)
        self.assertTrue(c.details["zero_variance_warning"])
        z = rb.seed_sensitivity_probe(lambda s: self.EqZero(2.5), range(1, 11), CFG)
        self.assertEqual(z.summary.mean, 2.5)
        self.assertTrue(z.details["zero_variance_warning"])

    def test_the_decision_to_fix_at_the_schema_is_recorded_where_the_cast_is_missing(self):
        """`SeedSummary.from_values` casts with `float.__float__` and says why; `_to_metric` does not,
        and the asymmetry would read as an oversight. Its docstring states the measured reason."""
        doc = " ".join(rb._to_metric.__doc__.split())
        self.assertIn("WHY THERE IS NO `float.__float__` HERE", doc)
        self.assertIn("it never compares or computes with it", doc)
        self.assertIn("a mutant removing it survives every test", doc)


class EveryDataclassFieldIsNormalisedOrExplicitlyExempt(unittest.TestCase):
    """THE ROUND-6 FIX, on this module's six dataclasses. The twin of
    `test_schema.EveryDataclassFieldIsNormalisedOrExplicitlyExempt`, and it reuses that file's shared
    body so the two cannot drift apart -- which is the failure mode this whole class exists to end.

    What it asserts, per class: that the class is in the registry at all (a NEW dataclass fails closed);
    that `_normalise_fields(self)` is the FIRST statement of its `__post_init__` (a call placed after a
    gate normalises nothing the gate used); and that every field is either stored PLAIN when handed a
    subclass instance, or refused with a `ValueError`, or named in `_NORMALISE_EXEMPT` with a nonblank
    reason. The field list comes from `dataclasses.fields()` and the class list from the module, so
    adding a field DEFAULTS TO COVERED rather than defaulting to forgotten.
    NOT COVERED BY IT, stated so the coverage is not read as larger than it is: a function parameter and
    a closure variable are not fields. That sentence used to continue "`arm_difference`'s arm names,
    `shift_reorder_rows`'s `rel_tol`, `probe_precision`'s `tol` / `param` ... are normalised where they
    are bound", i.e. it answered a boundary's gap with a LIST -- and round 7 found four live routes in
    that list, none of them on it. Parameters are now covered by their own computed boundary:
    `EveryPublicParameterIsNormalisedOrExplicitlyExempt` below. What remains outside BOTH boundaries is
    what a caller-supplied CALLABLE returns, normalised where it is consumed, with its own consequence
    test in this file."""

    def fixtures(self):
        return {
            rb.ProbeConfig: lambda: rb.ProbeConfig(10),
            rb.InsufficientEvidence: lambda: rb.InsufficientEvidence(3, 10, "3 measured of 10"),
            rb.SeedSummary: lambda: rb.SeedSummary.from_values([1.0, 2.0, 3.0]),
            rb.Scorecard: sc_simple,
            rb.MeasureFixture: lambda: rb.make_measure_fixture(1),
            rb.ShiftSpec: rb.shift_reorder_rows,
        }

    def test_robustness_fields_are_covered_or_exempt_with_a_reason(self):
        ts.assert_fields_are_covered_or_exempt(self, rb, self.fixtures(), expected_counts=(35, 3))

    def test_the_three_exemptions_are_the_three_callables_and_say_why(self):
        """An exemption list is only worth having if each entry carries a reason a reader can check, and
        the reason has to name the mechanism that ACTUALLY protects the field. All three are `ShiftSpec`'s
        callables: a callable stores no scalar to collapse, and what it RETURNS is normalised where it is
        consumed. `transform`'s reason had the first half right and the SECOND HALF WRONG, which an
        attester earned and `test_the_transform_reason_names_the_mechanism_that_really_protects_it` below
        measures: it claimed protection because the return "is a fixture, which normalises its own fields
        in MeasureFixture.__post_init__", and `probe_shift` never type-checks that return."""
        ex = dict(rb.ShiftSpec._NORMALISE_EXEMPT)
        self.assertEqual(sorted(ex), ["bound", "expected", "transform"])
        for name, why in ex.items():
            self.assertIn("callable", why, name)
            self.assertIn("_plain_measure", why, name)     # the mechanism, named in every reason
        # `MeasureFixture.__post_init__` may appear in `transform`'s reason ONLY as the mechanism being
        # DENIED, never as the protection -- the convention this file uses for a falsified claim.
        self.assertIn("THIS REASON USED TO NAME THE WRONG MECHANISM", ex["transform"])
        self.assertIn("probe_shift NEVER type-checks this return", ex["transform"])
        self.assertIn("is not what protects anything here", ex["transform"])
        self.assertNotIn("what it RETURNS is a fixture", ex["transform"])
        # and no OTHER class in the module exempts anything
        for cls in self.fixtures():
            if cls is not rb.ShiftSpec:
                self.assertEqual(dict(getattr(cls, "_NORMALISE_EXEMPT", {})), {}, cls.__name__)

    def test_an_honest_card_is_byte_identical_under_the_boundary(self):
        """The boundary must be invisible to honest data: it preserves container IDENTITY when nothing
        needed collapsing, so neither a stored `content_hash` nor an allocation pattern moved."""
        card = sc_simple()
        self.assertEqual(card.content_hash(), sc_simple().content_hash())
        self.assertEqual(_impure_rb(card, "card"), [])
        fx = rb.make_measure_fixture(1)
        self.assertIs(rb.MeasureFixture(fx.seed, fx.pred, fx.target, fx.mask).pred, fx.pred)
        spec = rb.shift_reorder_rows()
        self.assertIs(dataclasses.replace(spec, rationale=spec.rationale).bound, spec.bound)
        # a card built from subclass-wrapped fields is the same card, byte for byte
        kw = {f.name: getattr(card, f.name) for f in dataclasses.fields(card)}
        lied = rb.Scorecard(**{k: ts._subclassed(v) for k, v in kw.items()})
        self.assertEqual(lied.content_hash(), card.content_hash())
        self.assertEqual(_impure_rb(lied, "card"), [])

    def test_the_boundary_did_not_weaken_a_single_existing_refusal(self):
        """A normaliser that quietly became a coercion would be worse than the defect: it would make
        values this module refuses by TYPE acceptable. Every stated refusal is re-asserted."""
        with self.assertRaises(ValueError):
            rb.ProbeConfig(True)                               # bool is not a count
        with self.assertRaises(ValueError):
            rb.ProbeConfig(rb.SEED_FLOOR - 1)
        with self.assertRaises(ValueError):
            rb.SeedSummary.from_values([True, False, True])     # booleans are never measurements
        with self.assertRaises(ValueError):
            rb.SeedSummary.from_values(["1", "2", "3"])         # nor numbers parsed out of text
        with self.assertRaises(ValueError):
            rb.InsufficientEvidence(10, 3, "backwards")
        with self.assertRaises(ValueError):
            dataclasses.replace(sc_simple(), seed_digest="0" * 64)
        with self.assertRaises(ValueError):
            dataclasses.replace(sc_simple(), does_not_establish=("THIS IS A SAFETY FINDING.",))
        with self.assertRaises(ValueError):
            dataclasses.replace(sc_simple(), probe_id="   ")
        with self.assertRaises(ValueError):
            dataclasses.replace(sc_simple(), status="MEASURED")  # a bare str is not a ProbeStatus


# ------------------------------- machine-derived PARAMETER-coverage probe (the round-7 fix)
def _public_callables(namespace=None):
    """Every public callable `toy.robustness` DEFINES, read from the module namespace, not from a list.

    The three clauses are `_install_parameter_boundary`'s, written out again here on purpose: a test that
    asks the code under test for the list of things to check cannot fail when that list is wrong. The two
    lists are cross-checked for equality in
    `test_every_public_callable_is_behind_the_parameter_boundary`, which is where a disagreement surfaces."""
    ns = vars(rb) if namespace is None else namespace
    return {n: f for n, f in ns.items()
            if isinstance(f, types.FunctionType) and not n.startswith("_")
            and getattr(f, "__module__", None) == "toy.robustness"}


def _canonical_calls():
    """One HONEST call per public callable, naming EVERY parameter of it.

    A new parameter has no entry here, and `_parameter_coverage_complaints` requires the registry to name
    every parameter of every public callable -- so a new parameter fails closed twice over (here, and in
    the counts). The values are the ordinary ones a caller would pass; the probe lies about them itself."""
    fx = rb.make_measure_fixture(1)
    matrices = {"pred": fx.pred, "target": fx.target, "mask": fx.mask}
    per_seed = tuple(MetricValue.measured(float(i)) for i in range(12))
    return {
        "summarize_seeds": {"per_seed": per_seed, "min_seeds": 10},
        "require_summary": {"result": rb.SeedSummary.from_values([1.0, 2.0, 3.0])},
        "deep_freeze": {"x": {"a": 1.0, "b": [2, "c"]}},
        "thaw": {"x": {"a": (1.0, "b")}},
        "build_scorecard": {"probe_id": "p", "probe_kind": "seed_sensitivity", "seeds": SEEDS,
                            "per_seed": per_seed, "cfg": CFG, "status_if_summarized": PS.MEASURED,
                            "details_always": {"measure": "m"}, "details_if_summarized": {"n_seen": 1},
                            "non_claims": ("a stated non-claim",)},
        "scorecard_to_record": {"sc": sc_simple(), "run_id": "r1", "timestamp_utc": TS,
                                "code_version": rb.CODE_VERSION},
        "seed_sensitivity_probe": {"outcome": lambda s: float(s % 1000), "seeds": SEEDS, "cfg": CFG,
                                   "probe_id": "demo"},
        "benchmark_outcome": {"factory": fixture_oracle_gated, "metric": "S", "cfg": None},
        "make_measure_fixture": {"seed": 1, "rows": 16, "width": 3, "noise": 0.1, "magnitude_spread": 0},
        "make_order_sensitive_fixture": {"seed": 1, "big": 1e8},
        "mse_naive": dict(matrices),
        "mse_fsum": dict(matrices),
        "abs_bias_naive": dict(matrices),
        "abs_bias_fsum": dict(matrices),
        "abs_bias_plain": dict(matrices),
        "exact_masked_mse": dict(matrices),
        "shift_reorder_rows": {"kind": SK.INVARIANCE_EXACT, "rel_tol": 0.0},
        "shift_masked_out_rows": {},
        "shift_scale": {"factor": 4.0, "degree": 2},
        "shift_translate": {"c": 1000.0},
        "shift_column_offsets": {"offsets": (3.0, -7.0, 0.5)},
        "shift_jitter": {"eps": 1e-6},
        "standard_shifts": {"reorder_kind": SK.INVARIANCE_EXACT, "reorder_rel_tol": 0.0},
        "probe_shift": {"measure": rb.mse_fsum, "spec": rb.shift_reorder_rows(), "seeds": SEEDS,
                        "cfg": CFG, "fixture_factory": rb.make_measure_fixture, "probe_id": "p"},
        "arm_difference": {"arms": {"C0": MetricValue.measured(0.0)}, "treatment": "E", "control": "C0"},
        "guarded": {"measure": rb.mse_fsum},
        "missing_input_cases": {"fx": fx},
        "assert_no_silent_default": {"measure": rb.mse_fsum, "seeds": (0, 1, 2)},
        "probe_missing_inputs": {"measure": rb.mse_fsum, "seeds": SEEDS, "cfg": CFG, "probe_id": "p"},
        "plain_loop_mean": {"values": [1.0, 2.0, 3.0]},
        "probe_precision": {"kind": "magnitude", "param": 1.0, "seeds": SEEDS, "cfg": CFG, "tol": 1e-12,
                            "measure": rb.mse_naive},
        "precision_sweep": {"kind": "magnitude", "params": (1.0, 2.0), "seeds": SEEDS, "cfg": CFG,
                            "tol": 1e-12},
    }


def _spy_behind_the_boundary(name):
    """(callable, dict): a stand-in for `rb.<name>` with the SAME signature, behind the SAME boundary,
    whose body RECORDS WHAT IT RECEIVED and does nothing else.

    THE PART ROUND 7 SAID TO GET RIGHT, and the reason this probe is a spy and not an AST rule. The field
    boundary's AST assertion checks the NAME of the function called as the first statement of
    `__post_init__` and never inspects its ARGUMENT, so `_normalise_fields(InsufficientEvidence(1, 2,
    "inert"))` satisfies it -- mutants M5a/M5b, both unkilled, saved only because hand-placed guards
    still covered those fields. Round 6's lesson "a call after a gate normalises nothing the gate used"
    has that sibling: a call passed the WRONG OBJECT normalises nothing at all. So the assertion here is
    made on the argument as the CALLEE receives it, which no call with the wrong argument can satisfy;
    `test_the_assertion_is_on_the_ARGUMENT_not_on_the_called_name` exhibits the mutant that proves it."""
    original = getattr(rb, name).__wrapped__
    sig = inspect.signature(original)
    seen = {}

    def body(*args, **kwargs):
        seen.update(sig.bind(*args, **kwargs).arguments)
        return None

    body.__name__ = name
    body.__signature__ = sig
    return rb._plain_arguments(body), seen


def _parameter_coverage_complaints(calls=None, boundary=_spy_behind_the_boundary):
    """Every reason the parameter boundary's coverage is incomplete, as a list of strings; [] = covered.

    A function returning complaints rather than a body of assertions, so that its OWN fail-closure is
    testable: `test_a_new_public_function_fails_closed`, `test_a_new_parameter_fails_closed`,
    `test_a_declaration_for_a_parameter_that_can_carry_a_scalar_is_refused` and
    `test_the_assertion_is_on_the_ARGUMENT_not_on_the_called_name` each inject one defect and assert the
    matching complaint appears -- which is the only way to know this probe is not vacuous."""
    calls = _canonical_calls() if calls is None else calls
    public = _public_callables()
    out = []
    for name in sorted(set(public) | set(calls)):
        if name not in public:
            out.append(f"{name}: in the canonical-call registry but not a public callable of the module")
            continue
        fn = public[name]
        if not getattr(fn, "_AT_PARAMETER_BOUNDARY", False):
            out.append(f"{name}: not behind the parameter boundary")
            continue
        if name not in calls:
            out.append(f"{name}: a public callable with no canonical call; add one naming every parameter")
            continue
        params = list(inspect.signature(fn).parameters)
        given = calls[name]
        if set(params) != set(given):
            out.append(f"{name}: the canonical call names {sorted(given)} but the parameters are "
                       f"{sorted(params)}: a new parameter needs a value here and a decision about it")
            continue
        declared = dict(rb._PARAMETER_NO_SCALAR.get(name, {}))
        probe, seen = boundary(name)
        probe(**{p: ts._subclassed(v) for p, v in given.items()})
        for p in params:
            lies = ts._impure(ts._subclassed(given[p]), f"{name}.{p}")
            if p in declared:
                if not str(declared[p]).strip():
                    out.append(f"{name}.{p}: declared in _PARAMETER_NO_SCALAR with no reason recorded")
                if lies:
                    out.append(f"{name}.{p}: declared as carrying no collapsible scalar, but its own "
                               f"probe value carries {lies}")
                continue
            if not lies:
                out.append(f"{name}.{p}: nothing is proven here, because the probe value cannot carry a "
                           "subclass at all; declare it in _PARAMETER_NO_SCALAR with the mechanism that "
                           "does protect it")
            elif p not in seen:
                out.append(f"{name}.{p}: the callee never received it")
            elif ts._impure(seen[p], f"{name}.{p}"):
                out.append(f"{name}.{p}: the callee received {ts._impure(seen[p], f'{name}.{p}')}")
    return out


class EveryPublicParameterIsNormalisedOrExplicitlyExempt(unittest.TestCase):
    """THE ROUND-7 FIX: the field boundary's argument, made once more for PARAMETERS, and for the same
    reason -- four more live routes, none of them on the hand-written list of non-field exceptions.

    What it asserts, derived from the module and not from this file: that every public callable
    `toy.robustness` defines is behind `_plain_arguments` (a NEW PUBLIC FUNCTION fails closed); that the
    canonical-call registry names every parameter of each (a NEW PARAMETER fails closed); that for every
    parameter either the callee PROVABLY receives the plain value when handed a subclass, or the
    parameter is declared in `_PARAMETER_NO_SCALAR` with a reason; and -- the clause that makes the
    declarations self-policing rather than an escape hatch -- that a declared parameter PROVABLY cannot
    carry a collapsible scalar in the first place. Asserted at the CALLEE, on the argument, never on the
    name of a function called: see `_spy_behind_the_boundary`.
    WHAT IT DOES NOT COVER, so the coverage is not read as larger than it is: a method of a class (a
    dataclass's arguments are its fields, which `EveryDataclassFieldIsNormalisedOrExplicitlyExempt`
    covers from `dataclasses.fields()`; `SeedSummary.from_values` casts with `float.__float__` itself);
    what a caller-supplied CALLABLE returns; and `object.__setattr__`."""

    def test_every_public_callable_is_behind_the_parameter_boundary(self):
        public = _public_callables()
        self.assertEqual(sorted(public), list(rb._PARAMETER_BOUNDARY),
                         "the module namespace and the installer disagree about the public callables")
        for name, fn in sorted(public.items()):
            self.assertTrue(getattr(fn, "_AT_PARAMETER_BOUNDARY", False), name)
            self.assertIsNot(inspect.unwrap(fn), fn, name)          # a real wrapper, not a marked def
            self.assertEqual(fn.__name__, name)
            self.assertEqual(fn.__doc__, inspect.unwrap(fn).__doc__, name)
        self.assertEqual(len(public), 32, sorted(public))

    def test_every_parameter_is_normalised_or_declared_with_a_reason(self):
        self.assertEqual(_parameter_coverage_complaints(), [])
        calls = _canonical_calls()
        n_params = sum(len(inspect.signature(getattr(rb, n)).parameters) for n in calls)
        n_declared = sum(len(v) for v in rb._PARAMETER_NO_SCALAR.values())
        self.assertEqual((n_params, n_declared), (88, 30),
                         "the parameter / declaration counts moved. This is not a rubber stamp: confirm "
                         "the new parameter is covered (it is, by default) or declare it with the "
                         "mechanism that protects it, then update the count -- a count that is remembered "
                         "rather than measured is how five numbers got into circulation for SEED_FLOOR.")

    def test_what_the_two_boundaries_leave_is_measured_not_described(self):
        """"Methods are not covered" is a sentence a reader has to trust. This MEASURES the set: every
        public method of every public class in the module that takes an argument at all, derived from
        `vars(cls)`, is enumerated and each one's mechanism is named. Three exist, and a fourth fails
        here rather than being noticed."""
        found = []
        for cname, cls in sorted(vars(rb).items()):
            if cname.startswith("_") or not (isinstance(cls, type) and cls.__module__ == "toy.robustness"):
                continue
            for mname, member in sorted(vars(cls).items()):
                fn = member.__func__ if isinstance(member, (classmethod, staticmethod)) else member
                if mname.startswith("_") or not inspect.isfunction(fn):
                    continue
                if [p for p in inspect.signature(fn).parameters if p not in ("self", "cls")]:
                    found.append(f"{cname}.{mname}")
        self.assertEqual(found, ["SeedSummary.from_values", "ShiftSpec.bound", "ShiftSpec.expected"],
                         "a public method taking an argument appeared or vanished: state its mechanism")
        # 1. from_values casts every value itself and builds through __post_init__, which normalises
        values = [ts._subclassed(1.0), ts._subclassed(2.0), 3.0]
        self.assertNotEqual(ts._impure(values, "values"), [])
        self.assertEqual(ts._impure(rb.SeedSummary.from_values(values), "summary"), [])
        self.assertIn("float.__float__(v) if isinstance(v, float)",
                      inspect.getsource(rb.SeedSummary.from_values))
        # 2-3. the two default callables of ShiftSpec: their RETURNS are normalised at consumption, and
        # that is what their field exemptions say
        for field in ("expected", "bound"):
            self.assertIn("_plain_measure", rb.ShiftSpec._NORMALISE_EXEMPT[field])

    def test_a_new_public_function_fails_closed(self):
        """A function added to this module is covered by the boundary ONLY if the installer ran over it,
        and is PROVEN covered only if the registry names its parameters. Both are asserted by injecting
        one, which is the evidence that the two assertions above are not vacuous."""
        def probe_everything(threshold=1.0):
            return threshold
        probe_everything.__module__ = "toy.robustness"
        with mock.patch.object(rb, "probe_everything", probe_everything, create=True):
            self.assertIn("probe_everything", _public_callables())
            self.assertIn("probe_everything: not behind the parameter boundary",
                          _parameter_coverage_complaints())
        # and once it IS behind the boundary, it still fails for having no canonical call
        with mock.patch.object(rb, "probe_everything", rb._plain_arguments(probe_everything), create=True):
            self.assertEqual([c for c in _parameter_coverage_complaints() if "probe_everything" in c],
                             ["probe_everything: a public callable with no canonical call; add one "
                              "naming every parameter"])
        self.assertNotIn("probe_everything", _public_callables())   # the injection is gone

    def test_a_new_parameter_fails_closed(self):
        """A parameter ADDED to an existing public callable is normalised by default -- that is the point
        of the boundary -- but it is not PROVEN so until someone states a value for it and decides
        whether it can carry a scalar. Injected on `shift_jitter`, the factory of F2."""
        def shift_jitter(eps, extra_tolerance=1.0):
            return rb.shift_jitter(eps)
        shift_jitter.__module__ = "toy.robustness"
        with mock.patch.object(rb, "shift_jitter", rb._plain_arguments(shift_jitter)):
            complaints = [c for c in _parameter_coverage_complaints() if "shift_jitter" in c]
        self.assertEqual(len(complaints), 1, complaints)
        self.assertIn("extra_tolerance", complaints[0])
        self.assertIn("a new parameter needs a value here", complaints[0])
        self.assertEqual(_parameter_coverage_complaints(), [])      # and the real module is still clean

    def test_the_assertion_is_on_the_ARGUMENT_not_on_the_called_name(self):
        """THE MUTANT THAT PROVES IT, and the measurement that made it necessary. The field boundary's
        coverage test asserts that the FIRST STATEMENT of `__post_init__` is a call to
        `_normalise_fields` -- by NAME, never looking at the argument -- so a body reading
        `_normalise_fields(InsufficientEvidence(1, 2, "inert"))` passes it while normalising nothing
        (M5a/M5b, both unkilled). The same mutant for this boundary calls `_plain_value` on an inert
        object and forwards the caller's arguments untouched: it satisfies every source-level rule about
        the call and is killed here, because what is asserted is the argument the CALLEE received."""
        def name_only_boundary(name):
            original = getattr(rb, name).__wrapped__
            sig = inspect.signature(original)
            seen = {}

            def body(*args, **kwargs):
                seen.update(sig.bind(*args, **kwargs).arguments)
                return None

            @functools.wraps(body)
            def mutant(*args, **kwargs):
                rb._plain_value("inert")                # the right name, the wrong object
                return body(*args, **kwargs)

            body.__name__ = name
            body.__signature__ = sig
            mutant.__signature__ = sig
            return mutant, seen
        # the mutant's own source satisfies a name-only rule, exactly as M5a/M5b satisfied the AST one
        self.assertIn("_plain_value(", inspect.getsource(name_only_boundary))
        m5 = ast.parse("def __post_init__(self):\n"
                       "    _normalise_fields(InsufficientEvidence(1, 2, 'inert'))\n").body[0].body[0]
        self.assertTrue(isinstance(m5, ast.Expr) and isinstance(m5.value, ast.Call)
                        and getattr(m5.value.func, "id", None) == "_normalise_fields",
                        "the field boundary's rule is a name check, which is the point of this test")
        complaints = _parameter_coverage_complaints(boundary=name_only_boundary)
        self.assertNotEqual(complaints, [], "a boundary that normalises an inert object passed this probe")
        self.assertIn("probe_precision.kind: the callee received", " ".join(complaints))
        self.assertIn("make_measure_fixture.rows: the callee received", " ".join(complaints))
        self.assertIn("shift_jitter.eps: the callee received", " ".join(complaints))
        self.assertIn("shift_scale.factor: the callee received", " ".join(complaints))

    def test_a_declaration_for_a_parameter_that_can_carry_a_scalar_is_refused(self):
        """The clause that stops `_PARAMETER_NO_SCALAR` being an escape hatch, and the difference from
        the field boundary's `_NORMALISE_EXEMPT` (which really does skip the field): a declaration is
        accepted only where the probe CONFIRMS there was nothing to collapse. Declaring F1's `kind` --
        the parameter whose whole finding is that it carries one -- is refused."""
        forged = dict(rb._PARAMETER_NO_SCALAR)
        forged["probe_precision"] = {"kind": "a reason that reads plausibly and is false"}
        with mock.patch.object(rb, "_PARAMETER_NO_SCALAR", forged):
            complaints = [c for c in _parameter_coverage_complaints() if "probe_precision.kind" in c]
        self.assertEqual(len(complaints), 1, complaints)
        self.assertIn("declared as carrying no collapsible scalar, but its own probe value carries",
                      complaints[0])

    def test_a_stale_declaration_fails_at_import_not_at_review_time(self):
        """A reason for a parameter that no longer exists is a stale reason, and a stale reason is how
        `transform`'s wrong mechanism survived. The installer refuses one while importing the module."""
        with self.assertRaises(ValueError) as cm:
            rb._install_parameter_boundary({})      # a namespace with no public callables at all
        self.assertIn("_PARAMETER_NO_SCALAR names parameters that do not exist", str(cm.exception))
        self.assertIn("probe_shift.measure", str(cm.exception))
        self.assertEqual(_parameter_coverage_complaints(), [])      # and nothing was disturbed

    def test_every_declared_reason_names_a_mechanism_and_the_six_reasons_are_shared(self):
        """Thirty declarations, six reasons: a reason written per site is a reason nobody re-reads. Each
        names the mechanism that protects the parameter instead of this boundary."""
        reasons = {why for ps in rb._PARAMETER_NO_SCALAR.values() for why in ps.values()}
        self.assertEqual(len(reasons), 6, sorted(reasons))
        for why in reasons:
            self.assertTrue(why.strip())
            self.assertTrue(any(m in why for m in ("_plain_measure", "_to_metric", "_normalise_fields",
                                                   "isinstance", "check_mask")), why)
        # the mask reason's claim is checkable, so it is checked: a non-bool mask element is refused
        fx = rb.make_measure_fixture(1)
        for m in (rb.mse_naive, rb.mse_fsum, rb.abs_bias_fsum):
            with self.assertRaises((ValueError, TypeError, ArithmeticError)) as cm:
                m(fx.pred, fx.target, tuple(1 if b else 0 for b in fx.mask))
            self.assertIn("strict bool", str(cm.exception))
        self.assertIn("truthiness is not accepted", rb._WHY_MASK)

    def test_the_carrier_reason_states_the_duck_typed_route_it_does_not_close(self):
        """A reason is only worth having if it is true, and writing this one honestly found a NOTE the
        obvious wording would have hidden -- the same shape as the `transform` correction an attester
        earned. `_WHY_CARRIER` covers seven parameters, and apart from `require_summary` NONE of their
        functions type-checks the carrier. MEASURED: a hand-built namespace whose `min_seeds` has a lying
        `__float__` is accepted by `scorecard_to_record`, which records `min_seeds_required = 1.0` beside
        an `input_hashes["scorecard"]` for a card that says 10.
        Recorded as a note, not fixed: a caller who can hand-build that namespace can write any
        `ExperimentRecord` directly, so it grants them nothing they lack (the `transform` reasoning).
        IF THIS TEST FAILS BECAUSE A TYPE CHECK WAS ADDED, that is a fix and not a regression -- update
        `_WHY_CARRIER` to say so, because a reason that names the wrong mechanism is what this round had
        to correct."""
        card = sc_simple()

        class LyingMin(int):
            def __float__(self):
                return 1.0
        duck = SimpleNamespace(seeds=card.seeds, per_seed=card.per_seed, summary=card.summary,
                               insufficient=None, min_seeds=LyingMin(10), seed_digest=card.seed_digest,
                               probe_id="demo", probe_kind="seed_sensitivity", status=card.status,
                               content_hash=card.content_hash)
        rec = rb.scorecard_to_record(duck, run_id="r", timestamp_utc=TS)
        self.assertEqual(bm._metric_read(rec.metrics["min_seeds_required"]), 1.0)
        self.assertEqual(rec.provenance.input_hashes["scorecard"], card.content_hash())
        self.assertEqual(card.min_seeds, 10)                 # the card the hash belongs to says 10
        self.assertIs(rb._PARAMETER_NO_SCALAR["scorecard_to_record"]["sc"], rb._WHY_CARRIER)
        self.assertIn("type-checks nothing either", rb._WHY_CARRIER)
        self.assertIn("min_seeds_required = 1.0", rb._WHY_CARRIER)
        self.assertIn("grants them nothing", rb._WHY_CARRIER)
        # and the one carrier parameter that IS type-checked really is
        with self.assertRaises(rb.InsufficientEvidenceError):
            rb.require_summary(SimpleNamespace(n=12, mean=0.0, values=(1.0, 2.0, 3.0)))

    def test_the_boundary_is_invisible_to_honest_data(self):
        """A normalisation that moved an honest byte, or rebuilt an honest container, would be a breaking
        change for every stored `content_hash` and a behaviour change a reader cannot see. Asserted as
        IDENTITY of every argument of every public callable, and as equality of a card and a record built
        THROUGH the boundary with the same built around it (`__wrapped__`)."""
        for name, given in sorted(_canonical_calls().items()):
            probe, seen = _spy_behind_the_boundary(name)
            probe(**given)
            for p, v in given.items():
                self.assertIs(seen[p], v, f"{name}.{p} was rebuilt by the boundary")
        f = lambda s: float(s % 1000)                                       # noqa: E731
        around = rb.seed_sensitivity_probe.__wrapped__(f, SEEDS, CFG, probe_id="demo")
        through = rb.seed_sensitivity_probe(f, SEEDS, CFG, probe_id="demo")
        self.assertEqual(through.content_hash(), around.content_hash())
        self.assertEqual(rb.scorecard_to_record(through, run_id="r", timestamp_utc=TS).content_hash(),
                         rb.scorecard_to_record.__wrapped__(around, run_id="r", timestamp_utc=TS)
                         .content_hash())
        self.assertEqual(_impure_rb(through, "card"), [])

    def test_the_boundary_did_not_weaken_a_single_existing_refusal(self):
        """A normaliser that quietly became a coercion would be worse than the defect: `_plain_value`
        collapses a SUBCLASS to the value it stores and must never make a value this module refuses by
        TYPE acceptable. Every refusal on a parameter path is re-asserted."""
        fx = rb.make_measure_fixture(1)
        for bad in (True, -1, 2 ** 64, "7", 1.5):
            with self.assertRaises((ValueError, TypeError), msg=repr(bad)):
                rb.seed_sensitivity_probe(lambda s: 1.0, (bad, 2, 3), rb.ProbeConfig(3))
        with self.assertRaises(ValueError):
            rb.seed_sensitivity_probe(lambda s: 1.0, (7, 7, 7), rb.ProbeConfig(3))   # duplicate seeds
        with self.assertRaises(ValueError):
            rb.probe_precision("MAGNITUDE", 1.0, SEEDS, CFG)         # unknown kind
        with self.assertRaises(ValueError):
            rb.make_measure_fixture(1, rows=3)
        with self.assertRaises(ValueError):
            rb.make_measure_fixture(1, width=0)
        with self.assertRaises(ValueError):
            rb.arm_difference([("C0", MetricValue.measured(0.0))], "C0", "C0")   # not a mapping
        with self.assertRaises(ValueError):
            rb.summarize_seeds([1.0] * 12, 10)                       # not MetricValues
        with self.assertRaises(ValueError):
            rb.summarize_seeds([MetricValue.measured(1.0)] * 3, rb.SEED_FLOOR - 1)
        with self.assertRaises(ValueError):
            rb.deep_freeze({1: "a key that is not a str"})
        with self.assertRaises(rb.InsufficientEvidenceError):
            rb.require_summary(rb.InsufficientEvidence(3, 10, "3 of 10"))
        with self.assertRaises(TypeError):
            rb.mse_fsum(fx.pred, fx.target)                          # the callee's own arity error
        with self.assertRaises(TypeError):
            rb.probe_shift(rb.mse_fsum, rb.shift_reorder_rows(), SEEDS, CFG, no_such_parameter=1)


class TheParameterBoundaryClosesFourLiveRoutes(unittest.TestCase):
    """F1-F4 of round 7, each measured as the consequence it HAD, and each closed by the parameter
    boundary rather than by a fifth hand-placed call.

    Every lying type below is reachable through a PUBLIC parameter with no `object.__setattr__`, and lies
    only in the operator the gate or the construction is written in -- `isinstance`, `str.__str__`,
    `repr`, `float.__float__`, `int.__int__` and `math.frexp` are all honest, which is why the card the
    pre-fix run produced looks exactly like an honest one. The assertion in each case is the strongest
    available: the lying run's card is byte-identical to the honest run's."""

    class LyingKind(str):
        """Stores "magnitude"; compares and hashes as "cancellation"."""
        def __eq__(self, other):
            return "cancellation" == other if isinstance(other, str) else NotImplemented

        def __ne__(self, other):
            return not self.__eq__(other) if isinstance(other, str) else NotImplemented

        def __hash__(self):
            return hash("cancellation")

    class LyingEps(float):
        """Stores 1e-6; every multiplication it takes part in answers 1e9."""
        def __mul__(self, other):
            return 1e9

        __rmul__ = __mul__

    class LyingFactor(float):
        """Stores 4.0; `factor ** degree` answers 4.0 for every degree."""
        def __pow__(self, other, mod=None):
            return 4.0

    class LyingRows(int):
        """Stores its value; answers False to every ordering comparison, so `rows < 4` is False."""
        def __lt__(self, other):
            return False

        def __gt__(self, other):
            return False

        def __le__(self, other):
            return False

        def __ge__(self, other):
            return False

    def test_F1_a_lying_precision_kind_cannot_run_a_construction_the_card_does_not_name(self):
        """`kind` is `tol`'s and `param`'s sibling IN THE SAME SIGNATURE, and the only one of the three
        that was not normalised. PRE-FIX, measured on 3.13.5 and 3.12.4: INSUFFICIENT_EVIDENCE ->
        PRECISION_OK, labels (NOT_VALIDATED, UNKNOWN) -> (NOT_VALIDATED, TOY_RESULT), summary None ->
        n=12 mean=3.799e-17 sd=2.928e-17 -- a measurement where the honest run has NONE, on a card
        reading `precision:magnitude:200.0` with `details["kind"] == "magnitude"`."""
        honest = rb.probe_precision("magnitude", 200.0, SEEDS, CFG)
        self.assertIs(honest.status, PS.INSUFFICIENT_EVIDENCE)       # the control: 10**200 squares overflow
        self.assertIsNone(honest.summary)
        self.assertEqual(sorted(e.name for e in honest.evidence_labels), ["NOT_VALIDATED", "UNKNOWN"])
        k = self.LyingKind("magnitude")
        self.assertIsInstance(k, str)                                # every honest read is honest
        self.assertEqual(str(k), "magnitude")
        self.assertEqual(repr(k), "'magnitude'")
        self.assertTrue(k == "cancellation" and k != "magnitude")    # and the lie is the operator
        lying = rb.probe_precision(k, 200.0, SEEDS, CFG)
        self.assertIs(lying.status, PS.INSUFFICIENT_EVIDENCE)
        self.assertIsNone(lying.summary)
        self.assertNotIn(EvidenceClass.TOY_RESULT, lying.evidence_labels)
        self.assertEqual(lying.content_hash(), honest.content_hash())
        self.assertEqual(lying.details["kind"], "magnitude")
        self.assertIs(type(lying.details["kind"]), str)

    def test_F2_a_lying_jitter_eps_cannot_move_the_bound_it_is_measured_against(self):
        """`eps` is `shift_reorder_rows`'s `rel_tol` one factory down, and NOT the already-closed
        `spec.bound`-RETURN route: `_plain_measure` collapses that return correctly and the lie has
        already happened inside the closure, which returns a perfectly plain float. PRE-FIX, on both
        interpreters: SENSITIVITY_EXCEEDS_BOUND (12 violations, max_dev_over_bound 2.924e+04) ->
        SENSITIVITY_WITHIN_BOUND (0 violations, 1.287e-16) with `max_abs_dev` IDENTICAL at
        2.573404667950953e-07 -- the proof that the applied jitter never changed and only the bound
        moved, and the self-contradiction the card then serialises."""
        fac = lambda s: rb.make_measure_fixture(s, noise=1e-9)        # noqa: E731
        honest = rb.probe_shift(rb.abs_bias_fsum, rb.shift_jitter(1e-6), SEEDS, CFG, fixture_factory=fac)
        self.assertIs(honest.status, PS.SENSITIVITY_EXCEEDS_BOUND)   # the control: the bound IS exceeded
        self.assertEqual(honest.details["n_violations"], 12)
        e = self.LyingEps(1e-6)
        self.assertEqual(float.__float__(e), 1e-6)
        self.assertEqual(repr(e), "1e-06")
        self.assertEqual(2.0 * e, 1e9)                               # the reflected operator decides
        self.assertEqual(e * e, 1e9)
        lying = rb.probe_shift(rb.abs_bias_fsum, rb.shift_jitter(e), SEEDS, CFG, fixture_factory=fac)
        self.assertIs(lying.status, PS.SENSITIVITY_EXCEEDS_BOUND)
        self.assertEqual(lying.details["n_violations"], 12)
        self.assertEqual(lying.details["max_abs_dev"], honest.details["max_abs_dev"])
        self.assertEqual(lying.content_hash(), honest.content_hash())

    def test_F3_a_lying_scale_factor_cannot_certify_a_degree_2_invariance_on_a_degree_1_measure(self):
        """`factor ** degree` is `type(factor).__pow__` inside the `expected` closure, and
        `math.frexp(factor)` stays honest, so the card still reads INVARIANCE_EXACT and `scale_4.0`.
        PRE-FIX, on both interpreters, with `abs_bias_fsum` (degree 1) under a DECLARED degree 2:
        INVARIANCE_DEFECT (12 violations, max_abs_dev 1.225e-01) -> INVARIANCE_HOLDS with
        n_bitwise_equal 12."""
        honest = rb.probe_shift(rb.abs_bias_fsum, rb.shift_scale(4.0, 2), SEEDS, CFG)
        self.assertIs(honest.status, PS.INVARIANCE_DEFECT)           # the control: degree 1 != degree 2
        self.assertEqual(honest.details["n_violations"], 12)
        f = self.LyingFactor(4.0)
        self.assertEqual(math.frexp(f)[0], 0.5)                      # the honest read, and the classifier
        self.assertEqual(float.__float__(f), 4.0)
        self.assertEqual(f ** 2, 4.0)                                # the lie
        spec = rb.shift_scale(f, 2)
        self.assertEqual(spec.name, "scale_4.0")
        self.assertIs(spec.kind, SK.INVARIANCE_EXACT)
        lying = rb.probe_shift(rb.abs_bias_fsum, spec, SEEDS, CFG)
        self.assertIs(lying.status, PS.INVARIANCE_DEFECT)
        self.assertEqual(lying.details["n_bitwise_equal"], 0)
        self.assertEqual(lying.content_hash(), honest.content_hash())

    def test_F4_a_lying_row_count_cannot_measure_on_fixtures_the_module_refuses_to_build(self):
        """`rows < 4` is `type(rows).__lt__`, so `rows` defeated its OWN gate. PRE-FIX, on both
        interpreters: `make_measure_fixture(1, rows=Lo(3))` built 3 rows, and
        `probe_shift(mse_fsum, shift_reorder_rows(), SEEDS, CFG, fixture_factory=...rows=Lo(3))` went
        INSUFFICIENT_EVIDENCE -> INVARIANCE_HOLDS with TOY_RESULT and a 12-seed summary."""
        r3 = self.LyingRows(3)
        self.assertEqual(int.__int__(r3), 3)
        self.assertIsInstance(r3, int)
        self.assertFalse(isinstance(r3, bool))
        self.assertFalse(r3 < 4)                                     # the lie, in the gate's own operator
        with self.assertRaisesRegex(ValueError, "need rows >= 4"):
            rb.make_measure_fixture(1, rows=r3)
        honest = rb.probe_shift(rb.mse_fsum, rb.shift_reorder_rows(), SEEDS, CFG,
                                fixture_factory=lambda s: rb.make_measure_fixture(s, rows=3))
        lying = rb.probe_shift(rb.mse_fsum, rb.shift_reorder_rows(), SEEDS, CFG,
                               fixture_factory=lambda s: rb.make_measure_fixture(s, rows=r3))
        self.assertIs(honest.status, PS.INSUFFICIENT_EVIDENCE)       # the control
        self.assertIs(lying.status, PS.INSUFFICIENT_EVIDENCE)
        self.assertIsNone(lying.summary)
        self.assertNotIn(EvidenceClass.TOY_RESULT, lying.evidence_labels)
        self.assertEqual(lying.content_hash(), honest.content_hash())

    def test_F4_the_second_consequence_an_error_outside_the_declared_family_escaping_a_public_probe(self):
        """SEPARATE from the status flip, and the same class as the `OverflowError` escape
        `toy.benchmark._check_margin` had to close. `make_measure_fixture(1, rows=2)` raises the
        documented `ValueError`; PRE-FIX `rows=Lo(2)` reached `rng.sample(range(2), 2)`, forced both
        indices True and then `rng.choice([])` -- `IndexError: Cannot choose from an empty sequence`,
        OUTSIDE the `(ValueError, TypeError, ArithmeticError)` family every probe declares, so it
        escaped `probe_shift`'s own fail-closed handler and propagated out of a public probe."""
        r2 = self.LyingRows(2)
        with self.assertRaises(ValueError) as cm:
            rb.make_measure_fixture(1, rows=2)
        self.assertIn("need rows >= 4", str(cm.exception))
        with self.assertRaises(ValueError) as cm:                    # the SAME error, not an IndexError
            rb.make_measure_fixture(1, rows=r2)
        self.assertIn("need rows >= 4", str(cm.exception))
        card = rb.probe_shift(rb.mse_fsum, rb.shift_reorder_rows(), SEEDS, CFG,
                              fixture_factory=lambda s: rb.make_measure_fixture(s, rows=r2))
        self.assertIs(card.status, PS.INSUFFICIENT_EVIDENCE)         # recorded, not propagated
        self.assertEqual(card.insufficient.n_measured, 0)
        for m in card.per_seed:
            self.assertFalse(bm._metric_ok(m))
            self.assertIn("ValueError", m.reason)
        # and the error family every probe declares is the one the module documents
        self.assertIn("(ValueError, TypeError, ArithmeticError)", rb.make_measure_fixture.__doc__)


class AClosureVariableOfAFactoryIsItsParameter(unittest.TestCase):
    """Round 7's second warning, VERIFIED rather than assumed: "closure variables are not parameters of
    the function that uses them", so a signature-driven boundary looks like it cannot reach F2's `eps`
    and F3's `factor`. It does, and the reason is worth stating: those variables are not free variables
    of some unrelated scope, they are the FACTORY's own parameters, captured by a lambda the factory
    builds. Normalising the factory's parameter normalises the cell the lambda reads.
    What this class asserts is the cell itself -- `spec.bound.__closure__` / `spec.expected.__closure__`
    -- and not a status, because a status test could pass for a reason that has nothing to do with the
    closure. The statuses are in `TheParameterBoundaryClosesFourLiveRoutes`."""

    def cells(self, fn):
        return {} if fn.__closure__ is None else dict(zip(fn.__code__.co_freevars, fn.__closure__))

    def test_every_factory_captures_the_plain_value_in_the_cell_the_lambda_reads(self):
        lying = {
            "shift_jitter": (lambda v: rb.shift_jitter(v), TheParameterBoundaryClosesFourLiveRoutes.LyingEps(1e-6), "bound", "eps"),
            "shift_scale": (lambda v: rb.shift_scale(v, 2), TheParameterBoundaryClosesFourLiveRoutes.LyingFactor(4.0), "expected", "factor"),
            "shift_reorder_rows": (lambda v: rb.shift_reorder_rows(SK.INVARIANCE_TOLERANCE, v),
                                   type("RelTol", (float,), {"__mul__": lambda s, o: 1e9})(0.0), "bound", "rel_tol"),
            "shift_translate": (lambda v: rb.shift_translate(v), type("C", (float,), {})(1000.0), "transform", "c"),
        }
        for name, (build, value, attr, cell) in sorted(lying.items()):
            with self.subTest(factory=name):
                self.assertIsNot(type(value), float)                  # the input really is a subclass
                spec = build(value)
                cells = self.cells(getattr(spec, attr))
                self.assertIn(cell, cells, f"{name}: {attr} does not close over {cell}")
                held = cells[cell].cell_contents
                self.assertIs(type(held), float, f"{name}: the closure cell holds a {type(held).__name__}")
                self.assertEqual(held, float.__float__(value))
        # the container case: elements, not just the cell
        offs = type("Off", (float,), {})(3.0)
        spec = rb.shift_column_offsets((offs, -7.0))
        held = self.cells(spec.transform)["offsets"].cell_contents
        self.assertEqual([type(x) for x in held], [float, float])

    def test_the_boundary_reaches_the_cell_because_the_cell_is_a_parameter(self):
        """The mechanism, asserted rather than described: the un-wrapped factory stores the caller's
        object in the cell, the wrapped one stores the plain value, and nothing else differs."""
        e = TheParameterBoundaryClosesFourLiveRoutes.LyingEps(1e-6)
        around = rb.shift_jitter.__wrapped__(e)                      # the factory without the boundary
        through = rb.shift_jitter(e)
        self.assertIs(type(self.cells(around.bound)["eps"].cell_contents), type(e))
        self.assertIs(type(self.cells(through.bound)["eps"].cell_contents), float)
        self.assertEqual(around.name, through.name)
        self.assertEqual(around.bound(1.0, 1.0, None), 2e9)          # and the cell really decides
        self.assertAlmostEqual(through.bound(1.0, 1.0, None), 2e-6, delta=1e-11)

    def test_the_transform_reason_names_the_mechanism_that_really_protects_it(self):
        """THE WORDING CORRECTION AN ATTESTER EARNED, with the measurement that forced it.
        `ShiftSpec._NORMALISE_EXEMPT["transform"]` claimed protection because the return "is a fixture,
        which normalises its own fields in MeasureFixture.__post_init__" -- and `probe_shift` never
        type-checks that return. MEASURED here: a duck-typed `SimpleNamespace` carrying a `float`
        subclass whose `__abs__` answers 1e36 reaches `measure` and `_masked_stats` unchallenged and
        moves `max_dev_over_bound` from 4.034e-02 to 4.042e-35 (a factor of ~1e33), while the SAME lying
        element inside a real `MeasureFixture` is collapsed by that `__post_init__` and reproduces
        4.034e-02 exactly. A NOTE, not a finding: no status flip (the honest probe has 0 violations and
        the movement loosens the bound), and a caller who supplies `transform` supplies `bound` too, so
        it grants them nothing they lack. The effective protection is consumption-side normalisation."""
        class Big(float):
            def __abs__(self):
                return 1e36
        base = rb.shift_translate(1000.0)

        def lying_rows(fx, rng):
            shifted = base.transform(fx, rng)
            return shifted.seed, tuple((Big(r[0]),) + r[1:] for r in shifted.pred), shifted.target, shifted.mask

        def duck(fx, rng):
            seed, pred, target, mask = lying_rows(fx, rng)
            return SimpleNamespace(seed=seed, pred=pred, target=target, mask=mask)

        def real(fx, rng):
            return rb.MeasureFixture(*lying_rows(fx, rng))
        honest = rb.probe_shift(rb.mse_fsum, base, SEEDS, CFG)
        ducked = rb.probe_shift(rb.mse_fsum, dataclasses.replace(base, transform=duck), SEEDS, CFG)
        fixed = rb.probe_shift(rb.mse_fsum, dataclasses.replace(base, transform=real), SEEDS, CFG)
        self.assertIs(honest.status, PS.SENSITIVITY_WITHIN_BOUND)
        self.assertIs(ducked.status, PS.SENSITIVITY_WITHIN_BOUND)    # no status flip: hence a note
        self.assertAlmostEqual(honest.details["max_dev_over_bound"], 4.0336744e-02, places=8)
        self.assertLess(ducked.details["max_dev_over_bound"], 1e-30)  # the bound moved by ~1e33
        self.assertEqual(fixed.details["max_dev_over_bound"],         # ... and a real fixture collapses it
                         honest.details["max_dev_over_bound"])
        self.assertEqual(fixed.content_hash(), honest.content_hash())
        why = rb.ShiftSpec._NORMALISE_EXEMPT["transform"]
        self.assertIn("probe_shift NEVER type-checks this return", why)
        self.assertIn("4.042e-35", why)
        self.assertIn("grants them nothing they", why)
        self.assertEqual(rb._PARAMETER_NO_SCALAR["probe_shift"]["fixture_factory"],
                         rb._WHY_CALLABLE_FIXTURE)
        self.assertIn("does NOT type-check this return", rb._WHY_CALLABLE_FIXTURE)


def _impure_rb(v, path):
    return ts._impure(v, path)


if __name__ == "__main__":
    unittest.main()
