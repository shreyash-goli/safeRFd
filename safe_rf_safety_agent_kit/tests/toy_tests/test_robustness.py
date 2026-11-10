"""SR-11 tests for toy.robustness: tests of MEASUREMENT-PROCEDURE PROBES on synthetic fixtures.

TOY ONLY. Nothing here runs the experiment of docs/EVALUATION_PROTOCOL.md, produces a finding, or says
anything about RFdiffusion or any real model. Every number is a property of a measure or of the probe
machinery on a synthetic fixture. A probe that cannot fail is worthless, so each failure path is exercised
with a deliberately broken measure and asserted to fire."""
import dataclasses
import json
import math
import random
import struct
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from toy import robustness as rb
from toy import stability
from toy.benchmark import fixture_oracle_gated
from toy.robustness import ProbeStatus as PS
from toy.robustness import ShiftKind as SK
from toy.schema import (TOY_LABEL, EvidenceClass, ExperimentRecord, MetricValue, canonical_json, derive_seed)

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
        self.assertEqual(d["schema_version"], "1")
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


if __name__ == "__main__":
    unittest.main()
