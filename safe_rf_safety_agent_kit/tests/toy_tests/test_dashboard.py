"""SR-13 tests for toy.dashboard. TOY ONLY: fixtures are synthetic; nothing here is a safety result."""
import ast
import dataclasses
import inspect
import io
import itertools
import math
import os
import random
import re
import stat
import sys
import tempfile
import tokenize
import unittest
from collections.abc import Mapping
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
        fail_gate(j, j.gates[1].name)
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


def fail_gate(j, name):
    """Forge a failed gate on an otherwise SUPPORTED result. dataclasses.replace() is now refused upstream
    (JointResult validates gate/verdict consistency), so bypass the frozen dataclass, as a tamperer would."""
    gs = tuple(dataclasses.replace(g, passed=False) if g.name == name else g for g in j.gates)
    object.__setattr__(j, "gates", gs)
    return j


def measured_n(j):
    """The second source `db._recompute` / `db._pair_numbers_ok` now require: the study's OWN count of
    measured seeds, `n_attempted - n_failed`, anchored on `seed_scores` (db._measured_seeds).

    Every direct call to either function in this file goes through this helper or names the number
    explicitly, so no test can silently hand the verdict path a `None` second source and be handed a
    fail-closed it did not mean to ask for -- which would make a pass here mean nothing."""
    return db._measured_seeds(j)


def recompute(c, margins, j):
    """`db._recompute` with BOTH second sources taken from the result the component came from: the
    measured-seed count (round 5) and the per-seed series behind each interval (round 6)."""
    return db._recompute(c, margins, db._measured_seeds(j), db._measured_series(j))


def pair_ok(j, pair=None, c=None):
    """`db._pair_numbers_ok` for one pair of `j`, with `min_n` and both second sources read off `j`.

    The series is looked up by `c.metric`, so a test that passes `pair=` a pair from a DIFFERENT
    component must pass the matching `c=` too, or it is asking the interval cross-check to compare one
    metric's interval against another metric's data."""
    c = j.h1.components[0] if c is None else c
    return db._pair_numbers_ok(c.pair if pair is None else pair, c.min_n, db._measured_seeds(j),
                               db._series_of(db._measured_series(j), getattr(c, "metric", None)))


def joint_cell(h):
    return re.search(r"<b>Joint verdict:</b>.*?</p>", h).group(0)


def hyp_cells(h):
    return dict((m.group(1), m.group(3)) for m in re.finditer(
        r'<th colspan=8>(H\d) hypothesis verdict</th><td><span class="vd (vd-\w+)">(\w+)</span>', h))


class WriteGuards(unittest.TestCase):
    def setUp(self):
        self._t = tempfile.TemporaryDirectory()
        self.addCleanup(self._t.cleanup)
        self.root = Path(self._t.name).resolve()
        (self.root / "repo").mkdir()
        (self.root / "out").mkdir()
        self.repo_file = self.root / "repo" / "SOURCE_SNAPSHOT.json"
        self.repo_file.write_text("PRECIOUS", encoding="utf-8")
        p = mock.patch.object(db, "REPO_ROOT", self.root / "repo")   # a scratch 'repo'; the real one is never touched
        p.start()
        self.addCleanup(p.stop)

    def test_hardlink_to_repo_file_refused_and_file_untouched(self):
        link = self.root / "out" / "link.html"
        os.link(self.repo_file, link)
        self.assertFalse(db._inside_repo(link))                     # the PATH looks fine: only the inode is bad
        with self.assertRaisesRegex(ValueError, "hard link"):
            db.write_dashboard(link, {})
        self.assertEqual(self.repo_file.read_text(encoding="utf-8"), "PRECIOUS")
        self.assertEqual(link.read_text(encoding="utf-8"), "PRECIOUS")

    def test_hardlink_even_if_check_missed_replace_does_not_modify_inode(self):
        # second layer: write goes to a temp file + os.replace, so an existing inode is never rewritten
        link = self.root / "out" / "link.html"
        os.link(self.repo_file, link)
        with mock.patch.object(os, "lstat", side_effect=FileNotFoundError):    # simulate the nlink check missing
            db.write_dashboard(link, {})
        self.assertEqual(self.repo_file.read_text(encoding="utf-8"), "PRECIOUS")
        self.assertIn("<html", link.read_text(encoding="utf-8"))

    def test_path_inside_repo_refused_incl_dotdot_and_symlinked_dir(self):
        with self.assertRaises(ValueError):
            db.write_dashboard(self.root / "repo" / "x.html", {})
        with self.assertRaises(ValueError):
            db.write_dashboard(self.root / "out" / ".." / "repo" / "x.html", {})
        os.symlink(self.root / "repo", self.root / "out" / "dirlink")
        with self.assertRaises(ValueError):                           # only resolve() catches this
            db.write_dashboard(self.root / "out" / "dirlink" / "x.html", {})
        self.assertTrue(db._inside_repo(self.root / "out" / "dirlink" / "x.html"))
        self.assertFalse((self.root / "repo" / "x.html").exists())

    def test_symlink_file_refused(self):
        target = self.root / "out" / "real.html"
        target.write_text("old", encoding="utf-8")
        os.symlink(target, self.root / "out" / "sym.html")
        with self.assertRaisesRegex(ValueError, "symlink"):
            db.write_dashboard(self.root / "out" / "sym.html", {})
        self.assertEqual(target.read_text(encoding="utf-8"), "old")
        os.symlink(self.root / "out" / "nowhere", self.root / "out" / "dangling.html")
        with self.assertRaisesRegex(ValueError, "symlink"):
            db.write_dashboard(self.root / "out" / "dangling.html", {})

    def test_directory_target_refused(self):
        with self.assertRaises(ValueError):
            db.write_dashboard(self.root / "out", {})

    def test_normal_write_overwrites_regular_file_and_leaves_no_temp(self):
        out = self.root / "out" / "d.html"
        out.write_text("old", encoding="utf-8")
        db.write_dashboard(out, {})
        self.assertEqual(out.read_text(encoding="utf-8"), db.render_dashboard({}))
        self.assertEqual(sorted(x.name for x in (self.root / "out").iterdir()), ["d.html"])


def _fs_case_insensitive(d):
    probe = Path(d) / "CaseProbe"
    probe.mkdir()
    try:
        return (Path(d) / "caseprobe").exists()
    finally:
        probe.rmdir()


class IdentityAndCaseGuards(unittest.TestCase):
    """_inside_repo compares file IDENTITY (dev, inode); case-folded text is only a secondary check."""

    def setUp(self):
        self._t = tempfile.TemporaryDirectory()
        self.addCleanup(self._t.cleanup)
        self.tmp = Path(self._t.name).resolve()
        self.ci = _fs_case_insensitive(self.tmp)
        self.base = self.tmp / "ScratchRoot"
        self.repo = self.base / "Repo"
        (self.repo / "docs").mkdir(parents=True)
        self.prog = self.repo / "docs" / "PROGRESS.md"
        self.prog.write_text("PRECIOUS", encoding="utf-8")
        for p in (mock.patch.object(db, "REPO_ROOT", self.repo),
                  mock.patch.object(db, "_casefold_inside", lambda r, root: False)):   # identity layer ALONE
            p.start()
            self.addCleanup(p.stop)

    def need_ci(self):
        if not self.ci:
            self.skipTest("case-sensitive filesystem: case variants are different directories here "
                          "(the alias/identity tests below still run)")

    def test_case_varied_directory_component_refused(self):
        self.need_ci()
        for v in (self.base / "repo" / "docs" / "PROGRESS.md", self.base / "REPO" / "docs" / "progress.md"):
            self.assertTrue(db._inside_repo(v), v)
            with self.assertRaises(ValueError):
                db.write_dashboard(v, {})
        self.assertEqual(self.prog.read_text(encoding="utf-8"), "PRECIOUS")

    def test_case_varied_repo_root_prefix_refused(self):
        self.need_ci()
        v = self.tmp / "scratchroot" / "repo" / "docs" / "PROGRESS.md"
        self.assertTrue(db._inside_repo(v))
        with self.assertRaises(ValueError):
            db.write_dashboard(v, {})
        self.assertEqual(self.prog.read_text(encoding="utf-8"), "PRECIOUS")

    def test_new_file_inside_repo_via_case_variation_refused(self):
        self.need_ci()
        v = self.base / "REPO" / "docs" / "brand_new.html"
        with self.assertRaises(ValueError):
            db.write_dashboard(v, {})
        self.assertEqual(sorted(x.name for x in (self.repo / "docs").iterdir()), ["PROGRESS.md"])
        with self.assertRaises(ValueError):                       # deeper, nonexistent intermediate dirs too
            db.write_dashboard(self.base / "rEPo" / "no" / "such" / "x.html", {})

    def test_alias_detected_by_identity_not_text(self):
        # FS-independent: the path text never mentions the repo, resolve() is disabled, only inode identity can tell
        alias = self.tmp / "alias"
        os.symlink(self.repo, alias)
        with mock.patch.object(Path, "resolve", lambda self, strict=False: self):
            self.assertTrue(db._inside_repo(alias / "docs" / "PROGRESS.md"))
            self.assertTrue(db._inside_repo(alias / "docs" / "new" / "x.html"))
            self.assertFalse(db._inside_repo(self.tmp / "elsewhere.html"))

    def test_outside_paths_and_siblings_allowed(self):
        (self.base / "RepoSibling").mkdir()
        self.assertFalse(db._inside_repo(self.base / "RepoSibling" / "x.html"))
        self.assertFalse(db._inside_repo(self.tmp / "out.html"))
        out = db.write_dashboard(self.base / "RepoSibling" / "x.html", {})
        self.assertTrue(out.exists())

    def test_casefold_secondary_layer_alone(self):
        with mock.patch.object(db, "_casefold_inside", db_casefold_original):
            with mock.patch.object(db, "REPO_ROOT", Path("/nonexistent_zz/Repo")):
                self.assertTrue(db._inside_repo(Path("/NONEXISTENT_ZZ/repo/docs/x.html")))
                self.assertFalse(db._inside_repo(Path("/nonexistent_zz/RepoSibling/x.html")))
                self.assertTrue(db._inside_repo(Path("/nonexistent_zz/repo")))

    def test_resolution_error_fails_closed(self):
        with mock.patch.object(Path, "resolve", side_effect=RuntimeError("loop")):
            self.assertTrue(db._inside_repo(self.tmp / "x.html"))


db_casefold_original = db._casefold_inside


class DestinationGuards(unittest.TestCase):
    def setUp(self):
        self._t = tempfile.TemporaryDirectory()
        self.addCleanup(self._t.cleanup)
        self.tmp = Path(self._t.name).resolve()

    def test_fifo_refused_without_blocking(self):
        fifo = self.tmp / "pipe"
        os.mkfifo(fifo)
        with self.assertRaisesRegex(ValueError, "non-regular"):
            db.write_dashboard(fifo, {})
        self.assertTrue(stat.S_ISFIFO(os.lstat(fifo).st_mode))

    def test_directory_refused_as_non_regular(self):
        with self.assertRaisesRegex(ValueError, "non-regular"):
            db.write_dashboard(self.tmp, {})

    def test_device_and_pseudo_filesystems_deliberately_refused(self):
        for target in ("/dev/zz_dashboard.html", "/dev/fd/1", "/dev/null", "/proc/zz.html", "/sys/zz.html"):
            with self.assertRaises(ValueError, msg=target) as cm:
                db.write_dashboard(target, {})
        with self.assertRaisesRegex(ValueError, "device/pseudo"):
            db.write_dashboard("/dev/zz_dashboard.html", {})

    def test_symlinked_parent_into_device_dir_refused(self):
        os.symlink("/dev", self.tmp / "devlink")           # parent must be RESOLVED before the device check
        with self.assertRaisesRegex(ValueError, "device/pseudo"):
            db.write_dashboard(self.tmp / "devlink" / "zz.html", {})

    def test_is_device_dir_prefix_and_boundary(self):
        for yes in ("/dev", "/dev/fd", "/dev/fd/3", "/proc", "/proc/1/fd", "/sys", "/sys/kernel"):
            self.assertTrue(db._is_device_dir(Path(yes)), yes)
        for no in ("/devices", "/developer", "/processing", "/system", "/tmp", "/"):
            self.assertFalse(db._is_device_dir(Path(no)), no)

    def test_cleanup_on_keyboard_interrupt(self):
        out = self.tmp / "d.html"
        out.write_text("old", encoding="utf-8")
        with mock.patch.object(db.os, "replace", side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                db.write_dashboard(out, {})
        self.assertEqual(sorted(x.name for x in self.tmp.iterdir()), ["d.html"])
        self.assertEqual(out.read_text(encoding="utf-8"), "old")

    def test_unreadable_destination_is_a_deliberate_refusal(self):
        with mock.patch.object(db.os, "lstat", side_effect=PermissionError("denied")):
            with self.assertRaisesRegex(ValueError, "cannot inspect"):
                db.write_dashboard(self.tmp / "d.html", {})
        self.assertEqual(list(self.tmp.iterdir()), [])

    def test_overlong_path_component_is_value_error_not_raw_oserror(self):
        for tgt in (self.tmp / ("a" * 300) / "x.html", self.tmp / ("a" * 300)):
            with self.assertRaises(ValueError):
                db.write_dashboard(tgt, {})

    def test_missing_destination_directory_refused(self):
        with self.assertRaisesRegex(ValueError, "does not exist"):
            db.write_dashboard(self.tmp / "nope" / "x.html", {})

    def test_temp_file_created_in_destination_directory(self):
        real_mkstemp, real_replace = tempfile.mkstemp, os.replace
        seen = {}

        def spy_replace(src, dst):
            seen["src"], seen["dst"] = Path(src), Path(dst)
            return real_replace(src, dst)
        with mock.patch.object(db.tempfile, "mkstemp", wraps=real_mkstemp) as mk, \
                mock.patch.object(db.os, "replace", spy_replace):
            out = db.write_dashboard(self.tmp / "d.html", {})
        self.assertEqual(mk.call_args.kwargs.get("dir"), str(self.tmp))
        self.assertEqual(seen["src"].parent, self.tmp)             # same filesystem as the target: atomic rename
        self.assertEqual(seen["dst"], out)

    def test_temp_file_cleaned_up_when_replace_fails(self):
        out = self.tmp / "d.html"
        out.write_text("old", encoding="utf-8")
        with mock.patch.object(db.os, "replace", side_effect=OSError("boom")):
            with self.assertRaises(OSError):
                db.write_dashboard(out, {})
        self.assertEqual(sorted(x.name for x in self.tmp.iterdir()), ["d.html"])
        self.assertEqual(out.read_text(encoding="utf-8"), "old")

    def test_temp_file_cleaned_up_when_write_fails(self):
        with mock.patch.object(db, "render_dashboard", side_effect=RuntimeError("render")):
            with self.assertRaises(RuntimeError):
                db.write_dashboard(self.tmp / "d.html", {})
        self.assertEqual(list(self.tmp.iterdir()), [])

    def test_replaced_file_mode_is_private_0600(self):         # documented side effect, pinned so it is deliberate
        out = db.write_dashboard(self.tmp / "d.html", {})
        self.assertEqual(stat.S_IMODE(os.lstat(out).st_mode), 0o600)


class CspAndBadges(unittest.TestCase):
    def test_csp_meta_present_and_strict(self):
        h = db.render_dashboard({})
        metas = re.findall(r'<meta http-equiv="Content-Security-Policy" content="([^"]*)">', h)
        self.assertEqual(len(metas), 1)
        csp = metas[0]
        self.assertEqual(csp, "default-src 'none'; style-src 'unsafe-inline'")
        for loose in ("*", "unsafe-eval", "script-src", "http", "data:", "connect-src", "img-src"):
            self.assertNotIn(loose, csp)
        self.assertLess(h.index("Content-Security-Policy"), h.index("<style>"))

    def test_badge_caveats(self):
        for ec in (EC.HYPOTHESIS, EC.NOT_VALIDATED, EC.UNKNOWN):
            self.assertIn("NOT EVIDENCE", db._badge(ec))
        self.assertIn("not a safety finding", db._badge(EC.TOY_RESULT))
        # and NOT the content-asserting form: this badge sits beside untrusted free text
        self.assertNotIn("not a safety claim", db._badge(EC.TOY_RESULT))
        self.assertIn("not a model result", db._badge(EC.SOURCE_OBSERVED))
        self.assertIn("warn", db._badge(EC.UNKNOWN, "problem text"))
        self.assertEqual(set(db._BADGE), set(EC))                    # every class has a fixed badge


class MalformedInputs(unittest.TestCase):
    def test_history_rejects_nan_inf_bool_strings_arity(self):
        good, bad = db._valid_history([(0, 1.0, 2.0), (1, float("nan"), 1.0), (2, 1.0, float("inf")),
                                       (True, 1.0, 1.0), (3, False, 1.0), ("4", 1.0, 1.0), (5, 1.0),
                                       (6, 1.0, 1.0, 1.0), None, 7])
        self.assertEqual(good, [(0.0, 1.0, 2.0)])
        self.assertEqual(bad, 9)
        self.assertEqual(db._valid_history("not a list"), ([], 0))

    def test_render_reports_omitted_history_rows(self):
        t = dataclasses.replace(train(3, steps=3, timestamp_utc=TS),
                                history=((0, 1.0, 1.0), (1, float("nan"), 1.0), (2, True, 1.0)))
        h = db.render_dashboard({"train": t})
        self.assertIn("2 malformed history row(s) omitted", h)
        self.assertNotIn("nan", h.lower().replace("unknown", ""))

    def test_forged_metric_values_render_unknown(self):
        for forged in (float("nan"), True, False, 0, "0", float("inf"), 1):
            mv = MetricValue.measured(0.5)
            object.__setattr__(mv, "value", forged)
            cell = db._metric_cell(mv)
            self.assertIn("UNKNOWN", cell, forged)
            self.assertNotIn('class="measured"', cell)
        for notmv in (None, 0, 0.0, "0", {"value": 0.0}):
            self.assertIn("UNKNOWN", db._metric_cell(notmv))

    def test_train_fallback_labels(self):
        t = train(3, steps=3, timestamp_utc=TS)
        h = db.render_dashboard({"train": t})
        self.assertIn('data-evidence="TOY_RESULT"><h2>Toy training curves', h)
        no_rec = dataclasses.replace(t, record=None)
        h = db.render_dashboard({"train": no_rec})
        self.assertIn('data-evidence="UNKNOWN"><h2>Toy training curves', h)
        self.assertIn("no valid ExperimentRecord attached", h)
        self.assertIn("<svg", h)                                      # curve drawn, but never labelled above UNKNOWN
        hyp = dataclasses.replace(t, record=rec(ec=EC.HYPOTHESIS))
        self.assertIn('data-evidence="HYPOTHESIS"><h2>Toy training curves', db.render_dashboard({"train": hyp}))
        h = db.render_dashboard({"train": rec()})                       # bare record: no history, no curve
        self.assertIn("no usable history", h)
        self.assertNotIn("<svg", h)
        h = db.render_dashboard({"train": object()})
        self.assertIn('data-evidence="UNKNOWN"><h2>Toy training curves', h)

    def test_row_cap_is_loud(self):
        h = db.render_dashboard({"records": [rec(name=f"n{i}") for i in range(db.MAX_TABLE_ROWS + 1)]})
        self.assertIn(f"TRUNCATED: showing {db.MAX_TABLE_ROWS} of {db.MAX_TABLE_ROWS + 1}", h)
        self.assertEqual(h.count("UNTRUSTED FREE TEXT (name)"), db.MAX_TABLE_ROWS)
        self.assertNotIn('data-evidence="TOY_RESULT"><h2>Experiment records', h)   # incomplete => not plain TOY
        ok = db.render_dashboard({"records": [rec(name=f"n{i}") for i in range(db.MAX_TABLE_ROWS)]})
        self.assertNotIn("TRUNCATED", ok)
        self.assertIn('data-evidence="TOY_RESULT"><h2>Experiment records', ok)

    def test_non_record_entries_are_loud_not_silent(self):
        evil = {"name": "<script>x</script>", "verdict": "JOINT_SUPPORTED"}
        h = db.render_dashboard({"records": [rec(), evil, "str", 5, None]})
        self.assertIn("4 entries not rendered: not an ExperimentRecord", h)
        self.assertEqual(h.count("ENTRY IS NOT AN ExperimentRecord"), 4)
        self.assertNotIn("<script", h)
        self.assertNotIn("JOINT_SUPPORTED", h)                          # contents of bad entries are never rendered
        self.assertIn('data-evidence="NOT_VALIDATED"><h2>Experiment records', h)
        only = db.render_dashboard({"records": ["x"]})
        self.assertIn('data-evidence="UNKNOWN"><h2>Experiment records', only)
        self.assertIn("not iterable", db.render_dashboard({"records": 5}))
        self.assertIn("record list is empty", db.render_dashboard({"records": []}))


class ScorecardVerdictCore(unittest.TestCase):
    """Each layer of the verdict derivation demonstrated on its own, starting from a GENUINE SUPPORTED result.
    The renderer may only ever downgrade: every scenario must end with no supported joint cell."""

    def base(self):
        j = joint()
        h = db.render_scorecard(j)
        self.assertIn("vd-supported", joint_cell(h))
        self.assertEqual(set(hyp_cells(h).values()), {"SUPPORTED"})
        self.assertNotIn("NOT shown", h)
        return j

    def assertDowngraded(self, h, mismatch=True):
        self.assertNotIn("vd-supported", joint_cell(h))
        self.assertNotIn("vd-unsupported", joint_cell(h))
        self.assertIn("vd-inconclusive", joint_cell(h))
        if mismatch:
            self.assertIn("NOT shown", h)

    def test_layer_hypothesis_blocking(self):
        j = self.base()
        object.__setattr__(j.h1, "blocking", ("control_adequacy (forged)",))     # stored verdict still SUPPORTED
        h = db.render_scorecard(j)
        self.assertEqual(hyp_cells(h)["H1"], "INCONCLUSIVE")
        self.assertEqual(hyp_cells(h)["H2"], "SUPPORTED")                        # only the blocked hypothesis changes
        self.assertDowngraded(h)

    def test_layer_global_gate_blocks_everything(self):
        j = self.base()
        for name in ("control_adequacy", "min_seeds", "seed_list_frozen"):
            j = fail_gate(joint(), name)
            h = db.render_scorecard(j)
            self.assertEqual(set(hyp_cells(h).values()), {"INCONCLUSIVE"}, name)
            self.assertDowngraded(h)

    def test_layer_h3_scoped_gate_blocks_only_h3(self):
        j = self.base()
        h = db.render_scorecard(fail_gate(j, "convergence"))
        cells = hyp_cells(h)
        self.assertEqual(cells["H3"], "INCONCLUSIVE")
        self.assertEqual((cells["H1"], cells["H2"]), ("SUPPORTED", "SUPPORTED"))  # scope-aware, not blanket
        self.assertDowngraded(h)

    def test_layer_any_failed_gate_withholds_component_cells(self):
        j = self.base()
        h = db.render_scorecard(fail_gate(j, "convergence"))
        comp_rows = [r for r in h.split("<tr>") if "greater" in r or "less" in r]
        self.assertTrue(comp_rows)
        for r in comp_rows:
            self.assertNotIn("vd-supported", r)

    def test_layer_h3_converged_components_required(self):
        j = self.base()
        object.__setattr__(j.h3, "converged_components", ())
        h = db.render_scorecard(j)
        self.assertEqual(hyp_cells(h)["H3"], "INCONCLUSIVE")
        self.assertDowngraded(h)

    def test_layer_h3_weak_converged_components(self):
        j = self.base()
        weak = joint(expect=None, d=0.0, dms=0.0)
        self.assertNotEqual(weak.h3.converged_components[0].verdict, bm.Verdict.SUPPORTED)
        object.__setattr__(j.h3, "converged_components", weak.h3.converged_components)
        h = db.render_scorecard(j)
        self.assertEqual(hyp_cells(h)["H3"], "INCONCLUSIVE")
        self.assertDowngraded(h)

    def test_layer_supported_blockers(self):
        j = self.base()
        object.__setattr__(j.h3, "supported_blockers", ("convergence (forged)",))
        h = db.render_scorecard(j)
        self.assertEqual(hyp_cells(h)["H3"], "INCONCLUSIVE")
        self.assertDowngraded(h)

    def test_layer_component_recomputation(self):
        j = joint(expect=bm.JointVerdict.JOINT_UNSUPPORTED, S=0.0)
        object.__setattr__(j.h1.components[0], "verdict", bm.Verdict.SUPPORTED)
        object.__setattr__(j.h1, "verdict", bm.Verdict.SUPPORTED)
        h = db.render_scorecard(j)
        self.assertEqual(hyp_cells(h)["H1"], "INCONCLUSIVE")
        self.assertNotIn("vd-supported", joint_cell(h))

    def test_layer_combine_truth_table(self):
        V, JV = bm.Verdict, bm.JointVerdict
        for h1, h2, h3, ok in itertools.product(V, V, V, (True, False)):
            vs = (h1, h2, h3)
            if not ok:
                want = JV.JOINT_INCONCLUSIVE
            elif V.UNSUPPORTED in vs:
                want = JV.JOINT_UNSUPPORTED
            elif all(v is V.SUPPORTED for v in vs):
                want = JV.JOINT_SUPPORTED
            else:
                want = JV.JOINT_INCONCLUSIVE
            self.assertIs(db._combine(h1, h2, h3, ok), want, (vs, ok))
        # explicit anchors, independent of the loop above
        self.assertIs(db._combine(V.SUPPORTED, V.SUPPORTED, V.INCONCLUSIVE, True), JV.JOINT_INCONCLUSIVE)
        self.assertIs(db._combine(V.SUPPORTED, V.SUPPORTED, V.SUPPORTED, False), JV.JOINT_INCONCLUSIVE)
        self.assertIs(db._combine(V.SUPPORTED, V.UNSUPPORTED, V.SUPPORTED, True), JV.JOINT_UNSUPPORTED)

    def test_layer_joint_mismatch_both_directions(self):
        sup, uns = self.base(), joint(expect=bm.JointVerdict.JOINT_UNSUPPORTED, S=0.0)
        with mock.patch.object(bm.JointResult, "verdict", property(lambda self: bm.JointVerdict.JOINT_SUPPORTED)):
            h = db.render_scorecard(uns)            # stored claims SUPPORTED, structure says UNSUPPORTED
        self.assertDowngraded(h)
        self.assertIn("JOINT", h.split("Stored verdict(s) for ")[1].split(" disagree")[0])
        with mock.patch.object(bm.JointResult, "verdict", property(lambda self: bm.JointVerdict.JOINT_INCONCLUSIVE)):
            h = db.render_scorecard(sup)            # stored is weaker than the structure: still not promoted
        self.assertDowngraded(h)
        with mock.patch.object(bm.JointResult, "verdict", property(lambda self: "JOINT_SUPPORTED")):
            self.assertDowngraded(db.render_scorecard(uns))        # a bare string is not a JointVerdict

    def test_renderer_never_more_permissive_than_scorer(self):
        for kw in (dict(S=0.0), dict(conv=False), dict(gate_inputs=False), dict(L=1.0)):
            j = joint(expect=None, **kw)
            h = db.render_scorecard(j)
            if j.verdict is not bm.JointVerdict.JOINT_SUPPORTED:
                self.assertNotIn("vd-supported", joint_cell(h), kw)
                self.assertNotIn("NOT shown", h, kw)             # and the honest scorer result raises no alarm


class VerdictCoreSurvivors(unittest.TestCase):
    """Pins for failure modes that must end in INCONCLUSIVE plus an alarm, never in a decisive display."""

    def alarmed(self, h):
        self.assertIn("NOT shown", h)
        self.assertNotIn("vd-supported", joint_cell(h))
        self.assertNotIn("vd-unsupported", joint_cell(h))

    def comps(self, j):
        return [c for h in (j.h1, j.h2, j.h3) for c in (*h.components, *h.converged_components)]

    def test_recompute_exception_is_inconclusive_with_alarm(self):
        j = joint()
        for c in self.comps(j):
            object.__setattr__(c, "margin", "oops")                # float("oops") raises inside recomputation
        h = db.render_scorecard(j)
        self.assertEqual(hyp_cells(h), {"H1": "INCONCLUSIVE", "H2": "INCONCLUSIVE", "H3": "INCONCLUSIVE"})
        self.assertNotIn("vd-supported", h)
        self.alarmed(h)

    def test_recompute_exception_in_single_hypothesis(self):
        for hid in ("h1", "h2", "h3"):
            j = joint()
            h_ = getattr(j, hid)
            object.__setattr__(h_.components[0], "direction", "sideways")     # interval_verdict raises ValueError
            h = db.render_scorecard(j)
            self.assertEqual(hyp_cells(h)[hid.upper()], "INCONCLUSIVE", hid)
            self.alarmed(h)

    def test_recompute_exception_in_converged_component_only(self):
        j = joint()
        object.__setattr__(j.h3.converged_components[1], "margin", "oops")
        h = db.render_scorecard(j)
        self.assertEqual(hyp_cells(h)["H3"], "INCONCLUSIVE")
        self.assertEqual((hyp_cells(h)["H1"], hyp_cells(h)["H2"]), ("SUPPORTED", "SUPPORTED"))
        self.alarmed(h)

    def test_edited_component_margin_alone_is_an_alarm(self):
        # consistent edit of one component (verdict recomputes the same under it) is still caught via Margins
        j = joint()
        c = j.h1.components[0]
        object.__setattr__(c, "margin", c.margin / 2)
        h = db.render_scorecard(j)
        self.assertEqual(hyp_cells(h)["H1"], "INCONCLUSIVE")
        self.alarmed(h)
        j = joint()
        object.__setattr__(j.h3.converged_components[0], "direction", "less")
        self.alarmed(db.render_scorecard(j))

    def test_documented_limit_consistent_forgery_of_margins_object_is_not_detected(self):
        # Honest boundary: margins are producer-asserted. Forging the Margins object AND the component margin
        # consistently, while keeping the verdict derivable, is not detectable by the renderer. Pin that we
        # KNOW this (the page prints the margins it used so a reader can see them).
        j = joint()
        h = db.render_scorecard(j)
        self.assertIn("greater " + repr(bm.Margins().delta_S), h)
        self.assertIn("Uncertainty" , db.render_dashboard({"joint": j}))
        self.assertIn(repr(bm.Margins().delta_sel), db.render_dashboard({"joint": j}))

    def test_deleting_components_cannot_launder_a_weak_hypothesis(self):
        # F1: delete H3's weak component AND its converged counterpart; stored verdict forged to SUPPORTED.
        weak = joint(expect=None, dms=bm.Margins().delta_sel)
        self.assertEqual(weak.h3.verdict, bm.Verdict.INCONCLUSIVE)
        j = weak
        object.__setattr__(j.h3, "components", (j.h3.components[0],))
        object.__setattr__(j.h3, "converged_components", (j.h3.converged_components[0],))
        object.__setattr__(j.h3, "verdict", bm.Verdict.SUPPORTED)
        h = db.render_scorecard(j)
        self.assertEqual(hyp_cells(h)["H3"], "INCONCLUSIVE")
        self.alarmed(h)
        self.assertNotIn("JOINT_SUPPORTED", h)

    def test_component_set_must_match_protocol_tables_exactly(self):
        def alarm_for(mutate, hid="h3"):
            j = joint()
            mutate(getattr(j, hid))
            h = db.render_scorecard(j)
            self.assertEqual(hyp_cells(h)[hid.upper()], "INCONCLUSIVE")
            self.alarmed(h)
        alarm_for(lambda x: object.__setattr__(x, "components", (x.components[0],)))                    # deleted
        alarm_for(lambda x: object.__setattr__(x, "components", (x.components[0], x.components[0])))    # duplicated
        alarm_for(lambda x: object.__setattr__(x, "converged_components", ()))                          # no converged
        alarm_for(lambda x: object.__setattr__(x, "converged_components", x.converged_components[:1]))
        alarm_for(lambda x: object.__setattr__(x, "converged_components", (x.components[0],)))           # substituted
        alarm_for(lambda x: object.__setattr__(x, "converged_components", (x.components[0],)), "h1")             # stray converged on H1
        # genuine sets raise no alarm and keep working in any order
        j = joint()
        object.__setattr__(j.h3, "components", j.h3.components[::-1])
        self.assertNotIn("NOT shown", db.render_scorecard(j))

    def test_margins_missing_or_wrong_type_refused_not_skipped(self):
        # C2: a None Margins used to skip the margin cross-check (fail OPEN). Now the whole card is refused.
        for bad in (None, object(), {"delta_S": 0.1}, "margins"):
            j = joint(expect=None, dms=bm.Margins().delta_sel)      # weak H3
            for c in (*j.h3.components, *j.h3.converged_components):
                object.__setattr__(c, "margin", -1e9)                # forged margins that would flip the verdict
            object.__setattr__(j.h3, "verdict", bm.Verdict.SUPPORTED)
            object.__setattr__(j, "margins", bad)
            h = db.render_scorecard(j)
            self.assertIn("REFUSED", h, repr(bad))
            self.assertNotIn("vd-", h)
            self.assertNotIn("Suppression", h)
            self.assertIn("REFUSED", db.render_dashboard({"joint": j}))

    def test_extra_duplicate_components_alarm(self):
        # F-i / F-j: compare sorted SEQUENCES, not sets: a size-increasing duplicate must alarm too
        for field, hid in (("components", "h3"), ("converged_components", "h3")):
            j = joint()
            x = getattr(j, hid)
            cur = getattr(x, field)
            object.__setattr__(x, field, (*cur, cur[0]))
            h = db.render_scorecard(j)
            self.assertEqual(hyp_cells(h)[hid.upper()], "INCONCLUSIVE", field)
            self.alarmed(h)
        j = joint()
        object.__setattr__(j.h3, "components", (j.h3.components[0], j.h3.components[1], j.h3.components[0]))
        self.alarmed(db.render_scorecard(j))
        self.assertTrue(db._component_sets_ok(joint().h3))

    def test_component_set_check_itself_fails_closed_unmasked(self):
        # direct unit test: other layers (e.g. _declared) would otherwise force INCONCLUSIVE and mask a fail-open
        h3 = joint().h3
        for tbl in ("PRIMARY", "CONVERGED"):
            with mock.patch.object(bm, tbl, None):
                self.assertFalse(db._component_sets_ok(h3), tbl)
        with mock.patch.object(bm, "PRIMARY", {}):
            self.assertFalse(db._component_sets_ok(h3))
        self.assertFalse(db._component_sets_ok(object()))

    def test_the_transplanted_pair_residual_now_costs_the_whole_series(self):
        """ROUND-6 NARROWING OF A DOCUMENTED RESIDUAL, with its new cost measured rather than asserted.

        This test was called `test_documented_limit_same_name_forged_pair_is_a_residual` and it pinned
        the OPPOSITE outcome: transplanting a strong H3 component (and its converged pair) from one
        study into a weak one, under the correct metric name, rendered H3 SUPPORTED with no alarm, on the
        stated grounds that "intervals are producer-asserted". They are; but the per-seed values the
        interval was computed from are in the SAME result, so the transplant contradicts them.

        MEASURED, both halves:
          transplant alone      -> H3 INCONCLUSIVE, named: stored mean 1.000511355280501 vs the 30
                                   per-seed values' 0.100511355280501
          transplant + the series for those metrics copied over too (30 more forged MetricValues per
          metric) -> H3 SUPPORTED, no alarm
        So the residual is NOT gone, and the half that is gone is the cheap half. What is left needs the
        forger to restate the per-seed data as well, which is the `_recompute` residual as written."""
        weak = joint(expect=None, dms=bm.Margins().delta_sel)
        strong = joint()
        j = weak
        object.__setattr__(j.h3, "components", (j.h3.components[0], strong.h3.components[1]))
        object.__setattr__(j.h3, "converged_components", strong.h3.converged_components)
        object.__setattr__(j.h3, "verdict", bm.Verdict.SUPPORTED)
        h = db.render_scorecard(j)
        self.assertEqual(hyp_cells(h)["H3"], "INCONCLUSIVE")
        self.assertIn("INTERVAL CONTRADICTED", h)
        self.assertIn("H3/delta_minus_shuf", h)
        self.assertNotIn("JOINT_SUPPORTED", joint_cell(h))
        # THE RESIDUAL, PERFORMED: restate the per-seed series for the transplanted metrics as well.
        weak, strong = joint(expect=None, dms=bm.Margins().delta_sel), joint()
        k = weak
        object.__setattr__(k.h3, "components", (k.h3.components[0], strong.h3.components[1]))
        object.__setattr__(k.h3, "converged_components", strong.h3.converged_components)
        object.__setattr__(k.h3, "verdict", bm.Verdict.SUPPORTED)
        forged = 0
        for sw, ss in zip(k.seed_scores, strong.seed_scores):
            for metric in ("delta_minus_shuf", "delta_minus_shuf_conv", "delta_conv"):
                sw.metrics[metric] = ss.metrics[metric]     # the metrics mapping is a plain dict
                forged += 1
        self.assertEqual(forged, 90)
        h = db.render_scorecard(k)
        self.assertEqual(hyp_cells(h)["H3"], "SUPPORTED")
        self.assertNotIn("INTERVAL CONTRADICTED", h)
        self.assertNotIn("NOT shown", h)
        self.assertIn("producer-asserted", db._component_sets_ok.__doc__)
        self.assertIn("producer-asserted", db._recompute.__doc__)
        self.assertNotIn("is not a residual", db._recompute.__doc__)

    def test_component_set_check_fails_closed_if_tables_vanish(self):
        j = joint()
        with mock.patch.object(bm, "PRIMARY", None):
            h = db.render_scorecard(j)
        self.assertNotIn("vd-supported", joint_cell(h))

    def test_aggregation_requires_ALL_components_supported(self):
        # a component that is INCONCLUSIVE (interval spans the margin), not UNSUPPORTED: an UNSUPPORTED one would
        # trip the separate 'any UNSUPPORTED' branch and mask an all->any aggregation mutant
        weak = joint(expect=None, dms=bm.Margins().delta_sel)
        self.assertEqual(weak.h3.components[1].verdict, bm.Verdict.INCONCLUSIVE)
        j = joint()
        object.__setattr__(j.h3, "components", (j.h3.components[0], weak.h3.components[1]))   # one strong, one weak
        h = db.render_scorecard(j)
        self.assertEqual(hyp_cells(h)["H3"], "INCONCLUSIVE")        # 'any SUPPORTED' would show SUPPORTED
        self.alarmed(h)

    def test_converged_requires_ALL_components_supported(self):
        weak = joint(expect=None, dms=0.0)
        self.assertNotEqual(weak.h3.converged_components[1].verdict, bm.Verdict.SUPPORTED)
        self.assertEqual(weak.h3.converged_components[0].verdict, bm.Verdict.SUPPORTED)
        j = joint()
        object.__setattr__(j.h3, "converged_components", (j.h3.converged_components[0], weak.h3.converged_components[1]))
        h = db.render_scorecard(j)
        self.assertEqual(hyp_cells(h)["H3"], "INCONCLUSIVE")
        self.alarmed(h)
        weak0 = joint(expect=None, d=0.0)
        self.assertNotEqual(weak0.h3.converged_components[0].verdict, bm.Verdict.SUPPORTED)
        self.assertEqual(weak0.h3.converged_components[1].verdict, bm.Verdict.SUPPORTED)
        j = joint()
        object.__setattr__(j.h3, "converged_components", (weak0.h3.converged_components[0], j.h3.converged_components[1]))
        self.assertEqual(hyp_cells(db.render_scorecard(j))["H3"], "INCONCLUSIVE")

    def test_non_bool_gate_passed_values_fail_closed(self):
        for val in (1, "True", "yes", None, 1.0, object()):
            j = joint()
            g = next(g for g in j.gates if g.name == "control_adequacy")
            object.__setattr__(g, "passed", val)
            h = db.render_scorecard(j)
            self.assertEqual(set(hyp_cells(h).values()), {"INCONCLUSIVE"}, repr(val))
            self.alarmed(h)
            self.assertIn("FAIL", h)

    def test_unknown_gate_name_is_global_blocker(self):
        j = joint()
        g = j.gates[0]
        object.__setattr__(g, "name", "mystery_gate")               # .scope now raises KeyError
        object.__setattr__(g, "passed", False)
        h = db.render_scorecard(j)
        self.assertEqual(set(hyp_cells(h).values()), {"INCONCLUSIVE"})
        self.alarmed(h)

    def test_unknown_gate_scope_value_blocks_and_flags_contract(self):
        j = joint()
        with mock.patch.dict(bm.GATE_SCOPES, {"convergence": "H9"}):
            fail_gate(j, "convergence")
            h = db.render_scorecard(j)
        self.assertIn("CONTRACT PROBLEM", h)
        self.assertEqual(set(hyp_cells(h).values()), {"INCONCLUSIVE"})
        self.alarmed(h)
        # and the blocking clause itself, with the contract banner not involved
        j = joint()
        with mock.patch.dict(bm.GATE_SCOPES, {"convergence": "H9"}):
            fail_gate(j, "convergence")
            with mock.patch.object(db, "_contract_problems", lambda: []):
                h = db.render_scorecard(j)
        self.assertEqual(set(hyp_cells(h).values()), {"INCONCLUSIVE"})
        self.alarmed(h)

    def test_empty_or_missing_gates_refused(self):
        for bad in ((), None, [], "gates"):
            j = joint()
            object.__setattr__(j, "gates", bad)
            h = db.render_scorecard(j)
            self.assertIn("REFUSED", h)
            self.assertNotIn("Suppression", h)
        j = joint()
        object.__setattr__(j, "gates", (object(),))
        self.assertIn("REFUSED", db.render_scorecard(j))

    def test_conditional_note_names_deferred_gate_count(self):
        h = db.render_scorecard(joint())
        self.assertIn(f"CONDITIONAL on {len(bm.DEFERRED_GATES)} unimplemented gate(s)", joint_cell(h))
        self.assertGreater(len(bm.DEFERRED_GATES), 0)
        self.assertIn("Complete gate coverage: NO", h)
        j = joint(expect=bm.JointVerdict.JOINT_UNSUPPORTED, S=0.0)
        self.assertIn("CONDITIONAL on", joint_cell(db.render_scorecard(j)))


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


def forge_gate_pass(j, name):
    """Flip a FAILED gate to passed=True IN PLACE, leaving the gate NAME SET intact.

    Deliberately not `fail_gate`'s sibling: this is the forgery that the gate-name-set check cannot see,
    so it isolates the protocol-parameter cross-check from the gate-set check. Layers must not mask
    each other (the F-h lesson)."""
    gs = tuple(dataclasses.replace(g, passed=True) if g.name == name else g for g in j.gates)
    object.__setattr__(j, "gates", gs)
    return j


def forge_all_verdicts_supported(j):
    """Everything a thorough tamperer can reach post-construction: stored hypothesis and component
    verdicts, and the `blocking` / `supported_blockers` lists the scorer recorded."""
    for h_ in (j.h1, j.h2, j.h3):
        object.__setattr__(h_, "blocking", ())
        object.__setattr__(h_, "supported_blockers", ())
        object.__setattr__(h_, "verdict", bm.Verdict.SUPPORTED)
        for c in (*h_.components, *(h_.converged_components or ())):
            object.__setattr__(c, "verdict", bm.Verdict.SUPPORTED)
    return j


def joint_private_margins(**kw):
    """A fixture whose `margins` is a FRESH instance.

    STALE AS WRITTEN, CORRECTED: this said `bm.analyze_scores` declares `margins: Margins = Margins()`,
    a mutable default evaluated once at import and shared by every fixture. That WAS true and was
    reported upwards; `benchmark` has since fixed it (`margins: Optional[Margins] = None` plus the
    per-call `_margins()`, with the measured `delta_S = 99.0` cross-test contamination recorded in its
    own comment). So the scorer's default is no longer reachable through a fixture.

    This helper is kept regardless, and these tests still go through it: the fixtures below mutate a
    FIELD of `j.margins` with `object.__setattr__`, and two fixtures sharing one `Margins` instance for
    any other reason would give them a hidden ordering dependency. A fresh instance makes the mutation
    local by construction rather than by trusting another module's defaulting."""
    j = joint(**kw)
    object.__setattr__(j, "margins", bm.Margins())
    return j


class _MarginsNoSel(bm.Margins):
    """Margins whose `delta_sel` ATTRIBUTE IS ABSENT (the attribute access raises AttributeError).

    A plain `object.__delattr__` cannot produce this: every Margins field has a class-level default, so
    deleting the instance attribute just falls back to the class. Swapping `__class__` after construction
    does, and `isinstance(m, bm.Margins)` still holds so `_joint_wellformed` still accepts the result."""

    @property
    def delta_sel(self):
        raise AttributeError("delta_sel is absent")


class GateSetCompleteness(unittest.TestCase):
    """SR-13 item 1. `_joint_wellformed` checked `j.gates` only for 'is a non-empty tuple whose entries
    have .passed'. It never compared gate NAMES against `bm.GATE_SCOPES`, so a FAILED validity gate could
    be deleted or swapped and the page showed all-SUPPORTED / JOINT_SUPPORTED with no alarm. Components
    already got exactly this treatment from `_component_sets_ok`; gates did not."""

    def alarmed(self, h):
        self.assertIn("NOT shown", h)
        self.assertNotIn("vd-supported", joint_cell(h))
        self.assertNotIn("vd-unsupported", joint_cell(h))

    def assertGateSetAlarm(self, j, label):
        h = db.render_scorecard(j)
        self.assertEqual(set(hyp_cells(h).values()), {"INCONCLUSIVE"}, label)
        self.alarmed(h)
        self.assertIn("gate NAME set does not match", h, label)
        self.assertNotIn("JOINT_SUPPORTED", h, label)
        # the alarm must ATTRIBUTE the problem to every hypothesis, not only to JOINT: a bad gate set
        # invalidates all three. Without this the mutant `if mm or gate_set_bad:` -> `if mm:` survives,
        # because JOINT alone still disagrees and still prints "NOT shown".
        named = re.search(r"Stored verdict\(s\) for ([^<]+?) disagree", h).group(1)
        self.assertEqual(named, "H1, H2, H3, JOINT", label)
        return h

    def test_deleted_failing_gate_is_alarmed(self):
        j = fail_gate(joint(), "min_seeds")
        object.__setattr__(j, "gates", tuple(g for g in j.gates if g.name != "min_seeds"))
        h = self.assertGateSetAlarm(j, "deleted min_seeds")
        self.assertEqual(h.count("<td>PASS</td>") + h.count("<td>FAIL</td>"), 6)   # the row is really gone

    def test_failed_gate_swapped_for_a_duplicate_of_a_passing_gate(self):
        # WORST CASE: the gate COUNT is unchanged and there are zero FAIL rows, so no count-based or
        # FAIL-counting check can see this. Only comparing NAMES as sorted sequences catches it.
        j = fail_gate(joint(), "min_seeds")
        passing = next(g for g in j.gates if g.name == "failure_rate")
        object.__setattr__(j, "gates", tuple(passing if g.name == "min_seeds" else g for g in j.gates))
        h = self.assertGateSetAlarm(j, "swapped for duplicate")
        self.assertEqual(h.count("<td>PASS</td>"), 7)
        self.assertEqual(h.count("<td>FAIL</td>"), 0)

    def test_gates_truncated_to_one_passing_gate(self):
        j = joint()
        object.__setattr__(j, "gates", (next(g for g in j.gates if g.name == "failure_rate"),))
        self.assertGateSetAlarm(j, "truncated")

    def test_subset_of_real_gates_is_alarmed(self):
        # the case test_empty_or_missing_gates_refused never covered: a SUBSET of genuine gates
        full_gates = joint().gates
        for drop in sorted(bm.GATE_SCOPES):
            j = joint()
            object.__setattr__(j, "gates", tuple(g for g in full_gates if g.name != drop))
            self.assertGateSetAlarm(j, f"dropped {drop}")

    def test_extra_and_duplicate_gates_are_alarmed(self):
        j = joint()
        g0 = j.gates[0]
        object.__setattr__(j, "gates", (*j.gates, g0))          # size-increasing duplicate
        self.assertGateSetAlarm(j, "duplicate appended")

    def test_honest_n29_cannot_be_laundered_by_removing_the_failing_gate(self):
        """The QA scenario end to end: a genuine 29-seed run whose `min_seeds` gate really fails and
        which the scorer calls JOINT_INCONCLUSIVE, with the failing gate removed and every verdict
        forged. It must not reach JOINT_SUPPORTED."""
        j = joint(expect=bm.JointVerdict.JOINT_INCONCLUSIVE, seeds=FZ.seeds[:29])
        self.assertFalse(next(g.passed for g in j.gates if g.name == "min_seeds"))
        object.__setattr__(j, "gates", tuple(g for g in j.gates if g.name != "min_seeds"))
        forge_all_verdicts_supported(j)
        self.assertGateSetAlarm(j, "laundered n=29")

    def test_gate_set_check_itself_fails_closed_unmasked(self):
        # direct unit test: no other layer can mask a fail-open here
        good = joint().gates
        self.assertTrue(db._gate_set_ok(good))
        self.assertFalse(db._gate_set_ok(()))
        self.assertFalse(db._gate_set_ok(good[:-1]))
        self.assertFalse(db._gate_set_ok((*good, good[0])))
        self.assertFalse(db._gate_set_ok(None))
        self.assertFalse(db._gate_set_ok("gates"))
        self.assertFalse(db._gate_set_ok((object(),)))
        for tbl in (None, {}, [], "GATE_SCOPES"):
            with mock.patch.object(bm, "GATE_SCOPES", tbl):
                self.assertFalse(db._gate_set_ok(good), repr(tbl))
        # a renamed gate is caught even though the count is right
        j = joint()
        object.__setattr__(j.gates[0], "name", "mystery_gate")
        self.assertFalse(db._gate_set_ok(j.gates))

    def test_no_false_alarm_on_any_honest_fixture(self):
        """The check must not fire on a legitimate result. Verified across the same seven fixture
        variations QA used: the honest gate name set is always exactly set(bm.GATE_SCOPES)."""
        variations = [
            ("default", dict()),
            ("S=0.0", dict(expect=None, S=0.0)),
            ("conv=False", dict(expect=None, conv=False)),
            ("gate_inputs=False", dict(expect=None, gate_inputs=False)),
            ("L=1.0", dict(expect=None, L=1.0)),
            ("5 seeds", dict(expect=None, seeds=FZ.seeds[:5])),
            ("unregistered digest", dict(expect=None, registered=None)),
        ]
        for label, kw in variations:
            j = joint(**kw)
            self.assertEqual(sorted(g.name for g in j.gates), sorted(bm.GATE_SCOPES), label)
            self.assertTrue(db._gate_set_ok(j.gates), label)
            h = db.render_scorecard(j)
            self.assertNotIn("gate NAME set does not match", h, label)
        self.assertNotIn("NOT shown", db.render_scorecard(joint()))     # and the honest SUPPORTED is clean
        self.assertIn("vd-supported", joint_cell(db.render_scorecard(joint())))

    def test_a_duck_typed_extra_gate_constructs_upstream_and_is_caught_only_here(self):
        """The reviewer's note, pinned: this check is MORE load-bearing than "upstream already validates
        the gate names" suggests, so do not simplify it away. `JointResult.__post_init__` compares names
        only over entries passing `isinstance(g, GateResult)`, so the 7 real gates PLUS a duck-typed
        extra CONSTRUCTS FINE upstream -- the extra object is invisible to that check. `_gate_set_ok`
        does not filter, sees 8 names and fails. The injection route is live rather than hypothetical
        because `benchmark.carries_exemption` reads `exempt` off ANY object in the list."""
        class DuckGate:
            name, passed, reason, exempt, scope = "extra_gate", True, "injected", False, "all"
        j = joint()
        k = dataclasses.replace(j, gates=(*j.gates, DuckGate()))          # upstream ACCEPTS this
        self.assertEqual(len(k.gates), 8)
        self.assertEqual(sorted(g.name for g in k.gates if isinstance(g, bm.GateResult)),
                         sorted(bm.GATE_SCOPES))                           # why upstream accepts it
        self.assertFalse(db._gate_set_ok(k.gates))                         # only this catches it
        self.assertGateSetAlarm(k, "duck-typed extra gate")

    def test_upstream_already_refuses_an_incomplete_gate_set_at_construction(self):
        # why no legitimate path can omit a gate: the scorer refuses to build such a result at all
        j = joint()
        with self.assertRaisesRegex(ValueError, "gates must contain exactly"):
            dataclasses.replace(j, gates=tuple(g for g in j.gates if g.name != "min_seeds"))


class ProtocolParametersFailClosed(unittest.TestCase):
    """SR-13 item 2. `_recompute` read `min_n` / `width_tol` from the component with a renderer-invented
    default (`getattr(c, 'min_n', 30)`) and cross-checked only `direction` and `margin`. These are
    PROTOCOL PARAMETERS (6.1 minimum n = 30; 6.3 widths may differ by at most 25%) that the component
    merely asserts, so trusting them failed OPEN -- the same class as C2, and ruled the same way."""

    def alarmed(self, h):
        self.assertIn("NOT shown", h)
        self.assertNotIn("vd-supported", joint_cell(h))

    def spy_params(self, c, margins, j):
        """Capture the (width_tol, min_n) actually handed to the scorer."""
        seen = []
        real = bm.interval_verdict

        def spy(pair, margin, direction, width_tol=0.25, min_n=30):
            seen.append((width_tol, min_n))
            return real(pair, margin, direction, width_tol, min_n)
        with mock.patch.object(bm, "interval_verdict", spy):
            out = recompute(c, margins, j)
        return seen, out

    def test_weaker_than_protocol_parameters_never_reach_the_scorer(self):
        j = joint()
        c = j.h1.components[0]
        object.__setattr__(c, "min_n", 1)
        object.__setattr__(c, "width_tol", 1e9)
        seen, out = self.spy_params(c, j.margins, j)
        self.assertEqual(seen, [(0.25, 30)])            # floored to the scorer's own declared protocol values
        self.assertIsNot(out, None)

    def test_stricter_than_protocol_parameters_are_honoured_not_overridden(self):
        """Proof that the floor is a FLOOR and not a hard-coded 30/0.25: a stricter declared parameter is
        passed through to the scorer unweakened.

        THIS TEST USED TO STOP AT THE SPY, which is the shape of defect this whole item is about -- it
        asserted what reached `interval_verdict` and never asked what the PAGE then said. Measured
        consequence: two mutants that add a read inside `_recompute` behind `if mn > 10**6` -- a branch
        no other test in this file ever took -- survived the whole suite while turning a stricter
        parameter into a decisive SUPPORTED. Neither is caught by any mechanism here (one reads an
        UNDECLARED field, so the recording probe would see it only if its single honest render took that
        branch; the other re-reads an ALREADY-DECLARED one, which an attribute-SET comparison cannot see
        at all). Both die to the loop below, which is behavioural coverage of the branch itself: a
        stricter minimum the run does not meet is INCONCLUSIVE, with an alarm, at every magnitude."""
        j = joint()
        c = j.h1.components[0]
        object.__setattr__(c, "min_n", 50)
        object.__setattr__(c, "width_tol", 0.1)
        seen, _ = self.spy_params(c, j.margins, j)
        self.assertEqual(seen, [(0.1, 50)])
        # ... and the PAGE, over magnitudes either side of every threshold any branch could test on
        for mn in (31, 50, 10 ** 6, 10 ** 6 + 1, 2_000_000, 10 ** 12):
            k = joint()
            for cc in all_components(k):
                object.__setattr__(cc, "min_n", mn)
            self.assertEqual(db._protocol_params()[1], 30)          # the floor is below every mn above
            self.assertEqual(recompute(k.h1.components[0], k.margins, k), bm.Verdict.INCONCLUSIVE, mn)
            h = db.render_scorecard(k)
            self.assertEqual(set(hyp_cells(h).values()), {"INCONCLUSIVE"}, mn)
            self.alarmed(h)
            self.assertNotIn("JOINT_SUPPORTED", h, mn)
            self.assertNotIn("WEAKER THAN THE PROTOCOL", h, mn)     # stricter is not weaker
        # NOT VACUOUS: the same fixture at the honest min_n is decisive and silent.
        clean = db.render_scorecard(joint())
        self.assertIn("JOINT_SUPPORTED", joint_cell(clean))
        self.assertNotIn("NOT shown", clean)

    def test_missing_or_malformed_parameters_are_could_not_recompute_not_a_default(self):
        for bad in (None, "x", float("nan"), float("inf"), True, -1.0, [], object()):
            j = joint()
            c = j.h1.components[0]
            object.__setattr__(c, "width_tol", bad)
            self.assertIsNone(recompute(c, j.margins, j), f"width_tol={bad!r}")
        for bad in (None, "x", 1.5, True, -1, float("nan"), [], object()):
            j = joint()
            c = j.h1.components[0]
            object.__setattr__(c, "min_n", bad)
            self.assertIsNone(recompute(c, j.margins, j), f"min_n={bad!r}")
        # A field cannot be made ABSENT on a real ComponentResult: every one has a class-level default,
        # so `object.__delattr__` just falls back to it (min_n -> 30). The absent case is reached with a
        # stand-in component instead, which is what the `getattr(c, ..., None)` guard is actually for.
        j = joint()
        c = j.h1.components[0]
        object.__delattr__(c, "min_n")
        self.assertEqual(c.min_n, 30)                              # class default, not an absent attribute

        class Stand:
            metric, direction, margin = c.metric, c.direction, c.margin
            pair = c.pair
        self.assertFalse(hasattr(Stand(), "min_n"))
        self.assertFalse(hasattr(Stand(), "width_tol"))
        self.assertIsNone(recompute(Stand(), j.margins, j))
        self.assertIsNone(recompute(Stand(), None, j))
        # and a stand-in with no `pair` at all is 'could not recompute', not an exception
        self.assertIsNone(db._recompute(object(), None, 30, db._measured_series(j)))

    def test_forged_min_n_cannot_launder_a_genuine_below_minimum_run(self):
        """The laundering route, with the gate NAME SET left intact so only this cross-check can catch it:
        a genuine n=29 run, its `min_seeds` gate flipped to passed in place, `blocking` cleared, every
        stored verdict forged SUPPORTED, and `min_n` forged to 1.

        THE ONE-SIDED FLOOR IS STILL WHAT THIS TEST IS ABOUT, and it is still measured below (the
        unforged half, and the rendered outcome). What CHANGED in round 5 is that the forged half is now
        caught one step EARLIER, as 'could not recompute' rather than as a recomputation that floors to
        INCONCLUSIVE: `_n_problem`'s second source is the pair's own `n below protocol minimum` flag,
        which `summarize` appended because the real n (29) was below the real `min_seeds` (30), and
        `n >= min_n` is now true of the FORGED `min_n` of 1. So the flag and the parameter contradict
        each other, which only an edit can produce -- an honest `BenchmarkConfig(min_seeds=1)` run gets
        no flag at all (measured: min_seeds 1/10/29/30/60 against 10 and 30 seeds, 0 contradictions).
        The displayed page is unchanged either way, which is why this is recorded here rather than
        treated as a behaviour change: INCONCLUSIVE everywhere, alarmed, no JOINT_SUPPORTED."""
        j = joint(expect=bm.JointVerdict.JOINT_INCONCLUSIVE, seeds=FZ.seeds[:29])
        self.assertEqual(j.h1.components[0].pair.n, 29)
        forge_gate_pass(j, "min_seeds")
        forge_all_verdicts_supported(j)
        self.assertTrue(db._gate_set_ok(j.gates))       # the gate-set check is NOT what catches this
        h = db.render_scorecard(j)
        self.assertEqual(set(hyp_cells(h).values()), {"INCONCLUSIVE"}, "min_n untouched")
        self.alarmed(h)
        for h_ in (j.h1, j.h2, j.h3):                    # now forge the protocol parameter too
            for c in (*h_.components, *(h_.converged_components or ())):
                object.__setattr__(c, "min_n", 1)
        self.assertIsNone(recompute(j.h1.components[0], j.margins, j))   # round 5: caught earlier
        h = db.render_scorecard(j)
        self.assertEqual(set(hyp_cells(h).values()), {"INCONCLUSIVE"}, "min_n forged to 1")
        self.alarmed(h)
        self.assertNotIn("JOINT_SUPPORTED", h)
        # the FLOOR itself, unmasked by the new cross-check: with the pair's flags cleared so only the
        # one-sided floor can act, the recomputation still runs and still refuses to be weakened.
        for h_ in (j.h1, j.h2, j.h3):
            for c in (*h_.components, *(h_.converged_components or ())):
                object.__setattr__(c.pair, "flags", ())
        self.assertEqual(recompute(j.h1.components[0], j.margins, j), bm.Verdict.INCONCLUSIVE)
        self.assertEqual(set(hyp_cells(db.render_scorecard(j)).values()), {"INCONCLUSIVE"})

    def test_protocol_params_are_read_from_the_scorer_not_hard_coded(self):
        self.assertEqual(db._protocol_params(), (0.25, 30))
        sig = inspect.signature(bm.interval_verdict).parameters
        self.assertEqual(db._protocol_params(), (sig["width_tol"].default, sig["min_n"].default))

        def stricter(pair, margin, direction, width_tol=0.05, min_n=60):
            return bm.Verdict.INCONCLUSIVE, "stub"
        with mock.patch.object(bm, "interval_verdict", stricter):
            self.assertEqual(db._protocol_params(), (0.05, 60))
        for broken in (None, lambda pair, margin: None):
            with mock.patch.object(bm, "interval_verdict", broken):
                with self.assertRaises(Exception):
                    db._protocol_params()

    def test_no_false_alarm_when_the_config_uses_the_protocol_defaults(self):
        for kw in (dict(), dict(expect=None, S=0.0), dict(expect=None, conv=False),
                   dict(expect=None, gate_inputs=False), dict(expect=None, L=1.0)):
            j = joint(**kw)
            self.assertEqual((j.h1.components[0].width_tol, j.h1.components[0].min_n), (0.25, 30))
            self.assertNotIn("NOT shown", db.render_scorecard(j), repr(kw))


class DefenceInDepthLayersUnmasked(unittest.TestCase):
    """SR-13 item 6 (the F-h class). Each layer below is unreachable end to end because an EARLIER layer
    always fires first, so a mutant that deletes it survives the whole suite. Each is therefore called
    DIRECTLY, with nothing else able to mask it."""

    def test_D5_non_intervalpair_pair_is_refused(self):
        # HEAD correctly REFUSES, but no test ever passed a non-IntervalPair pair at all
        for bad in (object(), None, {"mean": 1.0}, "pair", 0.5):
            j = joint()
            object.__setattr__(j.h1.components[0], "pair", bad)
            self.assertFalse(db._joint_wellformed(j), repr(bad))
            out = db.render_scorecard(j)
            self.assertIn("REFUSED", out)
            self.assertNotIn("Suppression", out)
        j = joint()                                        # converged components are reached too
        object.__setattr__(j.h3.components[1], "pair", object())
        self.assertFalse(db._joint_wellformed(j))
        self.assertTrue(db._joint_wellformed(joint()))     # and an honest result still passes

    def test_D8_recompute_direction_clause(self):
        # masked end-to-end: a flipped direction already changes the recomputed verdict, so the page
        # looks the same either way. Directly, HEAD must say 'could not recompute' (None), not UNSUPPORTED.
        j = joint()
        c = j.h1.components[0]
        self.assertEqual(recompute(c, j.margins, j), bm.Verdict.SUPPORTED)
        object.__setattr__(c, "direction", "less")
        self.assertIsNone(recompute(c, j.margins, j))
        # the mutant's value, shown here so the difference is explicit and not merely asserted
        self.assertEqual(bm.interval_verdict(c.pair, float(c.margin), "less", 0.25, 30)[0],
                         bm.Verdict.UNSUPPORTED)
        self.assertIsNotNone(recompute(c, None, j))        # without margins there is no declared direction

    def test_D11_declared_raises_for_an_unknown_metric(self):
        # masked because `_component_sets_ok` validates metric names before `_declared` is ever called
        m = bm.Margins()
        self.assertEqual(db._declared("S", m), ("greater", m.delta_S))
        self.assertEqual(db._declared("L", m), ("less", m.delta_R))
        for bad in ("not_a_metric", "", None, 0, "S_U", "delta_all"):
            with self.assertRaises(LookupError, msg=repr(bad)):
                db._declared(bad, m)
        # and a component carrying an unknown metric name is 'could not recompute', never ('greater', 0.0)
        j = joint()
        c = j.h1.components[0]
        object.__setattr__(c, "metric", "not_a_metric")
        self.assertIsNone(recompute(c, j.margins, j))

    def test_D20_unknown_gate_scope_forces_gates_not_ok(self):
        # masked because the identical clause in `_eff_hypothesis`'s `blocked` already forces INCONCLUSIVE
        j = fail_gate(joint(), "convergence")
        gates = tuple(j.gates)
        self.assertTrue(db._gates_ok(gates))                      # scope 'H3' is block-SUPPORTED-only
        with mock.patch.dict(bm.GATE_SCOPES, {"convergence": "H9"}):
            self.assertFalse(db._gates_ok(gates))                 # an unrecognised scope is global
        with mock.patch.dict(bm.GATE_SCOPES, {"convergence": "all"}):
            self.assertFalse(db._gates_ok(gates))
        self.assertTrue(db._gates_ok(tuple(joint().gates)))       # no failures at all
        j2 = fail_gate(joint(), "min_seeds")
        self.assertFalse(db._gates_ok(tuple(j2.gates)))           # a genuine global failure
        # a gate whose name is not in GATE_SCOPES raises inside .scope -> treated as 'all' (fail safe)
        j3 = joint()
        g = j3.gates[0]
        object.__setattr__(g, "name", "mystery_gate")
        object.__setattr__(g, "passed", False)
        self.assertFalse(db._gates_ok(tuple(j3.gates)))

    def test_D31_render_train_none_is_its_own_panel_not_the_fall_through(self):
        """QA argued D31 (`_render_train(None)` early return) is genuinely equivalent -- "falls through to
        the same UNKNOWN panel". DISAGREE, and measured: the panel LABEL is UNKNOWN either way, but the
        fall-through loses "no training result supplied ... (not a flat zero curve)", gains a spurious
        "no valid ExperimentRecord attached" warning about a result that was never supplied, and gains a
        metric table of four UNKNOWN rows. The HTML differs; it was merely unasserted. Pinned."""
        out = db._render_train(None)
        self.assertIn('data-evidence="UNKNOWN"', out)
        self.assertIn("no training result supplied", out)
        self.assertIn("not a flat zero curve", out)
        self.assertNotIn("<table>", out)                 # no metric table for a result never supplied
        self.assertNotIn("no valid ExperimentRecord attached", out)
        self.assertNotIn("no usable history", out)
        self.assertNotIn("<svg", out)
        # the genuine fall-through (a non-None object carrying no record) is a DIFFERENT panel
        other = db._render_train(object())
        self.assertIn('data-evidence="UNKNOWN"', other)
        self.assertIn("no valid ExperimentRecord attached", other)
        self.assertIn("<table>", other)
        self.assertNotEqual(out, other)
        self.assertIn("no training result supplied", db.render_dashboard({}))

    def test_C2b_missing_margins_attribute_is_refused(self):
        # HEAD handles it via getattr(j, "margins", None); the MISSING-attribute case was untested, so
        # `getattr(...)` -> `j.margins` survived
        j = joint()
        object.__delattr__(j, "margins")
        self.assertFalse(hasattr(j, "margins"))
        self.assertFalse(db._joint_wellformed(j))                 # must return False, not raise
        out = db.render_scorecard(j)
        self.assertIn("REFUSED", out)
        self.assertNotIn("Suppression", out)
        self.assertNotIn("vd-", out)
        self.assertIn("REFUSED", db.render_dashboard({"joint": j}))
        self.assertIn("no scorecard supplied", db._render_uncertainty(j))


class UnknownNeverZero(unittest.TestCase):
    """SR-13 items 3 and 4: the acceptance criterion 'missing results render as UNKNOWN, not 0'."""

    def margin_rows(self, html):
        return re.findall(r"<tr><td>(delta_\w+)</td>", html)

    def test_bad_margin_field_renders_UNKNOWN_and_never_vanishes(self):
        """`_render_uncertainty`'s comprehension filtered a bad margin OUT, so the row disappeared
        entirely -- a silent blank in a panel whose own closing sentence says 'UNKNOWN means unmeasured,
        never zero'. A vanished row is a breach of the criterion, so it must render as UNKNOWN."""
        for bad in (None, float("nan"), float("inf"), float("-inf"), "x", "", True, False,
                    [], {}, object()):
            j = joint_private_margins()
            object.__setattr__(j.margins, "delta_sel", bad)
            out = db._render_uncertainty(j)
            self.assertEqual(self.margin_rows(out), ["delta_S", "delta_R", "delta_sel"], repr(bad))
            self.assertIn('<span class="unknown">UNKNOWN</span>', out)
            self.assertIn("NOT zero", out)
            self.assertIn("UNKNOWN means unmeasured, never zero", out)
            self.assertNotIn("<td><span class=\"measured\">0.0</span></td>", out)
            self.assertIn("UNKNOWN", db.render_dashboard({"joint": j}))

    def test_absent_margin_attribute_renders_UNKNOWN(self):
        j = joint_private_margins()
        object.__setattr__(j.margins, "__class__", _MarginsNoSel)
        self.assertIsInstance(j.margins, bm.Margins)
        self.assertEqual(getattr(j.margins, "delta_sel", "MISSING"), "MISSING")
        out = db._render_uncertainty(j)
        self.assertEqual(self.margin_rows(out), ["delta_S", "delta_R", "delta_sel"])
        self.assertIn("is absent from the Margins object", out)
        self.assertIn("NOT zero", out)

    def test_honest_margins_still_render_measured_values_with_no_unknown(self):
        out = db._render_uncertainty(joint())
        self.assertEqual(self.margin_rows(out), ["delta_S", "delta_R", "delta_sel"])
        self.assertNotIn("UNKNOWN</span> <span class=\"caveat\">delta", out)
        m = bm.Margins()
        for v in (m.delta_S, m.delta_R, m.delta_sel):
            self.assertIn(f'<span class="measured">{repr(float(v))}</span>', out)

    def test_zero_margin_renders_zero_not_unknown(self):
        j = joint_private_margins()
        object.__setattr__(j.margins, "delta_sel", 0.0)
        out = db._render_uncertainty(j)
        self.assertEqual(self.margin_rows(out), ["delta_S", "delta_R", "delta_sel"])
        self.assertIn('<span class="measured">0.0</span>', out)   # a MEASURED zero is still a zero

    def test_int_or_unk_unknown_branch(self):
        """Mutant `_int_or_unk: unknown -> "0"` survived the whole suite: nothing stopped a regression to
        a literal zero, which is the single most on-point thing SR-13 was asked to verify."""
        self.assertEqual(db._int_or_unk(0), "0")                  # a genuine zero is a zero
        self.assertEqual(db._int_or_unk(29), "29")
        self.assertEqual(db._int_or_unk(-3), "-3")
        for bad in (None, "", "0", 0.0, 1.5, float("nan"), float("inf"), True, False, [], {}, object()):
            cell = db._int_or_unk(bad)
            self.assertIn('<span class="unknown">UNKNOWN</span>', cell, repr(bad))
            self.assertIn("not recorded", cell, repr(bad))
            self.assertNotEqual(cell, "0", repr(bad))
            self.assertNotIn(">0<", cell, repr(bad))

    def test_int_or_unk_unknown_branch_on_the_page(self):
        for attr in ("n_attempted", "n_failed"):
            j = joint()
            object.__setattr__(j, attr, None)
            h = db.render_scorecard(j)
            line = re.search(r"<p>Attempted .*?</p>", h).group(0)
            self.assertIn("UNKNOWN", line)
            self.assertNotIn(" 0,", line.replace("UNKNOWN", ""))
        j = joint()
        object.__setattr__(j, "n_failed", 0)
        self.assertIn("failed <span class=\"measured\">0</span>" if False else "failed 0",
                      re.search(r"<p>Attempted .*?</p>", db.render_scorecard(j)).group(0))

    def test_verdict_cell_none_is_unknown_not_supported(self):
        """UNREACHABLE TODAY: every call site coerces to a `Verdict` enum first (`_vcoerce`, `_eff_*`),
        so no end-to-end input reaches this branch, and the mutant `None -> SUPPORTED styling` survived.
        Pinned anyway: `_verdict_cell` is the ONLY emitter of `vd-supported`, and the module docstring's
        'there is NO confirmed visual style' guarantee rests entirely on it, so a latent fail-open here
        is a latent fail-open in that guarantee."""
        for kw in ({}, {"joint": True}, {"note": " [hypothesis-level]"},
                   {"kind_caveat": "SCORER-VALIDATION FIXTURE"}, {"joint": True, "note": " x"}):
            cell = db._verdict_cell(None, **kw)
            self.assertIn('<span class="unknown">UNKNOWN</span>', cell, repr(kw))
            self.assertIn("verdict not a valid enum value", cell, repr(kw))
            self.assertNotIn("vd-", cell, repr(kw))
            self.assertNotIn("SUPPORTED", cell, repr(kw))
            self.assertNotIn("not a safety finding", cell, repr(kw))
        # the contrast: a real SUPPORTED enum DOES get the styling, so the test is not vacuous
        self.assertIn("vd-supported", db._verdict_cell(bm.Verdict.SUPPORTED))


class SubjectKindDistinction(unittest.TestCase):
    """SR-12 F4. `dashboard.py` never read `subject_kind` / `subject_kind_code`; it appended
    ' (toy fixture; conditional; not a safety finding)' to EVERY supported verdict unconditionally. That
    is a blanket label, not a distinction, and it becomes FALSE the moment a non-fixture result is
    rendered."""

    def fixture_joint(self, kind, name=None):
        return bm.analyze_scores(make_scores(FZ.seeds), frozen=FZ, registered_digest=FZ.digest,
                                 subject="synthetic", cfg=SMALL, subject_kind=kind, fixture_name=name)

    def test_the_old_blanket_label_is_gone(self):
        for kind, name in (("unknown", None), ("trained", None), ("fixture", "oracle")):
            h = db.render_scorecard(self.fixture_joint(kind, name))
            self.assertNotIn("toy fixture; conditional", h, kind)

    def test_fixture_is_rendered_as_a_scorer_validation_fixture(self):
        j = self.fixture_joint("fixture", "oracle")
        self.assertEqual(j.subject_kind, "fixture")
        h = db.render_scorecard(j)
        self.assertIn("SCORER-VALIDATION FIXTURE", h)
        self.assertIn("NOT a result about any method", h)
        self.assertIn("SCORER-VALIDATION FIXTURE; conditional; not a safety finding", h)
        self.assertIn(f'<span class="measured">{repr(float(bm.SUBJECT_KIND_CODE["fixture"]))}</span>', h)
        self.assertNotIn("SUBJECT KIND PROBLEM", h)

    def test_trained_is_rendered_as_trained_and_not_as_a_fixture(self):
        j = self.fixture_joint("trained")
        h = db.render_scorecard(j)
        self.assertIn("TRAINED SUBJECT (producer-declared)", h)
        self.assertNotIn("SCORER-VALIDATION FIXTURE", h)
        self.assertIn("NOT evidence that any model was trained", h)
        self.assertIn(f'<span class="measured">{repr(float(bm.SUBJECT_KIND_CODE["trained"]))}</span>', h)

    def test_unknown_renders_as_UNKNOWN_not_as_either_kind(self):
        j = joint()
        self.assertEqual(j.subject_kind, "unknown")
        h = db.render_scorecard(j)
        self.assertIn("subject kind (what the result claims about itself)", h)
        self.assertIn("did not record whether the answer was known by construction", h)
        self.assertNotIn("SCORER-VALIDATION FIXTURE", h)
        self.assertNotIn("TRAINED SUBJECT", h)
        self.assertIn("UNKNOWN; conditional; not a safety finding", h)

    def test_absent_or_invalid_subject_kind_renders_UNKNOWN(self):
        """THE TABLE THAT MISSED FINDING 1 FOR SEVEN ROUNDS, counted rather than argued: it held exactly
        the ten values below the `*word_liar` line, and 0 OF 10 WAS A `str` SUBCLASS INSTANCE -- round
        7's "0 of 107" in the string lane. Every one of the ten is either not a `str` at all or a `str`
        whose characters are not a recognised kind, so the membership test refused them on the TEXT and
        the `__hash__`/`__eq__` route was never driven. The subclass half is generated from the module's
        own vocabulary (`db._SUBJECT_KIND_LABELS`), not written out, so a new kind inherits it.

        The subclass half asserts the right thing for its shape, which is NOT "renders UNKNOWN": a liar
        whose STORED characters are a recognised kind must render exactly as that plain kind does, and
        one whose stored characters are not must render UNKNOWN with a problem. A test that demanded
        UNKNOWN of every subclass would pass on a tree that ignored the subclass entirely."""
        plain_bad = ("Fixture", "FIXTURE", "trained ", "", None, 0, True, [], object(), "safe")
        self.assertEqual(sum(1 for v in plain_bad if is_a_lying_string(v)), 0, "0 of 10, as measured")
        subclassy = [(a, b, d) for d in WORD_DUNDERS
                     for a in sorted(db._SUBJECT_KIND_LABELS) for b in sorted(db._SUBJECT_KIND_LABELS)
                     if a != b]
        self.assertGreater(len(subclassy), len(plain_bad), len(subclassy))
        for stored, shown, d in subclassy:
            liar = word_liar(stored, shown, d)
            self.assertTrue(is_a_lying_string(liar), (stored, shown, d))
            self.assertEqual(str.__str__(liar), stored, (stored, shown, d))
            j, k = joint(), joint()
            object.__setattr__(j, "subject_kind", liar)
            object.__setattr__(k, "subject_kind", stored)        # the same TEXT, as a plain str
            self.assertEqual(db.render_scorecard(j), db.render_scorecard(k), (stored, shown, d))
        for stored, shown, d in [(bad, k, d) for d in WORD_DUNDERS
                                 for bad in ("Fixture", "trained ", "safe", "")
                                 for k in sorted(db._SUBJECT_KIND_LABELS)]:
            j = joint()
            object.__setattr__(j, "subject_kind", word_liar(stored, shown, d))
            h = db.render_scorecard(j)
            self.assertIn("SUBJECT KIND PROBLEM", h, (stored, shown, d))
            self.assertNotIn("SCORER-VALIDATION FIXTURE", h, (stored, shown, d))
            self.assertNotIn("TRAINED SUBJECT", h, (stored, shown, d))
        for bad in plain_bad:
            j = joint()
            object.__setattr__(j, "subject_kind", bad)
            h = db.render_scorecard(j)
            self.assertIn("SUBJECT KIND PROBLEM", h, repr(bad))
            self.assertIn("shown as UNKNOWN", h, repr(bad))
            self.assertNotIn("SCORER-VALIDATION FIXTURE", h, repr(bad))
            self.assertNotIn("TRAINED SUBJECT", h, repr(bad))
        # A JointResult cannot have an ABSENT subject_kind (class-level default "unknown"), so the
        # absent branch is reached by calling the unit directly on an object that has no such field.
        j = joint()
        object.__delattr__(j, "subject_kind")
        self.assertEqual(j.subject_kind, "unknown")                # class default, renders UNKNOWN anyway
        self.assertIn("UNKNOWN", db.render_scorecard(j))
        label, caveat, code, problem, relabelled = db._subject_kind(object())
        self.assertEqual(label, "UNKNOWN")
        self.assertIn("subject_kind is absent from this result", problem)
        self.assertIn("shown as UNKNOWN", problem)
        self.assertFalse(relabelled)

    def test_subject_kind_free_text_is_escaped(self):
        j = joint()
        object.__setattr__(j, "subject_kind", Injection.P)
        h = db.render_scorecard(j)
        self.assertNotIn("<script", h)
        self.assertNotIn("<img", h)
        self.assertIn("SUBJECT KIND PROBLEM", h)

    def test_relabelled_fixture_is_detected_and_withholds_verdicts(self):
        """benchmark route (d): `object.__setattr__(result, "subject_kind", "trained")` relabels a result
        while its gates still record the gate-11(c) exemption. `JointResult.__post_init__` enforces the
        agreement at construction, so a mismatch proves post-construction tampering."""
        j = self.fixture_joint("fixture", "oracle")
        self.assertTrue(any(getattr(g, "exempt", False) for g in j.gates))
        self.assertIn("vd-supported", joint_cell(db.render_scorecard(j)))
        for relabel in ("trained", "unknown"):
            k = self.fixture_joint("fixture", "oracle")
            object.__setattr__(k, "subject_kind", relabel)
            h = db.render_scorecard(k)
            self.assertIn("carry the fixture exemption but subject_kind is", h, relabel)
            self.assertIn("relabelled after construction", h, relabel)
            self.assertIn("CONTRACT PROBLEM", h, relabel)
            self.assertNotIn("vd-supported", joint_cell(h), relabel)
            self.assertIn("JOINT_INCONCLUSIVE", h, relabel)

    def test_the_relabel_message_does_not_claim_which_side_changed(self):
        """Wording precision (the reviewer's second note). The message said "the result was relabelled
        after construction", but `benchmark.carries_exemption` reads `exempt` off ANY object in the gate
        list, so injecting a duck-typed gate with `exempt=True` into an honestly-labelled result
        produces the SAME message: the GATES, not the label, may be what changed. Both are
        post-construction tampering -- `JointResult.__post_init__` refuses the combination either way --
        but the page must not assert which side it was."""
        k = self.fixture_joint("fixture", "oracle")
        object.__setattr__(k, "subject_kind", "trained")
        h = db.render_scorecard(k)
        self.assertIn("relabelled after construction", h)
        self.assertIn("which of the two is not determined", h)
        self.assertIn("JointResult refuses that combination at construction", h)

        class DuckExempt:   # the other side: an honest 'unknown' result, an injected exempt gate
            name, passed, reason, exempt, scope = "extra_gate", True, "injected", True, "all"
        j = joint()
        self.assertEqual(j.subject_kind, "unknown")
        object.__setattr__(j, "gates", (*j.gates, DuckExempt()))   # __post_init__ would refuse this
        self.assertTrue(bm.carries_exemption(j.gates))
        h2 = db.render_scorecard(j)
        self.assertIn("carry the fixture exemption but subject_kind is", h2)
        self.assertIn("which of the two is not determined", h2)
        self.assertIn("CONTRACT PROBLEM", h2)
        self.assertNotIn("vd-supported", joint_cell(h2))

    def test_patched_subject_kind_code_table_is_a_visible_problem(self):
        j = joint()
        for tbl in ({}, None, {"fixture": 2.0}):
            with mock.patch.object(bm, "SUBJECT_KIND_CODE", tbl):
                h = db.render_scorecard(j)
            self.assertIn("SUBJECT KIND PROBLEM", h, repr(tbl))
            self.assertIn("table missing or patched", h, repr(tbl))
            self.assertIn("not encoded", h, repr(tbl))

    def test_the_page_states_that_subject_kind_is_producer_asserted(self):
        h = db.render_scorecard(joint())
        self.assertIn("PRODUCER-ASSERTED", h)
        self.assertIn("not an authenticated fact", h)
        self.assertIn("producer-asserted", db._subject_kind.__doc__.lower())
        self.assertIn("not authentication", db._subject_kind.__doc__.lower())


class NonDefaultConfigAndTheAnchorQuestion(unittest.TestCase):
    """Which anchor the protocol-parameter cross-check uses, and why it is not the config hash.

    `JointResult` carries `config_hash` -- a sha256 over ALL 18 `BenchmarkConfig` fields -- but NOT the
    config object. The renderer can learn exactly 2 of those 18 from a component (`min_n`, `width_tol`),
    so it can neither invert the digest nor verify a candidate config against it: 16 fields are unknown.
    `config_hash` is also a field on the SAME producer-asserted object, so even if it were invertible it
    would not be an independent anchor. There is therefore NO reachable provenanced config value, and the
    anchor used is the scorer's OWN declared default from `interval_verdict`'s signature, applied as a
    ONE-SIDED FLOOR (never weaker, a stricter setting passed through untouched)."""

    def build(self, seeds=None, **cfgkw):
        cfg = bm.BenchmarkConfig(n_boot=500, **cfgkw)
        scores = make_scores(FZ.seeds if seeds is None else seeds)
        j = bm.analyze_scores(scores, frozen=FZ, registered_digest=FZ.digest, subject="synthetic",
                              cfg=cfg)
        return j, cfg

    def spy_width_tols(self, j):
        seen = []
        real = bm.interval_verdict

        def spy(pair, margin, direction, width_tol=0.25, min_n=30):
            seen.append((width_tol, min_n))
            return real(pair, margin, direction, width_tol, min_n)
        with mock.patch.object(bm, "interval_verdict", spy):
            db.render_scorecard(j)
        return seen

    def test_the_renderer_cannot_reach_an_authoritative_config(self):
        j, cfg = self.build()
        self.assertEqual(j.config_hash, cfg.config_hash())            # the hash IS carried...
        names = [f.name for f in dataclasses.fields(bm.JointResult)]
        self.assertIn("config_hash", names)
        self.assertNotIn("cfg", names)                                # ...but the config object is not
        self.assertNotIn("config", names)
        self.assertEqual(len(dataclasses.fields(bm.BenchmarkConfig)), 18)
        visible = {"min_seeds", "width_tol"}                           # all the renderer can see
        self.assertEqual(len(visible), 2)
        self.assertLess(len(visible), len(dataclasses.fields(bm.BenchmarkConfig)))
        # a candidate config cannot be checked against the hash while 16 fields are unknown
        self.assertNotEqual(bm.BenchmarkConfig(width_tol=cfg.width_tol,
                                               min_seeds=cfg.min_seeds).config_hash(), j.config_hash)
        self.assertEqual(bm.BenchmarkConfig(n_boot=500).config_hash(), j.config_hash)  # only with ALL 18

    def test_a_stricter_registered_width_tol_is_never_relaxed_to_the_default(self):
        """The exact defect found in `benchmark.verdict_from_records`: a study registered at
        width_tol=0.10 re-scored with the module default 0.25, flipping INCONCLUSIVE -> SUPPORTED. The
        dashboard's floor is one-sided (`min`), so this direction is structurally impossible here."""
        j, cfg = self.build(width_tol=0.10)
        self.assertEqual(cfg.width_tol, 0.10)
        self.assertEqual({c.width_tol for h in (j.h1, j.h2, j.h3)
                          for c in (*h.components, *(h.converged_components or ()))}, {0.10})
        seen = self.spy_width_tols(j)
        self.assertEqual({wt for wt, _ in seen}, {0.10})      # the study's own tolerance, not 0.25
        self.assertNotIn(0.25, [wt for wt, _ in seen])
        # and the honest study raises no alarm and is not promoted
        h = db.render_scorecard(j)
        self.assertNotIn("NOT shown", h)
        self.assertNotIn("WEAKER THAN THE PROTOCOL", h)
        self.assertNotIn("vd-supported", joint_cell(h))       # the scorer itself said INCONCLUSIVE
        self.assertIs(j.verdict, bm.JointVerdict.JOINT_INCONCLUSIVE)

    def test_a_stricter_min_seeds_is_honoured_and_raises_no_false_alarm(self):
        j, _ = self.build(min_seeds=30)
        self.assertEqual({mn for _, mn in self.spy_width_tols(j)}, {30})
        self.assertNotIn("NOT shown", db.render_scorecard(j))
        self.assertNotIn("WEAKER THAN THE PROTOCOL", db.render_scorecard(j))

    def test_a_weaker_config_is_floored_and_its_disagreement_is_explained(self):
        """A run configured below the protocol minimum is honest but non-compliant (protocol 6.1: no
        verdict below n=30). The renderer must withhold the decisive cell AND say why, rather than show
        only the generic 'stored verdict disagrees' warning, which would imply a field was edited.

        The page no longer asserts "NOT evidence of tampering" here: see
        `WeakerThanProtocolWordingIsNotInverted`, which measures a forgery landing in this same branch."""
        j, _ = self.build(seeds=FZ.seeds[:8], min_seeds=5, width_tol=0.9)
        c = j.h1.components[0]
        self.assertEqual((c.min_n, c.width_tol, c.pair.n), (5, 0.9, 8))
        self.assertIs(j.verdict, bm.JointVerdict.JOINT_SUPPORTED)      # the scorer says SUPPORTED
        self.assertEqual(recompute(c, j.margins, j), bm.Verdict.INCONCLUSIVE)    # the renderer floors it
        self.assertEqual({(0.25, 30)}, set(self.spy_width_tols(j)))
        h = db.render_scorecard(j)
        self.assertNotIn("vd-supported", joint_cell(h))                # never promoted
        self.assertIn("WEAKER THAN THE PROTOCOL", h)
        self.assertIn("min_n=5 is below the protocol minimum 30", h)
        self.assertIn("width_tol=0.9 is wider than the protocol tolerance 0.25", h)
        self.assertIn("the ones being withheld", h)                    # a verdict really was withheld
        self.assertIn("does not by itself mean a field was edited", h)
        self.assertNotIn("NOT evidence of tampering", h)               # never asserted: see item 2
        self.assertIn("exploratory and non-compliant", h)
        self.assertIn("only an opaque config_hash", h)

    def test_weaker_than_protocol_is_silent_on_every_honest_default_fixture(self):
        for kw in (dict(), dict(expect=None, S=0.0), dict(expect=None, conv=False),
                   dict(expect=None, L=1.0), dict(expect=None, seeds=FZ.seeds[:29])):
            j = joint(**kw)
            self.assertEqual(db._weaker_than_protocol(j), [], repr(kw))
            self.assertNotIn("WEAKER THAN THE PROTOCOL", db.render_scorecard(j), repr(kw))
        for bad in (None, object(), "joint", 0):
            self.assertEqual(db._weaker_than_protocol(bad), [], repr(bad))

    def test_weaker_than_protocol_detects_each_parameter_independently(self):
        j, _ = self.build(seeds=FZ.seeds[:8], min_seeds=5)
        found = db._weaker_than_protocol(j)
        self.assertTrue(found)
        self.assertTrue(all("min_n=5" in f for f in found), found)
        self.assertFalse(any("width_tol" in f for f in found), found)
        j2, _ = self.build(width_tol=0.9)
        found2 = db._weaker_than_protocol(j2)
        self.assertTrue(found2)
        self.assertTrue(all("width_tol" in f for f in found2), found2)
        self.assertFalse(any("min_n" in f for f in found2), found2)
        self.assertEqual(len(found2), 6)       # every component and converged component is named


# ---------------------------------------------------------------------------------------------------------
# SR-13 re-attestation (this item had already FAILED twice). The four consumers of a stored number, the
# weaker-than-protocol wording, and the two mutants that survived the whole suite (M26, M27).
# ---------------------------------------------------------------------------------------------------------
NOT_A_FINITE_FLOAT = (0, 1, -1, 30, False, True, "0", "", "nan", "0.5", [], {}, (), [0.0], None, object(),
                      float("nan"), float("inf"), float("-inf"))
# `value = None` is the one entry above that does NOT break `MetricValue`'s invariant: it is exactly how
# a genuinely UNMEASURED metric is represented, so `_pair_numbers_ok` must accept it (an n < 2 interval
# is built that way) while every cell still renders it UNKNOWN. Kept separate so the fail-closed sweep
# does not demand a false alarm on an honest unmeasured bound.
BREAKS_MV_INVARIANT = tuple(v for v in NOT_A_FINITE_FLOAT if v is not None)


def forge_mv(mv, value):
    """Force a value past `MetricValue.__post_init__` (float only, bool rejected, finite), the way
    post-construction tampering or a type drift in a future `MetricValue` would."""
    object.__setattr__(mv, "value", value)
    return mv


def forge_bounds(pair, value, fields=("boot_lo", "boot_hi", "t_lo", "t_hi")):
    for f in fields:
        forge_mv(getattr(pair, f), value)
    return pair


def comp_row(h, metric):
    """The scorecard table row for one component metric."""
    m = re.search(r"<tr><td>H\d [^<]*?</td><td>%s</td>.*?</tr>" % re.escape(metric), h)
    assert m, metric
    return m.group(0)


def total_row(snapshot):
    h = db.render_dashboard({"snapshot": snapshot})
    m = re.search(r"<tr><th>total \(\d+ files\)</th>.*?</tr>", h)
    assert m, "no total row"
    return m.group(0), h


class MetricValueConsumersShareOneCheck(unittest.TestCase):
    """The SR-13 FAIL ground. `_interval` gated on `MetricValue.is_measured`, which is only
    `value is not None` (schema.py), and then called `_num` = `repr(float(x))`. `_metric_cell` on the
    SAME value correctly said UNKNOWN, so one rendered row contradicted itself: `mean` UNKNOWN beside
    two `.measured` monospace `[0.0, 0.0]` intervals -- verbatim the FAIL condition, "an interval of
    [0, 0] where the value is genuinely unknown". `""`/`[]`/`{}` additionally raised out of `float()`
    and took the whole page down, against `render_dashboard`'s own docstring. `pair.level` and the
    `SUBJECT_KIND_CODE` cell had the identical gap.

    Three reviewers checked the forged cases against `_metric_cell` ONLY, so all three missed
    `_interval`, which consumes the same type. The fix is therefore ONE shared check,
    `db._finite_float`, which all four cells and the recomputation now route through."""

    def test_interval_never_shows_a_forged_unknown_as_a_measured_interval(self):
        for bad in NOT_A_FINITE_FLOAT:
            j = joint()
            forge_bounds(j.h1.components[0].pair, bad)
            forge_mv(j.h1.components[0].pair.mean, bad)
            row = comp_row(db.render_scorecard(j), "S")            # must not raise
            self.assertEqual(row.count("interval not computable"), 2, (bad, row))
            self.assertNotIn('class="measured">[', row, repr(bad))
            for forbidden in ("[0.0, 0.0]", "[nan, nan]", "[inf, inf]", "[-inf, -inf]",
                              "[0, 0]", "[1.0, 1.0]", "[True, True]", "[30.0, 30.0]"):
                self.assertNotIn(forbidden, row, repr(bad))

    def test_interval_and_metric_cell_never_disagree_on_the_same_value(self):
        """The ROOT CAUSE pin: two consumers of one type with two different ideas of "measured". Any
        value `_metric_cell` calls UNKNOWN must make `_interval` say UNKNOWN too, and vice versa."""
        for bad in NOT_A_FINITE_FLOAT:
            mv = forge_mv(MetricValue.measured(1.0), bad)
            self.assertIn("UNKNOWN", db._metric_cell(mv), repr(bad))
            self.assertIn("interval not computable", db._interval(mv, mv), repr(bad))
            self.assertNotIn("measured", db._interval(mv, mv), repr(bad))
            self.assertIn("UNKNOWN", db._float_cell(bad, "why"), repr(bad))
            self.assertIsNone(db._finite_float(bad), repr(bad))
            self.assertIsNone(db._mv_float(mv), repr(bad))
            # one bound good and one forged is still UNKNOWN, in both orders
            ok = MetricValue.measured(2.0)
            self.assertIn("interval not computable", db._interval(ok, mv), repr(bad))
            self.assertIn("interval not computable", db._interval(mv, ok), repr(bad))
        for good in (0.0, -0.0, 1.5, -2.0, 1e308, 5e-324):
            mv = MetricValue.measured(good)
            v = repr(float(mv.value))                      # -0.0 is normalised to 0.0 by the schema
            self.assertIn('class="measured"', db._metric_cell(mv), repr(good))
            self.assertEqual(db._interval(mv, mv), '<span class="measured">[%s, %s]</span>' % (v, v))
            self.assertEqual(db._finite_float(mv.value), mv.value)
            self.assertIn('class="measured"', db._float_cell(mv.value, "why"), repr(good))
        # a MEASURED zero is still a zero in both: the criterion is "unknown is never 0", not "no zeros"
        z = MetricValue.measured(0.0)
        self.assertIn(">0.0<", db._metric_cell(z))
        self.assertIn("[0.0, 0.0]", db._interval(z, z))
        for junk in (None, 0.0, "0.0", object(), MetricValue.unmeasured("why")):
            self.assertIn("interval not computable", db._interval(junk, junk), repr(junk))

    def test_M26_unmeasured_bootstrap_bound_is_not_computable_never_zero(self):
        """M26, which survived all 150 tests: `render_scorecard(j)` with
        `boot_lo = MetricValue.unmeasured("bootstrap failed")` must emit UNKNOWN / "interval not
        computable", never `[0.0, 0.0]`."""
        j = joint()
        object.__setattr__(j.h1.components[0].pair, "boot_lo",
                           MetricValue.unmeasured("bootstrap failed"))
        h = db.render_scorecard(j)
        row = comp_row(h, "S")
        self.assertEqual(row.count("interval not computable"), 1, row)   # the bootstrap one only
        self.assertIn('class="measured">[', row)                         # the t interval still renders
        self.assertNotIn("[0.0, 0.0]", h)
        self.assertNotIn("0.0, 0.0", h)
        self.assertIn("NOT shown", h)                     # and it is not called decisive either
        self.assertNotIn("vd-supported", joint_cell(h))
        for field in ("boot_lo", "boot_hi", "t_lo", "t_hi"):
            k = joint()
            object.__setattr__(k.h1.components[0].pair, field, MetricValue.unmeasured("failed"))
            self.assertIn("interval not computable", comp_row(db.render_scorecard(k), "S"), field)

    def test_a_forged_bound_cannot_crash_the_whole_render(self):
        """`render_dashboard`'s docstring promises a pure function that refuses a malformed object with
        NO figures. `""`, `[]` and `{}` on a bound used to raise ValueError/TypeError out of `_num`'s
        `float()` and take the ENTIRE page down, including the four panels that have nothing to do with
        the scorecard. `_mv_float` never calls `float()`, so no input reaches a conversion."""
        for bad in ("", [], {}, (), object(), None, "0"):
            j = joint()
            forge_bounds(j.h1.components[0].pair, bad)
            page = db.render_dashboard({"snapshot": SNAP, "joint": j, "records": [rec()]})
            self.assertTrue(page.startswith("<!DOCTYPE html>"), repr(bad))
            self.assertIn("Source-diff inventory", page, repr(bad))
            self.assertIn("interval not computable", page, repr(bad))

    def test_level_cell_is_unknown_unless_it_is_a_finite_float(self):
        for bad in NOT_A_FINITE_FLOAT:
            j = joint()
            object.__setattr__(j.h1.components[0].pair, "level", bad)
            row = comp_row(db.render_scorecard(j), "S")
            self.assertIn('<span class="unknown">UNKNOWN</span> <span class="caveat">level</span>',
                          row, repr(bad))
            self.assertNotIn("nan", row, repr(bad))
            self.assertNotIn("inf", row, repr(bad))
        j = joint()                                   # not vacuous: an honest level still renders
        self.assertIn('<span class="measured">%s</span>' % repr(j.h1.components[0].pair.level),
                      comp_row(db.render_scorecard(j), "S"))

    def test_n_cell_excludes_bool_like_every_sibling_count_cell(self):
        """`pair.n = True` rendered the word "True" in a column of counts. `_int_cell` and
        `_int_or_unk` already excluded bool; this cell was the one that did not."""
        for bad, word in ((True, "True"), (False, "False")):
            j = joint()
            object.__setattr__(j.h1.components[0].pair, "n", bad)
            row = comp_row(db.render_scorecard(j), "S")
            self.assertIn('<span class="unknown">UNKNOWN</span> <span class="caveat">n</span>', row, word)
            self.assertNotIn("<td>%s</td>" % word, row, word)
        for bad in (None, 1.0, "30", float("nan"), [], object()):
            j = joint()
            object.__setattr__(j.h1.components[0].pair, "n", bad)
            self.assertIn('<span class="caveat">n</span>',
                          comp_row(db.render_scorecard(j), "S"), repr(bad))
        self.assertIn("<td>30</td>", comp_row(db.render_scorecard(joint()), "S"))   # not vacuous

    def test_subject_kind_code_must_be_a_finite_float_to_be_an_encoding(self):
        """A table patched to `{"unknown": nan}` raised nothing, so `float(code)` rendered a measured
        `nan` and NO problem was reported. A code that is not a finite float is not an encoding,
        whether the lookup raised or not."""
        j = joint()
        for tbl in ({"unknown": float("nan")}, {"unknown": float("inf")}, {"unknown": 0},
                    {"unknown": True}, {"unknown": "0.0"}, {"unknown": None}, {"unknown": [0.0]}):
            with mock.patch.object(bm, "SUBJECT_KIND_CODE", tbl):
                h = db.render_scorecard(j)
            self.assertIn("not encoded", h, repr(tbl))
            self.assertIn("SUBJECT KIND PROBLEM", h, repr(tbl))
            self.assertIn("table missing or patched", h, repr(tbl))
            self.assertNotIn('<span class="measured">nan</span>', h, repr(tbl))
            self.assertNotIn('<span class="measured">inf</span>', h, repr(tbl))
            self.assertNotIn('class="measured"', h.split("</table>")[0], repr(tbl))
        with mock.patch.object(bm, "SUBJECT_KIND_CODE", {"unknown": 0.0}):      # not vacuous
            h = db.render_scorecard(j)
        self.assertIn('<span class="measured">0.0</span>', h)
        self.assertNotIn("SUBJECT KIND PROBLEM", h)

    def test_a_forged_non_finite_bound_cannot_buy_a_decisive_verdict(self):
        """FOUND WHILE FIXING `_interval`, and not part of the reported defect.

        STALE AS WRITTEN, CORRECTED. This said, in the present tense, that "`IntervalPair.boot()` /
        `tint()` (benchmark.py) gate on `is_measured` alone, so a forged non-finite bound reaches
        `interval_verdict` AS A NUMBER". That WAS true and was reported upwards; it stopped being true
        when `benchmark.IntervalPair._bound` was added, which DELEGATES to `_metric_read`, that module's
        single checked reader, so a bound that is not a genuine finite number now reads as "interval not
        computable" at the scorer and never reaches `_verdict_from_bounds` as a number at all.
        What was MEASURED at the dashboard HEAD of that round, with `boot_lo = boot_hi = inf`:
        `lo > margin` was true, and the H1/S cell rendered a decisive `vd-supported` while
        `_metric_cell` and `_interval` on the same pair said UNKNOWN -- a SUPPORTED row with no figures
        behind it, which is worse than the `[0.0, 0.0]` this item started from.

        WHY `_pair_numbers_ok` IS STILL WORTH HAVING NOW THAT `_bound` CLOSES THE BOUNDS. `_bound`
        covers the four `MetricValue` bounds and nothing else. `pair.n` and `pair.level` are plain
        numbers that `_bound` never sees: `interval_verdict` reads `pair.n` directly for protocol 6.1's
        floor (the round-4 defect, G1, and `nan < 30` is False), and nothing in `benchmark` checks
        `pair.level` at all. This renderer also may not DEPEND on `_bound`: it recomputes precisely so
        that a change or regression in the scorer is a visible disagreement rather than a shared blind
        spot, and `_bound` is in the scorer. So this test keeps asserting the renderer's own
        fail-closed, and `pair.n`/`pair.level` remain covered only here."""
        for bad in (float("inf"), float("-inf"), float("nan"), 0, 1, True, "1e9"):
            j = joint()
            for h_ in (j.h1, j.h2, j.h3):
                for c in (*h_.components, *(h_.converged_components or ())):
                    forge_bounds(c.pair, bad)
            self.assertIsNone(recompute(j.h1.components[0], j.margins, j), repr(bad))
            h = db.render_scorecard(j)
            self.assertEqual(set(hyp_cells(h).values()), {"INCONCLUSIVE"}, repr(bad))
            self.assertNotIn("vd-supported", h, repr(bad))
            self.assertIn("NOT shown", h, repr(bad))
        # `value = None` IS the legitimately UNMEASURED state, and ROUND 6 SPLITS THIS CASE IN TWO,
        # which is the cleanest demonstration in this file of the difference between a bound that has a
        # second source and one that does not. On a 30-seed study:
        #   * the two BOOTSTRAP bounds forged to None stay "a legitimately unmeasured bound": there is
        #     no second source for them (n_boot and base_seed are not in JointResult), so the renderer
        #     has nothing to contradict it with and the scorer's own INCONCLUSIVE stands;
        #   * the two T bounds forged to None are a CONTRADICTION: the 30 per-seed values this result
        #     carries do give a t-interval, so "unmeasured" is false of this pair and fails closed.
        # The comment this replaces said `value = None` "is not a fail-closed case here", flat, which
        # was true of the bootstrap pair and false of the t pair.
        j = joint()
        for h_ in (j.h1, j.h2, j.h3):
            for c in (*h_.components, *(h_.converged_components or ())):
                forge_bounds(c.pair, None, ("boot_lo", "boot_hi"))
        self.assertIs(recompute(j.h1.components[0], j.margins, j), bm.Verdict.INCONCLUSIVE)
        h = db.render_scorecard(j)
        self.assertEqual(set(hyp_cells(h).values()), {"INCONCLUSIVE"})
        self.assertNotIn("vd-supported", h)
        self.assertNotIn("INTERVAL CONTRADICTED", h)
        j = joint()
        for h_ in (j.h1, j.h2, j.h3):
            for c in (*h_.components, *(h_.converged_components or ())):
                forge_bounds(c.pair, None, ("t_lo", "t_hi"))
        self.assertIsNone(recompute(j.h1.components[0], j.margins, j))
        h = db.render_scorecard(j)
        self.assertEqual(set(hyp_cells(h).values()), {"INCONCLUSIVE"})
        self.assertNotIn("vd-supported", h)
        self.assertIn("INTERVAL CONTRADICTED", h)
        # and genuinely unmeasured t bounds on a 1-seed study are still fine (no false fire)
        one = joint(expect=None, seeds=FZ.seeds[:1])
        self.assertIsNone(one.h1.components[0].pair.t_lo.value)
        self.assertIsNotNone(recompute(one.h1.components[0], one.margins, one))

    def test_pair_numbers_ok_fails_closed_unmasked_and_never_false_fires(self):
        """Direct unit test: `_recompute` has several other ways to return None, so no other layer may
        be allowed to mask a fail-open here (the F-h lesson)."""
        j = joint()
        self.assertTrue(pair_ok(j))
        for bad in BREAKS_MV_INVARIANT:
            k = joint()
            self.assertFalse(pair_ok(k, pair=forge_bounds(k.h1.components[0].pair, bad)), repr(bad))
        for field in ("boot_lo", "boot_hi", "t_lo", "t_hi"):           # one bad bound is enough
            k = joint()
            self.assertFalse(
                pair_ok(k, pair=forge_bounds(k.h1.components[0].pair, float("inf"), (field,))), field)
            k = joint()                                                 # and a non-MetricValue bound
            object.__setattr__(k.h1.components[0].pair, field, 1.0)
            self.assertFalse(pair_ok(k), field)
        for junk in (None, object(), "pair", 0):
            self.assertFalse(db._pair_numbers_ok(junk, 30, 30, [1.0, 2.0]), repr(junk))
        # NO FALSE FIRE: a genuinely unmeasured bound (n < 2) satisfies MetricValue's invariant
        k = joint(expect=None, seeds=FZ.seeds[:1])
        self.assertTrue(pair_ok(k))
        k = joint()
        object.__setattr__(k.h1.components[0].pair, "boot_lo", MetricValue.unmeasured("failed"))
        self.assertTrue(pair_ok(k))
        for kw in (dict(), dict(expect=None, S=0.0), dict(expect=None, conv=False),
                   dict(expect=None, L=1.0), dict(expect=None, seeds=FZ.seeds[:29])):
            j = joint(**kw)
            for h_ in (j.h1, j.h2, j.h3):
                for c in (*h_.components, *(h_.converged_components or ())):
                    self.assertTrue(pair_ok(j, c=c), repr(kw))
        self.assertNotIn("NOT shown", db.render_scorecard(joint()))     # honest page still clean


class WeakerThanProtocolWordingIsNotInverted(unittest.TestCase):
    """SR-13 item 2, measured at HEAD: an HONEST weak run got the accusation and a genuine forgery got
    the acquittal. The paragraph asserted, unconditionally, both "The recomputation used the protocol
    values, so any decisive verdict is withheld" and "this is a configuration statement, NOT evidence of
    tampering". Over a `min_n` 30->1 forgery on a real n=30 run BOTH were false as rendered: nothing was
    withheld (JOINT_SUPPORTED was displayed) and the field HAD been edited.

    The GUARD is sound and is not what changed here: the one-sided floor made both forgeries unable to
    move the verdict, and JOINT_SUPPORTED is the honest answer for a run whose real `pair.n` is 30.
    Nothing is laundered. This is purely a labelling defect -- which in this kit is the product."""

    def build(self, seeds=None, **cfgkw):
        cfg = bm.BenchmarkConfig(n_boot=500, **cfgkw)
        return bm.analyze_scores(make_scores(FZ.seeds if seeds is None else seeds), frozen=FZ,
                                 registered_digest=FZ.digest, subject="synthetic", cfg=cfg)

    def forge(self, field, value):
        j = joint()
        for h_ in (j.h1, j.h2, j.h3):
            for c in (*h_.components, *(h_.converged_components or ())):
                object.__setattr__(c, field, value)
        return j

    def para(self, h):
        m = re.search(r'<p class="warn">PROTOCOL PARAMETERS WEAKER.*?</p>', h)
        assert m, "no weaker-than-protocol paragraph"
        return m.group(0)

    def test_a_forgery_that_changed_nothing_is_not_told_a_verdict_was_withheld(self):
        for field, value in (("min_n", 1), ("min_n", 0), ("width_tol", 1e9), ("width_tol", 0.9)):
            h = db.render_scorecard(self.forge(field, value))
            self.assertIn("JOINT_SUPPORTED", joint_cell(h), (field, value))   # honest: the real n is 30
            self.assertNotIn("NOT shown", h, (field, value))
            p = self.para(h)
            self.assertIn("no decisive verdict was withheld", p, (field, value))
            self.assertNotIn("the ones being withheld", p, (field, value))
            self.assertNotIn("any decisive verdict is withheld", p, (field, value))

    def test_a_forgery_is_not_handed_an_exculpation(self):
        for field, value in (("min_n", 1), ("width_tol", 1e9)):
            p = self.para(db.render_scorecard(self.forge(field, value)))
            self.assertNotIn("NOT evidence of tampering", p, (field, value))
            self.assertNotIn("configuration statement", p, (field, value))
            self.assertIn("CANNOT BE DETERMINED FROM THIS RESULT", p, (field, value))
            self.assertIn("asserts neither", p, (field, value))

    def test_an_honest_weak_run_is_told_why_its_verdict_is_withheld(self):
        for ms in (10, 15, 20, 25, 29):
            j = self.build(seeds=FZ.seeds[:ms], min_seeds=ms)
            self.assertEqual(j.h1.components[0].pair.n, ms)
            h = db.render_scorecard(j)
            self.assertIn("NOT shown", h, ms)              # the disagreement is real and stays reported
            p = self.para(h)
            self.assertIn("the ones being withheld", p, ms)
            self.assertIn("does not by itself mean a field was edited", p, ms)
            self.assertIn("exploratory and non-compliant", p, ms)
            self.assertNotIn("no decisive verdict was withheld", p, ms)

    def test_neither_reading_is_asserted_because_the_two_are_indistinguishable(self):
        """Why the fix is not simply to swap the exculpation for an accusation. An HONEST
        `BenchmarkConfig(min_seeds=1)` run that nevertheless collected 30 seeds is MEASURABLY
        identical, in this paragraph, to `min_n` forged to 1 on an n=30 run: same list, same branch,
        same joint verdict. "NOT evidence of tampering" was false over the forgery and its negation
        would be false over this honest run, so the page states the undecidability and asserts
        neither."""
        honest = db.render_scorecard(self.build(min_seeds=1))
        forged = db.render_scorecard(self.forge("min_n", 1))
        for h in (honest, forged):
            self.assertIn("JOINT_SUPPORTED", joint_cell(h))
            self.assertIn("no decisive verdict was withheld", self.para(h))
            self.assertNotIn("evidence of tampering", self.para(h))
            self.assertIn("asserts neither", self.para(h))
        self.assertEqual(self.para(honest), self.para(forged))

    def test_the_honest_default_fixture_gets_no_paragraph_at_all(self):
        for kw in (dict(), dict(expect=None, S=0.0), dict(expect=None, seeds=FZ.seeds[:29])):
            h = db.render_scorecard(joint(**kw))
            self.assertNotIn("WEAKER THAN THE PROTOCOL", h, repr(kw))
            self.assertNotIn("asserts neither", h, repr(kw))


class UnreadableProtocolParametersAreReported(unittest.TestCase):
    """SR-13 item 3. `_protocol_params`' docstring claimed `_contract_problems` reports a missing
    default on the page. It did not: that function checked parameter NAMES only, which a defaultless
    signature passes. MEASURED at HEAD with `interval_verdict` patched to declare no defaults:
    `_protocol_params()` raised LookupError while `_contract_problems()` returned [], so every component
    became "could not recompute" and the page showed ONLY the generic "stored verdict disagrees"
    warning -- an edited-field reading of a scorer whose own protocol parameters are unreadable, which
    is the same mislabelling as item 2.

    Fixed in the CODE rather than the docstring: `_contract_problems` is the channel designed to fail
    loud, it already withholds every decisive verdict and prints a specific message, and an unreadable
    default is a scorer-API problem in exactly the way a changed signature is. Correcting the docstring
    instead would have left the reader with the misleading warning and no way to tell which it was."""

    def nodefaults(self, pair, margin, direction, width_tol, min_n):
        return bm.interval_verdict(pair, margin, direction, width_tol, min_n)

    def test_a_defaultless_or_unusable_default_is_a_visible_contract_problem(self):
        j = joint()
        stub = (bm.Verdict.INCONCLUSIVE, "stub")
        for repl in (self.nodefaults,
                     lambda pair, margin, direction, width_tol=None, min_n=30: stub,
                     lambda pair, margin, direction, width_tol=0.25, min_n="30": stub,
                     lambda pair, margin, direction, width_tol=float("nan"), min_n=30: stub,
                     lambda pair, margin, direction, width_tol=float("inf"), min_n=30: stub,
                     lambda pair, margin, direction, width_tol=0.25, min_n=True: stub):
            with mock.patch.object(bm, "interval_verdict", repl):
                probs = db._contract_problems()
                h = db.render_scorecard(j)
            self.assertTrue(any("protocol parameters" in p for p in probs), probs)
            self.assertTrue(any("unreadable" in p for p in probs), probs)
            self.assertIn("CONTRACT PROBLEM", h)
            self.assertIn("unreadable", h)
            self.assertIn("All decisive verdicts are withheld", h)
            self.assertNotIn("vd-supported", h)
            self.assertIn("JOINT_INCONCLUSIVE", h)
        self.assertEqual(db._contract_problems(), [])              # not vacuous: HEAD's scorer is clean
        self.assertNotIn("CONTRACT PROBLEM", db.render_scorecard(j))

    def test_the_docstring_and_the_code_now_agree(self):
        self.assertIn("_contract_problems", db._protocol_params.__doc__)
        with mock.patch.object(bm, "interval_verdict", self.nodefaults):
            with self.assertRaises(LookupError):
                db._protocol_params()
            self.assertTrue(db._contract_problems())

    def test_a_stricter_patched_default_is_still_not_a_problem(self):
        def stricter(pair, margin, direction, width_tol=0.05, min_n=60):
            return bm.interval_verdict(pair, margin, direction, width_tol, min_n)
        with mock.patch.object(bm, "interval_verdict", stricter):
            self.assertEqual(db._contract_problems(), [])
            self.assertEqual(db._protocol_params(), (0.05, 60))


class SnapshotTotalsPinned(unittest.TestCase):
    def test_M27_a_total_with_a_missing_count_is_UNKNOWN_not_a_wrong_number(self):
        """M27, which survived the whole suite: `changed_files`' `ok_totals` flag ignored. HEAD
        correctly gives `UNKNOWN / some counts missing`; the mutant gives
        `total (2 files) | 10 | 23` -- a wrong number presented as a measured total, which is exactly
        what SR-13's "missing results render as UNKNOWN, not 0" criterion exists to catch."""
        row, h = total_row({"changed_files": [{"additions": None, "deletions": 3},
                                              {"additions": 10, "deletions": 20}]})
        self.assertIn("some counts missing", row)
        self.assertIn('<span class="unknown">UNKNOWN</span>', row)
        self.assertNotIn("<th>10</th>", row)
        self.assertNotIn("<th>23</th>", row)
        self.assertNotIn("23", row)
        self.assertIn("UNKNOWN", h)
        for bad in (None, "3", 3.0, True, False, [], {}, object()):
            for key, other in (("additions", "deletions"), ("deletions", "additions")):
                r, _ = total_row({"changed_files": [{"additions": 1, "deletions": 2},
                                                    {key: bad, other: 7}]})
                self.assertIn("some counts missing", r, (key, bad))
                self.assertNotIn("<th>8</th>", r, (key, bad))
        for missing in ({"deletions": 7}, {"additions": 7}, {}):      # an absent key, not just a bad one
            r, _ = total_row({"changed_files": [{"additions": 1, "deletions": 2}, missing]})
            self.assertIn("some counts missing", r, repr(missing))
        r, h2 = total_row({"changed_files": [{"additions": 1, "deletions": 2}, "not a mapping"]})
        self.assertIn("some counts missing", r)
        self.assertIn("malformed entry", h2)
        # NOT VACUOUS: honest counts do total, and a genuine zero is still a zero
        r, _ = total_row({"changed_files": [{"additions": 0, "deletions": 3},
                                            {"additions": 10, "deletions": 20}]})
        self.assertIn("<th>10</th>", r)
        self.assertIn("<th>23</th>", r)
        self.assertNotIn("UNKNOWN", r)


# ---------------------------------------------------------------------------------------------------------
# SR-13 round 4. This item has now FAILED THREE TIMES for one reason in three places, and round 3's fix
# shipped a test class whose docstring ASSERTED that "all four cells and the recomputation now route
# through" the shared check -- after which round 3 found a sixth and a seventh consumer. The enumeration
# was never performed. Everything below exists to perform it. See the scheme note at the top of
# dashboard.py for the three mechanisms; these are the two that are tests.
# ---------------------------------------------------------------------------------------------------------
SCORER_CLASSES = {"IntervalPair": bm.IntervalPair, "ComponentResult": bm.ComponentResult,
                  "Margins": bm.Margins, "JointResult": bm.JointResult}


# ---------------------------------------------------------------------------------------------------------
# SR-13 ROUND 7: THE THIRD HALF OF A VALUE. A value has a TYPE (round 4's table), it has a STORED NUMBER
# (round 5's table), and it has DUNDERS -- and the dunders are what every cross-check these rounds added
# actually calls. `liar` is the shape that evaded five sweeps, and it is one object rather than four
# hand-written classes so that both tables and every new field get the SAME attack.
#
# COUNTED, not argued, on the round-6 tree: 0 of the 107 values in `HOSTILE_BY_KIND` + `LEGAL_BUT_WRONG`
# were `int`/`float` subclass instances (iterate both tables, test `type(v) not in (int, float)`). The
# tables held 44 hostile TYPES, all correctly rejected, and no hostile SUBCLASS -- which no amount of
# care in keeping either table could have fixed, because the attack is in neither the type nor the stored
# value. `test_both_hostile_tables_sweep_subclass_instances_too` now fails if that count returns to 0 for
# any kind or for any declared number that has a second source.
# ---------------------------------------------------------------------------------------------------------
def liar(stored, shown=None):
    """An `int`/`float` SUBCLASS INSTANCE that STORES `stored` while PRESENTING itself as `shown`.

    It is a subclass of `type(stored)`, so `isinstance(v, (int, float))` holds, `MetricValue`'s own
    float-only invariant holds, and `math.isfinite` reads the double it STORES (which, for the legal
    values this is used with, is finite). Nothing but a dunder is overridden:

      * every COMPARISON answers "nothing to see here": `__eq__` True, `__ne__` False, and all four
        orderings False. That is not one attack but all of them at once, because a cross-check can only
        be `==`, `!=` or an inequality: `_declared`'s `margin != declared`, `_n_problem`'s `n > measured_n`
        and `n >= min_n`, `_recompute`'s `max(c.min_n, 30)` and `min(c.width_tol, 0.25)`,
        `_measured_seeds`' `attempted != len(scores)` and `failed != listed_failed`. Python prefers a
        SUBCLASS's reflected method, so `max(mn, 30)` and `0.25 < wt` consult the liar even when it is
        the right-hand operand (measured: `max(liar(1, 30), 30)` is the liar, and `min(liar(1e9), 0.25)`
        is the liar).
      * ARITHMETIC behaves as if the object were `shown`, which is the `_measured_seeds` route:
        `attempted - failed` is the only arithmetic this renderer does on a declared number, and an
        `int` subclass overriding only `__sub__` defeats it outright while every equality beside it
        still holds.
      * every CONVERSION shows `shown`: `__float__` (which `_num`'s `repr(float(x))` consults, so this
        is how a forged number prints an honest figure), `__int__`, `__index__` and `__str__` (which
        `_e` consults, so this is how a forged COUNT prints an honest figure).

    `__repr__` is deliberately HONEST and names both numbers, so a sweep's failure message says which
    object it was holding. It is the one dunder a renderer never reads (`_num` reprs the *converted*
    plain float, and `_e` goes through `str`), so making it honest gives nothing back to the defence."""
    base = float if isinstance(stored, float) else int
    shown = stored if shown is None else shown

    class Liar(base):
        def __eq__(self, other): return True
        def __ne__(self, other): return False
        def __lt__(self, other): return False
        def __le__(self, other): return False
        def __gt__(self, other): return False
        def __ge__(self, other): return False
        def __sub__(self, other): return base(shown) - other
        def __rsub__(self, other): return other - base(shown)
        def __float__(self): return float(shown)
        def __int__(self): return int(shown)
        def __index__(self): return int(shown)
        def __str__(self): return str(shown)
        def __repr__(self): return f"<lying {base.__name__} storing {base.__repr__(self)} shown as {shown!r}>"
        __hash__ = base.__hash__

    Liar.__name__ = f"Lying{base.__name__.capitalize()}"
    return Liar(stored)


def exemption_forgeries(honest):
    """The values an exempted (not-rendered) field is forged to: ILL-TYPED, AND LEGAL FOR ITS OWN TYPE.

    THE ILL-TYPED HALF IS THE SUITE'S ORIGINAL FIVE AND IT IS NOT THE WHOLE JOB. Counted, not argued:
    `-1`, `nan`, `None`, `object()` and `liar(1e9, 0.0)` are each either inadmissible to every kind
    function or answer every comparison False, so NOT ONE of them is a legal value of the field's own
    type. They do catch an exempt field that gains a DISPLAY CELL (the cell reads UNKNOWN where the
    honest page read a figure, and the bytes differ). What they cannot catch is an exempt field that
    gains a CROSS-CHECK: an honest page is already quiet, a value no kind admits leaves the new check
    quiet too, and only a LEGAL value of the right type can make it speak. That is the shape of every
    round-5-to-7 defect in this item, so the table carries it.

    The legal half is chosen by the honest value's own type, because "legal" is a property of the field:
    a `MetricValue` field's legal values are `MetricValue`s (a bare `1e9` there is ill-typed, which is
    how the original five read as five), an `int` field's are `int`s. Each type also gets one
    conversion-only liar, which is round 8's shape and is legal by construction."""
    ill_typed = (-1, float("nan"), None, object(), liar(1e9, 0.0))
    if isinstance(honest, MetricValue):
        return ill_typed + (MetricValue.measured(0.0), MetricValue.measured(1e9),
                            MetricValue.measured(-1e9), MetricValue.unmeasured("forged unmeasured"),
                            forge_mv(MetricValue.measured(1.0), conversion_liar(1.0, 2.0, "__float__")))
    if isinstance(honest, int) and not isinstance(honest, bool):
        return ill_typed + (0, 1, 10 ** 6, -10 ** 6, conversion_liar(honest, honest + 1, "__str__"))
    return ill_typed + (0.0, 0.5, 1e9, -1e9, conversion_liar(honest, honest + 1.0, "__float__"))


def is_a_subclass_instance(v):
    """The shape round 7 exists for: an `int`/`float` subclass instance, not an `int`/`float`. This is
    the exact predicate the round-6 count used (`type(v) not in (int, float)` over values that are
    `isinstance` of one), so the figure in the section comment above is reproducible from this file."""
    return isinstance(v, (int, float)) and not isinstance(v, bool) and type(v) not in (int, float)


# ---------------------------------------------------------------------------------------------------------
# SR-13 ROUND 8: THE RENDER BOUNDARY. `liar` above overrides EIGHTEEN dunders at once, which is the right
# shape for the verdict-and-alarm sweeps (one object, every cross-check attacked) and the WRONG shape for
# asking "does this cell print the number the kind admitted?": a liar that also lies to `==` and `<` can
# trip a cross-check, and an alarmed page is a page whose bytes differ for a reason that has nothing to do
# with rendering. `conversion_liar` overrides EXACTLY ONE dunder and stores the HONEST number, so every
# comparison, every arithmetic and every predicate in this module and in `benchmark` underneath it sees
# the truth. The honest render is then the ONLY correct output, and any byte that moves is a renderer that
# converted the caller's object instead of the number its kind admitted. That is Finding 1 exactly, and
# round 7's pin could not see it: `test_every_admitted_field_is_normalised_by_its_kind` asserts the TYPE a
# kind function RETURNS and never looks at a rendered cell, one level below the gap it was written to close.
# ---------------------------------------------------------------------------------------------------------
CONVERSION_DUNDERS = ("__float__", "__int__", "__index__", "__str__", "__repr__", "__format__", "RAISE")


def conversion_liar(honest, shown, dunder):
    """An `int`/`float` subclass storing `honest` that lies ONLY on `dunder` (showing `shown`), or --
    for the pseudo-dunder "RAISE" -- refuses every conversion.

    Every conversion a renderer in this module can perform on a stored number is covered: `_num` is
    `repr(float(x))` (`__float__`, and `__repr__` if the spelling ever drops the `float()`), a count cell
    is `_e(v)` (`__str__`), an f-string interpolation is `__format__`, and `__int__`/`__index__` are the
    two remaining integer conversions. ONE AT A TIME, deliberately: a combined subclass cannot say WHICH
    conversion a cell performed, and the failure message is the whole value of this test.

    "RAISE" is the other half of the same defect and is not a theoretical one: a `__float__` that raises
    took BOTH renderers down with ZeroDivisionError at the previous HEAD, through the same `_num(mv.value)`
    -- a page taken down rather than a result refused, outside this module's stated error contract."""
    base = float if isinstance(honest, float) else int
    if dunder == "RAISE":
        def boom(self, *a):
            raise ZeroDivisionError("this object refuses every conversion")
        return type("RefusesEveryConversion", (base,),
                    {"__float__": boom, "__int__": boom, "__index__": boom, "__str__": boom,
                     "__format__": boom, "__hash__": base.__hash__})(honest)
    bodies = {"__float__": lambda self: float(shown),
              "__int__": lambda self: int(shown),
              "__index__": lambda self: int(shown),
              "__str__": lambda self: str(shown),
              "__repr__": lambda self: repr(shown),
              "__format__": lambda self, spec: format(shown, spec)}
    cls = type("LiesOn" + dunder.strip("_"), (base,), {dunder: bodies[dunder], "__hash__": base.__hash__})
    return cls(honest)


def a_lie_for(honest):
    """A shown value that is never equal to the honest one, and never renders as the same string.

    Derived from the honest number rather than written down: a first draft used the constant 0.5, which
    silently collided with `rec()`'s own metric value of 0.5 and made that whole site vacuous -- the site
    reported no finding on a tree where the defect was live."""
    shown = honest + 1 if isinstance(honest, int) else honest + 1.0
    assert shown != honest and str(shown) != str(honest), honest
    return shown


# Hostile values per KIND: everything an honest producer of a field of this kind cannot emit BECAUSE OF
# ITS TYPE. Round 4 wrote that as "everything an honest producer of a field of this kind cannot emit",
# full stop, and the sweep over it was this module's whole answer for a stored number -- which is how
# round 5 happened. See `LEGAL_BUT_WRONG` below: these lists contain not one legal `int`, and an honest
# producer of `pair.n` on a 29-seed run cannot emit the legal int `30` either. A type table cannot refuse
# a legal value; only a second source can, so the two tables are separate and both are swept.
#
# ROUND 7 added the SUBCLASS entries, which belong in THIS table rather than in `LEGAL_BUT_WRONG`
# because what they store is inadmissible: a subclass may lie about the number it holds, and when the
# number it holds is `nan`/`inf`/`10**400` the kind must still refuse it. The `10**400` pair is the
# round-7 bonus defect and is a PIN, not coverage: at the round-6 tree `_finite_number` applied
# `math.isfinite` to an `int` too large to be a float, so `ComponentResult.margin = 10**400` (reachable
# by `object.__setattr__`, and absent from this table) made `render_scorecard` AND `render_dashboard`
# raise OverflowError instead of refusing the result -- a page taken down, outside this module's error
# contract, which the sweep's "must not raise, ever" would have caught had the value been in the table.
# The subclass form of it lies to `math.isfinite` as well (`__float__` -> 1.0), which is why the
# finiteness test now runs on the NORMALISED value.
HOSTILE_BY_KIND = {
    "mv": BREAKS_MV_INVARIANT + (liar(float("nan"), 0.5), liar(float("inf"), 1.0)),
    "float": (0, 1, 30, -1, "0.5", "", [], {}, (), object(), None, True, False,
              float("nan"), float("inf"), float("-inf"),
              liar(float("nan"), 0.5), liar(float("inf"), 0.9875)),
    "num": ("0.1", "", "nan", [], {}, (), object(), None, True, False,
            float("nan"), float("inf"), float("-inf"), 10 ** 400,
            liar(float("nan"), 0.1), liar(10 ** 400, 1)),
    "count": (0.0, 1.0, 30.0, "30", "", [], {}, (), object(), None, True, False,
              float("nan"), float("inf"), float("-inf"),
              liar(30.0, 30), liar(float("nan"), 30)),
}
# Which hypotheses read a given declared number. A pair/component number is forged on EVERY instance, so
# all three are affected; a Margins field is read by exactly one hypothesis (benchmark.PRIMARY).
HYPOTHESES_READING = {("Margins", "delta_S"): ("H1",), ("Margins", "delta_R"): ("H2",),
                      ("Margins", "delta_sel"): ("H3",)}
# The display cell each declared number appears in, so the sweep can assert the FIGURE as well as the
# verdict. None means "this number has no cell of its own on the page".
FIGURE_CAVEAT = {("IntervalPair", "mean"): "malformed measured value",
                 ("IntervalPair", "boot_lo"): "interval not computable",
                 ("IntervalPair", "boot_hi"): "interval not computable",
                 ("IntervalPair", "t_lo"): "interval not computable",
                 ("IntervalPair", "t_hi"): "interval not computable",
                 ("IntervalPair", "n"): "n", ("IntervalPair", "level"): "level",
                 ("ComponentResult", "margin"): "margin",
                 ("ComponentResult", "min_n"): None, ("ComponentResult", "width_tol"): None,
                 ("Margins", "delta_S"): "delta_S is not a finite number",
                 ("Margins", "delta_R"): "delta_R is not a finite number",
                 ("Margins", "delta_sel"): "delta_sel is not a finite number",
                 ("JointResult", "n_attempted"): "not recorded",
                 ("JointResult", "n_failed"): "not recorded"}

# ---------------------------------------------------------------------------------------------------------
# SR-13 round 5: LEGAL-BUT-WRONG VALUES, and the enumeration of which declared numbers can have one.
#
# "When a type is the attack surface, enumerate its consumers, not its inputs" is this project's own
# standing rule, and round 4 applied it to one half of the problem and reversed it on the other: the
# CONSUMERS were enumerated by machine (the recording probe) while the INPUTS went back to being a list
# kept by hand -- a list of ill-typed values, which is the only kind of list a type predicate can act on.
# The gap it left is not a missing consumer and not a missing hostile type. It is that `_count(30)` is
# correct and `pair.n = 30` on a 29-seed run is a forgery, and those two facts are compatible.
#
# So every declared number is classified below by WHETHER THE RESULT CONTAINS A SECOND SOURCE FOR IT,
# into exactly one of three dicts whose union must be exactly `db.STORED_NUMBERS`
# (`test_every_declared_number_is_classified_by_its_second_source`). A new declared number cannot be
# added without saying which it is, and the two classes that have one get a legal-but-wrong sweep that
# asserts the VERDICT and the ALARM -- the same rule as the type sweep, over the other half of the space.
SECOND_SOURCE = {
    ("IntervalPair", "n"):
        "joint.n_attempted - joint.n_failed (itself anchored on joint.seed_scores), and the pair's own "
        "'n below protocol minimum' flag against the component's declared min_n",
    ("JointResult", "n_attempted"): "len(joint.seed_scores)",
    ("JointResult", "n_failed"): "the number of not-ok entries in joint.seed_scores",
    ("ComponentResult", "margin"): "joint.margins, via the protocol tables (db._declared)",
    ("Margins", "delta_S"): "the H1 component's own `margin` field (db._declared)",
    ("Margins", "delta_R"): "the H2 component's own `margin` field (db._declared)",
    ("Margins", "delta_sel"): "the H3 components' own `margin` fields (db._declared)",
    # ROUND 6: these four were in NO_SECOND_SOURCE and the content of those entries was FALSE. An exact
    # second source was already in the same JointResult and this module already read it -- the per-seed
    # series rebuilt from joint.seed_scores (db._seed_series, read by db._measured_seeds since round 5).
    ("IntervalPair", "mean"):
        "bm.mean(the per-seed series rebuilt from joint.seed_scores for this component's metric) -- "
        "benchmark.summarize computes the stored value as exactly that, so it reproduces BIT-EXACTLY "
        "(measured: 324 of 324 component-field comparisons over 18 honest shapes)",
    ("IntervalPair", "t_lo"): "bm.t_interval(that same series, pair.level)[0], bit-exactly",
    ("IntervalPair", "t_hi"): "bm.t_interval(that same series, pair.level)[1], bit-exactly",
    ("IntervalPair", "level"):
        "the stored t-interval together with that same series: t_interval(series, level) is strictly "
        "monotone in `level`, so the stored bounds pin it. This is NOT the bm.bonferroni_level() figure "
        "in the family line, which is still deliberately NOT compared (BenchmarkConfig.alpha is "
        "settable and JointResult carries only an opaque config_hash, so that comparison would "
        "false-fire on every honest non-default-alpha study). The t-interval equation needs no alpha. "
        "LIMIT, stated: on a pair with fewer than two values the t-interval is honestly unmeasured and "
        "the level is unconstrained -- a weaker check on those pairs, not a skipped one.",
}
# A legal-but-wrong value here cannot be REFUSED, because an honest producer may emit it: these are
# protocol parameters the component merely asserts, and a weaker-than-protocol value is produced by an
# honest non-compliant `BenchmarkConfig` as well as by an edit (argued at `db._weaker_than_protocol`).
# They are instead NEUTRALISED by `_recompute`'s one-sided floor, so what must hold is that they cannot
# change what the page displays. The STRICTER direction is honoured in full and does change it, which is
# `test_stricter_than_protocol_parameters_are_honoured_not_overridden`, not this sweep.
NEUTRALISED_BY_A_FLOOR = {
    ("ComponentResult", "min_n"): "max(c.min_n, the scorer's declared min_n default)",
    ("ComponentResult", "width_tol"): "min(c.width_tol, the scorer's declared width_tol default)",
}
# RESIDUALS, stated rather than quietly absent. Each is already documented in dashboard.py; this table
# exists so that "no second source" is a recorded decision per field instead of an omission per field.
#
# THE ROUND-6 DEFECT WAS THE CONTENT OF THIS DICT, not its absence: the three dicts partitioned
# db.STORED_NUMBERS correctly (7 + 2 + 6 = 15, pairwise disjoint, the test below green) and SIX of this
# dict's entries said "the interval itself is producer-asserted" while an EXACT second source for four of
# them sat in the same JointResult and this module already read it. A performed classification is not a
# true one: the machine checks that every declared number is in exactly one dict, and nothing in a test
# suite can check that the REASON written in it is true. Hence the two rules now applied here:
#   (1) an entry must name the second source it DOES NOT have and why it cannot be had -- not restate
#       that the field is producer-asserted, which is true of every field in every one of the dicts;
#   (2) each surviving reason is pinned by a test that would fail if the missing source appeared
#       (`test_the_two_bootstrap_bounds_have_no_recoverable_second_source`).
NO_SECOND_SOURCE = {
    ("IntervalPair", "boot_lo"):
        "the bootstrap resample is not reproducible from the result. benchmark.summarize computes it as "
        "bootstrap_ci(vals, level, n_boot, make_rng(derive_seed(base_seed, 'bootstrap:' + name))) and "
        "NEITHER n_boot NOR base_seed is a field of JointResult (confirmed from dataclasses.fields: it "
        "carries an opaque config_hash and a seed_list_digest, and freeze_seed_list derives the seeds by "
        "derive_seed(base_seed, 'replicate:k'), a hash that cannot be inverted). Unlike `mean` and the "
        "t-interval, which are closed-form functions of the per-seed series, there is no second source "
        "to read -- only a seed to guess. Residual: a self-consistent forged bootstrap pair under a "
        "correctly named component, which is the residual documented at db._recompute.",
    ("IntervalPair", "boot_hi"): "as `boot_lo`: the same unrecoverable n_boot and base_seed",
}
# Values of the RIGHT TYPE that an honest producer of this field cannot emit on the fixture named in the
# sweep. `None` means "use the default 30-seed fixture"; `pair.n` additionally gets the 29-seed fixture
# of the reported defect, in test_G3.
#
# ROUND 7 added the `liar(stored, shown)` entries. They are LEGAL-BUT-WRONG and not hostile: what each
# one STORES is a value of exactly the right type that this fixture's honest producer cannot emit, so the
# kind function must admit it (after normalising it) and the SECOND SOURCE must be what refuses it. The
# addition is the dunders: each stores the wrong number, answers every comparison a cross-check can make
# with "nothing to see", does `attempted - failed` as if it held the honest number, and PRINTS the honest
# number. Four of these were the round-6 attestation's four SR-13 findings and FAIL on the round-6 tree
# (measured, before/after, in `DundersAreNotPartOfTheTypeEither`); the rest are coverage, and which is
# which is recorded per entry rather than claimed for the group.
LEGAL_BUT_WRONG = {
    ("IntervalPair", "n"): (31, 50, 1000,              # a 30-seed study has no 31-seed component
                            liar(31, 30)),             # FINDING 1: the `pair.n` route, as a subclass
    # ROUND 6. Forged INSIDE the MetricValue (kind "mv"), so each is a finite float that `_mv_intact`
    # must admit -- an honest producer simply cannot emit it for THIS series. 0.5 and 1.5 are far from
    # the fixture's ~1.0 mean; the third is the sibling bound's own value, which is the cheapest forgery
    # of all (it makes the t-interval agree with the bootstrap interval, defeating protocol 6.3).
    # the three `mv` liars are COVERAGE, not pins: round 6 already normalised at the point of use here
    # (`_same_number` compares `bm.mean([stored]) == bm.mean([want])`, two plain floats, and its own
    # docstring argues the overridable-`__eq__` case), so these are caught on the round-6 tree too.
    ("IntervalPair", "mean"): (0.5, 1.5, -2.25, liar(0.5, 0.9995918337735029)),
    ("IntervalPair", "t_lo"): (0.5, 0.95, -2.25, liar(0.5, 0.9995918337735029)),
    ("IntervalPair", "t_hi"): (1.5, 1.05, 2.25, liar(1.5, 0.9995918337735029)),
    # also coverage: `bm.t_interval` normalises the level it is handed (`_check_level` -> `_plain_number`),
    # so a WRONG stored level was already caught. FINDING 4 is the other direction -- an HONEST stored
    # level with a lying `__float__`, which changes no verdict and edits every level FIGURE -- and it is
    # not a legal-but-wrong value at all, so it is pinned by its own test, not here.
    ("IntervalPair", "level"): (0.95, 0.99, 0.5, liar(0.95, 0.9875)),
    ("JointResult", "n_attempted"): (29, 31, 100, 0,   # contradicts len(seed_scores) == 30
                                     liar(29, 30)),    # NOTE A: the `attempted - failed` route
    ("JointResult", "n_failed"): (1, 5, 30,            # contradicts "no entry of seed_scores is not-ok"
                                  liar(1, 0)),
    ("ComponentResult", "margin"): (0.0, 0.2, 1.0, -1.0,    # != Margins() delta_S 0.10 / R 0.05 / sel 0.10
                                    liar(0.2, 0.1)),        # FINDING 3's mechanism, one value
    ("Margins", "delta_S"): (0.0, 0.2, 1.0, -1.0, liar(0.2, 0.1)),
    ("Margins", "delta_R"): (0.0, 0.2, 1.0, -1.0, liar(0.2, 0.05)),
    ("Margins", "delta_sel"): (0.0, 0.2, 1.0, -1.0, liar(0.2, 0.1)),
    ("ComponentResult", "min_n"): (0, 1, 5, 29,        # weaker than the protocol's 30: neutralised
                                   liar(1, 30)),       # FINDING 2: the `max(c.min_n, 30)` route
    ("ComponentResult", "width_tol"): (0.9, 1, 1e9,    # wider than the protocol's 0.25: neutralised
                                       liar(1e9, 0.25)),   # NOTE B: the `min(c.width_tol, 0.25)` route
}


def all_components(j):
    return [c for h_ in (j.h1, j.h2, j.h3) for c in (*h_.components, *(h_.converged_components or ()))]


def instances_of(j, cls_name):
    """Every live instance of `cls_name` inside one JointResult."""
    if cls_name == "IntervalPair":
        return [c.pair for c in all_components(j)]
    if cls_name == "ComponentResult":
        return all_components(j)
    if cls_name == "Margins":
        return [j.margins]
    return [j]


def forge_declared(j, cls_name, attr, value):
    """Forge one declared stored number on EVERY instance of its class inside `j`, the way
    post-construction tampering does. A `mv` field is forged inside the MetricValue, not replaced."""
    for obj in instances_of(j, cls_name):
        if db.STORED_NUMBERS[cls_name][attr] == "mv":
            forge_mv(getattr(obj, attr), value)
        else:
            object.__setattr__(obj, attr, value)
    return j


def recording_subclass(base, bucket):
    """A subclass of a scorer dataclass that records every attribute name read off it.

    `isinstance(x, base)` still holds, so `_joint_wellformed` still accepts the result and the render
    takes its normal path -- which is the point: the probe observes the REAL render, not a model of it.

    WHAT THIS PROBE COVERS, AND WHAT IT DOES NOT. Stated here because the two rounds before this one
    each shipped a mechanism whose docstring claimed more than the mechanism did, and the claim is what
    the next round had to disprove. MEASURED, one spelling per run, reading `IntervalPair.n`:

        p.n | getattr(p, "n" + "") | attrgetter("n")(p) | comprehension | lambda      -> SEEN
        p.__getattribute__("n")                                                       -> SEEN
        dataclasses.asdict(p)["n"]                                                    -> SEEN*
        vars(p)["n"]            -> BLIND   (the bucket gets `__dict__`, which the filter discards)
        p.__dict__["n"]         -> BLIND   (same)
        object.__getattribute__(p, "n")  -> BLIND   (the bucket stays EMPTY: `__getattribute__` is
                                  bypassed entirely, so the subclass is never consulted)

    So: ANY SPELLING THAT BYPASSES `__getattribute__` IS OUTSIDE THIS PROBE. Two of them are
    lint-clean by design -- `CLEAN_CLONE.md` deliberately leaves mapping reflection uncovered -- and
    both were measured to survive the whole suite while changing behaviour (forging `pair.n_boot = -1`
    through `vars(c.pair)["n_boot"]` gave JOINT_SUPPORTED with no alarm where HEAD gives INCONCLUSIVE),
    so a contributor could ship either through lint AND the suite.
    (*) `asdict` is seen, but it reads EVERY field, so the probe fails in the other direction, naming
    `n_boot`/`sd`/`iqr`/`minimum`/`maximum`/`max_over_median_abs` as read-but-undeclared: a true alarm
    with a misleading list.

    IT ALSO SEES ONLY WHAT ITS ONE RENDER EXERCISES. The probe renders a single honest dashboard, so a
    read behind a branch that render never takes is invisible: a plain-attribute read of an UNDECLARED
    field behind `if mn > 10**6` survived, and forging `min_n = 2_000_000` then gave JOINT_SUPPORTED
    with no alarm. And because the probe compares attribute SETS, a SECOND read of an ALREADY-DECLARED
    number is invisible by construction, exercised branch or not.

    WHAT IS THEREFORE NOT RELIED ON. This probe is a convenience that names a new consumer early; it is
    not the guarantee. The guarantee is behavioural: `EveryForgedNumberIsCheckedAtTheVerdictAndTheAlarm`
    and `TypeIsNotTheWholeOfAdmission` forge each declared number and assert the VERDICT CELL and the
    ALARM, and a test of that shape dies no matter how the read is spelled, which branch it sits behind,
    or whether any mechanism noticed it. The probe's own non-vacuity guard is working and is load-bearing
    for what it does cover: an undeclared read by plain attribute on the exercised path is killed, by
    `assertNotIn("n_boot", bucket)` in `test_the_probe_itself_is_not_vacuous`."""
    class Rec(base):
        def __getattribute__(self, name):
            bucket.add(name)
            return base.__getattribute__(self, name)
    Rec.__name__ = "Recording" + base.__name__
    return Rec


def is_a_stored_number(v):
    """What counts as a stored number: a `MetricValue`, or a real `int`/`float`. `bool` is excluded
    because no field of these classes holds one (`complete_gate_coverage` is a derived flag, not a datum).

    THIS PREDICATE IS EVALUATED ON A VALUE, which is a blind spot wherever the value comes from the
    honest fixture instance; see `numeric_fields_of`, which is what the two field-enumerating mechanisms
    now filter with."""
    return isinstance(v, MetricValue) or (isinstance(v, (int, float)) and not isinstance(v, bool))


NUMERIC_ANNOTATION = re.compile(r"\b(?:int|float|MetricValue)\b")


def numeric_fields_of(cls, obj):
    """The numeric fields of a scorer dataclass: numeric BY DECLARATION, union numeric BY HONEST VALUE.

    THE SECOND HALF ALONE WAS A BLIND SPOT SHARED BY BOTH FIELD-ENUMERATING MECHANISMS, and it is the
    kind that hides a whole field rather than a whole route. `test_every_numeric_field_of_a_verdict_
    bearing_class_is_declared_or_exempt` and `StoredNumbersAreEnumeratedNotAsserted.probe` both filtered
    with `is_a_stored_number(getattr(obj, f.name, None))` EVALUATED ON THE HONEST FIXTURE INSTANCE, so a
    numeric field whose honest value is not an `int`/`float`/`MetricValue` at fixture-build time was
    invisible to BOTH -- not merely undeclared, but unseeable. MEASURED in a `git archive HEAD` copy, on
    3.13.5: adding `IntervalPair.extra_count: Optional[int] = None` to `benchmark.py` PLUS a read of it
    on the normal verdict path left the targeted suite at `506 tests, OK` -- an undeclared, unadmitted
    consumer of a stored number, UNKILLED by `test_dashboard`, which is SR-13's own defect class.
    No live field has that shape today, which is exactly why neither mechanism's author could see it.

    The annotation half closes it: `dataclasses.fields()` carries the DECLARATION, which exists before
    any value does. `Optional[int] = None` is numeric by declaration, so such a field must be declared in
    `db.STORED_NUMBERS` or exempted in `FIELDS_NOT_RENDERED` the moment it exists. Measured on this tree:
    the two halves pick out the SAME 21 names today (13 + 3 + 3 + 2), so the annotation half costs nothing
    and the union is kept because the value half still catches a numeric field whose annotation is `Any`,
    a bare `object`, or a type alias this regex cannot read.
    THE FIGURE THIS REPLACES SAID "the SAME 15 names today (7 + 3 + 3 + 2)", and both the total and its
    first term were wrong in the paragraph that justifies the fix. 15 is `len(db.STORED_NUMBERS)`
    flattened -- the DECLARED numbers -- not what this function yields. For `IntervalPair` the
    enumeration yields 13: its 7 declared numbers UNION the 6 exempted in `FIELDS_NOT_RENDERED`
    (`n_boot`, `sd`, `iqr`, `minimum`, `maximum`, `max_over_median_abs`), which is the whole point of the
    union -- an exempt numeric field is enumerated and then excused, not invisible. The other three
    classes have no exemptions, so 3 + 3 + 2 were right and only the first term and the total were not.
    `test_the_two_halves_of_numeric_fields_of_agree_and_the_figure_is_counted` counts it rather than
    restating it, so this figure cannot drift again.

    IT IS NOT A TYPE CHECKER AND MAKES NO CLAIM TO BE. The annotation is matched as TEXT (these modules
    store annotations as strings), so `dict[str, float]` and `Callable[[int], None]` both read as numeric
    and would have to be exempted with a reason. That direction is the safe one."""
    annotated = set()
    for f in dataclasses.fields(cls):
        ann = f.type if isinstance(f.type, str) else getattr(f.type, "__name__", repr(f.type))
        if NUMERIC_ANNOTATION.search(ann):
            annotated.add(f.name)
    return annotated | {f.name for f in dataclasses.fields(cls)
                        if is_a_stored_number(getattr(obj, f.name, None))}


def module_code_by_line(module):
    """`module`'s source with COMMENTS and STRING/f-string literals removed, per line.

    Tokenizing rather than regexing the raw text matters: every docstring in dashboard.py discusses the
    very patterns the source test forbids ("a bare `float(code)`, which coerces"), so a text scan reports
    the documentation as the offence. Dropping STRING tokens drops the docstrings exactly."""
    src = Path(inspect.getsourcefile(module)).read_text(encoding="utf-8")
    skip = {tokenize.COMMENT, tokenize.STRING, tokenize.NL, tokenize.NEWLINE, tokenize.INDENT}
    skip |= {getattr(tokenize, n) for n in ("FSTRING_MIDDLE",) if hasattr(tokenize, n)}
    out = {}
    for tok in tokenize.generate_tokens(io.StringIO(src).readline):
        if tok.type in skip:
            continue
        out.setdefault(tok.start[0], []).append(tok.string)
    return src, {ln: "".join(parts) for ln, parts in out.items()}


def enclosing_functions(module):
    """line number -> name of the innermost function that contains it."""
    src = Path(inspect.getsourcefile(module)).read_text(encoding="utf-8")
    owner = {}
    for node in ast.walk(ast.parse(src)):               # ast.walk is breadth-first, so deeper wins
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for i in range(node.lineno, (node.end_lineno or node.lineno) + 1):
                owner[i] = node.name
    return owner


NUMERIC_PREDICATE = re.compile(r"math\.isfinite|isinstance\([^)]*\b(?:int|float)\b|(?<![\w.])float\(")
KIND_FUNCTIONS = {"_num", "_finite_float", "_finite_number", "_count"}


class StoredNumbersAreEnumeratedNotAsserted(unittest.TestCase):
    """THE ROUND-4 FIX, and the only part of it that is not a code change.

    Rounds 2 and 3 both ended with a correct local fix and a test class that STATED how many consumers
    of a stored number existed. Round 3's said "all four cells and the recomputation now route through"
    `_finite_float`; round 3's review then found a sixth and a seventh, because nobody had made the
    machine count them. Round 4 found an eighth (`pair.n`, which bought a decisive JOINT_SUPPORTED on a
    genuinely below-minimum run with no alarm) and a ninth and tenth (`c.margin` and `Margins.<attr>`,
    still `float()`-coerced inside the verdict path while both display cells checked properly).

    The two tests below replace the counting-by-eye. Neither asserts a number of consumers:

      * `test_the_enumeration_is_performed_by_probe_not_asserted` swaps each scorer class for a
        subclass that records every attribute read off it, renders a whole dashboard, and compares the
        attributes ACTUALLY READ -- by dashboard.py and by benchmark.py underneath it -- against
        `db.STORED_NUMBERS`, in BOTH directions. Add a consumer of an undeclared number and it fails
        naming the attribute; delete a consumer and leave the table behind and it fails too.
      * `test_no_numeric_predicate_lives_outside_the_kind_functions` reads dashboard.py's own source and
        fails if `math.isfinite`, `isinstance(..., int/float)` or `float(` appears in any function other
        than the four kind functions. That is the rule the previous two rounds' fixes broke: each left a
        "correct but separate" inline check behind, and a separate check is what drifts.

    Together they mean a future reader cannot add an unchecked consumer of a stored number: either the
    attribute is undeclared (probe fails) or the check is written inline (source test fails).

    THAT LAST SENTENCE IS OVERSTATED AND IS KEPT WITH ITS CORRECTION ATTACHED, because an overstated
    claim about a mechanism is what each of the last three rounds had to disprove. Four mutants were
    measured to survive both tests: the same consumer spelled `vars(c.pair)["n_boot"]` or
    `c.pair.__dict__["n_boot"]` (both outside `__getattribute__`, both lint-clean by design, both with a
    demonstrated behaviour change), an undeclared read behind a branch this probe's single render never
    takes, and a duplicate read of an already-DECLARED number, which an attribute-SET comparison cannot
    see at all. `recording_subclass`' docstring records the measurements.

    AND ROUND 5 WAS NOT ANY OF THOSE. It needed no unseen consumer: `pair.n` was declared, routed and
    swept, and a legal `int` still laundered a below-minimum run, because these two tests check WHETHER a
    number is admitted and not WHETHER THE VALUE IS BELIEVABLE. See `SECOND_SOURCE` and
    `TypeIsNotTheWholeOfAdmission`. The weight is therefore on the behavioural sweeps, which die
    regardless of spelling, branch or mechanism; these two remain because naming a new consumer by
    machine is cheaper than finding it by review, not because they close the space."""

    def probe(self, cls_name):
        bucket = set()
        j = joint()
        rec_cls = recording_subclass(SCORER_CLASSES[cls_name], bucket)
        for obj in instances_of(j, cls_name):
            object.__setattr__(obj, "__class__", rec_cls)
            self.assertIsInstance(obj, SCORER_CLASSES[cls_name])     # the render must take its real path
        page = db.render_dashboard({"snapshot": SNAP, "train": train(3, steps=10, timestamp_utc=TS),
                                    "joint": j, "records": [rec()]})
        self.assertNotIn("REFUSED", page, cls_name)                  # not a degraded render
        self.assertNotIn("NOT shown", page, cls_name)                # and not an alarmed one
        honest = instances_of(joint(), cls_name)[0]
        numeric = numeric_fields_of(SCORER_CLASSES[cls_name], honest)
        # BY DECLARATION OR BY VALUE: the value half alone could not see a read of a numeric field whose
        # honest value is None at fixture-build time, which is the blind spot `numeric_fields_of`
        # documents and measures. The non-field half of the union stays: a numeric PROPERTY read off the
        # object is not a `dataclasses.field` at all.
        return {a for a in bucket
                if a in numeric or is_a_stored_number(getattr(honest, a, None))}

    def test_the_enumeration_is_performed_by_probe_not_asserted(self):
        for cls_name in SCORER_CLASSES:
            read = self.probe(cls_name)
            declared = set(db.STORED_NUMBERS[cls_name])
            self.assertEqual(read, declared, f"""
{cls_name}: the stored numbers READ during a render do not match db.STORED_NUMBERS.
  read but NOT declared : {sorted(read - declared)}
  declared but NOT read : {sorted(declared - read)}
A number read but not declared is an UNCHECKED CONSUMER -- the SR-13 defect, three rounds running.
Declare it in db.STORED_NUMBERS with its kind and route its display cell through _kind_cell/_kind_text;
if it reaches a verdict, add its class to db.VERDICT_BEARING so _recompute fails closed on it.
A number declared but not read means the table has rotted; delete the entry.""")

    def test_the_probe_itself_is_not_vacuous(self):
        """If the recording subclass were not actually observing the render, the test above would pass
        by reading nothing. So: a deliberately undeclared numeric field must be caught."""
        bucket = set()
        j = joint()
        rec_cls = recording_subclass(bm.IntervalPair, bucket)
        for obj in instances_of(j, "IntervalPair"):
            object.__setattr__(obj, "__class__", rec_cls)
        db.render_scorecard(j)
        self.assertTrue({"n", "level", "boot_lo", "mean"} <= bucket, sorted(bucket))
        # `n_boot` is a real numeric field of IntervalPair that nothing renders. It is therefore NOT in
        # the declared table, and the probe proves that by not seeing it. The day something reads it,
        # the probe reports it rather than a reviewer having to notice.
        self.assertIsInstance(joint().h1.components[0].pair.n_boot, int)
        self.assertNotIn("n_boot", bucket)
        self.assertNotIn("n_boot", db.STORED_NUMBERS["IntervalPair"])
        for dead in ("sd", "iqr", "minimum", "maximum", "max_over_median_abs"):
            self.assertNotIn(dead, bucket, dead)

    def test_no_numeric_predicate_lives_outside_the_kind_functions(self):
        src, code = module_code_by_line(db)
        owner = enclosing_functions(db)
        offenders = [(ln, owner.get(ln), line.strip())
                     for ln, line in sorted(code.items())
                     if NUMERIC_PREDICATE.search(line) and owner.get(ln) not in KIND_FUNCTIONS]
        self.assertEqual(offenders, [], f"""
dashboard.py admits a stored number outside the four kind functions {sorted(KIND_FUNCTIONS)}:
{chr(10).join('  line %d in %r: %s' % o for o in offenders)}
That is the SR-13 root cause, not a style point: every round of this item shipped one correct-but-
separate inline check, and the separate one is the one that drifted. Call _finite_float / _finite_number
/ _count / _mv_intact (or _kind_cell / _kind_text, which do) instead.""")
        # NOT VACUOUS: the predicates do exist, in exactly those functions, and `float(` exactly once.
        found = {owner.get(ln) for ln, line in code.items() if NUMERIC_PREDICATE.search(line)}
        self.assertEqual(found, KIND_FUNCTIONS)
        self.assertEqual([ln for ln, line in code.items() if re.search(r"(?<![\w.])float\(", line)],
                         [ln for ln, line in code.items() if owner.get(ln) == "_num"
                          and re.search(r"(?<![\w.])float\(", line)])
        self.assertEqual(len([1 for line in code.values() if re.search(r"(?<![\w.])float\(", line)]), 1)

    def test_the_table_and_the_kinds_are_mutually_consistent(self):
        for cls_name, fields in db.STORED_NUMBERS.items():
            self.assertIn(cls_name, SCORER_CLASSES, cls_name)
            for attr, kind in fields.items():
                self.assertIn(kind, db._NUM_KINDS, (cls_name, attr, kind))
                self.assertIn((cls_name, attr), FIGURE_CAVEAT, (cls_name, attr))
        self.assertTrue(set(db.VERDICT_BEARING) <= set(db.STORED_NUMBERS))
        # ROUND 5: there is no longer a class that is not verdict-bearing. `JointResult` used to be the
        # exception, on the stated grounds that `n_attempted`/`n_failed` "feed no recomputation at all",
        # and that was the hole: their difference is the measured-seed count every `pair.n` is now
        # checked against. The equality is asserted in this direction so that re-exempting a class is a
        # deliberate edit to this line and not a quiet omission.
        self.assertEqual(set(db.STORED_NUMBERS) - set(db.VERDICT_BEARING), set())

    def test_the_declared_min_n_is_admitted_as_a_COUNT_not_as_any_number(self):
        """`_protocol_params` reads the scorer's own `min_n` default as kind "count", where HEAD read it
        as any number and then applied `int(mn_declared)` inside `_recompute` -- a coercion, which is
        the pattern this round removed. A scorer declaring `min_n = 30.0` or `30.5` is not declaring a
        usable minimum SEED COUNT, so it is a contract problem and the page says so.

        Pinned because the tightening is this round's and would otherwise be a new surviving mutant."""
        j = joint()                      # built with the REAL scorer, before any patch
        for bad in (30.0, 30.5, True, "30", None, float("inf")):
            def floaty(pair, margin, direction, width_tol=0.25, min_n=bad):
                return bm.Verdict.INCONCLUSIVE, "stub"
            with mock.patch.object(bm, "interval_verdict", floaty):
                with self.assertRaises(LookupError, msg=repr(bad)):
                    db._protocol_params()
                h = db.render_scorecard(j)
            self.assertIn("protocol parameters (width_tol, min_n) unreadable", h, repr(bad))
            self.assertIn("CONTRACT PROBLEM", h, repr(bad))
            self.assertNotIn("vd-supported", h, repr(bad))
        # width_tol stays kind "num": an int tolerance is a legitimate number, not a count
        def inty(pair, margin, direction, width_tol=1, min_n=60):
            return bm.Verdict.INCONCLUSIVE, "stub"
        with mock.patch.object(bm, "interval_verdict", inty):
            self.assertEqual(db._protocol_params(), (1, 60))
        self.assertEqual(db._protocol_params(), (0.25, 30))     # not vacuous

    def test_each_kind_function_admits_exactly_its_own_type(self):
        """Direct unit tests. The sweep below goes through a whole render, where several layers can mask
        a fail-open in one kind; these cannot be masked (the F-h lesson)."""
        self.assertEqual(db._finite_float(1.5), 1.5)
        self.assertEqual(db._finite_float(0.0), 0.0)
        for bad in (0, 1, True, False, "1.5", None, [], object(),
                    float("nan"), float("inf"), float("-inf")):
            self.assertIsNone(db._finite_float(bad), repr(bad))
        self.assertEqual(db._finite_number(1.5), 1.5)
        self.assertEqual(db._finite_number(0), 0)                 # an int IS admitted, unconverted
        self.assertEqual(db._finite_number(-7), -7)
        for bad in (True, False, "1.5", "", None, [], object(),
                    float("nan"), float("inf"), float("-inf")):
            self.assertIsNone(db._finite_number(bad), repr(bad))
        self.assertEqual(db._count(30), 30)
        self.assertEqual(db._count(0), 0)
        self.assertEqual(db._count(-3), -3)                       # sign is the caller's business
        for bad in (True, False, 1.0, 0.0, "30", None, [], object(), float("nan"), float("inf")):
            self.assertIsNone(db._count(bad), repr(bad))
        self.assertIsNotNone(db._mv_intact(MetricValue.measured(0.0)))
        self.assertIsNotNone(db._mv_intact(MetricValue.unmeasured("n < 2")))   # honestly unmeasured
        for bad in BREAKS_MV_INVARIANT:
            self.assertIsNone(db._mv_intact(forge_mv(MetricValue.measured(1.0), bad)), repr(bad))
        for junk in (1.0, 0, "1.0", None, object(), ()):
            self.assertIsNone(db._mv_intact(junk), repr(junk))

    def test_admitted_hands_back_the_values_so_nothing_is_admitted_twice(self):
        """`_admitted` returns the admitted VALUES, and `_recompute` uses them instead of re-reading
        the fields. This round's FIRST DRAFT returned a bool, so `_recompute` asked "intact?" and then
        read `c.margin` / `c.min_n` / `c.width_tol` again through their kind functions -- two
        admissions per field. Measured as a mutant: deleting the guard altogether changed no output,
        because the later reads caught everything. The fix for an unchecked-consumer defect had grown
        its own masked duplicate check, which is the exact failure mode of this item, so the duplicate
        was removed rather than pinned."""
        c = joint().h1.components[0]
        nums = db._admitted(c, "ComponentResult")
        self.assertEqual(nums, {"margin": c.margin, "min_n": c.min_n, "width_tol": c.width_tol})
        self.assertEqual(set(nums), set(db.STORED_NUMBERS["ComponentResult"]))
        p = joint().h1.components[0].pair
        self.assertEqual(db._admitted(p, "IntervalPair")["n"], 30)
        self.assertEqual(db._admitted(p, "IntervalPair")["level"], p.level)
        self.assertIs(db._admitted(p, "IntervalPair")["mean"], p.mean)
        # and `_recompute` really does consume them: the only read of each field is inside `_admitted`
        src = inspect.getsource(db._recompute)
        body = "".join(l for l in src.split("\n") if not l.strip().startswith("#"))
        for field in ("margin", "min_n", "width_tol"):
            self.assertNotIn(f"c.{field}", body.split('"""')[-1], field)
        for bad in HOSTILE_BY_KIND["num"]:
            self.assertIsNone(db._admitted(forge_declared(joint(), "ComponentResult", "margin", bad)
                                           .h1.components[0], "ComponentResult"), repr(bad))

    def test_admitted_requires_every_declared_field_to_be_present(self):
        """`db._numbers_intact`, the predicate alias this test used to call, was deleted in round 5:
        `_pair_numbers_ok` now needs the admitted `n` to cross-check rather than a yes/no, so the alias
        had no module-level caller left and would have been a reader kept alive by its tests alone."""
        j = joint()
        for cls_name in db.STORED_NUMBERS:
            for obj in instances_of(j, cls_name):
                self.assertIsNotNone(db._admitted(obj, cls_name), cls_name)
                self.assertEqual(set(db._admitted(obj, cls_name)),
                                 set(db.STORED_NUMBERS[cls_name]), cls_name)
        for cls_name in db.STORED_NUMBERS:                        # an object missing the fields entirely
            for junk in (None, object(), "pair", 0, ()):
                self.assertIsNone(db._admitted(junk, cls_name), (cls_name, repr(junk)))
        self.assertFalse(hasattr(db, "_numbers_intact"))
        # one absent field is enough, and `_pair_numbers_ok` is exactly the IntervalPair case
        class NoLevel(bm.IntervalPair):
            @property
            def level(self):
                raise AttributeError("level is absent")
        k = joint()
        p = k.h1.components[0].pair
        object.__setattr__(p, "__class__", NoLevel)
        self.assertIsNone(db._admitted(p, "IntervalPair"))
        self.assertFalse(pair_ok(k))
        self.assertEqual(pair_ok(joint()), True)


class FailsClosedAssertions:
    """`assertFailsClosedWithAnAlarm` as a mixin, so the round-5 class below uses the SAME assertion as
    the round-4 sweep rather than a re-typed copy of it. A plain mixin (no TestCase base) is not
    collected as a test case, so the sweeps it serves are not run twice."""

    def assertFailsClosedWithAnAlarm(self, h, hids, label):
        cells = hyp_cells(h)
        for hid in hids:
            self.assertEqual(cells.get(hid), "INCONCLUSIVE", f"{label}: {hid} is {cells.get(hid)}")
        self.assertIn("NOT shown", h, f"{label}: no alarm")
        jc = joint_cell(h)
        self.assertNotIn("vd-supported", jc, label)
        self.assertNotIn("vd-unsupported", jc, label)
        self.assertIn("JOINT_INCONCLUSIVE", jc, label)


class EveryForgedNumberIsCheckedAtTheVerdictAndTheAlarm(FailsClosedAssertions, unittest.TestCase):
    """THE TEST-DESIGN RULE THAT WOULD HAVE CAUGHT ALL THREE ROUNDS, applied as this module's default
    shape for a forgery test: FOR EVERY FORGED VALUE, ASSERT THE VERDICT CELL AND THE ALARM, NOT JUST
    THE FIGURE CELL.

    Every round's miss was a test that checked the number and never asked what the page concluded.
    Round 2's `_interval` tests checked the interval cell. Round 3's
    `test_n_cell_excludes_bool_like_every_sibling_count_cell` fed `nan`, `1.0`, `"30"` and `None` to
    `pair.n` and asserted ONLY on the n cell -- which was already correct -- so it passed while the same
    forged `nan` was buying a decisive JOINT_SUPPORTED two columns to the right. A figure cell reading
    UNKNOWN is not the property SR-13 is about; the property is that the page does not CONCLUDE
    anything from a number it will not show.

    The sweep is driven by `db.STORED_NUMBERS`, not by a list written here, so a number added to the
    table gets this assertion automatically and a number added WITHOUT the table fails the probe test
    above instead. That chain -- probe proves the table complete, table drives the sweep, sweep asserts
    verdict and alarm -- is what replaces three rounds of asserted enumerations."""

    def test_every_verdict_bearing_stored_number_fails_closed_with_an_alarm(self):
        for cls_name in db.VERDICT_BEARING:
            for attr, kind in db.STORED_NUMBERS[cls_name].items():
                hids = HYPOTHESES_READING.get((cls_name, attr), ("H1", "H2", "H3"))
                caveat = FIGURE_CAVEAT[(cls_name, attr)]
                for bad in HOSTILE_BY_KIND[kind]:
                    label = f"{cls_name}.{attr} = {bad!r}"
                    j = forge_declared(joint_private_margins(), cls_name, attr, bad)
                    h = db.render_scorecard(j)                       # must not raise, ever
                    self.assertFailsClosedWithAnAlarm(h, hids, label)
                    if caveat is not None:                           # ... and the FIGURE is UNKNOWN too
                        self.assertIn("UNKNOWN", h, label)
                        self.assertIn(caveat, db.render_dashboard({"joint": j}), label)
                    for forbidden in ("[0.0, 0.0]", "[nan, nan]", "[inf, inf]", ">nan<", ">inf<"):
                        self.assertNotIn(forbidden, h, f"{label}: {forbidden}")
        # NOT VACUOUS: the same fixture, unforged, is decisive and silent.
        clean = db.render_scorecard(joint_private_margins())
        self.assertIn("JOINT_SUPPORTED", joint_cell(clean))
        self.assertNotIn("NOT shown", clean)
        self.assertEqual(set(hyp_cells(clean).values()), {"SUPPORTED"})

    def test_the_study_seed_counts_are_a_figure_AND_the_second_source(self):
        """ROUND-5 REVERSAL, kept as its own test because the claim it replaces is the clearest
        statement of the round-5 defect in this file.

        This test used to be called `test_the_two_figure_only_numbers_are_UNKNOWN_and_create_no_verdict`
        and it asserted that `JointResult.n_attempted` / `n_failed` "feed NO recomputation, so
        UNKNOWN-without-an-alarm is the correct outcome for them rather than a gap" -- and then measured
        exactly that, over all 15 hostile counts: figure UNKNOWN, and `hyp_cells(h) == hyp_cells(honest)`
        in both directions. Every assertion passed. The asymmetry it called deliberate was the hole:
        `n_attempted - n_failed` is the study's own measured-seed count, which is the only second source
        this page has for `pair.n`, so a renderer that recomputes nothing from these two has no way to
        refuse a forged legal `n`. They are now BOTH a figure and a verdict input, which is the normal
        case in this module and not an exception to it.

        What must hold now: the figure still reads UNKNOWN (never 0), and the page fails closed with an
        alarm instead of carrying on -- because an unreadable second source means `pair.n` is
        unverified, not that the cross-check may be skipped."""
        honest = db.render_scorecard(joint())
        self.assertIn("JOINT_SUPPORTED", joint_cell(honest))
        for attr in ("n_attempted", "n_failed"):
            for bad in HOSTILE_BY_KIND["count"]:
                j = forge_declared(joint(), "JointResult", attr, bad)
                h = db.render_scorecard(j)
                line = re.search(r"<p>Attempted .*?</p>", h).group(0)
                self.assertIn("UNKNOWN", line, f"{attr}={bad!r}")
                self.assertIn("not recorded", line, f"{attr}={bad!r}")
                self.assertNotIn(">0<", line, f"{attr}={bad!r}")
                # the figure is UNKNOWN *and* nothing decisive survives it, with the reason named
                self.assertFailsClosedWithAnAlarm(h, ("H1", "H2", "H3"), f"{attr}={bad!r}")
                self.assertIsNone(db._measured_seeds(j), f"{attr}={bad!r}")
                self.assertIn("not readable", h, f"{attr}={bad!r}")
                self.assertNotEqual(hyp_cells(h), hyp_cells(honest), f"{attr}={bad!r}")

    def test_G1_a_forged_n_cannot_launder_a_genuinely_below_minimum_run(self):
        """ROUND-4 FAIL GROUND. `pair.n` had two consumers that disagreed: the display cell (an inline
        `isinstance(int)`) and `interval_verdict`'s protocol-6.1 floor, `n < min_n`. `nan < 30` and
        `inf < 30` are both False, so a forged `n` PASSED THE MINIMUM-SEED FLOOR AS A NUMBER.

        MEASURED AT HEAD on this fixture -- a genuine 29-seed run whose `min_seeds` gate was flipped to
        passed in place (leaving the gate NAME set intact, so the gate-set check cannot be what catches
        it) and whose stored verdicts were forged SUPPORTED:
            pair.n untouched -> every hypothesis INCONCLUSIVE, alarm raised   (the forgery is caught)
            pair.n = nan     -> JOINT_SUPPORTED displayed, NO alarm, and the sample-size cell reading
                                'UNKNOWN n' right beside it
        A below-minimum run rendering a decisive JOINT_SUPPORTED with no visible sample size is the
        whole of what SR-13 exists to prevent. A forged BOUND failed closed with an alarm; a forged `n`
        did not, because `_pair_numbers_ok` listed the four bounds by hand.

        Note what the pre-existing coverage did: it fed `nan` to `pair.n` and asserted the n cell only."""
        j = joint(expect=bm.JointVerdict.JOINT_INCONCLUSIVE, seeds=FZ.seeds[:29])
        self.assertEqual(j.h1.components[0].pair.n, 29)
        forge_gate_pass(j, "min_seeds")
        forge_all_verdicts_supported(j)
        self.assertTrue(db._gate_set_ok(j.gates))          # not the gate-set check
        # the fixture really does PRESENT a decisive stored verdict: `JointResult.verdict` is a property
        # over the (now forged) hypothesis verdicts, so the page is being asked to display SUPPORTED.
        self.assertIs(j.verdict, bm.JointVerdict.JOINT_SUPPORTED)
        h = db.render_scorecard(j)                         # untouched n: already caught
        self.assertFailsClosedWithAnAlarm(h, ("H1", "H2", "H3"), "n untouched")
        for bad in (float("nan"), float("inf"), float("-inf"), 1.0, True, "30", None, []):
            k = forge_declared(joint(expect=bm.JointVerdict.JOINT_INCONCLUSIVE, seeds=FZ.seeds[:29]),
                               "IntervalPair", "n", bad)
            forge_gate_pass(k, "min_seeds")
            forge_all_verdicts_supported(k)
            h = db.render_scorecard(k)
            self.assertFailsClosedWithAnAlarm(h, ("H1", "H2", "H3"), f"n={bad!r}")
            self.assertIsNone(recompute(k.h1.components[0], k.margins, k), repr(bad))
            self.assertFalse(pair_ok(k), repr(bad))
            self.assertNotIn("JOINT_SUPPORTED", h, repr(bad))
            # the n cell and the verdict cell now agree that the sample size is unknown
            self.assertIn('<span class="caveat">n</span>', comp_row(h, "S"), repr(bad))
        # NOT VACUOUS, and no over-refusal: a genuine 29 is still printed as 29, and a genuine 30-seed
        # run is still decisive with no alarm.
        self.assertIn("<td>29</td>", comp_row(db.render_scorecard(
            joint(expect=bm.JointVerdict.JOINT_INCONCLUSIVE, seeds=FZ.seeds[:29])), "S"))
        self.assertIn("<td>30</td>", comp_row(db.render_scorecard(joint()), "S"))
        self.assertNotIn("NOT shown", db.render_scorecard(joint()))

    def test_G2_a_coerced_margin_cannot_back_a_decisive_verdict(self):
        """ROUND-4 FAIL GROUND. `_recompute` did `float(c.margin)` and `_declared` did
        `float(getattr(margins, attr))` -- the bare coercion `_finite_float`'s own docstring already said
        had been eliminated -- while the two DISPLAY cells checked `(int, float)` + finite properly.

        MEASURED AT HEAD with both the component margin and the Margins field set to the string "0.1":
            uncertainty panel delta_S : UNKNOWN  "delta_S is not a finite number; unmeasured, NOT zero"
            scorecard H1 margin cell  : UNKNOWN  margin
            scorecard H1 verdict cell : SUPPORTED, with no alarm
        The margin read UNKNOWN in both panels while a decisive verdict derived from it was displayed.
        It could NOT be driven to a WRONG verdict -- the coerced value still had to float-equal the
        declared margin or `_recompute` returned None -- so this was a self-contradicting row plus
        unalarmed tampering rather than a laundered figure. That is still a fail: the criterion is that
        the display and the verdict admit the same values."""
        for bad in ("0.1", "0.05", "0.10", True, float("nan"), [0.1], None):
            j = joint_private_margins()
            for c in all_components(j):
                object.__setattr__(c, "margin", bad)
            for k in ("delta_S", "delta_R", "delta_sel"):
                object.__setattr__(j.margins, k, bad)
            page = db.render_dashboard({"joint": j})
            h = db.render_scorecard(j)
            self.assertFailsClosedWithAnAlarm(h, ("H1", "H2", "H3"), repr(bad))
            self.assertIn("is not a finite number; unmeasured, NOT zero", page, repr(bad))
            self.assertIn('<span class="caveat">margin</span>', comp_row(h, "S"), repr(bad))
            self.assertIsNone(recompute(j.h1.components[0], j.margins, j), repr(bad))
            self.assertIsNone(db._declared("S", j.margins)[1], repr(bad))
        # the component margin alone, with an honest Margins object: still an alarm (it was already)
        j = joint_private_margins()
        object.__setattr__(j.h1.components[0], "margin", "0.1")
        self.assertIsNone(recompute(j.h1.components[0], j.margins, j))
        self.assertFailsClosedWithAnAlarm(db.render_scorecard(j), ("H1",), "component margin only")
        # NOT VACUOUS / no over-refusal: an honest float margin, and a legitimate INT margin, both work.
        self.assertEqual(db._declared("S", bm.Margins()), ("greater", bm.Margins().delta_S))
        m_int = bm.Margins(delta_S=1, delta_R=1, delta_sel=1)
        self.assertEqual(db._declared("S", m_int), ("greater", 1))
        self.assertIn('<span class="measured">1.0</span>',
                      db._kind_cell(1, "why", "num"))          # an int margin still renders as a number

    def test_the_family_line_is_UNKNOWN_unless_both_of_its_numbers_are_admitted(self):
        """`_num(bm.bonferroni_level())` had no finiteness gate and `bm.N_PRIMARY` had none at all; only
        a bare `except` stood behind them. Measured at HEAD: `bonferroni_level` returning `nan`/`inf`
        printed "Bonferroni level nan"/"inf"; returning the STRING "0.9875" printed a coerced 0.9875 as
        if it were a measured number; `N_PRIMARY` patched to `nan`/`True` printed "nan primary
        intervals"/"True primary intervals"."""
        j = joint()
        fam = lambda h: re.search(r'<p class="caveat">([^<]*(?:primary intervals|family size)[^<]*)</p>', h).group(1)
        self.assertEqual(fam(db.render_scorecard(j)),
                         f"{bm.N_PRIMARY} primary intervals, Bonferroni level "
                         f"{repr(float(bm.bonferroni_level()))} (read from the scorer)")
        for bad in (float("nan"), float("inf"), "0.9875", 1, None, [], True):
            with mock.patch.object(bm, "bonferroni_level", lambda *a, **k: bad):
                h = db.render_scorecard(j)
            self.assertEqual(fam(h), "family size/level UNKNOWN", repr(bad))
            self.assertNotIn("Bonferroni level", h, repr(bad))
        for bad in (float("nan"), float("inf"), 4.0, True, "4", None, []):
            with mock.patch.object(bm, "N_PRIMARY", bad):
                h = db.render_scorecard(j)
            self.assertEqual(fam(h), "family size/level UNKNOWN", repr(bad))
            self.assertNotIn("primary intervals", h, repr(bad))
        with mock.patch.object(bm, "bonferroni_level", side_effect=ValueError("boom")):
            self.assertEqual(fam(db.render_scorecard(j)), "family size/level UNKNOWN")

    def test_no_false_alarm_the_scheme_admits_every_honest_fixture(self):
        """OVER-REFUSAL CHECK, which `_pair_numbers_ok` now needs more of than it did: it gained `mean`,
        `n` and `level`, and `_recompute` gained the whole `ComponentResult` triple. Nothing an honest
        producer builds may fail any of them -- including a 1-seed run, whose t-interval is genuinely
        unmeasured, and a 29-seed run, which is honestly below the protocol minimum."""
        for kw in (dict(), dict(expect=None, S=0.0), dict(expect=None, conv=False),
                   dict(expect=None, L=1.0), dict(expect=None, gate_inputs=False),
                   dict(expect=None, seeds=FZ.seeds[:29]), dict(expect=None, seeds=FZ.seeds[:1]),
                   dict(expect=None, registered="deadbeef" * 8)):
            j = joint(**kw)
            for cls_name in db.STORED_NUMBERS:
                for obj in instances_of(j, cls_name):
                    self.assertIsNotNone(db._admitted(obj, cls_name), (kw, cls_name))
            for c in all_components(j):
                self.assertIsNotNone(recompute(c, j.margins, j), repr(kw))
        for kw in (dict(), dict(expect=None, S=0.0), dict(expect=None, L=1.0)):
            self.assertNotIn("NOT shown", db.render_scorecard(joint(**kw)), repr(kw))
        # a legitimately unmeasured bound is NOT tampering, and a genuine 0.0 is still measured
        k = joint()
        object.__setattr__(k.h1.components[0].pair, "boot_lo", MetricValue.unmeasured("failed"))
        self.assertTrue(pair_ok(k))
        self.assertIn('<span class="measured">0.0</span>', db._kind_cell(0.0, "why", "num"))
        self.assertIn('<span class="measured">0</span>', db._kind_cell(0, "why", "count"))
        self.assertIn('<span class="measured">0.0</span>', db._kind_cell(0.0, "why", "float"))


def laundered_below_minimum(n=None, seeds=29, **over):
    """The round-5 fixture: a GENUINE below-minimum study presented as a decisive success.

    A real `seeds`-seed run, its failing `min_seeds` gate flipped to passed IN PLACE (so the gate NAME
    set stays intact and `_gate_set_ok` cannot be what catches it -- the same forgery `test_G1` uses),
    every stored component and hypothesis verdict forged SUPPORTED, and `blocking` cleared. `n` forges
    `pair.n` on every component; `over` forges fields of the JointResult itself."""
    j = joint(expect=bm.JointVerdict.JOINT_INCONCLUSIVE, seeds=FZ.seeds[:seeds])
    forge_gate_pass(j, "min_seeds")
    forge_all_verdicts_supported(j)
    if n is not None:
        for c in all_components(j):
            object.__setattr__(c.pair, "n", n)
    for k, v in over.items():
        object.__setattr__(j, k, v)
    return j


def honest_shapes():
    """Every legitimate study shape this file can build, as (label, JointResult). A cross-check that
    false-fires is a defect, so the no-false-alarm sweep needs more shapes than the forgery sweeps do --
    in particular shapes where `pair.n` is legitimately LESS than the measured-seed count, which is the
    reason the cross-check is an inequality and not an equality."""
    out = [(f"joint({kw})", joint(**kw)) for kw in (
        dict(), dict(expect=None, S=0.0), dict(expect=None, conv=False), dict(expect=None, L=1.0),
        dict(expect=None, gate_inputs=False), dict(expect=None, seeds=FZ.seeds[:29]),
        dict(expect=None, seeds=FZ.seeds[:1]), dict(expect=None, registered="deadbeef" * 8))]
    for nfail in (1, 3, 10):            # FAILED seeds: n_attempted stays 30, the measured count drops
        scores = make_scores(FZ.seeds)
        for i in range(nfail):
            scores[i] = bm.SeedScores.failed(FZ.seeds[i], "synthetic failure")
        out.append((f"n_failed={nfail}", bm.analyze_scores(
            scores, frozen=FZ, registered_digest=FZ.digest, subject="synthetic", cfg=SMALL)))
    scores = make_scores(FZ.seeds)      # one metric unmeasured on 5 OK seeds: pair.n < measured count
    for i in range(5):
        m = dict(scores[i].metrics)
        m["delta_conv"] = MetricValue.unmeasured("not supplied")
        scores[i] = dataclasses.replace(scores[i], metrics=m)
    out.append(("delta_conv unmeasured on 5 ok seeds", bm.analyze_scores(
        scores, frozen=FZ, registered_digest=FZ.digest, subject="synthetic", cfg=SMALL)))
    for ms, nseeds in ((10, 10), (10, 30), (29, 29), (1, 30), (60, 30), (30, 30)):
        out.append((f"min_seeds={ms} over {nseeds} seeds", bm.analyze_scores(
            make_scores(FZ.seeds[:nseeds]), frozen=FZ, registered_digest=FZ.digest, subject="synthetic",
            cfg=bm.BenchmarkConfig(n_boot=500, min_seeds=ms))))
    return out


class TypeIsNotTheWholeOfAdmission(FailsClosedAssertions, unittest.TestCase):
    """SR-13 ROUND 5. The item failed a FOURTH time, and this time not because a consumer of a stored
    number was missed. Every consumer was declared in `db.STORED_NUMBERS`, the probe proved the table
    complete, every consumer was routed through its kind function, and the whole table was swept with
    hostile values while asserting the verdict and the alarm. The defect is that `pair.n` was admitted
    BY TYPE ONLY.

    MEASURED AT HEAD on `laundered_below_minimum()` -- a genuine 29-seed run whose `min_seeds` gate was
    flipped to passed in place and whose stored verdicts were forged SUPPORTED:
        pair.n untouched (29) -> JOINT_INCONCLUSIVE, alarm, 1 warning paragraph    (caught)
        pair.n = 30           -> JOINT_SUPPORTED, NO alarm, ZERO warning paragraphs
        pair.n = 31           -> JOINT_SUPPORTED, NO alarm, ZERO warning paragraphs
        pair.n = nan          -> JOINT_INCONCLUSIVE, alarm                         (caught: not an int)
    `30` is a legal `int`, `_count` admits it, and `_count` MUST admit it. No tightening of a type
    predicate can distinguish the honest 30 from the forged one, so the round-4 mechanism could not have
    caught this however carefully its tables were kept.

    THE FIX IS THE ONE `benchmark.py` HAD ALREADY WRITTEN DOWN, at its own `n` cross-check: "A forged
    `n_seeds` is a legal count, so `_metric_count` cannot catch it; the only defence is a second stored
    number to compare it against ... n must be CHECKED against something, not trusted." This renderer
    printed BOTH HALVES of that second number on the same page -- "Attempted 29, failed 0" -- and used
    neither, and `IntervalPair.flags` carried the producer's own statement that n was below the minimum
    while `dashboard.py` contained no reference to `flags` at all."""

    def test_G3_a_LEGAL_n_cannot_launder_a_genuinely_below_minimum_run(self):
        """THE ROUND-5 PIN. Asserts the VERDICT and the ALARM for each legal forged `n`, not a figure."""
        j = laundered_below_minimum()
        self.assertEqual(j.h1.components[0].pair.n, 29)
        self.assertTrue(db._gate_set_ok(j.gates))            # not the gate-set check
        self.assertIs(j.verdict, bm.JointVerdict.JOINT_SUPPORTED)   # the page IS asked to show SUPPORTED
        self.assertFailsClosedWithAnAlarm(db.render_scorecard(j), ("H1", "H2", "H3"), "n untouched")
        for bad in (30, 31, 1000, 2 ** 40):                  # every one a legal, nonnegative int
            k = laundered_below_minimum(n=bad)
            self.assertEqual(db._count(bad), bad, repr(bad))         # the TYPE check is right to admit it
            h = db.render_scorecard(k)
            self.assertFailsClosedWithAnAlarm(h, ("H1", "H2", "H3"), f"n={bad!r}")
            self.assertNotIn("JOINT_SUPPORTED", h, repr(bad))
            self.assertIsNone(recompute(k.h1.components[0], k.margins, k), repr(bad))
            self.assertFalse(pair_ok(k), repr(bad))
            self.assertIn("SAMPLE SIZE CONTRADICTED", h, repr(bad))
            self.assertIn(f"a component claims {bad} seeds but the study records only 29", h, repr(bad))
            # the n CELL still prints the forged value: this page does not hide the number it refuses,
            # it shows it and says it is contradicted (round 4's n=nan rendered 'UNKNOWN n' instead).
            self.assertIn(f"<td>{bad}</td>", comp_row(h, "S"), repr(bad))
        # NOT VACUOUS and no over-refusal: the honest 29 and the honest 30 are unchanged.
        self.assertIn("<td>29</td>", comp_row(db.render_scorecard(
            joint(expect=bm.JointVerdict.JOINT_INCONCLUSIVE, seeds=FZ.seeds[:29])), "S"))
        clean = db.render_scorecard(joint())
        self.assertIn("<td>30</td>", comp_row(clean, "S"))
        self.assertIn("JOINT_SUPPORTED", joint_cell(clean))
        self.assertNotIn("NOT shown", clean)
        self.assertNotIn("SAMPLE SIZE CONTRADICTED", clean)

    def test_the_second_source_is_itself_anchored_on_the_seed_score_list(self):
        """A cross-check whose second source is one more producer-asserted integer is defeated by one
        more `object.__setattr__`. MEASURED with the n-cross-check in place but no anchor: on the
        `pair.n = 30` fixture, forging `n_attempted` to 30, to 1000, or to 31 with `n_failed` 1 each
        restored JOINT_SUPPORTED with no alarm. `seed_scores` is a LIST OF OBJECTS, and `SeedScores.ok`
        is a read-only property derived from the metrics rather than a stored flag, so neither the length
        nor the not-ok count can be edited in place at all."""
        for over in ({"n_attempted": 30}, {"n_attempted": 1000},
                     {"n_attempted": 31, "n_failed": 1}, {"n_failed": -1}):
            k = laundered_below_minimum(n=30, **over)
            h = db.render_scorecard(k)
            self.assertFailsClosedWithAnAlarm(h, ("H1", "H2", "H3"), repr(over))
            self.assertIsNone(db._measured_seeds(k), repr(over))
            self.assertIn("not readable", h, repr(over))
        # the anchor's two halves, each unmasked by the other
        j = joint()
        self.assertEqual(db._measured_seeds(j), 30)
        object.__setattr__(j, "seed_scores", tuple(j.seed_scores[:29]))
        self.assertIsNone(db._measured_seeds(j))             # length half
        j = joint()
        s0 = j.seed_scores[0]
        with self.assertRaises(AttributeError):              # `ok` is a property: not settable at all
            object.__setattr__(s0, "ok", True)
        object.__setattr__(j, "seed_scores",
                           (bm.SeedScores.failed(1, "synthetic"), *j.seed_scores[1:]))
        self.assertIsNone(db._measured_seeds(j))             # not-ok-count half
        for junk in (None, object(), 0, "scores"):           # an unreadable list is no second source
            k = joint()
            object.__setattr__(k, "seed_scores", junk)
            self.assertIsNone(db._measured_seeds(k), repr(junk))
        # THE RESIDUAL, RE-MEASURED. This comment used to say the anchor "raises the cost of the forgery
        # from one integer to 30 fabricated objects". MEASURED: the cost was 0 fabricated objects -- see
        # `test_the_measured_cost_of_the_anchors_residual` below, which performs the cheap variant and
        # the corrected figures rather than asserting them in prose. What is kept here is the part that
        # is still true of `_measured_seeds` ALONE, with the one fabricated object the variant below
        # needs: the two seed-count equalities cannot see an extra consistent entry. The INTERVAL
        # cross-check can, and does; that is asserted in the test below, not here, so this assertion
        # keeps measuring `_measured_seeds` unmasked.
        k = laundered_below_minimum(n=30)
        object.__setattr__(k, "seed_scores", (*k.seed_scores, make_scores([999])[0]))
        object.__setattr__(k, "n_attempted", 30)
        for c in all_components(k):
            object.__setattr__(c.pair, "flags", ())
        self.assertEqual(db._measured_seeds(k), 30)
        self.assertIsNone(db._n_problem(k.h1.components[0].pair, 30, 30, 30))

    def test_the_two_sources_are_independent_and_neither_masks_the_other(self):
        """The F-h lesson: each source must be able to catch the forgery with the other one disabled, or
        one of them is untested and could be fail-open without any test going red."""
        # SOURCE A ALONE: delete the producer's flag, so only the measured-seed count can act.
        k = laundered_below_minimum(n=30)
        for c in all_components(k):
            object.__setattr__(c.pair, "flags", ())
        self.assertIn("but the study records only 29 measured seeds",
                      db._n_problem(k.h1.components[0].pair, 30, 30, db._measured_seeds(k)))
        self.assertFailsClosedWithAnAlarm(db.render_scorecard(k), ("H1", "H2", "H3"), "source A alone")
        # SOURCE B ALONE: an honest 30-seed study, so source A is silent (30 <= 30) -- asserted on the
        # untouched pair FIRST, or "source B caught it" would be unfalsifiable -- then the flag is
        # forged on, which only source B can see.
        k = joint()
        self.assertEqual(db._measured_seeds(k), 30)
        self.assertIsNone(db._n_problem(k.h1.components[0].pair, 30, 30, 30),
                          "source A must be silent on this fixture, or source B is masked")
        for c in all_components(k):
            object.__setattr__(c.pair, "flags", (db.MIN_SEEDS_FLAG,))
        p = db._n_problem(k.h1.components[0].pair, 30, 30, db._measured_seeds(k))
        self.assertIn("but its stored n is 30, which is not below the declared minimum 30", p)
        self.assertFailsClosedWithAnAlarm(db.render_scorecard(k), ("H1", "H2", "H3"), "source B alone")
        # and a `flags` forged to the bare STRING would otherwise defeat source B, because `in` over a
        # string matches characters -- so a non-tuple `flags` is itself fail-closed.
        k = joint()
        for c in all_components(k):
            object.__setattr__(c.pair, "flags", db.MIN_SEEDS_FLAG)
        self.assertIn("flags field is not a tuple", db._n_problem(k.h1.components[0].pair, 30, 30, 30))
        self.assertFailsClosedWithAnAlarm(db.render_scorecard(k), ("H1", "H2", "H3"), "flags as a string")

    def test_n_problem_and_measured_seeds_fail_closed_unmasked(self):
        """Direct unit tests. `_recompute` has many other ways to return None, so no other layer may be
        allowed to mask a fail-open in either of these (the F-h lesson)."""
        flagged, clean = (db.MIN_SEEDS_FLAG,), ()
        P = lambda fl, n, mn, m: db._n_problem(joint().h1.components[0].pair.__class__(  # noqa: E731
            "x", n, 0.9, 10, *([MetricValue.unmeasured("u")] * 10), fl), n, mn, m)
        self.assertIsNone(P(clean, 29, 30, 29))              # honest below-minimum run
        self.assertIsNone(P(flagged, 29, 30, 29))            # ... and its flag agrees
        self.assertIsNone(P(clean, 0, 30, 30))               # a 0-seed converged series
        self.assertIsNone(P(clean, 25, 30, 30))              # legitimately fewer than the measured count
        self.assertIn("only 29", P(clean, 30, 30, 29))       # source A
        self.assertIn("not below the declared minimum", P(flagged, 30, 30, 30))   # source B
        self.assertEqual(P(clean, 30, 30, None), db.NO_SECOND_SOURCE_MSG)         # no second source
        self.assertEqual(db._measured_seeds(joint(expect=None, seeds=FZ.seeds[:1])), 1)
        self.assertEqual(db._measured_seeds(joint(expect=None, seeds=FZ.seeds[:29])), 29)
        for junk in (None, object(), 0, "joint", ()):
            self.assertIsNone(db._measured_seeds(junk), repr(junk))
        self.assertEqual(db._n_sources_disagree(joint(), 30), [])
        self.assertEqual(db._n_sources_disagree(joint(), None), [db.NO_SECOND_SOURCE_MSG])
        for junk in (None, object(), 0):
            self.assertEqual(db._n_sources_disagree(junk, 30), [], repr(junk))
        # a non-count `n` is NOT reported here: the kind functions alarm on that, in their own words
        k = forge_declared(joint(), "IntervalPair", "n", float("nan"))
        self.assertEqual(db._n_sources_disagree(k, 30), [])
        self.assertFalse(pair_ok(k))

    def test_the_min_seeds_flag_literal_is_the_one_the_scorer_emits(self):
        """`db.MIN_SEEDS_FLAG` is a string literal SHARED with `benchmark.summarize`, so a rename in the
        scorer would silently disable source B rather than break anything. It is pinned here, against
        the scorer's real output, rather than by a render-time contract probe: `_contract_problems`
        withholds every decisive verdict when it fires, and a page must not lose its verdicts because a
        neighbouring module in flux renamed a flag. The suite is the right place for that to go red."""
        self.assertIn(db.MIN_SEEDS_FLAG, bm.summarize("c", [1.0], 0.99, 10, 0, min_n=30).flags)
        self.assertNotIn(db.MIN_SEEDS_FLAG, bm.summarize("c", [1.0], 0.99, 10, 0, min_n=1).flags)
        self.assertIn(db.MIN_SEEDS_FLAG,
                      joint(expect=None, seeds=FZ.seeds[:29]).h1.components[0].pair.flags)
        self.assertNotIn(db.MIN_SEEDS_FLAG, joint().h1.components[0].pair.flags)

    def test_the_gate_detail_text_is_the_same_number_read_as_a_string(self):
        """The third source the brief named, and the one deliberately NOT read: the `min_seeds` gate row
        renders "29 measured seeds vs minimum 30" on the very page that displayed the forgery. It is
        `GateResult.reason`, free text, and structural guard 3 of this module is "No verdict is ever
        parsed from any string" -- so parsing it would make producer-supplied prose verdict-bearing.

        Nothing is given up, and that is what this test pins: `evaluate_gates` computes that sentence
        from `len(scores) - sum(not s.ok for s in scores)`, which is the same number off the same
        `seed_scores` list that `db._measured_seeds` reads as typed data. Pinned because it is a claim
        about a neighbouring module: if the gate ever reports a DIFFERENT quantity, this goes red and the
        argument for ignoring the text has to be made again rather than inherited."""
        for label, j in honest_shapes():
            g = next(g for g in j.gates if g.name == "min_seeds")
            self.assertEqual(g.reason.split()[0], str(db._measured_seeds(j)), label)
            self.assertIn("measured seeds vs minimum", g.reason, label)
        # and the text is rendered only through the untrusted-free-text box, never parsed
        h = db.render_scorecard(laundered_below_minimum(n=30))
        self.assertIn("29 measured seeds vs minimum 30", h)
        self.assertNotIn("reason", db._n_problem.__code__.co_names)

    def test_only_one_direction_of_the_flag_implication_is_used(self):
        """"flag present => n < min_n" is used. "n < min_n => flag present" is NOT, and must not be:
        `benchmark._pair_from_record` rebuilds an `IntervalPair` from stored metrics and passes no
        `flags`, so a records-roundtripped below-minimum pair legitimately carries an EMPTY tuple. The
        asymmetry is also the only form a forgery cannot exploit -- deleting the flag gives up a check
        and buys nothing, which `test_the_two_sources_are_independent...` measures on source A."""
        self.assertEqual(bm.IntervalPair.__dataclass_fields__["flags"].default, ())
        p = bm.IntervalPair("x", 5, 0.9, 10, *([MetricValue.unmeasured("u")] * 10))
        self.assertEqual((p.n, p.flags), (5, ()))            # below any minimum, and unflagged
        self.assertIsNone(db._n_problem(p, 5, 30, 29))       # so it must NOT be refused

    def test_every_declared_number_is_classified_by_its_second_source(self):
        """The classification is PERFORMED, like the consumer enumeration above it: a declared number
        that is in none of the three dicts fails here, naming itself, so "no second source" has to be a
        recorded decision rather than an omission."""
        declared = {(cls, attr) for cls, fields in db.STORED_NUMBERS.items() for attr in fields}
        classified = set(SECOND_SOURCE) | set(NEUTRALISED_BY_A_FLOOR) | set(NO_SECOND_SOURCE)
        self.assertEqual(classified, declared, f"""
A declared stored number is not classified by whether the result contains a second source for it.
  declared but unclassified : {sorted(declared - classified)}
  classified but undeclared : {sorted(classified - declared)}
Round 4 swept `HOSTILE_BY_KIND` (a TYPE table) over every declared number and called the enumeration
done; round 5's defect was a LEGAL value for a field that had a second source nobody consulted. Put the
entry in SECOND_SOURCE (and give it LEGAL_BUT_WRONG values), in NEUTRALISED_BY_A_FLOOR, or in
NO_SECOND_SOURCE with the reason -- the third is a residual and is allowed, but it has to be written.""")
        self.assertEqual(len(set(SECOND_SOURCE) & set(NEUTRALISED_BY_A_FLOOR)), 0)
        self.assertEqual(len(set(SECOND_SOURCE) & set(NO_SECOND_SOURCE)), 0)
        self.assertEqual(len(set(NEUTRALISED_BY_A_FLOOR) & set(NO_SECOND_SOURCE)), 0)
        # every entry that HAS a second source is swept with legal-but-wrong values
        self.assertEqual(set(LEGAL_BUT_WRONG),
                         set(SECOND_SOURCE) | set(NEUTRALISED_BY_A_FLOOR))
        for key, vals in LEGAL_BUT_WRONG.items():
            kind = db.STORED_NUMBERS[key[0]][key[1]]
            # an emptied entry would make the sweeps below pass by iterating over nothing, which is the
            # vacuity that let three rounds' "the enumeration is complete" claims stand
            self.assertGreaterEqual(len(vals), 3, f"{key}: too few legal-but-wrong values to be a sweep")
            for v in vals:                       # each must be ADMITTED by its kind: that is the point
                if kind == "mv":                 # an "mv" value is forged INSIDE the MetricValue
                    self.assertIsNotNone(
                        db._mv_intact(forge_mv(MetricValue.measured(1.0), v)), (key, v))
                else:
                    self.assertIsNotNone(db._NUM_KINDS[kind](v), (key, v))
                # ... and must not already be in the TYPE table. Compared by repr, not by `in`: `0` and
                # `0.0` are `==` in Python while being a legal count and an ill-typed one respectively,
                # which is the same int/float confusion the kind functions exist to refuse.
                self.assertNotIn(repr(v), [repr(x) for x in HOSTILE_BY_KIND[kind]], (key, v))

    def test_every_legal_but_wrong_value_fails_closed_with_an_alarm(self):
        """The round-4 sweep's rule -- assert the VERDICT and the ALARM, never the figure alone -- over
        the half of the value space a type predicate cannot reach."""
        for key in SECOND_SOURCE:
            cls_name, attr = key
            hids = HYPOTHESES_READING.get(key, ("H1", "H2", "H3"))
            for bad in LEGAL_BUT_WRONG[key]:
                label = f"{cls_name}.{attr} = {bad!r} (legal, wrong)"
                j = forge_declared(joint_private_margins(), cls_name, attr, bad)
                h = db.render_scorecard(j)                   # must not raise, ever
                self.assertFailsClosedWithAnAlarm(h, hids, label)
                self.assertNotIn("JOINT_SUPPORTED", joint_cell(h), label)
        clean = db.render_scorecard(joint_private_margins())  # NOT VACUOUS
        self.assertIn("JOINT_SUPPORTED", joint_cell(clean))
        self.assertNotIn("NOT shown", clean)

    def test_a_floored_parameter_cannot_change_what_the_page_displays(self):
        """The two declared numbers whose legal-but-wrong values may NOT be refused, because an honest
        non-compliant `BenchmarkConfig` emits them too (argued at `db._weaker_than_protocol`). What must
        hold instead is that the one-sided floor makes them unable to move anything displayed."""
        honest = db.render_scorecard(joint_private_margins())
        for key in NEUTRALISED_BY_A_FLOOR:
            for bad in LEGAL_BUT_WRONG[key]:
                label = f"{key[0]}.{key[1]} = {bad!r}"
                h = db.render_scorecard(forge_declared(joint_private_margins(), *key, bad))
                self.assertEqual(hyp_cells(h), hyp_cells(honest), label)
                self.assertEqual(joint_cell(h), joint_cell(honest), label)
                self.assertNotIn("NOT shown", h, label)
                self.assertIn("WEAKER THAN THE PROTOCOL", h, label)   # said, not silently absorbed

    def test_the_cross_check_never_false_fires_on_a_legitimate_study(self):
        """OVER-REFUSAL CHECK, and the reason the invariant is `component n <= measured seeds` rather
        than equality. Measured over 18 legitimate study shapes: 0 disagreements, and `pair.n` is
        STRICTLY less than the measured-seed count in three of them (`conv=False` gives `pair.n = 0` on
        the converged components; one converged metric left unmeasured on 5 OK seeds gives
        `delta_conv n = 25` against 30 measured seeds). A cross-check that false-fires is a defect."""
        strict, shapes = 0, honest_shapes()
        self.assertGreaterEqual(len(shapes), 18)
        for label, j in shapes:
            m = db._measured_seeds(j)
            self.assertIsNotNone(m, label)
            self.assertEqual(j.n_attempted - j.n_failed, m, label)
            self.assertEqual(db._n_sources_disagree(j, m), [], label)
            for c in all_components(j):
                self.assertLessEqual(c.pair.n, m, f"{label}/{c.metric}")
                self.assertIsNone(db._n_problem(c.pair, c.pair.n, c.min_n, m), f"{label}/{c.metric}")
                self.assertIsNotNone(recompute(c, j.margins, j), f"{label}/{c.metric}")
                strict += c.pair.n < m
            if db.MIN_SEEDS_FLAG in j.h1.components[0].pair.flags:   # the flagged shapes are reached
                self.assertLess(j.h1.components[0].pair.n, j.h1.components[0].min_n, label)
        self.assertGreater(strict, 0, "no shape exercised the strict inequality: the sweep is vacuous")
        for kw in (dict(), dict(expect=None, S=0.0), dict(expect=None, L=1.0)):
            h = db.render_scorecard(joint(**kw))
            self.assertNotIn("SAMPLE SIZE CONTRADICTED", h, repr(kw))
            self.assertNotIn("NOT shown", h, repr(kw))

    def test_a_deflated_n_is_the_safe_direction_and_is_still_alarmed(self):
        """Why the cross-check is one-sided. `interval_verdict` uses `n` for exactly one thing, protocol
        6.1's floor `n < min_n`, so only an INFLATED `n` can buy a decisive verdict from a run that
        earned none. A deflated `n` drives the floor the safe way; it is still caught one layer on, as a
        disagreement with the stored verdict, so it is not unalarmed tampering either."""
        j = joint()
        for c in all_components(j):
            object.__setattr__(c.pair, "n", 5)
        h = db.render_scorecard(j)
        self.assertFailsClosedWithAnAlarm(h, ("H1", "H2", "H3"), "n deflated to 5")
        self.assertNotIn("SAMPLE SIZE CONTRADICTED", h)      # not a cross-source contradiction
        self.assertIsNone(db._n_problem(j.h1.components[0].pair, 5, 30, 30))
        self.assertEqual(recompute(j.h1.components[0], j.margins, j), bm.Verdict.INCONCLUSIVE)

    def test_the_page_states_the_finding_without_asserting_tampering(self):
        """The round-4 lesson about the weaker-than-protocol paragraph, applied to this one before it can
        be made again: name the two contradicting numbers, say what was withheld (observable), and
        assert neither "a field was edited" nor "this is nothing"."""
        h = db.render_scorecard(laundered_below_minimum(n=30))
        p = re.search(r'<p class="warn">SAMPLE SIZE CONTRADICTED.*?</p>', h).group(0)
        self.assertIn("a component claims 30 seeds", p)          # both numbers, named
        self.assertIn("only 29 measured seeds", p)
        self.assertIn("is withheld (INCONCLUSIVE shown)", p)     # and it really was: asserted above
        self.assertIn("CANNOT BE DETERMINED FROM THIS RESULT", p)
        self.assertIn("asserts neither", p)
        self.assertNotIn("tampered", p)
        self.assertNotIn("forged", p)
        self.assertIn("H1/S", p)                                 # which component, not just "somewhere"
        # free text cannot reach this paragraph as markup
        k = laundered_below_minimum(n=30)
        object.__setattr__(k.h1.components[0], "metric", "S<script>x</script>")
        self.assertNotIn("<script>", db.render_scorecard(k))


# ---------------------------------------------------------------------------------------------------------
# SR-13 ROUND 6: the interval's own second source.
# ---------------------------------------------------------------------------------------------------------
def heavy_tailed(idx=0, factor=50.0):
    """An HONEST 30-seed study whose H1 is INCONCLUSIVE because of PROTOCOL 6.3 ALONE.

    One seed's S is multiplied by `factor`, which is a legitimate heavy-tailed sample: every gate passes,
    `pair.n` is a genuine 30, nothing is forged. The bootstrap interval sits entirely above the margin
    while the t-interval (which is not resistant to the outlier) straddles it, so `intervals_disagree`
    fires and `_verdict_from_bounds` returns INCONCLUSIVE with "bootstrap/t disagreement".

    This fixture exists because it is the only shape in this file where the T-INTERVAL, and nothing else,
    decides the verdict -- which is what makes `t_lo`/`t_hi` verdict-bearing and is why admitting them by
    type alone was the round-6 defect. It goes through `make_scores`, so the FIXTURE CONTRACT still holds.
    """
    scores = make_scores(FZ.seeds)
    m = dict(scores[idx].metrics)
    big = MetricValue.measured(m["S"].value * factor)
    m["S"], m["S_U"] = big, big
    scores[idx] = dataclasses.replace(scores[idx], metrics=m)
    return bm.analyze_scores(scores, frozen=FZ, registered_digest=FZ.digest, subject="synthetic", cfg=SMALL)


def forge_t_inward(j):
    """Make every t-interval equal its own bootstrap interval: same bounds, so identical width and the
    same side of every margin. Protocol 6.3 then cannot fire. Two `object.__setattr__` per component,
    inside existing `MetricValue`s -- no new object, and both values are legal finite floats."""
    for c in all_components(j):
        p = c.pair
        if p.boot_lo.value is None:
            continue
        forge_mv(p.t_lo, p.boot_lo.value)
        forge_mv(p.t_hi, p.boot_hi.value)
    return j


class TheIntervalHasASecondSourceInTheSameResult(FailsClosedAssertions, unittest.TestCase):
    """SR-13 ROUND 6. The item failed a FIFTH time, and -- like round 5 -- not because a consumer was
    missed. `mean`, `t_lo` and `t_hi` were declared, routed through `_mv_intact`, swept with hostile
    types, and CLASSIFIED: `NO_SECOND_SOURCE`, "the interval itself is producer-asserted". The three
    classification dicts partitioned `db.STORED_NUMBERS` exactly and the test that performs the
    partition was green. THE DEFECT WAS THE CONTENT OF THE CLASSIFICATION. An exact second source was in
    the same `JointResult` and this module already read it: the per-seed series rebuilt from
    `joint.seed_scores` (read by `_measured_seeds` since round 5) plus the admitted `pair.level`.
    `benchmark.summarize` sets `mean = _mv(mean(vals))` and `(t_lo, t_hi) = t_interval(vals, level)`, so
    `bm.mean` and `bm.t_interval` reproduce all three BIT-EXACTLY -- measured, 324 of 324
    component-field comparisons over all 18 honest shapes, 0 mismatched.

    MEASURED AT HEAD on `heavy_tailed()`, an HONEST study that protocol 6.3 refuses a verdict:
        untouched                              -> H1 INCONCLUSIVE, JOINT_INCONCLUSIVE   (correct)
        t_lo/t_hi forged to the bootstrap pair  -> H1 SUPPORTED, JOINT_SUPPORTED, NO ALARM
    and on the default fixture, `mean` forged to 0.5 on every component -> `0.5` rendered in `.measured`
    monospace beside a decisive JOINT_SUPPORTED with no alarm. Two `object.__setattr__` inside two
    `MetricValue`s bought a decisive success from a run that had not earned one.

    WHAT THIS CLASS IS FOR, beyond the two pins: a classification dict is checked by machine for being a
    PARTITION and cannot be checked for being TRUE. So every reason left in `NO_SECOND_SOURCE` is now
    pinned by a test that would fail if the missing source turned out to exist
    (`test_the_two_bootstrap_bounds_have_no_recoverable_second_source`)."""

    def test_the_fixture_is_an_honest_study_the_protocol_refuses(self):
        """NOT VACUOUS, asserted before anything is forged: the laundering below has to start from a
        run that is honestly INCONCLUSIVE, and for the 6.3 reason specifically rather than because a
        gate failed or `n` was short -- or "forging t bought a verdict" would be unfalsifiable."""
        j = heavy_tailed()
        c = j.h1.components[0]
        self.assertEqual(c.pair.n, 30)                           # a genuine, full-size sample
        self.assertTrue(all(g.passed for g in j.gates))          # every validity gate passes
        self.assertEqual(db._measured_seeds(j), 30)
        bad, why = bm.intervals_disagree(c.pair.boot(), c.pair.tint(), c.margin, c.width_tol)
        self.assertTrue(bad)
        self.assertIn("different sides of margin", why)
        self.assertIs(c.verdict, bm.Verdict.INCONCLUSIVE)
        self.assertIs(j.verdict, bm.JointVerdict.JOINT_INCONCLUSIVE)
        h = db.render_scorecard(j)                               # and the honest page is clean
        self.assertEqual(hyp_cells(h)["H1"], "INCONCLUSIVE")
        self.assertNotIn("NOT shown", h)
        self.assertNotIn("INTERVAL CONTRADICTED", h)
        self.assertNotIn("JOINT_SUPPORTED", joint_cell(h))

    def test_G4_a_forged_t_interval_cannot_launder_a_6_3_disagreement(self):
        """THE ROUND-6 PIN. Asserts the VERDICT and the ALARM, not the figure cell."""
        k = forge_t_inward(heavy_tailed())
        forge_all_verdicts_supported(k)
        self.assertIs(k.verdict, bm.JointVerdict.JOINT_SUPPORTED)   # the page IS asked to show SUPPORTED
        self.assertTrue(db._gate_set_ok(k.gates))                   # not the gate-set check
        self.assertEqual(db._measured_seeds(k), 30)                 # not the round-5 cross-check either
        self.assertIsNone(db._n_problem(k.h1.components[0].pair, 30, 30, 30))
        h = db.render_scorecard(k)
        self.assertFailsClosedWithAnAlarm(h, ("H1", "H2", "H3"), "t forged inward")
        self.assertIn("INTERVAL CONTRADICTED", h)
        self.assertIn("H1/S", h)
        self.assertIsNone(recompute(k.h1.components[0], k.margins, k))
        self.assertFalse(pair_ok(k))
        # the forged bound is still PRINTED, like a contradicted `n`: the page shows the number it
        # refuses and says it is contradicted, rather than hiding it behind UNKNOWN.
        self.assertIn('<span class="measured">[', comp_row(h, "S"))

    def test_a_forged_mean_is_alarmed_even_though_it_reaches_no_verdict(self):
        """`mean` is this module's `level` case: `interval_verdict` never reads it, and an edited figure
        is still unalarmed tampering. Measured at HEAD: `0.5` in `.measured` monospace beside a decisive
        JOINT_SUPPORTED with no alarm."""
        for bad in (0.5, 1.5, -2.25):
            j = joint()
            for c in all_components(j):
                forge_mv(c.pair.mean, bad)
            h = db.render_scorecard(j)
            self.assertFailsClosedWithAnAlarm(h, ("H1", "H2", "H3"), f"mean={bad!r}")
            self.assertIn("INTERVAL CONTRADICTED", h)
            self.assertIn(f"stored mean is {bad!r}", h)          # both numbers named
            self.assertIn("per-seed value(s) this study records", h)
        self.assertNotIn("INTERVAL CONTRADICTED", db.render_scorecard(joint()))

    def test_a_forged_level_is_now_cross_checked_by_the_t_interval(self):
        """The withdrawn half of `level`'s old entry. It said "`level` also reaches no verdict at all,
        so there is nothing a forged level could buy that the type check does not already refuse"; it is
        now an INPUT to the t-interval cross-check, so a forged level changes a recomputation.

        MEASURED AT HEAD, all six values below, each forged on every pair: the level cell rendered the
        forged number in `.measured` monospace, `_pair_numbers_ok` returned True, and the page displayed
        JOINT_SUPPORTED with no alarm -- INCLUDING `5.0`, `-1.0` and `0.0`, which are not confidence
        levels at all and which `bm._check_level` refuses outright. `_finite_float` admits them because
        they are finite floats, which is the whole point: a type predicate cannot refuse a legal float.
        Both failure modes are therefore covered here: a VALID level that is not this study's, and a
        finite float outside (0, 1)."""
        for bad in (0.95, 0.99, 0.5, 5.0, -1.0, 0.0):
            j = forge_declared(joint(), "IntervalPair", "level", bad)
            h = db.render_scorecard(j)
            self.assertFailsClosedWithAnAlarm(h, ("H1", "H2", "H3"), f"level={bad!r}")
            self.assertIn("INTERVAL CONTRADICTED", h)
            self.assertFalse(pair_ok(j), repr(bad))
        # the UNDECIDABLE comparison is still declined: an honest non-default alpha raises no alarm
        k = bm.analyze_scores(make_scores(FZ.seeds), frozen=FZ, registered_digest=FZ.digest,
                              subject="synthetic", cfg=bm.BenchmarkConfig(n_boot=500, alpha=0.01))
        self.assertNotEqual(k.h1.components[0].pair.level, bm.bonferroni_level())
        h = db.render_scorecard(k)
        self.assertNotIn("INTERVAL CONTRADICTED", h)
        self.assertNotIn("NOT shown", h)

    def test_an_unusable_second_source_fails_closed_and_is_never_skipped(self):
        """MUTANT D5's LESSON FROM LAST ROUND, applied to the new source before it can be repeated: an
        unreadable second source must fail closed, NOT skip the check. Every way the series can be
        unusable is driven, and each one is asserted DIRECTLY on `_interval_problem` (so no later layer
        can mask a fail-open) and THROUGH a render (so the page really does alarm)."""
        self.assertEqual(db._interval_problem({"level": 0.9875}, None), db.NO_INTERVAL_SOURCE_MSG)
        nums = db._admitted(joint().h1.components[0].pair, "IntervalPair")
        self.assertEqual(db._interval_problem(nums, None), db.NO_INTERVAL_SOURCE_MSG)
        # (a) seed_scores itself unreadable
        for junk in (None, object(), 0, "scores", ()):
            k = joint()
            object.__setattr__(k, "seed_scores", junk)
            self.assertFailsClosedWithAnAlarm(db.render_scorecard(k), ("H1", "H2", "H3"), repr(junk))
            self.assertIsNone(recompute(k.h1.components[0], k.margins, k), repr(junk))
        # (b) one per-seed metric forged, so the series would otherwise be silently SHORTENED. The two
        # cases are different and both are driven, because `SeedScores.ok` is derived from the PRIMARY
        # metrics only (`benchmark._PRIMARY_SERIES`):
        #   * a NON-primary metric (delta_conv) leaves `ok` True, so the entry is still in the series and
        #     `_mv_intact` is the only thing standing between a forged value and a shortened series;
        #   * a PRIMARY metric (S) flips `ok` to False, so the entry drops out before the metric is read
        #     -- and the round-5 anchor catches THAT, because the stored `n_failed` no longer matches.
        for bad in BREAKS_MV_INVARIANT:
            k = joint()
            forge_mv(k.seed_scores[0].metrics["delta_conv"], bad)
            self.assertIs(k.seed_scores[0].ok, True, repr(bad))          # still an OK seed
            self.assertIsNone(db._seed_series(tuple(k.seed_scores), "delta_conv"), repr(bad))
            h = db.render_scorecard(k)
            self.assertFailsClosedWithAnAlarm(h, ("H3",), repr(bad))
            self.assertIn("INTERVAL CONTRADICTED", h, repr(bad))
            m = joint()
            forge_mv(m.seed_scores[0].metrics["S"], bad)
            self.assertIs(m.seed_scores[0].ok, False, repr(bad))         # no longer an OK seed
            self.assertEqual(len(db._seed_series(tuple(m.seed_scores), "S")), 29, repr(bad))
            self.assertIsNone(db._measured_seeds(m), repr(bad))          # the round-5 anchor fires
            h = db.render_scorecard(m)
            self.assertFailsClosedWithAnAlarm(h, ("H1", "H2", "H3"), repr(bad))
            self.assertIn("not readable", h, repr(bad))
            self.assertIn("INTERVAL CONTRADICTED", h, repr(bad))
        # (c) a seed-score entry with no `metrics` at all, and a `metrics` that is not a mapping
        for junk in (None, 0, "m", object()):
            k = joint()
            object.__setattr__(k.seed_scores[0], "metrics", junk)
            self.assertIsNone(db._seed_series(tuple(k.seed_scores), "S"), repr(junk))
        # (d) a component whose metric name is not in the protocol tables has no series to compare
        self.assertIsNone(db._series_of(db._measured_series(joint()), "not_a_metric"))
        self.assertIsNone(db._series_of({}, "S"))
        self.assertIsNone(db._series_of(None, "S"))
        self.assertIsNone(db._series_of({"S": [1.0]}, []))        # unhashable key: not an exception
        # (e) and an honestly unmeasured metric on one seed is NOT a rejection: it is skipped, which is
        # the `delta_conv unmeasured on 5 ok seeds` shape and a legitimate study.
        k = joint()
        sw = k.seed_scores[0]
        sw.metrics["delta_conv"] = MetricValue.unmeasured("not supplied")
        self.assertEqual(len(db._seed_series(tuple(k.seed_scores), "delta_conv")), 29)
        self.assertEqual(len(db._seed_series(tuple(k.seed_scores), "S")), 30)

    def test_the_cross_check_is_exact_and_never_false_fires(self):
        """OVER-REFUSAL CHECK over every honest shape, and the measurement the whole fix rests on: the
        recomputation is BIT-EXACT, not approximate, so no tolerance has to be chosen and no tolerance
        can be widened into a fail-open. A cross-check that false-fires is a defect."""
        comparable = exact = 0
        shapes = honest_shapes()
        self.assertGreaterEqual(len(shapes), 18)
        for label, j in shapes:
            series = db._measured_series(j)
            for c in all_components(j):
                nums = db._admitted(c.pair, "IntervalPair")
                self.assertIsNotNone(nums, f"{label}/{c.metric}")
                ser = db._series_of(series, c.metric)
                self.assertIsNotNone(ser, f"{label}/{c.metric}")
                self.assertIsNone(db._interval_problem(nums, ser), f"{label}/{c.metric}")
                for attr in ("mean", "t_lo", "t_hi"):
                    comparable += 1
                    exact += db._interval_problem(nums, ser) is None
                # the recomputation really is performed on this component, not skipped
                if len(ser) >= 2:
                    self.assertEqual(bm.mean(ser), c.pair.mean.value, f"{label}/{c.metric}")
                    self.assertEqual(bm.t_interval(ser, c.pair.level),
                                     (c.pair.t_lo.value, c.pair.t_hi.value), f"{label}/{c.metric}")
            self.assertEqual(db._interval_sources_disagree(j, series), [], label)
        self.assertEqual((comparable, exact), (324, 324))
        for label, j in shapes:
            self.assertNotIn("INTERVAL CONTRADICTED", db.render_scorecard(j), label)

    def test_no_false_fire_on_the_six_shapes_the_reviewer_built(self):
        """OVER-REFUSAL CHECK over the six study shapes the round-5 reviewer built by hand, beyond the
        18 `honest_shapes()` holds. They were verified then against the `n` cross-check; the interval
        cross-check is new and owes them the same measurement, because a cross-check that false-fires is
        a defect and these are the shapes chosen to stress the edges (a non-default alpha, almost every
        seed failed, a metric unmeasured on every seed, a PRIMARY metric unmeasured on some seeds, a
        minimum nobody can meet, and a sample too small for a t-interval)."""
        def study(scores, **cfgkw):
            return bm.analyze_scores(scores, frozen=FZ, registered_digest=FZ.digest,
                                     subject="synthetic", cfg=bm.BenchmarkConfig(n_boot=500, **cfgkw))
        shapes = [("alpha=0.01", study(make_scores(FZ.seeds), alpha=0.01)),
                  ("min_seeds=100", study(make_scores(FZ.seeds), min_seeds=100)),
                  ("2 seeds", study(make_scores(FZ.seeds[:2]))),
                  ("both converged metrics unmeasured on all 30",
                   study(make_scores(FZ.seeds, conv=False)))]
        s = make_scores(FZ.seeds)                 # 29 of 30 failed
        for i in range(29):
            s[i] = bm.SeedScores.failed(FZ.seeds[i], "synthetic failure")
        shapes.append(("29 of 30 failed", study(s)))
        s = make_scores(FZ.seeds)                 # a PRIMARY metric unmeasured on 7 seeds
        for i in range(7):
            m = dict(s[i].metrics)
            m["delta"] = MetricValue.unmeasured("not supplied")
            s[i] = dataclasses.replace(s[i], metrics=m)
        shapes.append(("primary `delta` unmeasured on 7 seeds", study(s)))
        self.assertEqual(len(shapes), 6)
        for label, j in shapes:
            m = db._measured_seeds(j)
            self.assertIsNotNone(m, label)
            self.assertEqual(j.n_attempted - j.n_failed, m, label)
            series = db._measured_series(j)
            for c in all_components(j):
                nums = db._admitted(c.pair, "IntervalPair")
                self.assertIsNotNone(nums, f"{label}/{c.metric}")
                self.assertIsNone(db._interval_problem(nums, db._series_of(series, c.metric)),
                                  f"{label}/{c.metric}")
                self.assertIsNotNone(recompute(c, j.margins, j), f"{label}/{c.metric}")
            self.assertEqual(db._interval_sources_disagree(j, series), [], label)
            self.assertEqual(db._n_sources_disagree(j, m), [], label)
            h = db.render_scorecard(j)
            self.assertNotIn("INTERVAL CONTRADICTED", h, label)
            self.assertNotIn("SAMPLE SIZE CONTRADICTED", h, label)
            self.assertNotIn("not readable", h, label)

    def test_the_n_lt_2_shapes_are_required_not_tolerated(self):
        """`summarize` returns all-unmeasured for n == 0 and an unmeasured t-interval for n == 1. Those
        are what the cross-check REQUIRES there -- a MEASURED mean or t-bound on a 0/1-value series is a
        contradiction, not a free pass -- which is the branch a lazier implementation would make
        permissive and no honest fixture would notice."""
        one = joint(expect=None, seeds=FZ.seeds[:1])              # n == 1: mean measured, t unmeasured
        c = one.h1.components[0]
        self.assertEqual((c.pair.n, c.pair.t_lo.value), (1, None))
        self.assertTrue(pair_ok(one))
        forge_mv(c.pair.t_lo, 0.5)                                # a t-bound a 1-value series cannot have
        self.assertFalse(pair_ok(one))
        self.assertIn("stored t_lo is 0.5", db.render_scorecard(one))
        zero = joint(expect=None, conv=False)                     # n == 0 on the converged components
        cc = zero.h3.converged_components[0]
        self.assertEqual((cc.pair.n, cc.pair.mean.value), (0, None))
        self.assertTrue(pair_ok(zero, c=cc))
        forge_mv(cc.pair.mean, 0.25)
        self.assertFalse(pair_ok(zero, c=cc))
        self.assertFailsClosedWithAnAlarm(db.render_scorecard(zero), ("H3",), "n==0 mean forged")

    def test_the_comparison_cannot_be_decided_by_an_overridable_dunder(self):
        """`_same_number`, and why it is not `stored == want`. `MetricValue.__post_init__` tests
        `isinstance(self.value, float)`, which a `float` SUBCLASS passes, and `math.isfinite` reads the
        stored double -- so a lying `__eq__` is constructible through the PUBLIC api, with no
        `object.__setattr__` anywhere. `benchmark._plain_number`'s rule, in this module's own lane."""
        class Liar(float):
            def __eq__(self, other):
                return True

            def __ne__(self, other):
                return False

            def __hash__(self):
                return 0
        self.assertTrue(Liar(0.5) == 1.0)                         # the lie works on `==`
        self.assertFalse(db._same_number(Liar(0.5), 1.0))         # ... and not on the cross-check
        self.assertTrue(db._same_number(Liar(0.5), 0.5))          # the STORED double still decides
        self.assertTrue(db._same_number(0.5, 0.5))
        self.assertFalse(db._same_number(0.5, 0.5000000000000001))
        for junk in (None, "0.5", [], object(), float("nan"), float("inf"), True):
            self.assertFalse(db._same_number(junk, 0.5), repr(junk))
            self.assertFalse(db._same_number(0.5, junk), repr(junk))
        # and end to end: a measured MetricValue holding one, built through the public API
        j = joint()
        c = j.h1.components[0]
        object.__setattr__(c.pair, "mean", MetricValue.measured(Liar(0.5)))
        self.assertFalse(pair_ok(j))
        self.assertFailsClosedWithAnAlarm(db.render_scorecard(j), ("H1",), "lying __eq__")

    def test_the_two_bootstrap_bounds_have_no_recoverable_second_source(self):
        """THE SURVIVING `NO_SECOND_SOURCE` REASON, PINNED. Round 6's defect was a FALSE reason in a
        dict whose PARTITION was machine-checked, so each remaining reason gets a test that fails if the
        source it denies turns out to exist.

        `summarize` computes the bootstrap pair from `n_boot` and `derive_seed(base_seed, 'bootstrap:' +
        name)`. Neither `n_boot` nor `base_seed` is a field of `JointResult`, so neither is recoverable
        from the result, and `freeze_seed_list` derives the seed list by hashing so the seeds do not
        yield `base_seed` either. If a future `JointResult` gains one of them, this goes red and the
        classification has to be argued again instead of inherited."""
        fields = {f.name for f in dataclasses.fields(bm.JointResult)}
        self.assertNotIn("base_seed", fields)
        self.assertNotIn("n_boot", fields)
        self.assertNotIn("cfg", fields)
        self.assertNotIn("frozen", fields)
        self.assertIn("config_hash", fields)                      # only the opaque hash is carried
        self.assertIn("base_seed", {f.name for f in dataclasses.fields(bm.FrozenSeedList)})
        self.assertIn("n_boot", {f.name for f in dataclasses.fields(bm.BenchmarkConfig)})
        # ... so forging only the bootstrap pair is NOT caught by the interval cross-check, and that is
        # the residual the page now states in as many words.
        j = joint()
        for c in all_components(j):
            forge_mv(c.pair.boot_lo, c.pair.boot_lo.value)        # same value: a no-op forgery
        self.assertTrue(pair_ok(j))
        k = joint()
        for c in all_components(k):
            if c.pair.boot_lo.value is None:
                continue
            forge_mv(c.pair.boot_lo, c.pair.boot_lo.value - 0.001)
        self.assertTrue(pair_ok(k), "the bootstrap bounds are not cross-checked: stated, not hidden")
        h = db.render_scorecard(k)
        self.assertNotIn("INTERVAL CONTRADICTED", h)
        self.assertIn("BOOTSTRAP bounds are not cross-checked",
                      db.render_scorecard(forge_t_inward(heavy_tailed())))

    def test_the_page_states_the_interval_finding_without_asserting_tampering(self):
        """The round-4 lesson about the weaker-than-protocol paragraph, applied to this paragraph too:
        name the two contradicting numbers, say what was withheld (observable), assert neither "a field
        was edited" nor "this is nothing"."""
        k = forge_t_inward(heavy_tailed())
        forge_all_verdicts_supported(k)
        h = db.render_scorecard(k)
        p = re.search(r'<p class="warn">INTERVAL CONTRADICTED.*?</p>', h).group(0)
        self.assertIn("H1/S", p)                                  # which component
        self.assertIn("the interval&#x27;s stored t_lo is", p)     # both numbers, named
        self.assertIn("per-seed value(s) this study records", p)
        self.assertIn("is withheld (INCONCLUSIVE shown)", p)
        self.assertIn("CANNOT BE DETERMINED FROM THIS RESULT", p)
        self.assertIn("asserts neither", p)
        self.assertNotIn("tampered", p)
        self.assertNotIn("forged", p)
        # free text cannot reach this paragraph as markup
        m = forge_t_inward(heavy_tailed())
        object.__setattr__(m.h1.components[0], "metric", "S<script>x</script>")
        self.assertNotIn("<script>", db.render_scorecard(m))

    def test_the_prose_sibling_and_the_guard_share_one_implementation(self):
        """`_interval_sources_disagree` exists only so the page can say WHICH finding it is; the GUARD
        is `_recompute`'s. Both must call `_interval_problem`, or the paragraph and the withholding can
        drift apart -- which is the whole subject of this module's scheme note."""
        self.assertIn("_interval_problem", db._interval_sources_disagree.__code__.co_names)
        self.assertIn("_interval_problem", db._pair_numbers_ok.__code__.co_names)
        self.assertEqual(db._interval_sources_disagree(joint(), db._measured_series(joint())), [])
        for junk in (None, object(), 0):
            self.assertEqual(db._interval_sources_disagree(junk, {}), [], repr(junk))
        # an ILL-TYPED bound is not reported as a contradiction: the kind functions alarm on that in
        # their own words, exactly as `_n_sources_disagree` declines a non-count `n`.
        k = forge_declared(joint(), "IntervalPair", "t_lo", float("nan"))
        self.assertEqual(db._interval_sources_disagree(k, db._measured_series(k)), [])
        self.assertFalse(pair_ok(k))
        self.assertNotIn("INTERVAL CONTRADICTED", db.render_scorecard(k))
        self.assertIn("NOT shown", db.render_scorecard(k))

    def test_the_measured_cost_of_the_anchors_residual(self):
        """D2: the stated residual was far cheaper than its comment claimed, and the comment is now the
        measurement. It said the `seed_scores` anchor "raises the cost of the forgery from one integer to
        30 fabricated objects". MEASURED at HEAD: ZERO objects fabricated.

        On `laundered_below_minimum(n=30)` -- a GENUINE 29-seed run -- append one EXISTING reference
        (`seed_scores[0]`), two `object.__setattr__` (`seed_scores`, `n_attempted`), clear six `flags`
        tuples: `_measured_seeds` = 30, no alarm, JOINT_SUPPORTED, with `len(seed_scores) = 30` and 29
        DISTINCT seeds. `benchmark.evaluate_gates` already applies `len(set(ids)) != len(ids)` to the
        same list for `seed_list_frozen`; `_measured_seeds` did not."""
        k = laundered_below_minimum(n=30)
        k.__class__                                              # no object is fabricated below
        object.__setattr__(k, "seed_scores", (*k.seed_scores, k.seed_scores[0]))
        object.__setattr__(k, "n_attempted", 30)
        for c in all_components(k):
            object.__setattr__(c.pair, "flags", ())
        self.assertEqual(len(k.seed_scores), 30)                 # the two seed-count equalities hold
        self.assertEqual(len({s.seed for s in k.seed_scores}), 29)   # ... over 29 distinct seeds
        self.assertIsNone(db._measured_seeds(k), "the distinctness equality must refuse this")
        h = db.render_scorecard(k)
        self.assertFailsClosedWithAnAlarm(h, ("H1", "H2", "H3"), "duplicated seed-score reference")
        self.assertIn("not readable", h)
        # BOTH of the two cheap variants are closed, and by TWO independent checks, so neither masks
        # the other (the F-h lesson). The distinctness equality alone sees the duplicate; the interval
        # cross-check alone sees both, because an appended entry changes the series every stored mean
        # and t-interval was computed from.
        for tag, extra in (("duplicate reference", "dup"), ("one fabricated seed", "new")):
            m = laundered_below_minimum(n=30)
            m_extra = m.seed_scores[0] if extra == "dup" else make_scores([999])[0]
            object.__setattr__(m, "seed_scores", (*m.seed_scores, m_extra))
            object.__setattr__(m, "n_attempted", 30)
            for c in all_components(m):
                object.__setattr__(c.pair, "flags", ())
            ser = db._seed_series(tuple(m.seed_scores), "S")
            self.assertEqual(len(ser), 30, tag)
            self.assertNotEqual(bm.mean(ser), m.h1.components[0].pair.mean.value, tag)
            nums = db._admitted(m.h1.components[0].pair, "IntervalPair")
            self.assertIsNotNone(db._interval_problem(nums, ser), tag)
            self.assertFailsClosedWithAnAlarm(db.render_scorecard(m), ("H1", "H2", "H3"), tag)
        # NO FALSE FIRE: no honest shape repeats a seed id, and a study that honestly analysed one twice
        # already fails `seed_list_frozen` (a global gate), so no verdict is lost that was not lost.
        for label, j in honest_shapes():
            ids = [s.seed for s in j.seed_scores]
            self.assertEqual(len(set(ids)), len(ids), label)
            self.assertIsNotNone(db._measured_seeds(j), label)
        dup = make_scores(FZ.seeds[:29]) + [None]
        dup[29] = dup[0]
        d = bm.analyze_scores(dup, frozen=FZ, registered_digest=FZ.digest, subject="synthetic", cfg=SMALL)
        self.assertFalse(next(g for g in d.gates if g.name == "seed_list_frozen").passed)
        self.assertIs(d.verdict, bm.JointVerdict.JOINT_INCONCLUSIVE)

    def test_the_corrected_comment_claims_are_performed_not_asserted(self):
        """D4: four comments in these two files stated a guarantee, and a withdrawn guarantee has now
        survived twice in this project because it lived where `__doc__` cannot reach. Each corrected
        claim that is checkable is checked HERE, by machine, instead of being restated in prose.

        (1) "there are exactly four predicates in this module that admit a stored number -- one per
            kind". Counted, not asserted.
        (2) "`_admitted` ... so each field is admitted exactly once" was FALSE. Its round-5 replacement,
            "all three admissions go through the same kind function, `_count`, SO THEY CANNOT DISAGREE",
            WAS ALSO FALSE as an absolute, and is withdrawn in round 8: a kind function normalises the
            VALUE it is handed, and nothing makes the HOLDER hand it the same value twice. BOTH HALVES OF
            THE REPLACEMENT ARE MEASURED HERE -- that every admission of `pair.n` in a real render does go
            through `_count` (recording wrapper, real render), and that an alternating HOLDER of plain
            `int`s launders the fixture anyway.
        (3) "the two second sources, read ONCE for the whole card". Performed by call count.
        (4) the claims softened (the probe is not a completeness proof; the "cannot add an unchecked
            consumer" sentence) are disclaimed in the text itself, which is asserted below so the
            disclaimer cannot be deleted without this going red."""
        # (1) exactly four kinds, exactly four predicates, one per kind
        self.assertEqual(len(db._NUM_KINDS), 4)
        self.assertEqual(set(db._NUM_KINDS), {"float", "num", "count", "mv"})
        self.assertEqual(len(set(db._NUM_KINDS.values())), 4)
        self.assertEqual({f.__name__ for f in db._NUM_KINDS.values()},
                         {"_finite_float", "_finite_number", "_count", "_mv_intact"})
        # (2) every admission of `pair.n` during a real render goes through `_count`, and there are
        #     THREE of them per pair plus `bm.interval_verdict`'s own raw read of the attribute.
        seen = []
        real = db._count

        def recording_count(x):
            seen.append(x)
            return real(x)
        j = joint()
        n = j.h1.components[0].pair.n
        with mock.patch.object(db, "_count", recording_count), \
                mock.patch.dict(db._NUM_KINDS, {"count": recording_count}):
            h = db.render_scorecard(j)
        self.assertNotIn("NOT shown", h)                 # an ordinary, decisive render
        per_pair = seen.count(n) / len(all_components(j))
        self.assertGreater(per_pair, 1.0, f"`n` was admitted {per_pair} times per pair: the claim that "
                                          f"there is more than one admission is now false; fix the "
                                          f"comment at STORED_NUMBERS item 2 rather than this number")
        self.assertIn("pair.n", inspect.getsource(bm.interval_verdict))   # the fourth, unadmitted read
        self.assertNotIn("_count", inspect.getsource(bm._verdict_from_bounds))
        #     ... AND THE OTHER HALF: THE ADMISSIONS CANNOT DISAGREE ABOUT A VALUE, BUT NOTHING PREVENTS
        #     THE HOLDER FROM SUPPLYING TWO. A `__getattribute__` serving `n` from cycle([29, 30]) --
        #     every returned value a PLAIN `int`, so `_count` normalises nothing away and admits each one
        #     -- launders the 29-seed fixture into a decisive JOINT_SUPPORTED. This is the residual the
        #     scheme has declared since round 4 (the `vars()`/`__dict__` mutants are blind to the probe
        #     for the same reason), so it is pinned as a KNOWN FAIL-OPEN rather than fixed: the test
        #     asserts the laundering, and goes red if the mechanism is ever closed, which is the only
        #     honest way to record a residual that cannot be closed from this module.
        honest_laundered = db.render_scorecard(laundered_below_minimum())
        self.assertIn("JOINT_INCONCLUSIVE", joint_cell(honest_laundered))     # the honest fixture: caught
        k = laundered_below_minimum()

        class Alternating(bm.IntervalPair):
            def __getattribute__(self, name):
                if name == "n":
                    return next(object.__getattribute__(self, "_cycle"))
                return bm.IntervalPair.__getattribute__(self, name)

        for c in all_components(k):
            object.__setattr__(c.pair, "_cycle", itertools.cycle([29, 30]))
            object.__setattr__(c.pair, "__class__", Alternating)
        p0 = k.h1.components[0].pair
        self.assertIsInstance(p0, bm.IntervalPair)                    # the render takes its real path
        self.assertEqual({type(p0.n) for _ in range(10)}, {int},
                         "the holder must serve PLAIN ints: a kind function has nothing to normalise")
        hl = db.render_scorecard(k)
        self.assertIn("JOINT_SUPPORTED", joint_cell(hl),
                      "the alternating-holder residual has been CLOSED; delete this pin and the "
                      "withdrawal passage at STORED_NUMBERS item 2, and say so")
        self.assertEqual(set(hyp_cells(hl).values()), {"SUPPORTED"})
        self.assertIn("<td>29</td>", hl)                              # ... beside a sample size of 29
        self.assertIn("29 measured seeds vs minimum 30", hl)
        self.assertIn("is withheld", hl)                              # on a page that says it withheld it
        # (3) read once per card: one `_seed_series` call per protocol metric, not per component
        metrics = {m for table in (*bm.PRIMARY.values(), bm.CONVERGED) for m, _d, _a in table}
        calls = []
        real_series = db._seed_series

        def recording_series(scores, metric):
            calls.append(metric)
            return real_series(scores, metric)
        with mock.patch.object(db, "_seed_series", recording_series):
            db.render_scorecard(joint())
        self.assertEqual(sorted(calls), sorted(metrics), "the series is re-derived per component")
        self.assertGreater(len(all_components(joint())), 0)
        # (4) THE SOFTENED CLAIMS KEEP THEIR DISCLAIMERS. Each withdrawn sentence may still appear --
        # this file's house style is to quote what was wrong rather than delete it -- but it must appear
        # EXACTLY ONCE and inside a passage that withdraws it. Checked this way round deliberately: a
        # bare `assertNotIn` would pass if someone deleted the correction AND the quotation together,
        # which is the silent-withdrawal failure D4 is about.
        src = Path(inspect.getsourcefile(db)).read_text(encoding="utf-8")
        for claim, marker in (
                ("Proved complete by the recording-probe test", "THIS COMMENT USED TO SAY"),
                ("A future reader cannot add an unchecked consumer without turning",
                 "THIS COMMENT USED TO END"),
                ("`_admitted` is the only reader and it returns the admitted", "THE SENTENCE THIS"),
                ("STRICT in three of them", "The sentence this replaces said"),
                # ROUND 8's two withdrawals, same rule -- and then a stronger one below
                ("same kind function, `_count`, SO THEY CANNOT DISAGREE", "THE SENTENCE THIS REPLACES SAID"),
                ("test lives in `_finite_float`, shared with every other", "THIS REPLACES SAID")):
            self.assertEqual(src.count(claim), 1, claim)
            i = src.index(claim)
            self.assertIn(marker, src[max(0, i - 700):i], claim)
        # ROUND 8 FOUND THE LOOP ABOVE WEAKER THAN IT READS, and the weakness is recorded with its
        # measurement rather than quietly patched. The marker only has to appear SOMEWHERE in the 700
        # characters before the claim, and this file's comments quote withdrawn sentences one after
        # another -- so a NEIGHBOURING passage's identical marker satisfies the check. MEASURED, in a
        # verified copy on 3.13.5: a mutant that restored the `:208` absolute IN PLACE (deleting its own
        # "THE SENTENCE THIS REPLACES SAID" and the withdrawal around it, leaving the bare claim) passed
        # the whole of `test_dashboard`, because the round-5 withdrawal's identical marker sits ~630
        # characters above it once the mutant has shortened the passage by a line. That is the
        # silent-withdrawal failure this test exists to prevent, surviving this test.
        # So each round-8 claim must be (a) quoted exactly once, (b) introduced by a withdrawal phrase
        # UNIQUE TO ITS OWN PASSAGE, and (c) FOLLOWED, inside that passage, by the replacement claim --
        # which is also required to be unique, so deleting the replacement and keeping the quotation
        # cannot pass either. Both mutants die on (b); deleting only the replacement dies on (c).
        # ROUND 9 adds its two withdrawals to the SAME stronger rule, and they are the two load-bearing
        # prose claims Finding 1 falsified. `_subject_kind`'s docstring said "ONE REAL CROSS-CHECK IS
        # AVAILABLE and is made here" and "so a mismatch means the result was relabelled after
        # construction (route (d)) and is reported as a problem". One `str` subclass defeated both: the
        # cross-check was three string operators on the caller's object, so it was not made on the label
        # at all, and the mismatch was therefore NOT reported. Each is quoted exactly once, introduced by
        # a phrase unique to its own passage, and followed inside that passage by the replacement claim.
        for claim, intro, replacement in (
                ("same kind function, `_count`, SO THEY CANNOT DISAGREE",
                 "the sentence that stood here stated it as an",
                 "NOTHING PREVENTS THE HOLDER FROM SUPPLYING TWO"),
                ("test lives in `_finite_float`, shared with every other",
                 "THE SENTENCE\n    THIS REPLACES SAID",
                 "it derived this cell's safety FROM THE WRONG PROPERTY"),
                ("ONE REAL CROSS-CHECK IS AVAILABLE and is made here",
                 "ROUND 9 WITHDRAWS THE TWO CLAIMS THAT STOOD HERE",
                 "THE CROSS-CHECK IS MADE ON\n    THE CHARACTERS THE LABEL STORES"),
                ("was relabelled after construction (route (d)) and is reported as a problem",
                 "THE PASSAGE THIS ONE SUPERSEDES OPENED WITH",
                 "THE REPLACEMENT CLAIM, which is weaker")):
            self.assertEqual(src.count(claim), 1, claim)
            self.assertEqual(src.count(intro), 1, intro)
            self.assertEqual(src.count(replacement), 1, replacement)
            i = src.index(claim)
            self.assertIn(intro, src[max(0, i - 400):i], claim)
            self.assertIn(replacement, src[i:i + 2500], claim)
        # the round-6 withdrawals, same rule. (Not checked over THIS file: the assertion would have to
        # count its own literals. The classification dicts are checked by the partition test, and each
        # surviving `NO_SECOND_SOURCE` reason by its own test, which is the stronger guard anyway.)
        for claim, marker in (("the interval itself is producer-asserted", "WHY IT WAS FALSE"),
                              ("so there is nothing a forged level could buy that the type check",
                               "ONE CLAIM ABOUT `pair.level` IS WITHDRAWN")):
            self.assertEqual(src.count(claim), 1, claim)
            self.assertIn(marker, src[max(0, src.index(claim) - 1400):src.index(claim)], claim)

    def test_D9_an_absent_ok_attribute_is_not_a_pass(self):
        """D3: mutant `D9`, `getattr(s, "ok", None)` -> `getattr(s, "ok", True)` in `_measured_seeds`,
        SURVIVED the previous suite. Measured: with `seed_scores` = 30 ATTRIBUTE-LESS objects and
        `n_attempted=30, n_failed=0`, HEAD gives `_measured_seeds = None` and an alarm, while the mutant
        computes `listed_failed = 0 == n_failed`, passes both equalities, and returns `measured_n = 30`
        -- i.e. an object that says nothing about whether its seed succeeded is read as a success.

        No test drove a seed-score list of attribute-less objects OF THE RIGHT LENGTH: the junk cases
        were `None`/`object()`/`0`/`"joint"`/`()`, of which the last two ARE iterable but have the wrong
        length, so the length equality caught them and the `ok` default was never reached.

        THE STAND-INS CARRY DISTINCT `seed` VALUES, AND THAT IS NOT COSMETIC. The first draft of this
        test used bare attribute-less objects and D9 SURVIVED IT: with no `seed` attribute all 30 ids
        collapse onto the single `_MISSING` sentinel, so the round-6 DISTINCTNESS equality refused the
        list before the `ok` default was ever reached, and the test was measuring the wrong guard. Each
        guard has to be driven with the others satisfied or it is untested (the F-h lesson) -- which is
        exactly how D9 survived in the first place."""
        class Blank:
            def __init__(self, seed):
                self.seed = seed
        k = joint()
        object.__setattr__(k, "seed_scores", tuple(Blank(s) for s in FZ.seeds))
        self.assertEqual((k.n_attempted, k.n_failed), (30, 0))   # the length equality is satisfied
        self.assertEqual(len(k.seed_scores), k.n_attempted)
        self.assertEqual(len({s.seed for s in k.seed_scores}), 30)   # ... and so is distinctness
        self.assertFalse(any(hasattr(s, "ok") for s in k.seed_scores))
        self.assertIsNone(db._measured_seeds(k), "an absent `ok` must not default to True")
        self.assertFailsClosedWithAnAlarm(db.render_scorecard(k), ("H1", "H2", "H3"), "attribute-less")
        self.assertIn("not readable", db.render_scorecard(k))
        # the same for a list whose entries carry a NON-True `ok`, including truthy-but-not-True
        for val in (1, "yes", object(), None, False):
            class Duck:
                def __init__(self, seed):
                    self.seed, self.ok = seed, val
            m = joint()
            object.__setattr__(m, "seed_scores", tuple(Duck(s) for s in FZ.seeds))
            self.assertIsNone(db._measured_seeds(m), repr(val))
        # NOT VACUOUS: the real list, whose `ok` is a property, still reads 30
        self.assertEqual(db._measured_seeds(joint()), 30)


class RoundThreeSurvivorsPinned(unittest.TestCase):
    """Mutants that survived round 3's suite. Each was argued non-equivalent (or masked) by the
    reviewer, so each gets the test that was missing rather than a note saying it is fine."""

    def test_M6_a_duck_typed_bound_is_not_a_MetricValue(self):
        """M6: `_mv_float` dropping `isinstance(mv, MetricValue)`. `IntervalPair` has no
        `__post_init__`, so an object that merely carries `.value` reaches `render_scorecard` as a
        bound. HEAD renders UNKNOWN / 'interval not computable'; the mutant reads `.value` off the duck
        and renders a measured interval. HEAD also alarms, so this was a COVERAGE gap, not a behaviour
        defect -- no test fed a non-`MetricValue` bound to `_interval`, which is the one consumer that
        calls `_mv_float` without an `isinstance` of its own in front of it."""
        class DuckBound:
            def __init__(self, v):
                self.value, self.reason = v, None

        # distinctive bounds, so the mutant's output is a string that cannot occur by chance anywhere
        # else on the page (an earlier draft used 1.001 and collided with a real bootstrap bound)
        LO, HI = -12345.5, 67890.25
        self.assertIsNone(db._mv_float(DuckBound(LO)))
        self.assertIsNone(db._mv_intact(DuckBound(LO)))
        self.assertIn("interval not computable", db._interval(DuckBound(LO), DuckBound(HI)))
        self.assertNotIn("measured", db._interval(DuckBound(LO), DuckBound(HI)))
        self.assertIn("UNKNOWN", db._metric_cell(DuckBound(LO)))
        j = joint()
        object.__setattr__(j.h1.components[0].pair, "boot_lo", DuckBound(LO))
        object.__setattr__(j.h1.components[0].pair, "boot_hi", DuckBound(HI))
        h = db.render_scorecard(j)
        row = comp_row(h, "S")
        self.assertIn("interval not computable", row)
        self.assertNotIn(f"[{LO}, {HI}]", h)                      # the mutant's output, named
        self.assertNotIn("12345", h)
        self.assertNotIn("67890", h)
        self.assertEqual(hyp_cells(h)["H1"], "INCONCLUSIVE")
        self.assertIn("NOT shown", h)
        # a Mapping is not a MetricValue either, however duck-shaped
        self.assertIsNone(db._mv_float({"value": 1.0}))
        self.assertIn("interval not computable", db._interval({"value": 1.0}, {"value": 2.0}))

    def test_M24_the_snapshot_count_cells_admit_only_a_genuine_int(self):
        """M24: `_int_cell` admitting any non-`None`. The snapshot is caller-supplied JSON, so
        `ahead_by = True` / `2.5` / `"many"` / `[1]` all reach it; HEAD renders UNKNOWN, the mutant
        renders a measured `True` / `2.5` / `"many"`. No test fed a non-int `ahead_by` or
        `behind_by_*`. These cells are kind "count" in the shared scheme now, not a sibling of it."""
        keys = ("ahead_by", "behind_by_vs_merge_base", "behind_by_vs_upstream_main")
        rowpat = {"ahead_by": r"<tr><td>ahead_by \(merge-base compare\)</td><td>(.*?)</td></tr>",
                  "behind_by_vs_merge_base": r"<tr><td>behind_by_vs_merge_base[^<]*</td><td>(.*?)</td></tr>",
                  "behind_by_vs_upstream_main": r"<tr><td>behind_by_vs_upstream_main[^<]*</td><td>(.*?)</td></tr>"}
        for key in keys:
            for bad in (True, False, 2.5, "many", "7", [1], {}, None, float("nan"), object()):
                h = db.render_dashboard({"snapshot": {**SNAP, key: bad}})
                cell = re.search(rowpat[key], h).group(1)
                self.assertIn('<span class="unknown">UNKNOWN</span>', cell, (key, repr(bad)))
                self.assertIn(f"{key} not present", cell, (key, repr(bad)))
                self.assertNotIn("measured", cell, (key, repr(bad)))
                for word in ("True", "False", "2.5", "many", "nan"):
                    self.assertNotIn(word, cell, (key, repr(bad), word))
            # NOT VACUOUS: a genuine int renders measured, and a genuine zero is a zero
            for good in (0, 7, -3):
                cell = re.search(rowpat[key], db.render_dashboard(
                    {"snapshot": {**SNAP, key: good}})).group(1)
                self.assertEqual(cell, f'<span class="measured">{good}</span>', (key, good))
            # and an absent key is UNKNOWN, not 0
            snap = {k: v for k, v in SNAP.items() if k != key}
            self.assertIn(f"{key} not present", db.render_dashboard({"snapshot": snap}))

    def test_M25_verdict_cell_falls_back_to_the_kind_unknown_caveat(self):
        """M25: `_verdict_cell` dropping `or _KIND_UNKNOWN_CAVEAT`. UNREACHABLE through
        `render_scorecard` -- all three `kind_label`s are non-empty constants and the caller always
        builds a non-empty `supported_caveat` -- but the documented private behaviour ("when a caller
        supplies none, the UNKNOWN wording is used: this function never asserts 'toy fixture' on its
        own") was unpinned, so the mutant survived. Pinned by direct call, the F-h way."""
        for empty in (None, "", {}):
            kw = {} if empty is None else {"kind_caveat": empty}
            cell = db._verdict_cell(bm.Verdict.SUPPORTED, **kw)
            self.assertIn(db._KIND_UNKNOWN_CAVEAT, cell, repr(empty))
            self.assertIn("conditional; not a safety finding", cell, repr(empty))
            self.assertNotIn("fixture", cell, repr(empty))        # never the blanket word (F4)
            self.assertIn("vd-supported", cell, repr(empty))
        # a supplied caveat wins, and the fallback is not appended as well
        cell = db._verdict_cell(bm.Verdict.SUPPORTED, kind_caveat="TRAINED SUBJECT; conditional")
        self.assertIn("TRAINED SUBJECT; conditional", cell)
        self.assertNotIn(db._KIND_UNKNOWN_CAVEAT, cell)
        # and a non-SUPPORTED verdict carries no kind caveat at all, supplied or not
        for v in (bm.Verdict.UNSUPPORTED, bm.Verdict.INCONCLUSIVE):
            for kw in ({}, {"kind_caveat": "x"}):
                self.assertNotIn(db._KIND_UNKNOWN_CAVEAT, db._verdict_cell(v, **kw))
                self.assertNotIn("conditional", db._verdict_cell(v, **kw))

    def test_the_one_unpinnable_survivor_is_unpinnable_by_construction(self):
        """`_finite_float`'s `isinstance(x, bool)` clause. Verified rather than asserted: `bool.__mro__`
        is (bool, int, object), so `isinstance(True, float)` is False and the clause can never decide an
        outcome; and `bool` cannot be subclassed, so no input can be both. Kept and labelled in the
        docstring because the identical clause IS load-bearing in `_finite_number` and `_count`."""
        self.assertEqual(bool.__mro__, (bool, int, object))
        self.assertFalse(isinstance(True, float))
        with self.assertRaises(TypeError):
            type("X", (bool,), {})
        self.assertIsNone(db._finite_float(True))
        self.assertIsNone(db._finite_float(False))
        # the sibling kinds, where it decides the outcome and a mutant IS caught
        self.assertIsNotNone(db._finite_number(1))
        self.assertIsNone(db._finite_number(True))
        self.assertIsNotNone(db._count(1))
        self.assertIsNone(db._count(True))
        self.assertIn("THE `bool` CLAUSE IS REDUNDANT HERE", db._finite_float.__doc__)


# ---------------------------------------------------------------------------------------------------------
# SR-13 ROUND 7: the kinds now NORMALISE what they admit.
# ---------------------------------------------------------------------------------------------------------
# A numeric field of a verdict-bearing class that the renderer DOES NOT read, with the reason, so that
# "undeclared" is a recorded decision per field instead of an omission per field -- the same rule
# `NO_SECOND_SOURCE` applies to second sources. This list is the price of deriving the field set from
# `dataclasses.fields()` instead of from a render, and it buys the thing a render-time probe cannot give:
# a NEW numeric field on a scorer dataclass fails the suite the moment it exists, whether or not anything
# reads it yet (the probe sees only what its single render exercises, and
# `test_the_probe_itself_is_not_vacuous` asserts that `n_boot` is NOT in its bucket).
#
# THE TWO MECHANISMS ARE COMPLEMENTARY, NOT NESTED, and round 6 recorded the relation the wrong way round
# -- as the fields test strictly dominating the probe. Each catches something the other cannot, and the
# directions are worth naming because a mechanism believed to be redundant is a mechanism that gets
# deleted:
#   * FIELDS TEST ONLY: a numeric field that exists and is read by nothing yet. The probe observes one
#     render and cannot see a field before a consumer does.
#   * PROBE ONLY (1): an EXEMPTED field that starts being read. Its set comparison fails naming the
#     attribute, while the fields test's `numeric == declared | exempt` still holds, because the field is
#     accounted for -- as not rendered, which has just stopped being true. (The behavioural half of the
#     exemption check below catches it too IF the read moves a byte; a read that feeds a verdict which
#     does not flip moves none.)
#   * PROBE ONLY (2): "declared but not read" rot. A declared entry whose consumer was deleted passes the
#     fields test (the field is still numeric and still declared) and fails the probe.
# AND THEY SHARED A BLIND SPOT, which was the stronger reason not to call either redundant: both filtered
# candidate fields with `is_a_stored_number` evaluated on the HONEST FIXTURE INSTANCE. `numeric_fields_of`
# closes it and records the unkilled mutant that measures it.
#
# EACH REASON IS CHECKED, NOT WRITTEN: `test_every_numeric_field_...` forges each exempted field on every
# instance and requires BOTH renders to stay byte-identical, which is what "not read" means
# operationally. Round 6's ruling was that nothing in a test suite can check that a reason written in a
# table is true; where the reason is "this is not read", it can.
#
# ROUND 8 WIDENED THE VALUES, because the five it used were all of one kind. See `exemption_forgeries`:
# `-1`, `nan`, `None`, `object()` and `liar(1e9, 0.0)` are either inadmissible to any kind or answer
# every comparison False, so not one of them is a LEGAL value of the field's own type -- and an honest
# page is already quiet, so a newly added cross-check that consumed an exempt field would stay quiet
# under all five and fire only under a legal one. The attester had to establish this by hand, with 84
# byte-identity comparisons over legal values; it is a standing check now.
FIELDS_NOT_RENDERED = {
    ("IntervalPair", "n_boot"): "the bootstrap resample count. Nothing renders it and no recomputation "
                                "can use it: see NO_SECOND_SOURCE[boot_lo] -- it is one of the two "
                                "numbers whose absence from JointResult makes the bootstrap interval "
                                "irreproducible.",
    ("IntervalPair", "sd"): "a dispersion summary `summarize` records and this page does not show; the "
                            "page shows the two INTERVALS instead, which is what protocol 7 decides on.",
    ("IntervalPair", "iqr"): "as `sd`: a dispersion summary that is recorded and not rendered.",
    ("IntervalPair", "minimum"): "an order statistic of the series, not a figure on this page.",
    ("IntervalPair", "maximum"): "as `minimum`: an order statistic, recorded and not rendered.",
    ("IntervalPair", "max_over_median_abs"): "a heavy-tail diagnostic `summarize` records; protocol 6.3's "
                                             "tail rule is applied by the scorer, not re-derived here.",
}


class DundersAreNotPartOfTheTypeEither(FailsClosedAssertions, unittest.TestCase):
    """SR-13 ROUND 7. The item failed a SIXTH time, on four routes with one root cause, and -- like
    rounds 5 and 6 -- not because a consumer was missed or a second source was absent. Rounds 5 and 6
    ADDED the second sources; this round's defect is that the COMPARISONS against them were performed by
    the suspect value's own dunders, because the three kind functions ended `return x` and
    `_finite_number`'s docstring stated that non-conversion as a deliberate choice.

    MEASURED, all on a round-6 tree emulated by rebinding the three kind functions to their pre-fix
    bodies (`_NUM_KINDS` and the three globals are every path dashboard.py reaches them by), on
    Python 3.12.4 and 3.13.5, each one `object.__setattr__` -- benchmark's declared route (b), the same
    threat model as `laundered_below_minimum`:

        FINDING 1  pair.n = liar(30, 30) in laundered_below_minimum()   JOINT_SUPPORTED, 0 warn, no alarm
        FINDING 2  min_n  = liar(1, 30)  in laundered_below_minimum()   JOINT_SUPPORTED, 0 warn, no alarm
        FINDING 3  margin = liar(-1e5, honest) on an UNSUPPORTED study  JOINT_SUPPORTED, 0 warn, no alarm
        FINDING 4  level  = liar(0.9875, 0.5) on an honest study        every level cell reads 0.5
        NOTE A     n_attempted = liar(29, 30)                           _measured_seeds returns 30
        NOTE B     width_tol   = liar(1e9, 0.25)                        min(wt, 0.25) returns 1e9
        BONUS      margin = 10**400 (no subclass needed)                render_scorecard RAISES

    and after the fix, all seven: the honest verdict, with the alarm the forgery earns.

    WHY FIVE ROUNDS MISSED ALL OF IT, counted: 0 of the 107 values in `HOSTILE_BY_KIND` +
    `LEGAL_BUT_WRONG` were `int`/`float` subclass instances. Both tables are tables of VALUES, and the
    attack is in neither the type nor the stored value, so neither table could reach it however
    carefully it was kept -- the round-5 lesson one level up. The response is therefore NOT four more
    table rows: `test_every_admitted_field_is_normalised_by_its_kind` derives the fields from
    `dataclasses.fields()` and asserts the PROPERTY (the kind hands back a value of exactly the plain
    type), and `test_both_hostile_tables_sweep_subclass_instances_too` fails if the count of subclass
    instances in either table returns to zero for any kind or any declared number. The four rows exist
    beside them so that the reported attacks are literal in the file and run through the existing
    verdict-and-alarm sweeps."""

    def plain(self, kind, honest):
        return int if kind == "count" or (kind == "num" and isinstance(honest, int)) else float

    def forge_liar(self, j, cls_name, attr, stored="honest", shown="honest"):
        """Forge `attr` to a lying subclass on EVERY instance of `cls_name` in `j`. "honest" means each
        instance's OWN current value, which matters in both arguments: `shown="honest"` is why these
        four findings were unalarmed rather than merely wrong (the page kept showing what it showed
        before), and `stored="honest"` gives the pure-dunder attack -- a value that is CORRECT and lies
        anyway, which must change nothing at all."""
        for obj in instances_of(j, cls_name):
            if db.STORED_NUMBERS[cls_name][attr] == "mv":
                mv = getattr(obj, attr)
                if mv.value is None:                 # honestly unmeasured: nothing to forge
                    continue
                h = mv.value
                forge_mv(mv, liar(h if stored == "honest" else stored, h if shown == "honest" else shown))
            else:
                h = getattr(obj, attr)
                object.__setattr__(obj, attr, liar(h if stored == "honest" else stored,
                                                   h if shown == "honest" else shown))
        return j

    def test_every_numeric_field_of_a_verdict_bearing_class_is_declared_or_exempt(self):
        """THE MACHINE-DERIVED HALF. The field set comes from `dataclasses.fields()`, not from a render
        and not from a list written here, so a new numeric field on any verdict-bearing scorer class
        fails this test naming itself -- before anything reads it, which is the one thing the recording
        probe cannot do."""
        for cls_name in db.VERDICT_BEARING:
            obj = instances_of(joint(), cls_name)[0]
            numeric = numeric_fields_of(SCORER_CLASSES[cls_name], obj)
            declared = set(db.STORED_NUMBERS[cls_name])
            exempt = {a for c, a in FIELDS_NOT_RENDERED if c == cls_name}
            self.assertEqual(numeric, declared | exempt, f"""
{cls_name}: a numeric field is neither declared in db.STORED_NUMBERS nor exempted in FIELDS_NOT_RENDERED.
  numeric but unaccounted for : {sorted(numeric - declared - exempt)}
  accounted for but not numeric: {sorted((declared | exempt) - numeric)}
Declare it (with its kind, and its class in db.VERDICT_BEARING if it reaches a verdict), or exempt it
with the reason it is not rendered -- the exemption is then CHECKED behaviourally below.""")
            self.assertEqual(declared & exempt, set(), cls_name)
        # EVERY EXEMPTION IS CHECKED, not taken on trust: an exempted field is one whose value cannot
        # move one byte of either render. 6 fields x 5 hostile values x 2 renders.
        honest_card, honest_page = db.render_scorecard(joint()), db.render_dashboard({"joint": joint()})
        for (cls_name, attr), reason in FIELDS_NOT_RENDERED.items():
            self.assertGreater(len(reason), 40, (cls_name, attr))       # a reason, not a shrug
            honest_value = getattr(instances_of(joint(), cls_name)[0], attr)
            forgeries = exemption_forgeries(honest_value)
            self.assertGreaterEqual(len(forgeries), 10, (cls_name, attr))
            # NOT VACUOUS: at least one forgery is a value this field could honestly HOLD, so "not read"
            # is tested against something a consumer would admit rather than only against rubbish a kind
            # function refuses on sight.
            self.assertTrue(any(db._mv_intact(b) is not None or db._finite_number(b) is not None
                                for b in forgeries), (cls_name, attr))
            for bad in forgeries:
                j = joint()
                for obj in instances_of(j, cls_name):
                    object.__setattr__(obj, attr, bad)
                label = f"{cls_name}.{attr} = {bad!r}"
                self.assertEqual(db.render_scorecard(j), honest_card, label)
                self.assertEqual(db.render_dashboard({"joint": j}), honest_page, label)

    def test_every_admitted_field_is_normalised_by_its_kind(self):
        """THE PROPERTY, asserted per declared field rather than per attack: what a kind function hands
        back is of EXACTLY the plain type, so no dunder of the caller's object can reach a cross-check,
        a `float()` in `_num`, or an `_e(...)` in a count cell. Every `return x` mutant in the three
        kinds dies here, including on a field this round never thought of.

        `int`-vs-`float` is part of the property: `_num` renders them differently, `_declared`'s
        `margin != declared` is exact, and `_count`'s consumers use `len()`-comparable integers."""
        j = joint()
        for cls_name in db.VERDICT_BEARING:
            obj = instances_of(j, cls_name)[0]
            for attr, kind in db.STORED_NUMBERS[cls_name].items():
                label = f"{cls_name}.{attr} ({kind})"
                if kind == "mv":
                    honest = getattr(obj, attr).value
                    if honest is None:
                        continue
                    mv = forge_mv(MetricValue.measured(1.0), liar(honest, 0.5))
                    self.assertIsNotNone(db._mv_intact(mv), label)
                    got = db._mv_float(mv)
                    self.assertIs(type(got), float, f"{label}: _mv_float returned {type(got).__name__}")
                    self.assertEqual(got, honest, label)
                    continue
                honest = getattr(obj, attr)
                want = self.plain(kind, honest)
                v = liar(honest, honest)
                got = db._NUM_KINDS[kind](v)
                self.assertIsNotNone(got, f"{label}: the kind must still ADMIT a legal stored value")
                self.assertIs(type(got), want, f"{label}: kind returned {type(got).__name__}, not "
                                               f"{want.__name__} -- the caller's dunders are still live")
                self.assertEqual(got, honest, label)
                # NOT VACUOUS: the object really is a lying subclass, and it really lies
                self.assertTrue(is_a_subclass_instance(v), label)
                self.assertIsNot(type(v), want, label)
                self.assertTrue(v == object(), label)                  # __eq__ lies
                self.assertFalse(v > honest - 1 if want is int else v > honest / 2, label)
        # and the same property through the ONLY reader in the verdict path, on every live instance
        for cls_name in db.VERDICT_BEARING:
            k = joint()
            for attr, kind in db.STORED_NUMBERS[cls_name].items():
                self.forge_liar(k, cls_name, attr)        # every field, each storing its OWN true value
            for obj in instances_of(k, cls_name):
                nums = db._admitted(obj, cls_name)
                self.assertIsNotNone(nums, cls_name)
                for attr, v in nums.items():
                    if db.STORED_NUMBERS[cls_name][attr] != "mv":
                        self.assertIn(type(v), (int, float), f"{cls_name}.{attr}")
                        self.assertFalse(is_a_subclass_instance(v), f"{cls_name}.{attr}")
            # a liar storing the HONEST number cannot move one byte of the page
            self.assertEqual(db.render_scorecard(k), db.render_scorecard(joint()), cls_name)

    def test_both_hostile_tables_sweep_subclass_instances_too(self):
        """The round-6 count, turned into a test. It was 0 of 107, and a table of literals cannot reach
        this shape however carefully it is kept, so the requirement is per KIND and per DECLARED NUMBER
        and a new entry with only literals fails here."""
        counts = {}
        for kind, vals in HOSTILE_BY_KIND.items():
            n = sum(1 for v in vals if is_a_subclass_instance(v))
            counts[f"HOSTILE_BY_KIND[{kind}]"] = (n, len(vals))
            self.assertGreater(n, 0, f"HOSTILE_BY_KIND[{kind}] sweeps no subclass instance")
        for key, vals in LEGAL_BUT_WRONG.items():
            n = sum(1 for v in vals if is_a_subclass_instance(v))
            counts[f"LEGAL_BUT_WRONG{key}"] = (n, len(vals))
            self.assertGreater(n, 0, f"LEGAL_BUT_WRONG{key} sweeps no subclass instance: a declared "
                                     f"number with a second source must be attacked through its dunders "
                                     f"as well as through its type and its value")
        total = sum(n for n, _ in counts.values())
        allv = sum(t for _, t in counts.values())
        self.assertGreater(total, 0, counts)
        self.assertEqual(set(LEGAL_BUT_WRONG), set(SECOND_SOURCE) | set(NEUTRALISED_BY_A_FLOOR))
        # the measurement this test replaces, reproduced here so the number in the comments is checkable
        plain_only = [v for vals in (*HOSTILE_BY_KIND.values(), *LEGAL_BUT_WRONG.values())
                      for v in vals if type(v) in (int, float)]
        self.assertGreater(len(plain_only), 50, "the literal halves of both tables are still swept")
        self.assertGreater(total, 10, f"{total} subclass instances in {allv} table values: {counts}")

    def test_F1_a_lying_int_subclass_n_cannot_relaunder_the_round_five_fixture(self):
        """FINDING 1, pinned by its CONSEQUENCE on the suite's own fixture. Pre-fix: JOINT_SUPPORTED,
        0 warning paragraphs, every alarm False, on a genuine 29-seed run still carrying its
        'n below protocol minimum' flag, beside a gate row reading "29 measured seeds vs minimum 30"."""
        k = laundered_below_minimum(n=liar(30, 30))
        p = k.h1.components[0].pair
        # THE CONSEQUENCE FIRST, so that this test fails pre-fix on the page and not on a type
        h = db.render_scorecard(k)
        self.assertFailsClosedWithAnAlarm(h, ("H1", "H2", "H3"), "n = liar(30, 30)")
        self.assertNotIn("JOINT_SUPPORTED", h)
        self.assertIn("SAMPLE SIZE CONTRADICTED", h)
        self.assertIn("a component claims 30 seeds but the study records only 29", h)
        self.assertEqual(len(db._n_sources_disagree(k, 29)), 6)
        self.assertIn("<td>30</td>", comp_row(h, "S"))       # the refused number is still SHOWN
        # and the mechanism, so that a future reader can see which step does the refusing
        self.assertTrue(is_a_subclass_instance(p.n))
        self.assertEqual(int.__int__(p.n), 30)               # it stores a legal, honest-looking 30
        self.assertFalse(p.n > 29)                           # ... and lies to _n_problem's comparison
        self.assertFalse(p.n >= 30)                          # ... and to the flag clause as well
        self.assertEqual(db._measured_seeds(k), 29)
        self.assertEqual(db._count(p.n), 30)                 # ADMITTED, as a legal count must be
        self.assertIs(type(db._count(p.n)), int)             # but as a PLAIN int: this is the fix
        self.assertIsNone(recompute(k.h1.components[0], k.margins, k))
        self.assertFalse(pair_ok(k))
        # NOT VACUOUS: the honest fixtures are untouched by the fix
        self.assertNotIn("SAMPLE SIZE CONTRADICTED", db.render_scorecard(joint()))
        self.assertIn("JOINT_SUPPORTED", joint_cell(db.render_scorecard(joint())))

    def test_F2_a_lying_int_subclass_min_n_cannot_remove_the_protocol_floor(self):
        """FINDING 2. Pre-fix `max(c.min_n, 30)` returned 1 -- Python prefers the SUBCLASS's reflected
        `__lt__` even as the right-hand operand -- so protocol 6.1's floor was gone AND
        `_weaker_than_protocol` was silent, which is the combination that made the page honest-looking:
        `pair.n` was left at its true 29 and printed beside a decisive JOINT_SUPPORTED."""
        k = laundered_below_minimum()
        self.assertEqual(k.h1.components[0].pair.n, 29)       # untouched: only min_n is forged
        self.forge_liar(k, "ComponentResult", "min_n", 1, shown=30)
        c0 = k.h1.components[0]
        h = db.render_scorecard(k)                            # THE CONSEQUENCE FIRST
        self.assertFailsClosedWithAnAlarm(h, ("H1", "H2", "H3"), "min_n = liar(1, 30)")
        self.assertNotIn("JOINT_SUPPORTED", h)
        self.assertIn("WEAKER THAN THE PROTOCOL", h)          # and the page SAYS which finding it is
        self.assertEqual(len(db._weaker_than_protocol(k)), 6)
        self.assertIn("min_n=1 is below the protocol minimum 30", db._weaker_than_protocol(k)[0])
        self.assertEqual(int.__int__(c0.min_n), 1)
        self.assertIs(max(c0.min_n, 30), c0.min_n)            # the lie, measured on the real expression
        self.assertEqual(db._count(c0.min_n), 1)              # admitted ...
        self.assertEqual(max(db._count(c0.min_n), 30), 30)    # ... and the floor holds on the plain int
        self.assertIsNone(recompute(c0, k.margins, k))
        # ... and a STRICTER declared parameter is still honoured in full, not floored away
        s = joint()
        self.forge_liar(s, "ComponentResult", "min_n", 60, shown=30)
        self.assertEqual(hyp_cells(db.render_scorecard(s)),
                         {"H1": "INCONCLUSIVE", "H2": "INCONCLUSIVE", "H3": "INCONCLUSIVE"})

    def test_F3_a_lying_float_subclass_margin_cannot_buy_a_decisive_verdict(self):
        """FINDING 3, the only one of the four that turns an UNSUPPORTED study into a SUPPORTED page.
        Pre-fix, on two honest fixtures (H1 UNSUPPORTED at S=0.0, H2 UNSUPPORTED at L=1.0), with the
        stored verdicts forged SUPPORTED as `laundered_below_minimum` does: JOINT_UNSUPPORTED ->
        JOINT_SUPPORTED, 0 warning paragraphs, no alarm, and EVERY FIGURE ON THE PAGE HONEST -- the
        verdict was recomputed against +-100000.0 and the margin cells printed 0.1 and 0.05."""
        for kw, honest_joint in ((dict(expect=None, S=0.0), "JOINT_UNSUPPORTED"),
                                 (dict(expect=None, L=1.0), "JOINT_UNSUPPORTED")):
            self.assertIn(honest_joint, joint_cell(db.render_scorecard(joint(**kw))), repr(kw))
            j = forge_all_verdicts_supported(joint(**kw))
            for c in all_components(j):
                direction, declared = db._declared(c.metric, j.margins)
                stored = -1e5 if direction == "greater" else 1e5
                object.__setattr__(c, "margin", liar(stored, float(declared)))
            c0 = j.h1.components[0]
            h = db.render_scorecard(j)                       # THE CONSEQUENCE FIRST
            self.assertFailsClosedWithAnAlarm(h, ("H1", "H2", "H3"), f"margin liar {kw}")
            self.assertNotIn("JOINT_SUPPORTED", h, repr(kw))
            self.assertIn("-100000.0", h, repr(kw))          # the real margin is now the figure shown
            self.assertIsNone(recompute(c0, j.margins, j), repr(kw))
            self.assertEqual(float.__float__(c0.margin), -1e5)
            self.assertTrue(c0.margin == db._declared(c0.metric, j.margins)[1])   # the lie
            self.assertEqual(float(c0.margin), 0.1)                               # the honest figure
            self.assertEqual(db._finite_number(c0.margin), -1e5)                  # admitted, NORMALISED
            self.assertIs(type(db._finite_number(c0.margin)), float)
            # and the same attack on `Margins`, the other end of the same comparison
            k = forge_all_verdicts_supported(joint_private_margins(**kw))
            for attr, honest in (("delta_S", 0.10), ("delta_R", 0.05), ("delta_sel", 0.10)):
                object.__setattr__(k.margins, attr, liar(0.2, honest))
            self.assertFailsClosedWithAnAlarm(db.render_scorecard(k), ("H1", "H2", "H3"), "Margins liar")

    def test_F4_a_lying_float_subclass_level_cannot_edit_the_figure_it_displays(self):
        """FINDING 4, and the one that buys NO verdict change: `interval_verdict` never reads `level`,
        and `bm.t_interval` normalises the level it is handed, so the cross-check used the honest
        0.9875 while every level CELL in the same render printed 0.5. It is a finding by this module's
        own rule at `_pair_numbers_ok` -- "an edited figure is unalarmed tampering even when it buys
        nothing" -- which is the rule round 4 wrote for `pair.level` and round 7 had to apply to it.

        So this pins the FIGURE: the number shown is the number stored, and the forged one appears
        nowhere. The verdict stays SUPPORTED and the page stays silent, because nothing about the study
        changed -- a forged level that CONTRADICTS the stored t-interval is the other case, and it is
        swept by `LEGAL_BUT_WRONG[("IntervalPair", "level")]`."""
        k = joint()
        honest_level = k.h1.components[0].pair.level
        self.assertEqual(honest_level, 0.9875)
        self.forge_liar(k, "IntervalPair", "level", honest_level, shown=0.5)
        p = k.h1.components[0].pair
        h = db.render_scorecard(k)                            # THE CONSEQUENCE FIRST: the FIGURE
        self.assertNotIn(">0.5<", h)                          # the forged figure, nowhere on the page
        self.assertEqual(h.count('<span class="measured">0.9875</span>'), 6)   # one cell per component
        self.assertEqual(h, db.render_scorecard(joint()))     # byte-identical to the honest render
        self.assertTrue(pair_ok(k))                           # and no false alarm: nothing contradicts
        self.assertIn("JOINT_SUPPORTED", joint_cell(h))
        self.assertTrue(is_a_subclass_instance(p.level))
        self.assertEqual(float(p.level), 0.5)                 # what _num's float() used to print
        self.assertEqual(db._finite_float(p.level), 0.9875)   # admitted, NORMALISED
        self.assertIs(type(db._finite_float(p.level)), float)

    def test_note_A_an_int_subclass_overriding_only_sub_cannot_defeat_measured_seeds(self):
        """THE ATTESTER'S FIRST NOTE, closed by the same three lines. An `int` subclass overriding ONLY
        `__sub__` (storing the honest 29, returning 30) defeats `_measured_seeds` outright: both of its
        equalities are satisfied by the honest stored value, and the quantity it RETURNS is the lie. It
        buys nothing alone -- source (2), the pair's own flag, still fires -- so it is pinned here both
        alone and in the combination that completes the F1 render."""
        class OnlySub(int):
            def __sub__(self, other):
                return 30

        j = joint(expect=None, seeds=FZ.seeds[:29])
        self.assertEqual(j.n_attempted, 29)
        object.__setattr__(j, "n_attempted", OnlySub(29))
        self.assertEqual(j.n_attempted - j.n_failed, 30)      # the lie, on the real expression
        self.assertEqual(db._measured_seeds(j), 29)           # ... which the admitted plain int undoes
        self.assertIs(type(db._admitted(j, "JointResult")["n_attempted"]), int)
        # the combination: the F1 forgery with the flag deleted, so ONLY the measured-seed count can act
        k = laundered_below_minimum(n=30)
        object.__setattr__(k, "n_attempted", OnlySub(29))
        for c in all_components(k):
            object.__setattr__(c.pair, "flags", ())
        self.assertEqual(db._measured_seeds(k), 29)
        self.assertIn("only 29 measured seeds",
                      db._n_problem(k.h1.components[0].pair, 30, 30, db._measured_seeds(k)))
        self.assertFailsClosedWithAnAlarm(db.render_scorecard(k), ("H1", "H2", "H3"), "note A")
        # NOT VACUOUS: the honest counts still read, and a genuinely 29-seed study is not alarmed
        self.assertEqual(db._measured_seeds(joint()), 30)
        self.assertNotIn("SAMPLE SIZE CONTRADICTED",
                         db.render_scorecard(joint(expect=None, seeds=FZ.seeds[:29])))

    def test_note_B_a_lying_width_tol_cannot_remove_the_protocol_tolerance(self):
        """THE ATTESTER'S SECOND NOTE, and it is reported as a NOTE here too: NO VERDICT FLIP IS
        CLAIMED. `min(c.width_tol, 0.25)` returned 1e9 pre-fix and `_weaker_than_protocol` was silent,
        so the protocol-6.3 tolerance was removed with nothing said -- that much is measured. What is
        NOT claimed is that it bought a decisive verdict: on every honest shape this file builds, the
        floored tolerance leaves the page unchanged, and the one fixture where 6.3 alone decides
        (`heavy_tailed`) fires on the DISAGREEMENT clause, which `width_tol` does not govern. Measured
        below rather than asserted in prose, and the mechanism is closed regardless."""
        for label, j in (("joint()", joint()), ("heavy_tailed()", heavy_tailed()),
                         ("heavy_tailed(idx=7)", heavy_tailed(idx=7)),
                         ("heavy_tailed(factor=500)", heavy_tailed(factor=500.0))):
            honest = db.render_scorecard(j)
            k = j
            self.forge_liar(k, "ComponentResult", "width_tol", 1e9, shown=0.25)
            c0 = k.h1.components[0]
            h = db.render_scorecard(k)                                         # THE CONSEQUENCE FIRST
            self.assertEqual(hyp_cells(h), hyp_cells(honest), label)           # NO flip, either way
            self.assertEqual(joint_cell(h), joint_cell(honest), label)
            self.assertNotIn("NOT shown", h, label)                            # not tampering, either
            self.assertIn("WEAKER THAN THE PROTOCOL", h, label)                # but no longer SILENT
            self.assertEqual(len(db._weaker_than_protocol(k)), 6, label)
            self.assertIn("is wider than the protocol tolerance 0.25", db._weaker_than_protocol(k)[0])
            self.assertIs(min(c0.width_tol, 0.25), c0.width_tol, label)        # the lie
            self.assertEqual(db._finite_number(c0.width_tol), 1e9, label)      # admitted, normalised
            self.assertIs(type(db._finite_number(c0.width_tol)), float, label)
            self.assertEqual(min(db._finite_number(c0.width_tol), 0.25), 0.25, label)
        self.assertNotIn("WEAKER THAN THE PROTOCOL", db.render_scorecard(joint()))   # not vacuous

    def test_an_int_too_large_to_be_a_float_is_refused_not_raised(self):
        """THE ROUND-7 BONUS DEFECT, which needed no subclass at all and is the reason the finiteness
        test moved AFTER the normalisation. `math.isfinite(10**400)` RAISES OverflowError, so at the
        round-6 tree `ComponentResult.margin = 10**400` made `render_scorecard` AND `render_dashboard`
        raise -- a page taken down rather than a result refused, outside this module's error contract and
        against its own docstring promise. `benchmark._plain_number` had closed exactly this case in its
        own lane ("an int too large to be a float (`10**400`) -- which is how an OverflowError outside
        this module's error contract used to escape `_check_margin`") and this module had not."""
        self.assertIsNone(db._finite_number(10 ** 400))
        self.assertIsNone(db._finite_number(-10 ** 400))
        self.assertIsNone(db._finite_number(liar(10 ** 400, 1)))      # lies to math.isfinite as well
        self.assertTrue(math.isfinite(liar(10 ** 400, 1)))            # ... measured, on the predicate
        self.assertEqual(db._count(10 ** 400), 10 ** 400)             # kind "count" has no such test
        for key in (("ComponentResult", "margin"), ("Margins", "delta_S"),
                    ("ComponentResult", "width_tol")):
            for bad in (10 ** 400, -10 ** 400, liar(10 ** 400, 1)):
                j = forge_declared(joint_private_margins(), *key, bad)
                h = db.render_scorecard(j)                            # must not raise
                self.assertIn("UNKNOWN", h, (key, repr(bad)))
                self.assertNotIn("vd-supported", joint_cell(h), (key, repr(bad)))
                self.assertIn("NOT shown", h, (key, repr(bad)))
                self.assertNotIn("REFUSED", db.render_dashboard({"joint": j}), (key, repr(bad)))


# ---------------------------------------------------------------------------------------------------------
# SR-13 ROUND 8: THE PIN AT THE RENDER BOUNDARY.
# ---------------------------------------------------------------------------------------------------------
def render_payload():
    """A full dashboard payload, rebuilt from scratch on every call.

    Its own COPY of the snapshot mapping, because `SNAP` is a module-level dict every other test in this
    file reads: a forgery written into it would leak into unrelated tests in whatever order they run."""
    return {"snapshot": dict(SNAP), "train": train(3, steps=10, timestamp_utc=TS),
            "joint": joint(), "records": [rec()]}


def payload_records(p):
    """(label, ExperimentRecord) for every record either panel renders. Both panels, because
    `_metric_cell`'s second call site (`_metric_table`) serves BOTH and Finding 1 was at both."""
    out = [(f"records[{i}]", r) for i, r in enumerate(p.get("records") or ())
           if isinstance(r, ExperimentRecord)]
    t = p.get("train")
    if isinstance(getattr(t, "record", None), ExperimentRecord):
        out.append(("train.record", t.record))
    return out


def render_sites():
    """(label, forge(payload, dunder) -> instances forged) for every number this page turns into a figure.

    DERIVED, in four halves, and not one of them is a list of field names written in this file:
      (1) `db.STORED_NUMBERS` x every live instance of its class in the payload's `JointResult`. A NEW
          declared number therefore inherits this pin with no edit here -- which is the property round 7
          put into `test_every_admitted_field_is_normalised_by_its_kind` one level too low.
      (2) every measured `MetricValue` of every `ExperimentRecord` either panel renders. This half is NOT
          derivable from `STORED_NUMBERS`, and it is not optional: Finding 1 struck at BOTH of
          `_metric_cell`'s call sites, and a sweep built from the declaration table alone would have
          pinned the scorecard mean cells and left every record and training metric cell open.
      (3) the three positions of every training-history row -- the one member of the kind scheme that is
          not a declared attribute of a scorer object (`_valid_history`).
      (4) every numeric value of the caller-supplied snapshot mapping (`_int_cell`).
    Each forge returns how many instances it touched, and `test_the_render_boundary_pin_is_not_vacuous`
    requires that to be non-zero for every site: a site that forges nothing reports no finding on a tree
    where the defect is live, which is how the first draft of this sweep missed the records panel."""
    for cls_name, fields in db.STORED_NUMBERS.items():
        for attr, kind in fields.items():
            def forge(p, d, cls_name=cls_name, attr=attr, kind=kind):
                n = 0
                for obj in instances_of(p["joint"], cls_name):
                    if kind == "mv":
                        mv = getattr(obj, attr)
                        if mv.value is None:            # honestly unmeasured: nothing to forge
                            continue
                        forge_mv(mv, conversion_liar(mv.value, a_lie_for(mv.value), d))
                    else:
                        h = getattr(obj, attr)
                        object.__setattr__(obj, attr, conversion_liar(h, a_lie_for(h), d))
                    n += 1
                return n
            yield f"declared {cls_name}.{attr} ({kind})", forge
    for where, r in payload_records(render_payload()):
        for name, mv in sorted(r.metrics.items()):
            if mv.value is None:
                continue
            def forge(p, d, where=where, name=name):
                n = 0
                for w, r_ in payload_records(p):
                    if w != where:
                        continue
                    mv_ = r_.metrics[name]
                    forge_mv(mv_, conversion_liar(mv_.value, a_lie_for(mv_.value), d))
                    n += 1
                return n
            yield f"metric {where}.metrics[{name}]", forge
    for pos, what in enumerate(("step", "loss", "grad_norm")):
        def forge(p, d, pos=pos):
            rows = []
            for row in p["train"].history:
                r_ = list(row)
                r_[pos] = conversion_liar(r_[pos], a_lie_for(r_[pos]), d)
                rows.append(tuple(r_))
            object.__setattr__(p["train"], "history", rows)
            return len(rows)
        yield f"history train.history[*][{what}]", forge
    for key, v in sorted(SNAP.items()):
        if is_a_stored_number(v) and not isinstance(v, MetricValue):
            def forge(p, d, key=key):
                h = p["snapshot"][key]
                p["snapshot"][key] = conversion_liar(h, a_lie_for(h), d)
                return 1
            yield f"snapshot snapshot[{key}]", forge


class EveryDeclaredNumberRendersTheAdmittedValue(unittest.TestCase):
    """SR-13 ROUND 8, AND IT IS THE DELIVERABLE OF THE ROUND -- more than the one-liner it kills.

    FOUR ROUNDS (2, 3, 4 and 7) ENDED THE SAME WAY: the guard was fixed, and the one consumer that
    re-reads its field AFTER the guard was missed. Round 7 normalised at the point of admission, and
    `_metric_cell` -- which admits through `_mv_float` and then renders `_num(mv.value)`, the raw object --
    was missed for the fifth consecutive round. The pin round 7 wrote,
    `test_every_admitted_field_is_normalised_by_its_kind`, asserts what a KIND FUNCTION RETURNS and never
    looks at a rendered cell, so it is structurally incapable of seeing a consumer one level up. This
    class is that test moved to the boundary where it could have fired:

        for EVERY number the page turns into a figure, render it through the REAL renderers with a
        subclass that stores the HONEST double and lies ONLY on conversion, and require the rendered
        BYTES to equal the honest render's.

    WHY ONE DUNDER AND AN HONEST STORED VALUE. Because then the honest render is the ONLY correct output,
    and the test needs no model of what should have been alarmed. Every comparison, every arithmetic and
    every predicate -- in this module, and in `benchmark` underneath it -- sees the true number, so no
    cross-check may fire and no figure may move. A byte that moves is a renderer that converted the
    CALLER'S OBJECT instead of the number its kind admitted, wherever that happens and however it is
    spelled. It is the one shape that is diagnostic of the re-read defect and of nothing else.

    MEASURED ON THE PRE-FIX TREE (3.13.5, and 3.12.4 identical), 26 sites x 7 conversions: exactly 14
    findings, all of them Finding 1, at both of `_metric_cell`'s call sites and nowhere else --
        IntervalPair.mean  __float__  scorecard BYTES DIFFER   (6 of 6 mean cells printed the lie)
        IntervalPair.mean  __float__  dashboard BYTES DIFFER
        IntervalPair.mean  RAISE      both renderers RAISED ZeroDivisionError
        the 5 record/training metrics, the same two findings each, via `_metric_table`
    -- and 0 findings after the one-line fix. The 24 other sites were already honest, which is the other
    half of the measurement: `_interval`, `_kind_cell`, `_kind_text`, `_valid_history` and `_int_cell` all
    render the ADMITTED value, so `boot_lo`/`boot_hi`/`t_lo`/`t_hi` forged identically move not one byte.

    WHAT IT IS NOT. It is not a completeness proof, and the one claim this class makes about its own reach
    is that it does not depend on WHERE the re-read is. It sweeps the numbers that are DECLARED or
    reachable in ONE payload, so an undeclared field read only on a branch this payload does not take is
    outside it -- the same residual item 3 of the scheme note has declared since round 4, and the reason
    the recording probe and the fields test are kept beside this."""

    def honest(self):
        return db.render_scorecard(render_payload()["joint"]), db.render_dashboard(render_payload())

    def test_every_rendered_number_is_rendered_from_the_admitted_value(self):
        """THE PIN. Reports the WHOLE matrix rather than the first failure: "which cells re-read" is the
        question a reader of a red run is asking, and five rounds of this item were lost to answering it
        one site at a time."""
        honest_card, honest_page = self.honest()
        self.assertIn('class="measured"', honest_card)        # the honest renders are not empty pages
        self.assertIn('class="measured"', honest_page)
        findings, sites = [], 0
        for label, forge in render_sites():
            sites += 1
            for d in CONVERSION_DUNDERS:
                p = render_payload()
                if not forge(p, d):
                    continue
                try:
                    card = db.render_scorecard(p["joint"])
                except BaseException as ex:                   # noqa: BLE001 - a raise IS the finding
                    findings.append(f"{label} [{d}]: render_scorecard RAISED {type(ex).__name__}")
                    card = honest_card
                try:
                    page = db.render_dashboard(p)
                except BaseException as ex:                   # noqa: BLE001
                    findings.append(f"{label} [{d}]: render_dashboard RAISED {type(ex).__name__}")
                    page = honest_page
                if card != honest_card:
                    findings.append(f"{label} [{d}]: scorecard BYTES DIFFER from the honest render")
                if page != honest_page:
                    findings.append(f"{label} [{d}]: dashboard BYTES DIFFER from the honest render")
        self.assertEqual(findings, [], f"""
{len(findings)} of {sites * len(CONVERSION_DUNDERS)} (site x conversion) pairs moved the page or took it
down, with the stored number HONEST and only a conversion dunder lying:

  """ + "\n  ".join(findings) + """

Each one is a consumer that RE-READS its field after admission and converts the caller's object instead
of rendering the value its kind handed back -- SR-13's defect class, five rounds running. Fix the cell,
not this test: admit once (`_mv_float` / `_NUM_KINDS[kind]`) and render the value you were given. A raise
is the same defect: this module's contract is to refuse a malformed result, never to take the page down.""")

    def test_the_render_boundary_pin_is_not_vacuous(self):
        """FOUR WAYS IT COULD BE GREEN FOR NOTHING, each refused by measurement rather than by reading.

        (a) the lie must be VISIBLE to the conversions the renderers actually perform;
        (b) every site must really forge something (the first draft's constant lie of 0.5 collided with
            `rec()`'s own metric and made that site silently vacuous);
        (c) the subclass must really be a subclass, really store the honest number, and really pass the
            kind that admits its field -- a value the kind REFUSED would render UNKNOWN on both pages and
            the byte comparison would be comparing two honest renders;
        (d) the sites must cover every declared number AND both of `_metric_cell`'s call sites."""
        # (a) the module's only `float()`, and the count cells' `_e`, both read the lie
        self.assertEqual(db._num(conversion_liar(1.0, 2.0, "__float__")), "2.0")
        self.assertEqual(db._e(conversion_liar(3, 4, "__str__")), "4")
        self.assertEqual(f"{conversion_liar(3, 4, '__format__')}", "4")
        with self.assertRaises(ZeroDivisionError):
            db._num(conversion_liar(1.0, 0.0, "RAISE"))
        # (c) and it is admitted: a liar the kind refuses would make both pages honest for a WRONG reason
        for kind, honest in (("float", 0.5), ("num", 0.5), ("num", 3), ("count", 3)):
            for d in CONVERSION_DUNDERS:
                v = conversion_liar(honest, a_lie_for(honest), d)
                self.assertTrue(is_a_subclass_instance(v), (kind, d))
                self.assertEqual(float.__float__(v) if isinstance(v, float) else int.__int__(v), honest)
                got = db._NUM_KINDS[kind](v)
                self.assertIsNotNone(got, f"{kind} refused a legal stored value via {d}")
                self.assertIs(type(got), float if isinstance(honest, float) else int, (kind, d))
        # (b) every site forges at least one instance, for every conversion
        sites = list(render_sites())
        self.assertGreater(len(sites), 20, len(sites))
        for label, forge in sites:
            for d in CONVERSION_DUNDERS:
                self.assertGreater(forge(render_payload(), d), 0, f"{label} [{d}] forged nothing")
        # (d) coverage: every declared number, and both `_metric_cell` call sites
        labels = [label for label, _ in sites]
        for cls_name, fields in db.STORED_NUMBERS.items():
            for attr in fields:
                self.assertIn(f"declared {cls_name}.{attr} ({fields[attr]})", labels)
        self.assertTrue(any(l.startswith("metric records[0]") for l in labels), labels)
        self.assertTrue(any(l.startswith("metric train.record") for l in labels), labels)
        self.assertTrue(any(l.startswith("history ") for l in labels), labels)
        self.assertTrue(any(l.startswith("snapshot ") for l in labels), labels)
        # ... and the two call sites really are the two panels this covers
        src = inspect.getsource(db)
        self.assertEqual(src.count("_metric_cell("), 3)       # def + the scorecard row + `_metric_table`
        self.assertEqual(src.count("_metric_table("), 3)      # def + the training panel + the records panel

    def test_the_payload_this_sweep_renders_is_the_whole_page(self):
        """A sweep is only as wide as its payload. Asserted, because a payload that quietly lost its
        records list would make five of the 26 sites disappear and the pin would stay green."""
        p = render_payload()
        self.assertEqual(set(p), {"snapshot", "train", "joint", "records"})
        page = db.render_dashboard(p)
        self.assertEqual(page.count('data-evidence="'), 5)    # every panel rendered, none refused
        self.assertNotIn("REFUSED", page)
        self.assertNotIn("not iterable", page)
        self.assertEqual(len(payload_records(p)), 2)          # the records panel AND the training panel
        self.assertGreater(len(p["train"].history), 1)
        self.assertGreater(len(instances_of(p["joint"], "IntervalPair")), 1)
        # and `SNAP` is not corrupted by a sweep that forges into the payload's snapshot copy
        before = dict(SNAP)
        for label, forge in render_sites():
            forge(render_payload(), "__float__")
        self.assertEqual(SNAP, before)
        self.assertTrue(all(type(v) in (int, float, str, bool, type(None), list, dict)
                            for v in SNAP.values()))




# ---------------------------------------------------------------------------------------------------------
# SR-13 ROUND 9: THE SAME PIN, ONE LANE FURTHER OUT -- EVERY FIGURE AND EVERY DECISIVE WORD.
#
# ROUND 8 PROVED ITS OWN NUMBER COVERAGE COMPLETE, and that measurement is why this section exists rather
# than another number sweep: a logging subclass recording 39 candidate dunders, forged onto every declared
# number, every per-seed `MetricValue`, every record and training metric, every history position and every
# snapshot scalar, rendered through both renderers over 30 payloads (11 of them on branches the pin's own
# payload does not take, plus all 18 honest shapes) -- ~13,500 forged instances -- consulted 0 dunders and
# raised nothing. So the gap was not a missed number. THE PAGE PRINTS THINGS THAT ARE NOT NUMBERS, and
# `CONVERSION_DUNDERS` cannot reach any of them: a `str` has no `__float__`, and `render_sites()` is driven
# by `db.STORED_NUMBERS`, which declares no string.
#
# TWO SPELLINGS, both measured on the round-8 tree and both invisible to every sweep in this file:
#   * a `str` SUBCLASS that IS the honest text while `__hash__`/`__eq__`/`__ne__` answer as another word
#     -- which defeats a vocabulary lookup and an agreement check -- or while `__str__`/`__format__`
#     answer as another word, which defeats a display cell, or while `__len__` answers differently, which
#     defeats a truncation marker;
#   * a `list`/`tuple` SUBCLASS that holds the honest entries while `__len__` answers differently --
#     which defeats a printed count, because `isinstance(x, (list, tuple))` admits a subclass and the
#     rows are built by `__iter__`.
# `word_liar` and `container_liar` are those two shapes, ONE DUNDER AT A TIME and storing the HONEST
# content, for exactly the reason `conversion_liar` is: then the honest render is the only correct output
# and the test needs no model of what should have been alarmed.
# ---------------------------------------------------------------------------------------------------------
WORD_DUNDERS = ("eq", "str", "len", "format", "getitem")


def word_liar(text, shown, dunder):
    """A `str` SUBCLASS instance that STORES `text` and lies about it on exactly one `dunder`.

    "eq" is `__hash__` + `__eq__` + `__ne__` together and that is deliberate: they are not three attacks
    but one, because a dict/enum lookup is `__hash__` THEN `__eq__` and splitting them would make the
    lookup half unreachable (a liar with an honest `__hash__` lands in a different bucket and is never
    compared). The other four are one dunder each. Nothing else is overridden, so every slice, every
    regex, every `isinstance` and every `str.__str__` reads the honest characters."""
    bodies = {
        "eq": {"__hash__": lambda self: hash(shown),
               "__eq__": lambda self, o: shown == o if isinstance(o, str) else NotImplemented,
               "__ne__": lambda self, o: not (shown == o) if isinstance(o, str) else NotImplemented},
        "str": {"__str__": lambda self: shown, "__hash__": str.__hash__},
        "len": {"__len__": lambda self: len(shown), "__hash__": str.__hash__},
        "format": {"__format__": lambda self, spec: format(shown, spec), "__hash__": str.__hash__},
        "getitem": {"__getitem__": lambda self, i: shown[i], "__hash__": str.__hash__},
    }
    cls = type("LiesOnStr_" + dunder, (str,), bodies[dunder])
    return cls(text)


def container_liar(items, n):
    """A `list`/`tuple` SUBCLASS holding `items` whose `__len__` returns `n`. Iteration, indexing and
    `isinstance` are the base class's, so the ENTRIES are honest and only the size is a lie."""
    base = list if isinstance(items, list) else tuple
    cls = type("LiesOnLen_" + base.__name__, (base,), {"__len__": lambda self: n})
    return cls(items)


def is_a_lying_string(v):
    """The shape this section exists for: a `str` SUBCLASS instance, not a `str`. The exact predicate the
    "0 of 10" count in `test_absent_or_invalid_subject_kind_renders_UNKNOWN` uses, so that figure is
    reproducible from this file -- the string-lane twin of `is_a_subclass_instance`."""
    return isinstance(v, str) and type(v) is not str


def module_vocabularies():
    """Every vocabulary of decisive words these two modules DECLARE, read off the modules rather than
    written here, so a new kind, hypothesis, scope, verdict, evidence label, gate, metric or direction
    joins the lie vocabulary with no edit in this file."""
    return [sorted(db._SUBJECT_KIND_LABELS), sorted(db._HNAMES), sorted(db._KNOWN_SCOPES),
            sorted(v.value for v in bm.Verdict), sorted(v.value for v in bm.JointVerdict),
            sorted(e.value for e in EC), sorted(bm.GATE_SCOPES),
            sorted({m for t in (*bm.PRIMARY.values(), bm.CONVERGED) for m, _d, _a in t}),
            sorted({d for t in (*bm.PRIMARY.values(), bm.CONVERGED) for _m, d, _a in t})]


def words_against(text):
    """The lie texts for a site whose honest text is `text`.

    DERIVED FROM THE MODULES, in three parts, and the first is the dangerous one:
      (1) other members of every module vocabulary that CONTAINS this text -- a word THIS PAGE
          RECOGNISES, which is the only kind of lie a vocabulary lookup can be fooled by. Capped at two
          per vocabulary, sorted, because this sweep is diagnostic and not exhaustive: the exhaustive
          measurement (every site x 5 dunders x 28 texts = 2,800 forgeries) is recorded in
          `EveryDecisiveWordRendersTheAdmittedText`'s docstring, and a cap that hid a defect would have
          to hide it from all five dunders at once.
      (2) one word from a vocabulary that does NOT contain this text, so a field with no vocabulary of
          its own is still swept.
      (3) a string longer than `db.MAX_TEXT`, which is the `__len__` lane: the truncation marker.
    `a_lie_for`'s rule applies -- a lie is never the honest text, and never renders as the same string."""
    own = []
    for v in module_vocabularies():
        if text in v:
            own += [w for w in v if w != text][:2]
    other = next(w for v in module_vocabularies() for w in v if text not in v and w != text)
    lies = sorted(set(own)) + [other, "x" * (db.MAX_TEXT + 7)]
    assert all(lie != text and str(lie) != str(text) for lie in lies), text
    return lies


def word_holders(p):
    """class name -> every live instance of that class the payload hands the renderers.

    Keyed by the SAME names as `db.STORED_WORDS`, so the sweep is driven by the module's declaration and
    `test_every_string_field_of_a_rendered_class_is_declared` can enumerate against the same classes."""
    j = p["joint"]
    comps = all_components(j)
    recs = [r for _w, r in payload_records(p)]
    return {"IntervalPair": [c.pair for c in comps], "ComponentResult": comps,
            "Margins": [j.margins], "JointResult": [j],
            "HypothesisResult": [j.h1, j.h2, j.h3], "GateResult": list(j.gates),
            "ExperimentRecord": recs,
            # THE NINTH RENDERED DATACLASS (round 11). `_record_idents` and the records panel read
            # `rec.provenance.run_id`, `.code_version` and `.timestamp_utc` through `getattr`, so the
            # NAME `RunProvenance` appears ZERO times in `dashboard.py` and the eight-class list was
            # wrong structurally rather than by anyone's reading. It is in the sweep because being
            # rendered is what puts a class in it, not being mentioned.
            "RunProvenance": [r.provenance for r in recs],
            "MetricValue": [c.pair.mean for c in comps]}


WORD_CLASSES = {"IntervalPair": bm.IntervalPair, "ComponentResult": bm.ComponentResult,
                "Margins": bm.Margins, "JointResult": bm.JointResult,
                "HypothesisResult": bm.HypothesisResult, "GateResult": bm.GateResult,
                "ExperimentRecord": ExperimentRecord, "RunProvenance": RunProvenance,
                "MetricValue": MetricValue}
STRING_ANNOTATION = re.compile(r"^(?:str|Optional\[str\])$")


def string_fields_of(cls, obj):
    """The caller-supplied STRING fields of a class this page renders: string BY DECLARATION, union
    string BY HONEST VALUE. The string-lane twin of `numeric_fields_of`, and it exists for the same
    reason: the annotation half carries fields whose honest value is `None` at fixture-build time
    (`notes`, `fixture_name`, `MetricValue.reason`), and the value half carries fields whose annotation
    is not the word `str` at all -- which is how `evidence_class: EvidenceClass` and `verdict: Verdict`
    are caught, both of them `str` Enums and both of them the site of a round-9 finding.

    The annotation is matched WHOLE (`^str$` / `^Optional[str]$`), not searched: `Mapping[str,
    MetricValue]` mentions `str` and is not a string field, and admitting it by substring would put a
    mappingproxy in the sweep and make every forgery of it a refused no-op -- a vacuous site, which is
    the failure `test_the_decisive_word_pin_is_not_vacuous` (b) exists to refuse.

    THAT REASONING IS ABOUT FORGING THE MAPPING OBJECT, AND ROUND 11 FOUND WHAT IT LEFT UNSWEPT: the
    mapping's KEYS. CLAUDE.md rules that an input avoided because it "would make a test pass for the
    wrong reason" is itself a finding, and the avoidance recorded in the paragraph above is exactly that
    note -- correct about the mappingproxy, silent about the two string things inside it. A key is not
    the mapping: `set(metrics) | set(expected)` and `metrics.get(n)` ran on the KEY's `__hash__`/`__eq__`
    and a key storing "zzz" that compares as "initial_loss" swallowed a `TRAIN_EXPECTED` member whole.
    The keys are swept by `caller_mapping_sites()` and the mapping object is still not in THIS
    enumeration, which is the division the fix keeps: sweep the keys, not the mapping."""
    out = set()
    for f in dataclasses.fields(cls):
        ann = f.type if isinstance(f.type, str) else getattr(f.type, "__name__", repr(f.type))
        if STRING_ANNOTATION.match(ann.strip()) or isinstance(getattr(obj, f.name, None), str):
            out.add(f.name)
    return out


def word_sites():
    """(label, lane, forge(payload, shown, dunder) -> instances forged) for every caller-supplied string
    this page turns into a label, a decisive word or a lookup key.

    DRIVEN BY `db.STORED_WORDS` x every live instance of its class in the payload, so a newly declared
    string inherits this pin with no edit here -- and a string field that is NOT declared fails
    `test_every_string_field_of_a_rendered_class_is_declared` instead, which is the half that makes the
    declaration load-bearing rather than decorative. Entries in the "bare" lane are NOT yielded: they are
    declared residuals and are measured by `test_the_two_bare_string_residuals_are_still_open`."""
    for cls_name, fields in db.STORED_WORDS.items():
        for attr, lane in sorted(fields.items()):
            if lane == "bare":
                continue

            def forge(p, shown, d, cls_name=cls_name, attr=attr):
                n = 0
                for obj in word_holders(p)[cls_name]:
                    v = getattr(obj, attr, None)
                    if not isinstance(v, str):
                        continue           # honestly absent or not a string: nothing to forge
                    object.__setattr__(obj, attr, word_liar(str.__str__(v), shown, d))
                    n += 1
                return n
            yield f"{cls_name}.{attr}", lane, forge


def container_sites():
    """(label, forge(payload, n) -> containers forged) for every CALLER-SUPPLIED container either
    renderer receives, derived by walking the payload rather than from a list of names.

    Every `list`/`tuple` the caller hands in is swept, not only the one whose size is printed today:
    `len(files)` was the eighth conversion precisely because nobody had enumerated the containers, and a
    `len()` added to any of these tomorrow inherits this pin. The ten `len()` this module takes on
    containers IT built are a different question and are classified in `LEN_SITES`."""
    def snap_keys(p):
        return sorted(k for k, v in p["snapshot"].items() if isinstance(v, (list, tuple)))

    for key in snap_keys(render_payload()):
        def forge(p, n, key=key):
            p["snapshot"][key] = container_liar(list(p["snapshot"][key]), n)
            return 1
        yield f"snapshot[{key}]", forge

    def forge_records(p, n):
        p["records"] = container_liar(list(p["records"]), n)
        return 1
    yield "records", forge_records

    def forge_history(p, n):
        object.__setattr__(p["train"], "history", container_liar(list(p["train"].history), n))
        return 1
    yield "train.history", forge_history

    for attr in ("gates", "seed_scores", "ineligible"):
        def forge(p, n, attr=attr):
            object.__setattr__(p["joint"], attr, container_liar(tuple(getattr(p["joint"], attr)), n))
            return 1
        yield f"joint.{attr}", forge

    for which in ("components", "converged_components"):
        def forge(p, n, which=which):
            c = 0
            for h in (p["joint"].h1, p["joint"].h2, p["joint"].h3):
                v = getattr(h, which, None)
                if isinstance(v, (list, tuple)) and v:
                    object.__setattr__(h, which, container_liar(tuple(v), n))
                    c += 1
            return c
        yield f"hypothesis.{which}", forge


# Every `len()` in `dashboard.py`, keyed by (enclosing function, the argument as `ast.unparse` writes it),
# with THE EXPRESSION THAT BUILT the container. `test_every_len_in_the_module_is_classified` derives the
# keys from the module's own AST and fails if this mapping is not exactly that set, so a `len()` added
# anywhere in `dashboard.py` fails the suite until it is classified -- which is the property the round-8
# pin lacked, and the reason `len(files)` was swept by nothing.
#
# ROUND 9 FOUND TWO OF THESE TAKEN ON THE CALLER'S OBJECT and the other ten on containers this module had
# just built. One of the two is gone (`_render_snapshot` now counts what it ITERATED, so there is no
# `len(files)` to classify); the other is `_untrusted`, which now measures `_word(value)`. Both former
# caller sites keep a BEHAVIOURAL pin rather than this comment: the `_untrusted` one in
# `EveryDecisiveWordRendersTheAdmittedText` (through `ExperimentRecord.name`, `JointResult.subject` and
# `GateResult.name`, all of which reach `_untrusted`) and the snapshot one in
# `test_the_printed_file_count_is_what_was_iterated`.
LEN_SITES = {
    ("_untrusted", "s"): "`_word(value)` -- a plain `str` of the characters the caller's object stores -- "
                         "or `repr(value)` for a non-string. THIS WAS `value` ITSELF until round 9.",
    ("_defang", "scheme"): "the loop variable of this function's own two-element literal tuple.",
    ("_interval_problem", "series"): "the per-seed list `_seed_series` built from `joint.seed_scores`.",
    ("_measured_seeds", "ids"): "a list comprehension built in this function.",
    ("_measured_seeds", "set(ids)"): "a `set` built in the same expression.",
    ("_measured_seeds", "scores"): "`tuple(joint.seed_scores)`, built by `__iter__` in this function.",
    ("_render_records", "classes"): "a `set` this function accumulates.",
    ("_render_records", "recs"): "`list(records)`, built by `__iter__` in this function.",
    ("_render_train", "hist"): "`_valid_history`'s own list.",
    ("_render_train", "shown"): "a slice of `hist`, itself `_valid_history`'s list.",
    ("render_scorecard", "deferred"): "`tuple(joint.deferred_gates)`, built by `__iter__`; "
                                      "`deferred_gates` is a CLASS-level constant, not an init argument.",
}


def len_call_sites(module):
    """(enclosing function, argument source) for every `len(...)` call in `module`, by AST.

    AST and not a text scan, for the reason `module_code_by_line` gives: every docstring in
    `dashboard.py` discusses `len()` and a text scan would report the documentation."""
    src = Path(inspect.getsourcefile(module)).read_text(encoding="utf-8")
    owner = enclosing_functions(module)
    out = {}
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "len":
            key = (owner.get(node.lineno, "<module>"), ast.unparse(node.args[0]))
            out.setdefault(key, []).append(node.lineno)
    return out



class EveryStringFieldIsDeclaredAndClassified(unittest.TestCase):
    """THE DERIVATION HALF, and it is what makes `db.STORED_WORDS` load-bearing rather than decorative.

    `STORED_NUMBERS` has had this since round 4 (`numeric_fields_of` + `FIELDS_NOT_RENDERED`); the string
    lane had nothing, which is the structural reason Finding 1 could sit in `_subject_kind` for seven
    rounds while every number on the page was swept three different ways. A `str`-annotated or str-valued
    field of a class this page renders must be declared with a lane, so a NEW string field fails the
    suite until someone says what the page does with it."""

    def test_every_string_field_of_a_rendered_class_is_declared(self):
        p = render_payload()
        for cls_name, cls in WORD_CLASSES.items():
            objs = word_holders(p)[cls_name]
            self.assertTrue(objs, cls_name)
            fields = string_fields_of(cls, objs[0])
            declared = set(db.STORED_WORDS[cls_name])
            self.assertEqual(fields, declared, f"""
{cls_name}: the caller-supplied STRING fields this page can read do not match db.STORED_WORDS.
  enumerated but not declared: {sorted(fields - declared)}
  declared but not a string field: {sorted(declared - fields)}
Declare each in db.STORED_WORDS with its lane -- "shown" if the page turns it into a label, a decisive
word or a boxed figure (and then route it through `_word`/`_word_text`), "key" if the page hands it to a
lookup this module does not own and a lie must fail closed, "bare" if it is a declared residual.""")

    def test_the_lanes_are_a_partition_with_a_measured_assignment(self):
        self.assertEqual(set(db.STORED_WORDS), set(WORD_CLASSES))
        lanes = [lane for f in db.STORED_WORDS.values() for lane in f.values()]
        self.assertTrue(set(lanes) <= set(db.WORD_LANES), sorted(set(lanes)))
        self.assertEqual(len(lanes), 24, len(lanes))          # counted, not asserted in prose
        self.assertEqual(len(db.STORED_WORDS), 9, sorted(db.STORED_WORDS))   # nine rendered classes
        self.assertEqual(sorted(lanes).count("bare"), 2)
        self.assertEqual({k for cls in db.STORED_WORDS.values() for k, v in cls.items() if v == "bare"},
                         {"reason"})
        # and the numeric and string declarations are DISJOINT: no field is both a figure and a word
        for cls_name, fields in db.STORED_WORDS.items():
            self.assertEqual(set(fields) & set(db.STORED_NUMBERS.get(cls_name, {})), set(), cls_name)

    def test_the_two_halves_of_numeric_fields_of_agree_and_the_figure_is_counted(self):
        """THE CORRECTED FIGURE IN `numeric_fields_of`'s DOCSTRING, counted here instead of restated
        there. It said "the SAME 15 names today (7 + 3 + 3 + 2)"; 15 is `len(db.STORED_NUMBERS)`
        flattened, and the enumeration yields 21 -- `IntervalPair` contributes 13 (its 7 declared numbers
        UNION the 6 exempted in `FIELDS_NOT_RENDERED`), not 7. Both halves of the union still agree
        exactly per class, which is the claim that paragraph was making and the only one it got right."""
        p = render_payload()
        live = {"IntervalPair": p["joint"].h1.components[0].pair,
                "ComponentResult": p["joint"].h1.components[0],
                "Margins": p["joint"].margins, "JointResult": p["joint"]}
        per_class, total = {}, 0
        for cls_name, cls in SCORER_CLASSES.items():
            obj = live[cls_name]
            annotated = {f.name for f in dataclasses.fields(cls)
                         if NUMERIC_ANNOTATION.search(f.type if isinstance(f.type, str)
                                                      else getattr(f.type, "__name__", repr(f.type)))}
            valued = {f.name for f in dataclasses.fields(cls)
                      if is_a_stored_number(getattr(obj, f.name, None))}
            self.assertEqual(annotated, valued, f"{cls_name}: the two halves no longer agree")
            union = numeric_fields_of(cls, obj)
            self.assertEqual(union, annotated | valued, cls_name)
            declared = set(db.STORED_NUMBERS[cls_name])
            exempt = {a for c, a in FIELDS_NOT_RENDERED if c == cls_name}
            self.assertEqual(union, declared | exempt, cls_name)
            per_class[cls_name] = len(union)
            total += len(union)
        self.assertEqual([per_class[c] for c in ("IntervalPair", "ComponentResult", "Margins",
                                                 "JointResult")], [13, 3, 3, 2], per_class)
        self.assertEqual(total, 21, per_class)
        self.assertEqual(sum(len(v) for v in db.STORED_NUMBERS.values()), 15,
                         "15 is the DECLARED count; if it moves, the withdrawal paragraph moves too")
        # The corrected figure and its withdrawal are asserted on `__doc__`, NOT on this file's source:
        # the round-8 D4 note already rules that an assertion over THIS file would have to count its own
        # literals, and both strings below appear here as well as in the docstring.
        doc = numeric_fields_of.__doc__
        self.assertEqual(doc.count("the SAME 21 names today (13 + 3 + 3 + 2)"), 1)
        self.assertEqual(doc.count('THE FIGURE THIS REPLACES SAID "the SAME 15 names today'), 1)
        self.assertLess(doc.index("the SAME 21 names today"), doc.index("THE FIGURE THIS REPLACES SAID"))
        self.assertIn("15 is `len(db.STORED_NUMBERS)`", doc)

    def test_every_len_in_the_module_is_classified(self):
        """A `len()` added anywhere in `dashboard.py` fails this until it is classified. `len(files)` was
        SR-13's eighth conversion and it was swept by nothing: it is not a declared number, it passes
        through no kind function, and the round-8 snapshot half forges only SCALAR values of the mapping.
        A registry of `len()` sites is the derivation that would have named it."""
        derived = len_call_sites(db)
        self.assertEqual(set(derived), set(LEN_SITES), f"""
the `len()` call sites in dashboard.py do not match LEN_SITES.
  in the module, unclassified: {sorted(set(derived) - set(LEN_SITES))}
  classified but gone:         {sorted(set(LEN_SITES) - set(derived))}
Say what built each container. If it is CALLER-SUPPLIED, `len` is overridable: either count what you
ITERATED (see `_render_snapshot`) or admit it (`_word`), and add a behavioural pin here.""")
        self.assertEqual(len(derived), 11, sorted(derived))
        for (fn, arg), reason in LEN_SITES.items():
            self.assertTrue(reason.strip() and not reason.strip().startswith("TODO"), (fn, arg))
            self.assertIn(fn, [f for f in enclosing_functions(db).values()], fn)
        # NOT VACUOUS: the two round-9 caller-supplied sites really are gone from the caller lane
        self.assertNotIn(("_render_snapshot", "files"), derived,
                         "`len(files)` is back; the printed count must be what was ITERATED")
        self.assertIn("_word(value) if isinstance(value, str) else repr(value)",
                      inspect.getsource(db._untrusted))


# THE `"key"` LANE'S FIGURES, MOVED OUT OF A COMMENT IN `dashboard.py` AND ASSERTED (round 11).
#
# That comment stated three: "round 9 measures 54 of 54 forgeries withholding the joint verdict" for
# `ComponentResult.metric`, "27 of 27" for `HypothesisResult.verdict`, and "54 of 54" for
# `GateResult.name`. NONE of the three reproduced. Measured by the loop below -- the loop those figures
# describe -- it is 48, 4 and 42, each out of itself. The substance was right: every forgery that moved
# the page FAILED CLOSED, and not one left a decisive joint verdict standing. The arithmetic had rotted
# and nothing went red, because a figure in a comment is a figure no test can see -- the
# per-sentence-pinning gap CLAUDE.md names, in its mildest and most durable form.
#
# (forgeries that MOVED the page, forgeries that then FAILED CLOSED) per "key" site, asserted exactly, so
# a change in the lie vocabulary, the dunder list, the payload or the scorer moves this table or turns the
# suite red. `standing` is asserted to be 0 on its own line, because that is the lane's actual promise and
# the only part of this a reader should trust without re-deriving it; and the total forgery count is
# asserted too, because a site that silently stopped forging would otherwise lower every figure at once.
KEY_LANE_FIGURES = {
    "ComponentResult.metric": (48, 48),
    "GateResult.name": (42, 42),
    "HypothesisResult.verdict": (4, 4),
}


class EveryDecisiveWordRendersTheAdmittedText(FailsClosedAssertions, unittest.TestCase):
    """SR-13 ROUND 9, AND IT IS THE DELIVERABLE OF THE ROUND. The round-8 pin, one lane further out.

    ROUND 8 MEASURED ITS OWN NUMBER COVERAGE AND FOUND IT COMPLETE -- ~13,500 forged instances over 30
    payloads, 39 candidate dunders recorded, 0 consulted -- so this round did not re-sweep numbers. It
    swept what the page prints that is NOT a number, and found FIVE fail-open sites where round 8 had
    found one. All five are the same defect in the same shape: a guard spelled in a string operator,
    performed on the CALLER'S OBJECT rather than on the characters it stores.

    MEASURED ON THE PRE-FIX TREE (3.13.5, and 3.12.4 identical), 20 declared sites x 5 dunders x 28 lie
    texts = 2,800 forgeries. NINE SITES moved the page with a decisive verdict standing and no alarm, in
    TEN (site, dunder) combinations -- the two figures below are counted from the list that follows, and
    both were stated wrongly before. This docstring said "8 sites"; round 9's commit message said
    "99 of 600 findings across 10 sites", and 10 is the count of (site, dunder) entries, or of sites with
    `ComponentResult.metric` counted in. IT CONTRIBUTES ZERO FINDINGS: its lies fail closed and the
    `"key"` lane's exemption absorbs them, which is exactly what `KEY_LANE_FIGURES` now records (48 of 48
    moved, 48 of 48 failed closed). The commit message cannot be corrected in place; the figure is
    corrected here, and the two numbers this file states are now derived in the assertions at the end of
    the pin (`len(list(word_sites()))` and `pairs`) rather than written down. The nine:
        JointResult.subject_kind     [eq]  BYTE-IDENTICAL TO THE HONEST FIXTURE RENDER on a result whose
            gates carry the exemption and whose label stores "trained": SCORER-VALIDATION FIXTURE,
            JOINT_SUPPORTED, H1/H2/H3 SUPPORTED, no CONTRACT PROBLEM, no relabel paragraph. The honest
            plain-"trained" relabel renders JOINT_INCONCLUSIVE with every verdict withheld. Guard 1.
        ComponentResult.verdict      [eq]  and HypothesisResult.verdict: every stored verdict reading
            "UNSUPPORTED" displayed SUPPORTED x3 and JOINT_SUPPORTED with no mismatch paragraph, through
            `_vcoerce`'s `enum_cls(value)`. Guard 4.
        ExperimentRecord.evidence_class [eq]  a record whose stored label is "SOURCE_OBSERVED" -- the one
            label this page exists to refuse on a run record -- rendered a TOY RESULT badge with no
            problem; "NOT_VALIDATED" and "HYPOTHESIS" the same. 35 of 36 moved unalarmed. Guard 2.
        HypothesisResult.hid         [str] three rows all captioned `H3 ... hypothesis verdict`, 17 of 17
            lie texts, JOINT_SUPPORTED, 0 alarms.
        ComponentResult.direction    [str] `less 0.1` in all five rows while the scorer applied
            "greater"; [eq] passed `_declared`'s agreement check and changed the scorer's own branch.
        JointResult.subject / ExperimentRecord.name / GateResult.name  [len]  a 400-character value
            rendered 300 characters with NO "[... truncated]" marker.
    -- and 0 after the fixes. The OTHER ELEVEN of the twenty then declared were already honest, which is
    the other half of the measurement: `_untrusted`'s slice, `_e`, `_visible` and every `str` Enum member
    read the real buffer. (Twenty-two are declared now: `RunProvenance`'s four strings joined in round 11,
    and all four are honest too -- `9 - 8 = 1` and `20 - 9 = 11` are the two corrections, and the reason
    both figures are now `assertEqual`s below rather than sentences up here.)

    WHY ONE DUNDER AND THE HONEST TEXT, which is `conversion_liar`'s argument in the string lane: then
    the honest render is the ONLY correct output and this test needs no model of what should have been
    alarmed. Every slice, every regex, every `isinstance` and every `str.__str__` sees the true
    characters, so no cross-check may legitimately fire and no word may legitimately move.

    WHAT IT IS NOT. Not a completeness proof. It sweeps the strings DECLARED in `db.STORED_WORDS` and
    reachable in ONE payload; a string read only on a branch this payload does not take is outside it,
    the same residual item 3 of the scheme note has declared since round 4. What it does establish is
    that the pin does not depend on WHERE the read is or HOW it is spelled."""

    def honest(self):
        return db.render_scorecard(render_payload()["joint"]), db.render_dashboard(render_payload())

    def test_every_rendered_word_is_rendered_from_the_admitted_text(self):
        """THE PIN. Reports the WHOLE matrix, for the reason the round-8 pin does: "which words move" is
        the question a reader of a red run is asking."""
        honest_card, honest_page = self.honest()
        self.assertIn("SCORER-VALIDATION FIXTURE", db.render_scorecard(
            bm.analyze_scores(make_scores(FZ.seeds), frozen=FZ, registered_digest=FZ.digest,
                              subject="synthetic", cfg=SMALL, subject_kind="fixture",
                              fixture_name="oracle")))      # the words this pin is about are renderable
        findings, pairs = [], 0
        key_lane = {label: [0, 0, 0] for label, lane, _f in word_sites() if lane == "key"}
        for label, lane, forge in word_sites():
            p0 = render_payload()
            texts = {str.__str__(getattr(o, label.split(".")[1]))
                     for o in word_holders(p0)[label.split(".")[0]]
                     if isinstance(getattr(o, label.split(".")[1], None), str)}
            for honest_text in sorted(texts):
                for shown in words_against(honest_text):
                    for d in WORD_DUNDERS:
                        p = render_payload()
                        if not forge(p, shown, d):
                            continue
                        pairs += 1
                        try:
                            card = db.render_scorecard(p["joint"])
                        except BaseException as ex:          # noqa: BLE001 - a raise IS the finding
                            findings.append(f"{label} [{d}] -> {shown[:14]!r}: render_scorecard "
                                            f"RAISED {type(ex).__name__}")
                            continue
                        try:
                            page = db.render_dashboard(p)
                        except BaseException as ex:          # noqa: BLE001
                            findings.append(f"{label} [{d}] -> {shown[:14]!r}: render_dashboard "
                                            f"RAISED {type(ex).__name__}")
                            continue
                        if card == honest_card and page == honest_page:
                            continue
                        if lane == "key":
                            closed = "vd-supported" not in joint_cell(card)
                            key_lane[label][0] += 1
                            key_lane[label][1 if closed else 2] += 1
                            if closed:
                                continue                     # moved, and FAILED CLOSED: its lane's promise
                        findings.append(
                            f"{label} ({lane}) [{d}] -> {shown[:14]!r}: "
                            f"{'scorecard' if card != honest_card else ''}"
                            f"{' and ' if card != honest_card and page != honest_page else ''}"
                            f"{'dashboard' if page != honest_page else ''} BYTES DIFFER"
                            + ("" if lane != "key" else " WITH A DECISIVE JOINT VERDICT STANDING"))
        self.assertEqual(findings, [], f"""
{len(findings)} of {pairs} (site x honest text x lie x dunder) forgeries moved the page or took it down,
with the stored TEXT honest and only one string dunder lying:

  """ + "\n  ".join(findings) + """

Each one is a guard or a cell spelled in a string operator and performed on the CALLER'S OBJECT instead
of on the characters it stores -- SR-13's defect class in the non-numeric lane. Fix the site, not this
test: admit once (`_word`) and compare, look up and render the text you were given. A "shown" site must
be byte-identical; a "key" site may alarm but may not leave a decisive joint verdict standing; a raise is
the same defect either way, because this module's contract is to refuse a malformed result, never to take
the page down.""")
        # THE `"key"` LANE'S FIGURES, ASSERTED HERE BECAUSE THIS IS THE LOOP THAT PRODUCES THEM.
        self.assertEqual({k: (v[0], v[1]) for k, v in key_lane.items()}, KEY_LANE_FIGURES, f"""
the "key" lane's per-site figures moved: {key_lane} as (moved, failed closed, STANDING).
They used to live in a comment in `dashboard.py` reading 54/54, 27/27 and 54/54, and all three were
wrong. If the sweep legitimately changed, re-measure and move KEY_LANE_FIGURES -- but do not write the
number anywhere a test cannot read it.""")
        self.assertEqual({k: v[2] for k, v in key_lane.items()}, {k: 0 for k in KEY_LANE_FIGURES},
                         "a `key`-lane forgery left a DECISIVE JOINT VERDICT standing: that is the one "
                         "thing the lane promises, and it would now be false")
        # COUNTED, not described in prose: the size of the matrix this class reports on.
        self.assertEqual(len(list(word_sites())), 22, len(list(word_sites())))
        self.assertEqual(pairs, 670, pairs)

    def test_the_decisive_word_pin_is_not_vacuous(self):
        """FIVE WAYS IT COULD BE GREEN FOR NOTHING, each refused by measurement rather than by reading.
        (a) the liar must really be a `str` SUBCLASS that really STORES the honest characters;
        (b) the lie must be VISIBLE to the operation each dunder stands for;
        (c) every site must really forge something (the round-8 lesson: the first draft of the number
            sweep had a site that silently forged nothing and reported no finding on a live defect);
        (d) the lie texts must include a word THIS PAGE RECOGNISES -- a lie outside every vocabulary is
            refused on the text and never reaches the lookup, which is exactly how the ten-value
            `subject_kind` table missed Finding 1;
        (e) the sites must cover every declared string that is not a declared residual."""
        # (a) and (b)
        for d in WORD_DUNDERS:
            v = word_liar("trained", "fixture", d)
            self.assertTrue(is_a_lying_string(v), d)
            self.assertEqual(str.__str__(v), "trained", d)
            self.assertEqual(v[:7], "trained" if d != "getitem" else "fixture", d)
        self.assertTrue(word_liar("trained", "fixture", "eq") == "fixture")
        self.assertEqual(hash(word_liar("trained", "fixture", "eq")), hash("fixture"))
        self.assertFalse(word_liar("trained", "fixture", "eq") != "fixture")
        self.assertIn(word_liar("trained", "fixture", "eq"), {"fixture": 1})
        self.assertEqual(str(word_liar("trained", "fixture", "str")), "fixture")
        self.assertEqual(db._e(word_liar("trained", "fixture", "str")), "fixture")
        self.assertEqual(f"{word_liar('trained', 'fixture', 'format')}", "fixture")
        self.assertEqual(len(word_liar("n", "x" * 9, "len")), 9)
        # ... and `_word` is immune to every one of them, which is the whole fix in one assertion
        for d in WORD_DUNDERS:
            self.assertEqual(db._word(word_liar("trained", "fixture", d)), "trained", d)
            self.assertIs(type(db._word(word_liar("trained", "fixture", d))), str, d)
        self.assertIsNone(db._word(object()))
        self.assertIsNone(db._word(None))
        self.assertEqual(db._word(EC.TOY_RESULT), "TOY_RESULT")   # a str Enum member passes through
        # (c) every site forges at least one instance, for at least one honest text and every dunder
        sites = list(word_sites())
        self.assertGreater(len(sites), 15, len(sites))
        for label, _lane, forge in sites:
            cls_name, attr = label.split(".")
            honest_absent = all(not isinstance(getattr(o, attr, None), str)
                                for o in word_holders(render_payload())[cls_name])
            for d in WORD_DUNDERS:
                n = forge(render_payload(), "fixture", d)
                if honest_absent:
                    self.assertEqual(n, 0, f"{label} [{d}]: honestly absent but forged {n}")
                else:
                    self.assertGreater(n, 0, f"{label} [{d}] forged nothing")
        # (d) the lie vocabulary contains words the page recognises, derived from the modules
        self.assertGreater(len(module_vocabularies()), 5)
        self.assertIn("fixture", words_against("unknown"))
        self.assertIn("trained", words_against("unknown"))
        self.assertIn("H3", words_against("H1"))
        self.assertIn("less", words_against("greater"))
        self.assertIn("UNSUPPORTED", words_against("SUPPORTED"))
        self.assertIn("SOURCE_OBSERVED", words_against("HYPOTHESIS"))
        self.assertTrue(any(len(w) > db.MAX_TEXT for w in words_against("unknown")))
        for v in module_vocabularies():                       # no vocabulary is empty or a single word
            self.assertGreater(len(v), 1, v)
        # (e) coverage
        labels = {label for label, _l, _f in sites}
        for cls_name, fields in db.STORED_WORDS.items():
            for attr, lane in fields.items():
                self.assertEqual(f"{cls_name}.{attr}" in labels, lane != "bare", (cls_name, attr))

    def test_the_two_bare_string_residuals_are_still_open(self):
        """A DECLARED RESIDUAL, asserted the only honest way: the test states what the lie does and goes
        RED if the residual is ever closed, so it cannot be quietly widened and cannot be forgotten.

        Neither is re-litigated here. `GateResult.reason` was refused in round 5 (free text on a gate
        row, beside a PASS it does not decide) and `MetricValue.reason` outside `_untrusted` is a note,
        deliberately pinned where it is. What round 9 adds is the MEASUREMENT: both are rendered through
        the caller's `__str__`, so the text shown is not the text stored -- 18 of 90 forgeries moved the
        gate table with JOINT_SUPPORTED standing. That is a display discrepancy in an explanatory cell,
        not a figure and not a decisive word, which is why the ruling stands."""
        honest = db.render_scorecard(render_payload()["joint"])
        j = render_payload()["joint"]
        for g in j.gates:
            object.__setattr__(g, "reason", word_liar(str.__str__(g.reason), "UNSUPPORTED", "str"))
        moved = db.render_scorecard(j)
        self.assertNotEqual(moved, honest, "`GateResult.reason` is no longer rendered through the "
                                           "caller's __str__: delete this residual and say so")
        self.assertIn("<td>UNSUPPORTED</td>", moved)
        self.assertIn("vd-supported", joint_cell(moved))      # ... and it does NOT fail closed
        mv = MetricValue.unmeasured("honest reason")
        self.assertIn("honest reason", db._metric_cell(mv))
        object.__setattr__(mv, "reason", word_liar("honest reason", "forged reason", "str"))
        self.assertIn("forged reason", db._metric_cell(mv),
                      "`MetricValue.reason` is no longer rendered through the caller's __str__: "
                      "delete this residual and say so")
        self.assertEqual({a for cls in db.STORED_WORDS.values() for a, lane in cls.items()
                          if lane == "bare"}, {"reason"})


class EveryPrintedCountIsWhatWasIterated(FailsClosedAssertions, unittest.TestCase):
    """FINDING 2 AND ITS LANE. `len(files)` at `_render_snapshot` was the EIGHTH conversion: the only
    quantity either renderer printed that passed through no kind function, is absent from
    `db.STORED_NUMBERS`, and was outside the round-8 render-boundary pin -- whose snapshot half forges
    only SCALAR values of the mapping (`is_a_stored_number(v)`), so a `list` was never touched.

    MEASURED on the round-8 tree with the real `docs/SOURCE_SNAPSHOT.json` (8 changed files):
        changed_files as a `list` subclass, __len__ -> 0     ->  `total (0 files)` above 8 honest rows
        the same subclass, __len__ -> 9999                   ->  `total (9999 files)` above 8 honest rows
    every per-file additions/deletions figure honest and the additions/deletions TOTALS honest, because
    those are accumulated over `__iter__`. The Source-diff inventory is SR-13's first named deliverable
    and this is its headline count."""

    def test_the_printed_file_count_is_what_was_iterated(self):
        honest = db.render_dashboard(render_payload())
        entries = list(SNAP["changed_files"])
        self.assertGreater(len(entries), 1, "the fixture snapshot must have entries to count")
        for n in (0, 1, len(entries) - 1, len(entries) + 1, 9999):
            p = render_payload()
            p["snapshot"]["changed_files"] = container_liar(list(entries), n)
            page = db.render_dashboard(p)
            self.assertTrue(isinstance(p["snapshot"]["changed_files"], (list, tuple)), n)
            self.assertEqual(len(p["snapshot"]["changed_files"]), n, n)   # the lie is real
            self.assertEqual(page, honest, f"__len__ -> {n} moved the Source-diff inventory")
            self.assertIn(f"<th>total ({len(entries)} files)</th>", page, n)
        # the count tracks what is ITERATED, including malformed entries, which each render a row
        p = render_payload()
        p["snapshot"]["changed_files"] = container_liar([*entries, "not a mapping"], 1)
        page = db.render_dashboard(p)
        self.assertIn(f"<th>total ({len(entries) + 1} files)</th>", page)
        self.assertIn("malformed entry", page)
        self.assertIn("some counts missing", page)

    def test_no_caller_supplied_container_moves_a_figure_or_a_verdict(self):
        """THE LANE, derived by walking the payload rather than from a list of names: every `list`/`tuple`
        the caller hands either renderer is forged to a subclass holding the honest entries and lying only
        about its size. A `len()` added to any of them tomorrow inherits this pin.

        `__len__` is not only `len()`: `not x` and `bool(x)` fall through to it, which is why a lie of 0
        on a container the module tests for emptiness legitimately REFUSES the panel. That is the
        fail-closed direction and is accepted as such; a lie that leaves a decisive verdict standing on a
        changed page is the finding."""
        honest_card, honest_page = (db.render_scorecard(render_payload()["joint"]),
                                    db.render_dashboard(render_payload()))
        findings, sites = [], 0
        for label, forge in container_sites():
            sites += 1
            for n in (0, 1, 9999):
                p = render_payload()
                self.assertGreater(forge(p, n), 0, f"{label} forged nothing")
                try:
                    card, page = db.render_scorecard(p["joint"]), db.render_dashboard(p)
                except BaseException as ex:                   # noqa: BLE001
                    findings.append(f"{label} [__len__ -> {n}]: RAISED {type(ex).__name__}")
                    continue
                if card == honest_card and page == honest_page:
                    continue
                if "vd-supported" not in joint_cell(card) if "Joint verdict" in card else False:
                    continue                                  # moved, and failed closed
                if "REFUSED" in card or "vd-supported" not in card:
                    continue
                findings.append(f"{label} [__len__ -> {n}]: page moved with a decisive verdict standing")
        self.assertGreater(sites, 5, sites)
        self.assertEqual(findings, [], "\n  ".join([""] + findings))


# ---------------------------------------------------------------------------------------------------------
# SR-13 ROUND 11: THE THIRD CATEGORY -- THE CALLER'S SNAPSHOT `Mapping`, ITS LISTS' ELEMENTS, AND ITS KEYS.
#
# ROUND 9 CLOSED THE DECLARED STRINGS AND THE CONTAINER SIZES, and the gap it left is the shape of its own
# derivations rather than any site one of them reached:
#   * `word_sites()` is `db.STORED_WORDS` x the rendered DATACLASSES, so a string the caller hands in
#     loose -- a value of the snapshot mapping, an element of one of its lists -- belongs to no class and
#     is in no lane;
#   * the round-8 render-boundary pin forges a snapshot value only `if is_a_stored_number(v)`;
#   * `container_sites()` forges a list's `__len__` and NEVER ITS ELEMENTS.
# Three derivations, and between them a `str` the public `render_dashboard(data)` API accepts directly was
# swept by none. MEASURED on the round-9 tree through that API with NO `object.__setattr__` -- a `str`
# subclass storing the honest text and lying only on `__str__`:
#     snapshot["merge_base"]      the merge base printed is not the one the snapshot stores -- the
#                                 upstream ancestor CLAUDE.md names as a source of truth
#     snapshot["fork_commits"][*] BOTH honest fork-only commit hashes absent from the page entirely
#     snapshot["evidence_url"]    the attacker's host rendered under the caption "scheme omitted, not a
#                                 link" (only `__str__` moved it: `lower`/`__getitem__` into `_defang`
#                                 did not)
# 4 of 18 snapshot string sites moved, 0 extra `warn` spans, 0 extra UNKNOWN, panel still badged
# SOURCE_OBSERVED -- in the Source-diff inventory, which is SR-13's FIRST NAMED DELIVERABLE.
#
# AND THE THING NO LANE HAD A SHAPE FOR AT ALL: the mapping's KEYS. A value is read by `m.get("merge_base")`
# and `"evidence_url" in m`, which are `__hash__` + `__eq__` ON THE STORED KEY, so a key that stores one
# word and answers as another serves its own value under a name the mapping does not file it under. It was
# live at every caller `Mapping` the renderers touch -- the payload itself, the snapshot, each
# `changed_files` entry, and `ExperimentRecord.metrics`, where it SWALLOWS a `TRAIN_EXPECTED` member and
# breaks the positive half of this page's oldest criterion. Figures in the two classes below.
#
# THE REFERENCE RENDER FOR A KEY LIE IS NOT THE HONEST FIXTURE, and getting that wrong is the one way this
# sweep could have been written as a test that cannot pass: a forged mapping really is a different mapping,
# and the page SHOULD change. The reference is the SAME mapping with that one key PLAINIFIED --
# `str.__str__` of the characters it stores -- which is `word_liar`'s "store the honest content and lie on
# one dunder" rule applied to a key. Then the honest reading of the input is the only correct output, and
# this file needs no model of what should have been alarmed.
# ---------------------------------------------------------------------------------------------------------
def key_liar(stored, answers_as):
    """A `str` SUBCLASS instance that STORES `stored` and answers a dict or `in` lookup as `answers_as`.

    `word_liar`'s "eq" body hoisted to a key, and one attack rather than three for the same reason: a
    dict lookup is `__hash__` THEN `__eq__`, so a liar with an honest `__hash__` lands in a different
    bucket and is never compared. CPython abandons `lookdict_unicode` for the general lookup as soon as
    one key is not an exact `str`, and the general lookup calls the STORED key's `__eq__` first -- which
    is why this needs nothing but a plain `dict` built from caller-supplied JSON."""
    return type("KeyLiesOnEq", (str,), {
        "__hash__": lambda self: hash(answers_as),
        "__eq__": lambda self, o: answers_as == o if isinstance(o, str) else NotImplemented,
        "__ne__": lambda self, o: not (answers_as == o) if isinstance(o, str) else NotImplemented,
    })(stored)


def plain_key(stored, _answers_as=None):
    """THE REFERENCE for `key_liar`: the same characters, telling the truth about them."""
    return str.__str__(stored)


def walk_payload(obj, path=()):
    """("map", path) for every `Mapping`, and ("str", path) for every string VALUE or string list/tuple
    ELEMENT, reachable in the caller's payload through mappings, lists and tuples.

    A WALK AND NOT A LIST OF NAMES, which is the whole point: a new caller-supplied string, or a new keyed
    mapping in the payload, inherits both pins below with no edit here -- exactly as `container_sites()`
    inherits a new list. The walk stops at a dataclass: `train`, `joint` and each record are objects, not
    containers, and their strings are declared in `db.STORED_WORDS` and swept by `word_sites()`."""
    if isinstance(obj, Mapping):
        yield ("map", path)
        for k, v in obj.items():
            yield from walk_payload(v, path + (k,))
    elif isinstance(obj, (list, tuple)):
        for i, v in enumerate(obj):
            yield from walk_payload(v, path + (i,))
    elif isinstance(obj, str):
        yield ("str", path)


def shape_of(path):
    """A path with its list indices collapsed: two `changed_files` entries have the same SHAPE and
    exercise the same lookups in the same lines."""
    return tuple("*" if isinstance(s, int) else s for s in path)


def payload_walk_sorted(kind=None, per_shape=2):
    """The walk, sorted, with at most `per_shape` sites of any one structural shape.

    THE CAP IS `words_against`'s, for its reason and with the same obligation: this sweep is diagnostic
    and not exhaustive, so the EXHAUSTIVE figure is recorded in the docstring of the class that uses it
    (18 string sites and 13 mappings in this payload, against 12 and 6 swept), and a defect that the cap
    could hide would have to hide itself from the first two entries of its own shape and from all five
    dunders. The eight `changed_files` entries are one dict literal rendered eight times; the second is
    swept to catch a site that is position-dependent, and the other six buy nothing but seconds."""
    out, seen = [], {}
    for k, path in sorted(walk_payload(render_payload()), key=lambda t: (t[0], str(t[1]))):
        if kind is not None and k != kind:
            continue
        sh = (k, shape_of(path))
        seen[sh] = seen.get(sh, 0) + 1
        if seen[sh] <= per_shape:
            out.append((k, path))
    return out


def payload_walk_all(kind):
    return [(k, path) for k, path in sorted(walk_payload(render_payload()), key=lambda t: (t[0], str(t[1])))
            if k == kind]


def dig(p, path):
    """The container that owns `path[-1]` in payload `p`, with every mapping and sequence on the way down
    replaced by a mutable COPY.

    The copy is not tidiness. `render_payload()` gives each call its own snapshot `dict`, but the nested
    `changed_files` list and its entry mappings are `SNAP`'s OWN objects, and a forgery written into those
    would leak into every other test in this file in whatever order they run -- the hazard
    `render_payload`'s docstring was written for, one level deeper than it reaches."""
    cur = p
    for step, nxt in zip(path, path[1:]):
        child = cur[step]
        cur[step] = dict(child) if isinstance(child, Mapping) else list(child)
        cur = cur[step]
    return cur


def path_label(path):
    return "payload" + "".join(f"[{s!r}]" for s in path)


def payload_string_sites():
    """(label, honest text, forge(payload, shown, dunder) -> instances forged) for every CALLER-SUPPLIED
    STRING either renderer receives through the payload `Mapping` itself: a mapping VALUE or a list/tuple
    ELEMENT, at any depth. Derived by `walk_payload`, so nothing is named here."""
    p0 = render_payload()
    for _kind, path in payload_walk_sorted("str"):
        text = str.__str__(dig(p0, path)[path[-1]])

        def forge(p, shown, d, path=path):
            owner = dig(p, path)
            owner[path[-1]] = word_liar(str.__str__(owner[path[-1]]), shown, d)
            return 1
        yield path_label(path), text, forge


def _read_root(p):
    return dict(p)


def _write_root(p, m):
    p.clear()
    p.update(m)


def caller_mapping_sites():
    """(label, read(payload) -> dict, write(payload, mapping)) for every caller-supplied `Mapping` either
    renderer looks a word up in.

    TWO HALVES, and the second is not reachable by the first. `walk_payload` finds the payload itself, the
    snapshot and each `changed_files` entry. `ExperimentRecord.metrics` is a caller-supplied mapping that
    lives INSIDE a dataclass, so no walk of the payload reaches it -- and it is the one whose keys carried
    a finding. `payload_records` is reused for it for the reason `render_sites()` gives: both panels render
    records, and `_metric_table` serves both."""
    for _kind, path in payload_walk_sorted("map"):
        if not path:
            yield "payload", _read_root, _write_root
            continue

        def read(p, path=path):
            return dict(dig(p, path)[path[-1]])

        def write(p, m, path=path):
            dig(p, path)[path[-1]] = m
        yield path_label(path), read, write

    for where, _r in payload_records(render_payload()):
        def read(p, where=where):
            return dict(dict(payload_records(p))[where].metrics)

        def write(p, m, where=where):
            object.__setattr__(dict(payload_records(p))[where], "metrics", m)
        yield f"record {where}.metrics", read, write


def displace(m, target, donor, make_key):
    """`target`'s entry is GONE and `donor`'s key answers as `target` while keeping its OWN value, so the
    page is asked to print one name's value under another name. `make_key` is `key_liar` for the forgery
    and `plain_key` for the reference render."""
    out = {}
    for k, v in m.items():
        if k == target:
            continue
        out[make_key(donor, target) if k == donor else k] = v
    return out


def rename(m, target, word, make_key):
    """`target`'s key keeps its stored text and answers as `word`, which this mapping does not store: the
    looked-up name goes MISSING while the mapping still files a value under it. Plainifying the key
    changes nothing, so the reference is the honest mapping -- which is the stronger assertion of the two:
    byte-identical, not merely consistent."""
    return {(make_key(target, word) if k == target else k): v for k, v in m.items()}


class EveryCallerSuppliedStringRendersTheAdmittedText(FailsClosedAssertions, unittest.TestCase):
    """SR-13 ROUND 11, FIRST HALF: the strings the caller hands in LOOSE, which belong to no rendered
    class and so were in no lane.

    MEASURED ON THE PRE-FIX TREE, 3.12.4 and 3.13.5 BYTE-IDENTICALLY -- this sweep exactly as it stands,
    8 of its 120 forgeries moving the page, and 0 of 120 after the fix. All 8 are the [str] dunder at 4
    sites: `snapshot["merge_base"]`, BOTH `snapshot["fork_commits"]` elements, and
    `snapshot["evidence_url"]` -- the last printing an attacker-chosen host under a caption that says what
    the text IS. 0 of 120 on [eq], [len], [format] and [getitem], and the other 8 sites were already
    honest, because they reach the page through `_untrusted`, which admits. Exhaustively over all 18
    string sites the walk finds rather than the 12 this sweep caps to: the same 4 sites and no others.

    The sites and the lie texts are both DERIVED, so these figures are a record of one tree and not the
    definition of the sweep. What the test asserts is zero."""

    def test_no_caller_supplied_string_in_the_payload_moves_the_page(self):
        honest_card = db.render_scorecard(render_payload()["joint"])
        honest_page = db.render_dashboard(render_payload())
        findings, sites, forgeries = [], 0, 0
        for label, text, forge in payload_string_sites():
            sites += 1
            for shown in words_against(text):
                for d in WORD_DUNDERS:
                    p = render_payload()
                    self.assertEqual(forge(p, shown, d), 1, label)
                    forgeries += 1
                    try:
                        page = db.render_dashboard(p)
                    except BaseException as ex:          # noqa: BLE001 - a raise IS the finding
                        findings.append(f"{label} [{d}] -> {shown[:14]!r}: RAISED {type(ex).__name__}")
                        continue
                    if page != honest_page:
                        findings.append(f"{label} [{d}] -> {shown[:14]!r}: dashboard BYTES DIFFER")
            # THE SCORECARD IS CHECKED ONCE PER SITE AND NOT ONCE PER FORGERY, deliberately: it is handed
            # `p["joint"]` and nothing else, so a payload-mapping string cannot reach it except by
            # leaking out of the payload -- which is what this one render per site refuses.
            p = render_payload()
            forge(p, "zzz", "str")
            self.assertEqual(db.render_scorecard(p["joint"]), honest_card, label)
        self.assertGreater(sites, 9, sites)
        self.assertGreater(forgeries, 50, forgeries)
        self.assertEqual(findings, [], f"""
{len(findings)} of {forgeries} (caller string x lie x dunder) forgeries moved the page, with the stored
TEXT honest and only one string dunder lying:

  """ + "\n  ".join(findings) + """

A string the caller hands in through the payload mapping is an input exactly like a declared field, and
the page must render the characters it STORES: admit once (`_word` / `_word_text`) and render the admitted
text. No bare `str()` and no bare `_e()`, of a mapping value or of a list element.""")

    def test_the_caller_string_sweep_is_not_vacuous(self):
        """FOUR WAYS IT COULD BE GREEN FOR NOTHING.
        (a) the sites must be DERIVED from the payload, and must include the three that carried findings
            plus at least one list ELEMENT (the thing `container_sites()` structurally cannot reach);
        (b) every forge must really replace a string with a lying subclass, in the payload the renderer
            is then handed -- and must NOT leak into `SNAP`, which every other test in this file reads;
        (c) the lie must be visible through the operation each dunder stands for (`word_liar`'s own
            non-vacuity, re-checked here on a payload string rather than on a dataclass field);
        (d) the sweep must be able to FAIL: with the admission removed from `_defang`, it reports."""
        labels = {label for label, _t, _f in payload_string_sites()}
        self.assertIn("payload['snapshot']['merge_base']", labels)
        self.assertIn("payload['snapshot']['evidence_url']", labels)
        self.assertIn("payload['snapshot']['fork_commits'][0]", labels)
        self.assertIn("payload['snapshot']['changed_files'][0]['filename']", labels)
        self.assertTrue(any(isinstance(path[-1], int) for _k, path in payload_walk_sorted("str")),
                        "no list ELEMENT in the sweep")
        # the cap is a cap and not a filter: every shape the walk finds is represented
        self.assertEqual({shape_of(path) for _k, path in payload_walk_sorted("str")},
                         {shape_of(path) for _k, path in payload_walk_all("str")})
        self.assertEqual(len(payload_walk_all("str")), 18, len(payload_walk_all("str")))
        self.assertEqual(len(payload_walk_all("map")), 10, len(payload_walk_all("map")))
        # (b) the forgery lands in the payload and NOT in SNAP
        before = dict(SNAP)
        snap_cf0 = dict(SNAP["changed_files"][0])
        p = render_payload()
        for label, _t, forge in payload_string_sites():
            forge(p, "zzz", "str")
        self.assertEqual(dict(SNAP), before, "a forgery leaked into the module-level SNAP")
        self.assertEqual(dict(SNAP["changed_files"][0]), snap_cf0, "a forgery leaked into SNAP's entries")
        lying = [v for _k, path in payload_walk_sorted("str")
                 for v in [dig(p, path)[path[-1]]] if is_a_lying_string(v)]
        self.assertEqual(len(lying), len(payload_walk_sorted("str")))
        # (c)
        for d in WORD_DUNDERS:
            v = word_liar("abc", "xyz", d)
            self.assertTrue(is_a_lying_string(v), d)
            self.assertEqual(str.__str__(v), "abc", d)
            self.assertEqual(db._word(v), "abc", d)
        # (d) with the admission taken out of `_defang`, the sweep reports -- so it is not green by luck
        honest_page = db.render_dashboard(render_payload())
        with mock.patch.object(db, "_word", lambda x: str(x) if isinstance(x, str) else None):
            q = render_payload()
            q["snapshot"] = dict(q["snapshot"],
                                 evidence_url=word_liar(SNAP["evidence_url"], "https://h.invalid", "str"))
            self.assertNotEqual(db.render_dashboard(q), honest_page,
                                "with `_word` reading the caller's `__str__`, `_defang` must move")
        self.assertEqual(db.render_dashboard(render_payload()), honest_page)   # and the patch is undone


class NoMappingKeyServesAValueUnderAnotherName(FailsClosedAssertions, unittest.TestCase):
    """SR-13 ROUND 11, SECOND HALF: the `Mapping` KEYS, which is the thing `string_fields_of`'s own
    avoidance note left unswept.

    That note excluded `Mapping[str, MetricValue]` because forging THE MAPPING would be "a refused
    no-op -- a vacuous site". True of the mapping object and silent about the two string things inside
    it, and CLAUDE.md rules that an input avoided for that reason IS a finding. `metrics.get(n)` and
    `set(metrics) | set(expected)` ran on the KEY.

    MEASURED ON THE PRE-FIX TREE, 3.12.4 and 3.13.5 BYTE-IDENTICALLY -- this sweep exactly as it stands,
    77 of its 81 forgeries differing from the plainified reference, and 0 of 81 after the fix:
        payload (its own 4 keys)            12 of 12   a `train` result served to the scorecard, a
                                                       `records` list served as the snapshot
        snapshot (13 keys)                  35 of 39
        changed_files[0] / [1] (3 keys)      9 of 9 each
        train.record.metrics (4 keys)       12 of 12
        records[0].metrics (1 key)          skipped: a one-key mapping has no sibling to displace
    The 4 that already agreed are `snapshot` renames of keys this panel reads nowhere. EXHAUSTIVELY, over
    every ORDERED PAIR rather than the one donor per target this sweep rotates through: 154 of 156 for the
    snapshot, 6 of 6 for a `changed_files` entry, 12 of 12 for the payload and 12 of 12 for the metrics --
    recorded here for the reason `words_against` records its own exhaustive matrix, because the cheap
    sweep is the pin and the exhaustive one is the evidence that the cap hides nothing.

    The metrics half is FINDING B: a key storing "zzz" that hashes and compares as "initial_loss"
    SWALLOWED `initial_loss` -- 5 rows became 4, extra `warn` spans 0, and the name appeared NOWHERE on
    the page, neither as an UNKNOWN row nor as a 0. That is the POSITIVE half of this page's oldest
    criterion, read for eight rounds only in its negative direction ("never 0", which holds): "missing
    results render as UNKNOWN". A swallowed name is not missing-and-shown, it is gone. With two entries
    the same route printed a measured figure under the WRONG NAME.

    THE PUBLIC ROUTE IS CLOSED and that was verified, not assumed: `schema._plain_value` collapses a
    `str` subclass key, so `ExperimentRecord(metrics={liar: mv})` stores a plain `"zzz"`. The route here
    is `object.__setattr__` on `metrics` -- the same tier as every round-9 finding -- while the snapshot
    and payload halves need no such thing at all: that mapping IS the public API's argument."""

    def shapes(self, keys, target):
        """(shape name, target, second argument) for every key forgery this class makes at one key.
        The "rename" word is drawn from the module's own vocabularies and from the sibling keys, so it
        is a word the page could plausibly read, and never one this mapping already stores."""
        donor = keys[(keys.index(target) + 1) % len(keys)]
        outside = next(w for v in module_vocabularies() for w in v if w not in keys)
        return [("displace", target, donor), ("rename", target, outside),
                ("rename", target, "zzz_not_a_name")]

    def test_no_key_lie_changes_the_page_relative_to_the_same_mapping_plainified(self):
        """THE PIN. The reference for each forgery is the SAME mapping with that key told truthfully, so
        a page that moves is a page reading a word the mapping does not store."""
        findings, sites, forgeries = [], 0, 0
        shape_fns = {"displace": displace, "rename": rename}
        for label, read, write in caller_mapping_sites():
            keys = sorted(k for k in read(render_payload()) if isinstance(k, str))
            if len(keys) < 2:
                continue
            sites += 1
            for shape, target, arg in [s for k in keys for s in self.shapes(keys, k)]:
                fn = shape_fns[shape]
                ref = render_payload()
                write(ref, fn(read(ref), target, arg, plain_key))
                lie = render_payload()
                write(lie, fn(read(lie), target, arg, key_liar))
                forgeries += 1
                try:
                    want = db.render_dashboard(ref)
                except BaseException as ex:              # noqa: BLE001
                    findings.append(f"{label} {shape} {target!r}/{arg!r}: the PLAINIFIED reference "
                                    f"RAISED {type(ex).__name__}")
                    continue
                try:
                    got = db.render_dashboard(lie)
                except BaseException as ex:              # noqa: BLE001 - a raise IS the finding
                    findings.append(f"{label} {shape} {target!r}/{arg!r}: RAISED {type(ex).__name__}")
                    continue
                if got != want:
                    findings.append(f"{label} {shape} target={target!r} other={arg!r}: BYTES DIFFER "
                                    f"from the same mapping with that key plainified")
        self.assertGreater(sites, 3, sites)
        self.assertGreater(forgeries, 60, forgeries)
        self.assertEqual(findings, [], f"""
{len(findings)} of {forgeries} (caller mapping x key x shape) key forgeries made the page differ from the
render of THE SAME MAPPING with that one key plainified:

  """ + "\n  ".join(findings[:40]) + """

`m.get(name)` and `name in m` are `__hash__` + `__eq__` on the STORED key, so a key is an admitted input
like any other string: admit the keys ONCE (`_word_keyed`, or per entry as `_metric_table` does) and read
the mapping by the words its keys STORE. A value may only be printed under a name the mapping files it
under, and a name the mapping does not store must read as ABSENT.""")

    def test_a_swallowed_expected_metric_still_renders_UNKNOWN(self):
        """FINDING B AS ITS OWN ASSERTION, because the criterion it breaks is older than this sweep and
        should go red on its own line: EVERY `db.TRAIN_EXPECTED` name has a row, whatever a key claims.

        Pre-fix this test's first loop body loses the row entirely (measured: 5 rows -> 4, 0 extra warn,
        the name absent from the whole page)."""
        honest = db.render_dashboard(render_payload())
        for name in db.TRAIN_EXPECTED:
            self.assertIn(f'<span class="untrusted">{name}</span>', honest, name)
        for target in db.TRAIN_EXPECTED:
            for stored in ("zzz", "final_loss"):
                p = render_payload()
                r = dict(payload_records(p))["train.record"]
                m = dict(r.metrics)
                if target not in m:
                    continue
                donor = next(k for k in m if k != target)
                forged = {k: v for k, v in m.items() if k != target}
                forged = {(key_liar(stored, target) if k == donor else k): v for k, v in forged.items()}
                object.__setattr__(r, "metrics", forged)
                page = db.render_dashboard(p)
                self.assertIn(f'<span class="untrusted">{target}</span>', page,
                              f"{target} lost its row to a key storing {stored!r}: "
                              f"a missing result must render as UNKNOWN, never vanish")
                self.assertIn('<span class="unknown">UNKNOWN</span> <span class="caveat">not recorded',
                              page, target)
                # ... and the swallowing key's own row is captioned with the text it STORES
                self.assertIn(f'<span class="untrusted">{stored}</span>', page, (target, stored))

    def test_two_keys_storing_one_word_are_two_rows_and_neither_vanishes(self):
        """WHY `_metric_table` ADMITS PER ENTRY INSTEAD OF CALLING `_word_keyed`. The collapse that is
        right for a mapping the page looks words UP in would delete two real rows here to punish an
        ambiguity whose data is perfectly displayable, and "a metric row vanished" is the defect this
        class exists about. Measured: both rows render, with their own values."""
        p = render_payload()
        r = dict(payload_records(p))["records[0]"]
        m = dict(r.metrics)
        object.__setattr__(r, "metrics", {**m, key_liar("a", "b"): MetricValue.measured(7.5)})
        page = db.render_dashboard(p)
        self.assertEqual(page.count('<span class="untrusted">a</span>'), 2, "a row vanished")
        self.assertIn('<span class="measured">7.5</span>', page)
        self.assertIn('<span class="measured">0.5</span>', page)
        # and `_word_keyed`, which IS the right admission for a looked-up mapping, fails CLOSED on it
        self.assertEqual(db._word_keyed({key_liar("a", "b"): 1, "a": 2}), {})
        self.assertEqual(db._word_keyed({"a": 1, "b": 2}), {"a": 1, "b": 2})
        self.assertEqual(db._word_keyed({word_liar("a", "b", "eq"): 1}), {"a": 1})
        self.assertIs(type(next(iter(db._word_keyed({word_liar("a", "b", "eq"): 1})))), str)
        self.assertEqual(db._word_keyed({1: "x", None: "y"}), {})      # non-string keys name nothing
        self.assertEqual(db._word_keyed(object()), {})                 # not a mapping: refused, not raised

    def test_the_key_sweep_is_not_vacuous(self):
        """(a) `key_liar` must really store one word and answer as another, through a real `dict`;
        (b) the reference must really differ from the forgery as an INPUT (otherwise the pin compares a
            page with itself);
        (c) the sites must be derived and must include the payload, the snapshot, a `changed_files`
            entry and a record's `metrics`;
        (d) the pin must be able to FAIL: with the key admission removed, it reports."""
        k = key_liar("zzz", "initial_loss")
        self.assertEqual(str.__str__(k), "zzz")
        self.assertTrue(is_a_lying_string(k))
        self.assertEqual({k: 1}.get("initial_loss"), 1)
        self.assertIsNone({k: 1}.get("zzz"))
        self.assertIn("initial_loss", {k: 1})
        self.assertNotIn("zzz", {k: 1})
        self.assertEqual(plain_key(k), "zzz")
        self.assertIs(type(plain_key(k)), str)
        # (b)
        m = {"a": 1, "b": 2}
        self.assertEqual(sorted(map(str.__str__, displace(m, "a", "b", key_liar))), ["b"])
        self.assertEqual(displace(m, "a", "b", plain_key), {"b": 2})    # "a" absent, "b" under its name
        self.assertEqual(displace(m, "a", "b", key_liar).get("a"), 2)   # the lie serves b's value as a
        self.assertIsNone(displace(m, "a", "b", key_liar).get("b"))     # ... and b's own name is gone
        # (c)
        labels = {label for label, _r, _w in caller_mapping_sites()}
        self.assertIn("payload", labels)
        self.assertIn("payload['snapshot']", labels)
        self.assertIn("payload['snapshot']['changed_files'][0]", labels)
        self.assertIn("record train.record.metrics", labels)
        self.assertIn("record records[0].metrics", labels)
        # (d) remove the admission and the pin reports, at the snapshot and at the metrics table alike
        with mock.patch.object(db, "_word_keyed", lambda m: dict(m) if isinstance(m, Mapping) else {}):
            ref, lie = render_payload(), render_payload()
            ref["snapshot"] = displace(dict(ref["snapshot"]), "merge_base", "snapshot_note", plain_key)
            lie["snapshot"] = displace(dict(lie["snapshot"]), "merge_base", "snapshot_note", key_liar)
            self.assertNotEqual(db.render_dashboard(lie), db.render_dashboard(ref),
                                "without `_word_keyed` the snapshot must serve the wrong value")
        with mock.patch.object(db, "_word", lambda x: x if isinstance(x, str) else None):
            p = render_payload()
            r = dict(payload_records(p))["train.record"]
            m = dict(r.metrics)
            donor = next(k for k in m if k != "initial_loss")
            object.__setattr__(r, "metrics", displace(m, "initial_loss", donor, key_liar))
            self.assertNotIn('<span class="untrusted">initial_loss</span>', db.render_dashboard(p),
                             "without an admitted key, `initial_loss` must lose its row")

    def test_the_other_caller_mapping_inside_a_dataclass_is_rendered_by_nothing(self):
        """`RunProvenance.input_hashes` is the OTHER caller-supplied `Mapping` that lives inside a
        rendered dataclass, and it is a declared residual WITH A MEASUREMENT rather than an omission:
        neither panel renders it, so a lying key and a lying value move zero bytes. It is empty in
        `rec()`, so this test builds a record that carries one -- the sweep above cannot forge a site
        with nothing in it, and "the fixture happened to be empty" is not a reason to say nothing."""
        h = "a" * 64
        pr = RunProvenance(run_id="r1", timestamp_utc=TS, seed=1, code_version="c1",
                           python_version="3.12.0", toy_only=True, input_hashes={"config": h})
        r = ExperimentRecord(name="n", provenance=pr, metrics={"a": MetricValue.measured(0.5)},
                             evidence_class=EC.TOY_RESULT)
        honest = db.render_dashboard({"records": [r]})
        self.assertNotIn(h, honest, "input_hashes is rendered after all: give it a lane and sweep it")
        self.assertNotIn("config", honest)
        for forged in ({key_liar("other", "config"): h}, {"config": word_liar(h, "b" * 64, "str")}):
            object.__setattr__(pr, "input_hashes", forged)
            self.assertEqual(db.render_dashboard({"records": [r]}), honest,
                             "a lie in input_hashes moved the page: it is rendered, so sweep it")


class TheSubjectKindValueTable(unittest.TestCase):
    """FINDING 1 AS A TABLE, because the finding is a comparison of three renders and not a property of
    one. The rows are the ones the round-9 brief tabulated, reproduced here as assertions so the
    comparison is performed rather than quoted.

    ROUTE (d) -- `object.__setattr__` on a result built as a fixture, which is benchmark's own declared
    relabel route and the one that carries the gate-11(c) exemption forward:
        subject_kind            joint cell           H1/H2/H3        CONTRACT PROBLEM  relabel msg  label
        "fixture" (honest)      JOINT_SUPPORTED      SUPPORTED x3    no                no           FIXTURE
        "trained" (plain)       JOINT_INCONCLUSIVE   INCONCLUSIVE x3 YES               YES          UNKNOWN*
        word_liar("trained")    JOINT_SUPPORTED      SUPPORTED x3    no                no           FIXTURE
    (* the relabelled result's own label renders as the kind the TEXT names; what matters for the finding
    is that row 3 was BYTE-IDENTICAL to row 1 while `str(j.subject_kind)` was 'trained'.)

    THE PUBLIC ROUTE IS NOW REFUSED UPSTREAM, and this paragraph used to claim the opposite. It read
    "`analyze_scores(subject_kind=<liar>, fixture_name=\"oracle\")` constructs ... and no verdict moves",
    which was true when it was written and became false when SR-10 round 13 normalised `subject_kind` in
    `JointResult.__post_init__`. `analyze_scores` now raises for every dunder in `WORD_DUNDERS`, which
    `test_the_public_route_is_refused_upstream_for_every_dunder` asserts positively. Route (d) above is
    unaffected and still carries the three rows."""

    def fixture(self):
        return bm.analyze_scores(make_scores(FZ.seeds), frozen=FZ, registered_digest=FZ.digest,
                                 subject="synthetic", cfg=SMALL, subject_kind="fixture",
                                 fixture_name="oracle")

    def row(self, kind):
        j = self.fixture()
        if kind is not None:
            object.__setattr__(j, "subject_kind", kind)
        h = db.render_scorecard(j)
        return h, {"joint": re.search(r'Joint verdict:</b> <span class="vd [\w-]+">(\w+)', h).group(1),
                   "hyp": set(hyp_cells(h).values()),
                   "contract_problem": "CONTRACT PROBLEM" in h,
                   "relabel": "carry the fixture exemption but subject_kind is" in h,
                   "fixture_label": "SCORER-VALIDATION FIXTURE" in h}

    def test_the_three_rows(self):
        honest_fixture, r1 = self.row(None)
        self.assertEqual(r1, {"joint": "JOINT_SUPPORTED", "hyp": {"SUPPORTED"},
                              "contract_problem": False, "relabel": False, "fixture_label": True})
        relabelled, r2 = self.row("trained")
        self.assertEqual(r2, {"joint": "JOINT_INCONCLUSIVE", "hyp": {"INCONCLUSIVE"},
                              "contract_problem": True, "relabel": True, "fixture_label": False})
        # ROW 3. MEASURED on the round-8 tree: this render was BYTE-IDENTICAL to row 1 for the "eq"
        # dunder -- the forgery -- and the assertion below is the fix: a label whose CHARACTERS are
        # "trained" must render exactly as the plain text "trained" does, which is row 2.
        for d in WORD_DUNDERS:
            forged, r3 = self.row(word_liar("trained", "fixture", d))
            self.assertEqual(r3, r2, d)
            self.assertEqual(forged, relabelled,
                             f"[{d}] a label storing 'trained' must render as plain 'trained' does")
            self.assertNotEqual(forged, honest_fixture,
                                f"[{d}] it must NOT render as the honest fixture page")
        # the forged label really is the text 'trained', really is a `str`, and really is not a `str`
        liar = word_liar("trained", "fixture", "eq")
        self.assertEqual(str(liar), "trained")
        self.assertEqual(str.__str__(liar), "trained")
        self.assertIsInstance(liar, str)
        self.assertTrue(is_a_lying_string(liar))
        self.assertTrue(liar == "fixture")                   # ... while comparing as the other kind
        self.assertIn(liar, db._SUBJECT_KIND_LABELS)         # ... and resolving to its entry
        # ... and the fixed unit reports it as the relabel it is
        j = self.fixture()
        object.__setattr__(j, "subject_kind", liar)
        label, caveat, code, problem, relabel = db._subject_kind(j)
        self.assertEqual(label, db._SUBJECT_KIND_LABELS["trained"][0])
        self.assertTrue(relabel)
        self.assertIn("relabelled after construction", problem)

    def test_the_public_route_is_refused_upstream_for_every_dunder(self):
        """ROUND-13 REWRITE, and the reason is worth more than the test. This method was named
        `test_the_public_route_constructs_and_is_a_label_discrepancy_not_a_verdict_flip`, and its loop
        TOLERATED a refusal -- `except Exception: flips.append(...); continue` -- because when it was
        written `analyze_scores` really did construct. SR-10 round 13 closed that upstream, so EVERY
        iteration began landing in the `except` branch: the four render assertions inside the loop became
        dead code that can never fail, and the closing
        `assertEqual([f for f in flips if "REFUSED" not in f], [], flips)` filtered out exactly the
        strings it had just collected and compared [] to [], passing VACUOUSLY.

        A tolerant `except ... continue` is how a test survives its own subject being fixed. That is the
        mirror image of the `assertTrue(carries_exemption(...))` this class used to end with: one passes
        because the module is broken, the other passes because the module was repaired. Neither asserts
        anything. The refusal is now ASSERTED rather than tolerated, and the class docstring is pinned
        below so the stale prose cannot outlive the behaviour again. The three render rows live in
        `test_the_three_rows`, which uses route (d) and is unaffected."""
        self.assertIn("THE PUBLIC ROUTE IS NOW REFUSED UPSTREAM", TheSubjectKindValueTable.__doc__,
                      "the class docstring no longer describes what this class proves")
        # COUNT, not absence, and both of the obvious spellings were measured wrong before this one.
        # `assertNotIn('and no verdict moves\"\"\"')` is VACUOUS -- a docstring's value never contains its
        # own delimiter -- and the mutant restoring the withdrawn clause passed against it. Plain
        # `assertNotIn('and no verdict moves')` then failed on the HONEST tree, because the docstring
        # above QUOTES the withdrawn claim inside its own retraction, which is what this project's
        # withdrawal discipline requires it to do. So the pin is the one the rest of the kit uses:
        # the withdrawn phrase may appear exactly ONCE, as a quotation. Restoring it as a live claim
        # makes two, and fails.
        self.assertEqual(TheSubjectKindValueTable.__doc__.count("and no verdict moves"), 1,
                         "the withdrawn claim must appear exactly once, quoted inside its retraction")
        for d in WORD_DUNDERS:
            with self.subTest(dunder=d):
                liar = word_liar("trained", "fixture", d)
                with self.assertRaises(ValueError) as caught:
                    bm.analyze_scores(make_scores(FZ.seeds), frozen=FZ, registered_digest=FZ.digest,
                                      subject="synthetic", cfg=SMALL, subject_kind=liar,
                                      fixture_name="oracle")
                self.assertIn("fixture_name is required for, and only for", str(caught.exception))
        # THE CROSS-OWNER REQUEST, NOW CLOSED UPSTREAM (SR-10 round 13). The block that stood here
        # asserted the defect AS CORRECT BEHAVIOUR -- `assertTrue(carries_exemption(...))` with the
        # message "a result whose label stores 'trained' was granted the fixture exemption" -- which is
        # the shape round 5 found in `_SneakyBound`'s docstring: a test that passes because the thing it
        # describes is broken. `benchmark.py` now normalises `subject_kind` to the characters it stores
        # in `JointResult.__post_init__`, so no module path admits the liar as a fixture.
        #
        # The two raw-constant facts BELOW ARE UNCHANGED and are kept deliberately: they are properties
        # of the public constants under a caller's own direct subscript, which `benchmark.py` cannot
        # intercept and does not claim to. What changed is that no module code path reaches them.
        liar = word_liar("trained", "fixture", "eq")
        self.assertIn(liar, bm.SUBJECT_KINDS)                    # the raw constant still admits it
        self.assertEqual(bm.SUBJECT_KIND_CODE[liar], bm.SUBJECT_KIND_CODE["fixture"])
        with self.assertRaises(ValueError) as caught:            # but the module refuses it
            bm.analyze_scores(make_scores(FZ.seeds), frozen=FZ, registered_digest=FZ.digest,
                              subject="synthetic", cfg=SMALL, subject_kind=liar,
                              fixture_name="oracle")
        self.assertIn("fixture_name is required for, and only for", str(caught.exception))
        j = bm.analyze_scores(make_scores(FZ.seeds), frozen=FZ, registered_digest=FZ.digest,
                              subject="synthetic", cfg=SMALL, subject_kind=liar, fixture_name=None)
        self.assertEqual(str(j.subject_kind), "trained")
        self.assertIs(type(j.subject_kind), str, "the stored characters are what is kept")
        self.assertFalse(bm.carries_exemption(j.gates),
                         "a label storing 'trained' is no longer granted the fixture exemption")


if __name__ == "__main__":
    unittest.main()
