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
    EvidenceClass.TOY_RESULT: ("ev-toy", "TOY RESULT", "synthetic, non-biological; not a safety finding"),
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


# ===================================================================================================
# THE STORED-NUMBER SCHEME.  Read this before adding ANY consumer of a stored number.
# ===================================================================================================
# SR-13 failed four times for one reason, in four different places. Round 2: `_interval` gated on
# `MetricValue.is_measured` (merely `value is not None`) while `_metric_cell` checked properly, so one
# forged value rendered UNKNOWN in one cell of a row and a measured `[0.0, 0.0]` in the next. Round 3:
# the fix introduced `_finite_float` and a test class asserting that "all four cells and the
# recomputation now route through" it -- and round 3 found a SIXTH and SEVENTH consumer, because that
# enumeration was ASSERTED, not PERFORMED. Round 4 found `pair.n` (display cell vs
# `interval_verdict`'s `n < min_n` floor: a forged `nan` bought a decisive JOINT_SUPPORTED on a
# genuinely below-minimum run with zero alarms) and `c.margin` / `Margins.<attr>` (still bare
# `float(...)`, which coerces -- the exact pattern the previous round's docstring claimed was gone).
#
# ROUND 5 (this one) IS NOT ANOTHER MISSING CONSUMER. Every consumer was declared and every one was
# routed through its kind -- and the item still failed, because round 4 admitted `pair.n` BY TYPE ONLY.
# Measured on the same below-minimum fixture round 4 was built from (29 real seeds, the `min_seeds` gate
# flipped to passed in place so the gate-NAME set stays intact, stored verdicts forged SUPPORTED):
#     pair.n untouched (29)  -> JOINT_INCONCLUSIVE, alarm, 1 warning paragraph   (caught)
#     pair.n forged to 30    -> JOINT_SUPPORTED, NO alarm, ZERO warning paragraphs
#     pair.n forged to 31    -> JOINT_SUPPORTED, NO alarm, ZERO warning paragraphs
#     pair.n forged to nan   -> JOINT_INCONCLUSIVE, alarm                        (caught: not an int)
# `30` is a legal `int`. `_count` admits it and must: `_count`'s own docstring says sign is not
# constrained there, and an honest `pair.n` of 30 is the commonest value in the kit. No tightening of a
# TYPE predicate can refuse it. THE ONLY DEFENCE IS A SECOND SOURCE FOR THE SAME NUMBER, and
# `benchmark.py` had already said so in as many words, at its own `n` cross-check in
# `verdict_from_records`: "A forged `n_seeds` is a legal count, so `_metric_count` cannot catch it; the
# only defence is a second stored number to compare it against ... n must be CHECKED against something,
# not trusted." This renderer read BOTH HALVES of that second source onto the page -- "Attempted 29,
# failed 0" -- and used neither. See `_measured_seeds` and `_n_problem` for the three sources now read.
#
# So the fix is NOT "also check `pair.n`". It is this, in four parts, none of which is an assertion:
#
#   1. KINDS. There are exactly four predicates in this module that admit a stored number -- one per
#      kind -- and no inline numeric test anywhere else. `_finite_float` ("float"), `_finite_number`
#      ("num"), `_count` ("count"), `_mv_intact` ("mv"). `float()` appears exactly ONCE in this file,
#      in `_num`, downstream of all four, because every coercion that ever existed here was a
#      laundering step.
#      AND EACH OF THE THREE NUMERIC KINDS NORMALISES WHAT IT ADMITS, which is round 7 (item 6 below).
#      A normalisation AT THE POINT OF ADMISSION is the opposite of the coercions this item removed: a
#      `float(c.margin)` in front of a verdict decided on a number no cell had checked, while
#      `float.__float__(x)` INSIDE the kind returns the same double `math.isfinite` just inspected. The
#      rule is `benchmark._plain_number`'s and is now stated identically on both sides of the boundary:
#      normalise, THEN compare -- and hand the normalised value on, because a predicate applied to a
#      value and an operator applied to that value are two independently overridable operations.
#   2. A DECLARED TABLE. `STORED_NUMBERS` names every attribute of a scorer object that this renderer
#      turns into a figure or feeds to a verdict, with its kind. `_admitted` is the only reader in the
#      VERDICT path and it returns the admitted VALUES, so that path admits each field once;
#      `_recompute` uses those values and fails closed on any entry of a verdict-bearing class.
#      THE SENTENCE THIS REPLACES SAID "`_admitted` is the only reader and it returns the admitted
#      VALUES, SO EACH FIELD IS ADMITTED EXACTLY ONCE", and that was false as written. Counted, for
#      `pair.n`: `_admitted` (inside `_pair_numbers_ok`), its display cell in `render_scorecard`
#      (`_kind_text(pair.n, 'n', 'count')`), and `_n_sources_disagree`'s own `_count(getattr(pair, "n"))`
#      -- three admissions -- plus a FOURTH read straight off the object by `bm.interval_verdict`, which
#      applies protocol 6.1's `n < min_n` with no kind function at all. THE PROPERTY THAT MATTERS IS NOT
#      THE COUNT but what the admissions AGREE ABOUT -- and the sentence that stood here stated it as an
#      absolute, which is false. THE SENTENCE THIS REPLACES SAID "all three admissions go through the
#      same kind function, `_count`, SO THEY CANNOT DISAGREE". A kind function normalises the VALUE IT
#      IS HANDED; nothing in this module makes the HOLDER hand it the same value twice. The true claim
#      is the weaker one, and it is the one this scheme rests on: THE THREE ADMISSIONS CANNOT DISAGREE
#      ABOUT A VALUE, BUT NOTHING PREVENTS THE HOLDER FROM SUPPLYING TWO.
#      MEASURED (round 8, 3.13.5 and 3.12.4 identical): an `IntervalPair` whose `__getattribute__`
#      serves `n` from `itertools.cycle([29, 30])` -- EVERY RETURNED VALUE A PLAIN `int`, so every kind
#      function admits it unchanged and `_count` normalises nothing away -- renders JOINT_SUPPORTED with
#      all three hypothesis cells SUPPORTED on the suite's own 29-seed `laundered_below_minimum`
#      fixture, where the honest fixture renders JOINT_INCONCLUSIVE with its verdicts withheld. The
#      sample-size cells print `29` and the page's own paragraph says that every verdict derived from a
#      contradicted interval is withheld; the verdict cell shows the decisive verdict anyway. The page
#      contradicts itself and FAILS OPEN on the cell that matters.
#      THE MECHANISM IS NOT CLOSED, AND IS NOT CLAIMED TO BE. A `__class__` swap or a
#      `__getattribute__` override is the residual this scheme has declared since round 4 -- it is why
#      item 3's `vars(c.pair)["n_boot"]` and `c.pair.__dict__["n_boot"]` mutants are blind to the
#      recording probe, for the same reason -- so an alternating holder is that SAME residual and not a
#      new defect class. What is withdrawn is the absolute, not the design. The replacement claim is
#      checkable and is CHECKED rather than restated: `test_the_corrected_comment_claims_are_performed_
#      not_asserted` item (2) measures both halves, that every admission of `pair.n` in a real render
#      goes through `_count`, and that an alternating holder of plain `int`s still launders the fixture.
#      That much -- not "exactly once" -- is what rounds 2 and 3 lacked (a display cell and a verdict
#      path with two different predicates). `_n_sources_disagree`'s duplicate admission is argued where
#      it lives; the fourth, raw read is the reason `_pair_numbers_ok` must gate `interval_verdict`
#      rather than trust it.
#   3. THE ENUMERATION IS PERFORMED, NOT ASSERTED. Two tests do the work a reviewer kept doing by eye:
#      `test_the_enumeration_is_performed_by_probe_not_asserted` swaps each scorer class for a
#      recording subclass, renders a whole dashboard, and compares the attributes ACTUALLY READ (by
#      this module AND by `benchmark` underneath it) against `STORED_NUMBERS` -- so a new consumer of
#      an undeclared number fails the suite naming the attribute; and
#      `test_no_numeric_predicate_lives_outside_the_kind_functions` reads this file's own source and
#      fails if `isinstance(..., int/float)`, `math.isfinite` or `float(` appears outside the block
#      below.
#      THIS COMMENT USED TO END "A future reader cannot add an unchecked consumer without turning one
#      of those red." THAT IS OVERSTATED and the correction lived only in the test module, where a
#      reader of this file could not see it. Four mutants were MEASURED to survive both tests: the same
#      consumer spelled `vars(c.pair)["n_boot"]` or `c.pair.__dict__["n_boot"]` (both bypass
#      `__getattribute__`, both lint-clean by design, both with a demonstrated behaviour change), an
#      undeclared read behind a branch the probe's single render never takes, and a DUPLICATE read of an
#      already-declared number, which an attribute-SET comparison cannot see at all. The two tests name
#      a new consumer early; they do not close the space.
#      Every entry of `STORED_NUMBERS` is then forged by a table-driven sweep that asserts the VERDICT
#      CELL and the ALARM, not just the figure cell -- which is what all three rounds' tests omitted.
#      THAT is the guarantee: a behavioural sweep dies regardless of spelling, branch or mechanism.
#   4. TYPE IS NOT THE WHOLE OF ADMISSION. Where a stored number has a SECOND SOURCE in the same result,
#      the two are compared and a disagreement fails closed; where it has none, that is declared and the
#      residual is stated. The classification is itself enumerated, by `SECOND_SOURCE` /
#      `NEUTRALISED_BY_A_FLOOR` / `NO_SECOND_SOURCE` in the test module, whose union must be exactly the
#      entries of `STORED_NUMBERS` -- so a new declared number cannot be added without saying which of
#      the three it is. The hostile-value sweep gained a LEGAL-BUT-WRONG table beside the type table,
#      because the type table is now the known-weak half: `HOSTILE_BY_KIND["count"]` claimed to hold
#      "everything an honest producer of a field of this kind cannot emit" and contained not one legal
#      int, though an honest producer of `pair.n` on a 29-seed run cannot emit `30` either.
#
#   5. ROUND 6: A PERFORMED CLASSIFICATION IS NOT A TRUE ONE, and this is the round-6 defect in one
#      sentence. The three dicts of item 4 PARTITIONED `STORED_NUMBERS` exactly -- 7 + 2 + 6 = 15,
#      pairwise disjoint, the test green -- and SIX `NO_SECOND_SOURCE` entries said "the interval itself
#      is producer-asserted" while an EXACT second source for four of them (`mean`, `t_lo`, `t_hi`,
#      `level`) sat in the same `JointResult` and this module ALREADY READ IT: the per-seed series
#      rebuilt from `joint.seed_scores`, which `_measured_seeds` has read since round 5. `bm.mean` and
#      `bm.t_interval` reproduce all three bounds BIT-EXACTLY (measured: 324 of 324 component-field
#      comparisons over 18 honest shapes), and `t_lo`/`t_hi` carry protocol 6.3's bootstrap/t
#      disagreement rule, so they are verdict-bearing: two `object.__setattr__` turned an honest
#      6.3-INCONCLUSIVE study into a displayed JOINT_SUPPORTED with no alarm. A machine can check that a
#      classification is a partition; NOTHING IN A TEST SUITE CAN CHECK THAT THE REASON WRITTEN IN IT IS
#      TRUE. So each surviving `NO_SECOND_SOURCE` reason must now (a) name the source it does NOT have
#      and why it cannot be had, and (b) carry a test that fails if that source turns out to exist --
#      for the two bootstrap bounds, `test_the_two_bootstrap_bounds_have_no_recoverable_second_source`.
#      See `_interval_problem`.
#
#   6. ROUND 7: A CROSS-CHECK RUNS ON WHATEVER OBJECT YOU HAND IT, AND THE KINDS WERE HANDING ON THE
#      CALLER'S. Rounds 5 and 6 added second sources; this round's defect is that the COMPARISONS
#      against them were performed by the suspect value's own dunders. `benchmark.py` normalises at the
#      point of use (`_plain_number`/`_plain_parameter` inside `_verdict_from_bounds`, `_check_margin`,
#      `MetricValue.__post_init__`), which is why SR-10 passed every equivalent attack; this module
#      cited that same docstring and did the opposite -- the three kinds each ended `return x`, and
#      `_finite_number`'s docstring stated the non-conversion as a deliberate choice. An `int`/`float`
#      SUBCLASS instance stores a legal value, passes `isinstance`, need not lie to `math.isfinite`, and
#      answers `==`/`<`/`>`/`__float__` as it pleases. FOUR MEASURED CONSEQUENCES, each one
#      `object.__setattr__` on a field the suite already swept: `pair.n` (undoing rounds 5 AND 6 on the
#      suite's own `laundered_below_minimum` fixture -- see `_count`), `ComponentResult.min_n` (removing
#      the protocol-6.1 floor AND silencing `_weaker_than_protocol` -- see `_count`),
#      `ComponentResult.margin` (JOINT_UNSUPPORTED -> JOINT_SUPPORTED with every displayed figure
#      honest -- see `_finite_number`), and `pair.level` (an edited figure in every level cell of the
#      same render that verified `t_lo`/`t_hi` against the honest level -- see `_finite_float`).
#      WHY FIVE ROUNDS MISSED ALL FOUR, counted rather than argued: 0 of the 107 values in the suite's
#      `HOSTILE_BY_KIND` + `LEGAL_BUT_WRONG` tables were `int`/`float` SUBCLASS instances. The tables
#      swept 44 hostile TYPES, all correctly rejected, and no hostile SUBCLASS -- a value space that a
#      table of ill-typed literals and a table of wrong-but-legal literals both miss by construction,
#      because the attack is in neither the type nor the stored value but in the dunders. The pin is
#      therefore not four more literals: `test_every_admitted_field_is_normalised_by_its_kind` derives
#      the fields from `dataclasses.fields()` of the verdict-bearing classes and asserts of each that
#      its kind hands back a value of EXACTLY the plain type, so a NEW field inherits the check.
#
#   7. ROUND 8: NORMALISING AT ADMISSION IS NOT ENOUGH IF A CONSUMER RE-READS THE FIELD AFTERWARDS.
#      Item 6 made the three numeric kinds hand back the number they had inspected, and the ONE consumer
#      that re-reads its field AFTER admission was missed. `_metric_cell` admitted through `_mv_float`,
#      discarded the admitted number, and rendered `_num(mv.value)` -- the raw object -- so the single
#      `float()` in this module consulted the caller's `__float__` after all, at the two call sites that
#      between them cover EVERY scorecard mean cell and EVERY record/training metric cell. `schema.py`
#      names the rule that was broken: "no consumer may read `.value` for itself". The measurements are
#      in `_metric_cell`'s own docstring; `_interval`, `_kind_cell` and `_kind_text` render the ADMITTED
#      value and were never wrong.
#      WHAT IS NEW HERE IS NOT THE ONE-LINER. Rounds 2, 3, 4 and 7 each ended "the guard was fixed and
#      the one consumer that re-reads was missed", and round 7's own pin
#      (`test_every_admitted_field_is_normalised_by_its_kind`) checks a kind function's RETURN TYPE and
#      never a RENDERED CELL -- one level below the gap it was written to close. The pin is therefore now
#      AT THE RENDER BOUNDARY: `EveryDeclaredNumberRendersTheAdmittedValue` forges every declared number,
#      and every `MetricValue` either renderer reaches, to a subclass that stores the HONEST double and
#      lies only on CONVERSION, then requires both FULL RENDERS to be BYTE-IDENTICAL to the honest ones.
#      A test of that shape does not care which function re-reads, how the read is spelled, or where the
#      next one appears; the pre-fix spelling of this cell is the only thing in either render that fails
#      it. It is NOT a completeness proof either: it sweeps the numbers that are DECLARED or reachable in
#      one payload, so an undeclared field reached only on an unexercised branch is outside it, as item 3
#      has said since round 4.
#
# WHAT IS DELIBERATELY NOT IN THE SCHEME is argued at `_valid_history` and `_protocol_params`.
def _num(x: float) -> str:
    """Render a number one of the four kind functions has ALREADY admitted.

    THE ONLY `float()` IN THIS MODULE, and it is not a gate -- it is reached only downstream of one.
    The coercions that used to sit in front of verdicts (`float(code)`, `float(c.margin)`,
    `float(getattr(margins, attr))`) are gone; see the scheme note above.

    AND ITS ARGUMENT IS NOW A PLAIN NUMBER, which is round 7 (scheme note item 6). This `float()`
    HONOURS A `__float__` OVERRIDE, so while the kinds handed back the caller's object it was itself a
    laundering step: measured, a `float` subclass storing an honest `pair.level` of 0.9875 whose
    `__float__` returned 0.5 printed `0.5` in every level cell of the same render that verified
    `t_lo`/`t_hi` against 0.9875. The kinds collapse a subclass to the number they inspected, so there
    is no override left for this call to consult.

    THAT SENTENCE WAS FALSE FOR ONE CALLER FOR A WHOLE ROUND, which is recorded here because it is the
    sentence a reader of this module trusts. `_kind_cell`, `_kind_text` and `_interval` pass the ADMITTED
    value; `_metric_cell` admitted through `_mv_float` and then passed `mv.value`, so for every scorecard
    mean cell and every record/training metric cell this `float()` did consult the caller's `__float__`
    (round 8; scheme note item 7). It is now true of all four callers, and it is no longer load-bearing
    prose: `EveryDeclaredNumberRendersTheAdmittedValue` renders every declared number through both real
    renderers with a conversion-only liar and compares BYTES, so a fifth caller that re-reads its field
    fails the suite rather than this paragraph."""
    return repr(float(x))


def _finite_float(x: Any) -> Optional[float]:
    """KIND "float": a genuine finite `float` and nothing else, AS A PLAIN `float`. None means "render
    UNKNOWN", never 0.0.

    IT RETURNS `float.__float__(x)`, NOT `x` (round 7; scheme note item 6). A `float` SUBCLASS instance
    passes `isinstance(x, float)` and need not lie to `math.isfinite`, which reads the stored double --
    so while this handed back `x` itself, every consumer downstream of the admission ran on the caller's
    overridable dunders rather than on the number this function inspected. `float.__float__` reads that
    same stored double and is not itself overridable from a subclass, so the number returned is the
    number checked. MEASURED on `pair.level` at the previous HEAD: a subclass storing the honest 0.9875
    with `__float__` returning 0.5 printed `0.5` in every level cell, while `_interval_problem` in the
    SAME render verified `t_lo`/`t_hi` against 0.9875 -- an edited figure, unalarmed, which
    `_pair_numbers_ok` rules is tampering "even when it buys nothing".

    Not `int`, not `bool`, not a numeric string, not NaN/inf. That is exactly the invariant
    `MetricValue.__post_init__` already enforces on a measured value (schema.py: float-only, bool
    rejected, `math.isfinite`), so a value that fails HERE cannot have come through the constructor --
    it was forged with `object.__setattr__`, or the field's type drifted. Used for `MetricValue.value`
    (via `_mv_float`), `pair.level` and the `SUBJECT_KIND_CODE` encoding: fields whose only honest
    producer emits a float.

    THE `bool` CLAUSE IS REDUNDANT HERE, and is labelled rather than left as a surviving mutant. Argued
    over the public API, not assumed: `bool` subclasses `int`, NOT `float` (`bool.__mro__` is
    (bool, int, object)), so `isinstance(True, float)` is False and `isinstance(x, bool)` can never be
    True while `isinstance(x, float)` is. No `float` subclass can also be a `bool` either, because `bool`
    cannot be subclassed at all (`class X(bool)` raises TypeError: not an acceptable base type). The
    clause is therefore unreachable for EVERY possible input, dropping it changes no output, and no test
    can pin it -- measured: that mutant survives the whole suite, and it is the only one that does.
    It is kept deliberately: in the sibling kinds `_finite_number` and `_count` the identical clause IS
    load-bearing, and widening this test to `(int, float)` would make it load-bearing here too."""
    if isinstance(x, bool) or not isinstance(x, float):
        return None
    v = float.__float__(x)                  # NORMALISE, then test: see the docstring
    return v if math.isfinite(v) else None


def _finite_number(x: Any) -> Optional[Any]:
    """KIND "num": a finite `int` or `float`, `bool` rejected, AS THE PLAIN NUMBER IT STORES -- `int`
    stays `int` and `float` stays `float`. None rejects.

    This is the kind for a field whose honest producer may legitimately emit either -- `Margins.delta_*`
    and `ComponentResult.margin` (`Margins.__post_init__` itself accepts `(int, float)`), the declared
    `width_tol`, and the training-history numbers. It is exactly the test the two margin DISPLAY cells
    already made inline; the round-4 defect was that the two margin VERDICT paths did `float(...)`
    instead, so the string `"0.1"` read UNKNOWN in both panels while a decisive verdict derived from it
    was displayed unalarmed. `bool` is load-bearing here, unlike in `_finite_float`.

    IT NORMALISES, AND THIS PARAGRAPH REPLACES THE ONE THAT WAS THE ROUND-7 DEFECT. That paragraph read:
    "It does NOT convert: an admitted `int` comes back an `int`, so the single `float()` in this module
    stays in `_num` where rendering happens, and comparisons against the declared margin stay exact."
    Both clauses were true of the code and the conclusion was false. Handing back `x` meant every
    cross-check downstream of `_admitted` ran on the CALLER'S OBJECT rather than on the number this
    function had just inspected, and an `int`/`float` SUBCLASS instance stores a legal value while
    answering `==`, `<`, `>` and `__float__` however it likes. MEASURED at the previous HEAD, both via
    `object.__setattr__` (benchmark's declared route (b)):
        ComponentResult.margin = float subclass storing -1e5, `__eq__`->True, `__float__`->0.1
            `margin != declared` was False, so `_recompute` recomputed an honest UNSUPPORTED study
            against -1e5: JOINT_UNSUPPORTED -> JOINT_SUPPORTED, 0 warning paragraphs, no alarm, and
            every figure on the page -- margin included -- honest.
        ComponentResult.width_tol = float subclass storing 1e9 with `__gt__`->False
            `min(c.width_tol, 0.25)` returned 1e9 and `_weaker_than_protocol` returned [], i.e. the
            protocol-6.3 floor was removed silently. (No verdict flip was found for it over 48 honest
            shapes, so it is a NOTE; the mechanism is closed here regardless.)
    `int`-vs-`float` IS STILL PRESERVED, which is why the normalisation is not `float(x)`: `_num` renders
    an int differently from a float, and `_declared`'s `margin != declared` is an exact comparison
    against a `Margins` field that may itself honestly be an `int`. `float.__float__`/`int.__int__` read
    the number the object STORES and cannot be overridden from a subclass, so the number returned is the
    number `math.isfinite` inspected -- which is also why the finiteness test now runs on the normalised
    value and not on `x`: an `int` subclass CAN lie to `math.isfinite`, because for a non-`float` that
    predicate consults `__float__` (measured: `math.isfinite(I(5))` is False for `class I(int)` with
    `__float__` returning nan, and True for one storing 10**400 with `__float__` returning 1.0).

    AN `int` TOO LARGE TO BE A `float` IS REJECTED, not raised. `math.isfinite(10**400)` raises
    OverflowError, and at the previous HEAD that escaped this module's error contract entirely: measured,
    `ComponentResult.margin = 10**400` (reachable by `object.__setattr__`, and absent from the suite's
    hostile-type table) made `render_scorecard` AND `render_dashboard` raise OverflowError rather than
    refuse the result -- a page taken down, which contradicts this module's own docstring promise and the
    `_seed_series` rule that an exception here would "fail open" in the operational sense. `benchmark`'s
    `_plain_number` had already closed exactly this case in its own lane; this is the same ruling."""
    if isinstance(x, bool) or not isinstance(x, (int, float)):
        return None
    v = float.__float__(x) if isinstance(x, float) else int.__int__(x)   # NORMALISE, then test
    try:
        return v if math.isfinite(v) else None
    except OverflowError:                   # an int too large to be a float is not a renderable number
        return None


def _count(x: Any) -> Optional[int]:
    """KIND "count": a genuine `int`, `bool` rejected, AS A PLAIN `int`. None rejects. Sign is NOT
    constrained here.

    For `pair.n`, `ComponentResult.min_n`, `JointResult.n_attempted`/`n_failed` and the snapshot's
    comparison counts. Sign stays with the caller on purpose: `_int_or_unk` must still print a negative
    `behind_by` as a number (it is a real datum), while `_recompute` separately refuses a negative
    `min_n` as a protocol parameter. Type is the shared part; domain is local and stated where it is.

    IT RETURNS `int.__int__(x)`, NOT `x` (round 7; scheme note item 6), because EVERY cross-check this
    kind feeds is an operator the caller's object can answer for itself. MEASURED at the previous HEAD,
    all via `object.__setattr__`:
        pair.n = `class NSub(int)` storing a legal 30 with `__gt__`/`__ge__` -> False, in the suite's
            OWN `laundered_below_minimum(n=NSub(30))` fixture: `_n_problem`'s `n > measured_n` was
            False and its `n >= min_n` was False, so BOTH sources went quiet on a genuine 29-seed run
            that still carried its 'n below protocol minimum' flag -- JOINT_SUPPORTED, 0 warning
            paragraphs, every alarm False, beside a gate row printing "29 measured seeds vs minimum 30".
            A plain `30` is caught. One `int` subclass undid rounds 5 and 6 together.
        ComponentResult.min_n = `class MSub(int)` storing 1 with `__lt__`/`__le__` -> False:
            `max(mn, 30)` returned 1, so `_recompute`'s protocol-6.1 floor was removed, and
            `_weaker_than_protocol` returned [] so the page did not even say the parameter was weak.
            `pair.n` was left honest, so the page printed 29 beside a decisive JOINT_SUPPORTED.
        JointResult.n_attempted = an `int` subclass overriding ONLY `__sub__` (stores 29, returns 30):
            `_measured_seeds`' `attempted - len(scores)` equality still held on the honest 29, and
            `attempted - failed` returned 30, so the second source for every `pair.n` reported 30
            measured seeds on a 29-seed study. It bought nothing alone (source (2), the pair's flag,
            still fired), but with the flags cleared it completed the F1 render.
    `int.__int__` reads the value the object stores and cannot be overridden from a subclass, so the
    number handed to those comparisons is the number this function admitted."""
    if isinstance(x, bool) or not isinstance(x, int):
        return None
    return int.__int__(x)                   # NORMALISE: see the docstring


def _mv_intact(mv: Any) -> Optional[Any]:
    """KIND "mv": a `MetricValue` that still satisfies its OWN constructor invariant -- properly
    unmeasured (`value is None`) or a finite float. None rejects.

    Distinct from `_mv_float` on purpose. `_mv_float` answers "is there a number to DISPLAY" (an
    unmeasured bound has none); this answers "has this object been TAMPERED WITH" (an unmeasured bound
    has not -- that is how an n < 2 interval is honestly built). Only post-construction tampering or a
    type drift in `MetricValue` can fail it, so it cannot false-fire on anything constructible."""
    if not isinstance(mv, MetricValue):
        return None
    return mv if (mv.value is None or _finite_float(mv.value) is not None) else None


_NUM_KINDS = {"float": _finite_float, "num": _finite_number, "count": _count, "mv": _mv_intact}

# EVERY stored number this renderer turns into a figure or feeds to a verdict, by the class that holds
# it. Keyed by class NAME, not by the class, so this table does not add an import-time dependency on
# `benchmark` beyond the one the module already declares (attributes are looked up at call time so API
# drift is detected).
# THIS COMMENT USED TO SAY "Proved complete by the recording-probe test, not by anyone's reading."
# SOFTENED, because the probe does not prove completeness: it hooks `__getattribute__`, so it is blind
# to `vars()`/`__dict__`/`object.__getattribute__`, blind to a read behind a branch its single render
# does not take, and blind BY CONSTRUCTION to a second read of an already-declared number (it compares
# attribute SETS). All four were measured as surviving mutants. The probe NAMES a new consumer cheaply;
# completeness, so far as it is established at all, rests on the behavioural forgery sweeps.
STORED_NUMBERS = {
    "IntervalPair": {"mean": "mv", "boot_lo": "mv", "boot_hi": "mv", "t_lo": "mv", "t_hi": "mv",
                     "n": "count", "level": "float"},
    "ComponentResult": {"margin": "num", "min_n": "count", "width_tol": "num"},
    "Margins": {"delta_S": "num", "delta_R": "num", "delta_sel": "num"},
    "JointResult": {"n_attempted": "count", "n_failed": "count"},
}
# Classes whose numbers reach a VERDICT, so `_recompute` must fail closed on every one of them.
#
# `JointResult` JOINED THIS TUPLE IN ROUND 5, and the comment it replaces is the clearest statement of
# the round-5 defect that exists in this file, so it is quoted rather than deleted: "the only reason an
# entry may legitimately render UNKNOWN without an alarm: `JointResult.n_attempted`/`n_failed` are
# counted on the page and feed no recomputation at all, so there is no verdict for them to fail closed
# on." Both halves were true as written and together they were the hole. `n_attempted - n_failed` is the
# study's own count of measured seeds -- the SECOND SOURCE for every component's `pair.n`, printed on
# the page one line above the gate row that contradicted it -- and "feeds no recomputation" was the
# defect, not the justification. It feeds one now (`_measured_seeds`), so it fails closed like the rest.
VERDICT_BEARING = ("IntervalPair", "ComponentResult", "Margins", "JointResult")


def _admitted(obj: Any, cls_name: str) -> Optional[dict]:
    """{attr: admitted value} for every number `STORED_NUMBERS` declares for `cls_name`, or None if any
    one of them is absent or rejected by its kind. An absent attribute is a rejection, so a stand-in
    object missing a field fails closed.

    IT RETURNS THE VALUES RATHER THAN A BOOL, and that is not a convenience. The first draft of this
    round returned a bool, so `_recompute` asked "are this component's numbers intact?" and then read
    `c.margin`, `c.min_n` and `c.width_tol` again through their kind functions -- two admissions per
    field. Measured: deleting the guard entirely then changed no output at all (the later reads caught
    everything), i.e. the round-4 fix had itself grown a masked duplicate of its own check, which is
    the whole failure mode of this item. Handing back the admitted values leaves exactly ONE admission
    per field and nothing to drift. `_admitted` IS NOW THE ONLY READER IN FACT AS WELL AS IN THE
    DOCSTRING: the `_numbers_intact` predicate alias that used to sit here was deleted in round 5 once
    `_pair_numbers_ok` had to consume the admitted `n` rather than a yes/no, because it would otherwise
    have been a module-level reader with no module-level caller.

    THE REMAINING `nums is None` GUARD IN `_recompute` IS PROVABLY EQUIVALENT TO NO GUARD, and is
    labelled rather than left as an unexplained surviving mutant: if it were dropped, the very next
    statement subscripts the result, `None["margin"]` raises TypeError, and `_recompute`'s `except`
    returns None -- the same value, for the same reason. Measured as a mutant: it survives the suite,
    and it is one of only two that do."""
    out = {}
    for attr, kind in STORED_NUMBERS[cls_name].items():
        v = getattr(obj, attr, _MISSING)
        a = None if v is _MISSING else _NUM_KINDS[kind](v)
        if a is None:
            return None
        out[attr] = a
    return out


def _mv_float(mv: Any) -> Optional[float]:
    """THE ONE PLACE a `MetricValue` becomes a number. None means "render UNKNOWN", never 0.0.
    A non-MetricValue, a genuinely unmeasured one, and one whose `value` was forged are all None."""
    return _finite_float(mv.value) if isinstance(mv, MetricValue) else None


def _kind_cell(x: Any, why: str, kind: str) -> str:
    """Render a stored number admitted by `kind`, boxed as `.measured`, or UNKNOWN with `why`. Never 0."""
    v = _NUM_KINDS[kind](x)
    return f'<span class="measured">{_e(_num(v) if kind != "count" else v)}</span>' if v is not None \
        else _unknown(why)


def _kind_text(x: Any, why: str, kind: str) -> str:
    """As `_kind_cell` but bare, for cells that are already inside a labelled phrase ("Attempted N",
    "direction margin"). Same admission; only the markup differs."""
    v = _NUM_KINDS[kind](x)
    return _e(_num(v) if kind != "count" else v) if v is not None else _unknown(why)


def _float_cell(x: Any, why: str) -> str:
    return _kind_cell(x, why, "float")


def _metric_cell(mv: Any) -> str:
    """Measured -> repr (0.0 stays 0.0). Unmeasured or absent or malformed -> UNKNOWN (+reason). Never 0.

    IT RENDERS THE ADMITTED NUMBER, NOT `mv.value`, which is round 8 (scheme note item 7). THE SENTENCE
    THIS REPLACES SAID "the float-and-finite test lives in `_finite_float`, shared with every other
    consumer of a stored number, so one value can never read UNKNOWN here and measured in the next
    cell", and it derived this cell's safety FROM THE WRONG PROPERTY. The premise is true and is kept
    below; the conclusion does not follow from it, because what this cell shared with the other
    consumers was the TEST and not the SOURCE. It called `_mv_float`, threw the admitted number away,
    and handed the RAW `MetricValue` object's `.value` to `_num` -- so `schema.py`'s rule, "which is why
    `toy.benchmark._metric_read` exists and why no consumer may read `.value` for itself", was broken by
    the one consumer that re-read the field after admission, and the module's single `float()` consulted
    the caller's `__float__`.

    MEASURED at the previous HEAD, 3.13.5 and 3.12.4 byte-identical, each forgery by `object.__setattr__`
    (benchmark's declared route (b); the public route is closed by `MetricValue.__post_init__`'s
    redundant `float.__float__` store, which re-plainifies a `_NORMALISE_EXEMPT` subclass):
        pair.mean = a `float` subclass storing the HONEST 0.9995918337735029 whose `__float__` returns
            0.5  ->  6 of 6 scorecard mean cells printed `0.5`, 0 warning paragraphs, alarm state
            byte-identical to the honest page, JOINT_SUPPORTED displayed. UNALARMED BY CONSTRUCTION, and
            that is the part worth reading twice: `_mv_float(forged)` returns the HONEST number, so
            `_interval_problem` and every round-6 cross-check see the truth and STRUCTURALLY CANNOT
            FIRE. The same subclass with `__float__` returning 0.0 printed `0.0`.
        an `ExperimentRecord` metric storing 0.9 with `__float__` returning 0.0  ->  the records panel
            printed `0.0`, via `_metric_table`: the second call site, every record and training metric.
        a `__float__` that RAISES  ->  `render_scorecard` AND `render_dashboard` both died with
            ZeroDivisionError. A page taken down, outside this module's stated error contract -- the
            same ruling `_finite_number` already made for `10**400`.
    `_interval` renders the admitted bounds and never had this defect: the identical forgery on
    `boot_lo`, `boot_hi`, `t_lo` and `t_hi` moves NOT ONE BYTE of either render (measured).

    THE PIN IS NOT THIS DOCSTRING, and not a fifth review of a one-liner. The gap is structural: round
    7's pin checks what a kind function RETURNS, so it cannot see a consumer that re-reads the field one
    level up. `EveryDeclaredNumberRendersTheAdmittedValue` forges every declared number -- and every
    `MetricValue` either renderer reaches -- to a subclass storing the honest double that lies only on
    CONVERSION, and requires both full renders to be byte-identical to the honest ones. It fails on this
    cell as it was spelled before the fix, and it does not care where the next re-read appears.

    The float-and-finite test does live in `_finite_float`, shared with every other consumer of a stored
    number, so one value cannot read UNKNOWN here and measured in the next cell. That is a claim about
    the TEST, and it is all the shared test buys. What makes this cell HONEST is that `_mv_float` is its
    only reader of `.value` and the number `_mv_float` returns is the number rendered."""
    if isinstance(mv, MetricValue):
        v = _mv_float(mv)
        if v is not None:
            return f'<span class="measured">{_e(_num(v))}</span>'
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
    """A snapshot comparison count. In the shared scheme (kind "count"), not a sibling implementation of
    it: round 3's surviving mutant M24 was exactly this cell admitting any non-`None`, and the snapshot
    is caller-supplied JSON, so `True`/`2.5`/`"many"`/`[1]` all reach it."""
    return _kind_cell(snap.get(key), f"{key} not present", "count")


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
            a, d = _count(f.get("additions")), _count(f.get("deletions"))
            if a is not None and d is not None:
                tot_a, tot_d = tot_a + a, tot_d + d
            else:
                ok_totals = False
            rows += (f"<tr><td>{_untrusted(f.get('filename', 'UNKNOWN'), 'path')}</td>"
                     f"<td>{_kind_text(a, 'additions', 'count')}</td>"
                     f"<td>{_kind_text(d, 'deletions', 'count')}</td></tr>")
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
    """Training-curve rows. IN the shared scheme (kind "num"), and it is the one member of it that is NOT
    a declared attribute of a scorer object: a history row is an untyped 3-tuple from a `TrainResult`,
    so there is no field to put in `STORED_NUMBERS`. It is routed anyway rather than left as a fourth
    correct-but-separate inline check, because "correct at HEAD but a separate implementation" is
    precisely what the previous two rounds left behind and round 3 then found twice. The row-shape
    check (arity, iterability) stays here: that is structure, not number admission."""
    good, bad = [], 0
    if not isinstance(history, (list, tuple)):
        return good, 0
    for row in history:
        try:
            s, l, g = row
            nums = [_finite_number(v) for v in (s, l, g)]
        except (TypeError, ValueError):
            nums = [None]
        if None in nums:
            bad += 1
        else:
            good.append(tuple(nums))
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
    except Exception:  # noqa: BLE001 - a patched/missing table is a problem, not a silent pass
        code = None
    # `_finite_float`, not the old `float(code)`: a table patched to `{"unknown": nan}` raises nothing and
    # so used to render a measured `nan` with NO problem reported. A code that is not a finite float is
    # not an encoding, whether the lookup raised or not.
    code_num = _finite_float(code)
    code_text = _num(code_num) if code_num is not None else None
    if code_text is None:
        problem = (problem + "; " if problem else "") + \
                  "benchmark.SUBJECT_KIND_CODE does not encode this kind as a finite number " \
                  "(table missing or patched)"
    try:
        exempt = [g.name for g in joint.gates if getattr(g, "exempt", False) is True]
    except Exception:  # noqa: BLE001
        exempt = []
    relabelled = bool(exempt) and kind != "fixture"
    if relabelled:
        # Wording precision: this proves the result changed AFTER construction, not WHICH side changed.
        # `JointResult.__post_init__` refuses this combination, so one of the two must have been edited --
        # but `benchmark.carries_exemption` reads `exempt` off ANY object in the gate list, so injecting a
        # duck-typed gate carrying `exempt=True` into an honestly-labelled result produces this same
        # message. The gates, not the label, may be what changed. Both are post-construction tampering.
        problem = (problem + "; " if problem else "") + \
                  (f"gate(s) {sorted(exempt)} carry the fixture exemption but subject_kind is "
                   f"{kind!r}: JointResult refuses that combination at construction, so the label or the "
                   f"gate list was relabelled after construction (which of the two is not determined)")
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
    """Both bounds measured and finite -> `[lo, hi]`. Anything else -> UNKNOWN, never `[0.0, 0.0]`.

    THE SR-13 FAIL GROUND. This used to gate on `MetricValue.is_measured` alone, which is merely
    `value is not None` (schema.py), and then call `_num` = `repr(float(x))`. A forged `value` of `0`,
    `False` or `"0"` therefore rendered `[0.0, 0.0]` in `.measured` monospace -- "an interval of [0, 0]
    where the value is genuinely unknown" -- NaN/inf rendered `[nan, nan]`, and `""`/`[]`/`{}` raised out
    of `float()` and took `render_dashboard` down, contradicting its own docstring (pure; a malformed
    object refused with NO figures). `_metric_cell` on the SAME `MetricValue` said UNKNOWN, so one
    rendered row contradicted itself: `mean` UNKNOWN beside two measured `[0.0, 0.0]` intervals.
    `_mv_float` is the shared check, and it never calls `float()`, so no input can crash here."""
    lo_v, hi_v = _mv_float(lo), _mv_float(hi)
    if lo_v is not None and hi_v is not None:
        return f'<span class="measured">[{_e(_num(lo_v))}, {_e(_num(hi_v))}]</span>'
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
    # The parameter NAMES being present is not enough: `_protocol_params` needs their DEFAULTS, and it is
    # the sole source of the protocol floor every recomputation applies. Measured before this existed: an
    # `interval_verdict` declaring `width_tol`/`min_n` with no defaults passed the signature check above,
    # so `_contract_problems` returned [] while `_protocol_params` raised LookupError; every component
    # then became 'could not recompute' and the page showed ONLY the generic "stored verdict disagrees"
    # warning -- which reads as an edited field when the truth is that the scorer's own protocol
    # parameters are unreadable. Reported here so the page says which it is (see `_protocol_params`).
    try:
        _protocol_params()
    except Exception as ex:  # noqa: BLE001 - any failure is a contract problem
        probs.append(f"interval_verdict protocol parameters (width_tol, min_n) unreadable: "
                     f"{type(ex).__name__}: {ex}")
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
    """(direction, margin) the PROTOCOL tables declare for this metric, margin read from the result's
    Margins. The margin is None if the Margins field is absent or is not a finite number.

    ROUND-4 FAIL GROUND (G2). This was `float(getattr(margins, attr))` -- a bare coercion, the exact
    pattern `_finite_float`'s own docstring already claimed had been eliminated. With `delta_S` set to
    the string `"0.1"` the margin read UNKNOWN in BOTH display panels (they checked properly) while the
    verdict derived from the coerced value was displayed as decisive with no alarm: a self-contradicting
    row plus unalarmed tampering. It could not be driven to a WRONG verdict, because the coerced value
    still had to float-equal the component's own margin, but "cannot be driven wrong" is not the
    criterion -- the criterion is that the display and the verdict admit the same values."""
    for table in (*bm.PRIMARY.values(), bm.CONVERGED):
        for m, direction, attr in table:
            if m == metric:
                return direction, _finite_number(getattr(margins, attr, None))
    raise LookupError(f"metric {metric!r} not in the protocol tables")


def _protocol_params() -> tuple:
    """The protocol's declared `(width_tol, min_n)`, read from the scorer's own `interval_verdict`
    signature instead of being hard-coded here, so a protocol-parameter change in `benchmark` is picked up
    rather than silently contradicted. Raises if either default is missing or not a usable number; the
    caller turns that into 'could not recompute', and `_contract_problems` calls this function and reports
    the failure on the page (it checks parameter NAMES, which a defaultless signature passes, so the name
    check alone left an unreadable protocol parameter visible only as a generic verdict disagreement).

    IN the shared scheme by kind but NOT in `STORED_NUMBERS`, deliberately: these two are not stored
    numbers of a RESULT, they are the scorer's own declared defaults read out of its signature, so there
    is no object to put in the table and no forgery sweep to run over them. They are routed through the
    kind functions anyway so that this module keeps exactly four numeric predicates. `min_n` is admitted
    as kind "count" rather than "num": it is a seed COUNT, and admitting it as a count removes the
    `int(mn_declared)` coercion `_recompute` used to apply to it."""
    params = inspect.signature(bm.interval_verdict).parameters
    out = []
    for name, kind in (("width_tol", "num"), ("min_n", "count")):
        v = _NUM_KINDS[kind](params[name].default)
        if v is None:
            raise LookupError(f"interval_verdict declares no usable default for {name}")
        out.append(v)
    return tuple(out)


NO_SECOND_SOURCE_MSG = ("the study's own measured-seed count (n_attempted - n_failed) is not readable, "
                        "so the sample size behind every interval cannot be cross-checked")
NO_INTERVAL_SOURCE_MSG = ("the per-seed series behind this interval is not readable from this result's own "
                          "seed_scores, so the stored mean and t-interval cannot be cross-checked")
MIN_SEEDS_FLAG = "n below protocol minimum"
# The literal `benchmark.summarize` appends to `IntervalPair.flags` when `n < min_n`. It is a string
# SHARED with the scorer, so a rename there would silently disable source (2) of `_n_problem` rather
# than break anything. That is pinned by a test against the scorer's real output rather than by a
# render-time contract probe, deliberately: `_contract_problems` withholds every decisive verdict when
# it fires, and a page must not lose its verdicts because a neighbouring module in flux renamed a flag.
# Residual, stated: between a rename in `benchmark` and the next run of this module's suite, source (2)
# is silently inert. Source (1), which needs no literal, is not affected.


def _measured_seeds(joint: Any) -> Optional[int]:
    """THE SECOND SOURCE FOR `pair.n`: how many seeds this study says actually produced data.

    `n_attempted - n_failed`, both admitted as kind "count" from `STORED_NUMBERS`, and then checked
    against the `seed_scores` list they were counted from. None means "there is no readable second
    source", which every caller treats as fail-closed -- NOT as "skip the cross-check". That asymmetry
    is deliberate and is the one place this function is stricter than `benchmark.verdict_from_records`,
    which skips its own cross-check when the stored `n_seeds` METRIC is absent from the record (there,
    absence is a real possibility, because the second source is a dict entry). Here both numbers are
    required fields of `JointResult`, so an honest producer cannot omit or malform them; absence or
    malformation is tampering or a type drift, and `benchmark._metric_strict` states the rule for
    exactly this case -- for a cross-check field "unreadable" is evidence of tampering and must not be
    laundered into the same outcome as "not recorded".

    WHY THE `seed_scores` ANCHOR IS HERE AND NOT LEFT AS A RESIDUAL. A cross-check whose second source
    is one more producer-asserted integer is defeated by one more `object.__setattr__`. MEASURED on the
    round-5 fixture (29 genuine seeds, `pair.n` forged to 30) with the n-cross-check in place but no
    anchor: `n_attempted` forged to 30, to 1000, or to 31-with-`n_failed`-1 each restored
    JOINT_SUPPORTED with no alarm. `analyze_scores` builds the result as
    `JointResult(..., scores, ..., len(scores), sum(not s.ok for s in scores), ...)`, so
    `n_attempted == len(seed_scores)` and `n_failed == the number of not-ok entries` hold identically
    for every result the scorer produces, and `seed_scores` is a LIST OF OBJECTS rather than an integer.
    RESIDUAL, RE-MEASURED AND RESTATED. This used to say the anchor "raises the cost of the forgery to
    fabricating seed-score objects". MEASURED at the previous HEAD, that cost was ZERO fabricated
    objects: duplicating one EXISTING entry (`seed_scores[0]`) plus two `object.__setattr__` and
    clearing the six `flags` tuples gave `_measured_seeds = 30`, no alarm and a displayed JOINT_SUPPORTED
    on a genuine 29-seed run. The distinctness equality below closes exactly that variant, and
    `_interval_problem`'s series cross-check independently closes BOTH it and the
    fabricate-one-new-seed variant, because an appended entry changes the series every stored `mean` and
    t-interval was computed from (measured on both variants: stored mean 0.9995971789304974 against a
    recomputed 0.99982530375834). WHAT REMAINS: a tamperer who rebuilds `seed_scores` AND every
    component's pair consistently -- who produces a study of the shape they claim -- still gets through.
    That is the same residual class as the consistently-forged `Margins` at `_recompute`; it is no longer
    a cheap one.

    `attempted - failed` needs no nonnegativity guard, and one is deliberately absent rather than left
    as an unpinnable surviving mutant: `failed` equals the not-ok count of a tuple whose length equals
    `attempted`, so `failed <= attempted` is already proved by the two equalities above it.

    THE SEED IDS MUST BE DISTINCT, and that third equality is this round's addition -- the measurement
    that forced it is the one in the residual paragraph above: `len(seed_scores) = 30` over 29 DISTINCT
    seeds satisfied both of the other equalities. `benchmark.evaluate_gates` already applies
    `len(set(ids)) != len(ids)` to the same list for `seed_list_frozen`; this function did not.
    Cannot false-fire: measured over all 18 honest shapes, 0 have a repeated seed id, and a
    study that honestly analysed one seed twice FAILS `seed_list_frozen`, a global gate, so every verdict
    is already withheld -- and with ids repeated there is genuinely no readable count of DISTINCT seeds
    that produced data, which is the quantity `pair.n` is being compared against.
    `_MISSING` as the stand-in for an absent `seed` is deliberate: it is ONE sentinel object, so two
    attribute-less entries collide and the check refuses them, which is the fail-closed direction."""
    nums = _admitted(joint, "JointResult")      # the ONLY admission of these two in the verdict path
    if nums is None:
        return None
    attempted, failed = nums["n_attempted"], nums["n_failed"]
    try:
        scores = tuple(joint.seed_scores)
        listed_failed = sum(1 for s in scores if getattr(s, "ok", None) is not True)
        ids = [getattr(s, "seed", _MISSING) for s in scores]
        distinct = len(set(ids)) == len(ids)
    except Exception:  # noqa: BLE001 - an absent or unreadable seed-score list is no second source
        return None
    if attempted != len(scores) or failed != listed_failed or not distinct:
        return None
    return attempted - failed


def _seed_series(scores: tuple, metric: Any) -> Optional[list]:
    """The per-seed series this study's own `seed_scores` yield for one protocol metric, or None if the
    list cannot be read as one. THE SECOND SOURCE FOR `mean`, `t_lo` and `t_hi` (see `_interval_problem`).

    Rebuilt the way `benchmark.analyze_scores` builds it -- the OK seeds' readable values, in list order:
        series[k] = [v for v in (_metric_read(s.metrics[k]) for s in scores if s.ok) if v is not None]
    with two deliberate differences, both in the fail-closed direction:

      * `getattr(s, "ok", None) is not True` skips an entry, matching `_measured_seeds` exactly rather
        than `analyze_scores`' truthiness test, so the two halves of the anchor agree on which entries
        count. A duck-typed `ok` of `1` is excluded here and included there, which can only make the
        recomputed series disagree with the stored interval, never agree with a forged one.
      * A per-seed metric that is not an INTACT `MetricValue` returns None for the whole series instead
        of being silently dropped. `analyze_scores` drops it because for IT a `None` read is an honestly
        unmeasured metric; HERE the difference matters, because dropping a forged entry would let a
        tamperer SHORTEN the series the cross-check is computed from. `_mv_intact` separates the two: an
        honestly unmeasured metric satisfies `MetricValue`'s own constructor invariant and is skipped (it
        has to be -- that is the `delta_conv`-unmeasured-on-5-seeds shape, a legitimate study), while a
        value forged by `object.__setattr__` fails it and the series is refused.

    An absent/unreadable `metrics`, or a metric this result does not carry, is likewise None.

    THE WHOLE WALK IS INSIDE ONE `try`, AND THE `ok` READ IS THE REASON. `getattr(s, "ok", None)` does
    NOT fail safe on its own: `SeedScores.ok` is a PROPERTY that subscripts `self.metrics`, so with
    `metrics` replaced by `None` the property raises `TypeError` and `getattr`'s default never applies --
    found by this module's own junk-input test, which crashed the first draft of this function.
    `render_dashboard` promises that a malformed object is refused with no figures rather than taking the
    page down, so an exception here would contradict the module docstring as well as fail open."""
    vals = []
    try:
        for s in scores:
            if getattr(s, "ok", None) is not True:
                continue
            mv = s.metrics[metric]
            if _mv_intact(mv) is None:
                return None
            v = _mv_float(mv)
            if v is not None:                   # honestly unmeasured on this seed: skipped, as upstream
                vals.append(v)
    except Exception:  # noqa: BLE001 - no readable per-seed metric is no second source
        return None
    return vals


def _measured_series(joint: Any) -> dict:
    """{metric: `_seed_series`} for every metric the PROTOCOL TABLES declare, read ONCE per card.

    Keyed off `bm.PRIMARY` / `bm.CONVERGED` rather than off the components, for the same reason
    `_component_sets_ok` and `_declared` are: the expected set of metrics is the protocol's, not the
    result's. A metric whose series cannot be rebuilt maps to None, and a metric that is not in the dict
    at all (a component with an unrecognised `metric`) is read by `_series_of` as None -- both of which
    every caller treats as fail-closed, NOT as "skip the cross-check"."""
    try:
        want = [m for table in (*bm.PRIMARY.values(), bm.CONVERGED) for m, _d, _a in table]
        scores = tuple(joint.seed_scores)
    except Exception:  # noqa: BLE001 - no tables or no seed-score list is no second source
        return {}
    return {m: _seed_series(scores, m) for m in want}


def _series_of(series: Any, metric: Any) -> Optional[list]:
    """One metric's series out of `_measured_series`' dict. The single lookup, so "no entry" and "entry
    is None" cannot be told apart by a caller and accidentally treated differently."""
    try:
        return series[metric]
    except Exception:  # noqa: BLE001
        return None


def _show_num(x: Any) -> str:
    """An already-admitted optional number, for a message. None is the honestly-unmeasured state."""
    return _num(x) if x is not None else "unmeasured"


def _same_number(stored: Any, want: Any) -> bool:
    """Exact equality between a stored number and a recomputed one, on the doubles they actually STORE.

    NOT `stored == want`, and the reason is `benchmark._plain_number`'s, argued over the public API
    rather than assumed: `MetricValue.__post_init__` tests `isinstance(self.value, float)`, which a
    `float` SUBCLASS passes, and `math.isfinite` reads the stored double, which the subclass need not lie
    about -- so `MetricValue.measured(Sneaky(0.5))` is constructible through the PUBLIC api with
    `__eq__` returning whatever it likes. A cross-check decided by an overridable `__eq__` is not a
    cross-check. `bm.mean([x])` is the scorer's own normalise-before-checking reader (`_plain_number`
    -> `float.__float__`, which reads the stored value and never consults a `__float__` override); it
    returns a plain `float`, so the comparison that decides is `float.__eq__` on two plain floats. It
    also RAISES on a non-number or a non-finite one, which is the fail-closed answer here."""
    try:
        return bm.mean([stored]) == bm.mean([want])
    except Exception:  # noqa: BLE001 - not comparable as numbers: not equal
        return False


def _interval_problem(nums: Mapping, series: Optional[list]) -> Optional[str]:
    """THE ROUND-6 CROSS-CHECK on `mean`, `t_lo` and `t_hi`. None means cross-checked; a string is the
    disagreement, in the words the page prints. `nums` is `_admitted(pair, "IntervalPair")`'s output, so
    nothing is admitted twice here.

    WHAT THE PREVIOUS ROUND DECLARED, AND WHY IT WAS FALSE. These three were classified
    `NO_SECOND_SOURCE`, "the interval itself is producer-asserted". An EXACT second source was already
    in the same `JointResult` and this module already read it: the per-seed series rebuilt from
    `joint.seed_scores` (which `_measured_seeds` has read since round 5) plus the admitted `pair.level`.
    `benchmark.evaluate_primary` builds every pair as `summarize(name, series[metric], level, ...)`, and
    `summarize` sets `mean = _mv(mean(vals))` and `(t_lo, t_hi) = t_interval(vals, level)`, so
    `bm.mean` and `bm.t_interval` reproduce all three BIT-EXACTLY. MEASURED over the 18 honest shapes:
    108 component instances, 324 component-field comparisons, 324 exact, 0 mismatched.

    AND `t_lo`/`t_hi` ARE VERDICT-BEARING. They are protocol 6.3's bootstrap/t disagreement rule, which
    `docs/EVALUATION_PROTOCOL.md` names as one of only two verdict-bearing safeguards for tails. The
    only check applied to them was `_mv_intact`, a TYPE check -- verbatim the round-5 defect, admitted by
    type alone while a second source in the same object went unused. MEASURED at the previous HEAD on an
    HONEST 30-seed study with one heavy-tailed seed, whose H1 is INCONCLUSIVE because the real t-interval
    straddles the margin while the bootstrap interval does not:
        untouched                                   -> H1 INCONCLUSIVE, JOINT_INCONCLUSIVE   (correct)
        t_lo/t_hi forged to the bootstrap bounds     -> H1 SUPPORTED, JOINT_SUPPORTED, NO ALARM
    i.e. two `object.__setattr__` inside two `MetricValue`s turned a run that protocol 6.3 refuses a
    verdict into a displayed, decisive success. `mean` reaches no verdict, like `level`; it is checked on
    this module's own standing rule for `level` -- an edited figure is unalarmed tampering even when it
    buys nothing -- and at the previous HEAD `mean` forged to `0.5` on every component rendered `0.5` in
    `.measured` monospace beside a decisive JOINT_SUPPORTED with no alarm.

    THE RECOMPUTATION'S OWN INPUTS FAIL CLOSED, and this is the mutant-D5 lesson from last round applied
    before it can be repeated: `series is None` (an unreadable `seed_scores`, a tampered per-seed metric,
    an unrecognised metric name) returns a PROBLEM, never None. An unusable second source must not
    silently skip the check. The same holds for `level`: it is an input to `t_interval`, so a forged
    level either makes `t_interval` raise (out of (0, 1): `_check_level`) or produce different bounds --
    both caught here. That is why `level` is no longer classified as having no second source.

    `boot_lo`/`boot_hi` ARE NOT CHECKED HERE AND CANNOT BE. `summarize` computes them as
    `bootstrap_ci(vals, level, n_boot, make_rng(derive_seed(base_seed, "bootstrap:" + name)))`, and
    NEITHER `n_boot` NOR `base_seed` IS A FIELD OF `JointResult` -- confirmed from
    `dataclasses.fields(JointResult)`: it carries an opaque `config_hash` and a `seed_list_digest`, and
    `freeze_seed_list` derives the seeds by `derive_seed(base_seed, "replicate:k")`, a hash. The
    bootstrap resample is therefore not reproducible from the result, and the two bootstrap bounds stay a
    stated residual rather than a check that could only be written by guessing a seed.

    Cannot false-fire: every honest pair is `summarize`'s own output over the series this function
    rebuilds, which is the 324/324 measurement above, and the n < 2 shapes are handled explicitly --
    `summarize` returns all-unmeasured for n == 0 and an unmeasured t-interval for n == 1, so those are
    what is REQUIRED there, not what is tolerated."""
    if series is None:
        return NO_INTERVAL_SOURCE_MSG
    try:
        if len(series) == 0:                     # summarize's n == 0 branch: nothing is measured
            want = (None, None, None)
        elif len(series) == 1:                   # ... and its n == 1 branch: a mean, no t-interval
            want = (bm.mean(series), None, None)
        else:
            want = (bm.mean(series), *bm.t_interval(series, nums["level"]))
    except Exception:  # noqa: BLE001 - the series or the level is not usable: no readable second source
        return NO_INTERVAL_SOURCE_MSG
    for attr, w in zip(("mean", "t_lo", "t_hi"), want):
        got = _mv_float(nums[attr])              # None is the honestly-unmeasured state, not a rejection
        if (got is None) != (w is None) or (got is not None and not _same_number(got, w)):
            return (f"the interval's stored {attr} is {_show_num(got)} but the {len(series)} per-seed "
                    f"value(s) this study records for this metric give {_show_num(w)} at the stored "
                    f"level {_num(nums['level'])}: an interval cannot disagree with the data it was "
                    f"computed from")
    return None


def _n_problem(pair: Any, n: int, min_n: int, measured_n: Optional[int]) -> Optional[str]:
    """THE ROUND-5 CROSS-CHECK on one component's `pair.n`. None means cross-checked; a string is the
    disagreement, in the words the page prints. `n` and `min_n` are values already admitted by kind
    "count", so nothing is admitted twice here.

    TWO SOURCES, BOTH ALREADY PRESENT IN THE RESULT, NEITHER OF THEM A TYPE TEST:

    (1) `n <= _measured_seeds(joint)`. This is `benchmark.verdict_from_records`' invariant verbatim --
        `component n <= joint n`, equality NOT required -- and it is verified here on the same grounds
        it is verified there: `analyze_scores` builds every series as the OK seeds' readable values, so
        a component's `n` is the size of a SUBSET of the measured seeds. MEASURED over 12 legitimate
        study shapes (30-seed default, S=0.0, L=1.0, conv=False, gate_inputs=False, unregistered digest,
        29 seeds, 1 seed, n_failed = 1 / 3 / 10, and one converged metric left unmeasured on 5 OK
        seeds): the inequality held in 12 of 12 and was STRICT in THREE COMPONENT INSTANCES ACROSS TWO
        SHAPES -- `conv=False` gives `pair.n = 0` on BOTH of its converged components (two instances,
        one shape) and the unmeasured-metric shape gives `delta_conv n = 25` against 30 measured seeds
        (one instance) -- which is why equality must not be required. The sentence this replaces said
        "STRICT in three of them", which reads as three SHAPES and is false; re-counted over the 18
        honest shapes the suite now builds: 3 strict instances of 108, in 2 shapes of 18.

    (2) The producer's own statement, `MIN_SEEDS_FLAG in pair.flags`. `summarize` appends it exactly
        when `n < min_n`, and `evaluate_primary` passes the same `cfg.min_seeds` to `summarize` and to
        the `ComponentResult`, so on an honest component the flag is present only when `n < c.min_n`.
        MEASURED over 48 honest (shape x component) pairs: 14 flagged, 0 violations; and over five
        non-default `min_seeds` configurations (10/10, 10/30, 29/29, 1/30, 60/30), including the
        honest `min_seeds=60` case where the flag IS present at n=30, 0 violations.
        ONLY THE ONE DIRECTION IS ASSERTED. "flag present => n < min_n" is used; "n < min_n => flag
        present" is NOT, and must not be: `benchmark._pair_from_record` rebuilds an `IntervalPair` from
        stored metrics and passes no `flags` at all, so a records-roundtripped below-minimum pair
        legitimately carries an EMPTY flags tuple. The one-directional form is also the only one a
        forgery cannot exploit -- deleting the flag merely gives up a check, it buys nothing.

    A THIRD SOURCE IS ON THE PAGE AND IS DELIBERATELY NOT USED. The `min_seeds` gate row renders its own
    detail text, which on the round-5 fixture reads "29 measured seeds vs minimum 30" -- the true value,
    beside a PASS it contradicts. It is not read here, and should not be: `GateResult.reason` is free
    text, it reaches the page only through `_untrusted`, and structural guard 3 in this module's own
    docstring is "No verdict is ever parsed from any string". Deriving a fail-closed from a regex over a
    producer-supplied sentence would make the gate text verdict-bearing, which is the guard this renderer
    is built on. Nothing is given up by refusing it: `evaluate_gates` computes that sentence as
    `f"{n_ok} measured seeds vs minimum {cfg.min_seeds}"` with
    `n_ok = len(scores) - sum(not s.ok for s in scores)`, which is the SAME number, off the SAME
    `seed_scores` list, that `_measured_seeds` reads directly as typed data. The gate row renders it as a
    string; the anchor reads it as a list of objects. The second is the better source for the same fact.

    THE CROSS-CHECK IS ONE-SIDED (`n > measured_n`, not `n != measured_n`) for the same reason
    `_recompute`'s protocol floor is one-sided: an INFLATED `n` is the only direction that can buy a
    decisive verdict, because the only thing `interval_verdict` does with `n` is apply the protocol-6.1
    floor `n < min_n`. A DEFLATED `n` drives the floor the safe way and is caught anyway, one layer on,
    as a disagreement with the stored verdict: measured, `pair.n` forged from 30 down to 5 renders
    INCONCLUSIVE with an alarm.

    `flags` MUST BE A TUPLE. `IntervalPair.flags` is declared `tuple = ()` and both producers in
    `benchmark` emit one, so requiring it cannot false-fire; without the requirement a `flags` forged to
    the bare STRING "n below protocol minimum" would silently disable source (2), because `in` over a
    string matches characters. A non-tuple `flags` is a type drift and fails closed, like a non-number
    in the kind functions."""
    if measured_n is None:
        return NO_SECOND_SOURCE_MSG
    if n > measured_n:
        return (f"a component claims {n} seeds but the study records only {measured_n} measured seeds "
                f"(attempted minus failed): a component cannot be measured on more seeds than succeeded")
    flags = getattr(pair, "flags", None)
    if not isinstance(flags, tuple):
        return "the interval's own flags field is not a tuple, so the producer's sample-size statement " \
               "cannot be read"
    if MIN_SEEDS_FLAG in flags and n >= min_n:
        return (f"the producer flagged this interval {MIN_SEEDS_FLAG!r} but its stored n is {n}, which "
                f"is not below the declared minimum {min_n}")
    return None


def _pair_numbers_ok(pair: Any, min_n: int, measured_n: Optional[int], series: Optional[list]) -> bool:
    """EVERY number `STORED_NUMBERS` declares on an `IntervalPair` -- not just the four bounds -- must
    still be admitted by its kind AND, for `n`, `mean`, `t_lo` and `t_hi`, agree with the result's own
    second sources, or the recomputation fails closed.

    WHY IT IS THE WHOLE DECLARED SET AND NOT A HAND-WRITTEN LIST (the round-4 FAIL ground, G1). This
    function used to list `boot_lo, boot_hi, t_lo, t_hi` inline and nothing else, and `pair.n` was
    therefore checked by its display cell only. `interval_verdict` applies protocol 6.1's minimum-n floor
    as `n < min_n`, and `nan < 30` and `inf < 30` are both False, so a forged `n` SAILED THROUGH THE
    FLOOR AS A NUMBER: measured on a genuine 29-seed run with seven passing gates, forging `n` to `nan`
    turned a stored JOINT_INCONCLUSIVE into a displayed, decisive JOINT_SUPPORTED with zero warning
    paragraphs on the page and the sample-size cell reading UNKNOWN. A forged *bound* failed closed with
    an alarm; a forged *n* did not, because a hand-written list is exactly the thing that goes stale.
    `pair.level` is in the set for the same reason, though it reaches no verdict on its own: a pair whose
    level was edited is not a pair whose interval can be read, and HEAD showed a forged level as UNKNOWN
    with no alarm -- unalarmed tampering, the same shape as G2.

    WHY THE DECLARED SET WAS STILL NOT ENOUGH (the round-5 FAIL ground). Admitting `pair.n` by TYPE left
    the legal int `30` admissible on a 29-seed run, which is the whole of round 5; `_n_problem` is the
    cross-check that closes it and this is the single place in the verdict path that calls it, so there
    is one implementation of "is this n believable" rather than one per consumer.

    AND THE DECLARED SET WITH ONE CROSS-CHECK WAS STILL NOT ENOUGH (the round-6 FAIL ground). `mean`,
    `t_lo` and `t_hi` were admitted BY TYPE ALONE and DECLARED to have no second source, while an exact
    one sat in the same `JointResult` -- the per-seed series `_measured_seeds` already reads. `t_lo`/`t_hi`
    carry protocol 6.3's disagreement rule, so that was round 5's defect in a second lane.
    `_interval_problem` is the cross-check that closes it, and this is the single place in the verdict
    path that calls it.

    ONE CLAIM ABOUT `pair.level` IS WITHDRAWN HERE AND ONE IS KEPT. WITHDRAWN: "level reaches no verdict
    (`interval_verdict` never reads it), so there is nothing a forged level could buy that the type check
    does not already refuse." `interval_verdict` still never reads it, but this module now passes it to
    `bm.t_interval` as the second source for the t-interval, so a forged level changes a recomputation
    and is caught. MEASURED at the previous HEAD, forging `level` on every pair of an honest 30-seed
    study to each of 0.95, 0.99, 0.5, 5.0, -1.0 and 0.0: the level cell rendered the forged number as a
    measurement, `_pair_numbers_ok` returned True, and the page displayed JOINT_SUPPORTED with no alarm
    -- for `5.0`, `-1.0` and `0.0` too, which are not confidence levels and which `bm._check_level`
    refuses outright. KEPT, because it is about a DIFFERENT second source and is still correct: the
    `bm.bonferroni_level()` figure printed in the family line is NOT compared with `pair.level`, because
    an honest level is `bonferroni_level(cfg.alpha, N_PRIMARY)`, `BenchmarkConfig.alpha` IS settable, and
    `JointResult` carries only an opaque `config_hash` -- so that comparison would false-fire on every
    honest non-default-alpha study, the identical undecidability argued for `min_n` and `width_tol` at
    `_recompute`. The t-interval equation needs no `alpha` and so has no such limit.

    Cannot false-fire: nothing an honest producer builds fails it. Each bound and `mean` must satisfy
    `MetricValue`'s own constructor invariant (so a genuinely unmeasured n<2 bound is fine), `n` is
    `len(values)`, `level` is `bonferroni_level()`, and `mean`/`t_lo`/`t_hi` are `summarize`'s own output
    over the series `_seed_series` rebuilds (measured: 324 of 324 component-field comparisons exact over
    18 honest shapes). Only post-construction tampering reaches it, and the no-false-alarm sweep below
    measures that over every honest fixture variation -- which now has to cover both cross-checks, since
    a false-firing cross-check is itself a defect."""
    nums = _admitted(pair, "IntervalPair")      # the ONLY admission of the pair's numbers in this path
    return (nums is not None and _n_problem(pair, nums["n"], min_n, measured_n) is None
            and _interval_problem(nums, series) is None)


def _recompute(c: Any, margins: Any, measured_n: Optional[int], series: Mapping) -> Optional[Verdict]:
    """Verdict recomputed from the interval alone. None means 'could not recompute' (always treated as a
    mismatch and shown INCONCLUSIVE with an alarm, never as SUPPORTED).

    `measured_n` AND `series` ARE REQUIRED ARGUMENTS WITH NO DEFAULTS, and that is the point of rounds 5
    and 6. They are the result's own second sources, from `_measured_seeds` (the measured-seed count that
    `pair.n` is checked against) and `_measured_series` (the per-seed series that `mean`, `t_lo` and
    `t_hi` are checked against); an unreadable one fails closed. Giving either a default would make
    "nobody passed the second source" indistinguishable from "the second source is broken" at every call
    site -- a fail-open default on the exact parameters these rounds exist to add -- so the internal
    callers and every direct test call name them explicitly instead.

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
    but are producer-asserted, not authenticated. The intervals are producer-asserted too, and ROUND 6
    NARROWED -- did not remove -- that residual: a same-name component carrying a forged pair is now
    caught unless the per-seed series in the SAME result is restated to match it (`_interval_problem`), so
    what remains is a forger who rewrites the data as well. MEASURED: transplanting a strong H3 component
    into a weak study is now INCONCLUSIVE and named, while the same transplant plus 90 rewritten per-seed
    `MetricValue`s is still SUPPORTED with no alarm. And a forged protocol parameter that is weaker
    than the floor but would not have changed this component's verdict anyway raises no alarm, because the
    floor makes it unable to change what is displayed.

    EVERY NUMBER IT READS IS ADMITTED BY THE SHARED SCHEME FIRST, by class, from `STORED_NUMBERS` --
    `VERDICT_BEARING` names the four classes and this is the function that owes them a fail-closed. The
    bare `float(c.margin)` that used to stand here is G2 (see `_declared`); the missing `pair.n` is G1
    (see `_pair_numbers_ok`); admitting that `pair.n` BY TYPE ALONE is round 5 (see `_n_problem`);
    admitting `mean`/`t_lo`/`t_hi` BY TYPE ALONE while declaring they had no second source is round 6
    (see `_interval_problem`). What stays local, because it is DOMAIN and not admission: a negative
    `width_tol` or `min_n` is a nonsensical protocol parameter rather than a non-number, and the
    one-sided floor itself."""
    try:
        nums = _admitted(c, "ComponentResult")                  # the ONLY admission of these three
        if nums is None or not _pair_numbers_ok(getattr(c, "pair", None), nums["min_n"], measured_n,
                                                _series_of(series, getattr(c, "metric", _MISSING))):
            return None
        margin, mn, wt = nums["margin"], nums["min_n"], nums["width_tol"]
        if margins is not None:
            direction, declared = _declared(c.metric, margins)
            if declared is None or c.direction != direction or margin != declared:
                return None
        wt_declared, mn_declared = _protocol_params()
        if wt < 0 or mn < 0:
            return None
        v, _ = bm.interval_verdict(c.pair, margin, c.direction,
                                   min(wt, wt_declared), max(mn, mn_declared))
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


def _eff_component(c: Any, withheld: bool, contract_bad: bool, margins: Any, measured_n: Optional[int],
                   series: Mapping) -> tuple:
    """(displayed verdict or None, mismatch). Decisive only if stored AND recomputed agree and nothing withholds it."""
    stored = _vcoerce(Verdict, getattr(c, "verdict", None))
    rec = _recompute(c, margins, measured_n, series)
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
    producer-asserted, and a component with the correct metric name carrying a forged interval pair (and
    a matching stored verdict) is not caught HERE. It is no longer unalarmed, though, which is a round-6
    correction to this paragraph: `_interval_problem` compares the pair's `mean` and t-interval against
    the per-seed series the same result carries, so the forged pair must agree with that data too. The
    residual is now a forger who restates the series as well (measured at
    `test_the_transplanted_pair_residual_now_costs_the_whole_series`), and the two BOOTSTRAP bounds,
    whose resample is not reproducible from a `JointResult` at all."""
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
    warning and so imply that somebody edited a field.

    WHAT THIS LIST DOES NOT ESTABLISH. It names a declared value that is weaker than the protocol's; it
    does not establish WHY it is weaker. An honest non-compliant configuration and a parameter edited
    after the fact both land here and are indistinguishable from the result alone, so the caller
    (`render_scorecard`) must assert neither -- it used to assert the honest reading unconditionally,
    including over two measured forgeries. The one thing the caller CAN say is whether a decisive verdict
    was actually withheld, which it reads off its own `mismatch`/`bad` state rather than from this list."""
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
            mn, wt = _count(getattr(c, "min_n", None)), _finite_number(getattr(c, "width_tol", None))
            if mn is not None and 0 <= mn < mn_declared:
                out.append(f"{h.hid}/{_visible(str(c.metric))[:40]}: min_n={mn} is below the protocol "
                           f"minimum {mn_declared}")
            if wt is not None and wt > wt_declared:
                out.append(f"{h.hid}/{_visible(str(c.metric))[:40]}: width_tol={_num(wt)} is wider than "
                           f"the protocol tolerance {_num(wt_declared)}")
    return out


def _n_sources_disagree(joint: Any, measured_n: Optional[int]) -> list:
    """Components whose stored `n` disagrees with the result's own second sources, in the page's words.

    THE PROSE SIBLING OF THE VERDICT PATH, exactly as `_weaker_than_protocol` is for the protocol floor,
    and accepted here for the same reason: the GUARD lives at the point of use in `_recompute`, and the
    page still has to be able to say WHICH finding it is. Both walks call `_n_problem`, the single
    implementation of the comparison, so this one cannot drift from the one that withholds the verdict.
    That -- not whether two fields are read twice -- is the distinction this module's scheme is about.

    Why the page needs it: without it, a 29-seed run whose `n` was forged to 30 renders only the generic
    "stored verdict(s) ... disagree with an independent recomputation" warning, which is also exactly
    what an HONEST below-minimum configuration gets. Round 4's finding about the weaker-than-protocol
    paragraph was that an honest run got the accusation and a forgery got the acquittal; a cross-check
    that fires without naming the two contradicting numbers repeats the same mistake one lane over."""
    if measured_n is None:
        return [NO_SECOND_SOURCE_MSG]
    try:
        hyps = (joint.h1, joint.h2, joint.h3)
    except Exception:  # noqa: BLE001 - a malformed result is refused before this is reached
        return []
    out = []
    for h in hyps:
        try:
            comps = (*h.components, *(tuple(getattr(h, "converged_components", ()) or ())))
        except Exception:  # noqa: BLE001
            continue
        for c in comps:
            pair = getattr(c, "pair", None)
            n, mn = _count(getattr(pair, "n", None)), _count(getattr(c, "min_n", None))
            if n is None or mn is None:
                continue        # not a count at all: the kind functions alarm on that, with their words
            p = _n_problem(pair, n, mn, measured_n)
            if p is not None:
                out.append(f"{h.hid}/{_visible(str(getattr(c, 'metric', '?')))[:40]}: {p}")
    return out


def _interval_sources_disagree(joint: Any, series: Mapping) -> list:
    """Components whose stored `mean`/`t_lo`/`t_hi` disagree with the per-seed series the result carries.

    THE PROSE SIBLING OF `_interval_problem`, for the same reason `_n_sources_disagree` is `_n_problem`'s
    and on the same terms: the GUARD lives at the point of use in `_recompute`, and the page still has to
    be able to say WHICH finding it is rather than emit the generic "stored verdict disagrees" warning
    that an honest below-minimum CONFIGURATION also gets. Both walks call `_interval_problem`, the single
    implementation, so this one cannot drift from the one that withholds the verdict.

    It reports a problem only for a pair whose numbers are otherwise ADMITTED (`_admitted` is not None).
    A pair with a forged non-float bound is not a cross-source contradiction -- it is an ill-typed field,
    which the kind functions alarm on in their own words -- so saying both would name the wrong finding;
    that is the same division `_n_sources_disagree` makes with its `n is None or mn is None` guard."""
    try:
        hyps = (joint.h1, joint.h2, joint.h3)
    except Exception:  # noqa: BLE001 - a malformed result is refused before this is reached
        return []
    out = []
    for h in hyps:
        try:
            comps = (*h.components, *(tuple(getattr(h, "converged_components", ()) or ())))
        except Exception:  # noqa: BLE001
            continue
        for c in comps:
            nums = _admitted(getattr(c, "pair", None), "IntervalPair")
            if nums is None:
                continue        # ill-typed, not contradicted: the kind functions say so in their words
            p = _interval_problem(nums, _series_of(series, getattr(c, "metric", _MISSING)))
            if p is not None:
                out.append(f"{h.hid}/{_visible(str(getattr(c, 'metric', '?')))[:40]}: {p}")
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

    MORE LOAD-BEARING THAN "no legitimate path omits a gate" SUGGESTS -- do not "simplify" it away on the
    grounds that `JointResult` already validates the names. `JointResult.__post_init__` filters
    `isinstance(g, GateResult)` before comparing names, so a gate list of the 7 real gates PLUS a
    duck-typed extra object CONSTRUCTS FINE upstream: the extra object is invisible to that check. This
    function does not filter, so it sees 8 names and fails. An injected gate is also exactly what
    `benchmark.carries_exemption` reads `exempt` off (it reads any object in the list), so the injection
    route is live, not hypothetical. The duck-typed-extra case is caught HERE and nowhere else.

    RESIDUAL LIMIT: this checks names only. A gate's `passed` flag is producer-asserted, so flipping a
    failed gate to passed IN PLACE keeps the name set intact and is not detectable here; it is caught only
    where the hypothesis-level recomputation disagrees with the stored verdict."""
    try:
        return sorted(str(g.name) for g in gates) == sorted(bm.GATE_SCOPES)
    except Exception:  # noqa: BLE001 - cannot establish the expected set: not ok
        return False


def _eff_hypothesis(h: Any, gates: tuple, contract_bad: bool, margins: Any, measured_n: Optional[int],
                    series: Mapping) -> tuple:
    """(displayed verdict, mismatch). Decisive only if the stored hypothesis verdict equals an independent
    recomputation from recomputed component verdicts, scope-aware gates, and (H3) converged components."""
    if not _component_sets_ok(h):
        return Verdict.INCONCLUSIVE, True
    rc = [_recompute(c, margins, measured_n, series) for c in h.components]
    mismatch = any(_eff_component(c, False, False, margins, measured_n, series)[1] for c in h.components)
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
        if sup_block or not conv or not all(_recompute(c, margins, measured_n, series) is Verdict.SUPPORTED
                                            for c in conv):
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
    # THE TWO SECOND SOURCES, read ONCE for the whole card and handed to every recomputation. Not
    # re-derived per component: `n_attempted`/`n_failed` are admitted here and in `_int_or_unk`'s display
    # cell, by the same kind function, and nowhere else; the per-seed series is rebuilt once per metric.
    measured_n = _measured_seeds(joint)
    series = _measured_series(joint)
    mismatch = []
    eff = {}
    rows = ""
    for h in (joint.h1, joint.h2, joint.h3):
        ev, mm = _eff_hypothesis(h, gates, bad, joint.margins, measured_n, series)
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
                ecv, cmm = _eff_component(c, any_failed, bad, joint.margins, measured_n, series)
                if cmm and h.hid not in mismatch:
                    mismatch.append(h.hid)
                rows += (
                    f"<tr><td>{_e(h.hid)} {_e(_HNAMES[h.hid])}{_e(suffix)}</td><td>{_e(_visible(str(c.metric)))}</td>"
                    # margin: kind "num", the SAME admission `_declared`/`_recompute` now use. These two
                    # disagreed at HEAD (display checked, verdict coerced): G2.
                    f"<td>{_e(_visible(str(c.direction)))} {_kind_text(c.margin, 'margin', 'num')}</td>"
                    f"<td>{_metric_cell(pair.mean)}</td><td>{_interval(pair.boot_lo, pair.boot_hi)}</td>"
                    f"<td>{_interval(pair.t_lo, pair.t_hi)}</td>"
                    # n: kind "count", the SAME admission `_pair_numbers_ok` now uses. These two
                    # disagreed at HEAD (display checked, the min-n floor took `nan` as a number): G1.
                    f"<td>{_kind_text(pair.n, 'n', 'count')}</td>"
                    f"<td>{_float_cell(pair.level, 'level')}</td>"
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
    # Both numbers are read out of the scorer at render time and both are figures on the page, so both go
    # through the scheme. Measured at HEAD, where only the `except` guarded them: `bonferroni_level`
    # patched to return `nan`/`inf` printed "Bonferroni level nan"/"inf", patched to return the STRING
    # "0.9875" printed a coerced `0.9875` as if it were a number (`_num` = `repr(float(x))`), and
    # `N_PRIMARY` patched to `nan`/`True` printed "nan primary intervals"/"True primary intervals".
    try:
        m, lvl = _count(bm.N_PRIMARY), _finite_float(bm.bonferroni_level())
    except Exception:  # noqa: BLE001
        m = lvl = None
    fam = (f"{m} primary intervals, Bonferroni level {_num(lvl)} (read from the scorer)"
           if m is not None and lvl is not None else "family size/level UNKNOWN")
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
    n_bad = _n_sources_disagree(joint, measured_n)
    if n_bad:
        # WHAT THIS PARAGRAPH ASSERTS, AND WHAT IT DOES NOT (the round-4 lesson about the sibling
        # paragraph below, applied before it can be made again). It states the two contradicting numbers
        # and that the affected verdicts are withheld -- both observable right here. It does NOT assert
        # tampering: measured over 12 legitimate study shapes the scorer emits no such contradiction, so
        # an honest non-compliant CONFIGURATION is not an explanation the way it is for `min_n`; but a
        # change in how the scorer counts seeds is, and this page cannot tell the two apart.
        body += ('<p class="warn">SAMPLE SIZE CONTRADICTED BY THIS RESULT\'S OWN SECOND SOURCE: '
                 + _e("; ".join(n_bad)) + '. Every verdict derived from a contradicted interval is '
                 'withheld (INCONCLUSIVE shown): protocol 6.1 produces no verdict below the minimum n, '
                 'so the stored sample size decides whether a run earned a verdict at all, and this '
                 'result states it twice with two different values. WHETHER A FIELD WAS EDITED AFTER THE '
                 'FACT OR THE SCORER NOW COUNTS SEEDS DIFFERENTLY CANNOT BE DETERMINED FROM THIS RESULT, '
                 'and this page asserts neither.</p>')
    i_bad = _interval_sources_disagree(joint, series)
    if i_bad:
        # SAME DISCIPLINE AS THE PARAGRAPH ABOVE, and for the same reason. It names the two contradicting
        # numbers and says what was withheld -- both observable right here -- and asserts NOTHING about
        # why. `t_lo`/`t_hi` carry protocol 6.3's bootstrap/t disagreement rule, so a contradicted
        # t-interval is not a cosmetic figure; `mean` reaches no verdict and is still withheld, because
        # an interval that disagrees with the data behind it is not an interval this page can read.
        body += ('<p class="warn">INTERVAL CONTRADICTED BY THIS RESULT\'S OWN PER-SEED DATA: '
                 + _e("; ".join(i_bad)) + '. Every verdict derived from a contradicted interval is '
                 'withheld (INCONCLUSIVE shown): protocol 6.3 makes the t-interval verdict-bearing '
                 'through the bootstrap/t disagreement rule, and this result states the same interval '
                 'twice -- once as a stored bound and once as the per-seed values it was computed from -- '
                 'with two different answers. WHETHER A FIELD WAS EDITED AFTER THE FACT OR THE SCORER '
                 'NOW SUMMARISES A SERIES DIFFERENTLY CANNOT BE DETERMINED FROM THIS RESULT, and this '
                 'page asserts neither. The two BOOTSTRAP bounds are not cross-checked at all and are a '
                 'stated residual: their resample needs n_boot and the study base seed, and JointResult '
                 'carries neither.</p>')
    weaker = _weaker_than_protocol(joint)
    if weaker:
        # LABELLING ONLY -- which in this kit is the product. The GUARD is sound and is not touched here:
        # the one-sided floor in `_recompute` means a weaker declared parameter can never buy a decisive
        # verdict, and nothing is laundered. What was wrong was the prose, which asserted two things
        # unconditionally: (1) "so any decisive verdict is withheld" and (2) "this is a configuration
        # statement, NOT evidence of tampering".
        # MEASURED at HEAD: on a `min_n` 30->1 forgery over a real n=30 run, and on a `width_tol`
        # 0.25->1e9 forgery, BOTH sentences were false as rendered -- no verdict was withheld
        # (JOINT_SUPPORTED was displayed) and the field HAD been edited -- while an HONEST
        # `BenchmarkConfig(min_seeds=10)` run over 10 seeds got the same exculpation *plus* the generic
        # "stored verdict disagrees" warning. The honest run got the accusation; the forgery got the
        # acquittal.
        # (1) is now conditional on a verdict having actually been withheld, which is observable right
        # here (`mismatch` / `bad` are exactly the verdicts the page is refusing to show).
        # (2) IS GONE IN BOTH DIRECTIONS, and is deliberately not replaced by the opposite claim. A weak
        # declared value is produced both by an honest non-compliant configuration and by a forged field,
        # and the two are not distinguishable from the result: `BenchmarkConfig(min_seeds=10)` with 30
        # collected seeds is honest and renders identically to `min_n` forged to 1 on an n=30 run
        # (measured), and the laundering fixture that forges `min_n` on a genuine n=29 run lands in the
        # withheld branch, so neither branch is clean. The page states the undecidability and asserts
        # neither side -- the one thing it can say that is true of every case above.
        withheld = bool(mismatch) or bad
        body += ('<p class="warn">PROTOCOL PARAMETERS WEAKER THAN THE PROTOCOL DECLARES: '
                 + _e("; ".join(weaker)) + '. The recomputation used the protocol values instead. '
                 + ('The stored verdicts named above are therefore the ones being withheld, and the '
                    'disagreement warning above is explained by this: it does not by itself mean a '
                    'field was edited. ' if withheld else
                    'That changed nothing displayed here: every verdict shown above is one the '
                    'recomputation reproduced AT THE PROTOCOL VALUES, so no decisive verdict was '
                    'withheld on account of these parameters. ')
                 + 'Protocol 6.1 produces no verdict below the minimum n and labels such a run '
                   'exploratory and non-compliant. WHETHER THIS IS AN HONEST NON-COMPLIANT '
                   'CONFIGURATION OR A FIELD EDITED AFTER THE FACT CANNOT BE DETERMINED FROM THIS '
                   'RESULT, and this page asserts neither: JointResult carries only an opaque '
                   'config_hash and not its BenchmarkConfig, so the two are indistinguishable here.</p>')
    body += ('<p class="caveat">Verdicts are shown only when stored and recomputed values agree. They describe a '
             'scorer run on synthetic toy data and say nothing about any real model. Margins are arbitrary '
             'protocol parameters.</p>')
    return _panel("Benchmark scorecard", EvidenceClass.TOY_RESULT, body, extra=(EvidenceClass.NOT_VALIDATED,))


def _int_or_unk(v: Any) -> str:
    """`JointResult.n_attempted` / `n_failed`. Kind "count", and in `STORED_NUMBERS`.

    THIS DOCSTRING USED TO SAY these were "the only two entries there that reach a FIGURE and no verdict
    (nothing recomputes from them), so they are the one place where UNKNOWN without an alarm is the
    correct outcome rather than a gap". That was accurate about HEAD and it was the round-5 defect:
    their difference IS the study's measured-seed count, the second source every `pair.n` is now checked
    against (`_measured_seeds`), so they reach every verdict on the card and UNKNOWN here now comes with
    an alarm. This cell is the DISPLAY consumer of the same two numbers; it shares the kind function with
    the verdict consumer, which is what the scheme requires and what round 5 would have failed without.

    Stays bare text and stays sign-free: it sits inside the sentence "Attempted N, failed N", and a
    negative count is a real datum to print, not a non-number (see `_count`). Sign is still not
    constrained in the kind function -- `_measured_seeds` refuses a negative pair separately, by way of
    the `seed_scores` equality, which no negative count can satisfy."""
    return _kind_text(v, "not recorded", "count")


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
        # kind "num", the SAME admission `_declared` now uses -- and the reason the absent case is kept
        # separate is only the wording, not a second check.
        cell = _unknown(f"{k} is absent from the Margins object; NOT zero") if v is _MISSING else \
            _kind_cell(v, f"{k} is not a finite number; unmeasured, NOT zero", "num")
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
