"""SR-13: offline, static, self-contained audit dashboard (TOY / AUDIT EVIDENCE ONLY).

Standard library only. No network, no scripts, no external assets, no biological design UI.
Nothing rendered here is evidence about RFdiffusion, the fork, or any real biological capability,
and nothing bears on real-world safety. A standing banner says so on every page.

Public API
  render_dashboard(data) -> str          pure; no filesystem, no clock, deterministic
  write_dashboard(path=None, data=None)  writes ONLY to a caller path (default: fresh temp dir);
                                         refuses any path inside the repository tree
  load_snapshot(path=None) -> dict       reads docs/SOURCE_SNAPSHOT.json (local file)
  render_scorecard(joint) -> str         the ONLY scorecard renderer; takes a whole JointResult

`data` keys (all optional; an absent key renders its panel as UNKNOWN, never as zero or empty):
  "snapshot"  dict from SOURCE_SNAPSHOT.json
  "train"     toy.teacher_student.TrainResult (or any object with .history and .record)
  "joint"     toy.benchmark.JointResult
  "records"   iterable of toy.schema.ExperimentRecord

Structural guards against displaying an unsupported claim as confirmed
  1. There is NO "confirmed" visual style. The only verdict-styled element (CSS class `vd-supported`) is
     emitted by `_verdict_cell`, which is reachable only from `render_scorecard` and only from a
     *recomputed* structured verdict. It always carries "conditional; not a safety finding" plus the
     result's OWN subject kind (SR-12 F4): a scorer-validation fixture says so, a declared trained subject
     says so, and an absent or unrecognised `subject_kind` renders UNKNOWN. The caveat is never the
     blanket word "fixture", which would be false the moment a non-fixture result is rendered.
  2. Evidence badges come from one function, `_badge`, mapping EvidenceClass -> a fixed class. HYPOTHESIS,
     NOT_VALIDATED and UNKNOWN get hatched/dashed styles and the words "NOT EVIDENCE". Record evidence
     labels are re-validated; SOURCE_OBSERVED on a run record is an invalid label and is shown as UNKNOWN.
  3. Free text (name, notes, code_version, run_id, subject, ...) goes only through `_untrusted`: escaped,
     control/format characters made visible, truncated, boxed and captioned "UNTRUSTED FREE TEXT - NOT
     EVIDENCE". No verdict is ever parsed from any string.
  4. Verdicts are recomputed from structured fields; a stored verdict that disagrees is NOT shown.
  5. A scorecard is one table holding H1 (suppression), H2 (retention) and H3 (selectivity) together; a
     malformed JointResult is refused and shows no figures at all.
"""
from __future__ import annotations

import html
import inspect
import json
import math
import os
import stat
import tempfile
import unicodedata
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional

from toy import benchmark as bm  # attributes are looked up at call time so API drift is detected
from toy.benchmark import JointResult, HypothesisResult, IntervalPair, Verdict, JointVerdict
from toy.schema import EvidenceClass, ExperimentRecord, MetricValue

REPO_ROOT = Path(__file__).resolve().parents[2]
SNAPSHOT_PATH = REPO_ROOT / "docs" / "SOURCE_SNAPSHOT.json"

BANNER = ("NOTHING ON THIS PAGE IS EVIDENCE ABOUT RFdiffusion, THE FORK, OR ANY REAL BIOLOGICAL CAPABILITY. "
          "No result here bears on real-world safety. Numbers are synthetic, non-biological toy values or "
          "static source metadata. This page does not confirm any safety claim.")
NOT_EVIDENCE = "NOT EVIDENCE"
_MISSING = object()   # sentinel: distinguishes an ABSENT attribute from one whose value is None
MAX_TEXT = 300
MAX_TABLE_ROWS = 400

_BADGE = {  # fixed vocabulary: EvidenceClass -> (css class, visible label, caveat)
    EvidenceClass.SOURCE_OBSERVED: ("ev-source", "SOURCE OBSERVED", "static source metadata, not a model result"),
    EvidenceClass.TOY_RESULT: ("ev-toy", "TOY RESULT", "synthetic, non-biological; not a safety claim"),
    EvidenceClass.HYPOTHESIS: ("ev-hyp", "HYPOTHESIS", NOT_EVIDENCE),
    EvidenceClass.NOT_VALIDATED: ("ev-nv", "NOT VALIDATED", NOT_EVIDENCE),
    EvidenceClass.UNKNOWN: ("ev-unk", "UNKNOWN", NOT_EVIDENCE),
}

_CSS = """
body{font:14px/1.45 system-ui,sans-serif;margin:0;background:#f4f4f2;color:#1b1b1b}
main{max-width:1000px;margin:0 auto;padding:12px}
.banner{background:#7a0000;color:#fff;padding:12px 16px;font-weight:700;border-bottom:4px solid #000}
section{background:#fff;border:2px solid #555;margin:14px 0;padding:10px 14px}
section.ev-hyp,section.ev-nv,section.ev-unk{border-style:dashed;background:repeating-linear-gradient(45deg,#fff,#fff 10px,#f0f0f0 10px,#f0f0f0 20px)}
h1{font-size:20px;margin:10px 0}h2{font-size:16px;margin:0 0 6px}
.badge{display:inline-block;padding:1px 8px;margin-right:6px;border:2px solid #000;font:700 12px monospace}
.ev-source{background:#dde7f5}.ev-toy{background:#fff3c4}
.ev-hyp{background:#e8e8e8;border-style:dashed}.ev-nv{background:#e8e8e8;border-style:dashed}.ev-unk{background:#fff;border-style:dotted}
.caveat{font-size:12px;color:#444}
table{border-collapse:collapse;margin:6px 0}td,th{border:1px solid #888;padding:2px 8px;text-align:left;vertical-align:top}
.unknown{background:#000;color:#fff;font-weight:700;padding:0 4px}
.measured{font-family:monospace}
.untrusted{display:block;border:1px dashed #a00;background:repeating-linear-gradient(135deg,#fff,#fff 6px,#fbeaea 6px,#fbeaea 12px);
 font-family:monospace;white-space:pre-wrap;word-break:break-all;padding:2px 6px;color:#333}
.untrusted-cap{font-size:11px;color:#a00;font-weight:700}
.vd{display:inline-block;padding:1px 6px;font-weight:700;border:2px solid #000}
.vd-supported{background:#fff;outline:2px dotted #036;color:#036}
.vd-unsupported{background:#fff;color:#000;text-decoration:line-through}
.vd-inconclusive{background:#ddd;color:#000}
.warn{color:#a00;font-weight:700}
svg{background:#fff;border:1px solid #888;max-width:100%}
footer{font-size:12px;color:#444;margin:20px 0}
"""


# ------------------------------------------------------------------ escaping
def _e(value: Any) -> str:
    """The ONLY path from a value to HTML text/attributes."""
    return html.escape(str(value), quote=True)


def _visible(text: str) -> str:
    """Make control, bidi/format, private-use and unassigned characters visible instead of acting on layout."""
    out = []
    for ch in text:
        cat = unicodedata.category(ch)
        if ch in "\n\t" or (cat[0] not in "CZ" and ch.isprintable()) or ch == " ":
            out.append(ch)
        else:
            out.append(f"\\u{ord(ch):04x}" if ord(ch) <= 0xFFFF else f"\\U{ord(ch):08x}")
    return "".join(out)


def _untrusted(value: Any, label: str = "") -> str:
    s = value if isinstance(value, str) else repr(value)
    clipped = len(s) > MAX_TEXT
    s = _visible(s[:MAX_TEXT]) + (" [... truncated]" if clipped else "")
    cap = f"UNTRUSTED FREE TEXT{(' (' + label + ')') if label else ''} - NOT EVIDENCE"
    return f'<span class="untrusted-cap">{_e(cap)}</span><span class="untrusted">{_e(s)}</span>'


# -------------------------------------------------------------------- badges
def _coerce_class(value: Any, run_record: bool = False) -> tuple[EvidenceClass, Optional[str]]:
    """Validate a label. Returns (class, problem). Invalid labels degrade to UNKNOWN, never upward."""
    try:
        ec = EvidenceClass.parse(value)
    except ValueError:
        return EvidenceClass.UNKNOWN, "invalid evidence label; shown as UNKNOWN"
    if run_record and ec is EvidenceClass.SOURCE_OBSERVED:
        return EvidenceClass.UNKNOWN, "SOURCE_OBSERVED is not valid on a run record; shown as UNKNOWN"
    return ec, None


def _badge(ec: EvidenceClass, problem: Optional[str] = None) -> str:
    cls, label, caveat = _BADGE[ec]
    s = f'<span class="badge {cls}">{_e(label)}</span><span class="caveat">{_e(caveat)}</span>'
    if problem:
        s += f' <span class="warn">{_e(problem)}</span>'
    return s


def _panel(title: str, ec: EvidenceClass, body: str, problem: Optional[str] = None, extra: tuple = ()) -> str:
    """Every section on the page is built here, so none can be unlabelled."""
    cls = _BADGE[ec][0]
    extras = "".join(_badge(x) for x in extra)
    return (f'<section class="{cls}" data-evidence="{_e(ec.value)}"><h2>{_e(title)}</h2>'
            f'<div>{_badge(ec, problem)}{extras}</div>{body}</section>')


# ------------------------------------------------------------------- metrics
def _num(x: float) -> str:
    return repr(float(x))


def _metric_cell(mv: Any) -> str:
    """Measured -> repr (0.0 stays 0.0). Unmeasured or absent or malformed -> UNKNOWN (+reason). Never 0."""
    if isinstance(mv, MetricValue):
        if mv.value is not None and not isinstance(mv.value, bool) and isinstance(mv.value, float) \
                and math.isfinite(mv.value):
            return f'<span class="measured">{_e(_num(mv.value))}</span>'
        reason = mv.reason if mv.value is None else "malformed measured value"
        return f'<span class="unknown">UNKNOWN</span> <span class="caveat">{_e(_visible(str(reason))[:MAX_TEXT])}</span>'
    return '<span class="unknown">UNKNOWN</span> <span class="caveat">not recorded</span>'


def _metric_table(metrics: Optional[Mapping], expected: Iterable[str] = ()) -> str:
    metrics = metrics if isinstance(metrics, Mapping) else {}
    names = sorted(set(metrics) | set(expected), key=str)
    rows = "".join(f"<tr><td>{_untrusted(n, 'metric name')}</td><td>{_metric_cell(metrics.get(n))}</td></tr>"
                   for n in names)
    return f"<table><tr><th>metric</th><th>value</th></tr>{rows}</table>" if rows else ""


# ---------------------------------------------------------------- snapshot
def load_snapshot(path: Optional[Path] = None) -> dict:
    with open(path or SNAPSHOT_PATH, encoding="utf-8") as f:
        return json.load(f)


def _unknown(why: str) -> str:
    return f'<span class="unknown">UNKNOWN</span> <span class="caveat">{_e(why)}</span>'


def _int_cell(snap: Mapping, key: str) -> str:
    v = snap.get(key)
    if isinstance(v, int) and not isinstance(v, bool):
        return f'<span class="measured">{_e(v)}</span>'
    return _unknown(f"{key} not present")


def _defang(url: Any) -> str:
    s = str(url)
    for scheme in ("https://", "http://"):
        if s.lower().startswith(scheme):
            s = s[len(scheme):]
    return s


def _render_snapshot(snap: Any) -> str:
    if not isinstance(snap, Mapping):
        return _panel("Source-diff inventory", EvidenceClass.UNKNOWN,
                      "<p>" + _unknown("no source snapshot supplied") + "</p>")
    files = snap.get("changed_files")
    rows = ""
    if isinstance(files, (list, tuple)):
        tot_a = tot_d = 0
        ok_totals = True
        for f in files:
            if not isinstance(f, Mapping):
                rows += f"<tr><td colspan=3>{_unknown('malformed entry')}</td></tr>"
                ok_totals = False
                continue
            a, d = f.get("additions"), f.get("deletions")
            good = all(isinstance(v, int) and not isinstance(v, bool) for v in (a, d))
            if good:
                tot_a, tot_d = tot_a + a, tot_d + d
            else:
                ok_totals = False
            rows += (f"<tr><td>{_untrusted(f.get('filename', 'UNKNOWN'), 'path')}</td>"
                     f"<td>{_e(a) if isinstance(a, int) and not isinstance(a, bool) else _unknown('additions')}</td>"
                     f"<td>{_e(d) if isinstance(d, int) and not isinstance(d, bool) else _unknown('deletions')}</td></tr>")
        total = (f"<tr><th>total ({_e(len(files))} files)</th><th>{_e(tot_a)}</th><th>{_e(tot_d)}</th></tr>"
                 if ok_totals else f"<tr><th>total ({_e(len(files))} files)</th><td colspan=2>"
                 f"{_unknown('some counts missing')}</td></tr>")
        files_html = f"<table><tr><th>file</th><th>additions</th><th>deletions</th></tr>{rows}{total}</table>"
    else:
        files_html = "<p>" + _unknown("changed_files not present") + "</p>"
    commits = snap.get("fork_commits")
    commits_html = ("<ul>" + "".join(f"<li><code>{_e(_visible(str(c)))}</code></li>" for c in commits) + "</ul>"
                    if isinstance(commits, (list, tuple)) else "<p>" + _unknown("fork_commits not present") + "</p>")
    mb = snap.get("merge_base")
    mb_html = f"<code>{_e(_visible(str(mb)))}</code>" if isinstance(mb, str) else _unknown("merge_base not present")
    note = snap.get("behind_by_field_note")
    body = (
        f"<p>Fork: {_untrusted(snap.get('fork', 'UNKNOWN'))} Upstream: {_untrusted(snap.get('upstream', 'UNKNOWN'))}"
        f" Audit date: {_untrusted(snap.get('audit_date', 'UNKNOWN'))}</p>"
        f"<h3>Changed files</h3>{files_html}<h3>Fork-only commits</h3>{commits_html}"
        f"<p>Merge base: {mb_html}</p>"
        f"<table><tr><th>comparison</th><th>value</th></tr>"
        f"<tr><td>ahead_by (merge-base compare)</td><td>{_int_cell(snap, 'ahead_by')}</td></tr>"
        f"<tr><td>behind_by_vs_merge_base (fork vs its merge base)</td><td>{_int_cell(snap, 'behind_by_vs_merge_base')}</td></tr>"
        f"<tr><td>behind_by_vs_upstream_main (fork vs CURRENT upstream main; time-varying)</td>"
        f"<td>{_int_cell(snap, 'behind_by_vs_upstream_main')}</td></tr></table>"
        "<p><b>These are two different comparisons and must not be conflated.</b></p>"
        f"<p>Source note: {_untrusted(note) if note is not None else _unknown('behind_by_field_note not present')}</p>"
        f"<p class=\"caveat\">Evidence URL (scheme omitted, not a link): "
        f"{_untrusted(_defang(snap['evidence_url'])) if 'evidence_url' in snap else _unknown('not present')}</p>"
        "<p class=\"caveat\">Source metadata only; not a model-performance or safety result.</p>")
    return _panel("Source-diff inventory", EvidenceClass.SOURCE_OBSERVED, body)


# ------------------------------------------------------------------ training
def _valid_history(history: Any) -> tuple[list, int]:
    good, bad = [], 0
    if not isinstance(history, (list, tuple)):
        return good, 0
    for row in history:
        try:
            s, l, g = row
            ok = all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) for v in (s, l, g))
        except (TypeError, ValueError):
            ok = False
        if ok:
            good.append((float(s), float(l), float(g)))
        else:
            bad += 1
    return good, bad


def _svg_series(title: str, pts: list) -> str:
    """Linear axes; y always starts at 0 (so heights are proportional to values); ticks are labelled."""
    W, H, L, R, T, B = 460, 220, 70, 10, 24, 34
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    x0, x1 = min(xs), max(xs)
    ymax = max(ys)
    ymin = min(0.0, min(ys))
    if ymax <= ymin:
        ymax = ymin + 1.0
    if x1 <= x0:
        x1 = x0 + 1.0

    def X(x): return L + (x - x0) / (x1 - x0) * (W - L - R)
    def Y(y): return T + (ymax - y) / (ymax - ymin) * (H - T - B)

    path = " ".join(f"{X(x):.2f},{Y(y):.2f}" for x, y in pts)
    ticks = "".join(
        f'<line x1="{L}" x2="{W - R}" y1="{Y(v):.2f}" y2="{Y(v):.2f}" stroke="#ccc"/>'
        f'<text x="{L - 4}" y="{Y(v) + 4:.2f}" font-size="10" text-anchor="end">{_e(format(v, ".4g"))}</text>'
        for v in (ymin, (ymin + ymax) / 2, ymax))
    return (f'<svg width="{W}" height="{H}" viewBox="0 0 {W} {H}" role="img" '
            f'aria-label="{_e(title)}"><text x="{L}" y="14" font-size="12" font-weight="bold">{_e(title)}</text>'
            f'{ticks}<polyline fill="none" stroke="#000" stroke-width="1.5" points="{path}"/>'
            f'<text x="{L}" y="{H - 8}" font-size="10">step {_e(format(x0, ".4g"))}</text>'
            f'<text x="{W - R}" y="{H - 8}" font-size="10" text-anchor="end">step {_e(format(x1, ".4g"))}</text></svg>')


TRAIN_EXPECTED = ("initial_loss", "final_loss", "final_grad_norm", "loss_increased")


def _render_train(train: Any) -> str:
    if train is None:
        return _panel("Toy training curves", EvidenceClass.UNKNOWN,
                      "<p>" + _unknown("no training result supplied; no curve drawn (not a flat zero curve)") + "</p>")
    rec = getattr(train, "record", None)
    if isinstance(train, ExperimentRecord):
        rec = train
    hist, bad = _valid_history(getattr(train, "history", None))
    problem = None
    if isinstance(rec, ExperimentRecord):
        ec, problem = _coerce_class(rec.evidence_class, run_record=True)
    else:
        ec = EvidenceClass.UNKNOWN
        problem = "no valid ExperimentRecord attached"
    # A curve can never be labelled above what its record says; TOY_RESULT is the ceiling for run data.
    body = ""
    if hist:
        body += _svg_series("loss (linear axes, y includes 0)", [(s, l) for s, l, _ in hist])
        body += _svg_series("gradient norm (linear axes, y includes 0)", [(s, g) for s, _, g in hist])
        shown = hist[:MAX_TABLE_ROWS]
        rows = "".join(f"<tr><td>{_e(_num(s))}</td><td>{_e(_num(l))}</td><td>{_e(_num(g))}</td></tr>"
                       for s, l, g in shown)
        more = f"<p class=\"caveat\">Table truncated to {MAX_TABLE_ROWS} of {len(hist)} rows.</p>" if len(hist) > len(shown) else ""
        body += (f"<details open><summary>History table ({len(hist)} points)</summary><table><tr><th>step</th>"
                 f"<th>loss</th><th>grad norm</th></tr>{rows}</table>{more}</details>")
    else:
        body += "<p>" + _unknown("no usable history; no curve drawn") + "</p>"
    if bad:
        body += f'<p class="warn">{_e(bad)} malformed history row(s) omitted.</p>'
    if getattr(train, "loss_increased", False) is True:
        body += '<p class="warn">loss_increased: final loss exceeded initial loss.</p>'
    body += _metric_table(rec.metrics if isinstance(rec, ExperimentRecord) else None, TRAIN_EXPECTED)
    if isinstance(rec, ExperimentRecord):
        body += _record_idents(rec)
    body += '<p class="caveat">A training run is not evidence of selective unlearning or safety.</p>'
    return _panel("Toy training curves", ec, body, problem)


def _record_idents(rec: ExperimentRecord) -> str:
    p = rec.provenance
    out = (f"<table><tr><th>field</th><th>value (unverified)</th></tr>"
           f"<tr><td>name</td><td>{_untrusted(rec.name, 'name')}</td></tr>"
           f"<tr><td>run_id</td><td>{_untrusted(getattr(p, 'run_id', None), 'run_id')}</td></tr>"
           f"<tr><td>code_version</td><td>{_untrusted(getattr(p, 'code_version', None), 'code_version')}</td></tr>"
           f"<tr><td>timestamp_utc</td><td>{_untrusted(getattr(p, 'timestamp_utc', None))}</td></tr>"
           f"<tr><td>seed</td><td>{_untrusted(getattr(p, 'seed', None))}</td></tr></table>")
    if rec.notes is not None:
        out += f"<p>notes: {_untrusted(rec.notes, 'notes')}</p>"
    return out


# ----------------------------------------------------------------- scorecard
def _vcoerce(enum_cls, value):
    try:
        return enum_cls(value)
    except ValueError:
        return None


_SUBJECT_KIND_LABELS = {
    "fixture": ("SCORER-VALIDATION FIXTURE",
                "a test of the scorer on a fixture whose answer is known by construction; NOT a result "
                "about any method, model or intervention"),
    "trained": ("TRAINED SUBJECT (producer-declared)",
                "the producer declares a trained subject, so the answer was not known by construction; "
                "this label is self-asserted and is NOT evidence that any model was trained"),
    "unknown": ("UNKNOWN",
                "the producer did not record whether the answer was known by construction"),
}
# Default caveat for a supported cell when no subject kind was supplied. Deliberately NOT the word
# "fixture": a blanket 'toy fixture' label becomes FALSE the moment a non-fixture result is rendered (F4).
_KIND_UNKNOWN_CAVEAT = "subject kind UNKNOWN (not recorded); conditional; not a safety finding"


def _subject_kind(joint: Any) -> tuple:
    """(label, caveat, code_text, problem). Renders `JointResult.subject_kind` and its
    `benchmark.SUBJECT_KIND_CODE` encoding. An absent, misspelled, non-string or unencodable value renders
    as UNKNOWN -- never as 'trained' and never as 'fixture'.

    WHAT READING THIS PROVES, AND WHAT IT DOES NOT (benchmark.py's own docstring, routes (a)-(f)).
    `subject_kind` is PRODUCER-ASSERTED. A caller may DECLARE a trained student a scorer-validation
    fixture and so obtain the gate-11(c) exemption; `object.__setattr__(result, "subject_kind",
    "trained")` relabels a result after construction while its gates still record the exemption; a
    hand-built JointResult labelled 'trained'/'unknown' is refused only if its gates carry `exempt=True`,
    and that flag is itself producer-set; and `SUBJECT_KIND_CODE` can be patched. This panel therefore
    reports WHAT THE RESULT CLAIMS ABOUT ITSELF. It is not authentication.

    ONE REAL CROSS-CHECK IS AVAILABLE and is made here: the `control_adequacy` gate may carry
    `exempt=True` only for subject_kind == 'fixture'. `JointResult.__post_init__` enforces that at
    construction, so a mismatch means the result was relabelled after construction (route (d)) and is
    reported as a problem."""
    raw = getattr(joint, "subject_kind", _MISSING)
    problem = None
    if raw is _MISSING:
        kind = "unknown"
        problem = "subject_kind is absent from this result; shown as UNKNOWN"
    elif not isinstance(raw, str) or raw not in _SUBJECT_KIND_LABELS:
        kind = "unknown"
        problem = f"subject_kind {_visible(str(raw))[:60]!r} is not one of " \
                  f"{sorted(_SUBJECT_KIND_LABELS)}; shown as UNKNOWN"
    else:
        kind = raw
    label, caveat = _SUBJECT_KIND_LABELS[kind]
    try:
        code = bm.SUBJECT_KIND_CODE[kind]
        code_text = _num(float(code))
    except Exception:  # noqa: BLE001 - a patched/missing table is a problem, not a silent pass
        code_text = None
        problem = (problem + "; " if problem else "") + \
                  "benchmark.SUBJECT_KIND_CODE does not encode this kind (table missing or patched)"
    try:
        exempt = [g.name for g in joint.gates if getattr(g, "exempt", False) is True]
    except Exception:  # noqa: BLE001
        exempt = []
    relabelled = bool(exempt) and kind != "fixture"
    if relabelled:
        problem = (problem + "; " if problem else "") + \
                  (f"gate(s) {sorted(exempt)} carry the fixture exemption but subject_kind is "
                   f"{kind!r}: the result was relabelled after construction")
    return label, caveat, code_text, problem, relabelled


def _verdict_cell(v: Optional[Verdict], joint: bool = False, note: str = "",
                  kind_caveat: Optional[str] = None) -> str:
    """The only emitter of verdict styling. Callers pass a recomputed enum, never a string from free text.

    `kind_caveat` is the subject-kind-specific caveat attached to a SUPPORTED cell (F4). When a caller
    supplies none, the UNKNOWN wording is used: this function never asserts 'toy fixture' on its own."""
    if v is None:
        return _unknown("verdict not a valid enum value")
    name = v.value
    kind = name.split("_")[-1].lower()  # supported / unsupported / inconclusive
    cls = {"supported": "vd-supported", "unsupported": "vd-unsupported"}.get(kind, "vd-inconclusive")
    extra = " (" + (kind_caveat or _KIND_UNKNOWN_CAVEAT) + ")" if kind == "supported" else ""
    return f'<span class="vd {cls}">{_e(name)}</span><span class="caveat">{_e(extra)}{_e(note)}</span>'


def _interval(lo: Any, hi: Any) -> str:
    if isinstance(lo, MetricValue) and isinstance(hi, MetricValue) and lo.is_measured and hi.is_measured:
        return f'<span class="measured">[{_e(_num(lo.value))}, {_e(_num(hi.value))}]</span>'
    return _unknown("interval not computable")


def _contract_problems() -> list:
    """Check, at render time, the parts of the scorer API the recomputation relies on. Any problem makes the
    scorecard withhold EVERY decisive verdict and say so on the page (fail loud, never fall back silently)."""
    probs = []
    try:
        params = list(inspect.signature(bm.interval_verdict).parameters)
        if params[:3] != ["pair", "margin", "direction"] or not {"width_tol", "min_n"} <= set(params):
            probs.append(f"interval_verdict signature changed: {params}")
    except Exception as ex:  # noqa: BLE001 - any failure is a contract problem
        probs.append(f"interval_verdict not inspectable: {type(ex).__name__}")
    if {v.value for v in Verdict} != {"SUPPORTED", "UNSUPPORTED", "INCONCLUSIVE"}:
        probs.append("Verdict members changed")
    if {v.value for v in JointVerdict} != {"JOINT_SUPPORTED", "JOINT_UNSUPPORTED", "JOINT_INCONCLUSIVE"}:
        probs.append("JointVerdict members changed")
    scopes = getattr(bm, "GATE_SCOPES", None)
    if not isinstance(scopes, dict):
        probs.append("GATE_SCOPES missing")
    elif not set(scopes.values()) <= set(_KNOWN_SCOPES):
        probs.append(f"unknown gate scope(s) {sorted(set(scopes.values()) - set(_KNOWN_SCOPES))}")
    return probs


def _declared(metric: Any, margins: Any) -> tuple:
    """(direction, margin) the PROTOCOL tables declare for this metric, margin read from the result's Margins."""
    for table in (*bm.PRIMARY.values(), bm.CONVERGED):
        for m, direction, attr in table:
            if m == metric:
                return direction, float(getattr(margins, attr))
    raise LookupError(f"metric {metric!r} not in the protocol tables")


def _protocol_params() -> tuple:
    """The protocol's declared `(width_tol, min_n)`, read from the scorer's own `interval_verdict`
    signature instead of being hard-coded here, so a protocol-parameter change in `benchmark` is picked up
    rather than silently contradicted. Raises if either default is missing or not a usable number; the
    caller turns that into 'could not recompute', and `_contract_problems` reports it on the page."""
    params = inspect.signature(bm.interval_verdict).parameters
    out = []
    for name in ("width_tol", "min_n"):
        v = params[name].default
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
            raise LookupError(f"interval_verdict declares no usable default for {name}")
        out.append(v)
    return tuple(out)


def _recompute(c: Any, margins: Any = None) -> Optional[Verdict]:
    """Verdict recomputed from the interval alone. None means 'could not recompute' (always treated as a
    mismatch and shown INCONCLUSIVE with an alarm, never as SUPPORTED).

    If `margins` is given, the component's own margin/direction must equal what the protocol tables
    (benchmark.PRIMARY / CONVERGED) declare for that metric under the result's Margins; a component whose
    margin was edited on its own is therefore an alarm.

    PROTOCOL PARAMETERS FAIL CLOSED (SR-13 item 2, same ruling as C2). `min_n` (protocol 6.1, minimum n =
    30 seeds) and `width_tol` (protocol 6.3, bootstrap/t widths may differ by at most 25%) are read from
    the component, which is the producer's own assertion. They are therefore never trusted to be WEAKER
    than the value the scorer declares: the recomputation uses `max(c.min_n, declared)` and
    `min(c.width_tol, declared)`. A stricter configuration is honoured in full; a weaker one cannot buy a
    decisive verdict. A missing, non-numeric, non-finite or negative value is 'could not recompute', not a
    renderer-invented default (the old `getattr(c, 'min_n', 30)` fallback silently supplied one, which is
    the fail-open this replaces).

    Checked against the scorer, not assumed: `BenchmarkConfig.min_seeds` / `width_tol` ARE settable, and
    `ComponentResult` carries whatever the config used, so the floor is deliberately NOT a hard-coded
    30/0.25 but the scorer's declared default. `JointResult` does not carry its `BenchmarkConfig` (only an
    opaque `config_hash`), so the renderer has no way to learn a non-default value; a configuration weaker
    than the protocol floor therefore renders INCONCLUSIVE with an alarm. That is intended: protocol 6.1
    says that below the minimum "no verdict and no registered interval is produced", so a decisive cell
    for such a run would be the wrong thing to display.

    RESIDUAL LIMITS, stated plainly: the renderer has no second source of truth for the registered margins
    themselves. A result whose Margins object AND component margins were forged consistently recomputes
    consistently and raises no alarm. Margins are shown on the page (see 'Uncertainty and protocol limits')
    but are producer-asserted, not authenticated. Likewise the intervals themselves are producer-asserted:
    a same-name component with a self-consistent forged pair is a residual (only missing, extra or wrongly
    named components are alarmed, by `_component_sets_ok`). And a forged protocol parameter that is weaker
    than the floor but would not have changed this component's verdict anyway raises no alarm, because the
    floor makes it unable to change what is displayed."""
    try:
        if margins is not None:
            direction, margin = _declared(c.metric, margins)
            if c.direction != direction or float(c.margin) != margin:
                return None
        wt_declared, mn_declared = _protocol_params()
        wt, mn = getattr(c, "width_tol", None), getattr(c, "min_n", None)
        if isinstance(wt, bool) or not isinstance(wt, (int, float)) or not math.isfinite(wt) or wt < 0:
            return None
        if isinstance(mn, bool) or not isinstance(mn, int) or mn < 0:
            return None
        v, _ = bm.interval_verdict(c.pair, float(c.margin), c.direction,
                                   min(float(wt), float(wt_declared)), max(mn, int(mn_declared)))
        return Verdict(v)
    except Exception:  # noqa: BLE001
        return None


def _gate_scope(g: Any) -> str:
    try:
        return str(g.scope)
    except Exception:  # noqa: BLE001 - unknown gate/scope: treat as global (fail safe)
        return "all"


def _failed(g: Any) -> bool:
    return getattr(g, "passed", None) is not True


def _eff_component(c: Any, withheld: bool, contract_bad: bool, margins: Any = None) -> tuple:
    """(displayed verdict or None, mismatch). Decisive only if stored AND recomputed agree and nothing withholds it."""
    stored = _vcoerce(Verdict, getattr(c, "verdict", None))
    rec = _recompute(c, margins)
    if stored is None or rec is None or rec is not stored:
        return Verdict.INCONCLUSIVE, True
    if withheld or contract_bad:
        return Verdict.INCONCLUSIVE, False
    return stored, False


def _component_sets_ok(h: Any) -> bool:
    """The component and converged-component METRIC NAMES must be exactly what the protocol tables declare
    (benchmark.PRIMARY / CONVERGED), as sorted sequences (so extra duplicates alarm too). A deleted,
    duplicated, extra or wrongly-named component is alarmed.

    RESIDUAL LIMIT, stated plainly: this checks names only. The INTERVALS inside a component are
    producer-asserted; a component with the correct metric name carrying a forged but self-consistent
    interval pair (and a matching stored verdict) recomputes consistently and raises no alarm."""
    try:
        want = sorted(m for m, _d, _a in bm.PRIMARY[h.hid])
        if sorted(str(c.metric) for c in h.components) != want:
            return False
        if h.hid == "H3":
            cw = sorted(m for m, _d, _a in bm.CONVERGED)
            if sorted(str(c.metric) for c in (getattr(h, "converged_components", ()) or ())) != cw:
                return False
        elif getattr(h, "converged_components", ()):
            return False
        return True
    except Exception:  # noqa: BLE001 - cannot establish the expected sets: not ok
        return False


def _weaker_than_protocol(joint: Any) -> list:
    """Components whose DECLARED protocol parameters are weaker than the ones the scorer declares.

    Reported separately from the tampering alarm, because the two are different findings. A run
    configured with `BenchmarkConfig(min_seeds=5)` is HONEST, but by protocol 6.1 it is non-compliant --
    "with fewer than 30 completed, eligible seeds, no verdict and no registered interval is produced;
    whatever is computed is labelled below protocol minimum, exploratory, non-compliant". `_recompute`
    floors such a run to the protocol value, which makes its stored verdict disagree with the
    recomputation. Without this note the page would show only the generic "stored verdict disagrees"
    warning and so imply that somebody edited a field. It says what actually happened instead."""
    try:
        wt_declared, mn_declared = _protocol_params()
    except Exception:  # noqa: BLE001 - a contract problem, already reported by _contract_problems
        return []
    out = []
    try:
        hyps = (joint.h1, joint.h2, joint.h3)
    except Exception:  # noqa: BLE001
        return []
    for h in hyps:
        try:
            comps = (*h.components, *(tuple(getattr(h, "converged_components", ()) or ())))
        except Exception:  # noqa: BLE001
            continue
        for c in comps:
            mn, wt = getattr(c, "min_n", None), getattr(c, "width_tol", None)
            if isinstance(mn, int) and not isinstance(mn, bool) and 0 <= mn < mn_declared:
                out.append(f"{h.hid}/{_visible(str(c.metric))[:40]}: min_n={mn} is below the protocol "
                           f"minimum {mn_declared}")
            if isinstance(wt, (int, float)) and not isinstance(wt, bool) and math.isfinite(wt) \
                    and wt > wt_declared:
                out.append(f"{h.hid}/{_visible(str(c.metric))[:40]}: width_tol={_num(wt)} is wider than "
                           f"the protocol tolerance {_num(wt_declared)}")
    return out


def _gate_set_ok(gates: Any) -> bool:
    """The validity-gate NAMES must be exactly what the scorer declares in `benchmark.GATE_SCOPES`, as
    sorted sequences (so an extra duplicate alarms too). A deleted, duplicated, extra or wrongly-named
    gate is alarmed -- the same treatment `_component_sets_ok` gives component metric names.

    Why names and not a count: a FAILED gate swapped for a duplicate of a PASSING one leaves the count
    unchanged, so no count-based check can see it. Measured on HEAD before this existed: a deleted failing
    `min_seeds` gate rendered all-SUPPORTED / JOINT_SUPPORTED with no alarm and six gate rows.

    Verified against the scorer, not assumed: `JointResult.__post_init__` already refuses to construct a
    result whose `GateResult` names are not exactly `sorted(GATE_SCOPES)`, and the honest gate name set was
    confirmed to be exactly `set(GATE_SCOPES)` across seven fixture variations (default, S=0.0,
    conv=False, gate_inputs=False, L=1.0, 5 seeds, unregistered digest), 7 of 7. So no legitimate path
    omits a gate and this check cannot false-fire on an honest result; only post-hoc tampering
    (`object.__setattr__` on `gates`) reaches it.

    RESIDUAL LIMIT: this checks names only. A gate's `passed` flag is producer-asserted, so flipping a
    failed gate to passed IN PLACE keeps the name set intact and is not detectable here; it is caught only
    where the hypothesis-level recomputation disagrees with the stored verdict."""
    try:
        return sorted(str(g.name) for g in gates) == sorted(bm.GATE_SCOPES)
    except Exception:  # noqa: BLE001 - cannot establish the expected set: not ok
        return False


def _eff_hypothesis(h: Any, gates: tuple, contract_bad: bool, margins: Any = None) -> tuple:
    """(displayed verdict, mismatch). Decisive only if the stored hypothesis verdict equals an independent
    recomputation from recomputed component verdicts, scope-aware gates, and (H3) converged components."""
    if not _component_sets_ok(h):
        return Verdict.INCONCLUSIVE, True
    rc = [_recompute(c, margins) for c in h.components]
    mismatch = any(_eff_component(c, False, False, margins)[1] for c in h.components)
    if None in rc:
        return Verdict.INCONCLUSIVE, True
    blocked = bool(getattr(h, "blocking", ())) or any(
        _failed(g) and (_gate_scope(g) == "all" or h.hid in _gate_scope(g) or _gate_scope(g) not in _KNOWN_SCOPES)
        for g in gates)
    sup_block = bool(getattr(h, "supported_blockers", ())) or any(
        _failed(g) and _gate_scope(g) == "H3" for g in gates) and h.hid == "H3"
    if blocked:
        rv = Verdict.INCONCLUSIVE
    elif Verdict.UNSUPPORTED in rc:
        rv = Verdict.UNSUPPORTED
    elif all(v is Verdict.SUPPORTED for v in rc):
        rv = Verdict.SUPPORTED
    else:
        rv = Verdict.INCONCLUSIVE
    if rv is Verdict.SUPPORTED and h.hid == "H3":
        conv = tuple(getattr(h, "converged_components", ()) or ())
        if sup_block or not conv or not all(_recompute(c, margins) is Verdict.SUPPORTED for c in conv):
            rv = Verdict.INCONCLUSIVE
    stored = _vcoerce(Verdict, getattr(h, "verdict", None))
    if stored is not rv:
        return Verdict.INCONCLUSIVE, True
    return (Verdict.INCONCLUSIVE if contract_bad else rv), mismatch


_KNOWN_SCOPES = ("all", "H1H2", "H3")


def _gates_ok(gates: tuple) -> bool:
    """Global-gate state for the joint rule: a failed gate forces JOINT_INCONCLUSIVE if its scope is
    'all', OR if its scope is not a KNOWN scope (an unrecognised scope is treated as global -- fail safe).

    The unknown-scope clause is DEFENCE IN DEPTH and is masked end-to-end: `_eff_hypothesis`'s `blocked`
    clause contains the identical test and independently forces every hypothesis INCONCLUSIVE for the same
    gate, so dropping this clause changes no rendered page. It is extracted into its own function so it can
    be unit-tested DIRECTLY, with no other layer able to hide it (the F-h lesson)."""
    return not any(_failed(g) for g in gates
                   if _gate_scope(g) == "all" or _gate_scope(g) not in _KNOWN_SCOPES)


def _combine(h1: Verdict, h2: Verdict, h3: Verdict, gates_ok: bool) -> JointVerdict:
    """Protocol section 5, deliberately re-implemented (not bm.combine_joint) so a bug or drift there is a
    detectable disagreement rather than a shared blind spot."""
    vs = (h1, h2, h3)
    if not gates_ok:
        return JointVerdict.JOINT_INCONCLUSIVE
    if Verdict.UNSUPPORTED in vs:
        return JointVerdict.JOINT_UNSUPPORTED
    if all(v is Verdict.SUPPORTED for v in vs):
        return JointVerdict.JOINT_SUPPORTED
    return JointVerdict.JOINT_INCONCLUSIVE


def _joint_wellformed(j: Any) -> bool:
    if not isinstance(j, JointResult):
        return False
    for h, hid in ((j.h1, "H1"), (j.h2, "H2"), (j.h3, "H3")):
        if not isinstance(h, HypothesisResult) or h.hid != hid or not isinstance(h.components, tuple) or not h.components:
            return False
        if not all(isinstance(c.pair, IntervalPair) for c in h.components):
            return False
    if not isinstance(getattr(j, "margins", None), bm.Margins):   # fail closed: no margins, no cross-check, no figures
        return False
    return isinstance(j.gates, tuple) and bool(j.gates) and all(hasattr(g, "passed") for g in j.gates)


_HNAMES = {"H1": "Suppression (S)", "H2": "Retention (L)", "H3": "Selectivity (delta)"}


def render_scorecard(joint: Any) -> str:
    """Render a whole JointResult as a panel. There is no API to render H1 alone: suppression and
    retention/selectivity are always in the same table. A malformed object is refused with NO figures.
    Decisive verdicts are shown only where the stored value and an independent recomputation agree; any
    disagreement, recomputation failure or scorer-API change is shown loudly and displays INCONCLUSIVE."""
    if not _joint_wellformed(joint):
        return _panel("Benchmark scorecard", EvidenceClass.UNKNOWN,
                      '<p class="warn">REFUSED: not a complete JointResult (H1 suppression, H2 retention and H3 '
                      'selectivity must be reported together). No figures shown.</p>')
    problems = _contract_problems()
    gates = tuple(joint.gates)
    gate_set_bad = not _gate_set_ok(gates)
    if gate_set_bad:
        problems = [*problems, "validity-gate NAME set does not match benchmark.GATE_SCOPES: a gate was "
                               "deleted, duplicated, renamed or swapped, so the gate list cannot be read "
                               "as a complete set of protocol checks"]
    bad = bool(problems)
    kind_label, kind_caveat, kind_code, kind_problem, relabelled = _subject_kind(joint)  # noqa: E501
    supported_caveat = f"{kind_label}; conditional; not a safety finding"
    if relabelled:   # post-construction relabel (benchmark route (d)): an integrity failure, not a gap
        problems = [*problems, "subject_kind contradicts the fixture exemption recorded in the gates"]
        bad = True
    any_failed = any(_failed(g) for g in gates) or gate_set_bad
    mismatch = []
    eff = {}
    rows = ""
    for h in (joint.h1, joint.h2, joint.h3):
        ev, mm = _eff_hypothesis(h, gates, bad, joint.margins)
        eff[h.hid] = ev
        if mm or gate_set_bad:
            mismatch.append(h.hid)
        groups = [(h.components, "")]
        conv = tuple(getattr(h, "converged_components", ()) or ()) if h.hid == "H3" else ()
        if conv:
            groups.append((conv, " (converged-budget)"))
        for comps, suffix in groups:
            for c in comps:
                pair = c.pair
                ecv, cmm = _eff_component(c, any_failed, bad, joint.margins)
                if cmm and h.hid not in mismatch:
                    mismatch.append(h.hid)
                margin = c.margin if isinstance(c.margin, (int, float)) and not isinstance(c.margin, bool) \
                    and math.isfinite(c.margin) else None
                rows += (
                    f"<tr><td>{_e(h.hid)} {_e(_HNAMES[h.hid])}{_e(suffix)}</td><td>{_e(_visible(str(c.metric)))}</td>"
                    f"<td>{_e(_visible(str(c.direction)))} {_e(_num(margin)) if margin is not None else _unknown('margin')}</td>"
                    f"<td>{_metric_cell(pair.mean)}</td><td>{_interval(pair.boot_lo, pair.boot_hi)}</td>"
                    f"<td>{_interval(pair.t_lo, pair.t_hi)}</td>"
                    f"<td>{_e(pair.n) if isinstance(pair.n, int) else _unknown('n')}</td>"
                    f"<td>{_e(_num(pair.level)) if isinstance(pair.level, float) else _unknown('level')}</td>"
                    f"<td>{_verdict_cell(ecv, kind_caveat=supported_caveat)}</td></tr>")
        rows += (f"<tr><th colspan=8>{_e(h.hid)} hypothesis verdict</th>"
                 f"<td>{_verdict_cell(ev, note=' [hypothesis-level]', kind_caveat=supported_caveat)}</td></tr>")
    try:
        stored_j = _vcoerce(JointVerdict, joint.verdict)
    except Exception:  # noqa: BLE001
        stored_j = None
    # `not gate_set_bad` here is REDUNDANT belt-and-braces, and measured to be so: a bad gate set always
    # appends to `problems`, so `bad` is True, and `if bad: jv = JOINT_INCONCLUSIVE` below overrides
    # whatever `_combine` returned. Removing this conjunct changes no rendered page, so no test can pin
    # it; it is kept because it makes the joint rule correct on its own terms rather than only via `bad`.
    gates_ok = not gate_set_bad and _gates_ok(gates)
    try:
        jv = _combine(eff["H1"], eff["H2"], eff["H3"], gates_ok)   # independent of bm.combine_joint on purpose
    except Exception:  # noqa: BLE001
        jv = None
    if jv is None or jv is not stored_j:
        mismatch.append("JOINT")
        jv = JointVerdict.JOINT_INCONCLUSIVE
    if bad:
        jv = JointVerdict.JOINT_INCONCLUSIVE
    deferred = tuple(joint.deferred_gates) if isinstance(getattr(joint, "deferred_gates", None), (tuple, list)) else ()
    cond = f" CONDITIONAL on {len(deferred)} unimplemented gate(s)" if deferred or joint.complete_gate_coverage is not True else ""
    gate_rows = "".join(
        f"<tr><td>{_untrusted(g.name, 'gate')}</td><td>{'PASS' if g.passed is True else 'FAIL'}</td>"
        f"<td>{_e(_visible(str(g.reason))[:MAX_TEXT])}</td></tr>" for g in gates)
    try:
        fam = f"{bm.N_PRIMARY} primary intervals, Bonferroni level {_num(bm.bonferroni_level())} (read from the scorer)"
    except Exception:  # noqa: BLE001
        fam = "family size/level UNKNOWN"
    body = ""
    if bad:
        body += ('<p class="warn">SCORER/RENDERER CONTRACT PROBLEM: ' + _e("; ".join(problems)) +
                 '. All decisive verdicts are withheld (INCONCLUSIVE shown).</p>')
    body += (f"<p>Subject: {_untrusted(joint.subject, 'subject')}</p>"
             # F4: the ACTUAL scorer-validation distinction, read from the result, not a blanket label.
             f"<table><tr><th>subject kind (what the result claims about itself)</th>"
             f"<th>SUBJECT_KIND_CODE</th></tr>"
             f"<tr><td>{_e(kind_label)} <span class=\"caveat\">{_e(kind_caveat)}</span></td>"
             f"<td>{f'<span class=\"measured\">{_e(kind_code)}</span>' if kind_code is not None else _unknown('not encoded')}"
             f"</td></tr></table>"
             + (f'<p class="warn">SUBJECT KIND PROBLEM: {_e(kind_problem)}</p>' if kind_problem else "")
             + '<p class="caveat">subject_kind is PRODUCER-ASSERTED: it records what the producer declared, '
               'not an authenticated fact. A result declared a scorer-validation fixture is a test of the '
               'scorer, never a result about any method; a result declared trained is not evidence that '
               'anything was trained.</p>'
             + f"<p class=\"caveat\">{_e(fam)}</p>"
             f"<table><tr><th>hypothesis</th><th>metric</th><th>direction, margin</th><th>mean</th>"
             f"<th>bootstrap interval</th><th>t interval</th><th>n</th><th>level</th><th>verdict</th></tr>"
             f"{rows}</table>"
             f"<p><b>Joint verdict:</b> {_verdict_cell(jv, note=cond, kind_caveat=supported_caveat)}</p>"
             f"<p>Attempted {_int_or_unk(joint.n_attempted)}, failed {_int_or_unk(joint.n_failed)}. "
             f"Complete gate coverage: {'yes' if joint.complete_gate_coverage is True else 'NO'}.</p>"
             f"<table><tr><th>validity gate</th><th>result</th><th>detail</th></tr>{gate_rows}</table>")
    if mismatch:
        body += (f'<p class="warn">Stored verdict(s) for {_e(", ".join(mismatch))} disagree with an independent '
                 f'recomputation (or could not be recomputed) and are NOT shown; INCONCLUSIVE is displayed.</p>')
    weaker = _weaker_than_protocol(joint)
    if weaker:
        body += ('<p class="warn">PROTOCOL PARAMETERS WEAKER THAN THE PROTOCOL DECLARES: '
                 + _e("; ".join(weaker)) +
                 '. The recomputation used the protocol values, so any decisive verdict is withheld. '
                 'Protocol 6.1 produces no verdict below the minimum n and labels such a run '
                 'exploratory and non-compliant; this is a configuration statement, NOT evidence of '
                 'tampering. The renderer cannot tell the two apart from the result alone, because '
                 'JointResult carries only an opaque config_hash and not its BenchmarkConfig.</p>')
    body += ('<p class="caveat">Verdicts are shown only when stored and recomputed values agree. They describe a '
             'scorer run on synthetic toy data and say nothing about any real model. Margins are arbitrary '
             'protocol parameters.</p>')
    return _panel("Benchmark scorecard", EvidenceClass.TOY_RESULT, body, extra=(EvidenceClass.NOT_VALIDATED,))


def _int_or_unk(v: Any) -> str:
    return _e(v) if isinstance(v, int) and not isinstance(v, bool) else _unknown("not recorded")


def _render_uncertainty(joint: Any) -> str:
    if not _joint_wellformed(joint):
        return _panel("Uncertainty and protocol limits", EvidenceClass.UNKNOWN,
                      "<p>" + _unknown("no scorecard supplied") + "</p>")
    m = joint.margins
    # SR-13 acceptance criterion: "missing results render as UNKNOWN, not 0". A bad margin FIELD inside an
    # otherwise well-formed Margins must therefore still produce a ROW. The old comprehension filtered the
    # row out entirely, so a None/NaN/non-numeric margin VANISHED from a panel whose own closing sentence
    # says "UNKNOWN means unmeasured, never zero" -- a silent blank, which is the failure this criterion
    # names. (A missing or wrong-TYPE Margins object is a different case: `_joint_wellformed` refuses the
    # whole card, so nothing here is reached. See C2.)
    marg = ""
    for k in ("delta_S", "delta_R", "delta_sel"):
        v = getattr(m, k, _MISSING)
        if v is _MISSING:
            cell = _unknown(f"{k} is absent from the Margins object; NOT zero")
        elif isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
            cell = _unknown(f"{k} is not a finite number; unmeasured, NOT zero")
        else:
            cell = _metric_cell(MetricValue.measured(float(v)))
        marg += f"<tr><td>{_e(k)}</td><td>{cell}</td></tr>"
    body = ("<p>Margins are proposed defaults with no empirical basis (HYPOTHESIS, not findings).</p>"
            f"<table><tr><th>margin</th><th>value</th></tr>{marg}</table>"
            "<p>Unimplemented (deferred) validity gates: "
            + _e(", ".join(_visible(str(d)) for d in joint.deferred_gates) or "none listed") + ".</p>"
            "<p>Any SUPPORTED verdict is conditional on these. UNKNOWN means unmeasured, never zero.</p>")
    return _panel("Uncertainty and protocol limits", EvidenceClass.HYPOTHESIS, body)


# ------------------------------------------------------------------- records
def _render_records(records: Any) -> str:
    if records is None:
        return _panel("Experiment records", EvidenceClass.UNKNOWN, "<p>" + _unknown("no records supplied") + "</p>")
    try:
        recs = list(records)
    except TypeError:
        return _panel("Experiment records", EvidenceClass.UNKNOWN,
                      '<p class="warn">records is not iterable; nothing shown.</p>')
    rows, classes, skipped = "", set(), 0
    for r in recs[:MAX_TABLE_ROWS]:
        if not isinstance(r, ExperimentRecord):
            classes.add(EvidenceClass.UNKNOWN)
            skipped += 1
            rows += (f'<tr><td colspan=4><span class="warn">ENTRY IS NOT AN ExperimentRecord (type '
                     f'{_e(_visible(type(r).__name__))}); contents not rendered</span> '
                     f'{_unknown("cannot be labelled")}</td></tr>')
            continue
        ec, prob = _coerce_class(r.evidence_class, run_record=True)
        classes.add(ec)
        rows += (f"<tr><td>{_badge(ec, prob)}</td><td>{_untrusted(r.name, 'name')}</td>"
                 f"<td>{_metric_table(r.metrics)}</td>"
                 f"<td>{_untrusted(r.notes, 'notes') if r.notes is not None else _unknown('no notes')}"
                 f"{_untrusted(r.provenance.run_id, 'run_id')}{_untrusted(r.provenance.code_version, 'code_version')}</td></tr>")
    note = ""
    if skipped:
        note += f'<p class="warn">{_e(skipped)} entr{"y" if skipped == 1 else "ies"} not rendered: not an ExperimentRecord.</p>'
    if len(recs) > MAX_TABLE_ROWS:
        note += (f'<p class="warn">TRUNCATED: showing {_e(MAX_TABLE_ROWS)} of {_e(len(recs))} records; '
                 f'{_e(len(recs) - MAX_TABLE_ROWS)} not shown.</p>')
        classes.add(EvidenceClass.UNKNOWN)
    panel_ec = next(iter(classes)) if len(classes) == 1 else (EvidenceClass.NOT_VALIDATED if classes else EvidenceClass.UNKNOWN)
    body = (f"<table><tr><th>label</th><th>name</th><th>metrics</th><th>free text</th></tr>{rows}</table>"
            if rows else "<p>" + _unknown("record list is empty") + "</p>")
    return _panel("Experiment records", panel_ec, note + body)


# ---------------------------------------------------------------------- page
_LEGEND = "".join(f'<li><span class="badge {c}">{_e(l)}</span> {_e(v)}</li>' for c, l, v in _BADGE.values())


def render_dashboard(data: Optional[Mapping] = None) -> str:
    """Pure, deterministic. Missing keys render as UNKNOWN panels."""
    data = data if isinstance(data, Mapping) else {}
    panels = [
        _render_snapshot(data.get("snapshot")),
        _render_train(data.get("train")),
        render_scorecard(data["joint"]) if data.get("joint") is not None else
        _panel("Benchmark scorecard", EvidenceClass.UNKNOWN, "<p>" + _unknown("no scorecard supplied") + "</p>"),
        _render_uncertainty(data.get("joint")),
        _render_records(data.get("records")),
    ]
    return (
        "<!DOCTYPE html>\n<html lang=\"en\"><head><meta charset=\"utf-8\">"
        "<meta http-equiv=\"Content-Security-Policy\" content=\"default-src 'none'; style-src 'unsafe-inline'\">"
        "<title>SafeRFdiffusion audit dashboard (toy / audit evidence only)</title>"
        f"<style>{_CSS}</style></head><body>"
        f'<div class="banner" role="alert">{_e(BANNER)}</div><main>'
        "<h1>Audit dashboard: toy results and source metadata</h1>"
        f'<aside><b>Label legend</b><ul>{_LEGEND}</ul></aside>'
        + "".join(panels) +
        f'<footer>{_e(BANNER)} Free text is shown boxed as untrusted and is never interpreted as a verdict.</footer>'
        "</main></body></html>\n")


def _same_file(a: os.stat_result, b: os.stat_result) -> bool:
    return a.st_dev == b.st_dev and a.st_ino == b.st_ino


def _inside_repo(p: Path) -> bool:
    """True if `p` is, or would be created inside, the repository tree. Fails CLOSED (True) on any doubt.

    Primary check is IDENTITY, not text: every existing ancestor of the resolved target is compared by
    (st_dev, st_ino) with the repo root, so case-varied directory components on a case-insensitive volume
    (resolve() does not normalise those), bind mounts and aliases are all caught, and the check stays correct
    on a case-sensitive mount. A case-folded textual prefix comparison is a secondary belt-and-braces check
    (it can only over-refuse)."""
    try:
        r = Path(os.path.abspath(p)).resolve()
        root = REPO_ROOT.resolve()
    except (OSError, RuntimeError, ValueError):
        return True
    try:
        root_st = os.stat(root)
    except OSError:
        root_st = None
    for a in (r, *r.parents):
        try:
            st = os.stat(a)
        except OSError:
            continue                       # does not exist (yet): keep walking up to one that does
        if root_st is not None and _same_file(st, root_st):
            return True
    return _casefold_inside(r, root)


def _casefold_inside(r: Path, root: Path) -> bool:
    rs, ks = str(r).casefold(), str(root).casefold()
    return rs == ks or rs.startswith(ks.rstrip(os.sep) + os.sep)


_DEVICE_PREFIXES = ("/dev", "/proc", "/sys")


def _is_device_dir(parent: Path) -> bool:
    ps = str(parent)
    return any(ps == d or ps.startswith(d + os.sep) for d in _DEVICE_PREFIXES)


def write_dashboard(path: Optional[Any] = None, data: Optional[Mapping] = None) -> Path:
    """Write only to `path` (default: a fresh temp dir).

    Guards (path AND inode level): refuse a path that resolves inside the repo tree; refuse symlinks; refuse an
    existing target that is not a regular file; refuse an existing target with more than one hard link (a
    hardlink's path can lie outside the repo while its inode is a repo file); and write via a temp file +
    os.replace so that even a missed case replaces the directory entry and never modifies an existing inode.
    The temp file is created in the DESTINATION directory (rename is atomic only within one filesystem).

    Side effects / limits, stated plainly: the replaced file gets mode 0600 (mkstemp), not the umask default;
    a filesystem that does not report link counts (some FUSE/network mounts) would defeat the st_nlink guard,
    though the temp-file design still leaves the old inode untouched; /dev, /proc and /sys destinations are
    refused deliberately."""
    out = Path(path) if path is not None else Path(tempfile.mkdtemp(prefix="saferf_dashboard_")) / "dashboard.html"
    if _inside_repo(out):
        raise ValueError("refusing to write the dashboard inside the repository tree")
    try:
        parent = Path(os.path.abspath(out)).parent.resolve()
    except (OSError, RuntimeError, ValueError):
        raise ValueError("refusing: cannot resolve the destination directory") from None
    if _is_device_dir(parent):
        raise ValueError("refusing to write into a device/pseudo filesystem (/dev, /proc, /sys)")
    try:
        parent_ok = parent.is_dir()
    except OSError:
        parent_ok = False
    if not parent_ok:
        raise ValueError("refusing: destination directory does not exist")
    try:
        st = os.lstat(out)
    except FileNotFoundError:
        st = None
    except OSError as ex:
        raise ValueError(f"refusing: cannot inspect the destination ({type(ex).__name__})") from None
    if st is not None:
        if stat.S_ISLNK(st.st_mode):
            raise ValueError("refusing to write through a symlink")
        if not stat.S_ISREG(st.st_mode):
            raise ValueError("refusing to overwrite a non-regular file")
        if st.st_nlink > 1:
            raise ValueError("refusing to overwrite a file with multiple hard links (it may alias another file)")
    text = render_dashboard(data)
    fd, tmp = tempfile.mkstemp(prefix=".dashboard-", suffix=".tmp", dir=str(out.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
        os.replace(tmp, out)
    except BaseException:   # incl. KeyboardInterrupt: never leave a temp file behind
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return out
