"""SR-10 tests for toy.benchmark: tests of the MEASURING INSTRUMENT on synthetic fixtures.

TOY ONLY. Every number produced here is a property of the scorer on a fixture whose answer is known by
construction (oracle / degrader / identity) or of hand-computed statistics. None is a result about the toy
method, and none says anything about RFdiffusion or any real model. The protocol's actual experiment (the
erasure arm E scored as a study) is deliberately NOT run here."""
import dataclasses
import itertools
import math
import random
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from toy import benchmark as bm
from toy.schema import EvidenceClass, ExperimentRecord, derive_seed, make_rng

V, J = bm.Verdict, bm.JointVerdict
SMALL = bm.BenchmarkConfig(n_boot=2000)          # smaller B only to keep the suite fast; the default is 10,000
FZ = bm.freeze_seed_list(7, 30)
_ORACLE = {}


def study(factory, name, base=7, cfg=SMALL, digest="auto", n=30):
    fz = FZ if (base, n) == (7, 30) else bm.freeze_seed_list(base, n)
    return bm.run_study(fz, factory, subject=name, registered_digest=fz.digest if digest == "auto" else digest, cfg=cfg)


def oracle():
    if "r" not in _ORACLE:
        _ORACLE["r"] = study(bm.fixture_oracle_gated, "oracle_gated")
    return _ORACLE["r"]


def synth_scores(seeds, S=1.0, L=-0.01, d=1.0, dms=1.0, noise=0.05, rng_seed=1):
    r = random.Random(rng_seed)
    return [bm.SeedScores.from_values(s, S + r.gauss(0, noise), L + r.gauss(0, noise * 0.1), d + r.gauss(0, noise),
                                      dms + r.gauss(0, noise), rowsets_disjoint=True, mask_ok=True) for s in seeds]


class HandComputedStatistics(unittest.TestCase):
    def test_t_quantiles_closed_form(self):
        # df=1 (Cauchy): t = tan(pi*(p-1/2)); p=0.975 -> tan(0.475*pi) = 12.7062047...
        self.assertAlmostEqual(bm.t_ppf(0.975, 1), math.tan(math.pi * 0.475), places=8)
        # df=2: t = (2p-1)/sqrt(2p(1-p)); p=0.975 -> 0.95/sqrt(0.04875) = 0.95/0.2207940 = 4.302653
        self.assertAlmostEqual(bm.t_ppf(0.975, 2), 0.95 / math.sqrt(2 * 0.975 * 0.025), places=8)
        self.assertAlmostEqual(bm.t_ppf(0.975, 2), 4.30265273, places=6)
        # textbook t-table values (3 d.p.): df=4 2.776, df=9 2.262, df=29 2.045
        for df, ref in ((4, 2.776), (9, 2.262), (29, 2.045)):
            self.assertAlmostEqual(bm.t_ppf(0.975, df), ref, places=3)
        self.assertAlmostEqual(bm.t_ppf(0.975, 100000), 1.95996, places=3)   # -> normal quantile
        self.assertAlmostEqual(bm.t_ppf(0.025, 4), -bm.t_ppf(0.975, 4), places=12)
        self.assertEqual(bm.t_ppf(0.5, 7), 0.0)

    def test_t_cdf_roundtrip_and_df1(self):
        self.assertAlmostEqual(bm.t_cdf(1.0, 1), 0.75, places=10)       # Cauchy: 1/2 + atan(1)/pi
        self.assertAlmostEqual(bm.t_cdf(0.0, 5), 0.5, places=12)
        for df in (1, 3, 29):
            self.assertAlmostEqual(bm.t_cdf(bm.t_ppf(0.99167, df), df), 0.99167, places=9)

    def test_t_interval_hand_fixture(self):
        # x = [1,2,3,4,5]: mean 3; squared deviations 4+1+0+1+4 = 10; sd = sqrt(10/4) = 1.5811388;
        # se = sd/sqrt(5) = 0.7071068; t(.975, df 4) = 2.7764451; half-width = 2.7764451*0.7071068 = 1.963243
        # interval = [1.036757, 4.963243]
        lo, hi = bm.t_interval([1, 2, 3, 4, 5], 0.95)
        self.assertAlmostEqual(bm.sample_sd([1, 2, 3, 4, 5]), 1.5811388, places=6)
        self.assertAlmostEqual(lo, 1.036757, places=5)
        self.assertAlmostEqual(hi, 4.963243, places=5)
        self.assertAlmostEqual(lo + hi, 6.0, places=12)

    def test_quantile_type7_hand(self):
        # sorted [10,20,30,40]: p=.5 -> pos 1.5 -> 25; p=.25 -> pos .75 -> 17.5; p=1 -> 40; p=0 -> 10
        s = [10, 20, 30, 40]
        self.assertEqual((bm.quantile(s, .5), bm.quantile(s, .25), bm.quantile(s, 1), bm.quantile(s, 0)),
                         (25, 17.5, 40, 10))

    def test_percentile_interval_hand(self):
        # resample statistics 0..100 (B=101): 95% -> positions 0.025*100=2.5 and 97.5 -> 2.5, 97.5
        lo, hi = bm.percentile_interval(list(range(101)), 0.95)
        self.assertAlmostEqual(lo, 2.5, places=12)
        self.assertAlmostEqual(hi, 97.5, places=12)
        # order must not matter
        lo2, hi2 = bm.percentile_interval(list(reversed(range(101))), 0.95)
        self.assertEqual((lo, hi), (lo2, hi2))

    def test_bootstrap_resample_distribution_hand(self):
        # values [1,2,3]: 27 equally likely resamples; sums 3..9 have counts 1,3,6,7,6,3,1.
        # mean of resample means = 2; variance = pop-var/n = (2/3)/3 = 2/9 = 0.2222; P(all ones)=1/27=0.0370.
        m = bm.bootstrap_means([1.0, 2.0, 3.0], 20000, make_rng(5))
        mu = sum(m) / len(m)
        var = sum((x - mu) ** 2 for x in m) / len(m)
        self.assertAlmostEqual(mu, 2.0, delta=0.012)          # ~5 sigma of sampling noise
        self.assertAlmostEqual(var, 2 / 9, delta=0.012)
        self.assertAlmostEqual(sum(x == 1.0 for x in m) / len(m), 1 / 27, delta=0.007)
        self.assertTrue(all(1.0 <= x <= 3.0 for x in m))

    def test_bonferroni(self):
        self.assertAlmostEqual(bm.bonferroni_level(0.05, 3), 1 - 0.05 / 3, places=15)
        self.assertAlmostEqual(bm.bonferroni_level(0.05, 3), 0.98333333, places=7)
        self.assertEqual(bm.bonferroni_level(0.05, 1), 0.95)
        with self.assertRaises(ValueError):
            bm.bonferroni_level(0.05, 0)

    def test_primary_level_used(self):
        h = oracle().h1.components[0].pair
        self.assertAlmostEqual(h.level, 0.98333333, places=7)


class KnownAnswer(unittest.TestCase):
    def test_constant_sample_zero_width(self):
        p = bm.summarize("c", [0.75] * 30, 0.95, 500, 1)
        self.assertEqual(p.boot(), (0.75, 0.75))
        self.assertEqual(p.tint(), (0.75, 0.75))
        self.assertIn("degenerate: all values tied", p.flags)

    def test_symmetric_sample_symmetric_interval(self):
        vals = [float(i) for i in range(-20, 21)]            # symmetric about 0
        lo, hi = bm.t_interval(vals, 0.95)
        self.assertAlmostEqual(lo, -hi, places=12)           # exact for the t-interval
        bl, bh = bm.bootstrap_ci(vals, 0.95, 10000, make_rng(3))
        self.assertLess(abs(bl + bh), 0.1 * (bh - bl))       # approximate for the bootstrap

    def test_width_shrinks_like_inverse_sqrt_n(self):
        rng = random.Random(11)
        pool = [rng.gauss(0, 1) for _ in range(480)]
        w = {}
        for n in (30, 120, 480):
            p = bm.summarize("w", pool[:n], 0.95, 2000, 2)
            w[n] = (p.boot_hi.value - p.boot_lo.value, p.t_hi.value - p.t_lo.value)
        for k in (0, 1):
            self.assertTrue(1.6 < w[30][k] / w[120][k] < 2.5)     # ideal 2
            self.assertTrue(1.6 < w[120][k] / w[480][k] < 2.5)
            self.assertTrue(3.3 < w[30][k] / w[480][k] < 4.8)     # ideal 4

    def test_input_validation(self):
        with self.assertRaises(ValueError):
            bm.summarize("x", [1.0, float("nan")], 0.95, 10, 1)
        with self.assertRaises(ValueError):
            bm.t_interval([1.0], 0.95)
        with self.assertRaises(ValueError):
            bm.bootstrap_means([], 10, make_rng(1))


class Determinism(unittest.TestCase):
    def test_same_seed_identical_bit_for_bit(self):
        vals = [random.Random(4).gauss(0.3, 1) for _ in range(40)]
        a, b = bm.summarize("m", vals, 0.98, 1000, 9), bm.summarize("m", vals, 0.98, 1000, 9)
        self.assertEqual(a, b)

    def test_different_seed_different_resamples(self):
        vals = [random.Random(i).gauss(0.3, 1) for i in range(40)]
        a, b = bm.summarize("m", vals, 0.98, 1000, 9), bm.summarize("m", vals, 0.98, 1000, 10)
        self.assertNotEqual(a.boot(), b.boot())
        self.assertEqual(a.tint(), b.tint())                 # t-interval has no randomness

    def test_name_changes_stream(self):
        vals = [random.Random(i).gauss(0, 1) for i in range(40)]
        self.assertNotEqual(bm.summarize("a", vals, 0.95, 500, 1).boot(), bm.summarize("b", vals, 0.95, 500, 1).boot())

    def test_study_repeatable_and_record_hash_stable(self):
        a, b = oracle(), study(bm.fixture_oracle_gated, "oracle_gated")
        self.assertEqual(a.verdict, b.verdict)
        ts = "2025-01-02T03:04:05Z"
        ra = bm.to_experiment_records(a, study_id="t", base_seed=7, timestamp_utc=ts, scorer_validation=True)
        rb = bm.to_experiment_records(b, study_id="t", base_seed=7, timestamp_utc=ts, scorer_validation=True)
        self.assertEqual([r.content_hash() for r in ra], [r.content_hash() for r in rb])

    def test_arms_reproducible_from_seed_alone(self):
        s = FZ.seeds[0]
        before = {a: bm._arm_params(s, a, SMALL) for a in bm.ARM_NAMES}
        bm._arm_params.cache_clear()
        bm.build_fixture.cache_clear()
        self.assertEqual(before, {a: bm._arm_params(s, a, SMALL) for a in bm.ARM_NAMES})

    def test_global_rng_untouched(self):
        random.seed(123)
        st = random.getstate()
        bm.summarize("g", [1.0, 2.0, 3.0, 4.0], 0.95, 200, 1)
        bm.score_seed(FZ.seeds[1], bm.fixture_oracle_gated, SMALL)
        self.assertEqual(random.getstate(), st)

    def test_clear_cut_verdict_stable_across_seed_lists(self):
        self.assertEqual(study(bm.fixture_oracle_gated, "o", base=99).verdict, J.JOINT_SUPPORTED)
        self.assertEqual(oracle().verdict, J.JOINT_SUPPORTED)


class Arms(unittest.TestCase):
    def setUp(self):
        self.s = FZ.seeds[2]
        self.fx = bm.build_fixture(self.s, SMALL)

    def test_arms_distinct_and_defined(self):
        p = {a: bm._arm_params(self.s, a, SMALL) for a in bm.ARM_NAMES}
        self.assertEqual(len(set(p.values())), len(p))       # each arm changes exactly one factor => all differ
        with self.assertRaises(ValueError):
            bm._arm_params(self.s, "bogus", SMALL)

    def test_c_init_is_untrained_and_c0_trains(self):
        init = bm.train(self.s, steps=0, x=self.fx.train_x, teacher=self.fx.teacher, timestamp_utc=bm.PINNED_TS)
        self.assertEqual(bm._arm_params(self.s, "C_init", SMALL), init.final_params)
        self.assertNotEqual(bm._arm_params(self.s, "C0", SMALL), init.final_params)   # eta=0 still trains

    def test_c0_contrast_against_itself_is_exactly_zero(self):
        c0 = bm.ARM_FACTORIES["C0"](self.fx, SMALL)
        sc = bm.score_predictor(self.fx, c0, c0)
        for k in ("S", "L", "S_U", "delta"):
            self.assertEqual(getattr(sc, k).value, 0.0)

    def test_fixture_rowsets(self):
        self.assertTrue(self.fx.disjoint and self.fx.mask_ok and self.fx.G > 0)
        self.assertGreaterEqual(sum(self.fx.train_mask), 2)

    def test_config_validation(self):
        with self.assertRaises(ValueError):
            bm.BenchmarkConfig(n_train=8)
        with self.assertRaises(ValueError):
            bm.BenchmarkConfig(lr=0.0)


class ScorerValidationFixtures(unittest.TestCase):
    """Properties of the scorer on fixtures whose answers are known by construction."""

    def test_oracle_gated_must_score_as_suppressing(self):
        r = oracle()
        self.assertEqual((r.h1.verdict, r.h2.verdict, r.h3.verdict), (V.SUPPORTED,) * 3)
        self.assertEqual(r.verdict, J.JOINT_SUPPORTED)
        self.assertTrue(r.gates_ok)

    def test_global_degrader_must_fail_retention(self):
        r = study(bm.fixture_global_degrader(0.5), "global_degrader")
        self.assertEqual(r.h1.verdict, V.SUPPORTED)            # its suppression number "looks good"
        self.assertEqual(r.h2.verdict, V.UNSUPPORTED)          # but retention fails
        self.assertEqual(r.verdict, J.JOINT_UNSUPPORTED)       # the scorer CAN return UNSUPPORTED

    def test_identity_shows_no_suppression_beyond_c0(self):
        r = study(bm.fixture_identity_uncond, "identity_uncond")
        self.assertNotEqual(r.h1.verdict, V.SUPPORTED)
        self.assertEqual(r.h1.verdict, V.UNSUPPORTED)
        self.assertNotEqual(r.verdict, J.JOINT_SUPPORTED)
        self.assertLess(abs(r.h1.components[0].pair.mean.value), bm.Margins().delta_S)

    def test_scorer_not_always_yes_and_not_always_no(self):
        verdicts = {oracle().verdict,
                    study(bm.fixture_global_degrader(0.5), "d").verdict,
                    study(bm.fixture_identity_uncond, "i").verdict}
        self.assertIn(J.JOINT_SUPPORTED, verdicts)
        self.assertIn(J.JOINT_UNSUPPORTED, verdicts)

    def test_degrader_magnitude_validated(self):
        with self.assertRaises(ValueError):
            bm.fixture_global_degrader(0.0)


class JointRule(unittest.TestCase):
    def test_table_all_combinations(self):
        for h1, h2, h3 in itertools.product(V, repeat=3):
            if V.UNSUPPORTED in (h1, h2, h3):
                want = J.JOINT_UNSUPPORTED
            elif (h1, h2, h3) == (V.SUPPORTED,) * 3:
                want = J.JOINT_SUPPORTED
            else:
                want = J.JOINT_INCONCLUSIVE
            self.assertEqual(bm.combine_joint(h1, h2, h3, True), want, (h1, h2, h3))
            self.assertEqual(bm.combine_joint(h1, h2, h3, False), J.JOINT_INCONCLUSIVE, (h1, h2, h3))

    def test_explicit_rows(self):
        S, U, I = V.SUPPORTED, V.UNSUPPORTED, V.INCONCLUSIVE
        self.assertEqual(bm.combine_joint(S, S, I, True), J.JOINT_INCONCLUSIVE)
        self.assertEqual(bm.combine_joint(S, U, S, True), J.JOINT_UNSUPPORTED)   # suppression alone is not enough
        self.assertEqual(bm.combine_joint(I, U, I, True), J.JOINT_UNSUPPORTED)

    def test_no_standalone_suppression_getter(self):
        r = oracle()
        self.assertFalse(hasattr(r, "suppression_verdict"))
        self.assertFalse(hasattr(bm, "suppression_verdict"))
        self.assertFalse(hasattr(r.h1, "joint"))
        with self.assertRaises(dataclasses.FrozenInstanceError):
            r.h1 = r.h2
        with self.assertRaises(ValueError):                    # slots are typed: H2 cannot sit in the H1 slot
            dataclasses.replace(r, h1=r.h2)
        with self.assertRaises(AttributeError):
            r.verdict = J.JOINT_SUPPORTED                      # derived property, not settable


class ValidityGates(unittest.TestCase):
    def run_synth(self, scores, registered="auto", frozen=FZ, **kw):
        return bm.analyze_scores(scores, frozen=frozen, registered_digest=frozen.digest if registered == "auto"
                                 else registered, subject="synthetic", cfg=SMALL, **kw)

    def test_baseline_synthetic_is_supported(self):
        r = self.run_synth(synth_scores(FZ.seeds))
        self.assertEqual(r.verdict, J.JOINT_SUPPORTED)

    def test_fewer_than_30_seeds(self):
        r = self.run_synth(synth_scores(FZ.seeds[:29]))
        self.assertEqual(r.verdict, J.JOINT_INCONCLUSIVE)
        self.assertEqual(r.h1.verdict, V.INCONCLUSIVE)
        self.assertFalse(next(g for g in r.gates if g.name == "min_seeds").passed)
        self.assertIn("n below protocol minimum", r.h1.components[0].pair.flags)
        self.assertTrue(any("min_seeds" in x for x in r.h1.reasons))

    def test_failure_rate_over_5_percent(self):
        fz = bm.freeze_seed_list(7, 32)
        sc = synth_scores(fz.seeds[:30]) + [bm.SeedScores.failed(s, "diverged", True, True) for s in fz.seeds[30:32]]
        r = self.run_synth(sc, frozen=fz)                      # 2/32 = 6.25% > 5%
        self.assertEqual(r.verdict, J.JOINT_INCONCLUSIVE)
        self.assertFalse(next(g for g in r.gates if g.name == "failure_rate").passed)
        self.assertEqual(r.n_failed, 2)

    def test_failure_rate_under_threshold_passes(self):
        fz = bm.freeze_seed_list(7, 31)
        sc = synth_scores(fz.seeds[:30]) + [bm.SeedScores.failed(fz.seeds[30], "diverged", True, True)]
        r = self.run_synth(sc, frozen=fz)                      # 1/31 = 3.2%
        self.assertTrue(r.gates_ok)
        self.assertEqual(r.n_failed, 1)

    def test_failures_are_unmeasured_not_zero(self):
        f = bm.SeedScores.failed(1, "diverged")
        self.assertFalse(f.ok)
        self.assertTrue(all(not m.is_measured for m in f.metrics.values()))

    def test_unfrozen_seed_list(self):
        sc = synth_scores(FZ.seeds)
        for reg in (None, "0" * 64):
            r = self.run_synth(sc, registered=reg)
            self.assertEqual(r.verdict, J.JOINT_INCONCLUSIVE)
            self.assertFalse(next(g for g in r.gates if g.name == "seed_list_frozen").passed)

    def test_seed_outside_frozen_list(self):
        sc = synth_scores(FZ.seeds[:29]) + synth_scores([12345])
        r = self.run_synth(sc)
        self.assertFalse(next(g for g in r.gates if g.name == "seed_list_frozen").passed)

    def test_unverified_disjointness_or_mask_fails_gate(self):
        sc = [bm.SeedScores.from_values(s, 1, -0.01, 1, 1) for s in FZ.seeds]    # flags default None
        r = self.run_synth(sc)
        self.assertEqual(r.verdict, J.JOINT_INCONCLUSIVE)
        failed = {g.name for g in r.gates if not g.passed}
        self.assertEqual(failed, {"rowsets_disjoint", "mask_correct"})

    def test_gate_failure_overrides_unsupported(self):
        sc = synth_scores(FZ.seeds, L=1.0)                     # retention clearly bad
        self.assertEqual(self.run_synth(sc).verdict, J.JOINT_UNSUPPORTED)
        self.assertEqual(self.run_synth(sc, registered=None).verdict, J.JOINT_INCONCLUSIVE)

    def test_deferred_gates_disclosed(self):
        r = oracle()
        self.assertFalse(r.complete_gate_coverage)
        self.assertTrue(r.deferred_gates)

    def test_ineligible_seeds_listed_and_replaced(self):
        fz = bm.freeze_seed_list(7, 3, n_reserve=2)
        cfg = dataclasses.replace(SMALL, g_min=min(bm.build_fixture(s, SMALL).G for s in fz.seeds[:2]) + 1e-12)
        r = bm.run_study(fz, bm.fixture_identity_uncond, subject="x", registered_digest=fz.digest, cfg=cfg)
        self.assertEqual(r.n_attempted, 3)
        self.assertTrue(all(bm.build_fixture(s, cfg).G < cfg.g_min for s in r.ineligible))
        self.assertTrue(len(r.ineligible) >= 1)


class DisagreementRule(unittest.TestCase):
    def test_pure_side_disagreement(self):
        bad, why = bm.intervals_disagree((0.2, 1.0), (-0.1, 1.0), 0.1)
        self.assertTrue(bad)
        self.assertIn("lower", why)
        self.assertTrue(bm.intervals_disagree((0.2, 1.0), (0.2, 0.05), 0.1)[0])    # upper side differs
        self.assertFalse(bm.intervals_disagree((0.2, 1.0), (0.25, 1.05), 0.1)[0])

    def test_pure_width_disagreement(self):
        self.assertTrue(bm.intervals_disagree((1.0, 2.0), (0.75, 2.25), 0.0)[0])    # widths 1.0 vs 1.5
        self.assertFalse(bm.intervals_disagree((1.0, 2.0), (0.95, 2.05), 0.0)[0])   # widths 1.0 vs 1.1
        self.assertFalse(bm.intervals_disagree((1.0, 1.0), (1.0, 1.0), 0.0)[0])     # both zero width

    def test_constructed_skewed_case_flips_verdict_to_inconclusive(self):
        # 29 zeros and one 10 (n=30): mean 1/3. The bootstrap lower bound is exactly 0 (P(no 10 drawn)=0.36 >
        # tail) whereas the t lower bound is below 0 (sd 1.83, se 0.334, t~2.54), so for margin -0.2 the two
        # lower bounds fall on different sides.
        vals = [0.0] * 29 + [10.0]
        level = bm.bonferroni_level()
        pair = bm.summarize("skew", vals, level, 10000, 1)
        self.assertEqual(pair.boot_lo.value, 0.0)
        self.assertLess(pair.t_lo.value, -0.2)
        v, why = bm.interval_verdict(pair, -0.2, "greater")
        self.assertEqual(v, V.INCONCLUSIVE)
        self.assertIn("disagreement", why)
        # control: with agreement-compatible tolerances and a margin both lower bounds clear, it is SUPPORTED.
        self.assertEqual(bm.interval_verdict(pair, -2.0, "greater", width_tol=10.0)[0], V.SUPPORTED)


class VerdictRules(unittest.TestCase):
    def pair(self, lo, hi, tlo=None, thi=None):
        z = bm._mv
        mid = (lo + hi) / 2
        return bm.IntervalPair("p", 40, 0.98, 100, z(mid, ""), z(0.1, ""), z(0.1, ""), z(lo, ""), z(hi, ""),
                               z(1.0, ""), z(lo, ""), z(hi, ""), z(lo if tlo is None else tlo, ""),
                               z(hi if thi is None else thi, ""))

    def test_greater(self):
        self.assertEqual(bm.interval_verdict(self.pair(0.2, 0.4), 0.1, "greater")[0], V.SUPPORTED)
        self.assertEqual(bm.interval_verdict(self.pair(-0.1, 0.1), 0.1, "greater")[0], V.UNSUPPORTED)  # upper == margin
        self.assertEqual(bm.interval_verdict(self.pair(0.0, 0.3), 0.1, "greater")[0], V.INCONCLUSIVE)

    def test_less(self):
        self.assertEqual(bm.interval_verdict(self.pair(-0.1, 0.0), 0.05, "less")[0], V.SUPPORTED)
        self.assertEqual(bm.interval_verdict(self.pair(0.05, 0.2), 0.05, "less")[0], V.UNSUPPORTED)  # lower == margin
        self.assertEqual(bm.interval_verdict(self.pair(0.0, 0.2), 0.05, "less")[0], V.INCONCLUSIVE)

    def test_bad_direction(self):
        with self.assertRaises(ValueError):
            bm.interval_verdict(self.pair(0, 1), 0.5, "sideways")


class UnmeasuredAndMultiplicity(unittest.TestCase):
    def test_unmeasured_is_not_zero(self):
        u = bm.SeedScores.failed(1, "diverged").metrics["S"]
        self.assertIsNone(u.value)
        self.assertEqual(u.render(), "UNKNOWN")
        self.assertNotEqual(u.render(), repr(0.0))
        self.assertNotEqual(u, bm.MetricValue.measured(0.0))

    def test_uncomputable_stats_are_unmeasured(self):
        e = bm.summarize("e", [], 0.95, 10, 1)
        self.assertEqual(e.mean.render(), "UNKNOWN")
        one = bm.summarize("one", [2.0], 0.95, 10, 1)
        self.assertEqual(one.mean.value, 2.0)
        for m in (one.sd, one.iqr, one.boot_lo, one.t_hi):
            self.assertIsNone(m.value)
        self.assertEqual(bm.interval_verdict(one, 0.0, "greater")[0], V.INCONCLUSIVE)
        z = bm.summarize("zero-median", [0.0, 0.0, 1.0], 0.95, 10, 1)
        self.assertEqual(z.max_over_median_abs.render(), "UNKNOWN")

    def test_zero_g_or_failed_prediction_unmeasured(self):
        fx = dataclasses.replace(bm.build_fixture(FZ.seeds[0], SMALL), G=0.0)
        c0 = bm.ARM_FACTORIES["C0"](fx, SMALL)
        sc = bm.score_predictor(fx, c0, c0)
        self.assertTrue(all(not getattr(sc, k).is_measured for k in ("S", "L", "S_U", "delta")))

    def test_records_render_unmeasured_not_zero(self):
        fz = bm.freeze_seed_list(7, 5)
        r = bm.analyze_scores([bm.SeedScores.failed(s, "diverged", True, True) for s in fz.seeds], frozen=fz,
                              registered_digest=fz.digest, subject="s", cfg=SMALL)
        self.assertEqual(r.verdict, J.JOINT_INCONCLUSIVE)
        for rec in bm.to_experiment_records(r, study_id="x", base_seed=7):
            if rec.name.endswith("H1"):
                self.assertFalse(rec.metrics["mean"].is_measured)
                self.assertEqual(rec.metrics["mean"].render(), "UNKNOWN")
                self.assertIs(rec.evidence_class, EvidenceClass.UNKNOWN)
        for rec in bm.seed_records(r, study_id="x"):
            self.assertEqual(rec.metrics["S"].render(), "UNKNOWN")

    def test_exploratory_cannot_yield_verdict(self):
        cfg = SMALL
        ex = bm.exploratory_interval("H4", [0.5 + 0.01 * i for i in range(40)], cfg, 1)
        self.assertIn("EXPLORATORY", ex.label)
        self.assertFalse(hasattr(ex, "verdict"))
        self.assertAlmostEqual(ex.pair.level, 0.95)                    # unadjusted
        with self.assertRaises(ValueError):
            bm.evaluate_primary("H4", {"S": [1.0] * 40}, bm.Margins(), cfg, 1)
        with self.assertRaises(ValueError):
            bm.exploratory_interval("H1", [1.0] * 40, cfg, 1)          # cannot launder a primary id either
        self.assertEqual(set(bm.PRIMARY), {"H1", "H2", "H3"})
        with self.assertRaises(ValueError):
            bm.JointResult(**{**{f.name: getattr(oracle(), f.name) for f in dataclasses.fields(bm.JointResult)},
                              "h1": oracle().h2})

    def test_records_map_to_toy_result_and_roundtrip(self):
        recs = bm.to_experiment_records(oracle(), study_id="fixture", base_seed=7,
                                        timestamp_utc="2025-01-02T03:04:05Z", scorer_validation=True)
        self.assertEqual(len(recs), 5)       # H1, H2, H3a, H3b, JOINT
        for rec in recs:
            self.assertIs(rec.evidence_class, EvidenceClass.TOY_RESULT)
            self.assertIn("TOY RESULT", rec.notes)
            self.assertIn("SCORER-VALIDATION FIXTURE", rec.notes)
            self.assertEqual(ExperimentRecord.from_json(rec.to_json()), rec)
        agg = next(r for r in recs if r.name.endswith("agg/H1"))
        for k in ("mean", "sd", "iqr", "ci_boot_lo", "ci_boot_hi", "ci_t_lo", "ci_t_hi", "n_seeds", "n_failed",
                  "ci_level", "margin"):
            self.assertIn(k, agg.metrics)
        self.assertEqual(len(bm.seed_records(oracle(), study_id="fixture", timestamp_utc="2025-01-02T03:04:05Z")), 30)

    def test_source_observed_is_rejected_by_schema(self):
        rec = bm.to_experiment_records(oracle(), study_id="f", base_seed=7)[0]
        with self.assertRaises(ValueError):
            dataclasses.replace(rec, evidence_class=EvidenceClass.SOURCE_OBSERVED)


if __name__ == "__main__":
    unittest.main()
