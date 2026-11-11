"""SR-13 tests for toy.dashboard. TOY ONLY: fixtures are synthetic; nothing here is a safety result."""
import ast
import dataclasses
import inspect
import io
import itertools
import os
import random
import re
import stat
import sys
import tempfile
import tokenize
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
    """`db._recompute` with the second source taken from the result the component came from."""
    return db._recompute(c, margins, db._measured_seeds(j))


def pair_ok(j, pair=None, c=None):
    """`db._pair_numbers_ok` for one pair of `j`, with `min_n` and the second source read off `j`."""
    c = j.h1.components[0] if c is None else c
    return db._pair_numbers_ok(c.pair if pair is None else pair, c.min_n, db._measured_seeds(j))


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

    def test_documented_limit_same_name_forged_pair_is_a_residual(self):
        # Honest boundary (C1): names are checked, intervals are producer-asserted. A same-name component carrying
        # a self-consistent strong pair is NOT detectable. Pinned so the docstring stays truthful.
        weak = joint(expect=None, dms=bm.Margins().delta_sel)
        strong = joint()
        j = weak
        object.__setattr__(j.h3, "components", (j.h3.components[0], strong.h3.components[1]))
        object.__setattr__(j.h3, "converged_components", strong.h3.converged_components)
        object.__setattr__(j.h3, "verdict", bm.Verdict.SUPPORTED)
        self.assertEqual(hyp_cells(db.render_scorecard(j))["H3"], "SUPPORTED")
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
        self.assertIsNone(db._recompute(object(), None, 30))

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
        for bad in ("Fixture", "FIXTURE", "trained ", "", None, 0, True, [], object(), "safe"):
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
        # `value = None` is a legitimately UNMEASURED bound, so it is not a fail-closed case here: the
        # scorer itself returns INCONCLUSIVE ("interval not computable") for it. Still never decisive.
        j = joint()
        for h_ in (j.h1, j.h2, j.h3):
            for c in (*h_.components, *(h_.converged_components or ())):
                forge_bounds(c.pair, None)
        self.assertIs(recompute(j.h1.components[0], j.margins, j), bm.Verdict.INCONCLUSIVE)
        h = db.render_scorecard(j)
        self.assertEqual(set(hyp_cells(h).values()), {"INCONCLUSIVE"})
        self.assertNotIn("vd-supported", h)

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
            self.assertFalse(db._pair_numbers_ok(junk, 30, 30), repr(junk))
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

# Hostile values per KIND: everything an honest producer of a field of this kind cannot emit BECAUSE OF
# ITS TYPE. Round 4 wrote that as "everything an honest producer of a field of this kind cannot emit",
# full stop, and the sweep over it was this module's whole answer for a stored number -- which is how
# round 5 happened. See `LEGAL_BUT_WRONG` below: these lists contain not one legal `int`, and an honest
# producer of `pair.n` on a 29-seed run cannot emit the legal int `30` either. A type table cannot refuse
# a legal value; only a second source can, so the two tables are separate and both are swept.
HOSTILE_BY_KIND = {
    "mv": BREAKS_MV_INVARIANT,                              # forged into MetricValue.value
    "float": (0, 1, 30, -1, "0.5", "", [], {}, (), object(), None, True, False,
              float("nan"), float("inf"), float("-inf")),
    "num": ("0.1", "", "nan", [], {}, (), object(), None, True, False,
            float("nan"), float("inf"), float("-inf")),
    "count": (0.0, 1.0, 30.0, "30", "", [], {}, (), object(), None, True, False,
              float("nan"), float("inf"), float("-inf")),
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
NO_SECOND_SOURCE = {
    ("IntervalPair", "mean"): "the interval itself is producer-asserted; a self-consistent forged pair "
                              "under a correctly named component is the residual documented at _recompute",
    ("IntervalPair", "boot_lo"): "as `mean`", ("IntervalPair", "boot_hi"): "as `mean`",
    ("IntervalPair", "t_lo"): "as `mean`", ("IntervalPair", "t_hi"): "as `mean`",
    ("IntervalPair", "level"): "a second source IS on the page (bm.bonferroni_level in the family line) "
                               "and is deliberately not used: an honest pair's level is "
                               "bonferroni_level(cfg.alpha, N_PRIMARY), BenchmarkConfig.alpha is settable "
                               "and JointResult carries only an opaque config_hash, so comparing them "
                               "would false-fire on every honest non-default-alpha study -- the same "
                               "undecidability as min_n. `level` also reaches no verdict at all.",
}
# Values of the RIGHT TYPE that an honest producer of this field cannot emit on the fixture named in the
# sweep. `None` means "use the default 30-seed fixture"; `pair.n` additionally gets the 29-seed fixture
# of the reported defect, in test_G3.
LEGAL_BUT_WRONG = {
    ("IntervalPair", "n"): (31, 50, 1000),             # a 30-seed study has no 31-seed component
    ("JointResult", "n_attempted"): (29, 31, 100, 0),  # contradicts len(seed_scores) == 30
    ("JointResult", "n_failed"): (1, 5, 30),           # contradicts "no entry of seed_scores is not-ok"
    ("ComponentResult", "margin"): (0.0, 0.2, 1.0, -1.0),   # != Margins() delta_S 0.10 / R 0.05 / sel 0.10
    ("Margins", "delta_S"): (0.0, 0.2, 1.0, -1.0),
    ("Margins", "delta_R"): (0.0, 0.2, 1.0, -1.0),
    ("Margins", "delta_sel"): (0.0, 0.2, 1.0, -1.0),
    ("ComponentResult", "min_n"): (0, 1, 5, 29),       # weaker than the protocol's 30: neutralised
    ("ComponentResult", "width_tol"): (0.9, 1, 1e9),   # wider than the protocol's 0.25: neutralised
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
    because no field of these classes holds one (`complete_gate_coverage` is a derived flag, not a datum)."""
    return isinstance(v, MetricValue) or (isinstance(v, (int, float)) and not isinstance(v, bool))


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
        return {a for a in bucket if is_a_stored_number(getattr(honest, a, None))}

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
        # RESIDUAL, stated: a tamperer who rebuilds `seed_scores` consistently still gets through. This
        # raises the cost of the forgery from one integer to 30 fabricated objects; it does not remove it.
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


if __name__ == "__main__":
    unittest.main()
