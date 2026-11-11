"""SR-10 tests for toy.benchmark: tests of the MEASURING INSTRUMENT on synthetic fixtures.

TOY ONLY. Every number produced here is a property of the scorer on a fixture whose answer is known by
construction (oracle / degrader / identity) or of hand-computed statistics. None is a result about the toy
method, and none says anything about RFdiffusion or any real model. The protocol's actual experiment (the
erasure arm E scored as a study) is deliberately NOT run here."""
import ast
import collections.abc
import copy
import dataclasses
import functools
import gc
import hashlib
import inspect
import itertools
import json
import math
import operator
import os
import pickle
import random
import sys
import unittest
from enum import Enum
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from toy import benchmark as bm
from toy import robustness as rb
from toy import schema as schema_mod
from unittest import mock

from toy.schema import (EvidenceClass, ExperimentRecord, MetricValue, RunProvenance, derive_seed,
                        make_rng)

V, J = bm.Verdict, bm.JointVerdict
SMALL = bm.BenchmarkConfig(n_boot=2000)          # smaller B only to keep the suite fast; the default is 10,000
FZ = bm.freeze_seed_list(7, 30)
TS_PROBE = "2000-01-01T00:00:00Z"
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

    # N3: the worst-seed converged-budget gradient ratio per base seed, MEASURED. The module docstring
    # quoted "1.1e-3..3.4e-3" for the gate-12 failure and 3.4e-3 WAS ATTAINED BY NOTHING; the range over
    # the two failing seeds is 1.0754e-3 .. 1.7810e-3. A doc-only mutant on that figure survived the whole
    # suite (its docstring-stripped AST was confirmed unchanged, so the mutant was valid) because NO TEST
    # READ THE FIGURE. This table is why it cannot survive again.
    GRAD_RATIO = {7: 5.136962118700918e-05, 11: 5.174835583488726e-05, 99: 0.0005277795431588699,
                  23: 0.0017809917284920913, 5: 0.0010753564206187154}

    def test_the_gate12_marginality_figures_are_the_measured_ones(self):
        """The ratio is recomputed from the stored per-seed metrics, not parsed out of the gate's reason
        string, so this pins the NUMBER and not its formatting. It does not depend on `n_boot` -- it comes
        from training, not from the bootstrap -- confirmed identical at n_boot 2000 and 500."""
        for base, want in self.GRAD_RATIO.items():
            with self.subTest(base_seed=base):
                r = self.run_for(base)
                worst = max(bm._metric_read(s.metrics["conv_grad_ratio"]) for s in r.seed_scores if s.ok)
                self.assertEqual(worst, want, f"base {base}: worst gradient ratio moved")
                failed = {g.name for g in r.gates if not g.passed}
                self.assertEqual("convergence" in failed, worst > 1e-3, base)
        failing = sorted(self.GRAD_RATIO[b] for b in (23, 5))
        self.assertEqual([f"{v:.3g}" for v in failing], ["0.00108", "0.00178"])
        self.assertEqual(max(self.GRAD_RATIO.values()), self.GRAD_RATIO[23])
        self.assertLess(max(self.GRAD_RATIO.values()), 3.4e-3)        # the retracted figure, unattained
        doc = " ".join(bm.__doc__.split())
        # The retracted figure may appear ONLY as an attributed correction, never as the docstring's own
        # measurement -- the convention `test_robustness` uses for a falsified claim.
        self.assertNotIn("gradient ratio 1.1e-3..3.4e-3 vs tau_conv", doc)
        self.assertIn('USED TO SAY "1.1e-3..3.4e-3"', doc)
        for needle in ("7 -> 5.137e-05", "11 -> 5.175e-05", "99 -> 5.278e-04", "23 -> 1.781e-03",
                       "5 -> 1.075e-03", "1.08e-3 .. 1.78e-3", "3.4e-3 IS ATTAINED BY NOTHING"):
            self.assertIn(needle, doc, needle)

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


# ====================================================================== SR-15 round 5
# FOUR rounds of this item, in order, because the SHAPE repeated and only the location moved:
#   (R2, dashboard) `_interval` gated on `is_measured` while `_metric_cell` checked the value --
#     fixed by a shared helper across a HAND-LISTED set of consumers;
#   (R3, dashboard) two consumers of `pair.n` disagreed and a forged `n` bought a decisive verdict:
#     the enumeration was ASSERTED, not performed;
#   (R3, benchmark) `IntervalPair._bound` closed the LEFT operand of `lo > margin` and left the RIGHT
#     one (the stored `margin`) on the identical `is_measured`-only gate;
#   (R4, benchmark) the list of CONSUMERS was replaced by a STATIC RULE OVER SPELLINGS -- and the list
#     of spellings is itself hand-maintained. MEASURED: it caught 2 of 19 spellings of the same read
#     and 17 evaded it, two of its own four `getattr`-form branches were DEAD CODE (`vars` takes no
#     second positional argument; `__getattribute__` is an `ast.Attribute`, never an `ast.Name`), and
#     `MetricValue.to_dict()` already returns `{"value": ...}` so no new code was even needed.
# THE LESSON, which is the point of this round: ENUMERATING SYNTAX CANNOT WORK FOR THIS. A new spelling
# defeats it, forever. The protection is therefore THREE OVERLAPPING PARTIAL LAYERS, and the load-bearing
# one is not a mechanism at all:
#   L1 RUNTIME RECORDING PROBE (`TheCheckedReaderIsTheOnlyWayToReadAStoredMetric`) -- hooks the carrier
#      and records the (reader function, attribute) pairs a REAL run actually touches. Catches any read
#      that goes through the type's attribute protocol, over the paths the run exercises. MEASURED BLIND
#      SPOTS, pinned in `test_the_probes_blind_spellings_are_pinned_by_measurement`: the base slot
#      (`object.__getattribute__`) and `gc`-level reflection, which bypass the type entirely; and any
#      branch the run does not reach. It is NOT spelling-agnostic and NOT path-complete.
#   L2 BEHAVIOURAL COVERAGE PER READ SITE (`EveryReadSiteIsPinnedByItsConsequence` here and
#      `EveryMetricReadSiteIsPinnedByItsConsequence` in test_robustness.py) -- forge the metric behind
#      each site and assert the VERDICT and the REASONS TUPLE. THIS IS THE LAYER THAT ACTUALLY PROTECTS:
#      it depends on neither spelling nor path, so a site covered this way dies however the read is
#      written, including through the routes L1 is blind to. The sites that survived a reroute to a fully
#      unchecked read survived precisely because nothing asserted their consequence.
#   L3 THE STATIC SPELLING RULE (`TheStaticSpellingRuleIsATripwireNotAGuarantee`), dead branches fixed,
#      kept only as a cheap tripwire over code no run reaches. Its coverage is MEASURED, not claimed.
# Every one of the four rounds was missed by a test that checked an INTERMEDIATE and never asked what was
# concluded, which is why L2 and not L1 is where this round put the weight.
_SRC_FILES = {"benchmark": Path(bm.__file__), "robustness": Path(bm.__file__).with_name("robustness.py")}

_OWNED_FILES = {str(p.resolve()): name for name, p in _SRC_FILES.items()}
_SCHEMA_FILE = str(Path(schema_mod.__file__).resolve())
_STDLIB_DIR = os.path.dirname(os.__file__)
_ANON_CODE = {"<listcomp>", "<setcomp>", "<dictcomp>", "<genexpr>", "<lambda>"}

# EVERY (module, function, attribute) triple by which `benchmark.py` or `robustness.py` touches a stored
# `MetricValue`, MEASURED by the probe below during a real study, a real recompute and the real SR-11
# probes -- not listed from reading the source. Compared with set equality in BOTH directions, so an
# added consumer fails naming itself and a reader that stopped reading fails as a rotted entry.
_DECLARED_METRIC_TOUCHES = {
    ("benchmark", "_metric_read", "value"),                  # THE checked reader
    ("benchmark", "_metric_declared_unmeasured", "value"),   # honest-absence seam
    ("benchmark", "_metric_declared_unmeasured", "reason"),
    ("benchmark", "_metric_required", "__repr__"),           # names the offending metric in its ValueError
    ("benchmark", "_metric_strict", "__repr__"),             # ditto
    ("robustness", "arm_difference", "reason"),              # quotes an absent arm's stated reason
    ("robustness", "benchmark_outcome.<locals>.outcome", "reason"),       # ditto, for a probe outcome
    ("robustness", "Scorecard.to_dict", "to_dict"),          # delegates serialisation to the carrier
}
# Attribute names a declared reader may NOT use, pinned so the probe's own NON-VACUITY is provable: these
# are the routes round 4's static rule could not see, and the probe reports them by not seeing them.
_FORBIDDEN_TOUCHES = ("__dict__", "__dataclass_fields__", "__getattribute__", "__class__", "is_measured",
                      "__reduce_ex__", "__format__")


def _owning_reader(depth):
    """(module, qualified function) of the OWNED code that performed the current read, or None.

    THE ATTRIBUTION RULE, clause by clause, because the probe is only as good as this function:
      * the frame is in `benchmark.py` / `robustness.py`  -> THAT function is the reader;
      * the frame is in `toy/schema.py`                   -> the carrier's OWN internal read
        (construction, `is_measured`, `render`, `to_dict`). SR-04 owns and attests those. A read made by
        an owned module THROUGH one of them is still seen, as a read of the METHOD attribute by the owned
        frame -- which is why the probe records every attribute name and not just two;
      * the frame is a dataclass-generated method (`co_filename == "<string>"`) -> likewise the carrier's;
      * the frame is in the standard library              -> a TRAMPOLINE (`dataclasses.asdict`,
        `dataclasses.astuple`, `functools.partial`, `copy`), so walk up and attribute to the first
        non-stdlib frame. This is what makes `dataclasses.asdict(m)["value"]` written inside
        `benchmark.py` attributable to `benchmark.py` instead of to `dataclasses.py`;
      * anything else (this test file, `dashboard.py`, a caller-supplied callback) -> NOT an owned read,
        and ignored. The rule under test is about these two modules, and `dashboard.py` has its own probe.
    A comprehension or lambda frame is resolved to its enclosing named function (`co_name` is `<listcomp>`
    on interpreters that do not inline them), so the table does not depend on PEP 709."""
    f = sys._getframe(depth)
    while f is not None:
        fn = f.f_code.co_filename
        if fn in _OWNED_FILES:
            g, name = f, getattr(f.f_code, "co_qualname", f.f_code.co_name)
            while g.f_code.co_name in _ANON_CODE and g.f_back is not None \
                    and g.f_back.f_code.co_filename == fn:
                g = g.f_back
                name = getattr(g.f_code, "co_qualname", g.f_code.co_name)
            return (_OWNED_FILES[fn], name)
        if fn == _SCHEMA_FILE or not fn.startswith(_STDLIB_DIR):
            return None
        f = f.f_back
    return None


class recording_metric_reads:
    """Context manager: record every way `benchmark.py` / `robustness.py` touches a `MetricValue`.

    The hooks go on `MetricValue` ITSELF, not on a `__class__`-swapped subclass as `toy.dashboard`'s probe
    does, and the difference is deliberate: the objects whose reads matter here DO NOT EXIST when the probe
    starts. They are created inside the study, the serialisation, the recompute and the SR-11 probes, so
    there is nothing to swap a class on. A class-level hook covers every instance created inside the
    window, wherever it is created, while `isinstance`, the dataclass `__eq__`/`__hash__` and the frozen
    semantics are all untouched -- so the code under probe takes exactly its real path.
    `__repr__` and `__format__` are hooked as well as `__getattribute__`, because `repr(m)` and `f"{m}"`
    look the method up on the TYPE: `float(repr(m).split("value=")[1].split(",")[0])` reads a forged
    number with no instance attribute access at all, and it was the only one of 19 ordinary spellings that
    evaded a `__getattribute__`-only hook. Stringifying a metric is legitimate inside an error message, so
    it is not forbidden -- it is DECLARED like every other touch.
    TWO DESIGN CHOICES THAT ARE LOAD-BEARING, and the reason this probe is not simply `toy.dashboard`'s
    copied over (the dashboard's, measured verbatim, is blind to both of these):
      * EVERY ATTRIBUTE NAME IS RECORDED, with no filter. The dashboard's probe keeps only names whose
        value `is_a_stored_number`, which DISCARDS `__dict__` -- so `vars(x)["value"]` and
        `x.__dict__["value"]` leave it with an empty bucket. Here they are recorded as reads of
        `__dict__`, which `_FORBIDDEN_TOUCHES` then refuses. Same for `__getstate__`, `__reduce_ex__`
        and `to_dict`.
      * THE TABLE IS KEYED BY (module, READER FUNCTION, attribute), not by attribute. A set of attribute
        names makes a SECOND consumer of an ALREADY-DECLARED number invisible by construction, which is
        exactly the `pair.n` defect of round 3. Keyed by reader, a second consumer appears as a new triple.
    WHAT IT STILL CANNOT SEE, measured and pinned, not described: `object.__getattribute__(m, "value")`,
    `object.__getattribute__(m, "__dict__")["value"]` and `gc.get_referents(m)` bypass
    `type(m).__getattribute__` altogether, so no hook on the type can observe them. That is the same class
    as the `object.__setattr__` route this module's threat model already lists (route (b)): a deliberate
    bypass of the type's own protocol, not a spelling a consumer writes by accident. And the probe sees
    only the paths its run exercises. Those two limits are why layer 2 exists."""

    HOOKS = ("__getattribute__", "__repr__", "__format__")

    def __enter__(self):
        self.seen = set()
        self.saved = {n: MetricValue.__dict__.get(n, _ABSENT) for n in self.HOOKS}
        orig = {n: getattr(MetricValue, n) for n in self.HOOKS}
        seen = self.seen

        def hooked_getattribute(obj, name):
            who = _owning_reader(2)
            if who is not None:
                seen.add(who + (name,))
            return orig["__getattribute__"](obj, name)

        def hooked_repr(obj):
            who = _owning_reader(2)
            if who is not None:
                seen.add(who + ("__repr__",))
            return orig["__repr__"](obj)

        def hooked_format(obj, spec):
            who = _owning_reader(2)
            if who is not None:
                seen.add(who + ("__format__",))
            return orig["__format__"](obj, spec)

        MetricValue.__getattribute__ = hooked_getattribute
        MetricValue.__repr__ = hooked_repr
        MetricValue.__format__ = hooked_format
        return self

    def __exit__(self, *exc):
        for name, value in self.saved.items():
            if value is _ABSENT:
                delattr(MetricValue, name)
            else:
                setattr(MetricValue, name, value)
        return False


_ABSENT = object()


def forge(mv, value):
    """Install `value` into a built `MetricValue` -- route (b) of the module's own threat model."""
    object.__setattr__(mv, "value", value)
    return mv


# 19 spellings of ONE read: `m.value` on a metric forged to 1e9. Each is compiled with benchmark.py's own
# `co_filename` (see `_run_sneak`), so it is code "in benchmark.py" as far as any tool can tell. The
# second column of the measurement that drove this round -- round 4's STATIC rule caught S0 and S1 only.
SNEAK_SPELLINGS = [
    ("S0  plain attribute", "def _sneak(m):\n    return m.value\n"),
    ("S1  getattr literal", "def _sneak(m):\n    return getattr(m, 'value')\n"),
    ("S2  getattr concatenated", "def _sneak(m):\n    return getattr(m, 'val' + 'ue')\n"),
    ("S3  module-level name", "_F = 'value'\ndef _sneak(m):\n    return getattr(m, _F)\n"),
    ("S4  __dict__.get", "def _sneak(m):\n    return m.__dict__.get('value')\n"),
    ("S5  vars().get", "def _sneak(m):\n    return vars(m).get('value')\n"),
    ("S6  dataclasses.asdict", "def _sneak(m):\n    return dataclasses.asdict(m).get('value')\n"),
    ("S7  operator.attrgetter", "def _sneak(m):\n    return operator.attrgetter('value')(m)\n"),
    ("S8  itemgetter over vars", "def _sneak(m):\n    return operator.itemgetter('value')(vars(m))\n"),
    ("S9  destructuring", "def _sneak(m):\n    v, _r = dataclasses.astuple(m)\n    return v\n"),
    ("S10 comprehension", "def _sneak(m):\n    return [x.value for x in (m,)][0]\n"),
    ("S11 module-level lambda", "_peek = lambda m: m.value\ndef _sneak(m):\n    return _peek(m)\n"),
    ("S12 nested function", "def _sneak(m):\n    def inner(x):\n        return x.value\n    return inner(m)\n"),
    ("S13 method on a new class",
     "class _Peeker:\n    def peek(self, m):\n        return m.value\ndef _sneak(m):\n    return _Peeker().peek(m)\n"),
    ("S14 functools.partial",
     "def _peek(name, m):\n    return getattr(m, name)\ndef _sneak(m):\n    return functools.partial(_peek, 'value')(m)\n"),
    ("S15 m.__getattribute__", "def _sneak(m):\n    return m.__getattribute__('value')\n"),
    ("S16 to_dict, the schema contract", "def _sneak(m):\n    return m.to_dict()['value']\n"),
    ("S17 repr parsing, no attribute read at all",
     "def _sneak(m):\n    return float(repr(m).split('value=')[1].split(',')[0])\n"),
    ("S18 is_measured gate", "def _sneak(m):\n    return m.is_measured\n"),
]

# The ones that WIN against the probe, measured. All three bypass `type(m).__getattribute__` entirely.
SNEAK_BLIND_SPELLINGS = [
    ("B1 object.__getattribute__", "def _sneak(m):\n    return object.__getattribute__(m, 'value')\n"),
    ("B2 object.__getattribute__ for __dict__",
     "def _sneak(m):\n    return object.__getattribute__(m, '__dict__')['value']\n"),
    # `gc` reaches the instance's own storage. Two shapes, both handled, because CPython 3.11+ gives a
    # dataclass instance a MANAGED dict: until something materialises it, `get_referents` hands back the
    # field VALUES in declaration order (`[value, reason, type]`); afterwards it hands back the dict. The
    # first form was missed on a first measurement because an earlier `copy.copy` in the same process had
    # already materialised the dict -- a reminder that a probe measurement is itself order-sensitive.
    ("B3 gc.get_referents",
     "def _sneak(m):\n    r = gc.get_referents(m)[0]\n    return r['value'] if isinstance(r, dict) else r\n"),
]


def probe_run():
    """ONE REAL EXERCISE of both modules. Deliberately NOT a synthetic `MetricValue` fixture: the defect
    class is "a consumer somewhere in the pipeline reads a stored metric for itself", and a fixture only
    exercises the consumers the fixture's author thought of. Every call below is a public entry point.

    It covers, and has to cover, every declared read site -- the table is compared in both directions, so
    a site this run does not reach fails as "declared but NOT read" and the run has to be extended."""
    res = study(bm.fixture_global_degrader(0.5), "d")
    recs = bm.to_experiment_records(res, study_id="p", base_seed=7, timestamp_utc=TS_PROBE)
    bm.verdict_from_records(recs, SMALL)
    bm.seed_records(res, study_id="p", timestamp_utc=TS_PROBE)
    for r in recs:                                   # a real serialisation round-trip
        ExperimentRecord.from_json(r.to_json())
    failing = synth_scores(FZ.seeds, loss=0.9, gr=1.0)        # gates 11(c) and 12 genuinely fail
    bm.evaluate_gates(failing, FZ, FZ.digest, SMALL)
    res2 = bm.analyze_scores(failing, frozen=FZ, registered_digest=FZ.digest, subject="s", cfg=SMALL)
    bm.verdict_from_records(bm.to_experiment_records(res2, study_id="q", base_seed=7,
                                                     timestamp_utc=TS_PROBE), SMALL)
    orecs = bm.to_experiment_records(oracle(), study_id="o", base_seed=7, timestamp_utc=TS_PROBE)
    bm.verdict_from_records(orecs, SMALL)                     # the exempt / fixture decode path
    j = orecs[-1]
    for flag in (MetricValue.unmeasured("not recorded by this producer"),   # honestly absent: accepted
                 forge(MetricValue.measured(1.0), math.inf)):               # malformed: must raise
        try:
            bm.verdict_from_records(orecs[:-1] + [dataclasses.replace(
                j, metrics={**j.metrics, "loss_check_exempt": flag})], SMALL)
        except ValueError:
            pass
    for key in ("margin", "n_seeds"):                # the ValueError paths, which NAME the metric
        broken = {**recs[0].metrics, key: MetricValue.unmeasured("nope")}
        try:
            bm.verdict_from_records([dataclasses.replace(recs[0], metrics=broken)] + recs[1:], SMALL)
        except ValueError:
            pass
    # ---- SR-11: the real probes, both the summarized and the insufficient branch, and a real scorecard
    cfg = rb.ProbeConfig(3)
    card = rb.seed_sensitivity_probe(lambda s: float(s % 7), (1, 2, 3, 4, 5), cfg)
    card.to_dict()
    card.content_hash()
    rb.scorecard_to_record(card, run_id="r1", timestamp_utc=TS_PROBE)
    insuf = rb.seed_sensitivity_probe(lambda s: 1.0 if s < 2 else math.nan, (1, 2, 3, 4, 5), cfg)
    rb.scorecard_to_record(insuf, run_id="r2", timestamp_utc=TS_PROBE)
    insuf.to_dict()
    rb.summarize_seeds([MetricValue.measured(float(i)) for i in range(5)], 3)
    rb.arm_difference({"C0": MetricValue.measured(0.0), "E": MetricValue.measured(1.0)}, "E", "C0")
    rb.arm_difference({"C0": MetricValue.measured(0.0), "E": MetricValue.unmeasured("x")}, "E", "C0")
    rb.probe_missing_inputs(rb.mse_fsum, (1, 2, 3, 4, 5), cfg)
    rb.probe_shift(rb.mse_fsum, rb.shift_reorder_rows(), (1, 2, 3, 4, 5), cfg)
    rb.probe_shift(rb.mse_fsum, rb.shift_scale(2.0), (1, 2, 3, 4, 5), cfg)
    rb.probe_precision("cancellation", 1e8, (1, 2, 3, 4, 5), cfg)
    rb.precision_sweep("cancellation", (1e6, 1e8), (1, 2, 3, 4, 5), cfg)
    tiny = bm.BenchmarkConfig(steps=20, steps_conv=25, n_boot=50, n_train=16, n_eval=16)
    deg = bm.fixture_global_degrader(0.5)
    rb.seed_sensitivity_probe(rb.benchmark_outcome(deg, "S", tiny), (1, 2, 3), cfg)
    # ... and an UNMEASURED metric, so `benchmark_outcome` reaches its reason-quoting branch
    rb.seed_sensitivity_probe(rb.benchmark_outcome(deg, "E_loss_ratio", tiny), (1, 2, 3), cfg)


class TheCheckedReaderIsTheOnlyWayToReadAStoredMetric(unittest.TestCase):
    """THE ROUND-5 MECHANISM: a RUNTIME RECORDING PROBE, replacing round 4's static rule over spellings.

    Round 4 asserted that "a new consumer physically cannot read a stored metric without going through
    `_metric_read` and having the suite stay green". THAT CLAIM WAS FALSE and is withdrawn. It rested on an
    AST walk for `ast.Attribute` nodes named `value`/`is_measured` and `ast.Call` nodes named
    `getattr`/`setattr`/`vars`/`__getattribute__`; measured against 19 spellings of the same read it caught
    2 and 17 evaded, and two of its own four call-form branches were unreachable. The list of spellings a
    static rule must enumerate is itself hand-maintained, which is the exact failure mode of rounds 2 and 3
    one level of indirection up.

    A runtime probe hooks the OBJECT rather than the source text, so it does not have to guess at
    spellings: `recording_metric_reads` installs a recording `__getattribute__` (plus `__repr__` /
    `__format__`) on `MetricValue` itself; `probe_run` performs a real study, a real serialisation
    round-trip, three real recomputes, a genuinely failing-gate study and the real SR-11 probes; and
    `_owning_reader` attributes each read to the function in `benchmark.py` or `robustness.py` that
    performed it, through a stdlib trampoline if there was one. The observed set is compared with
    `_DECLARED_METRIC_TOUCHES` by set equality in BOTH directions.

    WHAT THIS IS NOT, stated first and in these words because the previous round's OVERCLAIM is the reason
    this round exists, and because the sentence "a probe sees the read however it is spelled" is FALSE:
      * IT IS NOT SPELLING-AGNOSTIC. `object.__getattribute__(m, "value")`,
        `object.__getattribute__(m, "__dict__")["value"]` and `gc.get_referents(m)` reach the value
        without going through `type(m).__getattribute__`, so no hook on the type can see them. MEASURED
        and pinned in `test_the_probes_blind_spellings_are_pinned_by_measurement`. (`vars(m)["value"]`,
        `m.__dict__["value"]`, `dataclasses.asdict`, `attrgetter`, a built string, a comprehension, a
        lambda and `to_dict()` ARE all seen -- see `recording_metric_reads` for the two design choices
        that buy that, both of which `toy.dashboard`'s probe lacks.)
      * IT IS NOT PATH-COMPLETE. It sees only what `probe_run` exercises, demonstrated in
        `test_the_probes_known_weakness_is_demonstrated_not_asserted`.
    So this class is layer 1 of three and is NOT the guarantee. The layer that protects is layer 2,
    `EveryReadSiteIsPinnedByItsConsequence` here and `EveryMetricReadSiteIsPinnedByItsConsequence` in
    `test_robustness.py`: forge the metric, assert the verdict and the reasons tuple. That one depends on
    neither spelling nor path, so it covers the routes above as well. Layer 3 is the static rule, kept as
    a tripwire with its coverage measured. No layer is a guarantee and none of them is described as one."""

    def test_the_reads_are_observed_at_runtime_not_enumerated_from_the_source(self):
        with recording_metric_reads() as rec:
            probe_run()
        read, declared = rec.seen, _DECLARED_METRIC_TOUCHES
        self.assertEqual(read, declared, f"""
The ways benchmark.py / robustness.py actually touched a stored MetricValue do not match the declared table.
  observed but NOT declared : {sorted(read - declared)}
  declared but NOT observed : {sorted(declared - read)}
An observed-but-undeclared touch is an UNCHECKED CONSUMER -- the defect of four rounds running. Read the
number through _metric_read / _metric_ok / _metric_required / _metric_count / _metric_strict; an Enum
payload through robustness._enum_value. A declared-but-unobserved touch means either the table has rotted
(delete the entry) or probe_run no longer reaches that site (extend probe_run: a site the probe does not
reach is a site the probe does not check).""")

    def test_the_probe_is_not_vacuous_it_does_not_see_reads_that_do_not_happen(self):
        """If the hooks were not really observing the run, the test above would pass by seeing nothing.
        So: the reads that DO happen are pinned by value, and the routes round 4's rule was blind to are
        pinned as ABSENT -- the day one appears, the probe reports it instead of a reviewer noticing.
        This is `toy.dashboard`'s `test_the_probe_itself_is_not_vacuous` applied to the carrier."""
        with recording_metric_reads() as rec:
            probe_run()
        seen = rec.seen
        self.assertIn(("benchmark", "_metric_read", "value"), seen)          # it really did observe
        self.assertGreaterEqual(len(seen), 8)
        for attr in _FORBIDDEN_TOUCHES:
            offenders = sorted(t for t in seen if t[2] == attr)
            self.assertEqual(offenders, [], f"a stored metric was reached through {attr!r}: {offenders}")
        # no function OTHER than the declared readers touches `value` or `reason` at all
        self.assertEqual(sorted({t[:2] for t in seen if t[2] in ("value", "reason")}),
                         [("benchmark", "_metric_declared_unmeasured"), ("benchmark", "_metric_read"),
                          ("robustness", "arm_difference"),
                          ("robustness", "benchmark_outcome.<locals>.outcome")])
        # and the hooks are gone afterwards: the probe cannot leak into another test
        self.assertNotIn("__getattribute__", MetricValue.__dict__)
        self.assertNotIn("__format__", MetricValue.__dict__)
        self.assertEqual(repr(MetricValue.measured(1.0)), "MetricValue(value=1.0, reason=None)")

    def _run_sneak(self, src):
        """Compile `src` WITH `co_filename` SET TO benchmark.py and run it under the probe.

        That is what makes the result mean something: to the probe's attribution rule, to `inspect`, to a
        traceback and to the static rule's own `ast.parse` of the file, the function is indistinguishable
        from code written in `benchmark.py`. The forged metric carries 1e9, which `_metric_read` refuses,
        so "the spelling reached the value" is checkable."""
        ns = {"dataclasses": dataclasses, "operator": operator, "functools": functools, "gc": gc,
              "copy": copy, "pickle": pickle, "MetricValue": MetricValue}
        exec(compile(src, str(_SRC_FILES["benchmark"].resolve()), "exec"), ns)
        with recording_metric_reads() as rec:
            try:
                got = ns["_sneak"](forge(MetricValue.measured(1.0), 1e9))
            except Exception as e:                     # a spelling that cannot even run is not a route
                got = e
        return sorted(rec.seen), got

    def test_the_probe_catches_the_ordinary_spellings_of_an_unchecked_read(self):
        """CAN THE MECHANISM BE FOOLED? Measured, against 19 spellings of the same forged read.
        All 19 are caught, where round 4's static rule caught 2 of them. The list includes
        `m.to_dict()["value"]`, which needs no new code at all -- `MetricValue.to_dict` already returns
        `{"value": ..., "reason": ...}` and is a SERIALISATION CONTRACT, so it cannot be removed -- and it
        is caught as a read of the `to_dict` attribute. It also includes `vars(m)["value"]` and
        `m.__dict__["value"]`, which are caught ONLY because this probe records every attribute name
        instead of filtering the bucket to stored numbers; `toy.dashboard`'s probe, measured verbatim, is
        blind to both. `test_the_probes_blind_spellings_are_pinned_by_measurement` has the ones that win."""
        results = {label: self._run_sneak(src) for label, src in SNEAK_SPELLINGS}
        evaded = sorted(k for k, (seen, _) in results.items() if not seen)
        self.assertEqual(evaded, [], f"spellings the probe did not see: {evaded}")
        for label, (triples, got) in results.items():
            # the spelling really did reach the forged number, so none of them is a straw man ...
            self.assertIn(got, (1e9, True), f"{label} did not reach the forged value: {got!r}")
            # ... and it is attributed to the SNEAKING function, never laundered onto a declared reader
            for _, fn, _ in triples:
                self.assertNotIn(fn, ("_metric_read", "_metric_declared_unmeasured"), (label, fn))
                self.assertTrue(fn.startswith(("_sneak", "_peek", "_other", "_Peeker")), (label, fn))
            self.assertNotIn(triples[0], _DECLARED_METRIC_TOUCHES, label)
        self.assertEqual(len(SNEAK_SPELLINGS), 19)

    def test_a_second_consumer_of_an_ALREADY_DECLARED_number_is_still_caught(self):
        """The failure mode a probe that compares ATTRIBUTE SETS has by construction, and the reason this
        table is keyed by (module, reader function, attribute): `value` is already declared -- read by
        `_metric_read` -- so a set of attribute names cannot distinguish a second, unchecked consumer of
        it from the first. That is the `pair.n` defect of round 3 ("two consumers that disagreed")
        reappearing inside the fix for it. Keyed by reader, the second consumer is a new triple."""
        triples, got = self._run_sneak("def _other_consumer(m):\n    return getattr(m, 'value')\n"
                                       "def _sneak(m):\n    return _other_consumer(m)\n")
        self.assertEqual(triples, [("benchmark", "_other_consumer", "value")])
        self.assertEqual(got, 1e9)
        self.assertIn(("benchmark", "_metric_read", "value"), _DECLARED_METRIC_TOUCHES)   # same attribute
        self.assertNotIn(("benchmark", "_other_consumer", "value"), _DECLARED_METRIC_TOUCHES)

    def test_the_probes_blind_spellings_are_pinned_by_measurement(self):
        """THE PROBE'S REAL LIMIT, measured and pinned rather than described -- and pinned as a FAILING
        case, so that if a future interpreter or a future hook does start seeing one of these, this test
        fails and the limit is re-measured instead of being carried forward as folklore.

        All three reach the forged value without going through `type(m).__getattribute__`, which is the
        only thing a hook on the type can intercept. They are the same class as the `object.__setattr__`
        route `toy.benchmark`'s own threat model lists as route (b): a deliberate bypass of the type's
        protocol, not something a consumer writes by accident. They are covered by layer 2 -- a forged
        metric reaching a verdict is caught by the consequence test whatever syntax read it."""
        for label, src in SNEAK_BLIND_SPELLINGS:
            triples, got = self._run_sneak(src)
            self.assertEqual(triples, [], f"{label}: the probe DID see this; update the measured limit")
            self.assertEqual(got, 1e9, f"{label} did not reach the forged value: {got!r}")
        self.assertEqual(len(SNEAK_BLIND_SPELLINGS), 3)

    def test_the_probes_known_weakness_is_demonstrated_not_asserted(self):
        """THE HONEST LIMIT, measured rather than described: a read on a path `probe_run` does not
        exercise is INVISIBLE to the probe. Here the identical sneaking read sits in a function that is
        defined (with benchmark.py's own `co_filename`) and never called, and the probe reports nothing.
        That is not a bug in the probe; it is the reason the static tripwire and the per-site consequence
        tests exist, and the reason neither this class nor any docstring may call the probe a guarantee."""
        ns = {}
        exec(compile("def _never_called(m):\n    return m.value\n",
                     str(_SRC_FILES["benchmark"].resolve()), "exec"), ns)
        with recording_metric_reads() as rec:
            probe_run()
        self.assertEqual(sorted(t for t in rec.seen if t[1] == "_never_called"), [])
        # and it IS a real read: calling it is seen at once, so the blindness is to the PATH, not the code
        with recording_metric_reads() as rec2:
            ns["_never_called"](MetricValue.measured(1.0))
        self.assertEqual(sorted(rec2.seen), [("benchmark", "_never_called", "value")])

    def test_the_readers_agree_with_metricvalues_own_construction_rule(self):
        """Not vacuous, and not over-refusing: `_metric_read` accepts exactly what `MetricValue`
        accepts at construction, and refuses exactly what only `object.__setattr__` can install."""
        for good in (0.0, -0.0, 5e-324, -5e-324, 1.7976931348623157e308, -1.0, 0.1):
            mv = MetricValue.measured(good)
            self.assertEqual(bm._metric_read(mv), mv.value, repr(good))
            self.assertTrue(bm._metric_ok(mv), repr(good))
            self.assertEqual(bm._metric_required(mv, "x"), mv.value)
        for bad in (math.inf, -math.inf, math.nan, 0, 1, -3, True, False, "0", "", "nan", [], [0.1], {},
                    (), None, object(), 10**400, bytearray(b"1")):
            mv = MetricValue.measured(1.0)
            object.__setattr__(mv, "value", bad)
            self.assertIsNone(bm._metric_read(mv), repr(bad))
            self.assertFalse(bm._metric_ok(mv), repr(bad))
            with self.assertRaises(ValueError, msg=repr(bad)):
                bm._metric_required(mv, "x")
            with self.assertRaises(ValueError, msg=repr(bad)):
                bm._metric_count(mv, "x")
            with self.assertRaises(ValueError, msg=repr(bad)):   # forged, not honestly absent
                bm._metric_strict(mv, "x")
        self.assertIsNone(bm._metric_read(None))
        self.assertIsNone(bm._metric_read(object()))
        # the honest-absence seam `_metric_strict` turns on
        unm = MetricValue.unmeasured("why")
        self.assertTrue(bm._metric_declared_unmeasured(unm))
        self.assertIsNone(bm._metric_strict(unm, "x"))
        self.assertIsNone(bm._metric_strict(None, "x"))
        self.assertFalse(bm._metric_declared_unmeasured(None))
        self.assertFalse(bm._metric_declared_unmeasured(MetricValue.measured(1.0)))
        # counts: integral and nonnegative, and `True` is not 1
        self.assertEqual(bm._metric_count(MetricValue.measured(30.0), "x"), 30)
        for bad in (30.5, -1.0, -0.5):
            with self.assertRaises(ValueError, msg=repr(bad)):
                bm._metric_count(MetricValue.measured(bad), "x")

    def test_enum_value_is_not_a_back_door_to_a_metric(self):
        from toy import robustness as rb_
        self.assertEqual(rb_._enum_value(bm.Verdict.SUPPORTED), "SUPPORTED")
        for not_an_enum in (MetricValue.measured(1.0), MetricValue.unmeasured("x"), 1.0, None, object()):
            with self.assertRaises(ValueError, msg=repr(not_an_enum)):
                rb_._enum_value(not_an_enum)


# The ONLY functions allowed to reach a `value` / `is_measured` field by a SYNTACTIC spelling the static
# tripwire below recognises. It names the READERS, not the reads; the reads are derived from the source.
_DECLARED_READERS = {"_metric_read", "_metric_declared_unmeasured", "_enum_value"}


def _attribute_reads(src):
    """Every `<expr>.value` / `<expr>.is_measured` attribute access in `src`, as (lineno, text)."""
    return sorted((n.lineno, ast.unparse(n)) for n in ast.walk(ast.parse(src))
                  if isinstance(n, ast.Attribute) and n.attr in ("value", "is_measured"))


def _getattr_reads(src):
    """Every CALL that names `value` / `is_measured` as a string argument, as (enclosing function, text).

    THE TWO DEAD BRANCHES THIS FIXES, found by the round-4 review inside round 4's own fix:
      * `vars` was in the call-name list with `len(n.args) > 1`. `vars` TAKES NO SECOND POSITIONAL
        ARGUMENT, so that branch could never match anything. `vars(x)["value"]` -- the actual spelling --
        is a `Subscript` over a `Call`, which the rule never looked at. Now matched.
      * `__getattribute__` was in the same `isinstance(n.func, ast.Name)` list. `m.__getattribute__(...)`
        parses as a `Call` whose `func` is an `ast.Attribute`, never an `ast.Name`, so that branch was
        equally unreachable. Both forms are now matched.
    Also matched now: a subscript of any of these calls (`vars(m)["value"]`, `asdict(m)["value"]`,
    `m.to_dict()["value"]`) and `attrgetter`/`itemgetter`. NOT matched, and the reason this is a tripwire
    and not a rule: a built string (`'val' + 'ue'`), a name bound elsewhere, destructuring, and every
    read that does not spell the word at the call site at all."""
    tree = ast.parse(src)
    owner = {}
    for fn in ast.walk(tree):
        if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for sub in ast.walk(fn):
                owner.setdefault(id(sub), fn.name)
    names = ("getattr", "setattr", "delattr", "vars", "__getattribute__", "to_dict", "asdict", "astuple",
             "attrgetter", "itemgetter")
    out = []
    for n in ast.walk(tree):
        if not isinstance(n, ast.Call):
            continue
        fname = n.func.id if isinstance(n.func, ast.Name) else getattr(n.func, "attr", None)
        if fname not in names:
            continue
        args = [a.value for a in n.args if isinstance(a, ast.Constant)]
        subs = [p.slice.value for p in ast.walk(tree)
                if isinstance(p, ast.Subscript) and p.value is n and isinstance(p.slice, ast.Constant)]
        if any(v in ("value", "is_measured") for v in args + subs):
            out.append((owner.get(id(n), "<module>"), ast.unparse(n)))
    return sorted(out)


class TheStaticSpellingRuleIsATripwireNotAGuarantee(unittest.TestCase):
    """LAYER 3: round 4's static rule, dead branches repaired, demoted to what it actually is.

    Round 4 built this and called it a guarantee: "a new consumer physically cannot read a stored metric
    without going through `_metric_read` and having the suite stay green." IT IS NOT A GUARANTEE, and the
    test below MEASURES how far short it falls instead of leaving a reader to trust the sentence. What it
    is good for is the one thing the runtime probe cannot do: it reads code that NO RUN EXECUTES. A plain
    `m.value` added to a branch `probe_run` never reaches is invisible to layer 1 and caught here. So the
    two are kept together, with their coverage stated, and neither is described as sufficient."""

    def test_no_attribute_access_named_value_or_is_measured_exists_in_either_module(self):
        for name, path in _SRC_FILES.items():
            found = _attribute_reads(path.read_text())
            self.assertEqual(found, [], f"{name}.py has {len(found)} unchecked metric reads: {found}; "
                                        "read stored metrics with _metric_read / _metric_ok / "
                                        "_metric_required / _metric_count / _metric_strict, and an Enum "
                                        "payload with robustness._enum_value")

    def test_the_call_spelling_is_confined_to_the_three_declared_readers(self):
        seen = set()
        for name, path in _SRC_FILES.items():
            for fn, text in _getattr_reads(path.read_text()):
                self.assertIn(fn, _DECLARED_READERS, f"{name}.py: {text} in {fn}() reaches a stored "
                                                     "metric outside the declared readers")
                seen.add(fn)
        self.assertEqual(seen, _DECLARED_READERS,
                         "a declared reader no longer contains such an access: the list is stale, which "
                         "would silently widen the rule")
        self.assertEqual(len(_DECLARED_READERS), 3)
        for fn in ("_metric_read", "_metric_declared_unmeasured"):
            self.assertTrue(callable(getattr(bm, fn)), fn)
        self.assertTrue(callable(rb._enum_value))

    def test_the_two_dead_branches_are_now_live(self):
        """Round 4's rule listed four call names and TWO OF THEM COULD NEVER MATCH: `vars` takes no second
        positional argument, and `__getattribute__` is an `ast.Attribute`. Both now match, and the test
        fails if either stops mattering."""
        self.assertEqual([t for _, t in _getattr_reads("def f(m):\n    return vars(m)['value']\n")],
                         ["vars(m)"])
        self.assertEqual([t for _, t in _getattr_reads("def f(m):\n    return m.__getattribute__('value')\n")],
                         ["m.__getattribute__('value')"])
        self.assertEqual([t for _, t in _getattr_reads("def f(m):\n    return m.to_dict()['value']\n")],
                         ["m.to_dict()"])
        # the old rule's shape, for contrast: these two produced nothing at all
        old = [n for n in ast.walk(ast.parse("def f(m):\n    return vars(m)['value']\n"))
               if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
               and n.func.id in ("getattr", "setattr", "vars", "__getattribute__") and len(n.args) > 1]
        self.assertEqual(old, [])

    def test_how_little_the_static_rule_catches_is_MEASURED_not_claimed(self):
        """THE NUMBER THAT REPLACES THE WORD "GUARANTEE". Each of the 19 spellings the runtime probe sees
        is run past BOTH halves of the static rule. MEASURED: the repaired rule catches 11 of 19 and 8
        evade it; round 4's SHIPPED rule caught 2. So a docstring calling it a guarantee is false by 8
        counterexamples, which is why this class is named what it is named.
        The 8 are NOT then chased by adding more call names to the rule, and that is deliberate: every
        name added is another hand-maintained entry, which is the defect this round exists to stop
        repeating. They are covered by layers 1 and 2, which do not depend on the spelling."""
        caught = []
        for label, src in SNEAK_SPELLINGS:
            if _attribute_reads(src) or [x for x in _getattr_reads(src) if x[0] not in _DECLARED_READERS]:
                caught.append(label)
        self.assertEqual(len(caught), 11, caught)
        self.assertEqual(len(SNEAK_SPELLINGS) - len(caught), 8)
        for evades in ("S2  getattr concatenated", "S3  module-level name", "S4  __dict__.get",
                       "S5  vars().get", "S6  dataclasses.asdict", "S9  destructuring",
                       "S14 functools.partial", "S17 repr parsing, no attribute read at all"):
            self.assertNotIn(evades, caught)
        # all 8 are seen by the runtime probe; that asymmetry is the whole argument for layer 1 over 3
        self.assertEqual(len(SNEAK_SPELLINGS), 19)
        # ... and every one of the 12 is caught by layer 1 or layer 2 instead; see
        # TheCheckedReaderIsTheOnlyWayToReadAStoredMetric and EveryReadSiteIsPinnedByItsConsequence.

    def test_the_withdrawn_guarantee_is_not_reinstated_anywhere_in_either_module(self):
        """THE OVERCLAIM ITSELF, pinned as source TEXT and not as a docstring, because the sentence that
        had to go was in a COMMENT -- so `__doc__` cannot see it and a doc-only mutant that put it back
        SURVIVED this suite on its first measurement. The single worst recurring defect in this project is
        a guard whose documentation overstates it; this test is the only thing in the suite that reads the
        prose where that happens."""
        forbidden = ("physically cannot read a stored metric",
                     "cannot add one and have the suite stay green",
                     "a new consumer physically cannot")
        for name, path in _SRC_FILES.items():
            src = path.read_text()
            low = src.lower()
            for phrase in forbidden:
                self.assertNotIn(phrase.lower(), low,
                                 f"{name}.py reinstates the withdrawn guarantee: {phrase!r}. The static "
                                 f"rule catches 11 of 19 spellings; the probe is blind to "
                                 f"object.__getattribute__ and to unexercised paths. Neither is a "
                                 f"guarantee and neither may be described as one.")
        # ... and the retraction, plus the three-layer description, IS where a reader looks
        bsrc = _SRC_FILES["benchmark"].read_text()
        for needle in ("THAT CLAIM WAS FALSE", "2 of 17 spellings of the same read were caught",
                       "Two of that rule's four `getattr`-form branches were DEAD",
                       "as a cheap tripwire -- not as a guarantee",
                       "it sees\n# only what the run it performs exercises"):
            self.assertIn(needle, bsrc, needle)
        rdoc = " ".join(rb._enum_value.__doc__.split())
        self.assertIn("it is a tripwire, not a guarantee, and this docstring used to describe it as one",
                      rdoc)
        self.assertIn("MEASURED 11 of 19 spellings", rdoc)

    def test_the_tripwire_can_fail_and_says_where(self):
        """THE PIN'S OWN PROOF: both halves are run against deliberately mutated source text, so this
        class cannot be the kind of test that passes because it never looks at anything."""
        src = _SRC_FILES["benchmark"].read_text()
        # ANCHOR NOTE: the margin is read out of `rm`, the `_word_keyed`-admitted copy of
        # `r.metrics`, not out of `r.metrics` directly -- see `benchmark._word_keyed`. The mutation
        # is the same one (drop the checked reader, read `.value` off the stored object); only the
        # mapping it is spelled against moved.
        reinstated = src.replace("        mg = _metric_required(rm[\"margin\"], f\"{tag}: margin\")",
                                 "        mg = rm[\"margin\"].value", 1)
        self.assertNotEqual(reinstated, src, "the anchor for the mutation is gone; update this test")
        ast.parse(reinstated)
        self.assertEqual([t for _, t in _attribute_reads(reinstated)], ["rm['margin'].value"])
        dodged = src.replace("def _check_margin(v: Any, what: str) -> float:",
                             "def _sneak(m):\n    return getattr(m, 'value', None)\n\n\n"
                             "def _check_margin(v: Any, what: str) -> float:", 1)
        ast.parse(dodged)
        self.assertIn(("_sneak", "getattr(m, 'value', None)"), _getattr_reads(dodged))
        self.assertNotIn("_sneak", _DECLARED_READERS)
        # and the mutation the tripwire CANNOT see, stated as a test so the limit is on the record
        evasive = src.replace("def _check_margin(v: Any, what: str) -> float:",
                              "def _sneak(m):\n    return getattr(m, 'val' + 'ue', None)\n\n\n"
                              "def _check_margin(v: Any, what: str) -> float:", 1)
        ast.parse(evasive)
        self.assertEqual(_attribute_reads(evasive), [])
        self.assertEqual([x for x in _getattr_reads(evasive) if x[0] not in _DECLARED_READERS], [])


class EveryReadSiteIsPinnedByItsConsequence(unittest.TestCase):
    """LAYER 2, AND THE LAYER THAT ACTUALLY PROTECTS: one test per stored-metric read site in
    `benchmark.py`, each forging the metric BEHIND that site and asserting the VERDICT and the REASONS
    TUPLE -- never an intermediate.

    WHY THIS IS THE LOAD-BEARING LAYER and not the probe. A reroute experiment replaced each read site in
    turn with a fully unchecked read and ran the whole suite: the sites that stayed GREEN were exactly the
    sites where no test asserted the CONSEQUENCE of the read. A consequence test does not care how the
    read is spelled, so it covers the three spellings the runtime probe is blind to
    (`object.__getattribute__`, `gc`) and the branches the probe's run does not reach. A spelling rule
    covers neither. Four rounds of this item were all missed by a test that checked an intermediate.

    THE THREE SITES A REVIEW OFFERED TO LET THROUGH AS "genuinely equivalent over the public API" are
    NOT accepted on that argument, because the argument turned out to be unnecessary: each of them is
    checked, and the check is asserted here by consequence like every other site. An equivalence argument
    about who can call what is a PROVENANCE argument, and this module has already shipped one of those
    offered as a validity argument."""

    FORGED = (math.inf, -math.inf, math.nan, True, False, 0, 1, "1.0", "", [1.0], {}, None, object())

    def test_B_seedscores_ok_a_forged_primary_metric_cannot_buy_a_verdict(self):
        """SeedScores.ok, the site whose reroute ESCALATED: with only the primary series forged to `inf`
        on 3 of 40 seeds and every gate input honest, an unchecked read took the study from
        JOINT_INCONCLUSIVE to JOINT_SUPPORTED, `n_failed` from 3 to 0, the failed-gate list from
        ['failure_rate'] to [] and left `reasons = ()`. All five consequences are asserted."""
        fz = bm.freeze_seed_list(7, 40)
        cfg = dataclasses.replace(SMALL, min_seeds=30)
        honest = bm.analyze_scores(synth_scores(fz.seeds), frozen=fz, registered_digest=fz.digest,
                                   subject="x", cfg=cfg, subject_kind="fixture", fixture_name="f")
        self.assertIs(honest.verdict, J.JOINT_SUPPORTED)          # the control: it CAN say yes
        self.assertEqual((honest.n_attempted, honest.n_failed), (40, 0))
        self.assertEqual([g.name for g in honest.gates if not g.passed], [])
        self.assertEqual(honest.h1.components[0].pair.n, 40)
        for bad in self.FORGED:
            scores = synth_scores(fz.seeds)
            for s in scores[:3]:
                for k in ("S", "L", "delta", "delta_minus_shuf"):
                    forge(s.metrics[k], bad)
            res = bm.analyze_scores(scores, frozen=fz, registered_digest=fz.digest, subject="x", cfg=cfg,
                                    subject_kind="fixture", fixture_name="f")
            why = repr(bad)
            self.assertIs(res.verdict, J.JOINT_INCONCLUSIVE, why)
            self.assertEqual((res.n_attempted, res.n_failed), (40, 3), why)
            self.assertEqual([g.name for g in res.gates if not g.passed], ["failure_rate"], why)
            self.assertEqual((res.h1.verdict, res.h2.verdict, res.h3.verdict),
                             (V.INCONCLUSIVE,) * 3, why)
            self.assertIn("gate failed: failure_rate", res.h1.reasons[0], why)
            # B-series, the same forgery seen at the other read site: the three seeds leave the SERIES,
            # so the component is measured on 37 and not on 40 silently including three forged numbers
            self.assertEqual(res.h1.components[0].pair.n, 37, why)
            # ... and the recompute from the stored records agrees, with no reason recorded
            recs = bm.to_experiment_records(res, study_id="f", base_seed=7, timestamp_utc=TS_PROBE)
            rv = bm.verdict_from_records(recs, cfg)
            self.assertEqual((rv.joint, rv.h1, rv.h2, rv.h3, rv.reasons),
                             (J.JOINT_INCONCLUSIVE,) + (V.INCONCLUSIVE,) * 3 + ((),), why)

    def test_B_series_each_primary_series_is_read_independently(self):
        """`analyze_scores`'s series comprehension reads every key through the same checked reader. Forging
        ONE key must drop those seeds from EVERY series (a seed with an unusable primary metric is not an
        OK seed at all), which is what makes `SeedScores.ok` and this site agree -- the round-3 defect was
        two consumers of one number that did NOT agree."""
        fz = bm.freeze_seed_list(7, 40)
        cfg = dataclasses.replace(SMALL, min_seeds=30)
        scores = synth_scores(fz.seeds)
        for s in scores[:5]:
            forge(s.metrics["delta"], math.inf)          # H3's series only
        res = bm.analyze_scores(scores, frozen=fz, registered_digest=fz.digest, subject="x", cfg=cfg,
                                subject_kind="fixture", fixture_name="f")
        self.assertEqual([c.pair.n for c in res.h1.components], [35])
        self.assertEqual([c.pair.n for c in res.h3.components], [35, 35])
        self.assertEqual(res.n_failed, 5)
        self.assertIs(res.verdict, J.JOINT_INCONCLUSIVE)
        self.assertEqual([g.name for g in res.gates if not g.passed], ["failure_rate"])

    def test_B_record_ec_a_forged_mean_downgrades_the_record_and_the_recompute_refuses_it(self):
        """`to_experiment_records` labels a component UNKNOWN when its mean is not a usable number, and
        `verdict_from_records` refuses a non-TOY_RESULT record. An unchecked read would label a record
        carrying a forged `inf` mean TOY_RESULT and recompute a verdict from it."""
        honest = bm.to_experiment_records(oracle(), study_id="g", base_seed=7, timestamp_utc=TS_PROBE)
        self.assertEqual({r.evidence_class for r in honest}, {EvidenceClass.TOY_RESULT})
        self.assertIs(bm.verdict_from_records(honest, SMALL).joint, J.JOINT_SUPPORTED)
        for bad in self.FORGED:
            res = study(bm.fixture_oracle_gated, "o2")
            forge(res.h1.components[0].pair.mean, bad)
            recs = bm.to_experiment_records(res, study_id="g", base_seed=7, timestamp_utc=TS_PROBE)
            got = [r.evidence_class for r in recs if r.name.endswith("/H1")]
            self.assertEqual(got, [EvidenceClass.UNKNOWN], repr(bad))
            with self.assertRaisesRegex(ValueError, "only TOY_RESULT records", msg=repr(bad)):
                bm.verdict_from_records(recs, SMALL)

    def test_B_subject_code_a_forged_subject_kind_code_cannot_relabel_a_result(self):
        """The decode is `code == SUBJECT_KIND_CODE[k]`, so an unchecked read of `True` decodes as
        'trained' (`True == 1.0`) and of `2` as 'fixture'. Asserted on BOTH shapes of study: one that
        claims the exemption (must raise) and one that does not (must not silently become a fixture)."""
        self.assertEqual(bm.SUBJECT_KIND_CODE, {"unknown": 0.0, "trained": 1.0, "fixture": 2.0})
        exempt = bm.to_experiment_records(oracle(), study_id="g", base_seed=7, timestamp_utc=TS_PROBE)
        self.assertEqual(bm.verdict_from_records(exempt, SMALL).subject_kind, "fixture")
        for bad in self.FORGED + (2, 2.0000001, -2.0):
            recs = [dataclasses.replace(r, metrics={**r.metrics, "subject_kind_code":
                                                    forge(MetricValue.measured(1.0), bad)})
                    if r.name.endswith("/JOINT") else r for r in exempt]
            with self.assertRaises(ValueError, msg=repr(bad)):     # the exemption no longer decodes
                bm.verdict_from_records(recs, SMALL)
        # and on a study that claims nothing, a forged code must not manufacture a kind
        plain = bm.analyze_scores(synth_scores(FZ.seeds), frozen=FZ, registered_digest=FZ.digest,
                                  subject="s", cfg=SMALL, subject_kind="unknown")
        precs = bm.to_experiment_records(plain, study_id="h", base_seed=7, timestamp_utc=TS_PROBE)
        base = bm.verdict_from_records(precs, SMALL)
        self.assertEqual(base.subject_kind, "unknown")
        for bad in (math.inf, math.nan, True, "2.0", None, [2.0], 7.0):
            recs = [dataclasses.replace(r, metrics={**r.metrics, "subject_kind_code":
                                                    forge(MetricValue.measured(1.0), bad)})
                    if r.name.endswith("/JOINT") else r for r in precs]
            rv = bm.verdict_from_records(recs, SMALL)
            # the forged code buys NO relabel: not 'fixture' (which would waive gate 11(c)) and not
            # 'trained' (which a bare `True == 1.0` would have produced), and the verdict does not move
            self.assertEqual(rv.subject_kind, "unknown", repr(bad))
            self.assertEqual((rv.joint, rv.h1, rv.h2, rv.h3, rv.reasons),
                             (base.joint, base.h1, base.h2, base.h3, ()), repr(bad))

    def test_B_exempt_flag_a_malformed_exemption_flag_always_raises(self):
        """`loss_check_exempt` goes through `_metric_strict`, not `_metric_read`: for a CROSS-CHECK field
        "unreadable" is evidence of tampering and must not be laundered into "not recorded". The honest
        unmeasured state must still be accepted, or the fix would be an over-refusal."""
        exempt = bm.to_experiment_records(oracle(), study_id="g", base_seed=7, timestamp_utc=TS_PROBE)
        j = exempt[-1]

        def with_flag(mv):
            return exempt[:-1] + [dataclasses.replace(j, metrics={**j.metrics, "loss_check_exempt": mv})]
        for bad in self.FORGED[:5] + ("1.0", [1.0], 0.5, 2.0, -1.0):
            with self.assertRaises(ValueError, msg=repr(bad)):
                bm.verdict_from_records(with_flag(forge(MetricValue.measured(1.0), bad)), SMALL)
        # honestly unmeasured: accepted, the exemption simply is not claimed, and nothing is concluded
        rv = bm.verdict_from_records(with_flag(MetricValue.unmeasured("not recorded")), SMALL)
        self.assertEqual((rv.joint, rv.reasons), (J.JOINT_SUPPORTED, ()))
        self.assertEqual(rv.subject_kind, "fixture")
        self.assertIs(bm.verdict_from_records(exempt, SMALL).joint, J.JOINT_SUPPORTED)   # not vacuous

    def test_B_pair_ci_level_is_CHECKED_not_merely_equivalent(self):
        """A review offered this site as "genuinely equivalent over the public API" because
        `_pair_from_record`'s only caller validates `ci_level` first. THE ARGUMENT IS NOT NEEDED and is
        therefore not accepted: `_pair_from_record` reads `ci_level` through `_metric_required` itself, so
        a forged level raises on the DIRECT call too, and a legal-but-wrong level is caught by the
        adjusted-level cross-check. Both are asserted, so the site does not depend on who calls it."""
        recs = bm.to_experiment_records(oracle(), study_id="g", base_seed=7, timestamp_utc=TS_PROBE)
        h1 = [r for r in recs if r.name.endswith("/H1")][0]
        rest = [r for r in recs if not r.name.endswith("/H1")]
        for bad in self.FORGED:
            r = dataclasses.replace(h1, metrics={**h1.metrics,
                                                 "ci_level": forge(MetricValue.measured(1.0), bad)})
            with self.assertRaises(ValueError, msg=repr(bad)):
                bm._pair_from_record(r)                       # the DIRECT call, with no caller to help
            with self.assertRaises(ValueError, msg=repr(bad)):
                bm.verdict_from_records([r] + rest, SMALL)
        # a LEGAL level that is not the adjusted one: the cross-check, asserted by consequence
        r = dataclasses.replace(h1, metrics={**h1.metrics, "ci_level": MetricValue.measured(0.5)})
        self.assertEqual(bm._pair_from_record(r).level, 0.5)
        with self.assertRaisesRegex(ValueError, "is not the adjusted level"):
            bm.verdict_from_records([r] + rest, SMALL)
        self.assertIs(bm.verdict_from_records(recs, SMALL).joint, J.JOINT_SUPPORTED)     # not vacuous

    def test_B_score_seed_and_converged_deltas_fail_closed_under_interposition(self):
        """The other two sites a review offered as equivalent, on the ground that they read an `ArmScores`
        built one statement earlier so no caller can interpose. Again the argument is not needed: the
        consequence is asserted under an interposition STRONGER than any caller can perform -- patching
        `score_predictor` so the `ArmScores` arrives already forged. The derived contrasts must come out
        UNMEASURED WITH A REASON, and the seed must stop being an OK seed, which is what keeps the forged
        number out of every series and out of every verdict."""
        tiny = bm.BenchmarkConfig(steps=20, steps_conv=25, n_boot=50, n_train=16, n_eval=16)
        real = bm.score_predictor
        honest = bm.score_seed(1, bm.fixture_global_degrader(0.5), tiny)
        self.assertTrue(honest.ok)
        for key in ("delta_minus_shuf", "delta_conv", "delta_minus_shuf_conv"):
            self.assertTrue(bm._metric_ok(honest.metrics[key]), key)
        for bad in (math.inf, math.nan, True, "1.0", None, [1.0]):
            def forging(fx, pred, c0, g_min=0.0, _r=real, _b=bad):
                a = _r(fx, pred, c0, g_min)
                forge(a.delta, _b)
                return a
            with mock.patch.object(bm, "score_predictor", forging):
                s = bm.score_seed(1, bm.fixture_global_degrader(0.5), tiny)
            self.assertFalse(s.ok, repr(bad))
            for key in ("delta_minus_shuf", "delta_conv", "delta_minus_shuf_conv"):
                self.assertFalse(bm._metric_ok(s.metrics[key]), (key, repr(bad)))
                self.assertTrue(bm._metric_declared_unmeasured(s.metrics[key]), (key, repr(bad)))
            self.assertEqual(s.metrics["delta_minus_shuf"].reason,
                             "treatment or C_shuf contrast unmeasured", repr(bad))
            self.assertEqual(s.metrics["delta_conv"].reason, "converged contrast unmeasured", repr(bad))


class TheCrossChecksFailClosedAndTheFlagsSurviveAsFarAsTheyCan(unittest.TestCase):
    """Two items raised by the SR-13 owner while building the same cross-check on its side.

    (1) THE n CROSS-CHECK WAS FAIL-OPEN ON AN ABSENT SECOND SOURCE. `joint_n = ... if "n_seeds" in gm
    else None` and then `if joint_n is not None and ...` meant deleting ONE dict entry silently skipped
    the check -- in the one guard whose stated purpose is that "n must be CHECKED against something, not
    trusted". Defensible-by-default is what every round of this item has been, so it is now DECIDED: it
    fails closed, on the grounds that `to_experiment_records` writes `n_seeds` into every JOINT record and
    that `verdict_from_records` already raises for every other missing required metric.

    (2) `_pair_from_record` DROPPED `flags`, so a roundtripped below-minimum pair lost the producer's own
    "n below protocol minimum". The two n-derived flags are now RECOMPUTED from the stored `n_seeds` and
    the bound `cfg.min_seeds`; the two value-derived ones are not recoverable and are deliberately not
    faked. Both directions are asserted below, so SR-13 can use the biconditional."""

    def recs(self, **cfg_kw):
        cfg = dataclasses.replace(SMALL, **cfg_kw) if cfg_kw else SMALL
        res = bm.analyze_scores(synth_scores(FZ.seeds), frozen=FZ, registered_digest=FZ.digest,
                                subject="s", cfg=cfg, subject_kind="fixture", fixture_name="f")
        return bm.to_experiment_records(res, study_id="x", base_seed=7, timestamp_utc=TS_PROBE), cfg

    def test_an_absent_joint_n_seeds_now_fails_closed(self):
        recs, cfg = self.recs()
        self.assertIs(bm.verdict_from_records(recs, cfg).joint, J.JOINT_SUPPORTED)   # the control
        j = recs[-1]
        self.assertIn("n_seeds", j.metrics, "to_experiment_records stopped writing the second source")
        stripped = {k: v for k, v in j.metrics.items() if k != "n_seeds"}
        with self.assertRaisesRegex(ValueError, "no n_seeds metric"):
            bm.verdict_from_records(recs[:-1] + [dataclasses.replace(j, metrics=stripped)], cfg)
        # and a forged n_seeds is still caught when the source IS there (the check itself still works)
        for n in (1e9, 31.0, 1e300):
            forged = [dataclasses.replace(r, metrics={**r.metrics,
                                                      "n_seeds": MetricValue.measured(n)})
                      if r.name.endswith("/H1") else r for r in recs]
            with self.assertRaisesRegex(ValueError, "exceeds the study", msg=repr(n)):
                bm.verdict_from_records(forged, cfg)

    def test_the_n_derived_flags_survive_the_record_roundtrip_in_both_directions(self):
        """`flag present <=> n < min_n`, the form SR-13 wanted and could not previously have."""
        recs, cfg = self.recs(min_seeds=5)                 # 30 measured seeds, minimum 5
        h1 = [r for r in recs if r.name.endswith("/H1")][0]
        self.assertEqual(bm._pair_from_record(h1, cfg.min_seeds).n, 30)
        self.assertNotIn("n below protocol minimum", bm._pair_from_record(h1, cfg.min_seeds).flags)
        # <= : a minimum above n puts the flag on, at every value of the minimum
        for mn in (31, 50, 10 ** 6, 10 ** 6 + 1, 2_000_000, 10 ** 12):
            p = bm._pair_from_record(h1, mn)
            self.assertIn("n below protocol minimum", p.flags, mn)
            self.assertEqual(p.n, 30, mn)
        # => : at or below n the flag is off, at every value
        for mn in (0, 1, 5, 20, 29, 30):
            self.assertNotIn("n below protocol minimum", bm._pair_from_record(h1, mn).flags, mn)
        # the n<20 flag needs no minimum at all, so it is always derived
        small, scfg = self.recs(min_seeds=5)
        few = dataclasses.replace(
            [r for r in small if r.name.endswith("/H1")][0],
            metrics={**[r for r in small if r.name.endswith("/H1")][0].metrics,
                     "n_seeds": MetricValue.measured(7.0)})
        self.assertEqual(bm._pair_from_record(few).flags, ("percentile bootstrap unreliable (n < 20)",))
        self.assertEqual(bm._pair_from_record(few, 30).flags,
                         ("n below protocol minimum", "percentile bootstrap unreliable (n < 20)"))
        # with no minimum supplied the min_n flag CANNOT be derived, and is absent rather than guessed
        self.assertEqual(bm._pair_from_record(h1).flags, ())

    def test_the_flags_that_cannot_be_recovered_are_not_faked(self):
        """A roundtripped flags tuple is a SUBSET of the producer's, never a superset and never a
        different one. "degenerate: all values tied" and "heavy tail" need the raw per-seed values; the
        module says so rather than reconstructing the producer's prose from a stored number."""
        tied = bm.summarize("S", [2.0] * 30, bm.bonferroni_level(0.05, 4), 200, 7, min_n=30)
        self.assertIn("degenerate: all values tied", tied.flags)
        heavy = bm.summarize("S", [0.01] * 29 + [50.0], bm.bonferroni_level(0.05, 4), 200, 7, min_n=30)
        self.assertTrue(any(f.startswith("heavy tail") for f in heavy.flags))
        for pair in (tied, heavy):
            rec = ExperimentRecord(
                name="evalproto/x/agg/H1",
                provenance=RunProvenance(run_id="r", timestamp_utc=TS_PROBE, seed=7,
                                         code_version="v", python_version="3.12.4", toy_only=True,
                                         input_hashes={}),
                metrics=bm._agg_metrics(pair, 0.1, 0, "fixture"), evidence_class=EvidenceClass.TOY_RESULT)
            back = bm._pair_from_record(rec, 30)
            self.assertTrue(set(back.flags) <= set(pair.flags), (pair.flags, back.flags))
            self.assertNotIn("degenerate: all values tied", back.flags)
            self.assertFalse(any(f.startswith("heavy tail") for f in back.flags), back.flags)
        doc = " ".join(bm._pair_from_record.__doc__.split())
        for needle in ("it cannot be RESTORED", "Reconstructing prose is not carrying evidence",
                       "a SUBSET of the producer's, never a superset"):
            self.assertIn(needle, doc, needle)

    def test_flags_influence_no_verdict_which_is_why_the_recompute_does_not_need_them(self):
        """THE MEASURED REASON `verdict_from_records` does NOT pass `cfg.min_seeds` to
        `_pair_from_record`. A first draft of the flags fix did, and a mutant that removed the argument
        SURVIVED the whole suite -- correctly, because the recomputed flags are unobservable there:
        nothing in this module's verdict logic reads `flags` (its only other use is
        `to_experiment_records` writing it into `notes`, which is not evidence) and `RecomputedVerdict`
        carries no pair. Rather than pin dead code, the argument was removed and the PROPERTY that makes
        it dead is pinned instead -- the same discipline that removed the duplicate `_admitted` check in
        SR-13: a guard whose removal changes no output is not a guard.
        The n-below-minimum FACT still reaches the verdict, by the route that always carried it."""
        # MEASURED, by owner rather than by line number so it cannot rot: `flags` is read in exactly one
        # place in the module, and that place writes it into free-text `notes`.
        tree = ast.parse(Path(bm.__file__).read_text())
        owner = {}
        for fn in ast.walk(tree):
            if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for sub in ast.walk(fn):
                    owner.setdefault(id(sub), fn.name)
        readers = sorted({owner.get(id(n), "<module>") for n in ast.walk(tree)
                          if isinstance(n, ast.Attribute) and n.attr == "flags"})
        self.assertEqual(readers, ["to_experiment_records"],
                         "a second consumer of IntervalPair.flags appeared; the dropped argument in "
                         "verdict_from_records may now be observable and this reasoning must be redone")
        pair = bm.summarize("S", [0.5 + 0.01 * i for i in range(30)], bm.bonferroni_level(0.05, 4), 200, 7)
        self.assertEqual(pair.flags, ())
        flagged = dataclasses.replace(pair, flags=("n below protocol minimum", "anything at all"))
        self.assertEqual(bm.interval_verdict(pair, 0.1, "greater"),
                         bm.interval_verdict(flagged, 0.1, "greater"))
        self.assertEqual(bm.ComponentResult("S", "greater", 0.1, pair).verdict,
                         bm.ComponentResult("S", "greater", 0.1, flagged).verdict)
        self.assertEqual(bm.ComponentResult("S", "greater", 0.1, pair).reason,
                         bm.ComponentResult("S", "greater", 0.1, flagged).reason)
        # the route that DOES carry it: n vs min_n inside _verdict_from_bounds, both directions
        self.assertIs(bm.interval_verdict(pair, 0.1, "greater", min_n=30)[0], V.SUPPORTED)
        v, why = bm.interval_verdict(pair, 0.1, "greater", min_n=31)
        self.assertIs(v, V.INCONCLUSIVE)
        self.assertEqual(why, "n=30 below protocol minimum 31: no verdict")

    def test_the_declared_input_RANGE_is_swept_not_just_the_default(self):
        """THE SR-13 OWNER'S GENERALISATION, applied here: an unexercised branch is only invisible while
        no test exercises the INPUT RANGE that selects it, and the input ranges are enumerable from the
        declared parameters even when the branches are not. `min_seeds` and `width_tol` are declared
        `BenchmarkConfig` fields whose stricter direction has a well-defined honest outcome, so each is
        swept across its range with the VERDICT and the REASONS TUPLE asserted -- which is cheaper and
        more durable than a mechanism, and covers branches no probe run reaches.
        Every recompute is run with the cfg the study ran under, so the config-hash binding holds and a
        reason would mean the binding fired rather than the parameter."""
        for mn in (5, 29, 30, 31, 50, 10 ** 6, 10 ** 6 + 1, 2_000_000, 10 ** 12):
            recs, cfg = self.recs(min_seeds=mn)
            rv = bm.verdict_from_records(recs, cfg)
            want = J.JOINT_SUPPORTED if mn <= 30 else J.JOINT_INCONCLUSIVE
            self.assertIs(rv.joint, want, f"min_seeds={mn}")
            self.assertEqual(rv.reasons, (), f"min_seeds={mn}")        # not the binding failing closed
            if mn > 30:
                self.assertEqual((rv.h1, rv.h2, rv.h3), (V.INCONCLUSIVE,) * 3, f"min_seeds={mn}")
                # and the min-seeds GATE names it, so the page cannot show a bare INCONCLUSIVE
                res = bm.analyze_scores(synth_scores(FZ.seeds), frozen=FZ, registered_digest=FZ.digest,
                                        subject="s", cfg=cfg, subject_kind="fixture", fixture_name="f")
                self.assertIn("min_seeds", [g.name for g in res.gates if not g.passed], mn)
                self.assertIn("gate failed: min_seeds", res.h1.reasons[0], mn)
        for wt in (0.0, 0.01, 0.25, 1.0, 10.0, 10 ** 6, 10 ** 12):
            recs, cfg = self.recs(width_tol=wt)
            rv = bm.verdict_from_records(recs, cfg)
            self.assertEqual(rv.reasons, (), f"width_tol={wt}")
            self.assertIn(rv.joint, (J.JOINT_SUPPORTED, J.JOINT_INCONCLUSIVE), f"width_tol={wt}")
            # a tolerance of 0 can only ever make a component LESS decisive, never more
            if wt == 0.0:
                self.assertIsNot(rv.joint, J.JOINT_UNSUPPORTED, "width_tol=0 invented an UNSUPPORTED")

    def unbalanced(self, n_total=32, n_conv=25, min_seeds=10):
        """A study whose CONVERGED-budget series is measured on fewer seeds than the primary series.

        `synth_scores` measures every series on every seed, which is why the sweep above cannot tell
        `cfg.min_seeds` from the constant 30: with n == 30 everywhere, `min_seeds <= 30` is decisive and
        `min_seeds > 30` fails the min-seeds GATE first, so the gate's state supplies the answer the
        component floor was supposed to supply. Here the primary series have n=32 and the two
        converged-budget series n=25, so the component floor is observable on its own."""
        fz = bm.freeze_seed_list(7, n_total)
        cfg = dataclasses.replace(SMALL, min_seeds=min_seeds)
        r = random.Random(5)
        g = lambda m, sd=0.05: m + r.gauss(0, sd)
        scores = []
        for i, s in enumerate(fz.seeds):
            conv = i < n_conv
            scores.append(bm.SeedScores.from_values(
                s, g(1.0), g(-0.01, 0.005), g(1.0), g(1.0), A=g(0.5, 0.01), F=0.005, E_loss_ratio=0.01,
                delta_conv=g(1.0) if conv else None,
                delta_minus_shuf_conv=g(1.0) if conv else None,
                conv_grad_ratio=1e-5, rowsets_disjoint=True, mask_ok=True))
        res = bm.analyze_scores(scores, frozen=fz, registered_digest=fz.digest, subject="s", cfg=cfg,
                                subject_kind="fixture", fixture_name="f")
        return bm.to_experiment_records(res, study_id="x", base_seed=7, timestamp_utc=TS_PROBE), cfg, res

    def test_the_component_floor_is_the_configured_minimum_not_a_constant_and_not_the_gate(self):
        """THE FIXTURE THE SWEEP ABOVE WAS MISSING, and the reason it was worth building: hardcoding
        `cfg.min_seeds -> 30` at `verdict_from_records`'s own recompute site SURVIVED the whole suite.
        That was not an equivalence -- it was an unexercised input shape. Every fixture in the file
        measures every series on all 30 seeds, so the sweep's `min_seeds` assertion was satisfied by the
        stored `gate_min_seeds` state (min_seeds > 30 fails the GATE, which blocks all three hypotheses
        before any component floor is consulted) rather than by the floor itself.
        With an UNBALANCED study the two differ, and so do "the configured minimum" and "whatever the
        gate said":
          * min_seeds=10: the gate passes AND every component clears its floor -> JOINT_SUPPORTED.
            Hardcoding 30 makes the two n=25 converged components INCONCLUSIVE -> JOINT_INCONCLUSIVE.
          * min_seeds=26: the gate STILL PASSES (32 measured >= 26) and only the n=25 converged
            components fall below -> JOINT_INCONCLUSIVE, h1/h2 still SUPPORTED. A recompute that read
            the gate instead of the floor, or that used any constant, cannot produce this pattern.
        Both directions assert the verdict, the three hypothesis verdicts and the reasons tuple."""
        recs, cfg, res = self.unbalanced(min_seeds=10)
        # the fixture really is unbalanced, and the shape is pinned so the test cannot go vacuous
        by = {r.name.rsplit("/agg/", 1)[1]: r for r in recs if "/agg/" in r.name}
        self.assertEqual(bm._pair_from_record(by["H1"]).n, 32)
        self.assertEqual(bm._pair_from_record(by["H3a"]).n, 32)
        self.assertEqual(bm._pair_from_record(by["H3a_conv"]).n, 25)
        self.assertEqual(bm._pair_from_record(by["H3b_conv"]).n, 25)
        self.assertEqual(bm._metric_count(by["JOINT"].metrics["n_seeds"], "n"), 32)
        self.assertTrue(all(g.passed for g in res.gates), [g.name for g in res.gates if not g.passed])
        rv = bm.verdict_from_records(recs, cfg)
        self.assertEqual(rv.reasons, ())
        self.assertEqual((rv.h1, rv.h2, rv.h3), (V.SUPPORTED,) * 3)
        self.assertIs(rv.joint, J.JOINT_SUPPORTED)
        # ... and 26 moves ONLY the converged components, with the gate still passing
        recs26, cfg26, res26 = self.unbalanced(min_seeds=26)
        self.assertTrue(all(g.passed for g in res26.gates),
                        [g.name for g in res26.gates if not g.passed])
        self.assertIn("min_seeds", [g.name for g in res26.gates if g.passed])
        rv26 = bm.verdict_from_records(recs26, cfg26)
        self.assertEqual(rv26.reasons, ())
        self.assertEqual((rv26.h1, rv26.h2), (V.SUPPORTED, V.SUPPORTED))
        self.assertIs(rv26.h3, V.INCONCLUSIVE)
        self.assertIs(rv26.joint, J.JOINT_INCONCLUSIVE)
        # the live result agrees with its own recompute, so this is a property of the floor, not of
        # the records path alone
        self.assertIs(res26.h3.verdict, V.INCONCLUSIVE)
        # the primary components (n=32) stay SUPPORTED; it is the CONVERGED ones (n=25) that fall below,
        # which is the shape no balanced fixture can produce
        self.assertEqual([c.verdict for c in res26.h3.components], [V.SUPPORTED, V.SUPPORTED])
        self.assertEqual([c.reason for c in res26.h3.converged_components],
                         ["n=25 below protocol minimum 26: no verdict"] * 2)
        self.assertIn("H3: finite-budget only", " ".join(res26.h3.reasons))


class TheMinimumSeedsFloorHoldsForEveryValueTheFieldsCanHold(unittest.TestCase):
    """F4: `IntervalPair` had NO `__post_init__`, and `ComponentResult` normalised `margin` while
    leaving `min_n` and `width_tol` -- passed in the same call -- untouched.

    Each of the three decides a component verdict through an overridable comparison:
      * `IntervalPair.n`     -- `n < min_n` in `_verdict_from_bounds`; `n` is DATA (the number of seeds
                                a series was measured on), not a protocol parameter;
      * `ComponentResult.min_n`     -- the same comparison with the subclass as the RIGHT operand, so
                                the REFLECTED `__gt__` decides;
      * `ComponentResult.width_tol` -- `abs(wb - wt) / big > width_tol` in `intervals_disagree`,
                                likewise reflected.
    MEASURED before the fix, each with the field still rendering as an honest number: `n=NSub(1)` and
    `min_n=MSub(30)` both returned SUPPORTED off a TWO-value series (record `n_seeds = 1.0`), and
    `width_tol=WSub(0.25)` turned a genuine INCONCLUSIVE ("widths differ by more than 25%") into
    SUPPORTED and JOINT_SUPPORTED. The module docstring's "no component verdict exists below the
    minimum" was false in exactly that way, and a doc-only mutant weakening the sentence survived,
    which is why the sentence is asserted here too."""

    class NSub(int):
        def __lt__(self, o):
            return False

        def __ge__(self, o):
            return True

    class MSub(int):
        def __gt__(self, o):
            return False

        def __le__(self, o):
            return True

        def __int__(self):
            return 10 ** 9

        def __index__(self):
            return 10 ** 9

    class WSub(float):
        def __lt__(self, o):
            return False

        def __gt__(self, o):
            return False

        def __float__(self):
            return 10 ** 9

    LVL = bm.bonferroni_level(0.05, 4)

    def tiny(self):
        """Two tied values: the intervals ARE computable and above the margin, so the ONLY thing
        standing between this pair and a SUPPORTED is the minimum-n rule."""
        return bm.summarize("S", [0.9, 0.9], self.LVL, 400, 7, min_n=30)

    def widths_disagree(self):
        """27.6% relative width difference: INCONCLUSIVE at width_tol=0.25, decisive above it."""
        return bm.summarize("S", [0.5] * 27 + [0.5 + 0.0001 * i for i in range(3)], self.LVL, 400, 7,
                            min_n=30)

    def test_a_forged_n_cannot_clear_the_protocol_minimum(self):
        pair = self.tiny()
        self.assertEqual(bm.interval_verdict(pair, 0.1, "greater"),
                         (V.INCONCLUSIVE, "n=2 below protocol minimum 30: no verdict"))
        for stored in (1, 2, 29):
            with self.subTest(stored=stored):
                forged = dataclasses.replace(pair, n=self.NSub(stored))
                self.assertIs(type(forged.n), int, "the subclass is still stored")
                self.assertEqual(forged.n, stored)
                self.assertEqual(bm.interval_verdict(forged, 0.1, "greater"),
                                 (V.INCONCLUSIVE, f"n={stored} below protocol minimum 30: no verdict"))
                c = bm.ComponentResult("S", "greater", 0.1, forged, 30, 0.25)
                self.assertIs(c.verdict, V.INCONCLUSIVE)
                h = bm.HypothesisResult("H1", (c,))
                self.assertIs(h.verdict, V.INCONCLUSIVE)
                self.assertEqual(h.reasons,
                                 (f"S: n={stored} below protocol minimum 30: no verdict",))
                self.assertIs(bm.combine_joint(h.verdict, V.SUPPORTED, V.SUPPORTED, True),
                              J.JOINT_INCONCLUSIVE)
                # the record stores the same n the verdict was refused for
                self.assertEqual(bm._agg_metrics(forged, 0.1, 0, "fixture")["n_seeds"].value,
                                 float(stored))
        # the honest direction still works: a real 30-seed pair is still decisive
        big = bm.summarize("S", [0.9 + 0.001 * i for i in range(30)], self.LVL, 400, 7, min_n=30)
        self.assertIs(bm.interval_verdict(big, 0.1, "greater")[0], V.SUPPORTED)

    def test_a_forged_min_n_cannot_waive_the_protocol_minimum(self):
        pair = self.tiny()
        for stored in (30, 31, 10 ** 6):
            with self.subTest(stored=stored):
                c = bm.ComponentResult("S", "greater", 0.1, pair, self.MSub(stored), 0.25)
                self.assertIs(type(c.min_n), int)
                self.assertEqual(c.min_n, stored)       # NOT 10**9 from __int__
                self.assertIs(c.verdict, V.INCONCLUSIVE)
                self.assertEqual(c.reason, f"n=2 below protocol minimum {stored}: no verdict")
                self.assertEqual(bm.interval_verdict(pair, 0.1, "greater", min_n=self.MSub(stored)),
                                 (V.INCONCLUSIVE, f"n=2 below protocol minimum {stored}: no verdict"))
        # and a minimum the pair genuinely meets is still honoured, through the subclass
        ok = bm.ComponentResult("S", "greater", 0.1, pair, self.MSub(2), 0.25)
        self.assertIs(ok.verdict, V.SUPPORTED)

    def test_a_forged_width_tol_cannot_silence_the_disagreement_rule(self):
        pair = self.widths_disagree()
        honest = bm.ComponentResult("S", "greater", 0.0, pair, 30, 0.25)
        self.assertIs(honest.verdict, V.INCONCLUSIVE)
        self.assertIn("widths differ by more than 25%", honest.reason)
        c = bm.ComponentResult("S", "greater", 0.0, pair, 30, self.WSub(0.25))
        self.assertIs(type(c.width_tol), float)
        self.assertEqual(c.width_tol, 0.25)
        self.assertIs(c.verdict, V.INCONCLUSIVE, c.reason)
        self.assertEqual(c.reason, honest.reason)
        h = bm.HypothesisResult("H1", (c,))
        self.assertEqual(h.reasons, (f"S: {honest.reason}",))
        self.assertIs(bm.combine_joint(h.verdict, V.SUPPORTED, V.SUPPORTED, True), J.JOINT_INCONCLUSIVE)
        # a genuinely loose tolerance still admits the component, so the normalisation is not a veto
        loose = bm.ComponentResult("S", "greater", 0.0, pair, 30, 0.5)
        self.assertIs(loose.verdict, V.SUPPORTED)

    def test_every_interval_pair_entry_point_agrees_with_the_plain_value(self):
        """The property rather than the three sites: for each field, the answer on a hostile subclass
        must equal the answer on the plain number it stores. `level` and `n_boot` are included because
        they are recorded and cross-checked, not because a verdict reads them directly."""
        pair = self.widths_disagree()
        entries = {
            "n": lambda v: bm.interval_verdict(dataclasses.replace(pair, n=v), 0.0, "greater"),
            "n stored": lambda v: bm._agg_metrics(dataclasses.replace(pair, n=v), 0.0, 0,
                                                  "fixture")["n_seeds"].value,
            "level stored": lambda v: dataclasses.replace(pair, level=v).level,
            "n_boot stored": lambda v: bm._agg_metrics(dataclasses.replace(pair, n_boot=v), 0.0, 0,
                                                       "fixture")["n_boot"].value,
            "min_n": lambda v: bm.ComponentResult("S", "greater", 0.0, pair, v, 0.25).verdict,
            "min_n reason": lambda v: bm.ComponentResult("S", "greater", 0.0, pair, v, 0.25).reason,
            "width_tol": lambda v: bm.ComponentResult("S", "greater", 0.0, pair, 30, v).verdict,
            "width_tol reason": lambda v: bm.ComponentResult("S", "greater", 0.0, pair, 30, v).reason,
        }
        for name, fn in entries.items():
            for sneak, stored in ((self.NSub, 2), (self.NSub, 30), (self.MSub, 2), (self.MSub, 30),
                                  (self.WSub, 0.25), (self.WSub, 0.5)):
                if issubclass(sneak, float) and "n" == name:
                    continue
                with self.subTest(entry=name, sneak=sneak.__name__, stored=stored):
                    try:
                        want, werr = fn(stored), None
                    except Exception as e:                      # pragma: no cover - parity is the point
                        want, werr = None, type(e)
                    try:
                        got, gerr = fn(sneak(stored)), None
                    except Exception as e:                      # pragma: no cover
                        got, gerr = None, type(e)
                    self.assertEqual(gerr, werr, f"{name}: raised differently for the same number")
                    self.assertEqual(got, want, f"{name}: answered differently for the same number")

    def test_the_module_docstring_no_longer_claims_more_than_it_can(self):
        doc = " ".join(bm.__doc__.split())
        self.assertIn("THIS BULLET USED TO END \"no component verdict exists below the minimum\", "
                      "FULL STOP, AND THAT WAS FALSE", doc)
        self.assertIn("`IntervalPair` had no `__post_init__` at all", doc)
        self.assertIn("normalised at construction now", doc)
        reader = " ".join(bm._metric_read.__doc__.split())
        self.assertIn("IT RETURNS A PLAIN `float`, NEVER THE STORED OBJECT", reader)
        src = Path(bm.__file__).read_text()
        self.assertIn("THIS COMMENT USED TO CONTINUE \"so a `MetricValue` built by the public API is "
                      "sound\". THAT WAS FALSE", src)


class TheSeedIsTheUnitOfReplication(unittest.TestCase):
    """The SR-10 twin of `toy.robustness._check_seeds` (F2 there), found by sweeping `set(` / `hash()`
    and worse here, because in SR-10 it buys a JOINT VERDICT.

    `evaluate_gates` refuses a repeated seed with `len(set(ids)) != len(ids)` and requires
    `set(ids) <= set(frozen.seeds)`; both are `__hash__` plus `__eq__` on whatever `SeedScores.seed`
    holds, and `SeedScores` validated its metrics but never its seed. A LYING `__hash__` alone is
    caught -- by the subset half, which then cannot find the seed in the frozen list -- so the attack
    needs an honest hash and a TYPE-SELECTIVE `__eq__`: equal to a plain int of the same value (so the
    subset check passes) and unequal to another instance of itself (so the duplicate check does not
    collapse the list). MEASURED through the public `SeedScores.from_values` + `analyze_scores`, with
    thirty copies of ONE seed: seed_list_frozen PASSED, min_seeds PASSED, JOINT_SUPPORTED, a recompute
    of JOINT_SUPPORTED with `reasons = ()`, a stored `n_seeds` of 30.0, and thirty per-seed records --
    for a study with one replicate. Design point 2 of the module docstring ("the seed is the unit of
    replication") and protocol 6.1's minimum-n rule were both satisfied by one example."""

    class SelSeed(int):
        def __eq__(self, o):
            return type(o) is int and int.__int__(self) == o

        def __ne__(self, o):
            return not self.__eq__(o)

        __hash__ = int.__hash__

    def dup(self, mk):
        one = FZ.seeds[0]
        return [bm.SeedScores.from_values(mk(one), 1.0, -0.01, 1.0, 1.0, A=0.5, F=0.005,
                                          E_loss_ratio=0.01, delta_conv=1.0, delta_minus_shuf_conv=1.0,
                                          conv_grad_ratio=1e-5, rowsets_disjoint=True, mask_ok=True)
                for _ in range(30)]

    def analyse(self, scores):
        return bm.analyze_scores(scores, frozen=FZ, registered_digest=FZ.digest, subject="s",
                                 cfg=SMALL, subject_kind="fixture", fixture_name="f")

    def test_one_seed_thirty_times_cannot_pass_the_frozen_seed_list_gate(self):
        self.assertTrue(self.SelSeed(FZ.seeds[0]) == FZ.seeds[0])          # the attack's premise ...
        self.assertFalse(self.SelSeed(FZ.seeds[0]) == self.SelSeed(FZ.seeds[0]))   # ... in both halves
        for nm, mk in (("plain int", int), ("int subclass", self.SelSeed)):
            with self.subTest(route=nm):
                res = self.analyse(self.dup(mk))
                failed = [g.name for g in res.gates if not g.passed]
                self.assertEqual(failed, ["seed_list_frozen"], nm)
                self.assertIn("not a subset of the frozen list",
                              [g.reason for g in res.gates if g.name == "seed_list_frozen"][0])
                self.assertIs(res.verdict, J.JOINT_INCONCLUSIVE, nm)
                self.assertEqual((res.h1.verdict, res.h2.verdict, res.h3.verdict),
                                 (V.INCONCLUSIVE,) * 3, nm)
                self.assertIn("gate failed: seed_list_frozen", res.h1.reasons[0], nm)
                # and the stored seed is the plain value, so the record cannot read as 30 distinct ones
                self.assertEqual(len({s.seed for s in res.seed_scores}), 1, nm)
                self.assertEqual({type(s.seed) for s in res.seed_scores}, {int}, nm)

    def test_an_honest_distinct_seed_list_still_passes_through_the_subclass(self):
        scores = [bm.SeedScores.from_values(self.SelSeed(s), 1.0, -0.01, 1.0, 1.0, A=0.5, F=0.005,
                                            E_loss_ratio=0.01, delta_conv=1.0,
                                            delta_minus_shuf_conv=1.0, conv_grad_ratio=1e-5,
                                            rowsets_disjoint=True, mask_ok=True) for s in FZ.seeds]
        res = self.analyse(scores)
        self.assertEqual([g.name for g in res.gates if not g.passed], [])
        self.assertIs(res.verdict, J.JOINT_SUPPORTED)
        recs = bm.to_experiment_records(res, study_id="x", base_seed=7, timestamp_utc=TS_PROBE)
        self.assertEqual(bm.verdict_from_records(recs, SMALL).reasons, ())
        self.assertEqual(len({r.provenance.seed for r in
                              bm.seed_records(res, study_id="x", timestamp_utc=TS_PROBE)}), 30)

    def test_a_seed_that_is_not_an_int_is_refused_at_construction(self):
        for bad in (True, False, 7.0, "7", None, [7]):
            with self.assertRaises(ValueError, msg=repr(bad)):
                bm.SeedScores.from_values(bad, 1.0, -0.01, 1.0, 1.0)
            with self.assertRaises(ValueError, msg=repr(bad)):
                bm.SeedScores.failed(bad, "why")
        s = bm.SeedScores.from_values(self.SelSeed(9), 1.0, -0.01, 1.0, 1.0)
        self.assertIs(type(s.seed), int)
        self.assertEqual(s.seed, 9)


class NoForgedStoredMetricBuysABetterVerdict(unittest.TestCase):
    """SR-15 D1-D5, pinned by ENUMERATING the metrics a record actually carries rather than listing the
    ones we happened to think of. The honest study is the global degrader: a measured, correct
    JOINT_UNSUPPORTED (h1 SUPPORTED, h2 UNSUPPORTED, h3 UNSUPPORTED). Mutant M31 -- deleting the
    `margin` check outright -- survived all 313 tests before this class existed, because the only
    margin-forgery test used `margin=9.0` and asserted the UNFAVOURABLE direction. Here every forged
    value is driven in BOTH directions and the assertion is on the verdict and the reasons tuple."""
    TS = "2025-01-02T03:04:05Z"
    BIG = sys.float_info.max
    # forged values reachable with no `object.__setattr__` at all (MetricValue accepts any finite float)
    LEGAL = (BIG, -BIG, 1e300, -1e300, 1e9, -1e9, 0.0, 30.5)
    # forged values needing `object.__setattr__`, i.e. route (b) of the module's own threat model
    RAW = (math.inf, -math.inf, math.nan, True, False, 1, 0, "1.0", "", [1.0], {}, None, object())

    @classmethod
    def setUpClass(cls):
        cls.res = bm.run_study(FZ, bm.fixture_global_degrader(0.5), subject="d",
                               registered_digest=FZ.digest, cfg=SMALL)
        cls.recs = bm.to_experiment_records(cls.res, study_id="f", base_seed=7, timestamp_utc=cls.TS)

    def honest(self):
        rv = bm.verdict_from_records(self.recs, SMALL)
        self.assertEqual((rv.joint, rv.h1, rv.h2, rv.h3),
                         (J.JOINT_UNSUPPORTED, V.SUPPORTED, V.UNSUPPORTED, V.UNSUPPORTED))
        self.assertEqual(rv.reasons, ())
        return rv

    def _forged(self, tag, key, val, raw):
        out = []
        for r in self.recs:
            if r.name.rsplit("/agg/", 1)[1] == tag:
                if raw:
                    mv = MetricValue.measured(1.0)
                    object.__setattr__(mv, "value", val)
                else:
                    mv = MetricValue.measured(val)
                r = dataclasses.replace(r, metrics={**r.metrics, key: mv})
            out.append(r)
        return out

    def test_every_metric_every_record_carries_is_forged_and_none_buys_a_verdict(self):
        """THE ENUMERATION IS PERFORMED, NOT ASSERTED: the key set comes from `rec.metrics` itself, so a
        metric added to `_agg_metrics` later is covered automatically and an unchecked new consumer of it
        fails here without anyone remembering to extend a list."""
        self.honest()
        tags = sorted(r.name.rsplit("/agg/", 1)[1] for r in self.recs)
        self.assertEqual(tags, sorted(["H1", "H2", "H3a", "H3b", "H3a_conv", "H3b_conv", "JOINT"]))
        n_cases, carved = 0, 0
        for rec in self.recs:
            tag = rec.name.rsplit("/agg/", 1)[1]
            self.assertTrue(rec.metrics, tag)
            for key in sorted(rec.metrics):
                for val, raw in [(v, False) for v in self.LEGAL] + [(v, True) for v in self.RAW]:
                    n_cases += 1
                    if (key == "margin" and not raw and isinstance(val, float)
                            and abs(val) <= bm.MARGIN_MAX):
                        # THE ONE CARVE-OUT, and it is the documented honest limit rather than an
                        # oversight: a WITHIN-BOUNDS margin is a legal protocol parameter, margins are
                        # producer-asserted, and `_check_margin` bounds magnitude only -- so such a cell
                        # is EXPECTED to be able to move a verdict. It is measured, in both directions,
                        # by `AMarginIsBoundedWhereverOneEnters`. The count is pinned below so the
                        # carve-out cannot silently grow to cover a future unchecked read.
                        carved += 1
                        continue
                    recs = self._forged(tag, key, val, raw)
                    why = f"{tag}.{key} := {val!r} (raw={raw})"
                    try:
                        rv = bm.verdict_from_records(recs, SMALL)
                    except ValueError:
                        continue            # refusing loudly is the fail-closed outcome
                    # no forgery may reach a favourable joint verdict ...
                    self.assertIsNot(rv.joint, J.JOINT_SUPPORTED, why)
                    # ... nor turn either genuinely UNSUPPORTED hypothesis into SUPPORTED ...
                    self.assertIsNot(rv.h2, V.SUPPORTED, why)
                    self.assertIsNot(rv.h3, V.SUPPORTED, why)
                    # ... and a verdict that moved at all must not look like a clean recompute
                    if (rv.joint, rv.h1, rv.h2, rv.h3) != (J.JOINT_UNSUPPORTED, V.SUPPORTED,
                                                           V.UNSUPPORTED, V.UNSUPPORTED):
                        self.assertNotEqual(rv.joint, J.JOINT_SUPPORTED, why)
        # THE CASE COUNT, PINNED BY VALUE. It was quoted as "492 cases" -- in a task brief and in commit
        # 57a6f03's message, which cannot be rewritten -- and 492 WAS NEVER MEASURED BY ANYONE: this
        # assertion used to read `assertGreater(n_cases, 400)`, which 492 and the true figure both
        # satisfy. The true figure is 2268 = 108 (key, record) pairs x 21 forged values, of which 12 are
        # carved out, leaving 2256 driven through a recompute. `assertEqual`, not `assertGreater`, so the
        # number in prose is the number the machine counted.
        self.assertEqual(n_cases, 2268, "the enumeration changed size; re-derive the quoted figure")
        self.assertEqual(len(self.LEGAL) + len(self.RAW), 21)
        self.assertEqual(sum(len(r.metrics) for r in self.recs), 108)
        self.assertEqual(n_cases - carved, 2256)
        self.assertGreater(n_cases, 400, "the enumeration collapsed; it is no longer covering the metrics")
        # 6 component records x 2 in-bounds float margins in LEGAL (0.0, 30.5); the JOINT record has no
        # `margin` metric. If this number moves, a carve-out was widened and must be re-argued.
        self.assertEqual(carved, 12, "the margin carve-out changed size")

    def test_the_favourable_margin_direction_is_covered_in_both_signs(self):
        """D1 PROPER. The sign that matters differs per component (`lo > margin` for H1/H3a/H3b and the
        converged pair, `hi < margin` for H2), which is why a single-sign forgery -- the only kind the
        pre-existing test did -- left the inverting direction untested. Signed per direction here."""
        self.honest()
        favourable = {"H1": -self.BIG, "H2": +self.BIG, "H3a": -self.BIG, "H3b": -self.BIG,
                      "H3a_conv": -self.BIG, "H3b_conv": -self.BIG}
        recs = self.recs
        for tag, val in favourable.items():
            recs = [dataclasses.replace(r, metrics={**r.metrics, "margin": MetricValue.measured(val)})
                    if r.name.rsplit("/agg/", 1)[1] == tag else r for r in recs]
        with self.assertRaisesRegex(ValueError, "MARGIN_MAX"):
            bm.verdict_from_records(recs, SMALL)
        # and the unfavourable direction still works as it always did (no over-refusal)
        raised = [dataclasses.replace(r, metrics={**r.metrics, "margin": MetricValue.measured(9.0)})
                  if r.name.endswith("/H1") else r for r in self.recs]
        rv = bm.verdict_from_records(raised, SMALL)
        self.assertEqual((rv.h1, rv.joint, rv.reasons), (V.UNSUPPORTED, J.JOINT_UNSUPPORTED, ()))

    def test_a_forged_n_seeds_is_cross_checked_against_the_studys_own_count(self):
        """D4. `_pair_from_record` had no check of ANY kind on `n_seeds`, and a forged count is a legal
        float that no value test can catch -- it needs a second stored number. The JOINT record's
        `n_seeds` is that number, and `component n <= joint n` holds by construction."""
        self.honest()
        for n in (1e9, 31.0, 1e300):
            recs = self._forged("H1", "n_seeds", n, False)
            with self.assertRaisesRegex(ValueError, "exceeds the study", msg=repr(n)):
                bm.verdict_from_records(recs, SMALL)
        # the error contract: nothing escapes as a raw int()/float() failure
        for n, raw in ((math.nan, True), (None, True), (30.5, False), (-1.0, False)):
            with self.assertRaises(ValueError, msg=repr(n)):
                bm.verdict_from_records(self._forged("H1", "n_seeds", n, raw), SMALL)
        # A LOWER count is honest-shaped (a series can be measured on fewer seeds than succeeded) and must
        # stay allowed -- and must still be refused a verdict by protocol 6.1's minimum-n floor. The joint
        # verdict stays JOINT_UNSUPPORTED because H2 and H3 are genuinely UNSUPPORTED and that outranks an
        # INCONCLUSIVE H1; the point of the assertion is that H1 loses its verdict, not that the joint moves.
        rv = bm.verdict_from_records(self._forged("H1", "n_seeds", 4.0, False), SMALL)
        self.assertEqual((rv.h1, rv.joint, rv.reasons), (V.INCONCLUSIVE, J.JOINT_UNSUPPORTED, ()))
        self.assertIsNot(rv.joint, J.JOINT_SUPPORTED)

    def test_a_gate_metric_forged_to_the_bool_true_does_not_pass(self):
        """D5. `v.value != 1.0` let `True` through, because `True == 1.0`. `GateResult.__post_init__`
        is strict about bools; the records path was not. Pinned on a study whose gates GENUINELY fail,
        so passing them is the thing that would change the verdict."""
        scores = synth_scores(FZ.seeds, loss=0.9, gr=1.0)        # control_adequacy + convergence both fail
        res = bm.analyze_scores(scores, frozen=FZ, registered_digest=FZ.digest, subject="s", cfg=SMALL)
        recs = bm.to_experiment_records(res, study_id="f", base_seed=7, timestamp_utc=self.TS)
        j = recs[-1]
        self.assertEqual({k: v.value for k, v in j.metrics.items()
                          if k in ("gate_control_adequacy", "gate_convergence")},
                         {"gate_control_adequacy": 0.0, "gate_convergence": 0.0})
        base = bm.verdict_from_records(recs, SMALL)
        self.assertEqual((base.joint, base.h1, base.h2, base.h3),
                         (J.JOINT_INCONCLUSIVE,) + (V.INCONCLUSIVE,) * 3)
        for forged in (True, 1, "1", "1.0", math.inf):
            m = dict(j.metrics)
            for k in list(m):
                if k.startswith("gate_"):
                    mv = MetricValue.measured(1.0)
                    object.__setattr__(mv, "value", forged)
                    m[k] = mv
            rv = bm.verdict_from_records(recs[:-1] + [dataclasses.replace(j, metrics=m)], SMALL)
            self.assertEqual((rv.joint, rv.h1, rv.h2, rv.h3),
                             (J.JOINT_INCONCLUSIVE,) + (V.INCONCLUSIVE,) * 3, repr(forged))
        # the honest float 1.0 must still pass, or the fix is vacuous
        ok = bm.to_experiment_records(oracle(), study_id="f", base_seed=7, timestamp_utc=self.TS)
        self.assertEqual(bm.verdict_from_records(ok, SMALL).joint, J.JOINT_SUPPORTED)

    def test_a_forged_ci_level_cannot_slip_past_the_alpha_cross_check(self):
        """D2. `abs(lv.value - want_level) > 1e-12` is False for `nan`, so a forged `nan` silently
        disabled the cross-check the docstring credits with pinning `alpha`."""
        for bad in (math.nan, math.inf, -math.inf, True, "0.9875", None, []):
            with self.assertRaises(ValueError, msg=repr(bad)):
                bm.verdict_from_records(self._forged("H1", "ci_level", bad, True), SMALL)
        self.assertEqual(bm.verdict_from_records(self.recs, SMALL).joint, J.JOINT_UNSUPPORTED)


class ForgedGateInputsCannotTurnAFailedGateIntoAPass(unittest.TestCase):
    """SR-15 D3. `evaluate_gates` read `s.metrics[...].value` into a list and gated on
    `any(v is None)`, which is the `is_measured` test by another spelling. Honest
    `E_loss_ratio = 0.9` fails gate 11(c) (`max(rs) > 1/loss_factor`) and honest
    `conv_grad_ratio = 1.0` fails gate 12 (`max(grs) <= tau_conv`); a forged `-inf` made BOTH pass,
    which took the whole study from JOINT_INCONCLUSIVE to JOINT_SUPPORTED."""

    def _scores(self):
        return synth_scores(FZ.seeds, loss=0.9, gr=1.0)

    def test_the_honest_values_fail_both_gates(self):
        g = {x.name: x.passed for x in bm.evaluate_gates(self._scores(), FZ, FZ.digest, SMALL)}
        self.assertFalse(g["control_adequacy"])
        self.assertFalse(g["convergence"])

    def test_a_forged_gate_input_cannot_make_either_gate_pass(self):
        for bad in (-math.inf, math.inf, math.nan, True, False, 0, 1, "0", [], None, object()):
            scores = self._scores()
            for s in scores:
                for k in ("E_loss_ratio", "conv_grad_ratio", "A", "F"):
                    object.__setattr__(s.metrics[k], "value", bad)
            g = {x.name: x.passed for x in bm.evaluate_gates(scores, FZ, FZ.digest, SMALL)}
            self.assertFalse(g["control_adequacy"], repr(bad))
            self.assertFalse(g["convergence"], repr(bad))
            # the conclusion, not just the intermediate: the study must not become favourable
            res = bm.analyze_scores(scores, frozen=FZ, registered_digest=FZ.digest, subject="s", cfg=SMALL)
            self.assertIs(res.verdict, J.JOINT_INCONCLUSIVE, repr(bad))
            self.assertIsNot(res.h1.verdict, V.SUPPORTED, repr(bad))
            recs = bm.to_experiment_records(res, study_id="f", base_seed=7, timestamp_utc="2025-01-02T03:04:05Z")
            rv = bm.verdict_from_records(recs, SMALL)
            self.assertIs(rv.joint, J.JOINT_INCONCLUSIVE, repr(bad))

    def test_the_honest_passing_study_still_passes(self):
        g = {x.name: x.passed for x in bm.evaluate_gates(synth_scores(FZ.seeds), FZ, FZ.digest, SMALL)}
        self.assertTrue(g["control_adequacy"])
        self.assertTrue(g["convergence"])


class _SneakyMargin(float):
    """N1 verbatim: stores one double, answers `abs()` and `float()` with two different other numbers."""
    def __abs__(self):
        return 1.0

    def __float__(self):
        return -1e308


class _SneakyBound(float):
    """A stored metric that compares favourably whatever it holds.

    `__eq__` is deliberately NOT overridden here, and WHY is now a finding rather than a note on a
    fixture. THE SENTENCE THAT USED TO STAND IN THIS DOCSTRING: "`__eq__` is deliberately NOT
    overridden, because `MetricValue.__post_init__` normalises `value == 0.0` and would replace the
    instance -- so a lying `__eq__` would make this test pass for the wrong reason."

    THE LESSON, in this round's words, because that sentence cost five rounds. The author of it
    found the mechanism, understood it precisely enough to write down that a lying `__eq__` REPLACES
    THE STORED VALUE, and then filed it as a nuisance to be routed around in a test fixture instead of
    as a hole in the validator. It was the most severe defect in the three modules: `MetricValue.
    measured(EqZero(7.0)).value` was 0.0, so the schema's own validator substituted the measurement,
    and an honest JOINT_UNSUPPORTED recomputed as JOINT_SUPPORTED with `reasons = ()`, an unchanged
    `config_hash`, and the per-seed values still reading as honest numbers in every record.

    THE RULE THIS BUYS, and it is cheap to apply: when you find yourself writing "I avoided X because
    it would make my test pass for the wrong reason", X is a finding. A test is steered away from a
    mechanism exactly when the mechanism does something the code under test should not do; the
    workaround is the discovery, and leaving it in a fixture's docstring hides it in the one place a
    reader of the module will never look. The same reasoning applies to "I had to use `object.
    __setattr__` to reproduce this" (then the public route is worth re-checking) and to "the assertion
    only holds for the default parameter" (then the parameter's range is unswept).

    `__eq__` STAYS un-overridden, now for the opposite reason: the schema stores the plain double it
    checked, so a lying `__eq__` no longer changes what is stored, and the four ORDER-comparison
    overrides below are what this fixture is for. A lying `__eq__` is covered separately and directly,
    at the root, by `test_schema.AMetricStoresTheNumberItChecked`."""
    def __gt__(self, other):
        return True

    def __lt__(self, other):
        return False

    def __ge__(self, other):
        return True

    def __le__(self, other):
        return False

    def __sub__(self, other):
        return 0.0

    def __rsub__(self, other):
        return 0.0


class _SneakyCount(float):
    """A count that passes `v != int(v)` and `v < 0` and then converts to something else entirely."""
    def __ne__(self, other):
        return False

    def __lt__(self, other):
        return False

    def __int__(self):
        return 10 ** 9

    def __index__(self):
        return 10 ** 9

    def __hash__(self):
        return 0


class _SneakyLevel(float):
    """A confidence level that passes `0 < level < 1` holding 5.0, and then picks its own tails."""
    def __gt__(self, other):
        return True

    def __lt__(self, other):
        return True

    def __rsub__(self, other):
        return 0.5


class NormaliseBeforeCheckingEverywhereANumberEnters(unittest.TestCase):
    """N1 AND THE SWEEP IT ASKED FOR, not the one site it was reported at.

    THE PATTERN: a predicate applied to a value and a conversion of that value are two INDEPENDENTLY
    OVERRIDABLE operations. Inspecting `v` and then using `float(v)` / `abs(v)` / `int(v)` / `v > m`
    checks one number and decides on another, and NO TAMPERING PRIMITIVE IS NEEDED -- an `int`/`float`
    subclass satisfies every `isinstance` test in the module and `math.isfinite` reads the stored double,
    which the subclass need not lie about. `MetricValue.measured(...)` accepts such an instance through
    the public API.

    THE REPORTED SITE: `_check_margin` tested `abs(v)` and returned `float(v)`, so `_SneakyMargin(0.0)`
    came back as -1e+308 -- seven orders outside the function whose docstring calls it "THE ONE validity
    test for a margin, wherever a margin enters the module" -- and carried SUPPORTED through
    `interval_verdict`, `ComponentResult` and `HypothesisResult`.

    THE THREE THE SWEEP FOUND, each worse than the reported one:
      * `_metric_read`, THE checked reader, returned the stored OBJECT. A `MetricValue.measured(Lo(-9.0))`
        built with no `object.__setattr__` at all made a genuinely NEGATIVE interval read SUPPORTED
        against an honest margin of 0.1. Every guard in this module that calls itself "the single checked
        reader" was downstream of that.
      * `_metric_count` returned `int(v)` after comparing `v != int(v)`: a stored `n_seeds` of 30.0 that
        converts to 1e9.
      * `_check_level` returned None, so the caller kept the original object and `percentile_interval`
        computed `(1.0 - level) / 2.0` on an overridable `__rsub__`.
      * (`toy.robustness.ProbeConfig` had the same defect on `SEED_FLOOR`; it is pinned in
        `test_robustness.ThePolicyParametersAreThemselvesPinned`.)

    THE FIX IS ORDERING, in one helper (`_plain_number`) that every validator now calls FIRST, and which
    reads the value through `float.__float__` / `int.__int__` -- the value the object STORES, which is the
    same number `math.isfinite` and `MetricValue.__post_init__` inspected. The checked number and the
    used number cannot differ because they are the same object."""

    SNEAKS = (_SneakyMargin, _SneakyBound, _SneakyCount, _SneakyLevel)

    def pair(self, values=None):
        return bm.summarize("S", values if values is not None else [0.5 + 0.01 * i for i in range(30)],
                            bm.bonferroni_level(0.05, 4), 200, 7)

    def test_check_margin_tests_and_returns_the_SAME_number(self):
        """N1. The stored double is 0.0, which IS a legal margin, so the correct answer is 0.0 -- not a
        refusal and emphatically not -1e+308. The honest control shows the bound still bites."""
        self.assertEqual(bm._check_margin(_SneakyMargin(0.0), "m"), 0.0)
        self.assertIs(type(bm._check_margin(_SneakyMargin(0.0), "m")), float)
        with self.assertRaisesRegex(ValueError, "MARGIN_MAX"):
            bm._check_margin(-1e308, "m")                       # the honest value it used to return
        # and a sneak whose STORED value is out of bounds is still refused, for its stored value
        with self.assertRaisesRegex(ValueError, "MARGIN_MAX"):
            bm._check_margin(_SneakyMargin(1e307), "m")
        for entry in (lambda v: bm.Margins(delta_S=v), lambda v: bm.Margins(delta_R=v),
                      lambda v: bm.Margins(delta_sel=v),
                      lambda v: bm.interval_verdict(self.pair(), v, "greater"),
                      lambda v: bm._verdict_from_bounds(30, (0.4, 0.6), (0.4, 0.6), v, "greater", 30, 0.25),
                      lambda v: bm.ComponentResult("S", "greater", v, self.pair(), 30, 0.25)):
            with self.assertRaisesRegex(ValueError, "MARGIN_MAX"):
                entry(_SneakyMargin(1e307))
            entry(_SneakyMargin(0.0))                           # the in-bounds stored value is accepted
        # Margins STORES the checked value, so nothing downstream re-converts it
        self.assertIs(type(bm.Margins(delta_S=_SneakyMargin(0.0)).delta_S), float)
        self.assertEqual(bm.Margins(delta_S=_SneakyMargin(0.25)).delta_S, 0.25)
        self.assertIs(type(bm.ComponentResult("S", "greater", _SneakyMargin(0.1), self.pair()).margin),
                      float)

    def test_a_forged_float_subclass_bound_cannot_buy_a_verdict(self):
        """THE WORST OF THE FOUR, and reachable with NO `object.__setattr__`: `MetricValue` accepts a
        `float` subclass, `_metric_read` used to hand it back with its overrides intact, and `lo > margin`
        is then whatever the subclass says. Driven on a genuinely NEGATIVE interval against an honest
        margin, and asserted on the verdict at all three levels plus the reasons tuple."""
        honest = self.pair([-9.0] * 30)
        self.assertIs(bm.interval_verdict(honest, 0.1, "greater")[0], V.UNSUPPORTED)
        # TWO LAYERS, asserted separately, because this test used to conflate them and the assertion
        # that held them together ("the hostile object really is stored") was an assertion that the
        # SCHEMA WAS BROKEN. Layer 1: the public constructor no longer stores the hostile object at all
        # -- `MetricValue.__post_init__` keeps the plain double it validated (the F1 root fix).
        built = MetricValue.measured(_SneakyBound(-9.0))
        self.assertIs(type(built.value), float, "MetricValue stored a float subclass")
        self.assertEqual(built.value, -9.0)
        # Layer 2, which is what `_metric_read` is FOR and must keep holding independently: route (b)
        # installs the hostile object after construction, past every constructor check.
        forged = dataclasses.replace(
            honest, boot_lo=forge(MetricValue.measured(1.0), _SneakyBound(-9.0)),
            boot_hi=forge(MetricValue.measured(1.0), _SneakyBound(-9.0)),
            t_lo=forge(MetricValue.measured(1.0), _SneakyBound(-9.0)),
            t_hi=forge(MetricValue.measured(1.0), _SneakyBound(-9.0)))
        self.assertIs(type(forged.boot_lo.value), _SneakyBound)     # the hostile object really is stored
        self.assertIs(type(bm._metric_read(forged.boot_lo)), float)  # ... and the reader plainifies it
        self.assertEqual(bm._metric_read(forged.boot_lo), -9.0)
        for nm, pair in (("route (b) forgery", forged),
                         ("public constructor", dataclasses.replace(
                             honest, boot_lo=built, boot_hi=MetricValue.measured(_SneakyBound(-9.0)),
                             t_lo=MetricValue.measured(_SneakyBound(-9.0)),
                             t_hi=MetricValue.measured(_SneakyBound(-9.0))))):
            with self.subTest(route=nm):
                v, why = bm.interval_verdict(pair, 0.1, "greater")
                self.assertIs(v, V.UNSUPPORTED, why)
                c = bm.ComponentResult("S", "greater", 0.1, pair, 30, 0.25)
                self.assertIs(c.verdict, V.UNSUPPORTED)
                h = bm.HypothesisResult("H1", (c,))
                self.assertIs(h.verdict, V.UNSUPPORTED)
                self.assertEqual(h.reasons, ("S: whole interval at or below margin",))
                self.assertIs(bm.combine_joint(h.verdict, V.SUPPORTED, V.SUPPORTED, True),
                              J.JOINT_UNSUPPORTED)

    def test_the_checked_reader_and_the_count_reader_return_plain_floats(self):
        for sneak in self.SNEAKS:
            mv = MetricValue.measured(sneak(30.0))
            got = bm._metric_read(mv)
            self.assertIs(type(got), float, sneak.__name__)
            self.assertEqual(got, 30.0, sneak.__name__)
            self.assertEqual(bm._metric_required(mv, "x"), 30.0, sneak.__name__)
            n = bm._metric_count(mv, "n")
            self.assertIs(type(n), int, sneak.__name__)
            self.assertEqual(n, 30, sneak.__name__)              # NOT 10**9 from __int__
        # a non-integral stored value is still refused, so the normalisation did not weaken the count rule
        with self.assertRaises(ValueError):
            bm._metric_count(MetricValue.measured(_SneakyCount(30.5)), "n")

    def test_check_level_returns_the_level_it_checked(self):
        self.assertEqual(bm._check_level(_SneakyLevel(0.95)), 0.95)
        self.assertIs(type(bm._check_level(_SneakyLevel(0.95))), float)
        for bad in (_SneakyLevel(5.0), _SneakyLevel(0.0), _SneakyLevel(-1.0), _SneakyLevel(1.0)):
            with self.assertRaises(ValueError, msg=repr(float.__float__(bad))):
                bm._check_level(bad)
        # the consequence: the interval's tails come from the checked level, not from `__rsub__`
        plain = bm.percentile_interval(list(range(101)), 0.95)
        self.assertEqual(bm.percentile_interval(list(range(101)), _SneakyLevel(0.95)), plain)
        self.assertEqual(bm.t_interval([1.0, 2.0, 3.0, 4.0, 5.0], _SneakyLevel(0.95)),
                         bm.t_interval([1.0, 2.0, 3.0, 4.0, 5.0], 0.95))

    def test_the_statistics_layer_computes_on_the_sample_it_validated(self):
        """`_check_finite` returned None, so `mean` / `sample_sd` / `t_interval` / `bootstrap_means` all
        went on to compute with the caller's objects. `_constant` is `x == v[0]` and `_mean` then returns
        `float(v[0])`, so a lying `__float__` on a "constant" sample chose the mean outright."""
        for sneak in self.SNEAKS:
            sample = [sneak(0.25)] * 4
            plain = [0.25] * 4
            self.assertEqual(bm.mean(sample), bm.mean(plain), sneak.__name__)
            self.assertIs(type(bm.mean(sample)), float, sneak.__name__)
            self.assertEqual(bm.sample_sd(sample), 0.0, sneak.__name__)
            mixed = [sneak(0.1), sneak(0.2), sneak(0.3), 0.4]
            self.assertEqual(bm.mean(mixed), bm.mean([0.1, 0.2, 0.3, 0.4]), sneak.__name__)
            self.assertEqual(bm.sample_sd(mixed), bm.sample_sd([0.1, 0.2, 0.3, 0.4]), sneak.__name__)
            self.assertEqual(bm.t_interval(mixed, 0.95), bm.t_interval([0.1, 0.2, 0.3, 0.4], 0.95))
        # and the whole summary, which is what reaches a verdict
        vals = [0.5 + 0.01 * i for i in range(30)]
        sneaky = bm.summarize("S", [_SneakyBound(v) for v in vals], bm.bonferroni_level(0.05, 4), 200, 7)
        plain = bm.summarize("S", vals, bm.bonferroni_level(0.05, 4), 200, 7)
        for f in ("mean", "sd", "iqr", "minimum", "maximum", "boot_lo", "boot_hi", "t_lo", "t_hi"):
            self.assertEqual(bm._metric_read(getattr(sneaky, f)), bm._metric_read(getattr(plain, f)), f)
        self.assertEqual(bm.interval_verdict(sneaky, 0.1, "greater"),
                         bm.interval_verdict(plain, 0.1, "greater"))

    def test_the_whole_entry_point_sweep_agrees_with_the_plain_value(self):
        """THE SWEEP ITSELF, as a property rather than a list of sites: for every entry point that takes a
        number, the answer on a hostile subclass must equal the answer on the plain double it stores --
        or both must raise the same way. A new validator that inspects before normalising fails here
        without anyone adding a case for it, PROVIDED it is reachable from one of these entry points;
        that proviso is the honest limit of this test and the reason `_plain_number` is one function."""
        pair30 = self.pair()
        entries = {
            "_check_margin": lambda v: bm._check_margin(v, "m"),
            "Margins.delta_S": lambda v: bm.Margins(delta_S=v).delta_S,
            "interval_verdict": lambda v: bm.interval_verdict(pair30, v, "greater"),
            "ComponentResult": lambda v: bm.ComponentResult("S", "greater", v, pair30).verdict,
            "_check_level": bm._check_level,
            "percentile_interval": lambda v: bm.percentile_interval(list(range(101)), v),
            "mean": lambda v: bm.mean([v, v, 0.5]),
            "sample_sd": lambda v: bm.sample_sd([v, v, 0.5]),
            "t_interval": lambda v: bm.t_interval([v, v, 0.5], 0.95),
            "quantile": lambda v: bm.quantile([0.0, 1.0, 2.0], v),
            "bonferroni_level": lambda v: bm.bonferroni_level(v, 4),
            "summarize": lambda v: bm._metric_read(bm.summarize("S", [v, v, 0.5], 0.9875, 50, 7).mean),
            "_mv": lambda v: bm._metric_read(bm._mv(v, "why")),
            "_metric_read": lambda v: bm._metric_read(MetricValue.measured(v)),
            "_metric_count": lambda v: bm._metric_count(MetricValue.measured(v), "n"),
            "BenchmarkConfig.alpha": lambda v: bm.BenchmarkConfig(alpha=v).config_hash(),
            "BenchmarkConfig.width_tol": lambda v: bm.BenchmarkConfig(width_tol=v).config_hash(),
            "required_n": lambda v: bm.required_n([v, 0.1], bm.Margins(), 0.9875),
        }
        probes = [sneak(x) for sneak in self.SNEAKS for x in (0.25, 0.5, 30.0, 0.9875)]
        for name, fn in entries.items():
            for sneaky in probes:
                plain = float.__float__(sneaky)
                with self.subTest(entry=name, stored=plain, sneak=type(sneaky).__name__):
                    try:
                        want, want_err = fn(plain), None
                    except Exception as e:
                        want, want_err = None, type(e)
                    try:
                        got, got_err = fn(sneaky), None
                    except Exception as e:
                        got, got_err = None, type(e)
                    self.assertEqual(got_err, want_err, f"{name}: raised differently for the same number")
                    self.assertEqual(got, want, f"{name}: answered differently for the same number")

    def test_a_large_int_is_a_ValueError_not_an_OverflowError(self):
        """N2. `_check_margin` raised `OverflowError` for `10**400` while its own docstring called such a
        value "not a finite real number" and `interval_verdict`'s promised a `ValueError`. `_check_finite`
        had always converted it and `mean([10**400])` had always raised `ValueError`, so the module was
        inconsistent with itself. `test_every_entry_point_for_a_margin_applies_the_same_bound` enumerated
        nine bad margins and no large int, which is why it was untested."""
        big = 10 ** 400
        pair30 = self.pair()
        for name, fn in (("_check_margin", lambda: bm._check_margin(big, "m")),
                         ("Margins delta_S", lambda: bm.Margins(delta_S=big)),
                         ("Margins delta_R", lambda: bm.Margins(delta_R=big)),
                         ("Margins delta_sel", lambda: bm.Margins(delta_sel=big)),
                         ("interval_verdict", lambda: bm.interval_verdict(pair30, big, "greater")),
                         ("_verdict_from_bounds",
                          lambda: bm._verdict_from_bounds(30, (0.4, 0.6), (0.4, 0.6), big, "greater", 30, 0.25)),
                         ("ComponentResult", lambda: bm.ComponentResult("S", "greater", big, pair30)),
                         ("BenchmarkConfig lr", lambda: bm.BenchmarkConfig(lr=big)),
                         ("BenchmarkConfig alpha", lambda: bm.BenchmarkConfig(alpha=big)),
                         ("BenchmarkConfig tau_conv", lambda: bm.BenchmarkConfig(tau_conv=big)),
                         ("_check_level", lambda: bm._check_level(big)),
                         ("mean", lambda: bm.mean([big])),
                         ("sample_sd", lambda: bm.sample_sd([big, 1.0])),
                         ("t_interval", lambda: bm.t_interval([big, 1.0], 0.95)),
                         ("summarize", lambda: bm.summarize("S", [big], 0.9875, 50, 7)),
                         ("required_n", lambda: bm.required_n([big], bm.Margins(), 0.9875))):
            with self.subTest(entry=name):
                with self.assertRaises(ValueError):
                    fn()
                try:
                    fn()
                except ValueError:
                    pass
                except OverflowError:                 # pragma: no cover - the defect, if it returns
                    self.fail(f"{name} raised OverflowError, outside the module's error contract")
        # a stored metric cannot hold one at all (schema refuses it), and the reader says so
        self.assertIsNone(bm._metric_read(forge(MetricValue.measured(1.0), big)))
        self.assertIsNone(bm._plain_number(big))
        self.assertEqual(bm._plain_number(10 ** 300), 1e300)      # not an over-refusal of large ints
        self.assertEqual(bm._plain_number(5), 5.0)
        self.assertIsNone(bm._plain_number(True))

    def test_plain_number_reads_the_stored_value_and_refuses_everything_else(self):
        """`_plain_number`'s own contract, directly, so the sweep above cannot pass by the helper being
        over-permissive. It reads through `float.__float__` / `int.__int__` ON PURPOSE: those are the
        values `math.isfinite` and `MetricValue.__post_init__` inspect, so an override is not consulted
        second -- it is not consulted at all."""
        self.assertEqual(bm._plain_number(_SneakyMargin(0.0)), 0.0)
        self.assertEqual(bm._plain_number(_SneakyMargin(2.5)), 2.5)
        self.assertEqual(bm._plain_number(_SneakyCount(30.0)), 30.0)
        for good, want in ((0.0, 0.0), (-0.0, -0.0), (1, 1.0), (-7, -7.0), (5e-324, 5e-324),
                           (sys.float_info.max, sys.float_info.max), (10 ** 300, 1e300)):
            self.assertEqual(bm._plain_number(good), want, repr(good))
            self.assertIs(type(bm._plain_number(good)), float, repr(good))
        for bad in (True, False, math.inf, -math.inf, math.nan, "1.0", "", None, [1.0], {}, (), object(),
                    10 ** 400, -10 ** 400, bytearray(b"1")):
            self.assertIsNone(bm._plain_number(bad), repr(bad))

    def test_no_validator_inspects_before_normalising_anywhere_in_the_module(self):
        """A SOURCE TRIPWIRE over the pattern itself, in the shape `toy.dashboard` uses for its kind
        functions: `abs(`, `int(` and a bare `float(` may appear only inside `_plain_number` (which is
        where the normalisation lives) and inside arithmetic that has already been normalised. Listed by
        OWNER so a new validator that writes `float(v)` in front of a check is named. This is a tripwire,
        not a proof -- the proof is the behavioural sweep above."""
        src = Path(bm.__file__).read_text()
        tree = ast.parse(src)
        owner = {}
        for fn in ast.walk(tree):
            if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for sub in ast.walk(fn):
                    owner.setdefault(id(sub), fn.name)
        coercions = sorted({(owner.get(id(n), "<module>"), n.func.id) for n in ast.walk(tree)
                            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                            and n.func.id in ("float", "int", "abs")})
        self.assertEqual(coercions, [
            ("_agg_metrics", "float"),          # IntervalPair.n / .level / .n_boot, validated at build
            ("_betacf", "abs"),                 # internal continued fraction, local floats only
            ("_check_margin", "abs"),           # AFTER _plain_number: the N1 fix is this ordering
            ("_mean", "float"),                 # v[0] of a sample _check_finite already normalised
            ("_metric_count", "int"),           # AFTER _metric_required, i.e. after _plain_number
            ("_plain_number", "float"),         # THE normaliser (float(int.__int__(v)) for an int)
            ("intervals_disagree", "abs"),      # bounds that came out of _metric_read
            ("quantile", "float"),              # AFTER _plain_number; an element of a checked sample
            ("quantile", "int"),                # math.floor of an already-normalised position
            ("sample_sd", "abs"),               # a sample _check_finite already normalised
            ("score_predictor", "float"),       # locally computed, math.isfinite-checked one line above
            ("score_seed", "float"),            # fx.G, validated at fixture build
            ("seed_list_digest", "int"),        # a digest, not a measurement
            ("summarize", "abs"),               # vals, normalised by _plain_number at entry
            ("to_experiment_records", "float"),  # counts off JointResult's own validated fields
            ("verdict_from_records", "abs"),    # |lv - want_level|, both from _metric_required
        ], "a coercion appeared or moved: check it is applied AFTER _plain_number, not before a test")


class AMarginIsBoundedWhereverOneEnters(unittest.TestCase):
    """SR-15: the `Margins` bounding decision, and the proof that the bound is applied at the single
    point where a margin is USED rather than at a remembered set of call sites.

    DECIDED: bound MAGNITUDE, not sign. The vacuous direction differs per field -- H1/H3 compare
    `lo > margin` so a very negative margin is vacuous, H2 compares `hi < margin` so a very positive
    one is -- and a negative `delta_R` ("the retention loss must be an improvement") is a legitimately
    STRICTER test. `MARGIN_MAX` is arbitrary and is NOT a protocol parameter; see `_check_margin`.
    STATED AS A LIMIT, NOT A CLOSURE: `Margins(-1e6, +1e6, -1e6)` is within bounds and still decides
    every component before the data is seen, and the test below MEASURES that rather than hiding it."""

    def test_margin_max_is_pinned_by_value_and_type(self):
        self.assertEqual(bm.MARGIN_MAX, 1e6)
        self.assertIsInstance(bm.MARGIN_MAX, float)
        self.assertNotIn("MARGIN_MAX", {f.name for f in dataclasses.fields(bm.BenchmarkConfig)})

    def test_every_entry_point_for_a_margin_applies_the_same_bound(self):
        pair = bm.summarize("S", [0.5 + 0.01 * i for i in range(30)], bm.bonferroni_level(0.05, 4), 200, 7)
        over = (sys.float_info.max, -sys.float_info.max, 1e6 + 1, -(1e6 + 1), math.inf, -math.inf,
                math.nan, True, False, "0.1", None, [0.1])
        for bad in over:
            with self.assertRaises(ValueError, msg=f"Margins {bad!r}"):
                bm.Margins(delta_S=bad)
            with self.assertRaises(ValueError, msg=f"Margins delta_R {bad!r}"):
                bm.Margins(delta_R=bad)
            with self.assertRaises(ValueError, msg=f"Margins delta_sel {bad!r}"):
                bm.Margins(delta_sel=bad)
            with self.assertRaises(ValueError, msg=f"interval_verdict {bad!r}"):
                bm.interval_verdict(pair, bad, "greater")
            with self.assertRaises(ValueError, msg=f"_verdict_from_bounds {bad!r}"):
                bm._verdict_from_bounds(30, (0.4, 0.6), (0.4, 0.6), bad, "greater", 30, 0.25)
            with self.assertRaises(ValueError, msg=f"ComponentResult {bad!r}"):
                bm.ComponentResult("S", "greater", bad, pair, 30, 0.25)
        # and through the record path, where the margin is a stored metric
        recs = bm.to_experiment_records(oracle(), study_id="f", base_seed=7, timestamp_utc="2025-01-02T03:04:05Z")
        for bad in (sys.float_info.max, -sys.float_info.max, 1e6 + 1):
            forged = [dataclasses.replace(r, metrics={**r.metrics, "margin": MetricValue.measured(bad)})
                      if r.name.endswith("/H1") else r for r in recs]
            with self.assertRaises(ValueError, msg=repr(bad)):
                bm.verdict_from_records(forged, SMALL)

    def test_the_bound_does_not_over_refuse_a_legitimate_margin(self):
        pair = bm.summarize("S", [0.5 + 0.01 * i for i in range(30)], bm.bonferroni_level(0.05, 4), 200, 7)
        for good in (0.0, -0.0, 0.05, 0.1, 1, -1, 5.0, -5.0, 1e6, -1e6, 5e-324):
            bm.Margins(delta_S=good, delta_R=good, delta_sel=good)
            bm.interval_verdict(pair, good, "greater")
            bm.ComponentResult("S", "greater", good, pair, 30, 0.25)
        # an int margin still works (the dashboard pins this too) and sign is deliberately unbounded
        self.assertEqual(bm.Margins(delta_S=1, delta_R=1, delta_sel=1).delta_S, 1)
        self.assertEqual(bm.Margins(delta_R=-0.02).delta_R, -0.02)
        self.assertIs(bm.interval_verdict(pair, 0.1, "greater")[0], V.SUPPORTED)

    def test_the_within_bounds_vacuous_margin_is_measured_and_documented_not_claimed_closed(self):
        """The honest limit. A legal `Margins(-1e6, +1e6, -1e6)` inverts a measured JOINT_UNSUPPORTED
        with a BYTE-IDENTICAL config_hash and `reasons = ()`. The old illustration (`delta_S=5.0,
        delta_R=-5.0`) only showed the SAFE direction, which understated the gap badly."""
        honest = bm.run_study(FZ, bm.fixture_global_degrader(0.5), subject="d",
                              registered_digest=FZ.digest, cfg=SMALL)
        vacuous = bm.run_study(FZ, bm.fixture_global_degrader(0.5), subject="d",
                               registered_digest=FZ.digest, cfg=SMALL,
                               margins=bm.Margins(-1e6, 1e6, -1e6))
        self.assertIs(honest.verdict, J.JOINT_UNSUPPORTED)
        self.assertIs(vacuous.verdict, J.JOINT_SUPPORTED)
        self.assertEqual(honest.config_hash, vacuous.config_hash)        # byte-identical provenance
        rv = bm.verdict_from_records(bm.to_experiment_records(
            vacuous, study_id="f", base_seed=7, timestamp_utc="2025-01-02T03:04:05Z"), SMALL)
        self.assertIs(rv.joint, J.JOINT_SUPPORTED)
        self.assertEqual(rv.reasons, ())                 # indistinguishable from a clean recompute
        # the safe direction the superseded illustration showed, kept so the contrast is on the record
        safe = bm.run_study(FZ, bm.fixture_global_degrader(0.5), subject="d", registered_digest=FZ.digest,
                            cfg=SMALL, margins=bm.Margins(delta_S=5.0, delta_R=-5.0, delta_sel=5.0))
        self.assertIs(safe.verdict, J.JOINT_UNSUPPORTED)

    def test_the_three_falsified_statements_are_corrected_where_a_reader_looks(self):
        mg = " ".join(bm.Margins.__doc__.split())
        self.assertNotIn("So the margin a recompute uses is always the margin that produced the record", mg)
        for needle in ('USED TO CLAIM "so the margin a recompute uses is always the margin that produced '
                       'the record", which was FALSE',
                       "a PROVENANCE argument offered as a VALIDITY argument",
                       "`Margins(-1e6, +1e6, -1e6)`",
                       "margins remain PRODUCER-ASSERTED"):
            self.assertIn(needle, mg)
        vd = " ".join(bm.verdict_from_records.__doc__.split())
        self.assertNotIn("so no margin a recompute uses can come from the caller at all. ", vd + " ")
        for needle in ("A PROVENANCE ARGUMENT OFFERED AS A VALIDITY ARGUMENT",
                       'IT WAS ALSO CLAIMED TO "GRANT NOTHING OVER FORGING THE `gate_*` METRICS DIRECTLY", '
                       "WHICH WAS FALSE",
                       "it cannot make a component SUPPORTED",
                       "The two are not equivalent"):
            self.assertIn(needle, vd)
        cm = " ".join(bm._check_margin.__doc__.split())
        self.assertIn("It does NOT close, and cannot close, the legal-`Margins` route", cm)
        self.assertIn("FOR ANY FINITE CAP", cm)
        rd = " ".join(bm._metric_read.__doc__.split())
        self.assertIn("`True` is an `int`", rd)


class ConfigHashIsCanonicalNotMerelyCalledCanonical(unittest.TestCase):
    """SR-15 D6. Mutant M19 -- dropping `sort_keys=True` from `config_hash` -- survived all 313 tests.
    `sort_keys` is the whole content of the word "canonical": without it the hash is a function of
    `dataclasses.asdict`'s iteration order, so a pure field REORDER (identical values) moves the hash
    and silently breaks the `config` binding of every stored record. "Repeatability" is the literal
    acceptance criterion for this module, so it is pinned by value here rather than by trust."""

    def test_config_hash_is_invariant_under_field_reordering(self):
        d = dataclasses.asdict(SMALL)
        self.assertEqual(len(d), 18)
        want = hashlib.sha256(json.dumps(d, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        self.assertEqual(SMALL.config_hash(), want)
        for order in (list(reversed(list(d))), sorted(d, key=lambda k: (len(k), k)), sorted(d, reverse=True)):
            shuffled = {k: d[k] for k in order}
            self.assertEqual(set(shuffled), set(d))
            self.assertEqual(SMALL.config_hash(), hashlib.sha256(
                json.dumps(shuffled, sort_keys=True, separators=(",", ":")).encode()).hexdigest(), order[:2])

    def test_dropping_sort_keys_really_would_change_the_hash(self):
        """THE PIN'S OWN PROOF, so the assertion above is not satisfiable by a no-op: with `sort_keys`
        removed, a reorder alone moves the hash. Measured 9eaf4bfefc57 -> 08d7772419c5."""
        d = dataclasses.asdict(SMALL)
        rev = {k: d[k] for k in reversed(list(d))}
        unsorted_fwd = hashlib.sha256(json.dumps(d, separators=(",", ":")).encode()).hexdigest()
        unsorted_rev = hashlib.sha256(json.dumps(rev, separators=(",", ":")).encode()).hexdigest()
        self.assertNotEqual(unsorted_fwd, unsorted_rev)
        self.assertEqual((unsorted_fwd[:12], unsorted_rev[:12]), ("9eaf4bfefc57", "08d7772419c5"))
        self.assertEqual(SMALL.config_hash()[:12], "ce68ac811ac7")
        self.assertIn("sort_keys=True", inspect.getsource(bm.BenchmarkConfig.config_hash))

    def test_the_repeatability_requirement_is_stated_where_the_reader_looks(self):
        ch = " ".join(bm.BenchmarkConfig.config_hash.__doc__.split())
        for needle in ("CANONICAL MEANS `sort_keys=True`, and that is load-bearing",
                       "9eaf4bfefc57 to 08d7772419c5", '"Repeatability" is the literal acceptance criterion'):
            self.assertIn(needle, ch)


# ================================================================= the KEY lane (round 12)
# SR-10 was UNMARKED for a flip that round 6 had already closed ONCE, on the other field of the same
# lookup: `m.get("config")` is `__hash__` + `__eq__` ON THE STORED KEY, so normalising `input_hashes`
# VALUES in `toy.schema` left the KEYS deciding which value every lookup in `verdict_from_records`
# returned. What follows is NOT three patches with three tests. It is a generator derived from the
# invariant -- EVERY DECISION READS THE CHARACTERS THE OBJECT STORES -- run over sites ENUMERATED from a
# real payload and from the module's own AST, which is the shape that out-found targeted search 13 to 4
# and then 7 to 1 in this project.
def _key_liar(stores, answers):
    """A `str` storing `stores` that HASHES and COMPARES as `answers`: the minimum object that makes a
    mapping serve one name's value under another name. `__hash__` must agree or the lookup never probes
    the right bucket, and `__eq__` is what CPython calls on the STORED key once it does (a `str` subclass
    key makes it abandon `lookdict_unicode` for the general lookup)."""
    class KeyLiar(str):
        def __hash__(self):
            return hash(answers)

        def __eq__(self, other):
            return other == answers if isinstance(other, str) else NotImplemented

        def __ne__(self, other):
            return not self.__eq__(other)
    return KeyLiar(stores)


def _honest_copy(recs):
    """A fresh, independently mutable copy of a record list, rebuilt THROUGH the public constructors so
    every copy starts normalised. `copy.deepcopy` cannot be used: `RunProvenance` stores a
    `mappingproxy`, which does not pickle."""
    out = []
    for r in recs:
        prov = dataclasses.replace(r.provenance, input_hashes=dict(r.provenance.input_hashes))
        out.append(dataclasses.replace(r, provenance=prov, metrics=dict(r.metrics)))
    return out


def _recompute_outcome(recs, cfg):
    """Everything a consumer of `verdict_from_records` can observe, as one comparable value: the four
    verdicts, the decoded subject kind, the config hash the recompute bound to, the reasons tuple, or the
    exception type and message. The REASONS are in it deliberately -- the defect's signature was
    `reasons = ()`, a clean recompute, so a pin that compared only verdicts would have missed the
    silencing of the refusal paragraph."""
    try:
        rv = bm.verdict_from_records(recs, cfg)
    except Exception as exc:                                   # noqa: BLE001 - the error IS the outcome
        return ("raised", type(exc).__name__, str(exc))
    return ("ok", rv.joint, rv.h1, rv.h2, rv.h3, rv.subject_kind, rv.config_hash, rv.reasons)


def _mapping_fields(rec):
    """The mappings of one record whose KEYS this module looks words up in, by the route it reads them:
    walked off the OBJECT, not listed, so a mapping a producer starts filing is swept the day it exists."""
    return (("metrics", rec.metrics, lambda r, m: object.__setattr__(r, "metrics", m)),
            ("provenance.input_hashes", rec.provenance.input_hashes,
             lambda r, m: object.__setattr__(r.provenance, "input_hashes", m)))


class TheConfigBindingReadsTheWordTheKeyStores(unittest.TestCase):
    """ROUND 12 FINDING 1, and round 6's Finding 1 returning through the KEYS of the same lookup.

    `stored = {r.provenance.input_hashes.get("config") for r in by.values()}` decided the binding on the
    STORED key's `__hash__`/`__eq__`. A key storing "seed_list_2" that answers as "config", CARRYING THE
    HASH THE RECOMPUTE ITSELF WILL WANT (`cfg.config_hash()` of the default cfg, since `cfg=None`), bound
    a `width_tol=0.10` study to the default 0.25 and reported JOINT_SUPPORTED with the refusal paragraph
    gone -- for a configuration NO RECORD EVER FILED A CONFIG HASH FOR.

    MEASURED against the pre-fix module, 3.12.4, `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src`, cleared
    `__pycache__`:
        honest  JOINT_INCONCLUSIVE  bound 236b3ce79ebc  reasons ("cfg does not match the stored study
                configuration (cfg 6089f9b81710 vs stored 236b3ce79ebc): refusing to recompute with a
                different min_seeds/width_tol/alpha",)
        forged  JOINT_SUPPORTED     bound 6089f9b81710  reasons ()
    THE TRAP, recorded because the first attempt at this reads as closed: planting the STUDY's own hash
    instead does NOT flip it. The hash has to be the one the recompute will ask for, which is why the
    forgery is `want_hash = cfg.config_hash()` and not the stored value.
    `object.__setattr__` IS needed on a real `ExperimentRecord` -- `schema._plain_value` collapses the key
    on every public route, re-verified here -- but the function's own contract is not enforced, so the
    same forgery also arrives through a DUCK-TYPED record with no tampering primitive at all
    (`test_a_duck_typed_record_is_the_same_forgery_without_object_setattr`)."""
    TS = "2025-01-02T03:04:05Z"
    TIGHT = dataclasses.replace(SMALL, width_tol=0.10)

    @classmethod
    def setUpClass(cls):
        cls.res = bm.run_study(FZ, bm.fixture_oracle_gated, subject="oracle_gated",
                               registered_digest=FZ.digest, cfg=cls.TIGHT)
        cls.recs = bm.to_experiment_records(cls.res, study_id="f", base_seed=7, timestamp_utc=cls.TS)

    def _forge(self, recs, planted):
        for r in recs:
            ih = {k: v for k, v in r.provenance.input_hashes.items() if k != "config"}
            ih[_key_liar("seed_list_2", "config")] = planted
            object.__setattr__(r.provenance, "input_hashes", ih)
        return recs

    def test_the_honest_recompute_refuses_the_mismatched_default_cfg(self):
        """THE REFERENCE the forgery has to not improve on. Still fails closed after the key fix: the
        round-7 behaviour (`cfg` omitted => refuse, never fall back to module defaults) is re-verified
        here because the config binding is exactly what this round touched."""
        rv = bm.verdict_from_records(self.recs)                 # no cfg argument at all
        self.assertEqual(rv.joint, J.JOINT_INCONCLUSIVE)
        self.assertEqual((rv.h1, rv.h2, rv.h3), (V.INCONCLUSIVE,) * 3)
        self.assertEqual(rv.config_hash, self.res.config_hash)
        self.assertEqual(len(rv.reasons), 1)
        self.assertIn("refusing to recompute with a different min_seeds/width_tol/alpha", rv.reasons[0])
        self.assertIn(bm.BenchmarkConfig().config_hash()[:12], rv.reasons[0])
        self.assertIn(self.res.config_hash[:12], rv.reasons[0])

    def test_a_key_answering_as_config_cannot_bind_the_recompute(self):
        """THE FLIP, pinned. Pre-fix this returned JOINT_SUPPORTED with `reasons = ()`; the key now reads
        as the word it stores, so no record files a `config` hash and the recompute refuses."""
        want = bm.BenchmarkConfig().config_hash()               # the hash the recompute itself will want
        recs = self._forge(_honest_copy(self.recs), want)
        self.assertFalse(any("config" in {str.__str__(k) for k in r.provenance.input_hashes}
                             for r in recs), "the premise: no record files a literal 'config' key")
        rv = bm.verdict_from_records(recs)
        self.assertEqual(rv.joint, J.JOINT_INCONCLUSIVE)
        self.assertIsNone(rv.config_hash, "a forged key must not be reported as the hash it bound to")
        self.assertEqual(len(rv.reasons), 1)
        self.assertIn("no stored config hash on at least one record", rv.reasons[0])
        self.assertNotEqual(rv.joint, J.JOINT_SUPPORTED)

    def test_planting_the_studys_own_hash_never_flipped_it_and_still_does_not(self):
        """THE TRAP, as a test so nobody re-runs it and concludes the site is closed."""
        recs = self._forge(_honest_copy(self.recs), self.res.config_hash)
        rv = bm.verdict_from_records(recs)
        self.assertEqual(rv.joint, J.JOINT_INCONCLUSIVE)

    def test_a_duck_typed_record_is_the_same_forgery_without_object_setattr(self):
        """`verdict_from_records` is annotated `Sequence[ExperimentRecord]` and checks no instance, so the
        key forgery also arrives on a plain object with four attributes. MEASURED pre-fix: JOINT_SUPPORTED,
        bound 6089f9b81710, `reasons = ()`, with no `object.__setattr__` anywhere -- which is why the
        'I needed a tampering primitive' reading of this finding was wrong."""
        class FakeProvenance:
            def __init__(self, hashes):
                self.input_hashes = hashes

        class FakeRecord:
            def __init__(self, real, hashes):
                self.name, self.metrics = real.name, real.metrics
                self.evidence_class, self.notes = real.evidence_class, real.notes
                self.provenance = FakeProvenance(hashes)

        want = bm.BenchmarkConfig().config_hash()
        fakes = []
        for r in self.recs:
            ih = {k: v for k, v in r.provenance.input_hashes.items() if k != "config"}
            ih[_key_liar("seed_list_2", "config")] = want
            fakes.append(FakeRecord(r, ih))
        rv = bm.verdict_from_records(fakes)
        self.assertEqual(rv.joint, J.JOINT_INCONCLUSIVE)
        self.assertIn("no stored config hash", rv.reasons[0])

    def test_the_public_route_is_closed_by_schema_and_that_is_re_verified_here(self):
        """The 'I needed `object.__setattr__`' smell, checked rather than asserted. `_plain_value`
        collapses a mapping KEY, so a liar handed to `RunProvenance` is stored as the characters it
        holds -- and a dict LITERAL containing both a liar and a real `config` key has already collapsed
        to one entry before `schema` sees it, which is a property of `dict`, not a guard."""
        liar = _key_liar("seed_list_2", "config")
        prov = RunProvenance(run_id="r", timestamp_utc=self.TS, seed=1, code_version="v",
                             python_version="3", toy_only=True, input_hashes={liar: "a" * 64})
        self.assertEqual([type(k) for k in prov.input_hashes], [str])
        self.assertEqual(list(prov.input_hashes), ["seed_list_2"])
        self.assertEqual(len({liar: "a" * 64, "config": "b" * 64}), 1)
        record = ExperimentRecord(name="evalproto/x/agg/H1", provenance=prov,
                                  metrics={_key_liar("junk", "margin"): MetricValue.measured(1.0)},
                                  evidence_class=EvidenceClass.TOY_RESULT, notes="n")
        self.assertEqual([type(k) for k in record.metrics], [str], "metrics keys too, not just hashes")
        self.assertEqual(list(record.metrics), ["junk"])

    def test_the_key_lane_is_stated_where_a_reader_looks_for_the_bindings_strength(self):
        """The load-bearing sentence, pinned per CLAUDE.md's per-sentence rule rather than by a lexical
        sweep: the `verdict_from_records` docstring is the one place a reader goes to learn how strong the
        config binding is, and until this round it described the VALUE lane only and said nothing about
        the NAME. A doc-only mutant that deletes the paragraph fails here."""
        doc = " ".join(bm.verdict_from_records.__doc__.split())
        for needle in ("THE KEY LANE, added in round 12 because the sentence above was true of the VALUE "
                       "and said nothing about the NAME",
                       "carrying the hash THIS CALL will ask for",
                       "Round 6 had closed the same flip on `input_hashes` VALUES in `toy.schema`; it "
                       "returned through the keys of the same lookup",
                       "THIS FUNCTION ENFORCES NO INSTANCE CHECK"):
            self.assertIn(needle, doc, needle)


class EveryWordLookedUpInAStoredMappingIsSwept(unittest.TestCase):
    """THE DERIVED SWEEP, and the deliverable of this round rather than the three patches above.

    HOW THE SITES ARE ENUMERATED: by WALKING A REAL PAYLOAD, the way `toy.dashboard`'s `_word_keyed` sweep
    walks the rendered payload rather than listing the page's lookups. For every record a study produces,
    for every mapping field of that record (`_mapping_fields`, read off the OBJECT), and for every key in
    that mapping, one forgery is built: the key is removed and a DERIVED donor -- the next key in sorted
    order, cyclically, so every key appears once as a target and once as a donor -- answers as it while
    keeping its own value. Nothing is listed in this file, so a metric a producer starts filing, or a new
    provenance anchor, is swept the day it exists. The `gate_*` lookup is covered without being named,
    which matters because its key is an f-STRING and a Constant-only AST sweep does not see the site.

    WHAT IT ASSERTS, and why it is not 'the verdict must not change': the honest fixture is the WRONG
    reference, because the forged mapping really is a different mapping. The reference is THE SAME MAPPING
    WITH THAT KEY PLAINIFIED -- the donor's value under the donor's own name and the target name absent,
    which is `base` minus the target key. So the assertion is exactly the round's invariant: the lookup
    reads the characters the key stores. A site satisfying neither that nor "cannot decide anything" is a
    complaint, and four were, all with `reasons = ()`:
        input_hashes 'seed_list_2' -> 'config'                  JOINT_INCONCLUSIVE -> JOINT_SUPPORTED
        metrics 'loss_check_exempt' -> 'gate_seed_list_frozen'   JOINT_INCONCLUSIVE -> JOINT_SUPPORTED
        metrics 'loss_check_exempt' -> 'subject_kind_code'       subject_kind fixture -> 'trained'
        metrics the exemption flag hidden behind an unread word  ValueError -> JOINT_SUPPORTED
    SWEEP SIZE is asserted below rather than described, so the sweep cannot quietly shrink to nothing."""
    TS = "2025-01-02T03:04:05Z"

    @classmethod
    def setUpClass(cls):
        cls.res = bm.run_study(FZ, bm.fixture_oracle_gated, subject="oracle_gated",
                               registered_digest=FZ.digest, cfg=SMALL)
        cls.recs = bm.to_experiment_records(cls.res, study_id="d", base_seed=7, timestamp_utc=cls.TS)

    def _cases(self):
        """Every (record index, field, target key, donor key) the payload yields. Derived, never typed."""
        for i, rec in enumerate(self.recs):
            for field, mapping, _ in _mapping_fields(rec):
                keys = sorted(str.__str__(k) for k in mapping)
                if len(keys) < 2:
                    continue
                for j, target in enumerate(keys):
                    yield i, field, target, keys[(j + 1) % len(keys)]

    def _build(self, index, field, target, donor, forge):
        recs = _honest_copy(self.recs)
        rec = recs[index]
        setter = next(s for name, _, s in _mapping_fields(rec) if name == field)
        base = next(m for name, m, _ in _mapping_fields(rec) if name == field)
        out = {str.__str__(k): v for k, v in base.items() if str.__str__(k) != target}
        if forge:
            value = out.pop(donor)
            out[_key_liar(donor, target)] = value
        setter(rec, out)
        return recs

    def test_every_key_of_every_stored_mapping_reads_as_the_word_it_stores(self):
        """EVERY complaint is collected before failing, deliberately: the first version stopped at the
        first and reported ONE site where the pre-fix module has 116 -- and the count is what
        distinguishes "the invariant is broken here" from "the invariant is broken module-wide".

        MEASURED against the pre-fix module, all 129 cases classified (3.12.4, PYTHONPATH=src, cleared
        `__pycache__`, nothing else running). 116 complaints, and they are NOT all the same severity --
        the distinction is the point, because a longer finding list is worth less than a classified one:
             13  agree: the lookup already read the word the key stored
             73  both raise, and only the metric NAMED in the message differs. UNCOVERED, NOT
                 CONSEQUENTIAL: the record is refused either way, and the harm is a misleading error
                 string, not a verdict. These are what a raw count of 116 would overstate.
             14  the forgery RAISES where the plainified mapping recomputes -- the fail-closed direction
             12  CONSEQUENTIAL: the forgery RECOMPUTES where the plainified mapping RAISES, i.e. it buys
                 a decisive verdict out of a record that is missing a metric
             17  CONSEQUENTIAL: both recompute and the verdict, the subject kind or the reasons differ
        So 29 of 129 forgeries move a verdict, a subject kind or a reasons tuple, and that is the number
        this round is about. Post-fix: 129 agree, 0 complaints."""
        swept = 0
        complaints = []
        for index, field, target, donor in self._cases():
            swept += 1
            forged = _recompute_outcome(self._build(index, field, target, donor, True), SMALL)
            plain = _recompute_outcome(self._build(index, field, target, donor, False), SMALL)
            if forged != plain:
                complaints.append(f"record {index} {field}: a key storing {donor!r} that answers as "
                                  f"{target!r} is not read as the word it stores.\n"
                                  f"      forged: {forged}\n      plain : {plain}")
        self.assertEqual(complaints, [], f"{len(complaints)} of {swept} swept (record, mapping, key) "
                                         f"forgeries are decided by a word the key does not store:\n"
                                         + "\n".join(complaints[:6]))
        self.assertGreaterEqual(swept, 100, "the sweep collapsed; it is supposed to walk a real payload")
        self.assertEqual(swept, len(list(self._cases())))

    def test_the_sweep_is_not_vacuous_and_the_honest_study_is_decisive(self):
        """NOT VACUOUS in the two ways a sweep like this fails silently: the reference outcome has to be
        REACHED (a payload of zero mappings would pass every assertion), and the honest study has to be
        DECISIVE, or every forgery would be compared against an INCONCLUSIVE that nothing can make worse."""
        honest = _recompute_outcome(_honest_copy(self.recs), SMALL)
        self.assertEqual(honest[0], "ok")
        self.assertEqual(honest[1], J.JOINT_SUPPORTED)
        self.assertEqual(honest[5], "fixture")
        self.assertEqual(honest[7], ())
        fields = {f for _, f, _, _ in self._cases()}
        self.assertEqual(fields, {"metrics", "provenance.input_hashes"})
        names = {t for _, f, t, _ in self._cases() if f == "metrics"}
        for required in ("subject_kind_code", "loss_check_exempt", "margin", "ci_level", "n_seeds",
                         "gate_seed_list_frozen", "gate_convergence", "ci_boot_lo", "ci_boot_hi"):
            self.assertIn(required, names, "the payload walk stopped covering a decisive name")
        self.assertIn("config", {t for _, f, t, _ in self._cases() if f == "provenance.input_hashes"})

    def test_the_sweep_catches_the_four_flips_it_exists_for(self):
        """THE EVIDENCE, as a test rather than as a claim in a report: each of the four complaints is
        rebuilt here and asserted to fail closed. Pre-fix each returned a decisive, reason-free recompute.
        These are the same cases the generator above produces; they are repeated by hand ONLY so that the
        consequences are named where a reader looks for them."""
        joint = [i for i, r in enumerate(self.recs) if str.__str__(r.name).endswith("/agg/JOINT")]
        self.assertEqual(len(joint), 1)
        at = joint[0]

        # (a) a FAILED global gate reads PASSED off the 1.0 filed as the exemption flag
        failed = bm.run_study(FZ, bm.fixture_oracle_gated, subject="oracle_gated",
                              registered_digest="0" * 64, cfg=SMALL)
        frecs = bm.to_experiment_records(failed, study_id="g", base_seed=7, timestamp_utc=self.TS)
        self.assertEqual(frecs[at].metrics["gate_seed_list_frozen"].value, 0.0)
        recs = _honest_copy(frecs)
        m = dict(recs[at].metrics)
        value = m.pop("loss_check_exempt")
        m.pop("gate_seed_list_frozen")
        m[_key_liar("loss_check_exempt", "gate_seed_list_frozen")] = value
        object.__setattr__(recs[at], "metrics", m)
        self.assertEqual(bm.verdict_from_records(recs, SMALL).joint, J.JOINT_INCONCLUSIVE)

        # (b) a declared scorer-validation fixture reported as a TRAINED subject
        recs = _honest_copy(self.recs)
        m = dict(recs[at].metrics)
        value = m.pop("loss_check_exempt")
        m.pop("subject_kind_code")
        m[_key_liar("loss_check_exempt", "subject_kind_code")] = value
        object.__setattr__(recs[at], "metrics", m)
        with self.assertRaises(ValueError) as caught:
            bm.verdict_from_records(recs, SMALL)
        self.assertIn("gate-11(c) exemption", str(caught.exception))

        # (c) the gate-11(c) forgery alarm silenced by hiding the flag behind an unread word
        recs = _honest_copy(self.recs)
        m = dict(recs[at].metrics)
        m["subject_kind_code"] = MetricValue.measured(bm.SUBJECT_KIND_CODE["trained"])
        value = m.pop("loss_check_exempt")
        m[_key_liar("loss_check_exempt", "zzz_never_read")] = value
        object.__setattr__(recs[at], "metrics", m)
        with self.assertRaises(ValueError) as caught:
            bm.verdict_from_records(recs, SMALL)
        self.assertIn("gate-11(c) exemption", str(caught.exception))

        # (d) a component's margin taken from a number filed under another name
        h1 = next(i for i, r in enumerate(self.recs) if str.__str__(r.name).endswith("/agg/H1"))
        recs = _honest_copy(self.recs)
        m = dict(recs[h1].metrics)
        self.assertEqual(m["margin"].value, 0.1)
        value = m["min"]
        m.pop("margin")
        m[_key_liar("min", "margin")] = value
        object.__setattr__(recs[h1], "metrics", m)
        with self.assertRaises(ValueError) as caught:
            bm.verdict_from_records(recs, SMALL)
        self.assertIn("stores no margin metric", str(caught.exception))

    def test_two_keys_storing_one_word_fail_closed_for_a_verdict_binding(self):
        """THE DELIBERATE CHOICE, and the OPPOSITE of `toy.dashboard._metric_table`, which does not
        collapse duplicates because two metrics whose keys store the same word are two ROWS and deleting
        either loses a real measurement. Here the name is read to BIND A VERDICT: serving either candidate
        would bind the recompute to whichever configuration the dict probed first, and 'absent' is already
        fail-closed at every lookup in this module (an absent config hash refuses, an absent metric
        raises). So both are dropped and the name reads as absent."""
        recs = _honest_copy(self.recs)
        for r in recs:
            ih = {k: v for k, v in r.provenance.input_hashes.items()}
            ih[_key_liar("config", "a_second_config")] = "9" * 64      # stores 'config' too
            object.__setattr__(r.provenance, "input_hashes", ih)
            self.assertEqual(sorted(str.__str__(k) for k in ih).count("config"), 2)
        rv = bm.verdict_from_records(recs, SMALL)
        self.assertEqual(rv.joint, J.JOINT_INCONCLUSIVE)
        self.assertIsNone(rv.config_hash)
        self.assertIn("no stored config hash on at least one record", rv.reasons[0])
        self.assertEqual(bm._word_keyed({"a": 1, _key_liar("a", "b"): 2}), {})
        self.assertEqual(bm._word_keyed({"a": 1, "b": 2}), {"a": 1, "b": 2})

    def test_a_non_string_key_names_nothing_and_a_hostile_mapping_is_refused(self):
        """The other two fail-closed cases of the admission, which `toy.dashboard._word_keyed` settled for
        the render lane: a key that is not a string names nothing this module looks up, and a `Mapping`
        whose `items()` raises is REFUSED (every lookup reads absent, which this module's callers answer
        with a named error) rather than taking an unrelated exception out of the error contract."""
        self.assertEqual(bm._word_keyed({1: "x", None: "y", "ok": "z"}), {"ok": "z"})

        class Hostile(collections.abc.Mapping):
            def items(self):
                raise RuntimeError("no")

            def __getitem__(self, k):
                raise KeyError(k)

            def __iter__(self):
                return iter(())

            def __len__(self):
                return 0

        self.assertEqual(bm._word_keyed(Hostile()), {})
        self.assertEqual(bm._word_keyed(object()), {})
        self.assertEqual(bm._word_keyed(None), {})

    def test_the_by_tag_is_cut_out_of_the_characters_the_record_name_stores(self):
        """`by["JOINT"]`, the third name the brief listed, measured rather than fixed on suspicion.
        `by`'s keys are NOT the caller's objects: `str.rsplit` on a subclass returns plain `str` slices
        (asserted below), so a `str`-subclass name cannot re-point the slot by `__eq__` alone. The route
        that exists is an OVERRIDDEN `rsplit`/`__contains__`, and MEASURED pre-fix it was already
        fail-closed -- but by an ACCIDENT of the 1:1 record set, not by reading: all seven tags are
        required, so moving one record into another's slot empties its own and raises `records missing
        for [...]`. The tag is now cut out of `_stored_word(r.name)`, which closes it by construction and
        leaves the accident doing no work."""
        self.assertEqual([type(x) for x in str.rsplit(_key_liar("a/agg/H1", "zz"), "/agg/", 1)],
                         [str, str])

        liar_tag = _key_liar("H1", "JOINT")

        class NameLiar(str):
            def __contains__(self, other):
                return True

            def rsplit(self, *args, **kwargs):
                return ["evalproto/d", liar_tag]

        recs = _honest_copy(self.recs)
        index = next(i for i, r in enumerate(recs) if str.__str__(r.name).endswith("/agg/H1"))
        object.__setattr__(recs[index], "name", NameLiar(str.__str__(recs[index].name)))
        self.assertEqual(_recompute_outcome(recs, SMALL), _recompute_outcome(_honest_copy(self.recs),
                                                                            SMALL),
                         "the tag must be the word the name stores, so the forgery is a no-op")

    def test_the_seed_scores_key_set_check_only_closed_the_displacing_forgery(self):
        """SeedScores, measured rather than assumed closed. `set(self.metrics) != set(SEED_METRICS)` is
        itself `__hash__`/`__eq__` on the caller's keys, and it refuses a DISPLACING liar (a key storing
        'S' that answers as 'E_loss_ratio' leaves 'S' absent). MEASURED pre-fix through this PUBLIC
        constructor with no `object.__setattr__`: a key storing 'junk' that answers as 'E_loss_ratio' was
        ACCEPTED, so gate 11(c) decided the E-loss check on a number the record then files under 'junk' --
        `seed_records` copies the key verbatim, so the audit trail shows no E_loss_ratio at all."""
        good = bm.MetricValue.measured(1.0)
        base = {k: good for k in bm.SEED_METRICS}
        displacing = dict(base)
        displacing[_key_liar("S", "E_loss_ratio")] = displacing.pop("S")
        with self.assertRaises(ValueError):
            bm.SeedScores(1, displacing)
        invented = dict(base)
        invented.pop("E_loss_ratio")
        invented[_key_liar("junk", "E_loss_ratio")] = good
        with self.assertRaises(ValueError) as caught:
            bm.SeedScores(1, invented)
        self.assertIn("metrics must have exactly keys", str(caught.exception))
        ok = bm.SeedScores(1, dict(base))
        self.assertEqual({type(k) for k in ok.metrics}, {str})


class TheKeyLaneSweepIsDerivedFromTheModuleNotFromAList(unittest.TestCase):
    """THE AST TRIPWIRE behind the payload walk, and the reason `input_hashes` could come back at all:
    round 6 normalised the values of the site it remembered, and nothing enumerated the sites.

    Every place `benchmark.py` looks a WORD up in a mapping it reaches THROUGH A FIELD is collected from
    the AST and checked against `bm.KEY_LANE_ATTRIBUTE_LOOKUPS`, which is declared IN THE MODULE so that
    nothing is listed in this test file and a new lookup fails closed. F-STRING keys are collected as well
    as literals, which is not decoration: `gm.get(f"gate_{n}")` is the site that turned a FAILED global
    gate into a passing one, and the first sweep written for this round -- `ast.Constant` subscripts
    only -- did not see it. MEASURED: 42 literal-key sites and one
    f-string site, which is the one that turned the gate."""

    @staticmethod
    def _annotation_nodes(tree):
        out = set()
        for node in ast.walk(tree):
            for field in ("annotation", "returns"):
                sub = getattr(node, field, None)
                if sub is not None:
                    out.update(id(n) for n in ast.walk(sub))
        return out

    @classmethod
    def _word_lookups(cls, source):
        """(line, container source, key source, is_fstring) for every mapping lookup with a STRING or
        F-STRING key, in all three spellings a module can write one: `m[k]`, `m.get(k)` and `k in m`.

        `is_fstring` comes from the AST NODE TYPE, not from sniffing the unparsed key text -- the first
        version of this test asked `"f'" in key` and the literal `'C_shuf'` matched it, which is the same
        class of mistake as every lexical rule this project has retired.
        OUT OF SCOPE, stated so the sweep does not read as larger than it is: a lookup whose key is a
        VARIABLE (`self.metrics[k]`, `series[metric]`). No static rule resolves what word those hold, and
        they are covered instead by the payload walk in `EveryWordLookedUpInAStoredMappingIsSwept`, which
        sees the read however it is spelled because it hooks the mapping rather than the source text."""
        tree = ast.parse(source)
        skip = cls._annotation_nodes(tree)
        found = []

        def wordish(node):
            return ((isinstance(node, ast.Constant) and isinstance(node.value, str))
                    or isinstance(node, ast.JoinedStr))

        def add(node, container, key):
            if id(node) not in skip and wordish(key):
                found.append((node.lineno, ast.unparse(container), ast.unparse(key),
                              isinstance(key, ast.JoinedStr)))

        for node in ast.walk(tree):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and node.func.attr in ("get", "pop", "setdefault") and node.args):
                add(node, node.func.value, node.args[0])
            if isinstance(node, ast.Subscript):
                add(node, node.value, node.slice)
            if (isinstance(node, ast.Compare) and len(node.ops) == 1
                    and isinstance(node.ops[0], (ast.In, ast.NotIn))):
                add(node, node.comparators[0], node.left)
        return found

    def test_every_word_lookup_through_a_field_is_admitted_or_declared(self):
        found = self._word_lookups(_SRC_FILES["benchmark"].read_text())
        through_a_field = sorted({container for _, container, _, _ in found
                                  if "." in container and "(" not in container})
        self.assertEqual(through_a_field, sorted(bm.KEY_LANE_ATTRIBUTE_LOOKUPS),
                         "a word is looked up in a mapping reached through a field that is neither "
                         "admitted by `_word_keyed` nor declared in `KEY_LANE_ATTRIBUTE_LOOKUPS` with "
                         "its reason. Admit it, or write down the measurement that makes it harmless.")
        for container, why in bm.KEY_LANE_ATTRIBUTE_LOOKUPS.items():
            self.assertTrue(why.strip() and len(why) > 40, container)

    def test_the_sites_the_fix_moved_are_no_longer_read_through_a_field(self):
        """The three lookups this round moved, pinned by ABSENCE, so reinstating any of them fails here
        as well as in the payload walk."""
        found = self._word_lookups(_SRC_FILES["benchmark"].read_text())
        containers = {container for _, container, _, _ in found}
        for gone in ("r.metrics", "rec.metrics", "r.provenance.input_hashes", "by['JOINT'].metrics"):
            self.assertNotIn(gone, containers, f"{gone} is read with a word key again; wrap it in "
                                               f"`_word_keyed` as `verdict_from_records` does")
        self.assertIn(("_word_keyed(r.provenance.input_hashes)", "'config'"),
                      {(c, k) for _, c, k, _ in found})

    def test_the_f_string_key_site_is_collected_and_a_constant_only_sweep_misses_it(self):
        """THE SWEEP'S OWN PROOF, and the measurement that justifies collecting `JoinedStr` at all."""
        source = _SRC_FILES["benchmark"].read_text()
        found = self._word_lookups(source)
        fstrings = [(c, k) for _, c, k, is_f in found if is_f]
        self.assertEqual(fstrings, [("gm", "f'gate_{n}'")])
        literals = [f for f in found if not f[3]]
        # 42, not the 44 a first count gave: that one also collected the two string FORWARD
        # REFERENCES `Optional["BenchmarkConfig"]` and `Optional["Margins"]`, which are string
        # Constants inside an annotation and not lookups at all. Annotation subtrees are excluded.
        self.assertEqual(len(literals), 42)
        self.assertNotIn("f'gate_{n}'", {k for _, _, k, _ in literals})

    def test_the_tripwire_fails_on_a_reinstated_unadmitted_lookup(self):
        """NOT VACUOUS: the pre-fix spelling of the defect, fed back in as source text, is reported."""
        source = _SRC_FILES["benchmark"].read_text()
        pre_fix = source.replace(
            'stored = {_word_keyed(r.provenance.input_hashes).get("config") for r in by.values()}',
            'stored = {r.provenance.input_hashes.get("config") for r in by.values()}', 1)
        self.assertNotEqual(pre_fix, source, "the anchor for the mutation is gone; update this test")
        ast.parse(pre_fix)
        containers = {c for _, c, _, _ in self._word_lookups(pre_fix) if "." in c and "(" not in c}
        self.assertIn("r.provenance.input_hashes", containers)
        self.assertNotIn("r.provenance.input_hashes", set(bm.KEY_LANE_ATTRIBUTE_LOOKUPS))


class NoIdentityComparisonAgainstAnEnumMemberStandsUnadmitted(unittest.TestCase):
    """ROUND 10's SR-11 LESSON RUN ON THIS MODULE. `Verdict`, `JointVerdict` and `EvidenceClass` are `str`
    subclasses by construction (`toy.schema._plain_value` depends on it), so `x is Verdict.SUPPORTED` is
    False for an `x` that `==` cannot distinguish from the member. `toy.robustness` answered this with a
    module-wide rewrite to `==`; MEASURED HERE, that answer would have been WRONG for this module, because
    the six sites point in opposite directions and `==` opens three to close one:
        1717 `self.h3.verdict is Verdict.SUPPORTED`      FAIL OPEN -- the gate-12 invariant does not fire
        998 / 1079 / 1089 `v is Verdict.SUPPORTED`       fail CLOSED; `==` makes all three read SUPPORTED
        1713 `h.verdict is not Verdict.INCONCLUSIVE`     fail CLOSED; `!=` lets a decisive hypothesis past
        1977 `r.evidence_class is not EvidenceClass.TOY_RESULT`  fail CLOSED; `!=` accepts a non-member
    So the OPERAND is admitted instead of the operator rewritten: after `_enum_member` the thing compared
    is a real member, both directions are closed at once, and the direction argument -- which has to be
    re-made for every new site -- is not load-bearing anywhere. What is pinned is the module-wide rule."""

    @staticmethod
    def _identity_sites(source):
        enums = {n: c for n, c in vars(bm).items()
                 if isinstance(c, type) and issubclass(c, Enum) and issubclass(c, (str, int))}
        aliases = {n: v for n, v in vars(bm).items()
                   if isinstance(v, Enum) and isinstance(v, (str, int))}

        def member_of(side):
            if (isinstance(side, ast.Attribute) and isinstance(side.value, ast.Name)
                    and side.value.id in enums and side.attr in enums[side.value.id].__members__):
                return f"{side.value.id}.{side.attr}"
            if isinstance(side, ast.Name) and side.id in aliases:
                return f"{side.id} (a module-level alias of {aliases[side.id]!r})"
            return None

        found = []
        for node in ast.walk(ast.parse(source)):
            if not isinstance(node, ast.Compare):
                continue
            for op, right in zip(node.ops, node.comparators):
                if not isinstance(op, (ast.Is, ast.IsNot)):
                    continue
                for side, other in ((node.left, right), (right, node.left)):
                    name = member_of(side)
                    if name is None:
                        continue
                    admitted = (isinstance(other, ast.Call) and isinstance(other.func, ast.Name)
                                and other.func.id in bm.ENUM_ADMISSIONS)
                    found.append((side.lineno, name, admitted, ast.unparse(node)[:90]))
        return sorted(found), sorted(enums)

    def test_every_identity_comparison_stands_behind_a_declared_admission(self):
        sites, enums = self._identity_sites(_SRC_FILES["benchmark"].read_text())
        self.assertEqual(enums, ["EvidenceClass", "JointVerdict", "Verdict"])
        for cls in (bm.Verdict, bm.JointVerdict, EvidenceClass):      # the premise of the whole rule
            self.assertTrue(issubclass(cls, str), cls)
            for member in cls:
                self.assertIs(cls(str.__str__(member)), member, "the admission resolves by stored chars")
        unadmitted = [s for s in sites if not s[2]]
        self.assertEqual(unadmitted, [], "an identity comparison against a str-backed Enum member does "
                                         "not admit its other operand: wrap it in `_enum_member`, or "
                                         "state at the site why the object cannot be a non-member")
        self.assertEqual(len(sites), 6, sites)

    def test_the_sweep_sees_the_six_pre_fix_lines_it_exists_for(self):
        """NOT VACUOUS: the six pre-fix spellings, fed back in as source, are all reported unadmitted."""
        pre_fix = ("def f(self, vs, r, h):\n"
                   "    if all(v is Verdict.SUPPORTED for v in vs):\n"
                   "        pass\n"
                   "    elif not all(v is Verdict.SUPPORTED for v in vs):\n"
                   "        pass\n"
                   "    elif not all(c.verdict is Verdict.SUPPORTED for c in self.converged):\n"
                   "        pass\n"
                   "    bad = [h.hid for h in vs if h.verdict is not Verdict.INCONCLUSIVE]\n"
                   "    if self.h3.verdict is Verdict.SUPPORTED:\n"
                   "        pass\n"
                   "    if r.evidence_class is not EvidenceClass.TOY_RESULT:\n"
                   "        pass\n")
        sites, _ = self._identity_sites(pre_fix)
        self.assertEqual(len(sites), 6, sites)
        self.assertEqual([s for s in sites if s[2]], [], "none of the six admits its operand")
        admitted = pre_fix.replace("v is Verdict.SUPPORTED",
                                   "_enum_member(Verdict, v) is Verdict.SUPPORTED")
        self.assertEqual([s for s in self._identity_sites(admitted)[0] if not s[2]][0][1],
                         "Verdict.SUPPORTED")

    def test_the_gate_12_invariant_refuses_an_unadmittable_verdict_rather_than_reading_it(self):
        """THE FAIL-OPEN SITE, measured. A `str` subclass answering True to `Verdict.SUPPORTED` passed
        `is Verdict.SUPPORTED` as False, so the invariant 'gate 12 (convergence) failed => H3 cannot be
        SUPPORTED' did not fire -- and `combine_joint` then coerced the SAME object with `Verdict(h3)`
        and reported JOINT_SUPPORTED. Admitting the operand alone is NOT enough here and that is the
        point of the extra refusal: `_enum_member` returns None for the liar, and `None is
        Verdict.SUPPORTED` is also False. The construction is refused instead."""
        class VerdictLiar(str):
            def __eq__(self, other):
                return other == bm.Verdict.SUPPORTED.value or other is bm.Verdict.SUPPORTED

            def __ne__(self, other):
                return not self.__eq__(other)

            def __hash__(self):
                return hash(bm.Verdict.SUPPORTED.value)

        liar = VerdictLiar("not-a-member")
        self.assertTrue(liar == bm.Verdict.SUPPORTED)
        self.assertIsNot(liar, bm.Verdict.SUPPORTED)
        self.assertIsNone(bm._enum_member(bm.Verdict, liar))
        self.assertIs(bm._enum_member(bm.Verdict, bm.Verdict.SUPPORTED), bm.Verdict.SUPPORTED)

        res = bm.run_study(FZ, bm.fixture_oracle_gated, subject="oracle_gated",
                           registered_digest=FZ.digest, cfg=SMALL)
        gates = tuple(bm.GateResult(g.name, False if g.name == "convergence" else g.passed,
                                    g.reason, exempt=g.exempt) for g in res.gates)
        fields = (res.subject, res.h1, res.h2, res.h3, gates, res.seed_scores, res.ineligible,
                  res.n_attempted, res.n_failed, res.seed_list_digest, res.registered_digest,
                  res.config_hash, res.margins, res.subject_kind, res.fixture_name)
        with self.assertRaises(ValueError) as caught:               # the honest reference: it fires
            bm.JointResult(*fields)
        self.assertIn("gate 12 (convergence) failed", str(caught.exception))
        object.__setattr__(res.h3, "verdict", liar)
        with self.assertRaises(ValueError) as caught:               # and the liar is refused, not read
            bm.JointResult(*fields)
        self.assertIn("is not a Verdict member", str(caught.exception))

    def test_an_evidence_class_that_merely_compares_equal_is_still_refused(self):
        """The admission must not be WEAKER than the `is not` it replaced: `isinstance(x, cls)` is
        required first, so a plain `str` 'TOY_RESULT' and an `__eq__` forgery both read as None."""
        class ClassLiar(str):
            def __eq__(self, other):
                return True

            def __ne__(self, other):
                return False

            def __hash__(self):
                return hash("TOY_RESULT")

        self.assertIsNone(bm._enum_member(EvidenceClass, ClassLiar("TOY_RESULT")))
        self.assertIsNone(bm._enum_member(EvidenceClass, "TOY_RESULT"))
        self.assertIs(bm._enum_member(EvidenceClass, EvidenceClass.TOY_RESULT), EvidenceClass.TOY_RESULT)
        res = bm.run_study(FZ, bm.fixture_oracle_gated, subject="oracle_gated",
                           registered_digest=FZ.digest, cfg=SMALL)
        recs = _honest_copy(bm.to_experiment_records(res, study_id="e", base_seed=7,
                                                     timestamp_utc="2025-01-02T03:04:05Z"))
        object.__setattr__(recs[0], "evidence_class", ClassLiar("TOY_RESULT"))
        with self.assertRaises(ValueError) as caught:
            bm.verdict_from_records(recs, SMALL)
        self.assertIn("only TOY_RESULT records can carry a recomputed verdict", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
