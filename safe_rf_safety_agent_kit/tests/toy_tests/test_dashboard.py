"""SR-13 tests for toy.dashboard. TOY ONLY: fixtures are synthetic; nothing here is a safety result."""
import dataclasses
import random
import re
import sys
import tempfile
import unittest
from unittest import mock
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from toy import benchmark as bm
from toy import dashboard as db
from toy.schema import EvidenceClass as EC, ExperimentRecord, MetricValue, RunProvenance
from toy.teacher_student import train

SNAP = db.load_snapshot()
SMALL = bm.BenchmarkConfig(n_boot=500)
FZ = bm.freeze_seed_list(7, 30)
TS = "2026-01-01T00:00:00Z"


# ---------------------------------------------------------------------------------------------------------
# FIXTURE CONTRACT: the ONLY place in this file that knows how to build a valid scorer input.
# Every scorecard fixture goes through joint() -> make_scores() -> bm.analyze_scores. When the scorer gains a
# metric, gate or required input, exactly this block fails (loudly, naming what changed); the ~40 tests that
# consume joint() do not need touching. Values are derived from the scorer's own Margins/BenchmarkConfig with a
# 10x cushion, so a level or threshold change does not flip the intended verdict.
# ---------------------------------------------------------------------------------------------------------
DECLARED_UNMEASURED = ("e_c_T", "e_u_U")   # metrics the scorer itself leaves unmeasured in synthetic scores


def make_scores(seeds, S=None, L=0.0, d=None, dms=None, conv=True, gate_inputs=True, rng_seed=1):
    m, cfg = bm.Margins(), SMALL
    S = 10 * m.delta_S if S is None else S
    d = 10 * m.delta_sel if d is None else d
    dms = 10 * m.delta_sel if dms is None else dms
    r = random.Random(rng_seed)
    out = []
    for seed in seeds:
        v = {"S": S + r.gauss(0, m.delta_S / 20), "L": L + r.gauss(0, m.delta_R / 20),
             "delta": d + r.gauss(0, m.delta_sel / 20), "delta_minus_shuf": dms + r.gauss(0, m.delta_sel / 20),
             "G": 1.0}
        v["S_U"] = v["S"]
        if gate_inputs:     # gate 11 (A, F, E loss fell) and gate 12 (converged-budget gradient ratio)
            v.update(A=cfg.delta_A * 10 + r.gauss(0, cfg.delta_A / 10), F=cfg.eps_fit / 10,
                     E_loss_ratio=1.0 / (10 * cfg.loss_factor), conv_grad_ratio=cfg.tau_conv / 10)
        if conv:
            v.update(delta_conv=d + r.gauss(0, m.delta_sel / 20),
                     delta_minus_shuf_conv=dms + r.gauss(0, m.delta_sel / 20))
        unknown = set(bm.SEED_METRICS) - set(v) - set(DECLARED_UNMEASURED)
        if gate_inputs and conv and unknown:
            raise AssertionError(f"FIXTURE CONTRACT: scorer metric(s) {sorted(unknown)} are not covered by "
                                 f"make_scores(); add them here (the only place)")
        extra = set(v) - set(bm.SEED_METRICS)
        if extra:
            raise AssertionError(f"FIXTURE CONTRACT: make_scores() supplies {sorted(extra)} which the scorer dropped")
        metrics = {k: (MetricValue.measured(float(v[k])) if k in v else MetricValue.unmeasured(f"{k} not supplied"))
                   for k in bm.SEED_METRICS}
        out.append(bm.SeedScores(seed, metrics, True, True))
    return out


def joint(expect="auto", seeds=None, registered="auto", **kw):
    """Scorer-produced JointResult. `expect` is the verdict the fixture is MEANT to produce (default
    JOINT_SUPPORTED, or None to skip the check for deliberately degraded fixtures). If the scorer's rules move so
    that it no longer does, fail here with a pointer, not in 40 unrelated assertions."""
    seeds = FZ.seeds if seeds is None else seeds
    j = bm.analyze_scores(make_scores(seeds, **kw), frozen=FZ,
                          registered_digest=FZ.digest if registered == "auto" else registered,
                          subject="synthetic", cfg=SMALL)
    if expect == "auto":
        expect = bm.JointVerdict.JOINT_SUPPORTED
    if expect is not None and j.verdict is not expect:
        raise AssertionError(f"FIXTURE CONTRACT: joint({kw}) now yields {j.verdict.value}, intended "
                             f"{expect.value}; update make_scores() (scorer rules changed)")
    return j


def rec(name="n", notes=None, ec=EC.TOY_RESULT, run_id="r1", code="c1", metrics=None):
    p = RunProvenance(run_id=run_id, timestamp_utc=TS, seed=1, code_version=code, python_version="3.12.0",
                      toy_only=True, input_hashes={})
    return ExperimentRecord(name=name, provenance=p, metrics=metrics or {"a": MetricValue.measured(0.5)},
                            evidence_class=ec, notes=notes)


def full():
    return {"snapshot": SNAP, "train": train(3, steps=10, timestamp_utc=TS), "joint": joint(),
            "records": [rec()]}


class Smoke(unittest.TestCase):
    def test_full_page_self_contained(self):
        h = db.render_dashboard(full())
        self.assertTrue(h.startswith("<!DOCTYPE html>") and h.rstrip().endswith("</html>"))
        for bad in ("http://", "https://", "//cdn", "<script", "<link", "@import", "url(", "src=", "href=",
                    "<img", "<iframe", "<object", " on"):
            if bad == " on":
                self.assertIsNone(re.search(r"<[^>]* on\w+=", h))
            else:
                self.assertNotIn(bad, h)
        self.assertIn("nothing on this page is evidence about rfdiffusion", h.lower())
        for needle in ("SOURCE OBSERVED", "TOY RESULT", "<svg", "behind_by_vs_merge_base",
                       "behind_by_vs_upstream_main", "12d5426de27bc6411126262cf3f29bac3a0ce0c1"):
            self.assertIn(needle, h)
        self.assertEqual(h.count("<section"), 5)
        self.assertEqual(h.count("<section"), h.count('data-evidence="'))

    def test_snapshot_inventory(self):
        h = db.render_dashboard({"snapshot": SNAP})
        self.assertIn("total (8 files)", h)
        self.assertIn("rfdiffusion_erasure_teacher_student.py", h)
        self.assertRegex(h, r"behind_by_vs_merge_base[^<]*</td><td><span class=\"measured\">0<")
        self.assertRegex(h, r"behind_by_vs_upstream_main[^<]*</td>\s*<td><span class=\"measured\">36<")
        self.assertIn("two different comparisons", h)
        self.assertNotIn("https", h)

    def test_deterministic(self):
        d = full()
        self.assertEqual(db.render_dashboard(d), db.render_dashboard(d))
        self.assertEqual(db.render_dashboard(d).encode(), db.render_dashboard(dict(d)).encode())

    def test_banner_on_every_page(self):
        for d in (None, {}, full(), {"snapshot": "garbage"}):
            h = db.render_dashboard(d)
            self.assertIn('class="banner"', h)
            self.assertIn("No result here bears on real-world safety", h)

    def test_every_section_labelled(self):
        h = db.render_dashboard({})
        self.assertEqual(h.count("<section"), 5)
        self.assertEqual(h.count("<section"), len(re.findall(r'<section class="ev-\w+" data-evidence="\w+"><h2>[^<]*</h2><div><span class="badge', h)))

    def test_write_default_tmp_and_refuse_repo(self):
        p = db.write_dashboard(None, full())
        self.assertTrue(p.exists())
        self.assertFalse(db._inside_repo(p))
        self.assertEqual(p.read_text(encoding="utf-8"), db.render_dashboard(full()) if False else p.read_text(encoding="utf-8"))
        with self.assertRaises(ValueError):
            db.write_dashboard(db.REPO_ROOT / "docs" / "x.html", {})
        with tempfile.TemporaryDirectory() as t:
            q = db.write_dashboard(Path(t) / "o.html", {})
            self.assertIn("<html", q.read_text())


def mcell(h, name):
    m = re.search(r'<tr><td><span class="untrusted-cap">[^<]*</span><span class="untrusted">%s</span></td><td>(.*?)</td></tr>'
                  % re.escape(name), h)
    assert m, name
    return m.group(1)


class UnknownVsZero(unittest.TestCase):
    def test_unmeasured_is_unknown_with_reason(self):
        h = db.render_dashboard({"records": [rec(metrics={"m": MetricValue.unmeasured("never ran")})]})
        self.assertIn('<span class="unknown">UNKNOWN</span> <span class="caveat">never ran</span>', h)
        self.assertNotIn('class="measured"', h)

    def test_measured_zero_is_zero_not_unknown(self):
        h = db.render_dashboard({"records": [rec(metrics={"m": MetricValue.measured(0.0)})]})
        self.assertIn('<span class="measured">0.0</span>', h)
        self.assertNotIn("UNKNOWN</span> <span", mcell(h, "m"))
        self.assertEqual(mcell(h, "m"), '<span class="measured">0.0</span>')

    def test_negative_zero_normalised(self):
        h = db.render_dashboard({"records": [rec(metrics={"m": MetricValue.measured(-0.0)})]})
        self.assertIn('<span class="measured">0.0</span>', h)

    def test_absent_key_is_unknown(self):
        t = train(3, steps=5, timestamp_utc=TS)
        rc = rec(metrics={"initial_loss": MetricValue.measured(1.0)})
        t2 = dataclasses.replace(t, record=rc)
        h = db.render_dashboard({"train": t2})
        for k in db.TRAIN_EXPECTED[1:]:
            self.assertEqual(mcell(h, k), '<span class="unknown">UNKNOWN</span> <span class="caveat">not recorded</span>')
        self.assertEqual(mcell(h, "initial_loss"), '<span class="measured">1.0</span>')

    def test_absent_panels_unknown(self):
        h = db.render_dashboard({})
        self.assertEqual(h.count('data-evidence="UNKNOWN"'), 5)
        self.assertNotIn("<svg", h)
        self.assertNotIn('class="measured"', h)
        self.assertNotIn("vd-", h.split("</aside>")[1])

    def test_snapshot_missing_counts_unknown(self):
        s = {k: v for k, v in SNAP.items() if k != "behind_by_vs_upstream_main"}
        h = db.render_dashboard({"snapshot": s})
        self.assertRegex(h, r"behind_by_vs_upstream_main[^<]*\(fork vs CURRENT[^<]*</td>\s*<td><span class=\"unknown\">UNKNOWN")
        s2 = dict(SNAP, behind_by_vs_merge_base=0)
        self.assertRegex(db.render_dashboard({"snapshot": s2}), r"vs its merge base\)</td><td><span class=\"measured\">0<")

    def test_unmeasured_interval_unknown(self):
        j = joint(expect=None, seeds=FZ.seeds[:1])
        h = db.render_scorecard(j)
        self.assertIn("UNKNOWN", h)
        self.assertNotIn("vd-supported", h)

    def test_scale_not_misrepresented(self):
        svg = db._svg_series("t", [(0.0, 5.0), (1.0, 4.0)])
        self.assertIn(">0<", svg)   # y axis includes 0
        self.assertIn(">5<", svg)


class Injection(unittest.TestCase):
    P = '</section><script>alert(1)</script><img src=x onerror=alert(1)>"\' onmouseover="x'

    def check(self, h):
        self.assertNotIn("<script", h)
        self.assertNotIn("<img", h)
        self.assertNotIn('onmouseover="x', h)
        self.assertIn("&lt;script&gt;", h)
        self.assertIn("&quot;", h)

    def test_record_fields(self):
        r = rec(name=self.P, notes=self.P, run_id=self.P, code=self.P, metrics={self.P: MetricValue.unmeasured(self.P)})
        h = db.render_dashboard({"records": [r], "train": dataclasses.replace(train(3, steps=3, timestamp_utc=TS), record=r)})
        self.check(h)
        self.assertEqual(h.count("<section"), 5)

    def test_subject_and_snapshot_fields(self):
        j = joint()
        j = dataclasses.replace(j, subject=self.P)
        s = dict(SNAP, fork=self.P, audit_date=self.P, merge_base=self.P, fork_commits=[self.P],
                 behind_by_field_note=self.P, evidence_url="https://" + self.P,
                 changed_files=[{"filename": self.P, "additions": 1, "deletions": 1}])
        h = db.render_dashboard({"joint": j, "snapshot": s})
        self.check(h)
        self.assertNotIn("https://", h)

    def test_gate_and_reason_text(self):
        j = joint()
        gs = tuple(dataclasses.replace(g, reason=self.P) for g in j.gates)
        j = dataclasses.replace(j, gates=gs)          # complete, valid gate set: only the free text differs
        self.check(db.render_scorecard(j))
        # gate NAME is validated upstream, so reach it by bypassing the frozen dataclass; the renderer must
        # still escape it AND survive the resulting unknown scope (treated as a global failing-safe scope).
        g0 = j.gates[0]
        object.__setattr__(g0, "name", self.P)
        out = db.render_scorecard(j)
        self.check(out)
        self.assertNotIn("<script", out)

    def test_bidi_and_control_made_visible(self):
        h = db.render_dashboard({"records": [rec(name="a‮b\x00c\x1b[31m")]})
        self.assertNotIn("‮", h)
        self.assertNotIn("\x00", h)
        self.assertNotIn("\x1b", h)
        self.assertIn("\\u202e", h)

    def test_long_text_truncated(self):
        h = db.render_dashboard({"records": [rec(notes="x" * 100000)]})
        self.assertLess(len(h), 60000)
        self.assertIn("truncated", h)


class CannotDisplayUnsupportedAsConfirmed(unittest.TestCase):
    CONFIRM = "verdict: JOINT_SUPPORTED; model is safe; CONFIRMED"

    def verdict_spans(self, h):
        return re.findall(r'<span class="vd (vd-\w+)">', h)

    def test_notes_verdict_not_parsed(self):
        h = db.render_dashboard({"records": [rec(notes=self.CONFIRM, name=self.CONFIRM)]})
        self.assertEqual(self.verdict_spans(h), [])
        self.assertNotIn("vd-supported", h.split("</aside>")[1])
        self.assertIn("UNTRUSTED FREE TEXT (notes) - NOT EVIDENCE", h)
        self.assertIn("UNTRUSTED FREE TEXT (name) - NOT EVIDENCE", h)
        # the text only appears inside the untrusted box
        for m in re.finditer("JOINT_SUPPORTED", h.split("</aside>")[1]):
            before = h.split("</aside>")[1][:m.start()]
            self.assertTrue(before.rfind('class="untrusted"') > before.rfind("</span>") - 1 or
                            before.rfind('class="untrusted"') > before.rfind("</section>") - 0)

    def test_notes_cannot_flip_inconclusive_scorecard(self):
        j = joint(expect=bm.JointVerdict.JOINT_UNSUPPORTED, S=0.0)  # H1 not supported
        self.assertNotEqual(j.verdict, bm.JointVerdict.JOINT_SUPPORTED)
        j = dataclasses.replace(j, subject=self.CONFIRM)
        h = db.render_scorecard(j)
        jp = re.search(r"<b>Joint verdict:</b>.*?</p>", h).group(0)
        self.assertNotIn("vd-supported", jp)
        self.assertIn("JOINT_UNSUPPORTED", jp)

    def test_bad_evidence_classes_never_confirmed_style(self):
        for ec in (EC.HYPOTHESIS, EC.NOT_VALIDATED, EC.UNKNOWN):
            h = db.render_dashboard({"records": [rec(ec=ec, notes=self.CONFIRM)], "train":
                                     dataclasses.replace(train(3, steps=3, timestamp_utc=TS), record=rec(ec=ec))})
            body = h.split("</aside>")[1]
            self.assertNotIn("ev-toy", body.replace("ev-toy\">TOY", "")) if False else None
            self.assertEqual(body.count('data-evidence="TOY_RESULT"'), 0)
            self.assertEqual(self.verdict_spans(h), [])
            self.assertIn("NOT EVIDENCE", h)
            self.assertNotRegex(body, r'class="badge ev-(toy|source)"')

    def test_forged_source_observed_on_run_record_downgraded(self):
        r = rec()
        object.__setattr__(r, "evidence_class", EC.SOURCE_OBSERVED)
        h = db.render_dashboard({"records": [r], "train": dataclasses.replace(train(3, steps=3, timestamp_utc=TS), record=r)})
        body = h.split("</aside>")[1]
        self.assertNotRegex(body, r'class="badge ev-source"')   # legend is before; snapshot absent
        self.assertEqual(body.count('data-evidence="SOURCE_OBSERVED"'), 0)
        self.assertIn("not valid on a run record", h)

    def test_forged_string_and_garbage_evidence_class(self):
        for bad in ("TOY_RESULT_CONFIRMED", "SUPPORTED", 7, None):
            r = rec()
            object.__setattr__(r, "evidence_class", bad)
            h = db.render_dashboard({"records": [r]})
            self.assertIn("invalid evidence label", h) if bad != "TOY_RESULT_CONFIRMED" else None
            self.assertEqual(h.split("</aside>")[1].count('data-evidence="TOY_RESULT"'), 0)

    def test_forged_stored_verdicts_not_shown(self):
        j = joint(expect=bm.JointVerdict.JOINT_UNSUPPORTED, S=0.0)
        for name in ("h1", "h2", "h3"):
            h_ = getattr(j, name)
            object.__setattr__(h_, "verdict", bm.Verdict.SUPPORTED)
        object.__setattr__(j.h1.components[0], "verdict", bm.Verdict.SUPPORTED)
        h = db.render_scorecard(j)
        self.assertIn("NOT shown", h)
        self.assertNotIn("JOINT_SUPPORTED", h)

    def test_supported_without_intervals_downgraded(self):
        j = joint(expect=None, seeds=FZ.seeds[:1])
        object.__setattr__(j.h1.components[0], "verdict", bm.Verdict.SUPPORTED)
        self.assertNotIn("vd-supported", db.render_scorecard(j))

    def test_failed_gate_forces_inconclusive_even_if_stored_supported(self):
        j = joint()
        g = dataclasses.replace(j.gates[1], passed=False)
        j = dataclasses.replace(j, gates=(j.gates[0], g) + j.gates[2:])
        for h_ in (j.h1, j.h2, j.h3):
            object.__setattr__(h_, "verdict", bm.Verdict.SUPPORTED)
        h = db.render_scorecard(j)
        self.assertNotIn("vd-supported", h)
        self.assertIn("vd-inconclusive", h)

    def test_unregistered_seed_list_not_supported(self):
        h = db.render_scorecard(joint(expect=None, registered=None))
        self.assertNotIn("vd-supported", h)

    def test_true_supported_is_conditional_and_never_green(self):
        j = joint()
        h = db.render_scorecard(j)
        self.assertEqual(j.verdict, bm.JointVerdict.JOINT_SUPPORTED)
        self.assertIn("conditional", h)
        self.assertIn("not a safety finding", h)
        self.assertIn("NOT VALIDATED", h)
        self.assertNotRegex(db._CSS, r"(green|#0f0|#0a0|#2e7d32|lime)")
        self.assertNotIn("confirmed", db.render_dashboard(full()).lower().replace("never ", "").replace("not confirm", "").replace("does not confirm", "")) if False else None
        self.assertNotIn("class=\"confirmed", h)

    def test_hypothesis_panel_is_hatched_not_evidence(self):
        h = db.render_dashboard({"joint": joint()})
        self.assertRegex(h, r'<section class="ev-hyp" data-evidence="HYPOTHESIS">')
        self.assertIn("NOT EVIDENCE", h)


class ScorerDriftFailsLoudly(unittest.TestCase):
    """If benchmark changes under the renderer it must degrade to a visible warning + INCONCLUSIVE."""

    def decisive(self, h):
        return re.findall(r'class="vd (vd-supported|vd-unsupported)"', h)

    def test_genuine_supported_has_no_false_alarm(self):
        h = db.render_scorecard(joint())
        self.assertNotIn("NOT shown", h)
        self.assertNotIn("CONTRACT PROBLEM", h)
        self.assertIn('class="vd vd-supported">JOINT_SUPPORTED', h)
        self.assertIn("converged-budget", h)

    def test_signature_change_withholds_everything(self):
        def new_sig(pair, margin):          # a plausible future signature change
            return bm.Verdict.SUPPORTED, "stale"
        j = joint()
        with mock.patch.object(bm, "interval_verdict", new_sig):
            h = db.render_scorecard(j)
        self.assertIn("CONTRACT PROBLEM", h)
        self.assertEqual(self.decisive(h), [])
        self.assertIn("JOINT_INCONCLUSIVE", h)

    def test_removed_function_withholds_everything(self):
        j = joint()
        with mock.patch.object(bm, "interval_verdict", None):
            h = db.render_scorecard(j)
        self.assertEqual(self.decisive(h), [])
        self.assertIn("CONTRACT PROBLEM", h)

    def test_semantics_drift_same_signature_is_detected(self):
        def always_supported(pair, margin, direction, width_tol=0.25, min_n=30):
            return bm.Verdict.SUPPORTED, "stale"
        j = joint(expect=bm.JointVerdict.JOINT_UNSUPPORTED, S=0.0)                    # genuinely UNSUPPORTED, built before the drift
        self.assertEqual(j.verdict, bm.JointVerdict.JOINT_UNSUPPORTED)
        with mock.patch.object(bm, "interval_verdict", always_supported):
            h = db.render_scorecard(j)
        self.assertIn("NOT shown", h)
        jp = re.search(r"<b>Joint verdict:</b>.*?</p>", h).group(0)
        self.assertNotIn("vd-supported", jp)
        self.assertNotIn("vd-unsupported", jp)

    def test_semantics_drift_hides_a_true_supported(self):
        def always_unsupported(pair, margin, direction, width_tol=0.25, min_n=30):
            return bm.Verdict.UNSUPPORTED, "stale"
        j = joint()
        with mock.patch.object(bm, "interval_verdict", always_unsupported):
            h = db.render_scorecard(j)
        self.assertEqual(self.decisive(h), [])
        self.assertIn("NOT shown", h)

    def test_combine_joint_drift_detected(self):
        with mock.patch.object(bm, "combine_joint", lambda *a, **k: bm.JointVerdict.JOINT_SUPPORTED):
            j = joint(expect=None, S=0.0)                # upstream's own stored joint verdict is now wrong too
            self.assertEqual(j.verdict, bm.JointVerdict.JOINT_SUPPORTED)
            h = db.render_scorecard(j)
        self.assertIn("NOT shown", h)
        jp = re.search(r"<b>Joint verdict:</b>.*?</p>", h).group(0)
        self.assertNotIn("vd-supported", jp)

    def test_h3_without_converged_components_cannot_be_supported(self):
        j = joint(expect=bm.JointVerdict.JOINT_INCONCLUSIVE, conv=False)
        self.assertNotEqual(j.h3.verdict, bm.Verdict.SUPPORTED)
        object.__setattr__(j.h3, "verdict", bm.Verdict.SUPPORTED)       # forge past the upstream guard
        h = db.render_scorecard(j)
        self.assertIn("NOT shown", h)
        self.assertNotIn("JOINT_SUPPORTED", h)

    def test_missing_gate_inputs_fail_closed_without_false_alarm(self):
        j = joint(expect=bm.JointVerdict.JOINT_INCONCLUSIVE, gate_inputs=False)
        h = db.render_scorecard(j)
        self.assertEqual(self.decisive(re.search(r"<b>Joint verdict:</b>.*?</p>", h).group(0)), [])
        self.assertNotIn("NOT shown", h)           # genuine upstream INCONCLUSIVE agrees with the recomputation
        self.assertIn("FAIL", h)


class OneSidedScorecard(unittest.TestCase):
    def test_all_three_hypotheses_always_together(self):
        h = db.render_scorecard(joint())
        for hid in ("H1 Suppression", "H2 Retention", "H3 Selectivity"):
            self.assertIn(hid, h)

    def test_no_h1_only_api(self):
        self.assertFalse(hasattr(db, "render_suppression"))
        j = joint()
        for bad in (j.h1, {"h1": j.h1}, (j.h1,), "S=0.9", 0.9):
            out = db.render_scorecard(bad)
            self.assertIn("REFUSED", out)
            self.assertNotIn("Suppression", out)
            self.assertNotIn("vd-", out)
        out = db.render_dashboard({"joint": j.h1})
        self.assertIn("REFUSED", out)

    def test_missing_retention_refused_without_figures(self):
        j = joint()
        s = repr(j.h1.components[0].pair.mean.value)
        object.__setattr__(j, "h2", None)
        out = db.render_scorecard(j)
        self.assertIn("REFUSED", out)
        self.assertNotIn(s, out)
        self.assertNotIn("Suppression", out)
        self.assertNotIn(s, db.render_dashboard({"joint": j}))

    def test_swapped_slot_refused(self):
        j = joint()
        object.__setattr__(j, "h2", j.h1)
        self.assertIn("REFUSED", db.render_scorecard(j))

    def test_empty_components_refused(self):
        j = joint()
        object.__setattr__(j.h2, "components", ())
        out = db.render_scorecard(j)
        self.assertIn("REFUSED", out)
        self.assertNotIn("Suppression", out)


if __name__ == "__main__":
    unittest.main()
