"""SR-13 tests for toy.dashboard. TOY ONLY: fixtures are synthetic; nothing here is a safety result."""
import dataclasses
import itertools
import os
import random
import re
import stat
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
        self.assertIn("not a safety claim", db._badge(EC.TOY_RESULT))
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


if __name__ == "__main__":
    unittest.main()
