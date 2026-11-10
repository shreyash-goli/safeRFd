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
from unittest import mock

from toy.schema import EvidenceClass, ExperimentRecord, MetricValue, derive_seed, make_rng

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


def synth_scores(seeds, S=1.0, L=-0.01, d=1.0, dms=1.0, noise=0.05, rng_seed=1, A=0.5, F=0.005, loss=0.01,
                 dc=1.0, dmsc=1.0, gr=1e-5, flags=True):
    """Synthetic per-seed values (no training). Defaults describe a clear-cut favourable pattern; they are
    inputs to test the scorer's logic, not measurements."""
    r = random.Random(rng_seed)
    g = lambda m, sd=noise: m + r.gauss(0, sd)
    return [bm.SeedScores.from_values(s, g(S), g(L, noise * 0.1), g(d), g(dms), A=g(A, 0.01), F=F, E_loss_ratio=loss,
                                      delta_conv=g(dc), delta_minus_shuf_conv=g(dmsc), conv_grad_ratio=gr,
                                      rowsets_disjoint=True if flags else None, mask_ok=True if flags else None)
            for s in seeds]


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
        self.assertAlmostEqual(mu, 2.0, delta=0.012)          # 3.6 sigma of the mean's sampling noise (se = sqrt(2/9/20000) = 0.0033)
        self.assertAlmostEqual(var, 2 / 9, delta=0.012)          # ~5 sigma for the variance
        self.assertAlmostEqual(sum(x == 1.0 for x in m) / len(m), 1 / 27, delta=0.007)   # se 0.0013: ~5 sigma
        self.assertTrue(all(1.0 <= x <= 3.0 for x in m))

    def test_bonferroni(self):
        # m=3 would give 1 - 0.05/3 = 0.98333; the family is FOUR intervals, so 1 - 0.05/4 = 0.9875
        self.assertEqual(bm.N_PRIMARY, 4)
        self.assertAlmostEqual(bm.bonferroni_level(0.05), 0.9875, places=15)
        self.assertAlmostEqual(bm.bonferroni_level(0.05, 3), 0.98333333, places=7)   # generic formula still right
        self.assertEqual(bm.bonferroni_level(0.05, 1), 0.95)
        # family-wise error with m=4 intervals each at 0.0125 miscoverage: <= 4*0.0125 = 0.05 (3-level: 0.0667)
        self.assertLessEqual(4 * (1 - bm.bonferroni_level()), 0.05 + 1e-15)
        self.assertGreater(4 * (1 - bm.bonferroni_level(0.05, 3)), 0.05)
        # N_PRIMARY must equal the number of primary intervals actually produced
        self.assertEqual(bm.N_PRIMARY, sum(len(v) for v in bm.PRIMARY.values()))
        with self.assertRaises(ValueError):
            bm.bonferroni_level(0.05, 0)

    def test_primary_level_used(self):
        h = oracle().h1.components[0].pair
        self.assertAlmostEqual(h.level, 0.9875, places=12)
        for hyp in (oracle().h1, oracle().h2, oracle().h3):
            for c in hyp.components + hyp.converged_components:
                self.assertAlmostEqual(c.pair.level, 0.9875, places=12)


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
        bm._arm_fit.cache_clear()
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
        sc = synth_scores(FZ.seeds, flags=False)                                  # flags None = not measured
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
        for must in ("gate1_config_shift_sensitivity_arm", "gate2_error_register_crosscheck", "V_set_probes",
                     "pilot_execution_and_n_cap_width_rule", "amendment_log_hash"):
            self.assertIn(must, r.deferred_gates)
        with self.assertRaises(AttributeError):
            r.complete_gate_coverage = True
        with self.assertRaises(TypeError):                      # not an init argument any more
            dataclasses.replace(r, complete_gate_coverage=True)

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
        # tail) whereas the t lower bound is below 0 (sd 1.83, se 0.334, t(df 29) at the 98.75% level ~2.6), so for margin -0.2 the two
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
        ex = bm.exploratory_interval("H5", [0.5 + 0.01 * i for i in range(40)], cfg, 1)
        self.assertIn("EXPLORATORY", ex.label)
        self.assertFalse(hasattr(ex, "verdict"))
        self.assertAlmostEqual(ex.pair.level, 0.95)                    # unadjusted
        with self.assertRaises(ValueError):
            bm.evaluate_primary("H5", {"S": [1.0] * 40}, bm.Margins(), cfg, 1)
        with self.assertRaises(ValueError):
            bm.exploratory_interval("H1", [1.0] * 40, cfg, 1)          # cannot launder a primary id either
        self.assertEqual(set(bm.PRIMARY), {"H1", "H2", "H3"})
        with self.assertRaises(ValueError):
            bm.JointResult(**{**{f.name: getattr(oracle(), f.name) for f in dataclasses.fields(bm.JointResult)},
                              "h1": oracle().h2})

    def test_records_map_to_toy_result_and_roundtrip(self):
        recs = bm.to_experiment_records(oracle(), study_id="fixture", base_seed=7,
                                        timestamp_utc="2025-01-02T03:04:05Z", scorer_validation=True)
        self.assertEqual(len(recs), 7)       # H1, H2, H3a, H3b, H3a_conv, H3b_conv, JOINT
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


# ===================================================== QA round 1: defects 1-5 and surviving mutants
class MinimumSeedsAtVerdictLevel(unittest.TestCase):
    """Defect 2: n < 30 gives no verdict wherever a verdict is produced, not only at the gate."""

    def clear_pair(self, n):
        return bm.summarize("p", [1.0 + 0.01 * (i % 5) for i in range(n)], 0.9875, 500, 1, min_n=30)

    def test_interval_verdict_refuses_small_n(self):
        v20, why = bm.interval_verdict(self.clear_pair(20), 0.1, "greater")
        self.assertEqual(v20, V.INCONCLUSIVE)
        self.assertIn("below protocol minimum", why)
        self.assertEqual(bm.interval_verdict(self.clear_pair(30), 0.1, "greater")[0], V.SUPPORTED)   # control
        self.assertEqual(bm.interval_verdict(self.clear_pair(29), 0.1, "greater")[0], V.INCONCLUSIVE)

    def test_evaluate_primary_with_20_seeds_yields_no_verdict_and_no_joint_support(self):
        r = random.Random(3)
        series = {"S": [1 + r.gauss(0, .05) for _ in range(20)], "L": [-.01 + r.gauss(0, .005) for _ in range(20)],
                  "delta": [1 + r.gauss(0, .05) for _ in range(20)],
                  "delta_minus_shuf": [1 + r.gauss(0, .05) for _ in range(20)],
                  "delta_conv": [1.0] * 20, "delta_minus_shuf_conv": [1.0] * 20}
        hs = [bm.evaluate_primary(h, series, bm.Margins(), SMALL, 1) for h in ("H1", "H2", "H3")]
        self.assertEqual([h.verdict for h in hs], [V.INCONCLUSIVE] * 3)
        self.assertNotEqual(bm.combine_joint(*[h.verdict for h in hs], gates_ok=True), J.JOINT_SUPPORTED)

    def test_min_seeds_parameter_is_the_cfg_value(self):
        cfg10 = dataclasses.replace(SMALL, min_seeds=10)
        series = {"S": [1.0 + .01 * i for i in range(12)]}
        self.assertEqual(bm.evaluate_primary("H1", series, bm.Margins(), cfg10, 1).verdict, V.SUPPORTED)
        self.assertEqual(bm.evaluate_primary("H1", series, bm.Margins(), SMALL, 1).verdict, V.INCONCLUSIVE)


class ComponentConjunctionAndBoundaries(unittest.TestCase):
    def run_h3(self, **kw):
        sc = synth_scores(FZ.seeds, **kw)
        return bm.analyze_scores(sc, frozen=FZ, registered_digest=FZ.digest, subject="syn", cfg=SMALL)

    def test_h3_conjunction_inconclusive_component_blocks_support(self):
        r = self.run_h3(d=1.0, dms=0.1)                 # H3a clearly above margin; H3b centred ON the margin
        a, b = r.h3.components
        self.assertEqual((a.verdict, b.verdict), (V.SUPPORTED, V.INCONCLUSIVE))
        self.assertEqual(r.h3.verdict, V.INCONCLUSIVE)  # 'any' instead of 'all' would say SUPPORTED
        self.assertEqual(r.verdict, J.JOINT_INCONCLUSIVE)

    def test_h3_one_unsupported_component_makes_h3_unsupported(self):
        r = self.run_h3(d=1.0, dms=-1.0)
        self.assertEqual([c.verdict for c in r.h3.components], [V.SUPPORTED, V.UNSUPPORTED])
        self.assertEqual((r.h3.verdict, r.verdict), (V.UNSUPPORTED, J.JOINT_UNSUPPORTED))

    def test_converged_conjunction(self):
        r = self.run_h3(dc=1.0, dmsc=0.1)               # finite fine; one converged component spans margin
        self.assertEqual([c.verdict for c in r.h3.components], [V.SUPPORTED] * 2)
        self.assertEqual(r.h3.verdict, V.INCONCLUSIVE)

    def pair(self, lo, hi, tlo=None, thi=None):
        z = bm._mv
        return bm.IntervalPair("p", 40, 0.98, 100, z((lo + hi) / 2, ""), z(.1, ""), z(.1, ""), z(lo, ""), z(hi, ""),
                               z(1., ""), z(lo, ""), z(hi, ""), z(lo if tlo is None else tlo, ""),
                               z(hi if thi is None else thi, ""))

    def test_exact_equality_boundaries(self):
        iv = bm.interval_verdict
        # greater: lower == margin is NOT supported; upper == margin IS unsupported
        self.assertEqual(iv(self.pair(0.5, 0.9), 0.5, "greater")[0], V.INCONCLUSIVE)
        self.assertEqual(iv(self.pair(0.25, 0.5), 0.5, "greater")[0], V.UNSUPPORTED)
        self.assertEqual(iv(self.pair(0.25, 0.500001), 0.5, "greater")[0], V.INCONCLUSIVE)
        # less: upper == margin is NOT supported; lower == margin IS unsupported
        self.assertEqual(iv(self.pair(0.0, 0.5), 0.5, "less")[0], V.INCONCLUSIVE)
        self.assertEqual(iv(self.pair(0.5, 0.75), 0.5, "less")[0], V.UNSUPPORTED)
        self.assertEqual(iv(self.pair(0.499999, 0.75), 0.5, "less")[0], V.INCONCLUSIVE)

    def test_each_bound_side_check_is_independently_effective(self):
        # equal-ish widths so the width rule cannot be what fires.
        up = bm.intervals_disagree((0.2, 1.1), (0.2, 0.9), 1.0)       # widths .9 vs .7 (22%): only UPPER sides differ
        self.assertTrue(up[0])
        self.assertIn("upper", up[1])
        lo = bm.intervals_disagree((0.3, 1.2), (0.1, 1.0), 0.2)       # widths .9 vs .9: only LOWER sides differ
        self.assertTrue(lo[0])
        self.assertIn("lower", lo[1])
        self.assertFalse(bm.intervals_disagree((0.3, 1.2), (0.25, 1.15), 0.2)[0])


class FailureRateBoundary(unittest.TestCase):
    def rate(self, n_ok, n_bad):
        fz = bm.freeze_seed_list(7, n_ok + n_bad)
        sc = synth_scores(fz.seeds[:n_ok]) + [bm.SeedScores.failed(s, "x", True, True) for s in fz.seeds[n_ok:]]
        r = bm.analyze_scores(sc, frozen=fz, registered_digest=fz.digest, subject="s", cfg=SMALL)
        return next(g for g in r.gates if g.name == "failure_rate").passed

    def test_exactly_five_percent_passes_just_above_fails(self):
        self.assertTrue(self.rate(38, 2))      # 2/40 = 5.0% exactly: limit is 'more than 5%'
        self.assertFalse(self.rate(37, 3))     # 7.5%
        self.assertTrue(self.rate(57, 3))      # 3/60 = 5.0%
        self.assertFalse(self.rate(56, 4))     # 6.7%


class ScorerInternals(unittest.TestCase):
    def test_metrics_are_g_normalised_dimensionless(self):
        fx = bm.build_fixture(FZ.seeds[3], SMALL)
        self.assertNotAlmostEqual(fx.G, 1.0, delta=0.02)          # otherwise the check below is vacuous
        pred, c0 = bm.fixture_oracle_gated(fx, SMALL), bm.ARM_FACTORIES["C0"](fx, SMALL)
        sc = bm.score_predictor(fx, pred, c0)

        def msq(a, b):   # independent element-mean squared error
            tot = n = 0
            for ra, rb in zip(a, b):
                for x, y in zip(ra, rb):
                    tot += (x - y) ** 2
                    n += 1
            return tot / n
        o = fx.teacher.outputs(fx.T)
        want = (msq(pred(fx.T), o.conditioned) - msq(c0(fx.T), o.conditioned)) / fx.G
        self.assertAlmostEqual(sc.S.value, want, places=12)
        # and G is the teacher-only normaliser on T u U
        both = fx.teacher.outputs(fx.T + fx.U)
        self.assertAlmostEqual(fx.G, msq(both.conditioned, both.unconditioned), places=12)

    def test_degrader_moves_away_from_conditioned_on_T(self):
        deg = bm.fixture_global_degrader(0.5)
        for s in FZ.seeds:
            fx = bm.build_fixture(s, SMALL)
            o = fx.teacher.outputs(fx.T)
            e = lambda p: bm._mse(p(fx.T), o.conditioned)
            self.assertGreater(e(deg(fx, SMALL)), e(bm.fixture_identity_uncond(fx, SMALL)), s)


class ConvergedBudgetAndControlGates(unittest.TestCase):
    """Defect 3: C_conv, gate 11, gate 12 are implemented, and each can fail."""

    def go(self, **kw):
        exempt = kw.pop("exempt", False)
        extra = {"subject_kind": "fixture", "fixture_name": "syn"} if exempt else {}
        return bm.analyze_scores(synth_scores(FZ.seeds, **kw), frozen=FZ, registered_digest=FZ.digest,
                                 subject="syn", cfg=SMALL, **extra)

    def test_baseline_has_both_gates_passing(self):
        r = self.go()
        self.assertEqual(r.verdict, J.JOINT_SUPPORTED)
        self.assertEqual({g.name for g in r.gates}, set(bm.GATE_SCOPES))

    def test_finite_budget_only_h3_cannot_be_supported(self):
        r = self.go(dc=0.0, dmsc=0.0)                  # finite H3a/H3b clearly supported, converged ones not
        self.assertEqual([c.verdict for c in r.h3.components], [V.SUPPORTED] * 2)
        self.assertEqual(r.h3.verdict, V.INCONCLUSIVE)
        self.assertTrue(any("finite-budget only" in x for x in r.h3.reasons))
        self.assertNotEqual(r.verdict, J.JOINT_SUPPORTED)

    def test_converged_evidence_missing_blocks_support(self):
        sc = [bm.SeedScores.from_values(x.seed, x.metrics["S"].value, x.metrics["L"].value, x.metrics["delta"].value,
                                        x.metrics["delta_minus_shuf"].value, A=.5, F=.005, conv_grad_ratio=1e-5,
                                        rowsets_disjoint=True, mask_ok=True) for x in synth_scores(FZ.seeds)]
        r = bm.analyze_scores(sc, frozen=FZ, registered_digest=FZ.digest, subject="s", cfg=SMALL)
        self.assertEqual(r.h3.verdict, V.INCONCLUSIVE)
        self.assertNotEqual(r.verdict, J.JOINT_SUPPORTED)
        self.assertFalse(r.h3.converged_components[0].pair.mean.is_measured)

    def test_gate12_gradient_not_converged(self):
        r = self.go(gr=0.5)
        self.assertFalse(next(g for g in r.gates if g.name == "convergence").passed)
        self.assertEqual(r.h3.verdict, V.INCONCLUSIVE)
        self.assertEqual((r.h1.verdict, r.h2.verdict), (V.SUPPORTED, V.SUPPORTED))   # gate 12 scopes to H3
        self.assertEqual(r.verdict, J.JOINT_INCONCLUSIVE)

    def test_gate12_does_not_hide_unsupported(self):
        r = self.go(gr=0.5, d=-1.0)
        self.assertEqual(r.h3.verdict, V.UNSUPPORTED)

    def test_gate11_control_undertrained(self):
        for kw in ({"A": 0.0}, {"F": 0.5}):
            r = self.go(**kw)
            self.assertFalse(next(g for g in r.gates if g.name == "control_adequacy").passed, kw)
            self.assertEqual((r.h1.verdict, r.h2.verdict, r.h3.verdict), (V.INCONCLUSIVE,) * 3, kw)

    def test_gate11_e_loss_must_fall_for_trained_treatment(self):
        self.assertEqual(self.go(loss=0.1).verdict, J.JOINT_SUPPORTED)
        r = self.go(loss=0.9)
        self.assertEqual((r.h1.verdict, r.h2.verdict, r.h3.verdict), (V.INCONCLUSIVE,) * 3)
        self.assertEqual(r.verdict, J.JOINT_INCONCLUSIVE)

    def test_unmeasured_gate_inputs_fail_not_pass(self):
        sc = [bm.SeedScores.from_values(x.seed, 1, -.01, 1, 1, rowsets_disjoint=True, mask_ok=True)
              for x in synth_scores(FZ.seeds)]
        r = bm.analyze_scores(sc, frozen=FZ, registered_digest=FZ.digest, subject="s", cfg=SMALL)
        self.assertEqual({g.name for g in r.gates if not g.passed}, {"control_adequacy", "convergence"})

    def test_c_conv_arm_is_E_at_converged_budget(self):
        self.assertIn("C_conv", bm.ARM_NAMES)
        s = FZ.seeds[0]
        cc = dataclasses.replace(SMALL, steps=SMALL.steps_conv)
        self.assertEqual(bm._arm_params(s, "C_conv", SMALL), bm._arm_params(s, "E", cc))
        self.assertNotEqual(bm._arm_params(s, "C_conv", SMALL), bm._arm_params(s, "E", SMALL))
        self.assertLessEqual(bm._arm_fit(s, "C_conv", SMALL).grad_ratio, SMALL.tau_conv)

    def test_real_fixture_study_has_converged_components_measured(self):
        h3 = oracle().h3
        self.assertEqual(len(h3.converged_components), 2)
        self.assertTrue(all(c.pair.mean.is_measured for c in h3.converged_components))

    def test_i_norm_identity_trajectories(self):
        """Protocol 4: per_mask_entry at lr/width reproduces per_masked_element at lr (an identity, not a
        statistical hypothesis). Tolerance: abs 1e-9 + rel 1e-9 (fixed here)."""
        w = 3
        for seed in (1, 2, 3, 4):
            mask = tuple(i % 2 == 0 for i in range(8))
            a = bm.train(seed, steps=60, lr=0.05, rows=8, width=w, mask=mask, normalization="per_masked_element",
                         timestamp_utc=bm.PINNED_TS)
            b = bm.train(seed, steps=60, lr=0.05 / w, rows=8, width=w, mask=mask, normalization="per_mask_entry",
                         timestamp_utc=bm.PINNED_TS)
            for pa, pb in zip(a.final_params, b.final_params):
                self.assertAlmostEqual(pa, pb, delta=1e-9 + 1e-9 * abs(pa))
            for (_, la, _), (_, lb, _) in zip(a.history, b.history):
                self.assertAlmostEqual(lb, w * la, delta=1e-9 + 1e-9 * abs(lb))   # loss is exactly width x larger

    def test_required_n_hand_computed(self):
        # margins 0.10/0.05/0.10 -> hw_max = 0.5*0.05 = 0.025. level 0.9875 -> z = Phi^-1(0.99375) = 2.4977.
        # SD_max = 0.2: (2.4977*0.2/0.025)^2 = 19.98^2 = 399.2 -> n_req 400.
        n_planned, n_req, capped = bm.required_n([0.1, 0.2, 0.05], bm.Margins(), 0.9875)
        self.assertEqual((n_planned, n_req, capped), (400, 400, False))
        # SD_max = 0.05: (2.4977*0.05/0.025)^2 = 24.95 -> 25 < floor 100
        self.assertEqual(bm.required_n([0.05], bm.Margins(), 0.9875)[:2], (100, 25))
        self.assertTrue(bm.required_n([0.2], bm.Margins(), 0.9875, n_cap=300)[2])
        with self.assertRaises(ValueError):
            bm.required_n([], bm.Margins(), 0.9875)

    def test_tail_ratio_flag_has_threshold(self):
        heavy = [0.01] * 29 + [5.0]
        p = bm.summarize("t", heavy, 0.95, 100, 1, tail_ratio_max=10.0)
        self.assertTrue(any(f.startswith("heavy tail") for f in p.flags))
        p2 = bm.summarize("t", [1.0 + .01 * i for i in range(30)], 0.95, 100, 1, tail_ratio_max=10.0)
        self.assertFalse(any(f.startswith("heavy tail") for f in p2.flags))


class Gate11IsGlobal(unittest.TestCase):
    """Orchestrator decision: a failed gate 11 invalidates the C0 contrast in BOTH directions, so it forces
    H1, H2 and H3 (and JOINT) to INCONCLUSIVE. It is a true gate, unlike gate 12."""
    CASES = {"A too small": {"A": 0.0}, "F too large": {"F": 0.5}, "E loss did not fall": {"loss": 0.9}}

    def go(self, **kw):
        return bm.analyze_scores(synth_scores(FZ.seeds, **kw), frozen=FZ, registered_digest=FZ.digest,
                                 subject="syn", cfg=SMALL)

    def test_each_failure_mode_makes_each_hypothesis_and_joint_inconclusive(self):
        for label, kw in self.CASES.items():
            r = self.go(**kw)
            self.assertFalse(next(g for g in r.gates if g.name == "control_adequacy").passed, label)
            for h in (r.h1, r.h2, r.h3):
                self.assertEqual(h.verdict, V.INCONCLUSIVE, (label, h.hid))
                self.assertTrue(any("control_adequacy" in x for x in h.reasons), (label, h.hid))
            self.assertEqual(r.verdict, J.JOINT_INCONCLUSIVE, label)
            self.assertFalse(r.gates_ok)

    def test_previously_reachable_unsupported_on_bad_control_is_gone(self):
        # H3 clearly UNSUPPORTED on its own intervals (d = -1) ...
        ok = self.go(d=-1.0)
        self.assertEqual((ok.h3.verdict, ok.verdict), (V.UNSUPPORTED, J.JOINT_UNSUPPORTED))   # control: gate 11 passing
        # ... but with gate 11 failed it must NOT be reported as UNSUPPORTED (nor JOINT_UNSUPPORTED)
        for kw in self.CASES.values():
            r = self.go(d=-1.0, **kw)
            self.assertEqual([c.verdict for c in r.h3.components][0], V.UNSUPPORTED)   # raw interval still says so
            self.assertEqual(r.h3.verdict, V.INCONCLUSIVE)
            self.assertEqual(r.verdict, J.JOINT_INCONCLUSIVE)

    def test_degrader_on_inadequate_control_is_inconclusive_not_unsupported(self):
        bad = dataclasses.replace(SMALL, eps_fit=1e-9)          # F can never pass: control declared inadequate
        r = bm.run_study(FZ, bm.fixture_global_degrader(0.5), subject="d", registered_digest=FZ.digest, cfg=bad)
        self.assertFalse(next(g for g in r.gates if g.name == "control_adequacy").passed)
        self.assertEqual(r.verdict, J.JOINT_INCONCLUSIVE)
        self.assertEqual(study(bm.fixture_global_degrader(0.5), "d").verdict, J.JOINT_UNSUPPORTED)   # control

    def test_recompute_from_records_treats_gate11_as_global(self):
        recs = bm.to_experiment_records(study(bm.fixture_global_degrader(0.5), "d"), study_id="f", base_seed=7,
                                        timestamp_utc="2025-01-02T03:04:05Z")
        self.assertEqual(bm.verdict_from_records(recs, SMALL).joint, J.JOINT_UNSUPPORTED)
        j = next(r for r in recs if r.name.endswith("/JOINT"))
        bad = dataclasses.replace(j, metrics={**j.metrics, "gate_control_adequacy": MetricValue.measured(0.0)})
        rv = bm.verdict_from_records([bad if r is j else r for r in recs], SMALL)
        self.assertEqual((rv.joint, rv.h1, rv.h2, rv.h3), (J.JOINT_INCONCLUSIVE,) + (V.INCONCLUSIVE,) * 3)

    def test_only_gate12_remains_scoped(self):
        self.assertEqual({n for n, sc in bm.GATE_SCOPES.items() if sc != "all"}, {"convergence"})

    def test_gate_levels_are_the_adjusted_bonferroni_level(self):
        seen = []
        real = bm.summarize

        def spy(name, values, level, *a, **k):
            seen.append((name, level))
            return real(name, values, level, *a, **k)
        with mock.patch.object(bm, "summarize", spy):
            self.go()
        g11 = [lv for n, lv in seen if n.startswith("gate11:")]
        self.assertEqual(len(g11), 2)                       # A and F
        conv = [lv for n, lv in seen if n.startswith("H3:") and "conv" in n]
        self.assertEqual(len(conv), 2)
        self.assertEqual(set(g11 + conv), {0.9875})         # same level as the family, not 95%
        self.assertTrue(all(lv == 0.9875 for n, lv in seen if n.startswith(("H1", "H2", "H3"))))

    def test_gate11_intervals_are_bootstrap_and_block_only(self):
        # A passes only if the bootstrap LOWER bound clears delta_A; being above on the mean alone is not enough
        vals_hi = synth_scores(FZ.seeds, A=0.5)
        self.assertTrue(next(g for g in bm.evaluate_gates(vals_hi, FZ, FZ.digest, SMALL) if g.name == "control_adequacy").passed)
        r = self.go()
        self.assertEqual(r.verdict, J.JOINT_SUPPORTED)      # passing gate 11 never creates a verdict by itself
        bad = self.go(A=0.0)
        self.assertEqual(bad.verdict, J.JOINT_INCONCLUSIVE)  # failing never creates UNSUPPORTED/SUPPORTED either


class TrainedStudentCannotBeExempted(unittest.TestCase):
    """The gate-11(c) exemption is an explicit declaration by the subject, never a default."""

    def test_kinds(self):
        self.assertEqual(bm.treatment_kind(bm.ARM_FACTORIES["E"]), "trained")
        for f in (bm.fixture_oracle_gated, bm.fixture_identity_uncond, bm.fixture_global_degrader(0.5)):
            self.assertEqual(bm.treatment_kind(f), "fixture")
        self.assertEqual(bm.treatment_kind(lambda fx, cfg: None), "unknown")
        both = bm.fixture_global_degrader(0.5)
        both.trained_student = True
        with self.assertRaises(ValueError):
            bm.treatment_kind(both)

    def test_no_caller_flag_can_grant_the_exemption_to_score_seed(self):
        with self.assertRaises(TypeError):
            bm.score_seed(FZ.seeds[0], bm.ARM_FACTORIES["E"], SMALL, trained=False)

    def test_wrapped_trained_student_is_not_exempt(self):
        wrapped = lambda fx, cfg: bm.ARM_FACTORIES["E"](fx, cfg)      # loses its declaration
        self.assertEqual(bm.treatment_kind(wrapped), "unknown")
        s = bm.score_seed(FZ.seeds[0], wrapped, SMALL)
        self.assertFalse(s.metrics["E_loss_ratio"].is_measured)
        self.assertIn("undeclared", s.metrics["E_loss_ratio"].reason)

    def test_undeclared_factory_fails_gate11_in_a_study(self):
        wrapped = lambda fx, cfg: bm.fixture_oracle_gated(fx, cfg)    # an honest fixture, but undeclared
        r = bm.run_study(FZ, wrapped, subject="undeclared", registered_digest=FZ.digest, cfg=SMALL)
        g = next(g for g in r.gates if g.name == "control_adequacy")
        self.assertFalse(g.passed)
        self.assertIn("E_loss_ratio", g.reason)
        self.assertEqual(r.verdict, J.JOINT_INCONCLUSIVE)
        self.assertEqual(oracle().verdict, J.JOINT_SUPPORTED)          # declared fixture: exempt, control

    def test_declared_trained_arm_gets_a_measured_loss_ratio(self):
        # instrument check on one seed only; the value is not recorded or interpreted
        s = bm.score_seed(FZ.seeds[0], bm.ARM_FACTORIES["E"], SMALL)
        self.assertTrue(s.metrics["E_loss_ratio"].is_measured)
        self.assertEqual(s.metrics["E_loss_ratio"].value, bm._arm_fit(FZ.seeds[0], "E", SMALL).loss_ratio)

    def test_exempt_default_is_false_in_analyze_scores(self):
        sc = [bm.SeedScores.from_values(x.seed, 1, -.01, 1, 1, A=.5, F=.005, delta_conv=1, delta_minus_shuf_conv=1,
                                        conv_grad_ratio=1e-5, rowsets_disjoint=True, mask_ok=True)
              for x in synth_scores(FZ.seeds)]                        # E_loss_ratio not supplied
        r = bm.analyze_scores(sc, frozen=FZ, registered_digest=FZ.digest, subject="s", cfg=SMALL)
        self.assertFalse(next(g for g in r.gates if g.name == "control_adequacy").passed)
        r2 = bm.analyze_scores(sc, frozen=FZ, registered_digest=FZ.digest, subject="s", cfg=SMALL,
                               subject_kind="fixture", fixture_name="declared")
        self.assertTrue(next(g for g in r2.gates if g.name == "control_adequacy").passed)


class InScopeGateInvariant(unittest.TestCase):
    """JointResult refuses a decisive hypothesis alongside a failed in-scope gate, however it was built."""

    def clean(self):
        r = bm.analyze_scores(synth_scores(FZ.seeds), frozen=FZ, registered_digest=FZ.digest, subject="s", cfg=SMALL)
        self.assertEqual(r.verdict, J.JOINT_SUPPORTED)
        return r

    def fields(self, r, **over):
        return {**{f.name: getattr(r, f.name) for f in dataclasses.fields(bm.JointResult)}, **over}

    def with_failed(self, r, name):
        return tuple(bm.GateResult(g.name, False, "forced") if g.name == name else g for g in r.gates)

    def test_hand_built_hypotheses_without_blocking_cannot_go_decisive(self):
        r = self.clean()
        for name, scope in bm.GATE_SCOPES.items():
            bare = dict(h1=bm.HypothesisResult("H1", r.h1.components),            # built WITHOUT blocking info
                        h2=bm.HypothesisResult("H2", r.h2.components),
                        h3=bm.HypothesisResult("H3", r.h3.components, r.h3.converged_components))
            self.assertTrue(all(bare[k].verdict is V.SUPPORTED for k in bare))      # decisive on their own
            with self.assertRaises(ValueError, msg=name):
                bm.JointResult(**self.fields(r, gates=self.with_failed(r, name), **bare))

    def test_correctly_built_inconclusive_hypotheses_are_accepted_and_inconclusive(self):
        r = self.clean()
        for name, scope in bm.GATE_SCOPES.items():
            if scope != "all":
                continue
            blk = (f"{name} (forced)",)
            hs = {k: bm.HypothesisResult(h.hid, h.components, h.converged_components, blocking=blk)
                  for k, h in (("h1", r.h1), ("h2", r.h2), ("h3", r.h3))}
            j = bm.JointResult(**self.fields(r, gates=self.with_failed(r, name), **hs))
            self.assertEqual(j.verdict, J.JOINT_INCONCLUSIVE, name)

    def test_gate12_failure_with_supported_h3_is_refused_but_inconclusive_is_fine(self):
        r = self.clean()
        gates = self.with_failed(r, "convergence")
        with self.assertRaises(ValueError):
            bm.JointResult(**self.fields(r, gates=gates))                       # h3 still SUPPORTED
        h3 = bm.HypothesisResult("H3", r.h3.components, r.h3.converged_components, supported_blockers=("convergence",))
        self.assertEqual(bm.JointResult(**self.fields(r, gates=gates, h3=h3)).verdict, J.JOINT_INCONCLUSIVE)

    def test_dataclasses_replace_cannot_bypass(self):
        r = self.clean()
        with self.assertRaises(ValueError):
            dataclasses.replace(r, gates=self.with_failed(r, "min_seeds"))

    def test_deferred_gates_are_exactly_the_six_unimplemented_checks(self):
        want = {"gate1_config_shift_sensitivity_arm", "gate2_error_register_crosscheck", "V_set_probes",
                "pilot_execution_and_n_cap_width_rule", "assumption1_exchangeability_check", "amendment_log_hash"}
        self.assertEqual(set(bm.DEFERRED_GATES), want)
        self.assertEqual(len(bm.DEFERRED_GATES), 6)
        self.assertEqual(set(oracle().deferred_gates), want)
        for key in ("shift sensitivity", "ERROR_REGISTER", "V-set", "n_cap", "exchangeability", "amendment log"):
            self.assertIn(key, bm.__doc__)           # the module docstring names each unimplemented check
        self.assertIn("interval_verdict", bm.__doc__)


class ConstantSampleExactness(unittest.TestCase):
    CONSTS = (0.7, -0.7, 0.1, -3.3, 1e15 + 0.5, 1e300, 1e-300, 123456789.123456789, 0.0, -0.0, 5.0)

    def test_sd_and_mean_exactly_exact_on_constants(self):
        for c in self.CONSTS:
            for n in (2, 3, 7, 30, 101):
                v = [c] * n
                self.assertEqual(bm.sample_sd(v), 0.0, (c, n))
                self.assertEqual(bm.mean(v), c, (c, n))

    def test_constant_intervals_have_exactly_zero_width(self):
        for c in (0.7, -3.3, 1e15 + 0.5):
            lo, hi = bm.t_interval([c] * 30, 0.95)
            self.assertEqual((lo, hi), (c, c))
            p = bm.summarize("k", [c] * 30, 0.9875, 200, 1)
            self.assertEqual((p.boot_lo.value, p.boot_hi.value), (c, c))
            self.assertEqual(p.sd.value, 0.0)

    def test_near_constant_is_not_collapsed(self):
        self.assertGreater(bm.sample_sd([0.7, 0.7, 0.7 + 1e-9]), 0.0)
        self.assertAlmostEqual(bm.sample_sd([1.0, 2.0, 3.0, 4.0]), math.sqrt(5 / 3), places=12)   # hand: var 5/3


# ===================================================== QA round 2: subject_kind, gate pins, contract gaps
def _col(x, i):
    return x(i) if callable(x) else x[i] if isinstance(x, (list, tuple)) else x


def gate_scores(seeds=None, A=0.5, F=0.005, loss=0.01, gr=1e-5, flags=True):
    """Per-seed values for gate 11/12 inputs; each column is a scalar, a list, or a function of the index.
    None in a column means 'not measured'. Inputs to test the gate logic, not measurements."""
    seeds = FZ.seeds if seeds is None else seeds
    return [bm.SeedScores.from_values(s, 1.0, -0.01, 1.0, 1.0, A=_col(A, i), F=_col(F, i), E_loss_ratio=_col(loss, i),
                                      delta_conv=1.0, delta_minus_shuf_conv=1.0, conv_grad_ratio=_col(gr, i),
                                      rowsets_disjoint=flags, mask_ok=flags) for i, s in enumerate(seeds)]


def gate(name, kind="unknown", **cols):
    return next(g for g in bm.evaluate_gates(gate_scores(**cols), FZ, FZ.digest, SMALL, kind) if g.name == name)


class Gate11Conditions(unittest.TestCase):
    """Pins every condition of gate 11 (a global gate: it can force the whole family INCONCLUSIVE)."""
    G = staticmethod(lambda **c: gate("control_adequacy", **c).passed)

    def test_A_strictly_above_delta_a_using_the_LOWER_bound(self):
        d = SMALL.delta_A
        self.assertFalse(self.G(A=d))                      # equality fails: need lower > delta_A
        self.assertTrue(self.G(A=d + 1e-9))
        self.assertFalse(self.G(A=[0.0, 0.1] * 15))        # mean == delta_A: lower < d < upper -> fails (hi would pass)
        self.assertTrue(self.G(A=[0.1, 0.2] * 15))
        self.assertFalse(self.G(A=[-1.0] * 30))

    def test_F_strictly_below_eps_fit_using_the_UPPER_bound(self):
        e = SMALL.eps_fit
        self.assertFalse(self.G(F=e))                      # equality fails: need upper < eps_fit
        self.assertTrue(self.G(F=e - 1e-9))
        self.assertFalse(self.G(F=[0.0, 0.1] * 15))        # mean == eps_fit: upper > e (lower would pass)
        self.assertTrue(self.G(F=[0.0, 0.01] * 15))

    def test_loss_ratio_uses_the_WORST_run_and_non_strict_boundary(self):
        lim = 1.0 / SMALL.loss_factor
        self.assertTrue(self.G(loss=lim))                  # exactly at the limit passes
        self.assertFalse(self.G(loss=lim + 1e-7))
        self.assertFalse(self.G(loss=[0.9] + [0.01] * 29))   # one bad run is enough (min would pass)
        self.assertFalse(self.G(loss=[0.01] * 29 + [0.9]))
        self.assertTrue(self.G(loss=[0.01] * 30))

    def test_loss_check_exempt_only_for_fixture_kind(self):
        bad = dict(loss=0.99)
        self.assertFalse(self.G(**bad))
        self.assertFalse(gate("control_adequacy", "trained", **bad).passed)
        self.assertTrue(gate("control_adequacy", "fixture", **bad).passed)
        self.assertFalse(gate("control_adequacy", "unknown", loss=None).passed)

    def test_missing_values_are_never_tolerated(self):
        for col in ("A", "F", "loss"):
            for pos in (0, 14, 29):
                vals = [0.5 if col == "A" else 0.005 if col == "F" else 0.01] * 30
                vals[pos] = None
                self.assertFalse(self.G(**{col: vals}), (col, pos))

    def test_failed_seeds_do_not_enter_gate11_but_too_few_ok_seeds_fail_it(self):
        fz = bm.freeze_seed_list(7, 31)
        sc = gate_scores(fz.seeds[:30]) + [bm.SeedScores.failed(fz.seeds[30], "x", True, True)]
        g = next(g for g in bm.evaluate_gates(sc, fz, fz.digest, SMALL) if g.name == "control_adequacy")
        self.assertTrue(g.passed)                        # the failed seed is excluded; loss is measured on every ok seed
        g2 = next(g for g in bm.evaluate_gates(sc, fz, fz.digest, SMALL, "fixture") if g.name == "control_adequacy")
        self.assertTrue(g2.passed)
        one = [gate_scores(fz.seeds[:1])[0]] + [bm.SeedScores.failed(s, "x", True, True) for s in fz.seeds[1:4]]
        g3 = next(g for g in bm.evaluate_gates(one, bm.freeze_seed_list(7, 4), bm.freeze_seed_list(7, 4).digest,
                                               SMALL, "fixture") if g.name == "control_adequacy")
        self.assertFalse(g3.passed)                      # a single ok seed cannot form an interval
        self.assertIn("not measured", g3.reason)
        two = gate_scores(FZ.seeds[:2])
        g4 = next(g for g in bm.evaluate_gates(two, FZ, FZ.digest, SMALL, "fixture") if g.name == "control_adequacy")
        self.assertTrue(g4.passed)                       # two ok seeds can (min_seeds is a separate gate)

    def test_evaluate_gates_default_is_not_exempt(self):
        sc = gate_scores(loss=None)
        g = next(g for g in bm.evaluate_gates(sc, FZ, FZ.digest, SMALL) if g.name == "control_adequacy")
        self.assertFalse(g.passed)
        with self.assertRaises(ValueError):
            bm.evaluate_gates(sc, FZ, FZ.digest, SMALL, "bogus")


class Gate12Conditions(unittest.TestCase):
    G = staticmethod(lambda **c: gate("convergence", **c).passed)

    def test_worst_run_and_non_strict_boundary(self):
        t = SMALL.tau_conv
        self.assertTrue(self.G(gr=t))
        self.assertFalse(self.G(gr=t * 1.0000001))
        self.assertFalse(self.G(gr=[1e-5] * 29 + [0.5]))     # one unconverged run (min would pass)
        self.assertFalse(self.G(gr=[0.5] + [1e-5] * 29))
        self.assertTrue(self.G(gr=[1e-5] * 30))

    def test_missing_ratio_fails(self):
        for pos in (0, 29):
            v = [1e-5] * 30
            v[pos] = None
            self.assertFalse(self.G(gr=v))
        self.assertFalse(bm.evaluate_gates([], FZ, FZ.digest, SMALL)[-1].passed)


class SubjectKindField(unittest.TestCase):
    def test_fixtures_are_marked_with_their_names(self):
        for fac, name in ((bm.fixture_oracle_gated, "oracle_gated"), (bm.fixture_identity_uncond, "identity_uncond"),
                          (bm.fixture_global_degrader(0.5), "global_degrader")):
            r = oracle() if name == "oracle_gated" else study(fac, name)
            self.assertEqual((r.subject_kind, r.fixture_name), ("fixture", name))

    def test_trained_treatment_is_not_marked_fixture_and_cannot_pass_gate11c_with_unchanged_loss(self):
        # C_init (an untrained student, loss ratio exactly 1) as the subject: a control-arm plumbing check, not E
        r = bm.run_study(FZ, bm.ARM_FACTORIES["C_init"], subject="C_init", registered_digest=FZ.digest, cfg=SMALL)
        self.assertEqual((r.subject_kind, r.fixture_name), ("trained", None))
        self.assertFalse(next(g for g in r.gates if g.name == "control_adequacy").passed)
        self.assertEqual(r.verdict, J.JOINT_INCONCLUSIVE)

    def test_undeclared_factory_is_unknown(self):
        r = bm.run_study(FZ, lambda fx, cfg: bm.fixture_oracle_gated(fx, cfg), subject="u", registered_digest=FZ.digest, cfg=SMALL)
        self.assertEqual((r.subject_kind, r.fixture_name), ("unknown", None))

    def test_construction_rules(self):
        o = oracle()
        f = {x.name: getattr(o, x.name) for x in dataclasses.fields(bm.JointResult)}
        for over in ({"subject_kind": "bogus"}, {"subject_kind": "fixture", "fixture_name": None},
                     {"subject_kind": "fixture", "fixture_name": "  "}, {"subject_kind": "trained", "fixture_name": "x"},
                     {"subject_kind": "unknown", "fixture_name": "x"}):
            with self.assertRaises(ValueError, msg=over):
                bm.JointResult(**{**f, **over})

    def test_kind_is_stored_as_a_metric_and_recomputed_ignoring_notes(self):
        ts = "2025-01-02T03:04:05Z"
        for res, want in ((oracle(), "fixture"),
                          (bm.run_study(FZ, bm.ARM_FACTORIES["C_init"], subject="C_init", registered_digest=FZ.digest, cfg=SMALL), "trained")):
            recs = bm.to_experiment_records(res, study_id="f", base_seed=7, timestamp_utc=ts)
            self.assertTrue(all(r.metrics["subject_kind_code"].value == bm.SUBJECT_KIND_CODE[want] for r in recs))
            self.assertEqual(bm.verdict_from_records(recs, SMALL).subject_kind, want)
            self.assertIn(f"subject_kind={want}", recs[-1].notes)                 # informational only
            lying = [dataclasses.replace(r, notes=r.notes.replace(f"subject_kind={want}", "subject_kind=unknown"))
                     for r in recs]
            self.assertEqual(bm.verdict_from_records(lying, SMALL).subject_kind, want)
            j = recs[-1]
            flipped = dataclasses.replace(j, metrics={**j.metrics, "subject_kind_code": MetricValue.measured(0.0)})
            if want == "fixture":      # the exemption flag stored with it makes the flip a detectable forgery
                with self.assertRaises(ValueError):
                    bm.verdict_from_records(recs[:-1] + [flipped], SMALL)
            else:
                self.assertEqual(bm.verdict_from_records(recs[:-1] + [flipped], SMALL).subject_kind, "unknown")
        sr = bm.seed_records(oracle(), study_id="f", timestamp_utc=ts)
        self.assertEqual(sr[0].metrics["subject_kind_code"].value, 2.0)


class ContractEdges(unittest.TestCase):
    def test_gateresult_passed_is_strictly_boolean(self):
        for bad in ("False", "True", "", 0, 1, None, 0.0):
            with self.assertRaises(ValueError, msg=repr(bad)):
                bm.GateResult("min_seeds", bad, "r")
        bm.GateResult("min_seeds", True, "r")
        bm.GateResult("min_seeds", False, "r")
        with self.assertRaises(ValueError):
            bm.GateResult("not_a_gate", True, "r")
        with self.assertRaises(ValueError):
            bm.GateResult("min_seeds", True, 5)

    def test_truthy_string_gate_cannot_reach_joint_supported(self):
        o = oracle()
        with self.assertRaises(ValueError):
            bm.JointResult(**{**{x.name: getattr(o, x.name) for x in dataclasses.fields(bm.JointResult)},
                              "gates": tuple(bm.GateResult(g.name, "False", "x") if g.name == "min_seeds" else g
                                             for g in o.gates)})

    def test_treatment_kind_declarations_are_strict(self):
        for val in ("yes", 1, "True", [1]):
            f = lambda fx, cfg: None
            f.trained_student = val
            self.assertEqual(bm.treatment_kind(f), "unknown")
            g = lambda fx, cfg: None
            g.scorer_validation_fixture = val
            self.assertEqual(bm.treatment_kind(g), "unknown")
        f = lambda fx, cfg: None
        f.trained_student = True
        with self.assertRaises(ValueError):                  # no arm_name: not a bare AttributeError
            bm.treatment_kind(f)
        with self.assertRaises(ValueError):
            bm.score_seed(FZ.seeds[0], f, SMALL)
        f.arm_name = "nonsense"
        with self.assertRaises(ValueError):
            bm.treatment_kind(f)
        g = lambda fx, cfg: None
        g.scorer_validation_fixture = True
        with self.assertRaises(ValueError):
            bm.treatment_kind(g)

    def test_overflow_is_handled_not_raised_raw(self):
        # true SD of [1e200,-1e200] is sqrt(2)*1e200 = 1.41421356e200 (representable) although the squares overflow
        self.assertAlmostEqual(bm.sample_sd([1e200, -1e200]) / 1.4142135623730951e200, 1.0, places=12)
        # true mean of [1e308,1e308,1] is (2e308+1)/3 = 6.6667e307 (representable) although the sum overflows
        self.assertAlmostEqual(bm.mean([1e308, 1e308, 1.0]) / 6.666666666666667e307, 1.0, places=12)
        with self.assertRaises(ValueError):                  # true SD sqrt(2)*1.7e308 = 2.4e308 is not representable
            bm.sample_sd([1.7e308, -1.7e308])
        with self.assertRaises(ValueError):
            bm.t_interval([1.7e308, -1.7e308], 0.95)

    def test_ci_level_is_validated_on_recompute(self):
        recs = bm.to_experiment_records(oracle(), study_id="f", base_seed=7, timestamp_utc="2025-01-02T03:04:05Z")
        h1 = next(r for r in recs if r.name.endswith("/H1"))
        for lv in (0.5, 0.95, 0.98333333, 0.9):
            bad = dataclasses.replace(h1, metrics={**h1.metrics, "ci_level": MetricValue.measured(lv)})
            with self.assertRaises(ValueError, msg=lv):
                bm.verdict_from_records([bad if r is h1 else r for r in recs], SMALL)
        unm = dataclasses.replace(h1, metrics={**h1.metrics, "ci_level": MetricValue.unmeasured("x")})
        with self.assertRaises(ValueError):
            bm.verdict_from_records([unm if r is h1 else r for r in recs], SMALL)

    def test_every_missing_or_failed_gate_blocks_recompute(self):
        recs = bm.to_experiment_records(oracle(), study_id="f", base_seed=7, timestamp_utc="2025-01-02T03:04:05Z")
        j = next(r for r in recs if r.name.endswith("/JOINT"))
        self.assertEqual(bm.verdict_from_records(recs, SMALL).joint, J.JOINT_SUPPORTED)
        for name, scope in bm.GATE_SCOPES.items():
            for how in ("drop", "zero"):
                m = {k: v for k, v in j.metrics.items() if k != f"gate_{name}"}
                if how == "zero":
                    m[f"gate_{name}"] = MetricValue.measured(0.0)
                rv = bm.verdict_from_records([dataclasses.replace(j, metrics=m) if r is j else r for r in recs], SMALL)
                self.assertNotEqual(rv.joint, J.JOINT_SUPPORTED, (name, how))
                if scope == "all":
                    self.assertEqual((rv.joint, rv.h1, rv.h2, rv.h3), (J.JOINT_INCONCLUSIVE,) + (V.INCONCLUSIVE,) * 3)
                else:
                    self.assertEqual(rv.h3, V.INCONCLUSIVE)


class JointInvariantCoversEveryHypothesis(unittest.TestCase):
    def test_each_decisive_hypothesis_alone_is_refused_with_a_failed_global_gate(self):
        r = bm.analyze_scores(synth_scores(FZ.seeds), frozen=FZ, registered_digest=FZ.digest, subject="s", cfg=SMALL)
        gates = tuple(bm.GateResult(g.name, False, "forced") if g.name == "min_seeds" else g for g in r.gates)
        blk = ("min_seeds (forced)",)
        mk = {"h1": lambda b: bm.HypothesisResult("H1", r.h1.components, blocking=b),
              "h2": lambda b: bm.HypothesisResult("H2", r.h2.components, blocking=b),
              "h3": lambda b: bm.HypothesisResult("H3", r.h3.components, r.h3.converged_components, blocking=b)}
        f = {x.name: getattr(r, x.name) for x in dataclasses.fields(bm.JointResult)}
        for open_one in mk:                                     # exactly one hypothesis left un-blocked
            hs = {k: fn(() if k == open_one else blk) for k, fn in mk.items()}
            self.assertIs(hs[open_one].verdict, V.SUPPORTED)
            with self.assertRaises(ValueError, msg=open_one):
                bm.JointResult(**{**f, "gates": gates, **hs})


class FixtureGuards(unittest.TestCase):
    """Minimum mask size, row-set disjointness and mask correctness are each enforced and each reach the gates."""

    def setUp(self):
        bm.build_fixture.cache_clear()
        self.seen = {}

    def tearDown(self):
        bm.build_fixture.cache_clear()

    def patched(self, train_fn=None, T_fn=None, U_fn=None):
        orig = bm._rows

        def fake(rng, n, width, want):
            rows = orig(rng, n, width, want)
            if want is None:
                rows = train_fn(rows) if train_fn else rows
                self.seen["train"] = rows
                return rows
            fn = T_fn if want is True else U_fn
            rows = fn(rows) if fn else rows
            if want is True:
                self.seen["T"] = rows
            return rows
        return mock.patch.object(bm, "_rows", fake)

    @staticmethod
    def with_x0(vals):
        return lambda rows: tuple((vals[i] if i < len(vals) else -0.5 - 0.01 * i, r[1], r[2]) for i, r in enumerate(rows))

    def test_mask_size_and_distinctness(self):
        s = FZ.seeds[0]
        for vals in ((0.5,), (0.5, 0.5), ()):
            bm.build_fixture.cache_clear()
            with self.patched(train_fn=self.with_x0(vals)):
                with self.assertRaises(bm.IneligibleSeed, msg=vals):
                    bm.build_fixture(s, SMALL)
        bm.build_fixture.cache_clear()
        with self.patched(train_fn=self.with_x0((0.5, 0.6))):          # exactly two distinct masked rows: eligible
            fx = bm.build_fixture(s, SMALL)
        self.assertEqual(sum(fx.train_mask), 2)

    def test_overlap_is_detected_and_fails_the_gate(self):
        s = FZ.seeds[0]

        def overlap(rows):
            reg = [r for r in self.seen["train"] if bm.in_region(r)]
            return tuple(reg[i % len(reg)] for i in range(len(rows)))
        with self.patched(T_fn=overlap):
            fx = bm.build_fixture(s, SMALL)
            sc = bm.score_seed(s, bm.fixture_identity_uncond, SMALL)
        self.assertFalse(fx.disjoint)
        self.assertIs(sc.rowsets_disjoint, False)
        g = next(g for g in bm.evaluate_gates([sc] + gate_scores(FZ.seeds[1:30]), FZ, FZ.digest, SMALL)
                 if g.name == "rowsets_disjoint")
        self.assertFalse(g.passed)

    def test_U_train_overlap_and_T_region_violation_each_detected(self):
        s = FZ.seeds[0]

        def u_overlap(rows):
            out = [r for r in self.seen["train"] if not bm.in_region(r)]
            return tuple(out[i % len(out)] for i in range(len(rows)))
        with self.patched(U_fn=u_overlap):
            fx = bm.build_fixture(s, SMALL)
        self.assertFalse(fx.disjoint)                          # only the U/TRAIN overlap can cause this
        self.assertTrue(fx.mask_ok)
        bm.build_fixture.cache_clear()
        with self.patched(T_fn=lambda rows: ((-0.5, rows[0][1], rows[0][2]),) + tuple(rows[1:])):
            fx2 = bm.build_fixture(s, SMALL)
        self.assertFalse(fx2.mask_ok)                          # a T row outside the region
        self.assertTrue(fx2.disjoint)

    def test_T_U_overlap_detected(self):
        with self.patched(U_fn=lambda rows: (self.seen["T"][0],) + tuple(rows[1:])):
            fx = bm.build_fixture(FZ.seeds[0], SMALL)
        self.assertFalse(fx.disjoint)

    def test_region_violation_is_detected_and_fails_the_gate(self):
        s = FZ.seeds[0]
        with self.patched(U_fn=lambda rows: ((0.5, rows[0][1], rows[0][2]),) + tuple(rows[1:])):
            fx = bm.build_fixture(s, SMALL)
            sc = bm.score_seed(s, bm.fixture_identity_uncond, SMALL)
        self.assertFalse(fx.mask_ok)
        self.assertTrue(fx.disjoint)
        g = next(g for g in bm.evaluate_gates([sc] + gate_scores(FZ.seeds[1:30]), FZ, FZ.digest, SMALL)
                 if g.name == "mask_correct")
        self.assertFalse(g.passed)

    def test_one_bad_or_unmeasured_seed_fails_each_flag_gate(self):
        for attr, gname in (("rowsets_disjoint", "rowsets_disjoint"), ("mask_ok", "mask_correct")):
            for bad in (False, None):
                sc = gate_scores()
                kw = {"rowsets_disjoint": True, "mask_ok": True, attr: bad}
                sc[7] = bm.SeedScores.from_values(FZ.seeds[7], 1.0, -0.01, 1.0, 1.0, A=.5, F=.005, E_loss_ratio=.01,
                                                  delta_conv=1.0, delta_minus_shuf_conv=1.0, conv_grad_ratio=1e-5, **kw)
                g = next(g for g in bm.evaluate_gates(sc, FZ, FZ.digest, SMALL) if g.name == gname)
                self.assertFalse(g.passed, (attr, bad))
        self.assertTrue(all(g.passed for g in bm.evaluate_gates(gate_scores(), FZ, FZ.digest, SMALL, "fixture")))


# ===================================================== QA round 3: the "equivalent" labels that were wrong
class HypothesisResultPublicConstructor(unittest.TestCase):
    """The public constructor is what enforces 'no verdict without an interval'; drive it directly."""

    def comp(self, lo, hi, metric="S", direction="greater", margin=0.1, n=40):
        z = bm._mv
        pair = bm.IntervalPair("p", n, 0.9875, 100, z((lo + hi) / 2, ""), z(.1, ""), z(.1, ""), z(lo, ""), z(hi, ""),
                               z(1., ""), z(lo, ""), z(hi, ""), z(lo, ""), z(hi, ""))
        return bm.ComponentResult(metric, direction, margin, pair, 30, 0.25)

    def good(self, metric="S", direction="greater"):
        c = self.comp(0.5, 0.9, metric, direction)
        self.assertIs(c.verdict, V.SUPPORTED)
        return c

    def test_duck_typed_component_with_a_verdict_but_no_interval_is_refused(self):
        class Duck:
            metric, verdict, reason = "S", V.SUPPORTED, "trust me"
        for comps, conv in (((Duck(),), ()), ((self.good(),), (Duck(), Duck()))):
            with self.assertRaises(ValueError):
                bm.HypothesisResult("H1" if not conv else "H3", comps if not conv else (self.good(), self.good()), conv)
        with self.assertRaises(ValueError):
            bm.HypothesisResult("H1", (Duck(),))
        with self.assertRaises(ValueError):
            bm.HypothesisResult("H3", (self.good(), self.good()), (Duck(), Duck()))
        with self.assertRaises(ValueError):
            bm.HypothesisResult("H1", ("SUPPORTED",))

    def test_component_counts_are_enforced(self):
        g = self.good
        with self.assertRaises(ValueError):
            bm.HypothesisResult("H1", (g(), g()))                         # H1 has one component
        with self.assertRaises(ValueError):
            bm.HypothesisResult("H1", ())
        with self.assertRaises(ValueError):
            bm.HypothesisResult("H3", (g(),), (g(), g()))                 # H3 needs two finite components
        with self.assertRaises(ValueError):
            bm.HypothesisResult("H3", (g(), g(), g()))
        with self.assertRaises(ValueError):
            bm.HypothesisResult("H1", (g(),), (g(),))                     # converged components belong to H3 only
        with self.assertRaises(ValueError):
            bm.HypothesisResult("H3", (g(), g()), (g(), g(), g()))
        with self.assertRaises(ValueError):
            bm.HypothesisResult("H9", (g(),))

    def test_h3_without_the_full_converged_set_is_never_supported(self):
        g = self.good
        for conv in ((), (g(),)):
            h = bm.HypothesisResult("H3", (g(), g()), conv)
            self.assertIs(h.verdict, V.INCONCLUSIVE, len(conv))
            self.assertTrue(any("not evaluated" in x for x in h.reasons))
        self.assertIs(bm.HypothesisResult("H3", (g(), g()), (g(), g())).verdict, V.SUPPORTED)   # control

    def test_unsupported_converged_component_blocks_h3_support(self):
        bad = self.comp(-0.5, 0.0)
        self.assertIs(bad.verdict, V.UNSUPPORTED)
        h = bm.HypothesisResult("H3", (self.good(), self.good()), (self.good(), bad))
        self.assertIs(h.verdict, V.INCONCLUSIVE)                          # block-only: never UNSUPPORTED from conv


class ConfigHashProvenance(unittest.TestCase):
    def test_hash_is_stable_and_changes_with_every_field(self):
        base = bm.BenchmarkConfig()
        self.assertEqual(base.config_hash(), bm.BenchmarkConfig().config_hash())
        self.assertRegex(base.config_hash(), r"^[0-9a-f]{64}$")
        seen = {base.config_hash()}
        for f in dataclasses.fields(base):
            v = getattr(base, f.name)
            other = dataclasses.replace(base, **{f.name: (v + 1 if isinstance(v, int) else v * 1.5 if v else 0.5)})
            h = other.config_hash()
            self.assertNotEqual(h, base.config_hash(), f.name)
            self.assertNotIn(h, seen, f.name)
            seen.add(h)
        self.assertNotEqual(bm.BenchmarkConfig().config_hash(), bm.BenchmarkConfig(steps=301).config_hash())

    def test_study_records_the_config_hash_of_its_config(self):
        o = oracle()
        self.assertEqual(o.config_hash, SMALL.config_hash())
        self.assertNotEqual(o.config_hash, bm.BenchmarkConfig().config_hash())     # n_boot differs


class BoundaryAndGuardGaps(unittest.TestCase):
    def test_width_tolerance_boundary_is_not_a_disagreement(self):
        # widths 1 and 0.75 differ by exactly 0.25 of the larger: 'more than 25%' is false
        self.assertEqual(bm.intervals_disagree((0.0, 1.0), (0.0, 0.75), 5.0, 0.25), (False, "agree"))
        self.assertTrue(bm.intervals_disagree((0.0, 1.0), (0.0, 0.7499), 5.0, 0.25)[0])
        self.assertTrue(bm.intervals_disagree((0.0, 1.0), (0.0, 0.75), 5.0, 0.2499)[0])

    def test_unmeasured_or_missing_interval_is_inconclusive_never_a_verdict(self):
        # n = 1 allowed through by min_n = 1: bounds do not exist
        one = bm.summarize("one", [5.0], 0.9875, 10, 1, min_n=1)
        self.assertEqual(bm.interval_verdict(one, 0.1, "greater", min_n=1)[0], V.INCONCLUSIVE)
        self.assertIn("not computable", bm.interval_verdict(one, 0.1, "greater", min_n=1)[1])
        # n = 40 but unmeasured bounds: what verdict_from_records rebuilds from records with unmeasured bounds
        u = bm.MetricValue.unmeasured("x")
        m = bm._mv(1.0, "")
        for boot_ok, t_ok in ((False, False), (True, False), (False, True)):
            lo, hi = (m, m) if boot_ok else (u, u)
            tlo, thi = (m, m) if t_ok else (u, u)
            pair = bm.IntervalPair("p", 40, 0.9875, 100, m, m, m, m, m, m, lo, hi, tlo, thi)
            v, why = bm.interval_verdict(pair, 0.1, "greater")
            self.assertEqual(v, V.INCONCLUSIVE, (boot_ok, t_ok))
            self.assertIn("not computable", why)

    def test_recompute_with_unmeasured_bounds_is_inconclusive(self):
        recs = bm.to_experiment_records(oracle(), study_id="f", base_seed=7, timestamp_utc="2025-01-02T03:04:05Z")
        h1 = next(r for r in recs if r.name.endswith("/H1"))
        for k in ("ci_t_lo", "ci_boot_hi"):
            bad = dataclasses.replace(h1, metrics={**h1.metrics, k: bm.MetricValue.unmeasured("x")})
            rv = bm.verdict_from_records([bad if r is h1 else r for r in recs], SMALL)
            self.assertEqual(rv.h1, V.INCONCLUSIVE, k)
            self.assertEqual(rv.joint, J.JOINT_INCONCLUSIVE, k)

    def test_a_seed_counted_as_failed_never_feeds_another_hypothesis(self):
        fz = bm.freeze_seed_list(7, 40)
        sc = []
        for i, s in enumerate(fz.seeds):
            if i < 2:   # S unmeasured => run failed; L = 50 would wreck H2 if it leaked in
                sc.append(bm.SeedScores.from_values(s, None, 50.0, 1.0, 1.0, A=.5, F=.005, E_loss_ratio=.01,
                                                    delta_conv=1.0, delta_minus_shuf_conv=1.0, conv_grad_ratio=1e-5,
                                                    rowsets_disjoint=True, mask_ok=True))
            else:
                sc.append(synth_scores([s], rng_seed=i)[0])
        r = bm.analyze_scores(sc, frozen=fz, registered_digest=fz.digest, subject="s", cfg=SMALL)
        self.assertEqual(r.n_failed, 2)
        for h in (r.h1, r.h2, r.h3):
            for c in h.components + h.converged_components:
                self.assertEqual(c.pair.n, 38, (h.hid, c.metric))
        self.assertLess(r.h2.components[0].pair.mean.value, 0.0)           # the L=50 values are not in it
        self.assertIs(r.h2.verdict, V.SUPPORTED)

    def test_mean_and_sd_refuse_non_finite_and_use_exact_sums(self):
        inf, nan = float("inf"), float("nan")
        for bad in ([inf, inf, inf], [nan, 1.0], [1.0, -inf], [True, False]):
            with self.assertRaises(ValueError, msg=bad):
                bm.sample_sd(bad)
        for bad in ([inf], [nan, 1.0]):
            with self.assertRaises(ValueError, msg=bad):
                bm.mean(bad)
        with self.assertRaises(ValueError):
            bm.bootstrap_means([1.0, nan], 5, make_rng(1))
        # math.fsum, not built-in sum (sum is compensated only from Python 3.12): the true mean is 0.5
        self.assertEqual(bm.mean([1e16, 1.0, -1e16, 1.0]), 0.5)
        self.assertEqual(bm.mean([0.1] * 10), 0.1)


# ===================================================== QA round 4
class SdUnderflow(unittest.TestCase):
    def exact_sd(self, v):
        from fractions import Fraction
        fr = [Fraction(x) for x in v]
        m = sum(fr) / len(fr)
        var = sum((x - m) ** 2 for x in fr) / (len(fr) - 1)
        import decimal
        decimal.getcontext().prec = 60
        return float(decimal.Decimal(var.numerator) / decimal.Decimal(var.denominator)) ** 0.5 if var > 1e-300 else \
            float((decimal.Decimal(var.numerator) / decimal.Decimal(var.denominator)).sqrt())

    def test_tiny_nonconstant_samples_do_not_report_zero(self):
        self.assertAlmostEqual(bm.sample_sd([1e-170, 2e-170]) / 7.0710678118654755e-171, 1.0, places=12)
        self.assertEqual(bm.sample_sd([5e-324, 1e-323, 0.0]), 5e-324)        # deviations are 0, +1 ulp, -1 ulp
        for v in ([1e-170, 2e-170], [1e-200, 3e-200, 2e-200, 9e-200], [5e-324, 1e-323, 0.0], [0.0, 1e-160, 3e-160]):
            sd = bm.sample_sd(v)
            self.assertGreater(sd, 0.0, v)
            self.assertAlmostEqual(sd / self.exact_sd(v), 1.0, places=9, msg=v)

    def test_zero_sd_if_and_only_if_constant(self):
        r = random.Random(5)
        for _ in range(300):
            scale = 10.0 ** r.randint(-320, 300)
            base = r.uniform(-1, 1) * scale
            v = [base + r.choice((0.0, r.uniform(0, 1) * scale * 1e-3)) for _ in range(r.randint(2, 8))]
            const = len(set(v)) == 1
            try:
                sd = bm.sample_sd(v)
            except ValueError:
                continue                                  # unrepresentable results are refused, never mis-reported
            self.assertEqual(sd == 0.0, const, v)

    def test_boundary_scales_agree(self):
        for scale in (1e-151, 1e-149, 1.0, 1e149, 1e151):
            sd = bm.sample_sd([0.0, scale, 3 * scale])
            self.assertAlmostEqual(sd / (scale * 1.5275252316519468), 1.0, places=12, msg=scale)


class ExemptionFlagAndForgery(unittest.TestCase):
    TS = "2025-01-02T03:04:05Z"

    def fields(self, r):
        return {f.name: getattr(r, f.name) for f in dataclasses.fields(bm.JointResult)}

    def test_gateresult_exempt_is_strict_and_only_for_control_adequacy(self):
        for bad in ("True", 1, None):
            with self.assertRaises(ValueError):
                bm.GateResult("control_adequacy", True, "r", exempt=bad)
        with self.assertRaises(ValueError):
            bm.GateResult("min_seeds", True, "r", exempt=True)
        self.assertTrue(bm.GateResult("control_adequacy", True, "r", exempt=True).exempt)

    def test_pipeline_sets_exempt_exactly_for_fixtures(self):
        gate_of = lambda r: next(g for g in r.gates if g.name == "control_adequacy")
        self.assertTrue(gate_of(oracle()).exempt)
        syn = bm.analyze_scores(synth_scores(FZ.seeds), frozen=FZ, registered_digest=FZ.digest, subject="s", cfg=SMALL)
        self.assertFalse(gate_of(syn).exempt)

    def test_hand_built_result_with_exempt_gates_must_be_labelled_fixture(self):
        o = oracle()
        for kind in ("trained", "unknown"):
            with self.assertRaisesRegex(ValueError, "exemption"):
                bm.JointResult(**{**self.fields(o), "subject_kind": kind, "fixture_name": None})
        # the same gates under the honest label are accepted
        self.assertEqual(bm.JointResult(**self.fields(o)).subject_kind, "fixture")
        with self.assertRaises(ValueError):
            dataclasses.replace(o, subject_kind="trained", fixture_name=None)

    def test_subject_kind_vocabulary_is_checked(self):
        syn = bm.analyze_scores(synth_scores(FZ.seeds), frozen=FZ, registered_digest=FZ.digest, subject="s", cfg=SMALL)
        for bad in ("bogus", "", "Fixture", None, 2):
            with self.assertRaisesRegex(ValueError, "subject_kind must be one of"):
                bm.JointResult(**{**self.fields(syn), "subject_kind": bad})
        with self.assertRaises(ValueError):
            bm.evaluate_gates(gate_scores(), FZ, FZ.digest, SMALL, "bogus")

    def test_records_carry_exempt_flag_and_forgeries_are_refused(self):
        recs = bm.to_experiment_records(oracle(), study_id="f", base_seed=7, timestamp_utc=self.TS)
        j = recs[-1]
        self.assertEqual(j.metrics["loss_check_exempt"].value, 1.0)
        self.assertEqual(bm.verdict_from_records(recs, SMALL).subject_kind, "fixture")
        for forged in ({"subject_kind_code": MetricValue.measured(1.0)},        # relabelled trained
                       {"subject_kind_code": MetricValue.measured(0.0)}):       # relabelled unknown
            bad = dataclasses.replace(j, metrics={**j.metrics, **forged})
            with self.assertRaisesRegex(ValueError, "exemption"):
                bm.verdict_from_records(recs[:-1] + [bad], SMALL)
        gone = dataclasses.replace(j, metrics={k: v for k, v in j.metrics.items() if k != "subject_kind_code"})
        with self.assertRaisesRegex(ValueError, "exemption"):                  # deleted code reads 'unknown'
            bm.verdict_from_records(recs[:-1] + [gone], SMALL)
        syn = bm.analyze_scores(synth_scores(FZ.seeds), frozen=FZ, registered_digest=FZ.digest, subject="s", cfg=SMALL)
        srecs = bm.to_experiment_records(syn, study_id="f", base_seed=7, timestamp_utc=self.TS)
        self.assertEqual(srecs[-1].metrics["loss_check_exempt"].value, 0.0)
        self.assertEqual(bm.verdict_from_records(srecs, SMALL).subject_kind, "unknown")
        lie = dataclasses.replace(srecs[-1], metrics={**srecs[-1].metrics, "loss_check_exempt": MetricValue.measured(1.0)})
        with self.assertRaisesRegex(ValueError, "exemption"):
            bm.verdict_from_records(srecs[:-1] + [lie], SMALL)

    def test_notes_kind_follows_subject_kind(self):
        recs = bm.to_experiment_records(oracle(), study_id="f", base_seed=7, timestamp_utc=self.TS)
        self.assertTrue(all("SCORER-VALIDATION FIXTURE" in r.notes for r in recs))
        syn = bm.analyze_scores(synth_scores(FZ.seeds), frozen=FZ, registered_digest=FZ.digest, subject="s", cfg=SMALL)
        srecs = bm.to_experiment_records(syn, study_id="f", base_seed=7, timestamp_utc=self.TS)
        self.assertTrue(all("SCORER-VALIDATION FIXTURE" not in r.notes and "toy fixture" in r.notes for r in srecs))
        for res, wrong in ((oracle(), False), (syn, True)):
            with self.assertRaisesRegex(ValueError, "contradicts"):
                bm.to_experiment_records(res, study_id="f", base_seed=7, timestamp_utc=self.TS, scorer_validation=wrong)
        bm.to_experiment_records(oracle(), study_id="f", base_seed=7, timestamp_utc=self.TS, scorer_validation=True)


class SmallPins(unittest.TestCase):
    def test_empty_seed_list_cannot_pass_the_flag_gates(self):
        g = {x.name: x for x in bm.evaluate_gates([], FZ, FZ.digest, SMALL)}
        for name in ("rowsets_disjoint", "mask_correct", "failure_rate", "min_seeds"):
            self.assertFalse(g[name].passed, name)

    def test_missing_tolerances_fail_by_assertion_not_by_crash(self):
        for kw, name, text in (({"loss": [None] + [0.01] * 29}, "control_adequacy", "E_loss_ratio not measured"),
                               ({"gr": [None] + [1e-5] * 29}, "convergence", "not measured")):
            try:
                g = gate(name, **kw)
            except Exception as e:                       # a TypeError here would only be a crash, not a verdict
                self.fail(f"{name} raised {type(e).__name__}: {e}")
            self.assertFalse(g.passed)
            self.assertIn(text, g.reason)


class OracleAcrossBaseSeeds(unittest.TestCase):
    """Five base seeds, 30 seeds each, n_boot=2000 (NOT the protocol default 10,000). Split in two on purpose:
    the invariants below hold under any gate configuration; the pins depend on the DEFAULT eps_fit/tau_conv/steps."""
    EXPECT = {7: J.JOINT_SUPPORTED, 11: J.JOINT_SUPPORTED, 99: J.JOINT_SUPPORTED,
              23: J.JOINT_INCONCLUSIVE, 5: J.JOINT_INCONCLUSIVE}
    RUNS = {}

    @classmethod
    def run_for(cls, base):
        if base not in cls.RUNS:
            cls.RUNS[base] = study(bm.fixture_oracle_gated, f"o{base}", base=base)
        return cls.RUNS[base]

    def test_config_independent_invariants(self):
        for base in self.EXPECT:
            r = self.run_for(base)
            comps = [c.verdict for h in (r.h1, r.h2, r.h3) for c in h.components + h.converged_components]
            self.assertEqual(set(comps), {V.SUPPORTED}, base)          # intervals are clear-cut for the oracle
            self.assertNotEqual(r.verdict, J.JOINT_UNSUPPORTED, base)
            failed = {g.name for g in r.gates if not g.passed}
            self.assertTrue(failed <= {"control_adequacy", "convergence"}, (base, failed))
            self.assertEqual(r.verdict == J.JOINT_SUPPORTED, not failed, base)   # SUPPORTED iff every gate passes

    DEFAULTS = {"width": 3, "n_train": 24, "n_eval": 32, "steps": 300, "lr": 0.3, "eta_star": 0.5, "g_min": 1e-3,
                "n_boot": 10_000, "alpha": 0.05, "min_seeds": 30, "max_failure_rate": 0.05, "width_tol": 0.25,
                "steps_conv": 1000, "tau_conv": 1e-3, "delta_A": 0.05, "eps_fit": 0.05, "loss_factor": 2.0,
                "tail_ratio_max": 10.0}
    MARGIN_DEFAULTS = {"delta_S": 0.10, "delta_R": 0.05, "delta_sel": 0.10}
    HINT = ("a BenchmarkConfig/Margins DEFAULT changed or a field was added. The EXPECT pins below were measured "
            "under these defaults: record the change in docs/PROGRESS.md, re-measure deliberately, then update this "
            "table. (eta_star is the erasure strength itself.)")

    def test_every_config_field_default_is_pinned(self):
        fields = {f.name: f.default for f in dataclasses.fields(bm.BenchmarkConfig)}
        self.assertEqual(set(fields), set(self.DEFAULTS), self.HINT)       # a new field must be added to the table
        for name, want in self.DEFAULTS.items():
            with self.subTest(field=name):
                self.assertEqual(fields[name], want, self.HINT)
                self.assertIs(type(fields[name]), type(want), name)
        mf = {f.name: f.default for f in dataclasses.fields(bm.Margins)}
        self.assertEqual(mf, self.MARGIN_DEFAULTS, self.HINT)

    def test_default_parameter_pins(self):
        for base, want in self.EXPECT.items():
            with self.subTest(base_seed=base):
                got = self.run_for(base).verdict
                self.assertEqual(
                    got, want,
                    f"base seed {base}: oracle verdict {got.value} != pinned {want.value}. If the defaults test "
                    f"passes, this is a CODE change that moved a verdict: find out why before touching EXPECT. "
                    f"If a default or budget changed, record it in docs/PROGRESS.md first.")


# ===================================================== QA round 5
class RelabelDetectionEndToEnd(unittest.TestCase):
    TS = "2025-01-02T03:04:05Z"

    def relabelled(self, kind):
        r = dataclasses.replace(oracle())                       # fresh instance; the shared oracle is untouched
        object.__setattr__(r, "subject_kind", kind)             # post-hoc tampering (documented open route)
        object.__setattr__(r, "fixture_name", None)
        return r

    def test_relabel_then_records_then_refusal(self):
        for kind in ("trained", "unknown"):
            recs = bm.to_experiment_records(self.relabelled(kind), study_id="f", base_seed=7, timestamp_utc=self.TS)
            j = recs[-1]
            self.assertEqual(j.metrics["subject_kind_code"].value, bm.SUBJECT_KIND_CODE[kind])
            self.assertEqual(j.metrics["loss_check_exempt"].value, 1.0)       # derived from the GATES, not the label
            with self.assertRaisesRegex(ValueError, "exemption"):
                bm.verdict_from_records(recs, SMALL)

    def test_deleted_flag_does_not_crash_and_is_documented_as_undetectable(self):
        recs = bm.to_experiment_records(oracle(), study_id="f", base_seed=7, timestamp_utc=self.TS)
        j = recs[-1]
        gone = dataclasses.replace(j, metrics={k: v for k, v in j.metrics.items() if k != "loss_check_exempt"})
        rv = bm.verdict_from_records(recs[:-1] + [gone], SMALL)               # old-format records: no AttributeError
        self.assertEqual(rv.subject_kind, "fixture")
        syn = bm.analyze_scores(synth_scores(FZ.seeds), frozen=FZ, registered_digest=FZ.digest, subject="s", cfg=SMALL)
        srecs = bm.to_experiment_records(syn, study_id="f", base_seed=7, timestamp_utc=self.TS)
        j2 = srecs[-1]
        gone2 = dataclasses.replace(j2, metrics={k: v for k, v in j2.metrics.items() if k != "loss_check_exempt"})
        self.assertEqual(bm.verdict_from_records(srecs[:-1] + [gone2], SMALL).subject_kind, "unknown")

    def test_flag_value_must_be_exactly_zero_or_one(self):
        recs = bm.to_experiment_records(oracle(), study_id="f", base_seed=7, timestamp_utc=self.TS)
        j = recs[-1]
        for v in (2.0, -1.0, 0.5):
            bad = dataclasses.replace(j, metrics={**j.metrics, "loss_check_exempt": MetricValue.measured(v)})
            with self.assertRaisesRegex(ValueError, "must be 0.0 or 1.0"):
                bm.verdict_from_records(recs[:-1] + [bad], SMALL)


class SdScaleBands(unittest.TestCase):
    def test_every_magnitude_band_gives_the_exact_answer(self):
        # SD of [0, s, 3s] is s*sqrt(7/3) ... (mean 4s/3; deviations -4s/3, -s/3, 5s/3; var = (16+1+25)/9/2 s^2)
        k = math.sqrt(42 / 18)
        for s in (1e-200, 1e-160, 1e-155, 1e-151, 1e-149, 1e-100, 1.0, 1e100, 1e149, 1e151, 1e154, 1e160, 1e199,
                  1e200, 1e204):
            self.assertAlmostEqual(bm.sample_sd([0.0, s, 3 * s]) / (s * k), 1.0, places=11, msg=s)

    def test_huge_band_does_not_raise(self):
        for s in (1e154, 1e160, 1e199):
            try:
                bm.sample_sd([0.0, s, 3 * s])
            except ValueError as e:
                self.fail(f"a representable SD at scale {s} was refused: {e}")

    def test_documented_limits_of_the_zero_sd_invariant(self):
        # (1) float floor: true SD 2.017e-324 (= 5e-324/sqrt(6)) rounds to 0.0 although the sample is not constant.
        # THIS line is the behavioural check on sample_sd; the arithmetic assertions further down only check the
        # figures quoted in the docstring and never call sample_sd.
        self.assertEqual(bm.sample_sd([0.0] * 5 + [5e-324]), 0.0)
        # (2) Python ints beyond 2**53 are converted to float
        self.assertEqual(bm.sample_sd([10 ** 20, 10 ** 20 + 1]), 0.0)
        # (3) fails closed with a false ValueError (x - m overflows)
        with self.assertRaises(ValueError):
            bm.sample_sd([1.7e308, -1.7e308, -1.7e308, -1.7e308])
        doc = " ".join(bm.sample_sd.__doc__.split())
        for needle in ("FLOAT FLOOR", "PYTHON INTS", "FALSE ValueError",
                       "Consumers (SR-11 robustness probes) must NOT read zero-SD as 'constant' for samples within a "
                       "few subnormal steps of each other",
                       "the `float(v)` cast in `SeedSummary.from_values`", "HALF the smallest subnormal (4.94e-324)", "2.017e-324"):
            self.assertIn(needle, doc)
        # the floor arithmetic quoted in the docstring
        # (in units of the smallest subnormal 4.94e-324; subnormal arithmetic itself is avoided here)
        self.assertAlmostEqual(4.94 / math.sqrt(6), 2.017, places=3)         # true SD of [0]*5+[1 step]
        self.assertLess(1 / math.sqrt(6), 0.5)               # below half a step: 0.0 is the correctly rounded SD
        self.assertGreater(bm.sample_sd([0.0] * 2 + [5e-324] * 2 + [1e-323]), 0.0)   # a few steps apart: nonzero
        # (4) an int too large for float is refused with ValueError, not a raw OverflowError
        with self.assertRaises(ValueError):
            bm.sample_sd([10 ** 400, 1])
        with self.assertRaises(ValueError):
            bm.mean([10 ** 400])

    @staticmethod
    def has_live_float_reference(source):
        """True iff the ANNOTATION-STRIPPED AST of `source` holds a live `ast.Name(id='float', ctx=Load)`.

        The annotation stripping is the whole point. Without it this helper was DEAD against its one real
        target: `def from_values(cls, values: Sequence[float])` supplies that Name from the ANNOTATION, so the
        helper returned True for the shipped cast, for `v * 1.0`, for the cast deleted entirely, and for the
        cast moved into a helper -- every mutation it existed to catch (all four measured). Only stripping the
        annotation and re-measuring makes it a tripwire rather than a constant."""
        import ast, textwrap

        class StripAnnotations(ast.NodeTransformer):
            def visit_arg(self, n):
                n.annotation = None
                return n

            def visit_FunctionDef(self, n):
                n.returns = None
                self.generic_visit(n)
                return n

            visit_AsyncFunctionDef = visit_FunctionDef

            def visit_AnnAssign(self, n):
                n.annotation = ast.Constant(value=None)
                if n.value is not None:
                    n.value = self.visit(n.value)
                return n

        tree = StripAnnotations().visit(ast.parse(textwrap.dedent(source)))
        return any(isinstance(n, ast.Name) and n.id == "float" and isinstance(n.ctx, ast.Load)
                   for n in ast.walk(tree))

    def test_the_cited_float_cast_still_exists_in_robustness(self):
        """TRIPWIRE ON A CROSS-MODULE CITATION, NOT A SEMANTIC GUARANTEE. `bm.sample_sd`'s docstring cites
        `the `float(v)` cast in `SeedSummary.from_values`` by symbol; this keeps that citation honest. It is
        KEPT rather than deleted because no semantic test can: a behaviour test pins that coercion happens,
        not that the cast is still written at the cited place, and a stale citation is exactly the class of
        inaccuracy this audit keeps finding. The BEHAVIOUR is pinned separately and semantically by
        test_robustness.test_from_values_wraps_unrepresentable_and_bad_types_in_valueerror (full cast removal
        leaks OverflowError there) and test_from_values_numeric_type_contract.
        Measured limits, pinned case by case in test_the_tripwire_itself_behaves_as_documented: dead code
        still satisfies it, and moving the cast into a helper turns it red even when that is harmless.
        When it fails, look at robustness.py and update sample_sd's docstring; do not just edit this."""
        import inspect
        from toy import robustness
        src = inspect.getsource(robustness.SeedSummary.from_values)
        # The real target IS annotated with `float` -- the exact trap this guard fell into. If this line ever
        # stops holding, the companion test's annotated snippets no longer model the target.
        self.assertIn("values: Sequence[float]", src)
        self.assertTrue(self.has_live_float_reference(src))
        self.assertNotIn("robustness.py:", " ".join(bm.sample_sd.__doc__.split()))   # no line-number citation

    def test_the_tripwire_itself_behaves_as_documented(self):
        """Every case carries the SAME annotation as the one real target, because the previous version of this
        test fed hand-written ANNOTATION-FREE snippets and so certified behaviour the target did not exhibit.
        Under the old helper the four `False` annotated cases below were all True: the guard was dead."""
        ann = "def f(v: Sequence[float]) -> float:\n"
        cases = {
            "live cast":                  (ann + "    return tuple(float(x) for x in v)\n", True),
            "map(float, ...)":            (ann + "    return tuple(map(float, v))\n", True),
            "dead code after return":     (ann + "    return v\n    float(v)\n", True),
            "comment decoy only":         (ann + "    # float(v) is cast here\n    return v\n", False),
            "cast moved into a helper":   (ann + "    return tuple(_coerce(x) for x in v)\n", False),
            "cast replaced by v * 1.0":   (ann + "    return tuple(x * 1.0 for x in v)\n", False),
            "cast deleted entirely":      (ann + "    return tuple(v)\n", False),
            "annotated local, no cast":   (ann + "    out: list[float] = []\n    return tuple(out)\n", False),
        }
        for name, (src, want) in cases.items():
            self.assertEqual(self.has_live_float_reference(src), want, name)
        self.assertEqual(len(cases), 8)        # eight annotated cases ...
        # ... plus two unannotated controls, so the fixed helper still agrees with the old one where the old
        # one was right (the annotation, not the stripping, was the bug).
        self.assertTrue(self.has_live_float_reference("def f(v):\n    return tuple(float(x) for x in v)\n"))
        self.assertFalse(self.has_live_float_reference("def f(v):\n    return tuple(v)\n"))

    def test_empty_seed_list_fails_failure_rate_even_if_the_limit_is_one(self):
        lax = dataclasses.replace(SMALL, max_failure_rate=1.0)
        g = next(x for x in bm.evaluate_gates([], FZ, FZ.digest, lax) if x.name == "failure_rate")
        self.assertFalse(g.passed)


# ===================================================== QA round 6
class RelabelRouteBoundaryIsExactlyAsDocumented(unittest.TestCase):
    """Pins the open route as it really is: the FLAG ALONE defeats the cross-check. Not a defence; a disclosure."""
    TS = "2025-01-02T03:04:05Z"

    def records(self, kind):
        r = dataclasses.replace(oracle())
        object.__setattr__(r, "subject_kind", kind)
        object.__setattr__(r, "fixture_name", None)
        return bm.to_experiment_records(r, study_id="f", base_seed=7, timestamp_utc=self.TS)

    def test_relabelled_records_with_the_flag_neutralised_are_accepted(self):
        for kind in ("trained", "unknown"):
            recs = self.records(kind)
            j = recs[-1]
            with self.assertRaises(ValueError):                              # control: flag left at 1.0 is caught
                bm.verdict_from_records(recs, SMALL)
            keep = {k: v for k, v in j.metrics.items() if k != "loss_check_exempt"}
            variants = {"flag deleted": keep,
                        "flag zeroed": {**keep, "loss_check_exempt": MetricValue.measured(0.0)},
                        "flag unmeasured": {**keep, "loss_check_exempt": MetricValue.unmeasured("x")},
                        "both fields deleted": {k: v for k, v in keep.items() if k != "subject_kind_code"}}
            for name, metrics in variants.items():
                rv = bm.verdict_from_records(recs[:-1] + [dataclasses.replace(j, metrics=metrics)], SMALL)
                self.assertEqual(rv.subject_kind, kind if name != "both fields deleted" else "unknown", (kind, name))
                self.assertEqual(rv.joint, J.JOINT_SUPPORTED, (kind, name))      # the documented hole

    def test_the_docstring_states_that_the_flag_alone_suffices(self):
        doc = " ".join(bm.__doc__.split())
        self.assertIn("THAT CROSS-CHECK IS DEFEATED BY THE FLAG ALONE", doc)
        self.assertNotIn("forged consistently", doc)

    def test_unmeasured_flag_is_handled_not_crashed(self):
        recs = bm.to_experiment_records(oracle(), study_id="f", base_seed=7, timestamp_utc=self.TS)
        j = recs[-1]
        bad = dataclasses.replace(j, metrics={**j.metrics, "loss_check_exempt": MetricValue.unmeasured("x")})
        self.assertEqual(bm.verdict_from_records(recs[:-1] + [bad], SMALL).subject_kind, "fixture")


class RecomputeIsBoundToTheStoredConfiguration(unittest.TestCase):
    """SR-10 item 2. `verdict_from_records` took min_seeds/width_tol/alpha from the caller's `cfg` and never
    compared `cfg.config_hash()` with the `config` hash the record already carries. Reachable by ORDINARY
    CALL, not tampering: every pre-existing test passed the study's own config, which is why it survived."""
    TS = "2025-01-02T03:04:05Z"
    # width_tol 0.10 vs the module default 0.25; this is the parameter that was shielded by nothing.
    TIGHT = dataclasses.replace(SMALL, width_tol=0.10)

    @classmethod
    def setUpClass(cls):
        cls.res = bm.run_study(FZ, bm.fixture_oracle_gated, subject="oracle_gated",
                               registered_digest=FZ.digest, cfg=cls.TIGHT)
        cls.recs = bm.to_experiment_records(cls.res, study_id="f", base_seed=7, timestamp_utc=cls.TS)

    def test_the_studys_own_config_recomputes_and_reports_itself_bound(self):
        rv = bm.verdict_from_records(self.recs, self.TIGHT)
        self.assertEqual(rv.reasons, ())
        self.assertEqual(rv.config_hash, self.res.config_hash)
        self.assertEqual((rv.joint, rv.h1, rv.h2, rv.h3),
                         (self.res.verdict, self.res.h1.verdict, self.res.h2.verdict, self.res.h3.verdict))

    def test_omitting_cfg_fails_closed_instead_of_using_module_defaults(self):
        """THE DEFECT. The default width_tol (0.25) is laxer than the registered 0.10, so before the fix the
        no-argument call turned this study's JOINT_INCONCLUSIVE into JOINT_SUPPORTED."""
        self.assertNotEqual(bm.BenchmarkConfig().config_hash(), self.res.config_hash)
        rv = bm.verdict_from_records(self.recs)                      # no cfg argument at all
        self.assertEqual((rv.joint, rv.h1, rv.h2, rv.h3),
                         (J.JOINT_INCONCLUSIVE,) + (V.INCONCLUSIVE,) * 3)
        self.assertEqual(len(rv.reasons), 1)
        self.assertIn("does not match the stored study configuration", rv.reasons[0])
        self.assertNotEqual(rv.joint, J.JOINT_SUPPORTED)

    def test_every_cfg_derived_parameter_is_bound_not_just_width_tol(self):
        for over in ({"width_tol": 0.9}, {"min_seeds": 5}, {"alpha": 0.01}, {"n_boot": 999},
                     {"eta_star": 0.25}, {"tau_conv": 1.0}):
            rv = bm.verdict_from_records(self.recs, dataclasses.replace(self.TIGHT, **over))
            self.assertEqual((rv.joint, rv.h1, rv.h2, rv.h3),
                             (J.JOINT_INCONCLUSIVE,) + (V.INCONCLUSIVE,) * 3, over)
            self.assertIn("does not match the stored study configuration", rv.reasons[0], over)

    def _strip_config(self, recs):
        return [dataclasses.replace(r, provenance=dataclasses.replace(
            r.provenance, input_hashes={k: v for k, v in r.provenance.input_hashes.items() if k != "config"}))
            for r in recs]

    def test_absent_stored_hash_fails_closed(self):
        rv = bm.verdict_from_records(self._strip_config(self.recs), self.TIGHT)
        self.assertEqual((rv.joint, rv.h1), (J.JOINT_INCONCLUSIVE, V.INCONCLUSIVE))
        self.assertIn("no stored config hash", rv.reasons[0])
        self.assertIsNone(rv.config_hash)
        # one record missing it is enough: a partial binding is no binding
        mixed = self.recs[:-1] + self._strip_config(self.recs[-1:])
        self.assertIn("no stored config hash", bm.verdict_from_records(mixed, self.TIGHT).reasons[0])

    def test_records_disagreeing_about_the_config_fail_closed(self):
        j = self.recs[-1]
        lie = dataclasses.replace(j, provenance=dataclasses.replace(
            j.provenance, input_hashes={**j.provenance.input_hashes, "config": "0" * 64}))
        rv = bm.verdict_from_records(self.recs[:-1] + [lie], self.TIGHT)
        self.assertEqual((rv.joint, rv.h1), (J.JOINT_INCONCLUSIVE, V.INCONCLUSIVE))
        self.assertIn("disagree on the stored config hash", rv.reasons[0])

    def test_a_forgery_is_still_raised_even_under_a_config_mismatch(self):
        """Ordering pin: the exemption cross-check must not be masked by the new fail-closed return."""
        j = self.recs[-1]
        forged = dataclasses.replace(j, metrics={**j.metrics, "subject_kind_code": MetricValue.measured(1.0)})
        with self.assertRaisesRegex(ValueError, "exemption"):
            bm.verdict_from_records(self.recs[:-1] + [forged], self.TIGHT)       # matching cfg
        with self.assertRaisesRegex(ValueError, "exemption"):
            bm.verdict_from_records(self.recs[:-1] + [forged])                   # mismatching cfg
        with self.assertRaisesRegex(ValueError, "exemption"):                    # and with no stored hash
            bm.verdict_from_records(self._strip_config(self.recs[:-1] + [forged]), self.TIGHT)

    def test_a_clean_recompute_never_carries_a_reason(self):
        self.assertEqual(bm.verdict_from_records(
            bm.to_experiment_records(oracle(), study_id="f", base_seed=7, timestamp_utc=self.TS), SMALL).reasons, ())

    def test_the_docstring_no_longer_claims_only_stored_metrics(self):
        doc = " ".join(bm.verdict_from_records.__doc__.split())
        # the false claim may appear ONLY as an attributed correction, never as the docstring's own promise
        self.assertNotIn("Rebuild the verdict ONLY from stored metrics", doc)
        self.assertIn('used to claim "ONLY from stored metrics", which was false', doc)
        for needle in ("BOUND TO THE CONFIGURATION THE STUDY RAN UNDER",
                       "`cfg.min_seeds`, `cfg.width_tol` and `cfg.alpha` are not stored as metrics",
                       "FAIL CLOSED", "never fall back to module defaults"):
            self.assertIn(needle, doc)
        mod = " ".join(bm.__doc__.split())
        self.assertIn("fails CLOSED", mod)
        # the open-routes list no longer claims every remaining hole is tampering
        self.assertIn("THAT FRAMING ONCE OVERSTATED THE CASE", mod)
        self.assertIn('"the routes known to us", never "the only routes"', mod)


class MarginsAreNotInTheConfigHash(unittest.TestCase):
    """SR-10 item 3. Documented, not closed: the per-record `margin` metric is what makes it sound."""

    def test_two_studies_differing_only_in_margins_hash_identically(self):
        self.assertEqual(SMALL.config_hash(), SMALL.config_hash())
        self.assertNotIn("delta_S", str(dataclasses.asdict(SMALL)))
        self.assertNotIn("margins", {f.name for f in dataclasses.fields(bm.BenchmarkConfig)})
        a = bm.analyze_scores(synth_scores(FZ.seeds), frozen=FZ, registered_digest=FZ.digest, subject="s",
                              cfg=SMALL, margins=bm.Margins())
        b = bm.analyze_scores(synth_scores(FZ.seeds), frozen=FZ, registered_digest=FZ.digest, subject="s",
                              cfg=SMALL, margins=bm.Margins(delta_S=5.0, delta_R=-5.0, delta_sel=5.0))
        self.assertEqual(a.config_hash, b.config_hash)               # byte-identical provenance ...
        self.assertNotEqual(a.h1.verdict, b.h1.verdict)              # ... with different verdicts

    def test_the_recompute_reads_the_margin_out_of_the_record_not_out_of_cfg(self):
        """The mitigation, pinned: change the stored `margin` metric alone and the recomputed verdict moves,
        which is only possible if `cfg` never supplies a margin."""
        a = bm.analyze_scores(synth_scores(FZ.seeds), frozen=FZ, registered_digest=FZ.digest, subject="s",
                              cfg=SMALL, margins=bm.Margins())
        recs = bm.to_experiment_records(a, study_id="f", base_seed=7, timestamp_utc="2025-01-02T03:04:05Z")
        h1 = next(r for r in recs if r.name.endswith("/H1"))
        self.assertEqual(h1.metrics["margin"].value, 0.10)
        self.assertEqual(bm.verdict_from_records(recs, SMALL).h1, V.SUPPORTED)
        raised = dataclasses.replace(h1, metrics={**h1.metrics, "margin": MetricValue.measured(9.0)})
        rv = bm.verdict_from_records([raised if r is h1 else r for r in recs], SMALL)
        self.assertEqual(rv.h1, V.UNSUPPORTED)
        self.assertEqual(rv.reasons, ())                  # the config still matched: margins are not in it

    def test_the_gap_and_the_int_float_asymmetry_are_documented(self):
        mg = " ".join(bm.Margins.__doc__.split())
        for needle in ("NOT COVERED BY `BenchmarkConfig.config_hash()`",
                       "TWO STUDIES DIFFERING ONLY IN MARGINS PRODUCE BYTE-IDENTICAL `config_hash`",
                       "reads the margin OUT OF THE RECORD",
                       "`config_hash` alone is not a complete provenance key"):
            self.assertIn(needle, mg)
        ch = " ".join(bm.BenchmarkConfig.config_hash.__doc__.split())
        self.assertIn("`Margins` is NOT a field", ch)
        self.assertIn("compare `==` yet hash DIFFERENTLY", ch)
        # the safe-direction asymmetry itself
        self.assertEqual(bm.BenchmarkConfig(eta_star=1), bm.BenchmarkConfig(eta_star=1.0))
        self.assertNotEqual(bm.BenchmarkConfig(eta_star=1).config_hash(),
                            bm.BenchmarkConfig(eta_star=1.0).config_hash())

    def test_every_benchmarkconfig_field_still_changes_the_hash(self):
        base = SMALL.config_hash()
        bumps = {"width": 4, "n_train": 32, "n_eval": 16, "steps": 301, "lr": 0.4, "eta_star": 0.6,
                 "g_min": 2e-3, "n_boot": 2001, "alpha": 0.04, "min_seeds": 31, "max_failure_rate": 0.06,
                 "width_tol": 0.26, "steps_conv": 1001, "tau_conv": 2e-3, "delta_A": 0.06, "eps_fit": 0.06,
                 "loss_factor": 3.0, "tail_ratio_max": 11.0}
        self.assertEqual(set(bumps), {f.name for f in dataclasses.fields(bm.BenchmarkConfig)})
        seen = {base}
        for k, v in bumps.items():
            h = dataclasses.replace(SMALL, **{k: v}).config_hash()
            self.assertNotIn(h, seen, k)
            seen.add(h)
        self.assertEqual(len(seen), 19)      # 18 fields + the base, zero collisions


class TheExemptionIsReadInExactlyOnePlace(unittest.TestCase):
    """SR-10 item 4 (B16b). `JointResult.__post_init__` filtered on `isinstance(g, GateResult)` while
    `to_experiment_records` did not, so the class's stated invariant was false and the mismatch only failed
    closed one step downstream, at the recompute."""
    TS = "2025-01-02T03:04:05Z"

    class Duck:                 # not a GateResult, but asserts the exemption just as much
        name = "control_adequacy"
        passed = True
        reason = "duck"
        exempt = True
        scope = "all"

    def syn(self):
        return bm.analyze_scores(synth_scores(FZ.seeds), frozen=FZ, registered_digest=FZ.digest, subject="s",
                                 cfg=SMALL)

    def test_a_duck_typed_exempt_gate_is_refused_at_construction(self):
        syn = self.syn()
        f = {x.name: getattr(syn, x.name) for x in dataclasses.fields(bm.JointResult)}
        gates = tuple(syn.gates) + (self.Duck(),)
        self.assertEqual(sorted(g.name for g in gates if isinstance(g, bm.GateResult)),
                         sorted(bm.GATE_SCOPES))          # the gate-NAME check cannot catch this
        for kind in ("trained", "unknown"):
            with self.assertRaisesRegex(ValueError, "exemption"):
                bm.JointResult(**{**f, "gates": gates, "subject_kind": kind, "fixture_name": None})

    def test_the_invariant_the_class_states_is_now_true(self):
        """Before the fix this exact object was ACCEPTED as 'trained' and then emitted
        loss_check_exempt=1.0 / subject_kind_code=1.0, which verdict_from_records refuses."""
        syn = self.syn()
        f = {x.name: getattr(syn, x.name) for x in dataclasses.fields(bm.JointResult)}
        for extra in ((self.Duck(),), (self.Duck(), self.Duck())):
            with self.assertRaisesRegex(ValueError, "exemption"):
                bm.JointResult(**{**f, "gates": tuple(syn.gates) + extra,
                                  "subject_kind": "trained", "fixture_name": None})
        # the same gate list under the honest label is accepted, and then agrees with the record it emits
        ok = bm.JointResult(**{**f, "gates": tuple(syn.gates) + (self.Duck(),),
                               "subject_kind": "fixture", "fixture_name": "declared"})
        j = bm.to_experiment_records(ok, study_id="f", base_seed=7, timestamp_utc=self.TS)[-1]
        self.assertEqual(j.metrics["loss_check_exempt"].value, 1.0)
        self.assertEqual(j.metrics["subject_kind_code"].value, bm.SUBJECT_KIND_CODE["fixture"])
        self.assertEqual(bm.verdict_from_records(
            bm.to_experiment_records(ok, study_id="f", base_seed=7, timestamp_utc=self.TS),
            SMALL).subject_kind, "fixture")

    def test_both_readers_go_through_the_one_helper_and_are_strict(self):
        self.assertTrue(bm.carries_exemption([self.Duck()]))
        self.assertTrue(bm.carries_exemption([bm.GateResult("control_adequacy", True, "r", exempt=True)]))
        self.assertFalse(bm.carries_exemption([bm.GateResult("min_seeds", True, "r")]))
        self.assertFalse(bm.carries_exemption([]))
        for truthy in ("True", 1, [1], 1.0):            # strictness matches GateResult.__post_init__
            duck = type("D", (), {"name": "control_adequacy", "passed": True, "reason": "", "exempt": truthy,
                                  "scope": "all"})()
            self.assertFalse(bm.carries_exemption([duck]), truthy)
        self.assertFalse(bm.carries_exemption([object()]))     # no `exempt` attribute at all
        # and the real pipeline still sets it exactly for fixtures
        self.assertTrue(bm.carries_exemption(oracle().gates))
        self.assertFalse(bm.carries_exemption(self.syn().gates))


class BooleansAreNeverMeasurements(unittest.TestCase):
    """SR-10 item 5 (B23). `_mv`'s `isinstance(x, bool)` guard, reachable through the public API and
    previously untested: dropping it makes True/False become measured(1.0)/measured(0.0)."""

    def test_mv_refuses_bools_directly(self):
        for b in (True, False):
            mv = bm._mv(b, "why not")
            self.assertFalse(mv.is_measured, b)
            self.assertIsNone(mv.value)
            self.assertEqual(mv.reason, "why not")
        self.assertTrue(bm._mv(1.0, "x").is_measured)     # control: a real float is measured
        self.assertTrue(bm._mv(0.0, "x").is_measured)     # including zero, which the bools must not mimic
        self.assertEqual(bm._mv(0.0, "x").value, 0.0)

    def test_the_public_route_seedscores_from_values(self):
        s = bm.SeedScores.from_values(0, True, False, True, 1.0)
        for k in ("S", "L", "delta"):
            self.assertFalse(s.metrics[k].is_measured, k)
            self.assertEqual(s.metrics[k].reason, "non-finite", k)
        self.assertTrue(s.metrics["delta_minus_shuf"].is_measured)      # the one genuine float
        self.assertEqual(s.metrics["delta_minus_shuf"].value, 1.0)
        self.assertFalse(s.ok)

    def test_the_optional_argument_route_too(self):
        s = bm.SeedScores.from_values(0, 1.0, 1.0, 1.0, 1.0, S_U=True, G=False, A=True, F=False,
                                      E_loss_ratio=True, delta_conv=False, delta_minus_shuf_conv=True,
                                      conv_grad_ratio=False)
        for k in ("S_U", "G", "A", "F", "E_loss_ratio", "delta_conv", "delta_minus_shuf_conv",
                  "conv_grad_ratio"):
            self.assertFalse(s.metrics[k].is_measured, k)
        self.assertTrue(s.ok)       # the four primaries are real floats

    def test_a_boolean_gate_input_cannot_satisfy_a_gate(self):
        """The consequence that matters: a bool must not be able to pass gate 11/12 by looking like 1.0/0.0."""
        scores = [bm.SeedScores.from_values(s, 1.0, -0.01, 1.0, 1.0, A=True, F=False, E_loss_ratio=False,
                                            delta_conv=1.0, delta_minus_shuf_conv=1.0, conv_grad_ratio=False,
                                            rowsets_disjoint=True, mask_ok=True) for s in FZ.seeds]
        gates = {g.name: g for g in bm.evaluate_gates(scores, FZ, FZ.digest, SMALL)}
        self.assertFalse(gates["control_adequacy"].passed)
        self.assertFalse(gates["convergence"].passed)
        self.assertIn("not measured on every seed", gates["convergence"].reason)


class ProtocolParameterDefaultsAreNotSharedObjects(unittest.TestCase):
    """Reported by the dashboard owner. `cfg`/`margins` were LITERAL default objects, evaluated once at
    import, so one instance was shared by every no-argument call. Both classes are frozen, but this kit's own
    threat model uses `object.__setattr__` to simulate tampering and that reaches through the freeze."""

    def scores(self):
        return synth_scores(FZ.seeds)

    def test_no_signature_declares_a_mutable_protocol_parameter_default(self):
        import inspect
        for fn in (bm.analyze_scores, bm.run_study, bm.verdict_from_records):
            for p in inspect.signature(fn).parameters.values():
                self.assertNotIsInstance(p.default, (bm.Margins, bm.BenchmarkConfig),
                                         f"{fn.__name__}({p.name}=) is a shared default object")
            self.assertIn("cfg", inspect.signature(fn).parameters)

    def test_each_call_gets_its_own_margins_and_config(self):
        a = bm.analyze_scores(self.scores(), frozen=FZ, registered_digest=FZ.digest, subject="s", cfg=SMALL)
        b = bm.analyze_scores(self.scores(), frozen=FZ, registered_digest=FZ.digest, subject="s", cfg=SMALL)
        self.assertEqual(a.margins, b.margins)
        self.assertIsNot(a.margins, b.margins)

    def test_forging_one_results_margins_cannot_poison_a_later_default_call(self):
        """THE DEFECT, measured: before the fix the fresh call below came back with delta_S = 99.0 and its
        verdict flipped SUPPORTED -> UNSUPPORTED."""
        first = bm.analyze_scores(self.scores(), frozen=FZ, registered_digest=FZ.digest, subject="s", cfg=SMALL)
        self.assertEqual(first.h1.verdict, V.SUPPORTED)
        object.__setattr__(first.margins, "delta_S", 99.0)      # exactly how routes (b)/(d) are demonstrated
        self.assertEqual(first.margins.delta_S, 99.0)           # the forgery really took
        fresh = bm.analyze_scores(self.scores(), frozen=FZ, registered_digest=FZ.digest, subject="s", cfg=SMALL)
        self.assertEqual(fresh.margins.delta_S, 0.10)
        self.assertEqual(fresh.margins, bm.Margins())
        self.assertEqual(fresh.h1.verdict, V.SUPPORTED)
        # and a non-numeric forgery cannot make a later default call raise either
        object.__setattr__(first.margins, "delta_S", "x")
        self.assertEqual(bm.analyze_scores(self.scores(), frozen=FZ, registered_digest=FZ.digest,
                                           subject="s", cfg=SMALL).h1.verdict, V.SUPPORTED)

    def test_the_cfg_resolver_really_constructs_per_call(self):
        """QA found this guard ineffective and the finding was exact. The test below forges a
        STAND-IN `BenchmarkConfig` and then asserts a FRESHLY constructed one is clean -- which is
        trivially true whether `_cfg` constructs per call or returns a module-level singleton, since
        the stand-in is a different object from the singleton either way. Making `_cfg` return a
        singleton SURVIVED all 307 tests.

        What the signature guard does cover is the ORIGINAL defect form -- a literal default object
        in the signature -- because that instance is reachable from `inspect.signature(...).default`.
        What was unpinned is the per-call construction the docstring promises. This asserts it
        directly, the way the `Margins` guard already did by forging the live resolved object."""
        self.assertIsNot(bm._cfg(None), bm._cfg(None))
        self.assertEqual(bm._cfg(None), bm._cfg(None))          # equal by value, distinct by identity
        # an explicit cfg must be passed through untouched, not copied
        given = bm.BenchmarkConfig(n_boot=2000)
        self.assertIs(bm._cfg(given), given)
        # and the same for the margins resolver, so both halves are pinned the same way
        self.assertIsNot(bm._margins(None), bm._margins(None))
        self.assertEqual(bm._margins(None), bm._margins(None))
        m = bm.Margins(delta_S=0.2)
        self.assertIs(bm._margins(m), m)
        # poisoning one resolved default cannot reach the next call
        first = bm._cfg(None)
        object.__setattr__(first, "width_tol", 99.0)
        self.assertEqual(bm._cfg(None).width_tol, 0.25)

    def test_forging_a_configs_field_cannot_poison_a_later_default_call(self):
        o = oracle()
        probe = bm.BenchmarkConfig()
        object.__setattr__(probe, "width_tol", 99.0)            # a stand-in for the once-shared instance
        self.assertEqual(bm.BenchmarkConfig().width_tol, 0.25)
        rv = bm.verdict_from_records(bm.to_experiment_records(
            o, study_id="f", base_seed=7, timestamp_utc="2025-01-02T03:04:05Z"), SMALL)
        self.assertEqual(rv.reasons, ())
        self.assertEqual(rv.joint, J.JOINT_SUPPORTED)

    def test_seed_list_digest_is_order_sensitive(self):
        """QA found this unpinned: making `seed_list_digest` order-blind SURVIVED all 307 tests, and
        order-sensitivity is exactly what the `seed_list_frozen` gate and the repeatability criterion
        rest on. Without it a reordered seed list still satisfies the gate, and a scorecard's `seeds`
        tuple could be reversed while `per_seed` stayed put -- misattributing every per-seed value
        behind a digest that still validates."""
        seeds = (11, 22, 33, 44, 55)
        d = bm.seed_list_digest(seeds)
        self.assertNotEqual(d, bm.seed_list_digest(tuple(reversed(seeds))))
        self.assertNotEqual(d, bm.seed_list_digest((22, 11, 33, 44, 55)))   # one adjacent swap
        self.assertEqual(d, bm.seed_list_digest(seeds))                     # stable for the same order
        # membership, length and duplication stay bound too, so the fix cannot narrow to order alone
        self.assertNotEqual(d, bm.seed_list_digest((11, 22, 33, 44)))
        self.assertNotEqual(d, bm.seed_list_digest(seeds + (66,)))
        self.assertNotEqual(d, bm.seed_list_digest((11, 11, 33, 44, 55)))
        self.assertNotEqual(d, bm.seed_list_digest((11, 22, 33, 44, 56)))

    def test_equal_configs_still_share_the_fixture_caches(self):
        """Per-call construction must not cost a cache miss: frozen dataclasses hash by value."""
        self.assertEqual(bm.BenchmarkConfig(), bm.BenchmarkConfig())
        self.assertEqual(hash(bm.BenchmarkConfig()), hash(bm.BenchmarkConfig()))
        before = bm.build_fixture.cache_info()
        bm.build_fixture(FZ.seeds[0], bm.BenchmarkConfig(n_boot=2000))
        bm.build_fixture(FZ.seeds[0], bm.BenchmarkConfig(n_boot=2000))
        after = bm.build_fixture.cache_info()
        self.assertGreater(after.hits, before.hits)

    def test_the_reason_is_written_down_where_the_next_reader_will_look(self):
        mod = " ".join(bm.__doc__.split())
        self.assertIn("LITERAL default objects", mod)
        self.assertIn("one instance shared by every no-argument call", mod)
        self.assertIn("CONSTRUCTED PER CALL", " ".join(bm.analyze_scores.__doc__.split()))
        self.assertIn("constructed per call", " ".join(bm.run_study.__doc__.split()))


class SdOverflowFallback(unittest.TestCase):
    def test_overflowing_sum_of_squares_becomes_a_value_error(self):
        # reachable in practice only for n above ~1.8e8; simulated by patching the squares helper
        with mock.patch.object(bm, "_sum_sq", side_effect=OverflowError("simulated")):
            with self.assertRaisesRegex(ValueError, "not representable"):
                bm.sample_sd([1.0, 2.0, 4.0])


# ===================================================== QA round 7
class SumSqSeamPinsTheOverflowGuarantee(unittest.TestCase):
    def test_a_sum_of_squares_that_overflows_to_inf_becomes_value_error(self):
        # plain sum() would return inf rather than raise; the guarantee must hold either way
        with mock.patch.object(bm, "_sum_sq", return_value=float("inf")):
            with self.assertRaisesRegex(ValueError, "not representable"):
                bm.sample_sd([1.0, 2.0, 4.0])

    def test_nan_from_the_seam_is_also_refused(self):
        with mock.patch.object(bm, "_sum_sq", return_value=float("nan")):
            with self.assertRaisesRegex(ValueError, "not representable"):
                bm.sample_sd([1.0, 2.0, 4.0])


class NonSequenceInputsAreValueErrors(unittest.TestCase):
    def test_public_statistics_refuse_non_sequences_with_value_error(self):
        bad = (None, {"a": 1.0, "b": 2.0}, {1.0, 2.0}, 5, 5.0, "12", b"12", object(), (x for x in (1.0, 2.0)))
        for v in bad:
            for fn in (bm.mean, bm.sample_sd, lambda x: bm.t_interval(x, 0.95),
                       lambda x: bm.bootstrap_means(x, 5, make_rng(1))):
                with self.assertRaises(ValueError, msg=repr(v)):
                    fn(v)

    def test_real_sequences_still_work(self):
        for v in ([1.0, 2.0, 4.0], (1.0, 2.0, 4.0), range(1, 4)):
            self.assertAlmostEqual(bm.mean(v), sum(v) / 3)
            self.assertGreater(bm.sample_sd(v), 0.0)
            bm.t_interval(v, 0.95)


class RelabelRouteFullGrid(unittest.TestCase):
    TS = "2025-01-02T03:04:05Z"

    def test_additional_accepted_routes(self):
        syn = bm.analyze_scores(synth_scores(FZ.seeds), frozen=FZ, registered_digest=FZ.digest, subject="s", cfg=SMALL)
        recs = bm.to_experiment_records(syn, study_id="f", base_seed=7, timestamp_utc=self.TS)
        j = recs[-1]
        base = {k: v for k, v in j.metrics.items() if k not in ("subject_kind_code", "loss_check_exempt")}
        M = MetricValue.measured
        routes = {"flag 0.0 + out-of-range code 7.0": ({"subject_kind_code": M(7.0), "loss_check_exempt": M(0.0)}, "unknown"),
                  "code forged to fixture, flag 1.0": ({"subject_kind_code": M(2.0), "loss_check_exempt": M(1.0)}, "fixture"),
                  "code forged to fixture, flag deleted": ({"subject_kind_code": M(2.0)}, "fixture"),
                  "code deleted, flag 0.0": ({"loss_check_exempt": M(0.0)}, "unknown"),
                  "code deleted, flag deleted": ({}, "unknown")}
        for name, (extra, kind) in routes.items():
            rec = dataclasses.replace(j, metrics={**base, **extra})
            rv = bm.verdict_from_records(recs[:-1] + [rec], SMALL)
            self.assertEqual((rv.subject_kind, rv.joint), (kind, J.JOINT_SUPPORTED), name)    # accepted: documented


    def test_full_grid_matches_the_documented_rule(self):
        M, U = MetricValue.measured, MetricValue.unmeasured("x")
        codes = {"deleted": None, "unmeasured": U, "0": M(0.0), "1": M(1.0), "2": M(2.0), "7": M(7.0), "-1": M(-1.0)}
        flags = {"deleted": None, "unmeasured": U, "0": M(0.0), "1": M(1.0), "0.5": M(0.5), "2": M(2.0)}
        accepted = rejected = 0
        for base_name, base in (("fixture result", oracle()),
                                ("non-fixture result", bm.analyze_scores(synth_scores(FZ.seeds), frozen=FZ,
                                                                       registered_digest=FZ.digest, subject="s", cfg=SMALL))):
            recs = bm.to_experiment_records(base, study_id="f", base_seed=7, timestamp_utc=self.TS)
            j = recs[-1]
            clean = {k: v for k, v in j.metrics.items() if k not in ("subject_kind_code", "loss_check_exempt")}
            for cn, cv in codes.items():
                for fn, fv in flags.items():
                    extra = {}
                    if cv is not None:
                        extra["subject_kind_code"] = cv
                    if fv is not None:
                        extra["loss_check_exempt"] = fv
                    rec = dataclasses.replace(j, metrics={**clean, **extra})
                    decoded_fixture = cn == "2"
                    # the documented rule, written out independently of the implementation
                    want_accept = fn in ("deleted", "unmeasured", "0") or (fn == "1" and decoded_fixture)
                    try:
                        bm.verdict_from_records(recs[:-1] + [rec], SMALL)
                        got = True
                    except ValueError:
                        got = False
                    self.assertEqual(got, want_accept, (base_name, "code", cn, "flag", fn))
                    accepted += got
                    rejected += not got
        self.assertEqual((accepted, rejected), (44, 40))        # 22 / 20 per base result, two base results

    def test_docstring_states_the_exact_rule(self):
        doc = " ".join(bm.__doc__.split())
        for needle in ("22 accepted, 20 rejected",
                       "a record is accepted iff the flag is deleted, unmeasured or 0.0 (any code), or the flag is "
                       "1.0 and the decoded code is 'fixture' (2.0)",
                       "A relabel is caught only when the flag is 1.0 with a code other than 2.0, or when the flag is "
                       "malformed (measured but not 0.0 or 1.0, e.g. 0.5 or 2.0)"):
            self.assertIn(needle, doc)
        self.assertNotIn("Only a relabel that leaves the flag at 1.0 is caught", doc)

    def test_docstring_claims_are_text_pinned(self):
        doc = " ".join(bm.__doc__.split())
        for needle in ("(as is deleting both fields)", "flag 0.0 with an out-of-range code",
                       "forging the code to 'fixture' (2.0) with the flag at 1.0 or deleted",
                       "code deleted with flag 0.0", "producer-asserted, not authenticated"):
            self.assertIn(needle, doc)


class IntervalPairBoundsMustBeFiniteFloats(unittest.TestCase):
    """SR-13's re-attestation found that a forged non-finite bound bought a decisive SUPPORTED
    verdict, not merely an ugly interval. `IntervalPair.boot()`/`tint()` gated on `is_measured`,
    which is only `value is not None`, so `object.__setattr__(pair.boot_lo, "value", inf)` reached
    `interval_verdict` as a real number and `lo > margin` was trivially true. The dashboard fixed it
    at the renderer; this pins the root cause here, where every other consumer of these methods also
    benefits."""

    def _pair(self):
        return bm.summarize("S", [0.5 + 0.01 * i for i in range(30)], 0.9875, 200, 7)

    def test_a_forged_bound_cannot_produce_an_interval_or_a_verdict(self):
        bad = [math.inf, -math.inf, math.nan, 0, 1, True, False, "0", "", [], {}, None, object()]
        for v in bad:
            for attr in ("boot_lo", "boot_hi", "t_lo", "t_hi"):
                p = self._pair()
                self.assertIsNotNone(p.boot(), "the honest fixture must have a usable interval")
                object.__setattr__(getattr(p, attr), "value", v)
                which = p.boot() if attr.startswith("boot") else p.tint()
                self.assertIsNone(which, f"{attr}={v!r} must make the interval not computable")
                # and the verdict built from it must not be decisive
                verd = bm.interval_verdict(p, direction="greater", margin=0.1)[0]
                self.assertIsNot(verd, V.SUPPORTED, f"{attr}={v!r} bought a decisive verdict")

    def test_the_honest_path_is_unaffected(self):
        """The guard must not false-fire: a genuine fixture still yields both intervals and can
        still reach SUPPORTED, so this is not a fix that simply refuses everything."""
        p = self._pair()
        self.assertIsNotNone(p.boot())
        self.assertIsNotNone(p.tint())
        for iv in (p.boot(), p.tint()):
            self.assertTrue(all(isinstance(x, float) and math.isfinite(x) for x in iv))
        self.assertIs(bm.interval_verdict(p, direction="greater", margin=0.1)[0], V.SUPPORTED)
        # a genuine 0.0 bound is a measurement, not a forgery, and must survive
        p2 = self._pair()
        object.__setattr__(p2.boot_lo, "value", 0.0)
        self.assertEqual(p2.boot()[0], 0.0)

    def test_the_reason_is_recorded_where_the_next_reader_looks(self):
        doc = " ".join(bm.IntervalPair._bound.__doc__.split())
        self.assertIn("is only `value is not None`", doc)
        self.assertIn("decisive **SUPPORTED** with no figures behind it", doc)


class TIntervalAndBootstrapContracts(unittest.TestCase):
    def test_sum_vs_fsum_claim_is_stated_precisely(self):
        doc = " ".join(bm._sum_sq.__doc__.split())
        for needle in ("overflow-equivalent", "220k random trials on Python 3.12.4 ONLY", "not proven value-equivalent",
                       "below Python 3.12 the built-in sum is uncompensated"):
            self.assertIn(needle, doc)

    def test_t_interval_refuses_bad_elements_with_value_error(self):
        for bad in ([1.0, None, 2.0], [1.0, "2", 3.0], [1.0, [2.0], 3.0], [1.0, 2 + 3j, 3.0], [10 ** 400, 1],
                    [1.0, float("inf"), 2.0], [1.0, float("nan"), 2.0], [True, False], [1.0, b"x"]):
            with self.assertRaises(ValueError, msg=repr(bad)):
                bm.t_interval(bad, 0.95)

    def test_t_interval_still_correct(self):
        lo, hi = bm.t_interval([1, 2, 3, 4, 5], 0.95)
        self.assertAlmostEqual(lo, 1.036757, places=5)

    def test_bootstrap_rng_must_be_usable(self):
        for bad in (None, object(), 5, "rng"):
            with self.assertRaises(ValueError, msg=repr(bad)):
                bm.bootstrap_means([1.0, 2.0], 5, bad)
        self.assertEqual(len(bm.bootstrap_means([1.0, 2.0], 5, make_rng(1))), 5)
        with self.assertRaises(ValueError):
            bm.bootstrap_ci([1.0, 2.0], 0.95, 5, None)


class IneligibleVersusFailed(unittest.TestCase):
    """Defect 4: a TRAIN mask with < 2 rows is an ineligible seed (listed, replaced), not a failed run."""

    def degenerate_first_train_draw(self):
        orig, calls = bm._rows, {"n": 0}

        def fake(rng, n, width, want):
            if want is None:
                calls["n"] += 1
                if calls["n"] == 1:      # first replicate's TRAIN rows all outside the region
                    return tuple((-0.5, -0.1 * (i + 1), 0.2) for i in range(n))
            return orig(rng, n, width, want)
        return mock.patch.object(bm, "_rows", fake)

    def setUp(self):
        bm.build_fixture.cache_clear()

    def tearDown(self):
        bm.build_fixture.cache_clear()

    def test_listed_replaced_and_not_counted_as_failure(self):
        fz = bm.freeze_seed_list(7, 3, n_reserve=2)
        with self.degenerate_first_train_draw():
            r = bm.run_study(fz, bm.fixture_identity_uncond, subject="x", registered_digest=fz.digest, cfg=SMALL)
        self.assertEqual(r.ineligible, (fz.seeds[0],))
        self.assertEqual([s.seed for s in r.seed_scores], list(fz.seeds[1:4]))
        self.assertEqual((r.n_attempted, r.n_failed), (3, 0))
        self.assertTrue(next(g for g in r.gates if g.name == "failure_rate").passed)

    def test_score_seed_raises_ineligible_not_a_failed_record(self):
        with self.degenerate_first_train_draw():
            with self.assertRaises(bm.IneligibleSeed):
                bm.score_seed(FZ.seeds[0], bm.fixture_identity_uncond, SMALL)

    def test_mask_validation_is_outcome_independent(self):
        self.assertTrue(issubclass(bm.IneligibleSeed, ValueError))


class RecordsAndRecompute(unittest.TestCase):
    """Defect 5 and 3 (record schema): no verdict in notes; the verdict is recomputable from metrics."""
    TS = "2025-01-02T03:04:05Z"
    WORDS = ("SUPPORTED", "UNSUPPORTED", "INCONCLUSIVE", "safe")

    def recs(self, res):
        return bm.to_experiment_records(res, study_id="f", base_seed=7, timestamp_utc=self.TS, scorer_validation=True)

    def test_notes_carry_no_verdict_text(self):
        res = oracle()
        for rec in self.recs(res) + bm.seed_records(res, study_id="f", timestamp_utc=self.TS):
            for w in self.WORDS:
                self.assertNotIn(w, rec.notes.replace("not a safety finding", ""), rec.name)

    def test_recompute_matches_for_three_fixtures(self):
        for fac, name in ((bm.fixture_oracle_gated, "o"), (bm.fixture_global_degrader(0.5), "d"),
                          (bm.fixture_identity_uncond, "i")):
            res = oracle() if name == "o" else study(fac, name)
            rv = bm.verdict_from_records(self.recs(res), SMALL)
            self.assertEqual((rv.joint, rv.h1, rv.h2, rv.h3), (res.verdict, res.h1.verdict, res.h2.verdict, res.h3.verdict))

    def test_notes_text_is_ignored_by_recompute(self):
        res = study(bm.fixture_global_degrader(0.5), "d")
        evil = [dataclasses.replace(r, notes="verdict: JOINT_SUPPORTED; model is safe") for r in self.recs(res)]
        self.assertEqual(bm.verdict_from_records(evil, SMALL).joint, J.JOINT_UNSUPPORTED)

    def test_failed_or_missing_gate_in_records_forces_inconclusive(self):
        recs = self.recs(oracle())
        self.assertEqual(bm.verdict_from_records(recs, SMALL).joint, J.JOINT_SUPPORTED)
        j = next(r for r in recs if r.name.endswith("/JOINT"))
        for tamper in ({"gate_min_seeds": MetricValue.measured(0.0)},
                       {"gate_seed_list_frozen": MetricValue.unmeasured("not recorded")}):
            bad = dataclasses.replace(j, metrics={**j.metrics, **tamper})
            rv = bm.verdict_from_records([bad if r is j else r for r in recs], SMALL)
            self.assertEqual(rv.joint, J.JOINT_INCONCLUSIVE)
        # gate 12 failure recorded => H3 cannot be SUPPORTED
        bad = dataclasses.replace(j, metrics={**j.metrics, "gate_convergence": MetricValue.measured(0.0)})
        self.assertEqual(bm.verdict_from_records([bad if r is j else r for r in recs], SMALL).h3, V.INCONCLUSIVE)

    def test_recompute_requires_all_records_and_toy_result(self):
        recs = self.recs(oracle())
        with self.assertRaises(ValueError):
            bm.verdict_from_records([r for r in recs if not r.name.endswith("H3a_conv")], SMALL)
        unk = [dataclasses.replace(r, evidence_class=EvidenceClass.UNKNOWN) if r.name.endswith("/H1") else r
               for r in recs]
        with self.assertRaises(ValueError):
            bm.verdict_from_records(unk, SMALL)

    def test_record_schema_per_section_8a(self):
        res = oracle()
        sr = bm.seed_records(res, study_id="f", timestamp_utc=self.TS, prereg_hash="a" * 64, amendments_hash="b" * 64)
        self.assertTrue(all(r.name == "evalproto/f/oracle_gated" for r in sr))
        keys = set(sr[0].provenance.input_hashes)
        self.assertTrue({"prereg", "amendments", "seed_list", "config", "train_rows", "eval_T", "eval_U"} <= keys)
        self.assertEqual(sr[0].metrics["gate_finite"].value, 1.0)
        self.assertEqual(sr[0].metrics["gate_disjoint"].value, 1.0)
        for k in bm.SEED_METRICS:
            self.assertIn(k, sr[0].metrics)
        self.assertFalse(sr[0].metrics["E_loss_ratio"].is_measured)   # not a trained student: unmeasured, not 0
        self.assertNotIn("prereg", self.recs(res)[0].provenance.input_hashes)   # absent unless supplied

    def test_planned_slots_are_unknown_and_unmeasured(self):
        slots = bm.planned_slot_records(study_id="f", arms=["E", "C0"], seeds=list(FZ.seeds[:2]), timestamp_utc=self.TS)
        self.assertEqual(len(slots), 4)
        for r in slots:
            self.assertIs(r.evidence_class, EvidenceClass.UNKNOWN)
            self.assertTrue(all(not m.is_measured for m in r.metrics.values()))

    def test_direct_joint_result_refuses_empty_or_partial_gates(self):
        o = oracle()
        fields = {f.name: getattr(o, f.name) for f in dataclasses.fields(bm.JointResult)}
        for gates in ((), o.gates[:-1]):
            with self.assertRaises(ValueError):
                bm.JointResult(**{**fields, "gates": gates})
        with self.assertRaises(TypeError):
            bm.HypothesisResult("H1", o.h1.components, verdict=V.SUPPORTED)   # verdicts are derived, not supplied


if __name__ == "__main__":
    unittest.main()
