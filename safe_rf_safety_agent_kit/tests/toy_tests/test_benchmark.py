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
        return bm.analyze_scores(synth_scores(FZ.seeds, **kw), frozen=FZ, registered_digest=FZ.digest,
                                 subject="syn", cfg=SMALL, loss_check_exempt=exempt)

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
                               loss_check_exempt=True)
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
                self.assertNotIn(w, rec.notes.replace("not a safety claim", ""), rec.name)

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
