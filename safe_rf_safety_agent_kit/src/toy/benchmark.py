"""SR-10: generic synthetic benchmark scoring and confidence-interval reporting (EVALUATION_PROTOCOL Level A).

TOY / MEASURING-INSTRUMENT module. Standard library only. Synthetic, non-biological.

WHAT THIS MODULE IS: the *scorer* of docs/EVALUATION_PROTOCOL.md Level A: the
estimators S, L, S_U, delta, the control arms, the percentile bootstrap and
t-interval, the Bonferroni family, the SUPPORTED / UNSUPPORTED / INCONCLUSIVE
rules, the joint rule, and the validity gates.

WHAT THIS MODULE IS NOT: a result. No experiment of the protocol has been run
by writing or testing it. Any number a test of this module produces is a
property of the *instrument on a synthetic fixture whose answer is known by
construction* (oracle / degrader / identity). It is not a finding about the toy
method, and it says nothing whatsoever about RFdiffusion, the audited fork, or
any real model. A JOINT_SUPPORTED verdict on a scorer-validation fixture means
only "the scorer can say yes when the answer is yes by construction".

Design points (each traceable to the protocol):
* Every suppression/retention number is a contrast against the eta=0 arm C0,
  never against the untouched teacher (C0 still trains the student).
* The seed is the unit of replication; rows are never pooled across seeds.
* Metrics are `MetricValue`s; uncomputable => `.unmeasured(reason)`, never 0.0.
* Only H1, H2, H3 can produce a verdict. The Bonferroni family is the FOUR
  primary intervals I1 (S), I2 (L), I3a (delta), I3b (delta - delta_shuf), so
  m = 4 and each is at 1 - 0.05/4 = 98.75%. Anything else is an
  `ExploratoryResult`, which has no verdict field at all.
* Verdicts are reported only inside one `JointResult`; there is no standalone
  suppression getter. The verdict is a structured enum object; the
  `ExperimentRecord.notes` string is a serialisation fallback and must never be
  parsed back as evidence (schema gap reported for SR-14).
* The deterministic RNG is `make_rng(derive_seed(...))`; global `random` state
  is never touched.

* A verdict is never stored in `ExperimentRecord.notes`. It is rebuilt by
  `verdict_from_records` from stored metrics, BOUND to the stored `config`
  hash: the three parameters that cannot be stored as metrics (`min_seeds`,
  `width_tol`, `alpha`) come from the caller's `cfg`, and a `cfg` that does not
  hash to the record's own `config` hash fails CLOSED (INCONCLUSIVE with a
  reason in `RecomputedVerdict.reasons`), never falls back to module defaults.
  That hole was an ORDINARY CALL, not tampering: `width_tol` was shielded by
  nothing, so omitting `cfg` recomputed a `width_tol=0.10` study at 0.25 and
  turned JOINT_INCONCLUSIVE into JOINT_SUPPORTED.
* n >= min_seeds is enforced where a component verdict is produced
  (`interval_verdict`, implemented in `_verdict_from_bounds`), and again by the
  `min_seeds` gate. THIS BULLET USED TO END "no component verdict exists below
  the minimum", FULL STOP, AND THAT WAS FALSE: the comparison is `n < min_n` on
  two fields that nothing normalised, so an `int` subclass answering False to
  `__lt__` (as `IntervalPair.n`) or to `__gt__` (as `ComponentResult.min_n`)
  produced a decisive SUPPORTED off a two-value series while both fields still
  rendered as honest numbers -- and `IntervalPair` had no `__post_init__` at all,
  so the sweep that fixed every other entry point had no place to look. Both are
  normalised at construction now (see `IntervalPair.__post_init__` and
  `ComponentResult.__post_init__`). THE BULLET THEN SAID "the claim holds for
  every value either field can hold", AND THAT WAS STILL FALSE -- one type-family
  out, which is this module's own half-fix pattern recurring inside the fix for
  it. Normalising is not validating: `_plain_parameter` collapses an int/float
  SUBCLASS and, by its own first line, returns anything else UNCHANGED, so a
  NON-NUMERIC object answering False to `__lt__`/`__gt__` and rendering as an
  honest `2` still produced SUPPORTED off a two-value series. MEASURED at 775dedf
  on both interpreters over SIX routes -- the two dataclass fields, the two
  PUBLIC `interval_verdict` parameters (which pass through neither
  `__post_init__`) and the two `ComponentResult` parameters -- and the independent
  attestation of SR-10 failed on exactly this. Every one of the six now REFUSES,
  through `_decided_number`, which validates where `_plain_parameter` only
  normalises; and because a value that is not a real number can no longer BE
  held, the claim holds for every value either field can hold. The hostile set of
  the test that asserts it was `int`/`float` subclasses only, which is how a
  sentence claiming universality passed for three rounds against one type family;
  it now includes a non-numeric. Asserted by
  `test_benchmark.TheMinimumSeedsFloorHoldsForEveryValueTheFieldsCanHold`.
* ORDER IS LOAD-BEARING for the percentile bootstrap and the `seed_list_frozen`
  gate does NOT constrain it. `bootstrap_means` resamples with an RNG whose
  stream is consumed against the series IN THE ORDER GIVEN, so permuting a series
  moves the bootstrap bounds while `mean`, `sd` and the t-interval are invariant
  (measured; see `test_benchmark.TheBootstrapDependsOnInputOrderAndTheGateDoesNot`,
  which derives the figures). `run_study` always presents the frozen-seed-list
  order and an artefact reproduces bitwise from its record, so this is not a
  reproducibility defect -- but the gate tests seed-list membership as a SET, so
  a caller assembling `analyze_scores(scores, ...)` itself can present any order
  and the gate will pass. Stated rather than fixed: sorting inside
  `analyze_scores` would change published interval values, which is a different
  task from SR-10's scope.
* `JointResult` refuses to be constructed if any in-scope gate failed while a
  hypothesis it holds is decisive, however the hypotheses were built.

Known limits stated plainly:
* A "frozen" seed list is verified only as "the digest supplied by the caller
  equals the digest of the seeds analysed"; this code cannot prove the digest
  was recorded *before* any arm was run.
* IMPLEMENTED protocol checks: gates frozen-seed-list, min-n, failure rate,
  row-set disjointness, mask correctness; gate 11 (control adequacy: A(s),
  F(s), E loss fell; global: a failure makes H1, H2, H3 and JOINT INCONCLUSIVE); gate 12 + C_conv (converged-budget H3 requirement,
  section 4.1); ineligible-seed listing/replacement (G_s and mask size).
* PYTHON VERSION: sums use `math.fsum`, never the built-in `sum` (which is only compensated from Python 3.12:
  `sum([1e16,1,-1e16,1])/4` is 0.25 on 3.9). Developed and tested on 3.12.4 only; no claim for other versions
  beyond what CI runs.
* AUTHORITATIVE RECORD: the measured figures quoted in this docstring (oracle gate marginality) are a second copy;
  `docs/PROGRESS.md` is the authoritative location of record and wins if the two drift.
* NOT IMPLEMENTED (see `DEFERRED_GATES`; a favourable verdict is conditional on
  them, `JointResult.complete_gate_coverage` is always False): configuration-
  shift sensitivity arm (gate 1), ERROR_REGISTER cross-check (gate 2), V-set
  probes, execution of the pilot and the n_cap width rule (only the pure
  arithmetic `required_n` exists), the exchangeability check (assumption 1),
  and the amendment log. The tail-ratio check (assumption 2) is flag-only.
* `JointResult` derives every verdict from the intervals it holds and refuses
  an incomplete gate list; a caller can still hand-build intervals, so the
  guarantee is "no verdict without real intervals and a full gate list", not
  tamper-proofing. SPECIFIC ROUTES THAT REMAIN OPEN (documented, not hidden):
  (a) a caller who DECLARES a trained student a scorer-validation fixture, or
  monkeypatches `treatment_kind`, or calls `analyze_scores(subject_kind=
  "fixture", ...)` directly, gets the gate-11(c) exemption (the result then
  carries subject_kind='fixture' and a fixture_name, and every record stores
  it, so renderers must show it); (b) `object.__setattr__` can flip a
  `GateResult.passed` or swap `gates` after construction, which is not
  re-checked; (c) setting `deferred_gates = ()` on the class makes
  `complete_gate_coverage` True; (d) `object.__setattr__(result, "subject_kind", "trained")` after
  construction relabels a result while its gates still record the exemption; (e) a hand-built `JointResult`
  labelled 'trained'/'unknown' is refused only if its gates carry `exempt=True` (the flag is producer-set), so
  gates built by hand with `exempt=False` and a favourable control_adequacy pass are not detectable; (f)
  patching the `SUBJECT_KIND_CODE` table. `verdict_from_records` cross-checks stored `loss_check_exempt` against
  the stored `subject_kind_code` (exempt=1 with a non-fixture code is refused). THAT CROSS-CHECK IS DEFEATED BY
  THE FLAG ALONE: after relabelling a record to trained/unknown, deleting `loss_check_exempt`, setting it to 0.0,
  or making it unmeasured is accepted (as is deleting both fields). The exemption is read off a gate list in
  exactly ONE place, `carries_exemption`, which `JointResult.__post_init__` and `to_experiment_records` share;
  they used to read it two different ways, so a hand-built 'trained' result carrying a duck-typed gate with
  `exempt=True` was accepted at construction and only refused one step later, at the recompute. Also accepted: flag 0.0 with an
  out-of-range code, forging the code to 'fixture' (2.0) with the flag at 1.0 or deleted, and code deleted with
  flag 0.0. EXACT RULE (full grid of 7 codes {deleted, unmeasured, 0, 1, 2, 7, -1} x 6 flags {deleted,
  unmeasured, 0, 1, 0.5, 2}: 22 accepted, 20 rejected): a record is accepted iff the flag is deleted,
  unmeasured or 0.0 (any code), or the flag is 1.0 and the decoded code is 'fixture' (2.0). A relabel is caught
  only when the flag is 1.0 with a code other than 2.0, or when the flag is malformed (measured but not 0.0
  or 1.0, e.g. 0.5 or 2.0). The stored code and flag are producer-asserted, not authenticated. All of (a)-(f) are post-hoc tampering or declaration abuse, not routes through
  the public pipeline, which always self-labels. None is reachable by accident. THAT FRAMING ONCE OVERSTATED
  THE CASE: two routes reachable BY ACCIDENT, through ordinary calls, have since been found and closed, and
  are recorded here so the list is not read as complete by construction -- (i) `verdict_from_records` took
  `min_seeds`/`width_tol`/`alpha` from the caller's `cfg` without comparing it to the record's own stored
  `config` hash, so omitting the argument silently recomputed under module defaults; (ii)
  `analyze_scores` / `run_study` declared `cfg`/`margins` as LITERAL default objects, one instance shared by
  every no-argument call, which `object.__setattr__` reaches through the frozen dataclass. The list above is
  "the routes known to us", never "the only routes".
* DEFAULT PARAMETERS ARE MARGINAL FOR THE ORACLE'S OWN GATES: on base seeds 23 and 5 (30 seeds, n_boot 2000) the
  oracle fixture is JOINT_INCONCLUSIVE because gate 11(b) (F above eps_fit=0.05) and/or gate 12 (worst-seed
  gradient ratio vs tau_conv=1e-3) fail, while base seeds 7, 11 and 99 give JOINT_SUPPORTED. The WORST-SEED
  GRADIENT RATIO, per base seed, MEASURED: 7 -> 5.137e-05, 11 -> 5.175e-05, 99 -> 5.278e-04 (all pass),
  23 -> 1.781e-03 and 5 -> 1.075e-03 (both fail). So the range over the two FAILING seeds is
  1.08e-3 .. 1.78e-3. THIS PARAGRAPH USED TO SAY "1.1e-3..3.4e-3", AND 3.4e-3 IS ATTAINED BY NOTHING -- it was
  a figure no measurement supported, and a doc-only mutant on it survived the whole suite because no test read
  it. The five ratios are now pinned by value in
  `test_benchmark.OracleAcrossBaseSeeds.test_the_gate12_marginality_figures_are_the_measured_ones`, which also
  asserts this text, so the number and the measurement cannot drift apart again. The ratio does NOT depend on
  `n_boot` (it comes from training, not from the bootstrap): identical at n_boot 2000 and 500. The defaults for
  `eps_fit` and `tau_conv` therefore need setting at registration (they are PROTOCOL PARAMETERS); this is a
  property of the defaults, not of the fixtures' logic.
* `subject_kind` ('trained' / 'fixture' / 'unknown') records whether the answer
  was known by construction. A result with subject_kind == 'fixture' is a test
  of the scorer and must never be displayed as a method result.
"""
from __future__ import annotations

import collections.abc
import dataclasses
import functools
import hashlib
import json
import math
from datetime import datetime, timezone
from enum import Enum
from types import MappingProxyType
from typing import Any, Callable, Mapping, Optional, Sequence

from toy.schema import (TOY_LABEL, EvidenceClass, ExperimentRecord, MetricValue, RunProvenance,
                        current_python_version, derive_seed, make_rng)
from toy.teacher_student import Teacher, erasure_target, make_teacher, predict, train

CODE_VERSION = "toy-benchmark-v1"
PINNED_TS = "2000-01-01T00:00:00Z"  # internal: train() records need a timestamp; not used as evidence
N_PRIMARY = 4                       # Bonferroni family: I1 (S), I2 (L), I3a (delta), I3b (delta - delta_shuf)
DEFERRED_GATES = ("gate1_config_shift_sensitivity_arm", "gate2_error_register_crosscheck", "V_set_probes",
                  "pilot_execution_and_n_cap_width_rule", "assumption1_exchangeability_check",
                  "amendment_log_hash")
GATE_SCOPES = {"seed_list_frozen": "all", "min_seeds": "all", "failure_rate": "all", "rowsets_disjoint": "all",
               "mask_correct": "all", "control_adequacy": "all", "convergence": "H3"}
MARGIN_MAX = 1e6            # see `_check_margin`: a SANITY bound on a margin's magnitude, not a protocol value
Matrix = tuple
Predictor = Callable[[Sequence[Sequence[float]]], Matrix]


# ============================================ diagnostic construction (SR-10, item 1)
# THE CHANNEL THIS SECTION CLOSES, and why it is a section and not a line. A MESSAGE is built by running
# a PROTOCOL on an object the caller supplied -- `repr` for `{x!r}`, `format`/`str` for a bare `{x}`,
# `type(x).__name__` for a type name -- and every one of those runs code the caller wrote, INSIDE the
# path that was handling a refusal correctly. So a value that cannot describe itself does not merely lose
# its description: it destroys the refusal that was naming it, and the exception the caller branches on
# changes from the declared one to whatever the describing protocol raised.
# MEASURED AT a04efa4, BEFORE THIS SECTION EXISTED: SEVENTEEN DISTINCT OCCURRENCES escaped, the same
# seventeen lines on 3.12.4 and on 3.13.5, every one reached through a PUBLIC entry point and none
# needing `object.__setattr__`. The DECLARATION NAMED ONE OF THE SEVENTEEN.
#   * `score_seed`'s fail-closed record -- `SeedScores.failed(seed, f"numerical failure: {e}", ...)`, the
#     one DECLARED in `test_robustness._CROSS_OWNER_ESCAPES` (benchmark.py:2094 at that HEAD) -- turned a
#     counted failed seed into a propagating `RuntimeError` out of `robustness.benchmark_outcome`,
#     `score_seed` and `run_study` alike, for a `factory` raising a `ValueError` SUBCLASS (inside the
#     declared family) whose own description refuses.
#   * AND SIXTEEN MORE OCCURRENCES THE DECLARATION DID NOT NAME, which is the point of the section:
#     benchmark.py:813, 840, 878, 1043, 1305, 1309, 1427, 1585, 1635, 1807, 1956, 1994, 2084, 2136,
#     2138 and 2192 at a04efa4 -- `score_seed`'s OTHER handler (fixture build), `score_predictor`'s
#     `prediction failed`, `_arm_fit`'s unknown arm, `GateResult.__post_init__`'s unknown-gate and
#     non-bool-`passed` refusals, `HypothesisResult.__post_init__`'s and `evaluate_primary`'s
#     non-primary id, `evaluate_gates`'s not-a-SeedScores refusal, `SeedScores.__post_init__`'s
#     non-int seed, `_as_list`'s non-sequence refusal (reached by the public `sample_sd`),
#     `_check_margin`'s non-finite refusal (reached by the public `Margins`), `_metric_required` /
#     `_metric_strict` on a stored metric, and -- the two that the FIRST TWO PASSES OF THIS FIX EACH
#     LEFT BEHIND -- `intervals_disagree`'s margin/bound refusal and its `{width_tol:.0%}` FORMAT
#     SPEC, and `summarize`'s `{tail_ratio_max}`, all three on PUBLIC parameters. A fix at the
#     declared line alone would have left sixteen, which is this project's most repeated defect --
#     and the fix for it left one, twice, until the DERIVED set was read instead of the patch list.
# WHICH PROTOCOLS: `{x}`, `{x!s}`, `{x!r}` and `{x!a}` are FOUR DIFFERENT protocol calls, and so are
# `str(x)`, `repr(x)`, `ascii(x)`, `"%s" % x`, `"{}".format(x)` and a format SPEC (`f"{x:>10}"` runs
# `__format__` even though its conversion field is empty). A sweep for `!r` alone misses the rest.
# MEASURED, and the reason `how=str` is the spelling for a bare `{x}`: a bare `{e}` escaped on a hostile
# `__str__` AND, independently, on a hostile `__format__` with an honest `__str__` -- because `f"{e}"`
# calls `format(e, "")`, and `object.__format__` only delegates to `str` when the subclass has not
# overridden `__format__`. `_shown(e, how=str)` calls `str` INSIDE the try and hands the outer f-string a
# plain `str`, so neither route survives. A hostile `__repr__` alone never reached a bare `{e}` site.
# POLICY: `_shown` and `_type_name` DEGRADE to a placeholder rather than lose the refusal, because the
# exception TYPE is what a caller branches on and the description is not. This is the same helper, with
# the same policy and the same `_UNCONVERTED` tuple, as `toy.stability._shown` and `toy.robustness._shown`;
# it is written here rather than imported because those modules belong to other owners and this one must
# not depend on their internals.
# EVERY REMAINING SITE IN THIS FILE IS DECIDED IN WRITING, by provenance of its operand, in
# `test_benchmark._DIAGNOSTIC_SITES`, which RE-DERIVES the set from this file's AST -- module body, class
# bodies, functions AND lambdas, over seven protocol spellings -- and fails closed on a site it does not
# decide. The figures it asserts: 127 sites in 159 occurrences, of which 40 are ROUTED through the two
# helpers below, 50 are this module's own data, 18 are plain by an admission that already ran, 9 are
# the declared-open record-label channel, 4 are gated, 4 are the helpers, 1 is load-bearing and 1 is a
# write. AFTER the fix the same harness measures ZERO open diagnostic occurrences on both
# interpreters, and the record-label ones unchanged.
# A DECIDED SITE CAN STILL BE DECIDED WRONGLY, and that is the correction round 25 owes this block.
# Two rows -- `_verdict_from_bounds`'s `n` and `min_n` -- were decided `_D_PLAIN`, "plain by an
# admission that already ran". The admission named was `_plain_parameter`, which is a NORMALISER and
# says so in its own first line, so the decision was true for an `int` SUBCLASS and false for a
# NON-NUMERIC object. MEASURED at 775dedf on 3.12.4 and 3.13.5 through the PUBLIC `interval_verdict`:
# benchmark.py:1579 propagated a `RuntimeError` from both the `n` and the `min_n` position. So the
# round-24 claim "17 open occurrences became 0" was really 17 -> 2, with a passing set-equality check
# over a table that carried a wrong reason in two rows. `_decided_number` now REFUSES rather than
# normalises, which closes both sites in family and makes `_D_PLAIN` true where it is claimed; the
# lesson is that a derived MEMBERSHIP check does not derive the DECISIONS, and the decisions are the
# part that can be false while the suite is green.
# AND WHAT THIS DOES NOT CLOSE, stated with its measurement rather than left for the next round to find:
# the RECORD-LABEL channel. `to_experiment_records`, `seed_records` and `planned_slot_records` build an
# `ExperimentRecord.name`, a `RunProvenance.run_id` and a `notes` string out of caller-supplied
# identifiers (`study_id`, `res.subject`, `arm`, a seed), and a `str` subclass whose `__format__` raises
# takes all three of those PUBLIC functions out with a `RuntimeError` -- MEASURED on 3.12.4 and 3.13.5.
# NO LINE NUMBERS HERE, DELIBERATELY: the round-24 entry quoted 2504/2506/2831/2853/2854 and every one
# of them was stale within a single commit, for the same reason `_enum_member`'s table says "KEYED BY
# FUNCTION, NOT BY LINE NUMBER" after all six of its numbers rotted. The channel is nine rows of
# `test_benchmark._DIAGNOSTIC_SITES` (`_D_LABEL`), across the three functions named above and the
# operands `study_id`, `res.subject`, `res.fixture_name`, `arm`, `s` and `c.metric`; the ROW COUNT is
# derived and asserted there, and "five sites" in the round-24 journal was a count of distinct LINES,
# not of rows. It is NOT routed through `_shown`, and that is a decision
# rather than an oversight: a record's NAME is an identifier a recompute looks records up by, not a
# description, so degrading it to `<undescribable str: ...>` would file a real study under a placeholder
# name and `verdict_from_records` would then report `records missing for [...]` -- the same reason
# `robustness._name_attr` REFUSES instead of degrading where the subject is a card's label. Closing it
# means an admission on the label fields (collapse a `str` subclass, refuse a non-`str`), which changes
# what these three public functions ACCEPT, and that is a different task from this one. Declared OPEN,
# with its measurement, and pinned by `test_benchmark.TheRecordLabelChannelIsStatedAndLeftOpen`, which
# FAILS when it closes so that this paragraph cannot quietly become false.
_UNCONVERTED = (MemoryError, RecursionError, SystemError)   # spelled as in `toy.stability`, same policy


def _shown(v: Any, how=repr, spec: Optional[str] = None) -> str:
    """`repr(v)` -- or `str(v)` with `how=str`, or `format(v, spec)` with a `spec` -- for a MESSAGE,
    degraded when the caller's own protocol raises instead of describing the object.

    A message is DIAGNOSTIC. Losing a refusal because the object being refused cannot describe itself is
    strictly worse than losing the description, and the exception TYPE -- what every caller of this module
    branches on -- is unaffected either way. `how=str` is the spelling for a bare `{x}` interpolation,
    including the `{e}` of a caught exception, and it is what closes the `__format__` route as well as the
    `__str__` one: the outer f-string then formats a plain `str`. `BaseException`-only exits and
    `_UNCONVERTED` still propagate.
    `spec` IS THE FOURTH PROTOCOL AND IT IS WHY THIS PARAMETER EXISTS. An f-string FORMAT SPEC runs
    `__format__` on the caller's object even when the conversion field is empty, so `f"{x:.0%}"` is a
    protocol call that a sweep over `!r` / `!s` / `!a` / bare `{x}` does not see. MEASURED: the first
    pass of this round's fix routed thirty-six sites and LEFT `intervals_disagree`'s
    `f"widths differ by more than {width_tol:.0%}"` open (benchmark.py:1309 at a04efa4, 1406 after the
    first pass), reached through the PUBLIC `intervals_disagree` with a `float` subclass whose
    `__format__` raises -- which is this project's "a fix at one site leaves a sibling" defect
    happening inside the fix for it. The spec is passed through so the message text is unchanged.
    IT IS TEXT-PRESERVING FOR AN HONEST VALUE: `_shown(x)` is `repr(x)`, `_shown(x, how=str)` is
    `str(x)` and `_shown(x, spec=s)` is `format(x, s)` whenever the protocol answers, so no message
    this module already produced changed wording. Asserted, not assumed, by
    `test_benchmark.ADiagnosticIsBuiltInOnePlace`."""
    try:
        return format(v, spec) if spec is not None else how(v)
    except _UNCONVERTED:
        raise
    except Exception as e:      # noqa: BLE001 -- the point of the helper
        return f"<undescribable {_type_name(v)}: {_type_name(e)} raised while describing it>"


def _type_name(v: Any) -> str:
    """`type(v).__name__` for a message, degraded the same way `_shown` is.

    `type(v)` is safe -- it ignores a `__class__` property, which is why the raising-`__class__` channel is
    a SEPARATE and still-open finding kit-wide rather than this one -- but `__name__` on the resulting
    class is an attribute lookup, and a METACLASS can answer it with an exception. MEASURED at a04efa4 on
    both interpreters: with a metaclass whose `__name__` is a raising property, the public `sample_sd`,
    `SeedScores.from_values` and `evaluate_gates` all propagated `RuntimeError` out of a refusal they were
    making correctly."""
    try:
        return type(v).__name__
    except _UNCONVERTED:
        raise
    except Exception:           # noqa: BLE001 -- the point of the helper
        return "<unnamed type>"


# ====================================================== THE checked metric reader
# WHY THIS SECTION EXISTS AT ALL, and the rule it enforces, because three successive rounds of this audit
# failed to the SAME defect and each fix closed only the consumer it was looking at:
#   round 2 (dashboard): `_interval` gated on `MetricValue.is_measured` while `_metric_cell` checked the
#     value properly -- fixed by a shared `_finite_float` across "all" consumers, a HAND-MAINTAINED set;
#   round 3 (dashboard): `pair.n` had two consumers that disagreed, and a forged `n` bought a verdict;
#   round 3 (here): `IntervalPair._bound` closed the LEFT operand of `lo > margin` while the RIGHT operand,
#     one line away in the same call chain, still had the identical `is_measured`-only gate.
# `MetricValue.is_measured` is ONLY `value is not None` (`toy/schema.py`). `MetricValue.__post_init__`
# refuses a non-float, a bool and a non-finite float AT CONSTRUCTION.
#   THIS COMMENT USED TO CONTINUE "so a `MetricValue` built by the public API is sound". THAT WAS FALSE,
#   it was the premise the whole checked-reader architecture was said to rest on, and nothing read it (a
#   doc-only mutant DELETING the sentence survived the suite). The construction check was
#   inspect-before-normalise: `isinstance(v, float)` admits a float SUBCLASS, `math.isfinite` reads the
#   stored double, and the `value == 0.0` normalisation at the end was `type(v).__eq__` -- so
#   `MetricValue.measured(EqZero(7.0)).value` was 0.0, the SCHEMA'S OWN VALIDATOR substituting the
#   stored measurement, and an honest JOINT_UNSUPPORTED recomputed as JOINT_SUPPORTED with `reasons=()`.
#   `MetricValue.__post_init__` now stores the plain double it checked (see `toy/schema.py`), so a
#   metric built by the public API holds the number that was validated. The REST of this rule stands
#   unchanged and is why the readers below are not optional: `object.__setattr__(mv, "value",
#   <anything>)` is route (b) of this module's own threat model, every stored metric reaching a
#   recompute has been through serialisation, and a construction-time guarantee says nothing about
#   either. So NO consumer may read `.value` or `.is_measured` for itself.
#
# THE RULE: in this module and in `toy/robustness.py` every read of a stored metric goes through
# `_metric_read` below (which reaches the field by `getattr` with a string literal, inside one function);
# an `Enum` payload is read through `robustness._enum_value` for the same reason.
#
# HOW THE RULE IS ENFORCED, and the correction of a claim that used to stand here. ROUND 4 wrote a STATIC
# RULE OVER SPELLINGS -- an AST walk for `ast.Attribute` nodes named `value`/`is_measured` plus `ast.Call`
# nodes named `getattr`/`setattr`/`vars`/`__getattribute__` -- and this comment claimed that under it "a
# future reader cannot add [an unchecked read] and have the suite stay green". THAT CLAIM WAS FALSE, and it
# failed in the way every enumeration-by-syntax fails: the list of spellings is itself hand-maintained.
# MEASURED against that rule alone, 2 of 17 spellings of the same read were caught and 15 evaded it
# (`getattr(x, "val" + "ue")`, a module-level `_F = "value"`, `x.__dict__.get("value")`, `vars(x)`,
# `dataclasses.asdict(x)`, `operator.attrgetter`, `operator.itemgetter(...)(vars(x))`, destructuring, a
# comprehension, a lambda, a nested function, a method on a new class, `functools.partial`,
# `x.__getattribute__("value")` -- and `MetricValue.to_dict()` already returns `{"value": ...}`, so no new
# code is even needed). Two of that rule's four `getattr`-form branches were DEAD: `vars` takes no second
# positional argument, and `__getattribute__` is spelled as an `ast.Attribute`, never as an `ast.Name`.
# WHAT ENFORCES IT NOW is a RUNTIME RECORDING PROBE
# (`tests/toy_tests/test_benchmark.py::TheCheckedReaderIsTheOnlyWayToReadAStoredMetric`): it installs a
# recording `__getattribute__` on `MetricValue` itself, runs a REAL study, a REAL recompute and the REAL
# SR-11 probes, and compares the (reader function, attribute) pairs ACTUALLY READ off a stored metric by
# these two modules against a declared table, in BOTH directions. A probe sees the read however it is
# spelled, because it hooks the object rather than the source text. The AST rule is KEPT, with its two dead
# branches fixed, as a cheap tripwire -- not as a guarantee. The probe's own honest limit is that it sees
# only what the run it performs exercises, so each read site additionally carries a test that forges the
# metric behind it and asserts the VERDICT and the REASONS TUPLE (`EveryReadSiteIsPinnedByItsConsequence`).
def _plain_number(v: Any) -> Optional[float]:
    """Collapse a real number to a PLAIN `float`, or None if it is not one. NORMALISE BEFORE CHECKING.

    THE ORDERING DEFECT THIS EXISTS FOR, and the reason every validator in this module now normalises
    first: a predicate applied to a value and a conversion of that value are two INDEPENDENTLY OVERRIDABLE
    operations, so inspecting `v` and then using `float(v)` / `abs(v)` / `int(v)` / `v > m` checks one
    number and decides on another. No tampering primitive is needed -- a `float` subclass passes
    `isinstance(v, float)`, and `math.isfinite` reads the STORED double, which the subclass need not lie
    about. MEASURED, on `_check_margin`, which tested `abs(v)` and returned `float(v)`:

        class Sneaky(float):
            def __abs__(self):   return 1.0
            def __float__(self): return -1e308
        _check_margin(Sneaky(0.0), "m")  ->  -1e+308      # MARGIN_MAX is 1e6

    and on `_metric_read` itself, which checked `math.isfinite(v)` and then returned `v` ITSELF, overrides
    and all: a `MetricValue.measured(Lo(-9.0))` built through the PUBLIC api, with `__gt__` returning True,
    made a genuinely NEGATIVE interval read SUPPORTED against an honest margin of 0.1 -- component,
    hypothesis and joint -- with no `object.__setattr__` anywhere.
    `float.__float__` / `int.__int__` are used rather than `float(v)` / `int(v)` DELIBERATELY: they read
    the value the object actually STORES, which is the same number `math.isfinite` and `MetricValue`'s own
    construction check inspected, so the number checked and the number returned cannot differ. A
    `__float__` override is not consulted second; it is not consulted at all.
    Returns None for a bool, a non-number, a non-finite float, and an int too large to be a float
    (`10**400` -- which is how an `OverflowError` outside this module's error contract used to escape
    `_check_margin`; `_check_finite` had always converted it)."""
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    try:
        f = float.__float__(v) if isinstance(v, float) else float(int.__int__(v))
    except (OverflowError, ValueError, TypeError):
        return None
    if type(f) is not float or not math.isfinite(f):
        return None
    return f


def _plain_parameter(v: Any) -> Any:
    """Collapse an `int`/`float` SUBCLASS to the plain number it STORES, PRESERVING int-vs-float.

    The companion to `_plain_number` for a field that must keep its declared TYPE. `_plain_number`
    returns a float for everything, which is wrong for a COUNT (`IntervalPair.n`, `n_boot`,
    `ComponentResult.min_n`, `SeedScores.seed`): those are compared with `len()`, used as dict keys and
    digest inputs, and written to records as integral values. A `bool` is returned UNCHANGED, because
    every caller's own type check rejects it by name and silently turning `True` into 1 is the D5 defect.
    Anything that is not an int/float subclass instance is returned unchanged, so this is a normaliser,
    never a validator: the caller still checks what it requires. Same ordering rule as `_plain_number`
    (normalise, THEN compare) and the same pattern as `BenchmarkConfig.__post_init__`'s own loop."""
    if isinstance(v, bool):
        return v
    if isinstance(v, float) and type(v) is not float:
        return float.__float__(v)
    if isinstance(v, int) and type(v) is not int:
        return int.__int__(v)
    return v


def _decided_number(v: Any, what: str, *, integral: bool) -> Any:
    """`_plain_parameter`, and then REFUSE what is not a real number. The VALIDATOR `_plain_parameter`
    deliberately is not.

    THE DEFECT THIS CLOSES, and it is the independent attestation's one FAIL on SR-10. Three rounds
    closed this lane against `int`/`float` SUBCLASSES -- `_plain_parameter` collapses a subclass to the
    plain number it stores -- and its own docstring says what that leaves: "anything that is not an
    int/float subclass instance is returned unchanged, so this is a normaliser, never a validator".
    A NON-NUMERIC object is therefore passed through untouched, and every comparison that decides here
    is then `type(v).__lt__` / `__gt__` on the caller's class.
    MEASURED at 775dedf, on 3.12.4 and 3.13.5, with `p = summarize('H1:S', [1.5, 1.5], level=0.9875,
    n_boot=200, base_seed=7)` -- TWO TIED VALUES -- and an object that is neither an `int` nor a `float`,
    whose comparisons all answer False and which renders as an honest `2`. NO `object.__setattr__`:
    `dataclasses.replace` is the route this module's own `IntervalPair` docstring declares legitimate.
    SIX ROUTES, all six turning `(INCONCLUSIVE, 'n=2 below protocol minimum 30: no verdict')` into
    `(SUPPORTED, 'whole interval above margin')` off a two-value series:
        A `dataclasses.replace(p, n=<int subclass>)`      -- CLOSED already (the control)
        B `dataclasses.replace(p, n=<non-numeric>)`       -- IntervalPair field
        C `interval_verdict(p, m, d, min_n=<non-numeric>)`    -- PUBLIC parameter
        D `interval_verdict(p, m, d, width_tol=<non-numeric>)` -- PUBLIC parameter, and this one
          converts a GENUINE bootstrap/t disagreement into a decisive SUPPORTED
        E `ComponentResult(..., min_n=<non-numeric>)`
        F `ComponentResult(..., width_tol=<non-numeric>)`
    THE FIXTURE IS LOAD-BEARING AND THAT IS MEASURED, NOT ASSUMED. With UNTIED values ([1.4, 1.6]) all
    six routes still bypass the floor -- the reason text changes -- but the disagreement rule absorbs it
    and the verdict stays INCONCLUSIVE. Only TIED values reach SUPPORTED. A test written on an untied
    series measures a weaker defect and would report this as a note.
    WHY THREE CALL SITES AND NOT TWO. C and D pass through NEITHER `__post_init__`: they are the public
    `interval_verdict` parameters. Refusing only in the two dataclasses is a half-fix of exactly the
    shape the comment inside `_verdict_from_bounds` already warns about, so the refusal is applied there
    too -- at the single point where a number DECIDES -- as well as in the two dataclasses, which must
    still refuse so that a stored field and the record built from it cannot disagree.
    `bool` is refused BY NAME, as everywhere else here (D5): `True` is not a count of anything."""
    v = _plain_parameter(v)
    if isinstance(v, bool) or not isinstance(v, int if integral else (int, float)):
        raise ValueError(f"{what} must be a real {'whole number' if integral else 'number'}, "
                         f"not a {_type_name(v)}: a value that is not one cannot be compared, and "
                         f"every comparison this module makes with it decides a verdict")
    return v


def _check_seed(v: Any) -> int:
    """THE ONE ADMISSION for a seed: a real non-bool `int`, collapsed to the plain value it stores.

    Spelled once because this lane had a SECOND ENTRANCE. `SeedScores.__post_init__` refused a non-int
    seed and normalised it, and `build_fixture` -- the other way a seed enters this module -- did
    neither. MEASURED at 775dedf on both interpreters, with an HONEST `class MySeed(int): pass` and no
    `object.__setattr__`: `functools.lru_cache` keys on `__hash__`/`__eq__`, so
    `build_fixture(MySeed(11), cfg)` and `build_fixture(11, cfg)` share ONE entry, and after the
    subclass called first the PLAIN-SEED caller received a fixture whose `.seed` was a `MySeed`
    -- process-wide, decided by call order. The two halves need two different fixtures and only one of
    them escapes:
      * the HONEST subclass poisons silently (`build_fixture(11).seed` is a `MySeed`, `score_seed`
        still returns ok=True), which is a provenance defect: the seed written to records is not the
        seed the caller passed;
      * a subclass that cannot DESCRIBE itself additionally escapes. `score_seed(11, ARM_FACTORIES['E'],
        cfg)` returned ok=True on a clean cache and raised `RuntimeError` after the poisoning call,
        out of the declared family, through `benchmark.py:1944` into `teacher_student.py:385`, which
        is ANOTHER OWNER'S bare `f"...seed{seed}..."`. Closing it there is not this module's to do;
        refusing the subclass before it is stored closes it from this side.
    WHAT THIS DOES NOT DO, stated because the obvious reading is wrong: it does not stop the two calls
    from SHARING a cache entry. The key is hashed before this body runs (the same fact `_arm_fit`
    records). It does not need to: hash-equal int subclasses denote the same seed, and what was wrong
    was the VALUE the shared entry stored, which is now a plain int whoever calls first."""
    if isinstance(v, bool) or not isinstance(v, int):
        raise ValueError(f"seed must be an int, got {_type_name(v)}")
    return int.__int__(v)


# ---------------------------------------------------------------- the KEY lane and the ENUM lane
# `_plain_number` / `_plain_parameter` / `_metric_read` are this module's admissions for a stored VALUE,
# and they held under two full rounds of direct attack. The three below are the SAME argument for the two
# other things a decision in this module is written in: the NAME a value is filed under, and the identity
# of an Enum member. Round 6 normalised `input_hashes` VALUES in `toy.schema`; the same flip came back
# through the KEYS, because `m.get("config")` is `__hash__` + `__eq__` ON THE STORED KEY, not on the
# literal. One invariant covers all three lanes: EVERY DECISION READS THE CHARACTERS THE OBJECT STORES.
def _stored_word(x: Any) -> Optional[str]:
    """The plain `str` `x` STORES, or None when `x` is not a string at all.

    `str.__str__(x)`, not `str(x)` and not `x`, for exactly the reason `_plain_number` returns
    `float.__float__(v)`: a `str` SUBCLASS passes every `isinstance(x, str)` check and need not lie to a
    regex or a format test, while `__eq__`, `__ne__`, `__hash__` and `__str__` are all overridable -- and
    a vocabulary lookup is written in the first three of those. `str.__str__` is not overridable from a
    subclass, so the characters compared are the characters stored. The twin of `toy.dashboard._word`;
    it is NOT a vocabulary check and makes no claim to be, so every caller still tests what it requires."""
    return str.__str__(x) if isinstance(x, str) else None


def _word_keyed(m: Any) -> dict:
    """THE ONE ADMISSION for the KEYS of a stored `Mapping` this module looks a word up in. A plain `dict`
    keyed by the characters each key STORES.

    WHY IT EXISTS, measured at the previous HEAD through `verdict_from_records`, each forgery being one
    key removed and one sibling key answering as it while keeping its own value -- so the verdict is
    decided by a number the record files under a DIFFERENT NAME, with the mapping itself the only record
    of which. All four with `reasons = ()`, i.e. with the exact signature of a clean recompute:
        input_hashes: 'seed_list_2' answers as 'config'   JOINT_INCONCLUSIVE -> JOINT_SUPPORTED
            carrying `cfg.config_hash()` of the DEFAULT cfg, so the recompute binds to a configuration
            NO RECORD EVER FILED A CONFIG HASH FOR (literal 'config' key filed by any record: False).
            The study ran at width_tol=0.10 and the recompute ran at 0.25 with the refusal paragraph gone.
            Planting the STUDY's own hash instead does NOT flip it -- the hash must be the one the
            recompute itself will want, which is why a first attempt at this reads as closed.
        metrics: 'loss_check_exempt' answers as 'gate_seed_list_frozen'  JOINT_INCONCLUSIVE -> SUPPORTED
            a FAILED global gate (seed_list_frozen, stored 0.0) reads PASSED off the 1.0 filed as the
            exemption flag. The `gate_*` lookup is an f-STRING key, so a sweep that collects only
            `ast.Constant` subscripts does not see the site at all.
        metrics: 'loss_check_exempt' answers as 'subject_kind_code'  kind fixture -> 'trained'
            a declared scorer-validation fixture, whose JOINT_SUPPORTED means only "the scorer can say
            yes when the answer is yes by construction", reported as a TRAINED subject.
        metrics: exemption flag hidden behind a key answering as an unread word  RAISES -> SUPPORTED
            the gate-11(c) forgery check ("records claim the exemption but subject_kind_code is not
            'fixture'") is silenced: the record still stores 1.0 and `gm.get` no longer finds it.
    TWO KEYS STORING ONE WORD FAIL CLOSED -- both are dropped and the name reads as ABSENT. This is the
    OPPOSITE of `toy.dashboard._metric_table`, which deliberately does not collapse duplicates because
    two metrics whose keys store the same word are two ROWS and deleting either loses a real measurement.
    The choice differs because the consequence differs: here the name is read to BIND A VERDICT, and
    "absent" is already fail-closed at every one of this module's lookups (an absent `config` hash gives
    JOINT_INCONCLUSIVE with its reason, an absent metric raises), whereas on a display table "absent"
    would be a silent deletion. Serving EITHER of two candidates under a contested name would be a
    verdict bound to a configuration chosen by whichever key the dict probed first.
    A HOSTILE `Mapping` whose `items()` raises returns `{}` rather than propagating: every lookup then
    reads absent, which this module's callers already handle by raising a NAMED error or refusing to
    recompute -- never by taking an unrelated exception out of the module's documented error contract."""
    out: dict = {}
    seen_twice = set()
    try:
        items = list(m.items())
    except Exception:       # noqa: BLE001 - a hostile Mapping need not be iterable; refuse, never raise
        return {}
    for k, v in items:
        w = _stored_word(k)
        if w is None:
            continue        # not a string: it names nothing this module looks up
        if w in out:
            seen_twice.add(w)
        out[w] = v
    for w in seen_twice:
        del out[w]
    return out


def _plain_word(x: Any) -> Any:
    """THE ONE ADMISSION for a word this module looks up IN ONE OF ITS OWN CONSTANTS -- the PROBE side of
    the key lane. `_word_keyed` normalises the names a STORED mapping files its values under; this
    normalises the name the module itself carries to a lookup, when that name came from a caller.

    WHY A SECOND ADMISSION AND NOT THE FIRST ONE. `_word_keyed` rewrites the keys of the mapping being
    probed, so it has nothing to do at `PRIMARY[self.hid]` or `SUBJECT_KIND_CODE[res.subject_kind]`: there
    the mapping is a module constant whose keys are this file's own literals and are already honest, and
    the liar is the SUBSCRIPT. `PRIMARY[HidLiar("H3")]` -- a `str` subclass storing 'H3' whose `__hash__`
    is `hash("H1")` and whose `__eq__` answers True to both -- serves H1's ONE-component row for an id
    that renders as 'H3' and requires TWO, so `HypothesisResult.__post_init__`'s length check passes on
    the wrong row and the SELECTIVITY component is dropped and never evaluated (MEASURED:
    JOINT_UNSUPPORTED -> JOINT_SUPPORTED, `h3.hid` rendering 'H3', components `['delta']`, and nothing in
    the output saying a requirement was skipped). The same object shape at `SUBJECT_KIND_CODE[...]` files
    a declared scorer-validation FIXTURE under the TRAINED code 1.0 (MEASURED, and the recompute does not
    catch it when the gate list claims no exemption), which erases the one disclaimer this module's header
    exists for.

    Anything that is not a `str` is returned UNCHANGED, so this is a normaliser, never a validator: every
    caller still runs its own membership check, and `None` must keep reading as "not a gate name" rather
    than as the characters of `'None'`. Same ordering rule as `_plain_number` and `_plain_parameter`
    (normalise, THEN compare), and the same reason `str.__str__` rather than `str()`: see `_stored_word`.
    THE SITES ARE ENUMERATED, not remembered -- see `PROBE_LANE_CONSTANT_LOOKUPS`.
    WHAT THAT ENUMERATION DOES NOT REACH, stated because its scope would otherwise read as wider than it
    is. It collects the SUBSCRIPT, `.get` and `in` spellings of a lookup. TWO COMPARISON-SPELLED probes
    into module constants sit outside all three: `set(self.metrics) != set(SEED_METRICS)` in
    `SeedScores.__post_init__` and `sorted(names) != sorted(GATE_SCOPES)` in `JointResult.__post_init__`.
    Both let a caller's `__eq__` / `__hash__` decide against a module constant, and both are admitted
    anyway for reasons that are at the sites and are NOT interchangeable: the first normalises the keys
    with `_word_keyed` on the line above, so the sets compared are the stored words; the second compares
    names the loop beneath it has plainified, and `GateResult.__post_init__`'s own measurement records
    that this comparison is NOT what closed that site. MEASURED as not consequential, and declared here
    rather than promoted: a THIRD comparison-spelled probe would be a new finding, not a new entry."""
    w = _stored_word(x)
    return x if w is None else w


def _plain_word_fields(obj: Any, *names: str) -> None:
    """`_plain_word` applied to named fields of a frozen dataclass, at construction. One admission per
    OBJECT beats one per site for the same reason `SeedScores` admits `metrics` at the class rather than
    at `ok`, `evaluate_gates`, `joint_verdict` and `seed_records` separately: `JointResult.subject_kind`
    alone is probed at four sites in three functions, and a fix per site is the half-fix pattern this
    module has already failed to three times."""
    for n in names:
        object.__setattr__(obj, n, _plain_word(getattr(obj, n)))


def _enum_member(cls: Any, x: Any) -> Any:
    """THE ONE ADMISSION for an Enum-valued field this module compares by IDENTITY. The genuine member of
    `cls` whose value the object STORES, or None.

    Round 10's SR-11 lesson in this module's own spellings: `Verdict`, `JointVerdict` and `EvidenceClass`
    are `str` subclasses by construction (`toy.schema._plain_value` depends on it), so `x is
    Verdict.SUPPORTED` is False for an `x` that `==` cannot distinguish from the member. MEASURED at the
    previous HEAD, with `VL` a `str` subclass whose `__eq__` answers True to `Verdict.SUPPORTED`:
        VL == Verdict.SUPPORTED  ->  True        VL is Verdict.SUPPORTED  ->  False
    and the six identity sites in this module pointed in MIXED directions, which is why neither `is` nor
    `==` is right everywhere and a blanket rewrite to `==` would have opened TWO sites to close one.
    THE TABLE IS KEYED BY FUNCTION, NOT BY LINE NUMBER: every line number it used to carry (1717, 998,
    1079, 1089, 1713, 1977) had gone stale, which is the same rot as a hand-maintained list of spellings.
        `JointResult.__post_init__`'s `self.h3.verdict is Verdict.SUPPORTED`  -- FAIL OPEN. The class
            invariant "gate 12 (convergence) failed => H3 cannot be SUPPORTED" does not fire, and
            `combine_joint` then coerces the same object with `Verdict(h3)` and reports JOINT_SUPPORTED.
        `HypothesisResult.__post_init__`, TWICE (`v is Verdict.SUPPORTED` over the components and
            `c.verdict is Verdict.SUPPORTED` over the converged-budget components) -- fail CLOSED as
            written (the liar reads as not-supported => INCONCLUSIVE); `==` would have made these TWO
            read SUPPORTED. These two, and not three, are the whole of what the uniform rule buys here.
        `combine_joint`'s `all(... is Verdict.SUPPORTED for v in vs)` -- THIS ROW USED TO BE COUNTED WITH
            THE THREE ABOVE AND THAT WAS FALSE, which is why the count above is two and not three. The
            site was ALREADY FAIL-OPEN one line further up: `vs = (Verdict(h1), Verdict(h2), Verdict(h3))`
            is itself a `_value2member_map_` probe, i.e. `__hash__` + `__eq__` on the caller's object, and
            the liar WINS it. MEASURED at this HEAD with `VL` as above: `Verdict(VL)` ->
            `Verdict.SUPPORTED` (the real member), `_enum_member(Verdict, VL)` -> None, and
            `combine_joint(SUPPORTED, SUPPORTED, VL, True)` -> JOINT_SUPPORTED. So `vs` held genuine
            members by the time the comparison ran and the `_enum_member` wrap added here WAS a no-op.
            IT IS NO LONGER A NO-OP, AND THAT SENTENCE IS WITHDRAWN RATHER THAN LEFT TO READ TRUE.
            The paragraph used to end "what the row does NOT excuse is the coercion itself; `Verdict(h3)`
            is a separate lane (a constructor probe, not an identity comparison) and is out of this
            sweep's scope" -- i.e. the coercion was DECLARED open. N3 of the SR-10 attestation measured
            what that cost: `Verdict(h)` builds its own message out of the caller's object, `enum.py`'s
            `ValueError("%r is not a valid %s")`, so a `str` subclass holding an invalid value whose
            `__repr__` raises left `combine_joint` as a `RuntimeError` FROM THE STANDARD LIBRARY --
            which `test_benchmark._DIAGNOSTIC_SITES`, a census over THIS file, structurally cannot see.
            The coercion now goes through `_enum_member` too and refuses in family, so the liar above
            is REFUSED instead of reading as SUPPORTED: `combine_joint(SUPPORTED, SUPPORTED, VL, True)`
            raises `ValueError` at this HEAD. The row's arithmetic is unchanged -- `==` would still have
            opened TWO sites and not three -- but the wrap at this site is now load-bearing, and
            `test_benchmark.TheEnumTableRowThatWasFalseIsCorrected` asserts the refusal rather than the
            old no-op.
        `JointResult.__post_init__`'s `h.verdict is not Verdict.INCONCLUSIVE`  -- fail CLOSED as written;
            `!=` would have let a decisive hypothesis past the failed-global-gate check.
        `verdict_from_records`'s `r.evidence_class is not EvidenceClass.TOY_RESULT` -- fail CLOSED as
            written; `!=` would ACCEPT a non-member that merely compares equal.
    ADMITTING THE OPERAND closes both directions at once and leaves the direction argument unnecessary:
    after this call the thing compared is a real member, so `is` means what it says. `isinstance(x, cls)`
    is required FIRST and deliberately, so that a plain `str` "TOY_RESULT" is still not an
    `EvidenceClass` -- the admission must not be weaker than the `is` it replaces at any site.
    `cls(_stored_word(x))` resolves by the characters stored, which for every member of these three
    classes is its own value (asserted by the test, not assumed here)."""
    if not isinstance(x, cls):
        return None
    w = _stored_word(x)
    if w is None:
        return None
    try:
        return cls(w)
    except ValueError:
        return None


# The admitting calls an identity comparison against a str-backed Enum member may stand behind. A
# DECLARATION read by `test_benchmark`'s AST sweep, which enumerates those comparisons from this file and
# fails on any whose operand is not one of these -- so a NEW identity site has to be admitted or
# explicitly exempted, rather than noticed by a reviewer.
ENUM_ADMISSIONS = ("_enum_member", "Verdict", "JointVerdict", "EvidenceClass")

# Every place this module looks a key up in a mapping it reaches THROUGH A FIELD, rather than in a local
# already admitted by `_word_keyed` or in one of its own constants. A DECLARATION, not a proof: what makes
# it load-bearing is that `test_benchmark.TheKeyLaneSweepIsDerivedFromTheModuleNotFromAList` enumerates
# these sites from this file's AST -- string-literal AND f-STRING keys, since the `gate_*` lookup is an
# f-string and a Constant-only sweep does not see it at all -- and fails if the set it finds differs. A
# NEW lookup through a field therefore has to be admitted or written down here with its reason, which is
# the property no previous round's fix had: `input_hashes` was found in round 6, normalised on its VALUES,
# and came back in round 12 through its KEYS because nothing enumerated the sites.
#   VARIABLE KEYS ARE COLLECTED TOO, as of this round, and that is a correction rather than an extension.
# The sweep used to collect string and f-string keys only and defer a variable key "to the payload walk" --
# but the payload walk reaches RECORD mappings and nothing else, so `self.newmap[k]` on any other object
# was covered by neither. MEASURED: mutant M9c (a new mapping field plus a verdict-deciding variable-key
# read of it) was unkilled by `test_benchmark`, `test_dashboard` and `test_robustness` together. Collecting
# variable keys costs THREE more declarations, listed below, and closes the gap by enumeration instead of
# by a promise about where the other sweep looks.
#   THAT FIGURE SAID "four" AND WAS WRONG, corrected here and in the test that repeated it: this table
# went 3 -> 6 (`s.metrics`, `other.params`, `teacher.params` PLUS `self.metrics`, `o.conditioned`,
# `o.unconditioned`), which is three more and not four. The other half of the claim -- "two of which say
# this is a `range` index" -- is right (`o.conditioned`, `o.unconditioned`). The length of this table is
# now PINNED by the test rather than narrated here, because a figure in a test is pinned and a correction
# in a comment is not; that is the lesson this round's third accounting correction was itself about.
KEY_LANE_ATTRIBUTE_LOOKUPS = MappingProxyType({
    "s.metrics": "ADMITTED AT THE CLASS, not at the site: `SeedScores.__post_init__` runs `_word_keyed` "
                 "over `metrics` before its exact-key-set check, so every `s.metrics[...]` in this module "
                 "and every key `seed_records` copies into a record is the word the producer's key stored. "
                 "One admission per object beats one per site here because `ok`, `evaluate_gates`, "
                 "`joint_verdict` and `seed_records` all read the same mapping. Both the literal-key and "
                 "the VARIABLE-key spellings (`s.metrics[key]` in `evaluate_gates`, `s.metrics[k]` in "
                 "`analyze_scores`) are covered by that one admission.",
    "self.metrics": "the SAME field and the same class admission, read from inside `SeedScores.ok` as "
                    "`self.metrics[k]` with a VARIABLE key. It used to be mentioned only in prose inside "
                    "the `s.metrics` entry, on the grounds that the AST sweep could not see a variable "
                    "key; the sweep now sees it, so it is declared where the sweep reads rather than "
                    "described where a reader might not.",
    "other.params": "REACHABLE, and the previous reason for this entry was WRONG in its inference while "
                    "right in its count. It used to say the C_rand branch is one 'no study builds' -- but "
                    "`ARM_FACTORIES` is public, `run_study`'s `treatment` is a caller-supplied argument, "
                    "and `ARM_FACTORIES['C_rand']` declares `trained_student=True` with `arm_name` "
                    "'C_rand', so `run_study(frozen, ARM_FACTORIES['C_rand'], ...)` reaches this branch "
                    "(MEASURED: `treatment_kind(ARM_FACTORIES['C_rand'])` -> 'trained'). What actually "
                    "carries the entry is the IN-PROCESS ARGUMENT: `other` is "
                    "`make_teacher(derive_seed(seed, 'rand_target'), cfg.width)` and `teacher` is "
                    "`build_fixture(...).teacher`, both built by `toy.teacher_student.make_teacher` in "
                    "this process, which writes the four keys as literals -- so no caller object is ever "
                    "a key of either mapping, whoever runs the arm.",
    "teacher.params": "the same construction and the same in-process argument; see `other.params`.",
    "o.conditioned": "NOT A WORD LOOKUP AT ALL, declared because the sweep now collects variable keys and "
                     "therefore sees it: `o` is a `TeacherOutputs` and `i`/`j` are integers from "
                     "`range(...)` in `_control_adequacy`, so the subscript is a SEQUENCE INDEX. A rule "
                     "that guessed index-ness from the spelling of the variable would be the lexical "
                     "rule this project has retired three times, so it is written down instead.",
    "o.unconditioned": "the same object and the same integer `range` indices; see `o.conditioned`.",
})

# The PROBE side of the key lane: every place this module looks a word up in ONE OF ITS OWN CONSTANTS
# with a key that is NOT a literal. There `_word_keyed` has nothing to normalise -- the constant's keys
# are this file's literals and are already honest -- and the liar is the SUBSCRIPT. A DECLARATION on the
# same terms as `KEY_LANE_ATTRIBUTE_LOOKUPS`: `test_benchmark.TheProbeLaneSweepIsDerivedFromTheModule`
# enumerates these sites from this file's AST, keyed by ENCLOSING FUNCTION so a moved site fails closed
# rather than hiding behind an identical subscript text elsewhere, and fails if the set differs. Each
# value names the admission that makes the site read the characters the probe stores.
#   THE INVARIANT: a lookup into a module constant decides on the characters the probe stores.
# Every entry is either admitted by `_plain_word` / `_plain_word_fields` at or above the site, or is
# UNREACHABLE BY A CALLER'S OBJECT and says why. Nothing here is "a reviewer looked at it".
PROBE_LANE_CONSTANT_LOOKUPS = MappingProxyType({
    "HypothesisResult.__post_init__: PRIMARY[self.hid]":
        "`_plain_word_fields(self, 'hid')` is the first statement of `__post_init__`, so both the "
        "membership refusal and the component-count check read the stored characters. THE FINDING THIS "
        "CLOSES: `PRIMARY[HidLiar('H3')]` served H1's one-component row, the length check passed, and the "
        "SELECTIVITY component was dropped and never evaluated -- JOINT_UNSUPPORTED -> JOINT_SUPPORTED.",
    "evaluate_primary: PRIMARY[hid]":
        "`hid = _plain_word(hid)` at the top, before the refusal and before `build(PRIMARY[hid])`. "
        "Normalising only inside `HypothesisResult` would be too late: this function picks the component "
        "TABLE off the probe and builds the components from it.",
    "exploratory_interval: PRIMARY[name]":
        "`name = _plain_word(name)` at the top. The consequential direction here is mild and stated "
        "rather than inflated: `ExploratoryResult` has no verdict field at all, so a probe that evaded "
        "the refusal bought a label, not a verdict. Closed anyway, because the refusal is the sentence "
        "'only H1, H2, H3 can produce a verdict' in executable form.",
    "_tag: PRIMARY[hid]":
        "`hid = _plain_word(hid)` at the top. `len(PRIMARY[hid]) == 1` decides whether a component is "
        "filed as `H3` or as `H3a`/`H3b`, i.e. the NAME a record is stored under and the name "
        "`verdict_from_records` requires -- a probe reading as H1 collapsed all three H3 records onto one "
        "tag (MEASURED: `records missing for ['H3a','H3b','H3a_conv','H3b_conv']`).",
    "GateResult.scope: GATE_SCOPES[self.name]":
        "the same normalised field, read by the `scope` property -- which is the one that DECIDES whether "
        "a failed gate forces INCONCLUSIVE everywhere ('all') or only blocks a SUPPORTED H3 ('H3'). It "
        "gets its own entry rather than sharing `__post_init__`'s because the sweep is keyed by enclosing "
        "function: two identical subscripts in two methods are two sites, and collapsing them is how a "
        "site moves out from under a declaration unnoticed.",
    "GateResult.__post_init__: GATE_SCOPES[self.name]":
        "`_plain_word_fields(self, 'name')` is the first statement of `__post_init__`, so the unknown-gate "
        "refusal and the `scope` property read the same characters. MEASURED AT THE PRE-FIX HEAD THIS SITE "
        "ALREADY FAILED CLOSED, and the reason matters because the reason previously recorded for it was "
        "wrong: it is NOT `sorted(names) != sorted(GATE_SCOPES)` (a liar that answers its own stored word "
        "passes that elementwise `==`), it is that 'convergence' is the only scope-'H3' gate, so a probe "
        "must answer 'convergence' to downgrade a global gate -- and then `'convergence' in failed` finds "
        "it by the same hash and the gate-12 invariant fires. Closed by reading now, not by that accident.",
    "JointResult.__post_init__: GATE_SCOPES[n]":
        "`failed` is built with `_plain_word(g.name)` as its keys. `g.name` is normalised for a real "
        "`GateResult`, but this comprehension reads `.name` off ANY object in the list -- a hand-built "
        "gate list may carry a duck-typed object, exactly as `carries_exemption` already documents -- so "
        "the normalisation is at the comprehension and not left to the class.",
    "verdict_from_records: GATE_SCOPES[n]":
        "UNREACHABLE BY A CALLER'S OBJECT: `n` iterates `GATE_SCOPES` itself (`state = {n: gm.get(...) "
        "for n in GATE_SCOPES}`, then `failed` filters that dict), so every probe is one of this file's "
        "own literal keys. Nothing to admit; declared so the site is enumerated rather than overlooked.",
    "evaluate_gates: SUBJECT_KINDS[subject_kind]":
        "`subject_kind = _plain_word(subject_kind)` at the top, before the refusal and before "
        "`exempt = subject_kind == 'fixture'` -- the one line that decides whether gate 11(c)'s E-loss "
        "check runs at all.",
    "JointResult.__post_init__: SUBJECT_KINDS[self.subject_kind]":
        "`_plain_word_fields(self, 'subject_kind')` is the first statement of `__post_init__`, so the "
        "membership refusal, the `fixture_name` biconditional and the `carries_exemption(gates) and "
        "self.subject_kind != 'fixture'` invariant all read the stored characters. THE FINDING THIS "
        "CLOSES: a probe storing 'fixture' and answering 'trained' was accepted, rendered as 'fixture', "
        "and made every record file the TRAINED code.",
    "_agg_metrics: SUBJECT_KIND_CODE[subject_kind]":
        "`subject_kind = _plain_word(subject_kind)` at the top. Its only caller passes "
        "`res.subject_kind`, which `JointResult` already normalises, but this function is the one that "
        "turns a word into the STORED NUMBER a recompute decodes, so it does not inherit the guarantee.",
    "to_experiment_records: SUBJECT_KIND_CODE[res.subject_kind]":
        "`res.subject_kind` is normalised by `JointResult.__post_init__`; this is the JOINT record's "
        "`subject_kind_code`, the number `verdict_from_records` decodes the kind from. MEASURED pre-fix: "
        "2.0 (fixture) became 1.0 (trained) with `loss_check_exempt` 0.0, so the gate-11(c) cross-check "
        "had nothing to fire on and the recompute reported `subject_kind 'trained'`, JOINT_SUPPORTED, "
        "`reasons = ()`.",
    "seed_records: SUBJECT_KIND_CODE[res.subject_kind]":
        "the same normalised field, on the per-seed audit trail. Worth its own entry because this record "
        "set is NOT the one `verdict_from_records` reads, so no cross-check anywhere covers it: a wrong "
        "code here is wrong in the only place a reader goes for per-seed provenance.",
    "_arm_fit: ARM_NAMES[arm]":
        "`arm = _plain_word(arm)` at the top -- AND, separately, at both call paths that can carry a "
        "caller's object (`_arm_params` and `score_seed`'s `trained_arm`). The second half is not "
        "belt-and-braces: `_arm_fit` is `functools.lru_cache`d, so the cache key is HASHED BEFORE THE "
        "BODY RUNS and a normalisation inside the body cannot reach it. A probe storing 'C_rand' that "
        "answers 'C0' would otherwise be served the C0 entry of the cache.",
    "treatment_kind: ARM_NAMES[_plain_word(getattr(treatment, 'arm_name', None))]":
        "the probe is read through `_plain_word`. `None` must keep reading as 'not an arm name', which is "
        "why `_plain_word` returns a non-`str` unchanged instead of stringifying it. This is the "
        "TRUSTED-DECLARATION boundary and the entry claims no more: a caller who declares a trained "
        "student still gets 'trained'. What is closed is the narrower thing -- the declared arm name is "
        "validated against the characters it stores, so it cannot pass validation as one arm and then be "
        "cached, scored and reported as another.",
})


# Every place this module reads an ATTRIBUTE off an ELEMENT of a collection it iterates -- the THIRD lane
# of the same rule as `KEY_LANE_ATTRIBUTE_LOOKUPS` (the mapping it reaches through a field) and
# `PROBE_LANE_CONSTANT_LOOKUPS` (the word it looks up in its own constants). A DECLARATION on the same
# terms: `test_benchmark.TheElementLaneSweepIsDerivedFromTheModule` collects every attribute read whose
# object is the target of a `for` statement or of a comprehension generator in this file, keyed by
# ENCLOSING FUNCTION, and fails if the set differs -- so a NEW read off a collection element has to be
# admitted or written down here with its reason.
#   WHY THE LANE EXISTS AT ALL, and why a list of two was not enough. Round 13 wrapped
# `JointResult.__post_init__`'s `failed = {_plain_word(g.name): g ...}` *because* "this comprehension
# reads `.name` off ANY object in the list" -- and left the sibling comprehension 145 lines later,
# `to_experiment_records`' `gate_m`, unguarded, where a DUPLICATE duck-typed gate name overwrote a
# genuinely failed gate's stored 0.0 with 1.0 and `verdict_from_records` reported JOINT_SUPPORTED with
# `reasons = ()` (SR-10 Finding 1; the measurement is at the site). DERIVING the lane rather than listing
# it found a SECOND flip nobody had reported: `evaluate_gates`' `ids = [s.seed for s in scores]`, where a
# duck-typed score object walks around `SeedScores.__post_init__` -- the one place the seed is normalised
# -- and buys seed_list_frozen PASSED, JOINT_SUPPORTED and a clean recompute off ONE seed repeated thirty
# times (measurement at that site too). Two sites of 33 were consequential and neither was findable from
# the other; that is the argument for enumeration over inspection.
#   THE INVARIANT: an attribute read off a collection element either reaches an object whose class has
# already admitted the field, or is refused, or is declared fail-closed WITH ITS MEASUREMENT. "A reviewer
# looked at it" is not an entry.
ELEMENT_LANE_ATTRIBUTE_READS = MappingProxyType({
    # ---- admitted by an INSTANCE CHECK at or above the site: the element cannot be anything but the
    # ---- class that normalises the field, so the class's admission reaches the read.
    "HypothesisResult.__post_init__: c.verdict":
        "`if not all(isinstance(c, ComponentResult) for c in self.components + self.converged_components)` "
        "raises BEFORE this read, so `verdict` is the one `ComponentResult.__post_init__` DERIVED from the "
        "interval rather than a value an element supplied. This is the shape every other entry in this "
        "lane is measured against: refuse the element, then read it.",
    "HypothesisResult.__post_init__: c.metric":
        "the same instance check, one line above. `metric` only reaches `reasons`, which is prose, but it "
        "is read off the same validated element and is declared rather than left to be inferred from the "
        "verdict entry above it.",
    "HypothesisResult.__post_init__: c.reason":
        "the same instance check, and `reason` is `init=False` on `ComponentResult` -- DERIVED by "
        "`interval_verdict` beside the verdict, never supplied -- so this read cannot carry a caller's "
        "prose even before the instance check is considered. It reaches `HypothesisResult.reasons` and "
        "nothing else; see `c.metric` for the shape of the argument.",
    "JointResult.__post_init__: h.hid":
        "`if not isinstance(h, HypothesisResult) or h.hid != hid` -- the instance check is the FIRST "
        "operand and `or` short-circuits, so the comparison never runs on a non-HypothesisResult. The "
        "second read (the failed-global-gate loop) runs after all three slots have passed that check.",
    "JointResult.__post_init__: h.verdict":
        "the same loop, and an unadmittable verdict is REFUSED there rather than interpreted below "
        "(`_enum_member(Verdict, h.verdict) is None` raises) -- because the two gate invariants read it in "
        "OPPOSITE directions and no single default for 'cannot tell what this is' is fail-closed at both.",
    "evaluate_gates: s.seed":
        "REFUSED AT THIS FUNCTION: every element of `scores` must be a real `SeedScores` or the call "
        "raises, because `SeedScores.__post_init__` is the only place the seed is normalised and this read "
        "feeds both seed-list gates. THE MEASURED FLIP IS AT THE REFUSAL ITSELF: duck score objects "
        "carrying one lying `int` subclass bought seed_list_frozen PASSED, min_seeds PASSED, "
        "JOINT_SUPPORTED and a recompute of JOINT_SUPPORTED with `reasons = ()` off a single seed.",
    "evaluate_gates: s.ok":
        "the same refusal, which also makes `ok` the derived property (`all(_metric_ok(...))`) rather than "
        "a flag an element asserts -- a duck returning True from `ok` with nothing measured inflated "
        "`n_ok` and so the min_seeds and failure_rate gates.",
    "evaluate_gates: s.metrics":
        "the same refusal; `ok_scores` is a local list comprehended from the already-refused `scores`. "
        "`SeedScores.__post_init__` normalises these KEYS with `_word_keyed` and requires the exact key "
        "set, which is what makes `s.metrics['E_loss_ratio']` at gate 11(c) the producer's own metric.",
    "analyze_scores: s.ok":
        "`evaluate_gates(scores, ...)` is called before these reads and refuses a non-`SeedScores` "
        "element, so this function inherits the refusal rather than repeating it. Stated rather than "
        "assumed: if that call ever moves below these reads, this entry is wrong and the lane says so.",
    "analyze_scores: s.metrics":
        "the same inherited refusal; the values go through `_metric_read`, so an unreadable metric is "
        "dropped from the series rather than coerced. See `s.ok`.",
    "seed_records: s.seed":
        "ADMITTED AT THE OBJECT: `JointResult.__post_init__` refuses a `seed_scores` element that is not a "
        "`SeedScores`, so the seed this writes into `RunProvenance` is the plain int that class stored. "
        "One admission per object beats one per site here for the same reason `_plain_word_fields` exists: "
        "`seed_records` alone reads four fields off these elements.",
    "seed_records: s.metrics":
        "the same class refusal, which carries the `_word_keyed` key normalisation and the exact-key-set "
        "check into the per-seed audit trail -- the record set NO cross-check anywhere reads, so a wrong "
        "key here is wrong in the only place a reader goes for per-seed provenance.",
    "seed_records: s.ok":
        "the same class refusal; `ok` decides this record's `evidence_class` (TOY_RESULT vs UNKNOWN), so an "
        "element asserting it would be labelling its own evidence class.",
    "seed_records: s.input_hashes":
        "the same class refusal. The KEYS of this mapping are additionally normalised by `RunProvenance`'s "
        "own construction boundary, which raises on collision -- deliberately left there rather than "
        "duplicated here, and recorded as that boundary's business.",
    "to_experiment_records: h.hid":
        "`res.h1/h2/h3` are instance-checked by `JointResult.__post_init__`, so the hid is the one "
        "`HypothesisResult.__post_init__` normalised with `_plain_word_fields` and refused against "
        "`PRIMARY` -- which matters because `_tag` subscripts `PRIMARY` with it to pick the record NAME.",
    "to_experiment_records: h.components":
        "the same class refusal on the slot, and `HypothesisResult.__post_init__`'s own instance check on "
        "the tuple's elements, so `comps` holds genuine `ComponentResult`s two steps up.",
    "to_experiment_records: h.converged_components":
        "the same two steps; see `h.components`. Its length is additionally bounded by "
        "`len(self.converged_components) > len(CONVERGED)` at the class.",
    "to_experiment_records: c.metric":
        "`comps` is `h.components` / `h.converged_components`, both instance-checked at "
        "`HypothesisResult.__post_init__`, so this is a genuine `ComponentResult.metric`. NOT NORMALISED "
        "AT THAT CLASS and deliberately so: `__post_init__` admits `margin`, `min_n` and `width_tol` but "
        "not `metric`, which `_tag` reads through `startswith`/`in`/`replace`. MEASURED and declared NOT "
        "CONSEQUENTIAL -- the collapse direction fails closed (the tag names a record "
        "`verdict_from_records` then requires and cannot find), and the swap direction is FULLY LATERAL: "
        "same tag set, same joint verdict, same reasons.",
    "to_experiment_records: c.margin":
        "the same instance check, and `ComponentResult.__post_init__` STORES WHAT WAS CHECKED -- "
        "`_check_margin`'s plain float -- so `_agg_metrics` writes the validated number and not a third "
        "conversion of the caller's object.",
    "to_experiment_records: c.pair":
        "the same instance check; every scalar of the pair is read through `IntervalPair._bound` and the "
        "checked metric reader at the point of use, so this read carries no number of its own.",
    "to_experiment_records: g.passed":
        "ITERATES `real.items()`, NOT `res.gates`: `real` is built one loop above behind "
        "`isinstance(g, GateResult)`, refuses a duplicate name and refuses an incomplete set, so this "
        "element is a validated gate and `passed` is the exact bool `GateResult.__post_init__` required. "
        "THIS IS SR-10 FINDING 1 AND THE MEASUREMENT IS AT THE SITE; the entry is written against the "
        "iterable because reading the same field off `res.gates` is what the defect was.",
    # ---- MODULE-BUILT ELEMENTS: unreachable by a caller's object, and why.
    "analyze_scores: g.name":
        "UNREACHABLE BY A CALLER'S OBJECT: `gates` is the local tuple `evaluate_gates` returned two lines "
        "above, every element of which this module constructed with `GateResult(...)` in this process. No "
        "caller supplies, appends to or replaces it. Declared so the site is enumerated rather than "
        "overlooked -- the property no previous round's fix had.",
    "analyze_scores: g.passed":
        "the same in-process tuple; see `g.name`. This read decides the `glob` blocking list, so it would "
        "matter if the tuple were ever caller-supplied, which is the reason the entry is here.",
    "analyze_scores: g.reason":
        "the same in-process tuple, and `GateResult.__post_init__` requires `reason` to be a `str`. It "
        "reaches the `glob` / `g12` blocking strings and nothing else -- prose carried into "
        "`HypothesisResult.reasons`, never a number and never a verdict. Declared because the lane "
        "enumerates reads, not just the consequential ones.",
    "analyze_scores: g.scope":
        "the same in-process tuple, and `scope` is the `GATE_SCOPES` lookup on the gate's own normalised "
        "name, declared in `PROBE_LANE_CONSTANT_LOOKUPS`.",
    # ---- DUCK-TYPED ELEMENTS DELIBERATELY ADMITTED, each fail-closed WITH ITS MEASUREMENT. A gate list
    # ---- may carry a non-`GateResult`: that is documented at `carries_exemption` and a test in
    # ---- `test_dashboard` pins the route, so these sites must read ducks and must not be made to refuse.
    "JointResult.__post_init__: g.name":
        "THREE READS, all on a list that may carry a duck: the completeness check FILTERS "
        "(`isinstance(g, GateResult)`), the `failed` loop normalises with `_plain_word` AND now refuses an "
        "unknown name with a ValueError instead of escaping as `KeyError` from `GATE_SCOPES[n]` "
        "(measured: a duck named 'extra_gate' with a FALSY `passed` -- the documented duck fixtures all "
        "PASS, so nothing covered it). Admitting the duck is deliberate: refusing it here would break the "
        "`carries_exemption` route this module documents and `test_dashboard` pins.",
    "JointResult.__post_init__: g.passed":
        "read off ANY object, deliberately, and FAIL-CLOSED in both directions: a duck that reports FAILED "
        "enters `failed` and can only ADD a blocking gate (or now be refused by name), and a duck that "
        "reports PASSED is skipped and can take nothing away, because no invariant here is of the form "
        "'some gate passed'. The direction is the whole of the argument and it is stated, not implied.",
    "JointResult.gates_ok: g.passed":
        "`all(g.passed for g in self.gates if g.scope == 'all')` -- a duck CANNOT MASK a failed real gate, "
        "because `all` requires every element, so the only direction a duck moves this property is toward "
        "False. An extra failing duck making an honest result INCONCLUSIVE is the conservative error and "
        "is accepted as such.",
    "JointResult.gates_ok: g.scope":
        "the same `all`; a duck that answers a scope other than 'all' removes ITSELF from the "
        "comprehension and nothing else, and a duck answering 'all' can only add a conjunct. "
        "`dashboard._gate_set_ok` is what reports the extra object to a reader, and it does not filter.",
    "to_experiment_records: g.name":
        "read off ANY object in the loop that BUILDS `real`, which is the point: the read happens AFTER "
        "`isinstance(g, GateResult)` has `continue`d past every duck, so the name entering `real` is the "
        "one `GateResult.__post_init__` normalised and refused against `GATE_SCOPES`. The duck is ignored "
        "rather than refused, exactly as the completeness check ignores it.",
    # ---- DECLARED OPEN, and not closed quietly.
    "verdict_from_records: r.name":
        "THE DUCK-TYPED RECORD ROUTE IS DECLARED OPEN: this function ENFORCES NO INSTANCE CHECK, and a "
        "plain object with `name`, `metrics`, `evidence_class` and `provenance` reaches every lookup. "
        "`r.name` is read through `_stored_word`, so the tag is cut out of the characters the name STORES "
        "and a `str` subclass cannot file a record under another component's tag. A test documents the "
        "route deliberately; it is listed here as OPEN rather than as admitted.",
    "verdict_from_records: r.evidence_class":
        "THE SAME ROUTE, DECLARED OPEN, and the read itself is closed: `_enum_member(EvidenceClass, ...) is not "
        "EvidenceClass.TOY_RESULT` raises, so a non-member that merely compares equal to TOY_RESULT is "
        "refused rather than accepted.",
    "verdict_from_records: r.provenance":
        "THE SAME ROUTE, DECLARED OPEN; the mapping it reaches is normalised at the read "
        "(`_word_keyed(r.provenance.input_hashes).get('config')`), which is the key-lane admission "
        "declared in `KEY_LANE_ATTRIBUTE_LOOKUPS`, not an element-lane one.",
})


def _metric_read(x: Any) -> Optional[float]:
    """Read a stored `MetricValue` as a number. Returns a genuine finite `float`, or None.

    None means exactly "no usable number here", which every caller in this module already handles as the
    fail-closed case (unmeasured, no verdict). It covers all of: an honestly unmeasured metric; a forged
    `nan`/`inf`/`-inf`; a forged `int`, `bool`, `str`, `list` or `None`; and an object that is not a
    `MetricValue` at all. `isinstance(v, bool)` is checked FIRST because `True` is an `int` and
    `True == 1.0`, which is how a forged gate metric read as PASSED (D5).
    IT RETURNS A PLAIN `float`, NEVER THE STORED OBJECT. Returning the object itself was the round-4
    defect: a `float` subclass satisfies `isinstance(v, float)` and need not lie to `math.isfinite`, so
    every downstream `lo > margin` ran on overridable dunders. See `_plain_number` for the measurement."""
    v = getattr(x, "value", None)
    if isinstance(v, bool) or not isinstance(v, float):
        return None
    return _plain_number(v)


def _metric_declared_unmeasured(x: Any) -> bool:
    """True iff `x` is a `MetricValue` in the EXPLICIT unmeasured state (value None, WITH a reason).

    Separates "honestly absent" from "forged garbage": both give `_metric_read(x) is None`, and for the
    `loss_check_exempt` cross-check the difference decides between accepting and raising. The reason is
    required because that is the state `MetricValue.unmeasured` actually produces -- `__post_init__`
    refuses `value=None` without one -- so a value forged to `None` by `object.__setattr__` on a measured
    metric leaves `reason` as None and is correctly classified as forged rather than as honestly absent."""
    if not isinstance(x, MetricValue) or getattr(x, "value", None) is not None:
        return False
    why = getattr(x, "reason", None)
    return isinstance(why, str) and bool(why.strip())


def _metric_ok(x: Any) -> bool:
    """The replacement for every `MetricValue.is_measured` read: measured AND readable as a number."""
    return _metric_read(x) is not None


def _metric_required(x: Any, what: str) -> float:
    """A stored metric a verdict depends on. No fail-open: unreadable => ValueError naming the metric."""
    v = _metric_read(x)
    if v is None:
        raise ValueError(f"{what}: stored metric is not a usable finite number ({_shown(x)}); refusing to recompute")
    return v


def _metric_count(x: Any, what: str) -> int:
    """A stored metric that is a COUNT (n_seeds, n_boot): required, integral and nonnegative.

    THE DEFECT THIS CLOSES (D4): `_pair_from_record` did `int(m["n_seeds"].value)` with no check at all, so
    a forged `n_seeds=1e9` was silently accepted and cleared the protocol's minimum-n floor, while a forged
    `nan` escaped as a bare `ValueError: cannot convert float NaN to integer` and a forged `None` as a
    `TypeError` -- both outside this module's stated error contract."""
    v = _metric_required(x, what)
    if v != int(v) or v < 0:
        raise ValueError(f"{what}: stored count {_shown(v)} is not a nonnegative whole number")
    return int(v)


def _metric_strict(x: Any, what: str) -> Optional[float]:
    """A stored metric that may be honestly absent but must never be malformed.

    Returns the number, or None if `x` is missing or EXPLICITLY unmeasured. Anything else -- a forged
    non-finite, a bool, a string -- RAISES, because for a cross-check field "unreadable" is evidence of
    tampering and must not be laundered into the same outcome as "not recorded"."""
    if x is None:
        return None
    v = _metric_read(x)
    if v is None and not _metric_declared_unmeasured(x):
        raise ValueError(f"{what}: stored metric is neither a finite number nor explicitly unmeasured ({_shown(x)})")
    return v


def _check_margin(v: Any, what: str) -> float:
    """THE ONE validity test for a margin, wherever a margin enters the module. Returns it as a float.

    A margin is a THRESHOLD on an effect size in G_s units, pre-registered before any arm is run. Two
    things disqualify a value from being one, and both are checked here:
      * it is not a finite real number (bool, str, None, nan, +-inf);
      * its magnitude exceeds `MARGIN_MAX`. `MARGIN_MAX = 1e6` is ARBITRARY and is NOT a protocol
        parameter -- it is a sanity bound, seven orders of magnitude above the proposed defaults
        (0.05 / 0.10) and far outside any plausible G_s-scale threshold. Sign is NOT bounded, on purpose:
        the vacuous direction differs per field (H1/H3 compare `lo > margin`, so a very NEGATIVE margin is
        vacuous; H2 compares `hi < margin`, so a very POSITIVE one is), and a negative `delta_R` -- "the
        retention loss must be an improvement" -- is a legitimately STRICTER test, not an invalid one.
    WHAT THIS DOES AND DOES NOT BUY, stated because a bound of this shape invites overreading:
      * It closes the forged-record route (D1): a stored `margin` metric of -1.7976931348623157e308 turned
        a genuine JOINT_UNSUPPORTED into JOINT_SUPPORTED with `reasons = ()` and an unchanged
        `config_hash` -- indistinguishable from a clean recompute. It now raises.
      * It does NOT close, and cannot close, the legal-`Margins` route. `Margins(-1e6, +1e6, -1e6)` is
        within bounds and still decides every component before any data is seen. FOR ANY FINITE CAP there
        is a legal margin at the cap that is vacuous for a small-effect study, so no bound here can make a
        margin trustworthy. Margins are producer-asserted and are NOT in `config_hash` (see `Margins`);
        that remains a documented gap, and this bound narrows it rather than closing it.
    It is applied at the single point where a margin is USED to decide (`_verdict_from_bounds`), so every
    path -- `evaluate_primary` from a `Margins` object, `verdict_from_records` from a stored metric, a
    hand-built `interval_verdict` or `ComponentResult` call -- is covered by construction. There is no set
    of call sites to remember, which is the mistake that produced three rounds of half-fixes.
    ORDER MATTERS AND IS THE ROUND-4 FIX: the value is NORMALISED FIRST (`_plain_number`) and every test
    below, plus the returned value, is the normalised one. This function used to test `abs(v)` and return
    `float(v)` -- two independently overridable dunders -- so `Sneaky(0.0)` with `__abs__` returning 1.0 and
    `__float__` returning -1e308 came back as -1e+308, seven orders outside this function's own bound, and
    carried SUPPORTED through `interval_verdict`, `ComponentResult` and `HypothesisResult`. It also raised
    `OverflowError` for `10**400` while this docstring called such a value "not a finite real number" and
    `interval_verdict` promised a `ValueError`; `_plain_number` converts it, as `_check_finite` always did."""
    f = _plain_number(v)
    if f is None:
        raise ValueError(f"{what} must be a finite number, got {_shown(v)}")
    if abs(f) > MARGIN_MAX:
        raise ValueError(f"{what} magnitude {f!r} exceeds MARGIN_MAX={MARGIN_MAX!r}: a threshold that large "
                         f"decides the component without reference to the data (it is not a margin)")
    return f


# =================================================================== enums
class Verdict(str, Enum):
    SUPPORTED = "SUPPORTED"
    UNSUPPORTED = "UNSUPPORTED"
    INCONCLUSIVE = "INCONCLUSIVE"


class JointVerdict(str, Enum):
    JOINT_SUPPORTED = "JOINT_SUPPORTED"
    JOINT_UNSUPPORTED = "JOINT_UNSUPPORTED"
    JOINT_INCONCLUSIVE = "JOINT_INCONCLUSIVE"


# ============================================================== parameters
@dataclasses.dataclass(frozen=True)
class Margins:
    """PROTOCOL PARAMETERS (proposed defaults, arbitrary, no empirical basis), in G_s units.

    NOT COVERED BY `BenchmarkConfig.config_hash()`, stated because it would otherwise be a silent gap:
    `Margins` is not a `BenchmarkConfig` field and is not written into `input_hashes`, so TWO STUDIES
    DIFFERING ONLY IN MARGINS PRODUCE BYTE-IDENTICAL `config_hash` -- and margins change verdicts.
    What recomputation does and does not get from the per-record `margin` metric, precisely (this paragraph
    USED TO CLAIM "so the margin a recompute uses is always the margin that produced the record", which was
    FALSE: nothing validated it, and the claim was a PROVENANCE argument offered as a VALIDITY argument):
    every component record stores its own `margin` as a measured metric (`_agg_metrics`), and
    `verdict_from_records` reads the margin OUT OF THE RECORD it is recomputing -- never from a caller's
    `cfg`, never from `config_hash`. That means a margin a recompute uses cannot come from the CALLER. It
    does NOT mean the margin is the one that produced the record: a stored `margin` metric rewritten to
    -1.7976931348623157e308 (a finite float, which `MetricValue` therefore accepts) turned a measured
    JOINT_UNSUPPORTED degrader study into JOINT_SUPPORTED with `reasons = ()` and the SAME `config_hash`
    ce68ac811ac7 -- byte-identical to a clean recompute. `_check_margin` now bounds every margin, wherever
    it enters, so that route raises instead; see `_check_margin` for what the bound does and does not buy.
    MEASURED, AND SHARPER THAN THE `delta_S=5.0, delta_R=-5.0` ILLUSTRATION THAT USED TO STAND HERE (which
    only showed the SAFE direction -- it drives the same study to JOINT_UNSUPPORTED): a WITHIN-BOUNDS, fully
    legal `Margins(-1e6, +1e6, -1e6)` turns that study's JOINT_UNSUPPORTED into JOINT_SUPPORTED, with a
    byte-identical `config_hash` and `reasons = ()`. No bound on this class can close that -- for any finite
    cap, a margin at the cap is vacuous for a small-effect study -- so margins remain PRODUCER-ASSERTED.
    What the gap DOES cost: `config_hash` alone is not a complete provenance key for a study, and a
    favourable verdict is not evidence that the margins were registered rather than chosen. Do not quote
    `config_hash` as a provenance key on its own; quote the per-component `margin` metrics (or
    `JointResult.margins`) alongside it, and treat a margin near `MARGIN_MAX` as unregistered."""
    delta_S: float = 0.10
    delta_R: float = 0.05
    delta_sel: float = 0.10

    def __post_init__(self) -> None:
        # STORE WHAT WAS CHECKED. The return value used to be discarded, so the field kept whatever object
        # the caller passed and `evaluate_primary` re-read it through a bare `float(getattr(...))` -- a
        # second, overridable conversion of a value that had already been validated once (see
        # `_plain_number`). The field now holds the plain float `_check_margin` admitted.
        for k in ("delta_S", "delta_R", "delta_sel"):
            object.__setattr__(self, k, _check_margin(getattr(self, k), k))


@dataclasses.dataclass(frozen=True)
class BenchmarkConfig:
    """PROTOCOL PARAMETERS plus toy-fixture sizes. Must be frozen before any arm is run."""
    width: int = 3
    n_train: int = 24        # protocol: >= 16 so the masked subset has >= 2 distinct values per column
    n_eval: int = 32         # rows in each of T and U
    steps: int = 300
    lr: float = 0.3
    eta_star: float = 0.5
    g_min: float = 1e-3      # outcome-independent eligibility threshold on teacher-only G_s
    n_boot: int = 10_000     # protocol B
    alpha: float = 0.05      # family-wise
    min_seeds: int = 30
    max_failure_rate: float = 0.05
    width_tol: float = 0.25
    steps_conv: int = 1000      # converged budget for C_conv (protocol 4.1); PROTOCOL PARAMETER
    tau_conv: float = 1e-3      # gate 12: final/initial gradient norm must be <= this in every converged run
    delta_A: float = 0.05       # gate 11(a): lower bound of mean A(s) must exceed this
    eps_fit: float = 0.05       # gate 11(b): upper bound of mean F(s) must be below this
    loss_factor: float = 2.0    # gate 11(c): E training loss must fall at least this factor in every run
    tail_ratio_max: float = 10.0  # assumption-2 flag threshold on max|v|/median|v| (flag only, not a verdict input)

    _INT_FIELDS = ("width", "n_train", "n_eval", "steps", "n_boot", "min_seeds", "steps_conv")
    _NUM_FIELDS = ("lr", "eta_star", "g_min", "alpha", "max_failure_rate", "width_tol", "tau_conv", "delta_A",
                   "eps_fit", "loss_factor", "tail_ratio_max")

    def __post_init__(self) -> None:
        # NORMALISE BEFORE CHECKING (see `_plain_number`): an `int`/`float` SUBCLASS satisfies every
        # `isinstance` test below and can still override `__lt__`, `__float__`, `__int__` or the arithmetic
        # the parameter is then used in, so the value validated here would not be the value used. Only
        # subclass instances are collapsed, to their exact base type: int-vs-float is preserved on purpose,
        # because `config_hash` distinguishes them (see `config_hash`, gap (2)).
        for k in self._INT_FIELDS + self._NUM_FIELDS:
            v = getattr(self, k)
            if isinstance(v, bool):
                continue                              # the type checks below reject it by name
            if isinstance(v, float) and type(v) is not float:
                object.__setattr__(self, k, float.__float__(v))
            elif isinstance(v, int) and type(v) is not int:
                object.__setattr__(self, k, int.__int__(v))
        for k in self._INT_FIELDS:
            v = getattr(self, k)
            if isinstance(v, bool) or not isinstance(v, int) or v < 0:
                raise ValueError(f"{k} must be a nonnegative int")
        if self.width < 1 or self.n_eval < 1 or self.n_boot < 1:
            raise ValueError("width, n_eval and n_boot must be >= 1")
        if self.n_train < 16:
            raise ValueError("n_train must be >= 16 (protocol: masked subset needs >= 2 distinct values)")
        for k in self._NUM_FIELDS:
            # `_plain_number`, not `math.isfinite(v)`: `math.isfinite(10**400)` RAISES `OverflowError`, which
            # is outside this module's stated error contract (`_check_margin` had the same defect, N2).
            f = _plain_number(getattr(self, k))
            if f is None or f < 0:
                raise ValueError(f"{k} must be a finite nonnegative number")
        if self.lr <= 0 or not 0 < self.alpha < 1:
            raise ValueError("lr must be > 0 and alpha in (0,1)")

    def config_hash(self) -> str:
        """sha256 over the canonical JSON of all 18 fields; every field changes it (no collisions found).
        CANONICAL MEANS `sort_keys=True`, and that is load-bearing, not decoration: it is what makes the
        hash a function of the field VALUES rather than of `dataclasses.asdict`'s iteration order.
        MEASURED with `sort_keys` dropped: reordering the dict's keys alone, with every value identical,
        moves the hash from 9eaf4bfefc57 to 08d7772419c5 -- so every stored record's `config` binding would
        break on a field reorder and `verdict_from_records` would fail closed on correct records. With
        `sort_keys=True` both orders give ce68ac811ac7. "Repeatability" is the literal acceptance criterion
        for this module, so the invariance is pinned directly by
        `test_config_hash_is_canonical_under_field_reordering` rather than left to a reader's trust in the
        word "canonical" (a mutant that deleted `sort_keys` previously survived the whole suite).
        TWO DOCUMENTED GAPS: (1) `Margins` is NOT a field and is not hashed -- see `Margins` for why the
        per-record `margin` metric makes recomputation sound anyway, and for what the gap costs. (2)
        `json.dumps` distinguishes int from float, so `BenchmarkConfig(eta_star=1)` and `(eta_star=1.0)`
        compare `==` yet hash DIFFERENTLY. That direction is safe: it can only produce a spurious MISMATCH,
        which fails closed, never a spurious match."""
        return hashlib.sha256(json.dumps(dataclasses.asdict(self), sort_keys=True,
                                         separators=(",", ":")).encode()).hexdigest()


# PROTOCOL-PARAMETER DEFAULTS ARE CONSTRUCTED PER CALL, NEVER AS LITERAL DEFAULT OBJECTS.
# A literal `cfg: BenchmarkConfig = BenchmarkConfig()` is evaluated ONCE at import, and every call that omits
# the argument then shares that one instance. `BenchmarkConfig` and `Margins` are frozen, so ordinary code
# cannot mutate them -- but this module's own threat model and tests routinely use `object.__setattr__` to
# simulate tampering (that is how open routes (b) and (d) below are demonstrated), and that reaches straight
# through the freeze into the shared default. MEASURED consequence before this was fixed: forging
# `delta_S = 99.0` on one result's `margins` flipped a LATER no-argument `analyze_scores` call from
# SUPPORTED to UNSUPPORTED, process-wide, and gave tests a hidden ordering dependency. Every such parameter
# therefore defaults to None and is constructed inside the function (`_cfg` / `_margins`). Equal frozen
# instances still hash and compare equal, so the `lru_cache`s on `build_fixture` / `_arm_fit` keep hitting.
def _cfg(cfg: Optional["BenchmarkConfig"]) -> "BenchmarkConfig":
    return BenchmarkConfig() if cfg is None else cfg


def _margins(margins: Optional["Margins"]) -> "Margins":
    return Margins() if margins is None else margins


# ============================================================ statistics
def _constant(v: Sequence[float]) -> bool:
    return all(x == v[0] for x in v)


def _as_list(v, what: str) -> list:
    """Accept only real sequences of numbers (list/tuple/range...). None, dicts, sets, strings, scalars and
    generators are refused with ValueError (never a raw TypeError/KeyError from deeper in the arithmetic)."""
    if isinstance(v, (str, bytes)) or not isinstance(v, collections.abc.Sequence):
        raise ValueError(f"{what} needs a sequence of numbers, got {_type_name(v)}")
    return list(v)


def _check_finite(v: Sequence[float], what: str) -> list:
    """Validate a sample and RETURN IT AS PLAIN FLOATS, so the sample checked is the sample computed on.

    It used to return None and leave the caller holding the original objects. That is the
    inspect-before-normalise pattern of `_plain_number` applied to a whole sample: an `int`/`float`
    subclass passes every test here (`math.isfinite` reads the stored double) and can still override
    `__eq__` -- which `_constant` uses -- and `__float__` -- which `_mean` then calls on `v[0]` for a
    sample it believes constant. Every caller now rebinds to the returned list."""
    out = []
    for x in v:
        f = _plain_number(x)
        if f is None:
            raise ValueError(f"{what} needs finite numbers (no inf/nan/non-numeric/too-large int)")
        out.append(f)
    return out


def mean(v: Sequence[float]) -> float:
    """Public mean: finite numeric sequences only (ValueError otherwise)."""
    v = _check_finite(_as_list(v, "mean"), "mean")
    return _mean(v)


def _mean(v: Sequence[float]) -> float:
    """Exactly-rounded mean via math.fsum, deliberately NOT built-in sum (sum only became compensated in
    Python 3.12; e.g. sum([1e16,1,-1e16,1])/4 is 0.25 on 3.9 but the true mean is 0.5). A constant sample returns
    that constant exactly (n*x/n can be off by an ulp). Caller guarantees finite input."""
    if len(v) == 0:
        raise ValueError("mean of empty sample")
    if _constant(v):
        return float(v[0])
    try:
        return math.fsum(v) / len(v)
    except OverflowError:     # the SUM overflows although the mean may not: average the scaled terms instead
        r = math.fsum(x / len(v) for x in v)
        if not math.isfinite(r):
            raise ValueError("mean is not representable as a finite float") from None
        return r


def _sum_sq(v: Sequence[float], m: float) -> float:
    """Sum of squared deviations via math.fsum. EQUIVALENCE CLAIM, stated precisely: substituting built-in sum is
    overflow-equivalent through sample_sd (an inf result is refused with ValueError either way, confirmed on a real
    n=2e8 input) and was value-identical in 220k random trials on Python 3.12.4 ONLY; it is not proven
    value-equivalent, and below Python 3.12 the built-in sum is uncompensated."""
    return math.fsum((x - m) ** 2 for x in v)


def sample_sd(v: Sequence[float]) -> float:
    """Sample SD, divisor n-1. Exactly 0.0 for a constant sample (no cancellation residue: a zero-variance
    series must be recognisable as such). Otherwise two-pass with an exactly-rounded mean.

    LIMITS OF THE 'SD == 0 iff constant' INVARIANT (stated so nobody relies on more than is true):
    (1) FLOAT FLOOR: a non-constant sample returns 0.0 when its true SD is below ~2.47e-324, which is HALF the
        smallest subnormal (4.94e-324), because 0.0 is then the correctly rounded value. Example:
        [0.0]*5 + [5e-324] has true SD 5e-324/sqrt(6) = 2.017e-324 and returns 0.0.
        Consumers (SR-11 robustness probes) must NOT read zero-SD as 'constant' for samples within a few
        subnormal steps of each other.
    (2) PYTHON INTS beyond 2**53 are converted to float, so sample_sd([10**20, 10**20+1]) is 0.0. SR-11 casts to
        float first (robustness.py, the `float(v)` cast in `SeedSummary.from_values`; cited by symbol, not line
        number, and guarded by a test), so this is only
        reachable by a direct caller. An int too large for float (10**400) raises ValueError.
    (3) FALSE ValueError: a representable SD can still be refused when x - m overflows, e.g.
        [1.7e308, -1.7e308, -1.7e308, -1.7e308]. It fails closed (raises, never mis-reports)."""
    v = _as_list(v, "sample SD")
    n = len(v)
    if n < 2:
        raise ValueError("sample SD needs n >= 2")
    v = _check_finite(v, "sample SD")      # without this, [inf,inf,inf] would give 0.0 (constant) or nan
    if _constant(v):
        return 0.0
    m = _mean(v)
    big = max(abs(x - m) for x in v)
    if big > 0 and not 1e-150 < big < 1e150:
        # squares would underflow (below ~1e-162 a non-constant sample would report SD 0.0, breaking the invariant
        # "SD == 0 iff constant") or overflow: factor out the largest deviation, compute, scale back.
        r = big * math.sqrt(math.fsum(((x - m) / big) ** 2 for x in v) / (n - 1))
        if not math.isfinite(r):
            raise ValueError("sample SD is not representable as a finite float")
        return r
    try:
        r = math.sqrt(_sum_sq(v, m) / (n - 1))
    except OverflowError:     # reachable only when n*big^2 overflows (e.g. n above ~1.8e8 near big=1e150)
        raise ValueError("sample SD is not representable as a finite float") from None
    if not math.isfinite(r):  # a sum that overflowed to inf instead of raising (e.g. a plain-sum implementation)
        raise ValueError("sample SD is not representable as a finite float")
    return r


def quantile(sorted_v: Sequence[float], p: float) -> float:
    """Linear-interpolation quantile (the 'type 7' definition): position p*(n-1) in the sorted sample.

    `p` is NORMALISED BEFORE the range test, so the position computed is the one validated: `0.0 <= p
    <= 1.0` is two overridable comparisons and `p * (n - 1)` is an overridable `__mul__`. See
    `_plain_number`."""
    p = _plain_number(p)
    if p is None or not 0.0 <= p <= 1.0:
        raise ValueError("p must lie in [0, 1]")
    n = len(sorted_v)
    if n == 0:
        raise ValueError("quantile of empty sample")
    pos = p * (n - 1)
    i = int(math.floor(pos))
    if i >= n - 1:
        return float(sorted_v[-1])
    return sorted_v[i] + (pos - i) * (sorted_v[i + 1] - sorted_v[i])


def bonferroni_level(alpha: float = 0.05, m: int = N_PRIMARY) -> float:
    """Per-hypothesis two-sided confidence level 1 - alpha/m. The primary family has m = N_PRIMARY = 4 intervals
    (alpha=.05 -> 0.9875). The formula is generic: m=3 would give 0.98333, which is NOT the protocol level."""
    # NORMALISE BEFORE CHECKING (see `_plain_number`). This site was found by the entry-point sweep in
    # `test_benchmark.NormaliseBeforeCheckingEverywhereANumberEnters`, not by reading the code: `0 < alpha
    # < 1` is two overridable comparisons and `alpha / m` an overridable `__truediv__`, so a `float`
    # subclass holding 30.0 was ACCEPTED and one holding 0.25 was REFUSED -- wrong in both directions.
    a = _plain_number(alpha)
    if a is None or not 0 < a < 1 or isinstance(m, bool) or not isinstance(m, int):
        raise ValueError("need 0 < alpha < 1 and integer m >= 1")
    m = int.__int__(m)
    if m < 1:
        raise ValueError("need 0 < alpha < 1 and integer m >= 1")
    return 1.0 - a / m


def _check_level(level: float) -> float:
    """Validate a confidence level and RETURN IT as a plain float; every caller rebinds to the result.

    It used to return None, so the caller kept the original object: a `float` subclass overriding `__lt__`
    / `__gt__` passed `0 < level < 1` with a stored value of 5.0 and then supplied `__rsub__` to
    `(1.0 - level) / 2.0` inside `percentile_interval`, i.e. it chose its own interval tails. Same
    inspect-before-normalise pattern as `_check_margin`; see `_plain_number`."""
    f = _plain_number(level)
    if f is None or not 0 < f < 1:
        raise ValueError("level must be in (0, 1)")
    return f


def percentile_interval(stats: Sequence[float], level: float) -> tuple[float, float]:
    """Percentile interval of already-computed resample statistics (type-7 quantiles at
    (1-level)/2 and 1-(1-level)/2)."""
    level = _check_level(level)
    s = sorted(stats)
    tail = (1.0 - level) / 2.0
    return quantile(s, tail), quantile(s, 1.0 - tail)


def bootstrap_means(values: Sequence[float], n_boot: int, rng) -> list[float]:
    """n_boot resample means; each resample draws len(values) items with replacement."""
    values = _as_list(values, "bootstrap")
    if not callable(getattr(rng, "choices", None)):
        raise ValueError("rng must provide .choices (e.g. a random.Random from make_rng)")
    if len(values) < 1 or isinstance(n_boot, bool) or not isinstance(n_boot, int) or n_boot < 1:
        raise ValueError("need a nonempty sample and n_boot >= 1")
    n = len(values)
    vals = list(values)
    vals = _check_finite(vals, "bootstrap")
    return [_mean(rng.choices(vals, k=n)) for _ in range(n_boot)]


def bootstrap_ci(values: Sequence[float], level: float, n_boot: int, rng) -> tuple[float, float]:
    """Percentile bootstrap CI of the mean over seed-level values."""
    return percentile_interval(bootstrap_means(values, n_boot, rng), level)


def _betacf(a: float, b: float, x: float) -> float:
    tiny, eps = 1e-300, 3e-16
    qab, qap, qam = a + b, a + 1.0, a - 1.0
    c, d = 1.0, 1.0 - qab * x / qap
    d = 1.0 / (d if abs(d) > tiny else tiny)
    h = d
    for m in range(1, 1000):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        d = 1.0 / (d if abs(d) > tiny else tiny)
        c = 1.0 + aa / c
        c = c if abs(c) > tiny else tiny
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        d = 1.0 / (d if abs(d) > tiny else tiny)
        c = 1.0 + aa / c
        c = c if abs(c) > tiny else tiny
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < eps:
            break
    return h


def _betainc(a: float, b: float, x: float) -> float:
    """Regularised incomplete beta I_x(a, b)."""
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    bt = math.exp(math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b) + a * math.log(x) + b * math.log1p(-x))
    if x < (a + 1.0) / (a + b + 2.0):
        return bt * _betacf(a, b, x) / a
    return 1.0 - bt * _betacf(b, a, 1.0 - x) / b


def t_cdf(t: float, df: float) -> float:
    """Student-t CDF via the incomplete beta function."""
    if df <= 0:
        raise ValueError("df must be positive")
    x = df / (df + t * t)
    tail = 0.5 * _betainc(df / 2.0, 0.5, x)
    return 1.0 - tail if t > 0 else tail


def t_ppf(p: float, df: float) -> float:
    """Student-t quantile by bisection on t_cdf (accuracy ~1e-12)."""
    if not 0.0 < p < 1.0:
        raise ValueError("p must be in (0, 1)")
    if p == 0.5:
        return 0.0
    if p < 0.5:
        return -t_ppf(1.0 - p, df)
    lo, hi = 0.0, 1.0
    while t_cdf(hi, df) < p:
        hi *= 2.0
        if hi > 1e15:
            raise ValueError("t quantile out of range")
    for _ in range(200):
        mid = 0.5 * (lo + hi)
        if t_cdf(mid, df) < p:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)


def t_interval(values: Sequence[float], level: float) -> tuple[float, float]:
    """Two-sided t-interval for the mean, df = n-1 (needs n >= 2)."""
    level = _check_level(level)
    values = _as_list(values, "t-interval")
    values = _check_finite(values, "t-interval")   # BEFORE any arithmetic: no raw TypeError/OverflowError
    n = len(values)
    if n < 2:
        raise ValueError("t-interval needs n >= 2")
    m, se = _mean(values), sample_sd(values) / math.sqrt(n)
    h = t_ppf(1.0 - (1.0 - level) / 2.0, n - 1) * se
    return m - h, m + h


def _sign(b: float, m: float) -> int:
    return (b > m) - (b < m)


def intervals_disagree(boot: tuple[float, float], tint: tuple[float, float], margin: float,
                       width_tol: float = 0.25) -> tuple[bool, str]:
    """Protocol 6.3 disagreement rule. Disagree iff (a) some bound (lower or upper) is on a different
    side of `margin` in the two intervals, or (b) the widths differ by more than width_tol.
    Relative width difference is |wb-wt| / max(wb, wt) (the protocol does not name the denominator);
    both widths zero => no width disagreement."""
    for nm, b, t in (("lower", boot[0], tint[0]), ("upper", boot[1], tint[1])):
        if _sign(b, margin) != _sign(t, margin):
            return True, (f"{nm} bound on different sides of margin {_shown(margin)} "
                          f"(bootstrap {_shown(b)}, t {_shown(t)})")
    wb, wt = boot[1] - boot[0], tint[1] - tint[0]
    big = max(wb, wt)
    if big > 0 and abs(wb - wt) / big > width_tol:
        return True, (f"widths differ by more than {_shown(width_tol, spec='.0%')} "
                          f"(bootstrap {_shown(wb)}, t {_shown(wt)})")
    return False, "agree"


# ============================================================ interval pair
def _mv(x: Optional[float], reason: str) -> MetricValue:
    """A number or an explicit absence. `_plain_number` rather than `math.isfinite(x)` then `float(x)`: one
    operation, so the number recorded is the number checked (see `_plain_number`)."""
    f = _plain_number(x)
    return MetricValue.unmeasured(reason) if f is None else MetricValue.measured(f)


@dataclasses.dataclass(frozen=True)
class IntervalPair:
    """Mean, spread and both intervals for one per-seed series. All numbers are MetricValues."""
    name: str
    n: int
    level: float
    n_boot: int
    mean: MetricValue
    sd: MetricValue
    iqr: MetricValue
    minimum: MetricValue
    maximum: MetricValue
    max_over_median_abs: MetricValue   # assumption-2 check (heavy tails)
    boot_lo: MetricValue
    boot_hi: MetricValue
    t_lo: MetricValue
    t_hi: MetricValue
    flags: tuple = ()

    def __post_init__(self) -> None:
        """STORE WHAT WAS CHECKED, for the three scalars that are NOT `MetricValue`s.

        This class had NO `__post_init__` at all, which is how it escaped the entry-point sweep that
        fixed `_check_margin`, `_check_level`, `_metric_count` and `Margins`: there was no place to look.
        `n` is the one that matters, and it is DATA (the number of seeds a series was measured on), not
        a protocol parameter -- protocol 6.1's floor is applied as `n < min_n` inside
        `_verdict_from_bounds`, i.e. as `type(n).__lt__`. MEASURED, with no `object.__setattr__`
        (`dataclasses.replace` suffices, and so does any direct constructor call):

            class NSub(int):
                def __lt__(self, o):  return False
                def __ge__(self, o):  return True
            interval_verdict(replace(pair_of_2_values, n=NSub(1)), 0.1, "greater")  ->  SUPPORTED

        a decisive SUPPORTED off a TWO-value series whose own record then stores `n_seeds = 1.0`. The
        module docstring's "no component verdict exists below the minimum" was false in exactly that
        way. `level` and `n_boot` are recorded, cross-checked against the Bonferroni level and written
        to records as `ci_level` / `n_boot`, so they are normalised here too and nothing downstream
        re-converts them. The MetricValue fields need nothing: `MetricValue.__post_init__` stores the
        plain double it checked and `_bound` / `_metric_read` plainify every read anyway."""
        # REFUSE, not merely normalise: `_plain_parameter` passes a NON-NUMERIC object through
        # unchanged by its own docstring, and the attestation's one FAIL was exactly that -- see
        # `_decided_number`, which carries the six measured routes. All three fields are refused, not
        # just `n`: `level` and `n_boot` are cross-checked and written to records as `ci_level` /
        # `n_boot`, and leaving one member of a normalised set unrefused is this module's half-fix
        # pattern one field out.
        for k, integral in (("n", True), ("n_boot", True), ("level", False)):
            object.__setattr__(self, k, _decided_number(getattr(self, k), f"IntervalPair.{k}",
                                                        integral=integral))

    @staticmethod
    def _bound(m: Any) -> Optional[float]:
        """A bound is usable only if it is a genuine finite `float`, not merely `is_measured`.

        THE DEFECT THIS CLOSES, found by the SR-13 re-attestation and fixed there renderer-side
        while the root cause stayed here: `is_measured` is only `value is not None`
        (`schema.py`), so a post-hoc `object.__setattr__(pair.boot_lo, "value", inf)` -- route (b),
        the same one every other guard in this module is built against -- passed this gate and
        reached `interval_verdict` as a real number. `lo > margin` is then trivially true, so the
        component returned a decisive **SUPPORTED** with no figures behind it. A forged `nan`,
        an `int`, a `str`, a `bool` or a list got the same treatment and were formatted as
        measurements downstream.
        Returning None means "interval not computable", which every caller already handles as the
        fail-closed case, so a forged bound can no longer produce a verdict in either direction.
        THAT FIX WAS HALF A FIX, and this is where it is recorded: it closed the LEFT operand of
        `lo > margin` and left the RIGHT operand -- the stored `margin` metric, one line away in the same
        call chain -- on the identical `is_measured`-only gate. `_bound` now DELEGATES to `_metric_read`,
        the module's single checked reader, so there is one implementation of "is this a usable number"
        rather than one per consumer; see the `_metric_read` section header for the rule that keeps it
        that way. The 152-case table behind this method (19 forged value types x 4 bound fields x 2
        directions) is unchanged by the delegation."""
        return _metric_read(m)

    def boot(self) -> Optional[tuple[float, float]]:
        lo, hi = self._bound(self.boot_lo), self._bound(self.boot_hi)
        return None if lo is None or hi is None else (lo, hi)

    def tint(self) -> Optional[tuple[float, float]]:
        lo, hi = self._bound(self.t_lo), self._bound(self.t_hi)
        return None if lo is None or hi is None else (lo, hi)


def summarize(name: str, values: Sequence[float], level: float, n_boot: int, base_seed: int,
              min_n: int = 30, tail_ratio_max: float = 10.0) -> IntervalPair:
    """Spread + percentile bootstrap + t-interval for one series. The bootstrap RNG is
    make_rng(derive_seed(base_seed, "bootstrap:" + name)) so the interval is reproducible from the record."""
    level = _check_level(level)
    # `_plain_number`, not `float(v)`: the conversion and the finiteness test must be the same operation on
    # the same number (see `_plain_number`). A bare `float(v)` honours a `__float__` override, so the value
    # summarised could differ from the value checked -- and `bool` was admitted as 1.0/0.0.
    vals = [_plain_number(v) for v in values]
    if any(v is None for v in vals):
        raise ValueError("values must be finite; filter failed runs before summarising")
    n = len(vals)
    flags = []
    if n < min_n:
        flags.append("n below protocol minimum")
    if n < 20:
        flags.append("percentile bootstrap unreliable (n < 20)")
    if n >= 2 and len(set(vals)) == 1:
        flags.append("degenerate: all values tied")
    no = "no data" if n == 0 else "needs n >= 2"
    if n == 0:
        u = MetricValue.unmeasured(no)
        return IntervalPair(name, 0, level, n_boot, u, u, u, u, u, u, u, u, u, u, tuple(flags))
    s = sorted(vals)
    med = quantile(sorted(abs(v) for v in vals), 0.5)
    ratio = max(abs(v) for v in vals) / med if med > 0 else None
    mom = _mv(ratio, "median |value| is 0")
    if ratio is not None and ratio > tail_ratio_max:
        flags.append(f"heavy tail: max|v|/median|v| = {ratio:.3g} > "
                         f"{_shown(tail_ratio_max, how=str)} (flag only)")
    if n >= 2:
        bl, bh = bootstrap_ci(vals, level, n_boot, make_rng(derive_seed(base_seed, "bootstrap:" + name)))
        tl, th = t_interval(vals, level)
        sd, iqr = sample_sd(vals), quantile(s, 0.75) - quantile(s, 0.25)
        return IntervalPair(name, n, level, n_boot, _mv(mean(vals), ""), _mv(sd, ""), _mv(iqr, ""),
                            _mv(s[0], ""), _mv(s[-1], ""), mom, _mv(bl, ""), _mv(bh, ""), _mv(tl, ""), _mv(th, ""),
                            tuple(flags))
    u = MetricValue.unmeasured(no)
    return IntervalPair(name, n, level, n_boot, _mv(vals[0], ""), u, u, _mv(s[0], ""), _mv(s[-1], ""), mom,
                        u, u, u, u, tuple(flags))


# =============================================================== verdicts
def _verdict_from_bounds(n: int, boot: Optional[tuple], tint: Optional[tuple], margin: float, direction: str,
                         min_n: int, width_tol: float) -> tuple:
    if direction not in ("greater", "less"):
        raise ValueError("direction must be 'greater' or 'less'")
    # THE SINGLE POINT AT WHICH A MARGIN IS USED TO DECIDE, so the one place it has to be valid. Every path
    # that can produce a component verdict passes through here -- `evaluate_primary` (margin from a
    # `Margins` object), `verdict_from_records.comp` (margin from a stored metric), and any direct
    # `interval_verdict` / `ComponentResult` call -- so `_check_margin` needs no list of call sites.
    margin = _check_margin(margin, "margin")
    # ... AND THE SAME ARGUMENT APPLIES TO THE OTHER THREE NUMBERS THAT DECIDE HERE. `_check_margin`'s
    # docstring states the principle this line implements -- the check belongs at the single point of
    # USE, "so every path is covered by construction [and] there is no set of call sites to remember,
    # which is the mistake that produced three rounds of half-fixes" -- and `n`, `min_n` and `width_tol`
    # were the three it had not been applied to. `n < min_n` and (inside `intervals_disagree`)
    # `... > width_tol` are overridable comparisons; normalising in `IntervalPair.__post_init__` and
    # `ComponentResult.__post_init__` alone would have left the PUBLIC `interval_verdict(pair, margin,
    # direction, width_tol=..., min_n=...)` parameters un-normalised, which is a half-fix of exactly the
    # shape this module keeps rediscovering. (Found by the test written for the dataclass fix, not by
    # reading the code.) The dataclasses still normalise what they STORE, so a field and the record
    # built from it cannot disagree; this covers what they DECIDE.
    # REFUSED here as well as in the two dataclasses, and that is the whole point of this comment
    # block one type-family out: `_plain_parameter` is a normaliser and a NON-NUMERIC object went
    # through it untouched, so routes C and D of `_decided_number`'s measurement -- the PUBLIC
    # `interval_verdict(pair, margin, direction, width_tol=..., min_n=...)` parameters -- pass through
    # neither `__post_init__` and were open with the dataclasses fixed.
    n = _decided_number(n, "n", integral=True)
    min_n = _decided_number(min_n, "min_n", integral=True)
    width_tol = _decided_number(width_tol, "width_tol", integral=False)
    if n < min_n:   # protocol 6.1: no verdict below the minimum number of seeds, wherever the verdict is made
        return Verdict.INCONCLUSIVE, f"n={n} below protocol minimum {min_n}: no verdict"
    if boot is None or tint is None:
        return Verdict.INCONCLUSIVE, "interval not computable (n < 2): unmeasured, not zero"
    bad, why = intervals_disagree(boot, tint, margin, width_tol)
    if bad:
        return Verdict.INCONCLUSIVE, "bootstrap/t disagreement: " + why
    lo, hi = boot
    if direction == "greater":
        if lo > margin:
            return Verdict.SUPPORTED, "whole interval above margin"
        if hi <= margin:
            return Verdict.UNSUPPORTED, "whole interval at or below margin"
    else:
        if hi < margin:
            return Verdict.SUPPORTED, "whole interval below margin"
        if lo >= margin:
            return Verdict.UNSUPPORTED, "whole interval at or above margin"
    return Verdict.INCONCLUSIVE, "interval spans margin"


def interval_verdict(pair: IntervalPair, margin: float, direction: str, width_tol: float = 0.25,
                     min_n: int = 30) -> tuple:
    """Protocol section 7 for one component. direction 'greater': SUPPORTED iff lower > margin,
    UNSUPPORTED iff upper <= margin. direction 'less': SUPPORTED iff upper < margin, UNSUPPORTED iff
    lower >= margin. The bootstrap interval decides; the t-interval can only veto via the disagreement rule.
    n < min_n (default 30) is always INCONCLUSIVE.
    RAISES ValueError (rather than returning a verdict) for a `margin` that is not a finite number or whose
    magnitude exceeds `MARGIN_MAX`: see `_check_margin`. No verdict is the fail-closed outcome, and it is
    consistent with how this module already treats a forged record elsewhere."""
    return _verdict_from_bounds(pair.n, pair.boot(), pair.tint(), margin, direction, min_n, width_tol)


def combine_joint(h1: Verdict, h2: Verdict, h3: Verdict, gates_ok: bool) -> JointVerdict:
    """Protocol section 5. A failed validity gate gives INCONCLUSIVE first (section 5 last line,
    section 7 stop rule); then any UNSUPPORTED => JOINT_UNSUPPORTED; all three SUPPORTED =>
    JOINT_SUPPORTED; otherwise INCONCLUSIVE."""
    # N3: `Verdict(h)` builds its OWN message out of the caller's object -- `enum.py`'s
    # `ValueError("%r is not a valid %s")` -- so a `str` subclass holding an invalid value whose
    # `__repr__` raises escaped as a `RuntimeError` out of `enum.py`. MEASURED at 775dedf on both
    # interpreters. Invisible to `test_benchmark._DIAGNOSTIC_SITES` because the format site is in the
    # standard library, which is why a derived census over THIS file could not have found it.
    # `_enum_member` is this module's safe admission and the lines below already used it; the refusal
    # is kept (and keeps its `ValueError` type) rather than letting an invalid verdict fall through to
    # JOINT_INCONCLUSIVE, which would be a quieter answer than the one this function gives today.
    vs = tuple(_enum_member(Verdict, h) for h in (h1, h2, h3))
    if any(v is None for v in vs):
        # `Verdict.__members__`, NOT `[m.value for m in Verdict]`. The first spelling of this
        # message read `.value` off each member, and THREE of this file's own guards caught it at once
        # -- `TheStaticSpellingRuleIsATripwireNotAGuarantee` (the AST rule over `.value`
        # /`.is_measured`), and `TheElementLaneSweepIsDerivedFromTheModule` twice (a new undeclared
        # `combine_joint: m.value` element read, and its derived count 33 -> 34). The rule is about
        # `MetricValue.value`, and an Enum member's `.value` is a different attribute on a different
        # class -- but the tripwire is lexical ON PURPOSE and a per-site exemption is the thing it
        # exists to avoid, so the message is respelled instead of the rule being widened.
        raise ValueError(f"combine_joint takes Verdict members; a value that is not one of "
                         f"{sorted(Verdict.__members__)} cannot be combined")
    if not gates_ok:
        return JointVerdict.JOINT_INCONCLUSIVE
    if Verdict.UNSUPPORTED in vs:
        return JointVerdict.JOINT_UNSUPPORTED
    if all(_enum_member(Verdict, v) is Verdict.SUPPORTED for v in vs):
        return JointVerdict.JOINT_SUPPORTED
    return JointVerdict.JOINT_INCONCLUSIVE


# component table: hypothesis -> ((per-seed metric, direction, margin attribute), ...)
PRIMARY = {
    "H1": (("S", "greater", "delta_S"),),
    "H2": (("L", "less", "delta_R"),),
    "H3": (("delta", "greater", "delta_sel"), ("delta_minus_shuf", "greater", "delta_sel")),
}
# converged-budget requirement for H3 (protocol 4.1); can only BLOCK a SUPPORTED, never create UNSUPPORTED
# (extra UNSUPPORTED-capable intervals would enlarge the m=4 family).
CONVERGED = (("delta_conv", "greater", "delta_sel"), ("delta_minus_shuf_conv", "greater", "delta_sel"))
assert N_PRIMARY == sum(len(v) for v in PRIMARY.values())


@dataclasses.dataclass(frozen=True)
class ComponentResult:
    """One interval and its verdict. The verdict is DERIVED from the interval in __post_init__."""
    metric: str
    direction: str
    margin: float
    pair: IntervalPair
    min_n: int = 30
    width_tol: float = 0.25
    verdict: Verdict = dataclasses.field(init=False)
    reason: str = dataclasses.field(init=False)

    def __post_init__(self) -> None:
        # STORE WHAT WAS CHECKED (see `Margins.__post_init__` and `_plain_number`): the field used to keep
        # the caller's object while only the DERIVED verdict saw the checked value, so `_agg_metrics` wrote
        # `MetricValue.measured(float(c.margin))` -- a third conversion -- into the record.
        object.__setattr__(self, "margin", _check_margin(self.margin, "margin"))
        # `min_n` and `width_tol` are passed in the SAME call as `margin` and were left untouched, which
        # is the half-fix pattern this module has failed to three times. Both decide a verdict through an
        # overridable comparison -- `n < min_n` in `_verdict_from_bounds` and `abs(wb - wt) / big >
        # width_tol` in `intervals_disagree`, each resolving to the REFLECTED operator because the
        # subclass is the right operand. MEASURED: `width_tol=WSub(0.25)` with `__lt__`/`__gt__` returning
        # False turned a genuine INCONCLUSIVE ("widths differ by more than 25%") into SUPPORTED, and
        # `min_n=MSub(30)` gave SUPPORTED off a two-value series -- both while the fields still RENDER as
        # 0.25 and 30 and the margin beside them was fully validated.
        # REFUSE, not merely normalise -- see `_decided_number`. Routes E and F of its measurement.
        # THIS SITE IS REDUNDANT TODAY AND THAT IS MEASURED, NOT ASSUMED. `__post_init__` below always
        # derives the verdict through `interval_verdict` -> `_verdict_from_bounds`, which refuses the
        # same two values at the point of USE, so a mutant that degrades THIS line back to
        # `_plain_parameter` is UNKILLED by the whole suite on both interpreters (round 25, mutant R3).
        # It is kept anyway, and the reason is a rule and not a preference: a field that decides is
        # refused where it is STORED as well as where it is READ, so a future change that stops
        # deriving the verdict here cannot silently store a value nothing checked. What is NOT claimed
        # is that this line is independently pinned -- it is not, the mutation harness says so, and
        # saying "defence in depth" without that measurement would be the overclaim this module's
        # history is made of.
        for k, integral in (("min_n", True), ("width_tol", False)):
            object.__setattr__(self, k, _decided_number(getattr(self, k), f"ComponentResult.{k}",
                                                        integral=integral))
        v, why = interval_verdict(self.pair, self.margin, self.direction, self.width_tol, self.min_n)
        object.__setattr__(self, "verdict", v)
        object.__setattr__(self, "reason", why)


@dataclasses.dataclass(frozen=True)
class HypothesisResult:
    """Verdict derived from components and gate state (never a free argument).
    blocking: gate failures that force INCONCLUSIVE. supported_blockers: failures that only prevent SUPPORTED
    (gate 12 for H3: protocol says 'H3 cannot be SUPPORTED')."""
    hid: str
    components: tuple
    converged_components: tuple = ()
    blocking: tuple = ()
    supported_blockers: tuple = ()
    label: str = "PRIMARY"
    verdict: Verdict = dataclasses.field(init=False)
    reasons: tuple = dataclasses.field(init=False)

    def __post_init__(self) -> None:
        # NORMALISE THE PROBE, THEN LOOK IT UP -- the ordering rule of `_plain_number`, one lane further
        # out. `hid` is not just validated against `PRIMARY`, it SELECTS THE ROW THAT SAYS HOW MANY
        # COMPONENTS THIS HYPOTHESIS REQUIRES, so a probe that answers as another id does not merely
        # evade a refusal, it replaces the requirement. MEASURED through this PUBLIC constructor with no
        # `object.__setattr__`, with `HidLiar` a `str` subclass storing 'H3' whose `__hash__` is
        # `hash('H1')` and whose `__eq__` answers True to 'H3' and 'H1':
        #     PRIMARY[HidLiar('H3')] -> one row (H1's), where H3 requires two
        #     HidLiar('H3') != 'H3'  -> False, so the H3 converged-budget path below still runs
        #     HypothesisResult('H3', (one component,))  -> ValueError, the honest short build
        #     HypothesisResult(HidLiar('H3'), (one component,), conv)  -> ACCEPTED, verdict SUPPORTED,
        #         `hid` rendering as 'H3', components ['delta'], and NOTHING in `reasons` saying the
        #         selectivity requirement was skipped
        # and `JointResult.__post_init__`'s `h.hid != hid` read False too, so the construction stood:
        # JOINT_UNSUPPORTED -> JOINT_SUPPORTED on a study whose shuffled-control comparison was the only
        # thing holding it down. See `_plain_word` and `PROBE_LANE_CONSTANT_LOOKUPS`.
        _plain_word_fields(self, "hid")
        if self.hid not in PRIMARY:
            raise ValueError(f"{_shown(self.hid)} is not a primary hypothesis")
        if len(self.components) != len(PRIMARY[self.hid]):
            raise ValueError("wrong number of components for " + self.hid)
        if self.hid != "H3" and self.converged_components:
            raise ValueError("only H3 has converged-budget components")
        if len(self.converged_components) > len(CONVERGED):
            raise ValueError("too many converged-budget components")
        if not all(isinstance(c, ComponentResult) for c in self.components + self.converged_components):
            raise ValueError("components must be ComponentResult objects (verdicts are derived, not supplied)")
        vs = [c.verdict for c in self.components]
        reasons = [f"{_shown(c.metric, how=str)}: {_shown(c.reason, how=str)}" for c in self.components]
        if self.blocking:
            verdict = Verdict.INCONCLUSIVE
            reasons = [f"gate failed: {_shown(g, how=str)}" for g in self.blocking] + reasons
        elif Verdict.UNSUPPORTED in vs:
            verdict = Verdict.UNSUPPORTED
        elif not all(_enum_member(Verdict, v) is Verdict.SUPPORTED for v in vs):
            verdict = Verdict.INCONCLUSIVE
        elif self.hid != "H3":
            verdict = Verdict.SUPPORTED
        elif self.supported_blockers:
            verdict = Verdict.INCONCLUSIVE
            reasons += [f"cannot be SUPPORTED, gate failed: {_shown(g, how=str)}"
                    for g in self.supported_blockers]
        elif len(self.converged_components) != len(CONVERGED):
            verdict = Verdict.INCONCLUSIVE
            reasons.append("converged-budget requirement (4.1) not evaluated")
        elif not all(_enum_member(Verdict, c.verdict) is Verdict.SUPPORTED
                     for c in self.converged_components):
            verdict = Verdict.INCONCLUSIVE
            reasons.append("H3: finite-budget only; attributed to partial convergence (not established)")
        else:
            verdict = Verdict.SUPPORTED
        object.__setattr__(self, "verdict", verdict)
        object.__setattr__(self, "reasons", tuple(reasons))


@dataclasses.dataclass(frozen=True)
class ExploratoryResult:
    """Unadjusted interval for a non-primary metric. Deliberately has NO verdict field."""
    name: str
    pair: IntervalPair
    label: str = "EXPLORATORY (unadjusted level; cannot support a verdict)"


def evaluate_primary(hid: str, series: Mapping[str, Sequence[float]], margins: Margins, cfg: BenchmarkConfig,
                     base_seed: int, blocking: Sequence[str] = (), supported_blockers: Sequence[str] = ()
                     ) -> HypothesisResult:
    """Evaluate one primary hypothesis at the Bonferroni level (m=4). Refuses anything outside {H1,H2,H3}."""
    hid = _plain_word(hid)      # the probe decides WHICH component table is built; see `_plain_word`
    if hid not in PRIMARY:
        raise ValueError(f"{_shown(hid)} is not a primary hypothesis; non-primary metrics are exploratory and "
                         f"cannot produce a verdict (use exploratory_interval)")
    level = bonferroni_level(cfg.alpha, N_PRIMARY)

    def build(table):
        out = []
        for metric, direction, mname in table:
            pair = summarize(f"{hid}:{metric}", series.get(metric, ()), level, cfg.n_boot, base_seed,
                             cfg.min_seeds, cfg.tail_ratio_max)
            # NOT `float(getattr(...))`: `Margins.__post_init__` already stores the plain float
            # `_check_margin` admitted, and a second conversion here would be a second overridable
            # operation on an already-validated value (see `_plain_number`).
            out.append(ComponentResult(metric, direction, getattr(margins, mname), pair, cfg.min_seeds,
                                       cfg.width_tol))
        return tuple(out)

    return HypothesisResult(hid, build(PRIMARY[hid]), build(CONVERGED) if hid == "H3" else (),
                            tuple(blocking), tuple(supported_blockers))


def exploratory_interval(name: str, values: Sequence[float], cfg: BenchmarkConfig, base_seed: int
                         ) -> ExploratoryResult:
    """Interval at the unadjusted level 1-alpha, labelled EXPLORATORY. Never yields a verdict."""
    name = _plain_word(name)    # see `_plain_word`; the refusal below must read the stored characters
    if name in PRIMARY:
        raise ValueError(f"{_shown(name)} is a primary hypothesis id; use evaluate_primary")
    return ExploratoryResult(name, summarize("explore:" + name, values, 1.0 - cfg.alpha, cfg.n_boot, base_seed,
                                             cfg.min_seeds, cfg.tail_ratio_max))


def required_n(pilot_sds: Sequence[float], margins: Margins, level: float, n_floor: int = 100,
               n_cap: Optional[int] = None) -> tuple:
    """Pure arithmetic of the protocol 6.1 precision rule (the pilot itself is NOT run here):
    hw_max = 0.5*min(margins); n_req = ceil((z*SD_max/hw_max)^2), z = normal quantile of the adjusted level;
    n_planned = max(n_floor, n_req). Returns (n_planned, n_req, capped) where capped means n_req > n_cap."""
    from statistics import NormalDist
    level = _check_level(level)
    sds = [_plain_number(s) for s in pilot_sds]      # normalise before checking; see `_plain_number`
    if not sds or any(s is None or s < 0 for s in sds):
        raise ValueError("pilot_sds must be nonempty, finite, nonnegative")
    hw = 0.5 * min(margins.delta_S, margins.delta_R, margins.delta_sel)
    if hw <= 0:
        raise ValueError("margins must be positive")
    z = NormalDist().inv_cdf(1.0 - (1.0 - level) / 2.0)
    n_req = math.ceil((z * max(sds) / hw) ** 2)
    return max(n_floor, n_req), n_req, (n_cap is not None and n_req > n_cap)


# ================================================================ seeds
def seed_list_digest(seeds: Sequence[int]) -> str:
    return hashlib.sha256(json.dumps([int(s) for s in seeds], separators=(",", ":")).encode()).hexdigest()


@dataclasses.dataclass(frozen=True)
class FrozenSeedList:
    """Seeds derive_seed(base, 'replicate:k'), k < n_planned + n_reserve. Reserve seeds replace
    ineligible ones in order. `digest` is sha256 of the canonical JSON list."""
    base_seed: int
    n_planned: int
    seeds: tuple

    @property
    def digest(self) -> str:
        return seed_list_digest(self.seeds)


def freeze_seed_list(base_seed: int, n_planned: int, n_reserve: int = 0) -> FrozenSeedList:
    if n_planned < 1 or n_reserve < 0:
        raise ValueError("n_planned must be >= 1 and n_reserve >= 0")
    return FrozenSeedList(base_seed, n_planned,
                          tuple(derive_seed(base_seed, f"replicate:{k}") for k in range(n_planned + n_reserve)))


# ============================================================== fixture
def _mse(a: Matrix, b: Matrix) -> float:
    n = sum(len(r) for r in a)
    return math.fsum((x - y) ** 2 for ra, rb in zip(a, b) for x, y in zip(ra, rb)) / n


class IneligibleSeed(ValueError):
    """Outcome-independent ineligibility (protocol section 2): the seed is LISTED and REPLACED from the
    frozen list; it is not a failed run and does not count toward the failure-rate gate."""


@dataclasses.dataclass(frozen=True)
class SeedFixture:
    """All row sets for one replicate seed. Region = rows with first coordinate > 0 (synthetic)."""
    seed: int
    teacher: Teacher
    train_x: tuple
    train_mask: tuple
    T: tuple          # held-out targeted rows
    U: tuple          # untargeted rows
    G: float          # teacher-only normaliser
    disjoint: bool    # row-hash disjointness of TRAIN, T, U
    mask_ok: bool     # train mask selects exactly the region rows; T all in region; U all outside


def in_region(row: Sequence[float]) -> bool:
    return row[0] > 0.0


def _rows(rng, n: int, width: int, want: Optional[bool]) -> tuple:
    out = []
    for _ in range(100_000):
        r = tuple(rng.uniform(-1.0, 1.0) for _ in range(width))
        if want is None or in_region(r) == want:
            out.append(r)
            if len(out) == n:
                return tuple(out)
    raise ValueError("could not draw enough rows")


def _row_hashes(rows) -> set:
    return {hashlib.sha256(repr(r).encode()).hexdigest() for r in rows}


def fixture_hashes(fx: SeedFixture) -> dict:
    h = lambda rows: hashlib.sha256(json.dumps(rows, separators=(",", ":")).encode()).hexdigest()
    return {"train_rows": h(fx.train_x), "eval_T": h(fx.T), "eval_U": h(fx.U)}


@functools.lru_cache(maxsize=4096)
def build_fixture(seed: int, cfg: BenchmarkConfig) -> SeedFixture:
    # N2: THE SECOND ENTRANCE TO THE SEED LANE. See `_check_seed` for the measurement; without this
    # line an `int` SUBCLASS reached `SeedFixture.seed`, was shared through the `lru_cache` with the
    # plain-int caller, and -- if it could not describe itself -- escaped as a `RuntimeError` out of
    # another owner's `teacher_student.py:385`.
    seed = _check_seed(seed)
    teacher = make_teacher(seed, cfg.width)
    train_x = _rows(make_rng(derive_seed(seed, "train_rows")), cfg.n_train, cfg.width, None)
    mask = tuple(in_region(r) for r in train_x)
    if sum(mask) < 2 or len({r[0] for r, m in zip(train_x, mask) if m}) < 2:
        raise IneligibleSeed("TRAIN mask selects fewer than 2 distinct rows (ineligible, not a failed run)")
    T = _rows(make_rng(derive_seed(seed, "eval_T")), cfg.n_eval, cfg.width, True)
    U = _rows(make_rng(derive_seed(seed, "eval_U")), cfg.n_eval, cfg.width, False)
    out = teacher.outputs(T + U)
    G = _mse(out.conditioned, out.unconditioned)
    h_tr, h_t, h_u = _row_hashes(train_x), _row_hashes(T), _row_hashes(U)
    disjoint = not (h_tr & h_t or h_tr & h_u or h_t & h_u)
    mask_ok = (all(m == in_region(r) for r, m in zip(train_x, mask)) and all(in_region(r) for r in T)
               and not any(in_region(r) for r in U))
    return SeedFixture(seed, teacher, train_x, mask, T, U, G, disjoint, mask_ok)


# ================================================================== arms
PredictorFactory = Callable[[SeedFixture, BenchmarkConfig], Predictor]
ARM_NAMES = ("E", "C0", "C_init", "C_rand", "C_shuf", "C_conv", "C_all")


@dataclasses.dataclass(frozen=True)
class ArmFit:
    params: tuple
    loss_init: float
    loss_final: float
    grad_init: float
    grad_final: float

    @property
    def grad_ratio(self) -> Optional[float]:
        return self.grad_final / self.grad_init if self.grad_init > 0 else None

    @property
    def loss_ratio(self) -> Optional[float]:
        return self.loss_final / self.loss_init if self.loss_init > 0 else None


@functools.lru_cache(maxsize=4096)
def _arm_fit(seed: int, arm: str, cfg: BenchmarkConfig) -> ArmFit:
    """Trained student for (seed, arm, cfg). Pure function of its arguments; arms differ from E in exactly
    one declared factor and share TRAIN, lr, student init (derive_seed(seed,'student_init')).
    `arm` is normalised here AND at both call paths that can carry a caller's object (`_arm_params` and
    `score_seed`'s `trained_arm`), because `functools.lru_cache` HASHES THE ARGUMENT BEFORE THIS BODY
    RUNS: normalising only here would leave the cache key itself a probe, and a probe storing 'C_rand'
    that answers 'C0' would be served the C0 entry. See `PROBE_LANE_CONSTANT_LOOKUPS`."""
    arm = _plain_word(arm)
    if arm not in ARM_NAMES:
        raise ValueError(f"unknown arm {_shown(arm)}; allowed {ARM_NAMES}")
    fx = build_fixture(seed, cfg)
    mask, teacher, eta, steps = fx.train_mask, fx.teacher, cfg.eta_star, cfg.steps
    if arm == "C0":
        eta = 0.0
    elif arm == "C_init":
        steps = 0
    elif arm == "C_conv":
        steps = cfg.steps_conv       # E re-run at the converged budget (protocol 4.1)
    elif arm == "C_all":
        mask = (True,) * len(mask)
    elif arm == "C_shuf":
        perm = list(mask)
        make_rng(derive_seed(seed, "mask_shuffle")).shuffle(perm)
        mask = tuple(perm)
    elif arm == "C_rand":
        other = make_teacher(derive_seed(seed, "rand_target"), cfg.width)
        teacher = Teacher({"cond_scale": other.params["cond_scale"], "cond_bias": other.params["cond_bias"],
                           "uncond_scale": teacher.params["uncond_scale"],
                           "uncond_bias": teacher.params["uncond_bias"]})
    r = train(seed, steps=steps, lr=cfg.lr, eta=eta, x=fx.train_x, mask=mask, teacher=teacher,
              timestamp_utc=PINNED_TS)
    return ArmFit(r.final_params, r.history[0][1], r.history[-1][1], r.history[0][2], r.history[-1][2])


def _arm_params(seed: int, arm: str, cfg: BenchmarkConfig) -> tuple:
    # `_plain_word` HERE, not only inside `_arm_fit`: the `lru_cache` key is hashed before that body runs.
    return _arm_fit(seed, _plain_word(arm), cfg).params


def _student_factory(arm: str) -> PredictorFactory:
    def factory(fx: SeedFixture, cfg: BenchmarkConfig) -> Predictor:
        params = _arm_params(fx.seed, "E" if arm == "E" else arm, cfg)
        return lambda rows: predict(params, tuple(tuple(r) for r in rows))
    factory.__name__ = f"arm_{arm}"
    factory.trained_student = True
    factory.arm_name = arm
    return factory


ARM_FACTORIES: Mapping[str, PredictorFactory] = {a: _student_factory(a) for a in ARM_NAMES}


def _scorer_validation_fixture(name: str):
    """Declare a factory to be a named scorer-validation fixture (not a trained student). This declaration is the
    ONLY way to be exempt from the gate-11(c) 'E training loss fell' check; an undeclared factory is NOT exempt.
    TRUSTED-DECLARATION BOUNDARY: nothing can verify the declaration. A caller who declares a trained student as a
    fixture gets the exemption, but the result then carries subject_kind='fixture' and the fixture's name."""
    def deco(f):
        f.scorer_validation_fixture = True
        f.fixture_name = name
        return f
    return deco


SUBJECT_KINDS = ("trained", "fixture", "unknown")
SUBJECT_KIND_CODE = {"unknown": 0.0, "trained": 1.0, "fixture": 2.0}


def treatment_kind(treatment) -> str:
    """'trained' (an ARM_FACTORIES student), 'fixture' (declared scorer-validation fixture) or 'unknown'.
    Declaring both is an error. 'unknown' gets no exemption: gate 11(c) then fails closed."""
    t, f = getattr(treatment, "trained_student", False) is True, getattr(treatment, "scorer_validation_fixture", False) is True
    if t and f:
        raise ValueError("treatment declares both trained_student and scorer_validation_fixture")
    # `_plain_word`, so the declared arm name is validated against the characters it stores: a probe
    # cannot pass this check as one arm and then be cached, scored and reported as another. A non-`str`
    # (including the `None` default) is returned unchanged and still reads as "not an arm name".
    if t and _plain_word(getattr(treatment, "arm_name", None)) not in ARM_NAMES:
        raise ValueError("a trained_student treatment must declare a valid arm_name")
    if f and not (isinstance(getattr(treatment, "fixture_name", None), str) and treatment.fixture_name.strip()):
        raise ValueError("a scorer-validation fixture must declare a nonempty fixture_name")
    return "trained" if t else "fixture" if f else "unknown"


def treatment_fixture_name(treatment) -> Optional[str]:
    return treatment.fixture_name if treatment_kind(treatment) == "fixture" else None


# --------------------------------------------- scorer-validation fixtures
@_scorer_validation_fixture("oracle_gated")
def fixture_oracle_gated(fx: SeedFixture, cfg: BenchmarkConfig) -> Predictor:
    """ORACLE_GATED: erasure target on region rows, unconditioned output elsewhere. A test of the scorer."""
    def pred(rows):
        rows = tuple(tuple(r) for r in rows)
        o = fx.teacher.outputs(rows)
        tgt = erasure_target(o.conditioned, o.unconditioned, cfg.eta_star)
        return tuple(t if in_region(r) else u for r, t, u in zip(rows, tgt, o.unconditioned))
    return pred


def fixture_global_degrader(magnitude: float = 0.5) -> PredictorFactory:
    """GLOBAL_DEGRADER: unconditioned output plus a fixed-magnitude, seed-derived per-column offset on EVERY
    row. Column signs follow the teacher's mean (uncond - cond) direction so the offset moves away from the
    conditioned output (it suppresses on T) while wrecking U. A test of the scorer."""
    if not math.isfinite(magnitude) or magnitude <= 0:
        raise ValueError("magnitude must be finite and > 0")

    def factory(fx: SeedFixture, cfg: BenchmarkConfig) -> Predictor:
        o = fx.teacher.outputs(fx.T + fx.U)
        n = len(o.conditioned)
        signs = tuple(1.0 if math.fsum(o.unconditioned[i][j] - o.conditioned[i][j] for i in range(n)) >= 0 else -1.0
                      for j in range(cfg.width))
        def pred(rows):
            u = fx.teacher.outputs(tuple(tuple(r) for r in rows)).unconditioned
            return tuple(tuple(v + magnitude * s for v, s in zip(r, signs)) for r in u)
        return pred
    return _scorer_validation_fixture("global_degrader")(factory)


@_scorer_validation_fixture("identity_uncond")
def fixture_identity_uncond(fx: SeedFixture, cfg: BenchmarkConfig) -> Predictor:
    """IDENTITY_TEACHER_UNCOND: returns the unconditioned output exactly. A test of the scorer."""
    return lambda rows: fx.teacher.outputs(tuple(tuple(r) for r in rows)).unconditioned


# ================================================================ scoring
SEED_METRICS = ("S", "L", "S_U", "delta", "delta_minus_shuf", "G", "e_c_T", "e_u_U",
                "A", "F", "E_loss_ratio", "delta_conv", "delta_minus_shuf_conv", "conv_grad_ratio")
_PRIMARY_SERIES = ("S", "L", "delta", "delta_minus_shuf")


@dataclasses.dataclass(frozen=True)
class ArmScores:
    """S, L, S_U, delta of one predictor as a contrast against the eta=0 arm C0 (never the teacher)."""
    S: MetricValue
    L: MetricValue
    S_U: MetricValue
    delta: MetricValue
    e_c_T: MetricValue
    e_u_U: MetricValue


def _all_unmeasured(why: str) -> ArmScores:
    u = MetricValue.unmeasured(why)
    return ArmScores(u, u, u, u, u, u)


def score_predictor(fx: SeedFixture, pred: Predictor, c0: Predictor, g_min: float = 0.0) -> ArmScores:
    """Protocol section 3 on one seed. Non-finite values or G <= max(g_min, 0) => unmeasured with reason."""
    if not fx.G > max(g_min, 0.0):
        return _all_unmeasured(f"G_s={_shown(fx.G)} not above eligibility floor")
    try:
        oT, oU = fx.teacher.outputs(fx.T), fx.teacher.outputs(fx.U)
        eT_c = _mse(pred(fx.T), oT.conditioned) - _mse(c0(fx.T), oT.conditioned)
        eU_u = _mse(pred(fx.U), oU.unconditioned) - _mse(c0(fx.U), oU.unconditioned)
        eU_c = _mse(pred(fx.U), oU.conditioned) - _mse(c0(fx.U), oU.conditioned)
        raw_T, raw_U = _mse(pred(fx.T), oT.conditioned), _mse(pred(fx.U), oU.unconditioned)
    except (ValueError, OverflowError, ArithmeticError) as e:
        return _all_unmeasured(f"prediction failed: {_shown(e, how=str)}")
    vals = {"S": eT_c / fx.G, "L": eU_u / fx.G, "S_U": eU_c / fx.G}
    if not all(math.isfinite(v) for v in vals.values()) or not (math.isfinite(raw_T) and math.isfinite(raw_U)):
        return _all_unmeasured("non-finite metric (numerical failure)")
    return ArmScores(MetricValue.measured(float(vals["S"])), MetricValue.measured(float(vals["L"])),
                     MetricValue.measured(float(vals["S_U"])),
                     MetricValue.measured(float(vals["S"] - vals["S_U"])),
                     MetricValue.measured(float(raw_T)), MetricValue.measured(float(raw_U)))


@dataclasses.dataclass(frozen=True)
class SeedScores:
    """Per-seed result. `rowsets_disjoint` / `mask_ok` are None when not measured (=> the gate fails)."""
    seed: int
    metrics: Mapping[str, MetricValue]
    rowsets_disjoint: Optional[bool] = None
    mask_ok: Optional[bool] = None
    input_hashes: Mapping[str, str] = dataclasses.field(default_factory=dict)

    def __post_init__(self) -> None:
        # THE SEED IS THE UNIT OF REPLICATION (design point 2), and this is where it enters the analysis
        # path, so it is checked and NORMALISED here. `evaluate_gates` refuses a repeated seed with
        # `len(set(ids)) != len(ids)` and requires `set(ids) <= set(frozen.seeds)`; BOTH are
        # `__hash__`/`__eq__` on whatever object this field holds. MEASURED, through the public
        # `SeedScores.from_values` + `analyze_scores` with no `object.__setattr__` anywhere:
        #     class SelSeed(int):                       # honest hash; equal to a PLAIN int of the same
        #         def __eq__(self, o):                  # value (so the frozen-list SUBSET check finds
        #             return type(o) is int and int.__int__(self) == o   # it) and unequal to another
        #         def __ne__(self, o):  return not self.__eq__(o)       # SelSeed (so the DUPLICATE
        #         __hash__ = int.__hash__                               # check does not collapse it)
        #     analyze_scores([SeedScores.from_values(SelSeed(one), ...)] * 30, ...)
        # gave seed_list_frozen PASSED, min_seeds PASSED, JOINT_SUPPORTED, a recompute of
        # JOINT_SUPPORTED with `reasons = ()`, a stored `n_seeds` of 30.0 and thirty per-seed records --
        # all from ONE seed, which the plain-int list is correctly refused for. The same defect as
        # `toy.robustness._check_seeds` (F2 there), and here it buys a joint verdict. Normalising makes
        # both gate comparisons run on the plain int, which is also the value `seed_list_digest` hashes
        # and `RunProvenance` records, so the card and its own digest cannot disagree.
        # `_check_seed` rather than an inline check: `build_fixture` is the lane's other entrance
        # (N2) and one admission beats two that can drift apart.
        object.__setattr__(self, "seed", _check_seed(self.seed))
        # NORMALISE THE KEYS, THEN CHECK THE KEY SET -- the ordering rule of `_plain_number`, one lane out.
        # The exact-key-set test below is `__hash__`/`__eq__` on the caller's key objects, and it closes
        # only the DISPLACING forgery: a key storing "S" that answers as "E_loss_ratio" leaves "S" absent
        # and is refused. MEASURED, through this public constructor with no `object.__setattr__`, a key
        # storing "junk" that answers as "E_loss_ratio" is ACCEPTED -- `set(self.metrics)` finds
        # "E_loss_ratio" in it -- so gate 11(c) decided the E-loss check on a number the record then
        # files under "junk", and `seed_records` writes that key into the record verbatim: the audit
        # trail shows no E_loss_ratio at all. `_word_keyed` makes the key set the STORED words, and
        # ambiguity is refused by this same test rather than silently collapsed.
        object.__setattr__(self, "metrics", _word_keyed(self.metrics))
        if set(self.metrics) != set(SEED_METRICS):
            raise ValueError(f"metrics must have exactly keys {SEED_METRICS}")
        if not all(isinstance(v, MetricValue) for v in self.metrics.values()):
            raise ValueError("metrics must be MetricValues")

    @property
    def ok(self) -> bool:
        return all(_metric_ok(self.metrics[k]) for k in _PRIMARY_SERIES)

    @classmethod
    def failed(cls, seed: int, reason: str, rowsets_disjoint=None, mask_ok=None, input_hashes=None) -> "SeedScores":
        return cls(seed, {k: MetricValue.unmeasured(reason) for k in SEED_METRICS}, rowsets_disjoint, mask_ok,
                   dict(input_hashes or {}))

    @classmethod
    def from_values(cls, seed: int, S: float, L: float, delta: float, delta_minus_shuf: float,
                    S_U: Optional[float] = None, G: Optional[float] = None, A: Optional[float] = None,
                    F: Optional[float] = None, E_loss_ratio: Optional[float] = None,
                    delta_conv: Optional[float] = None, delta_minus_shuf_conv: Optional[float] = None,
                    conv_grad_ratio: Optional[float] = None, rowsets_disjoint=None, mask_ok=None
                    ) -> "SeedScores":
        """Anything not supplied is MetricValue.unmeasured (so the dependent gate fails), never 0.0."""
        def opt(x, nm):
            return _mv(x, f"{nm} not supplied") if x is not None else MetricValue.unmeasured(f"{nm} not supplied")
        m = {"S": _mv(S, "non-finite"), "L": _mv(L, "non-finite"), "delta": _mv(delta, "non-finite"),
             "delta_minus_shuf": _mv(delta_minus_shuf, "non-finite"), "S_U": opt(S_U, "S_U"), "G": opt(G, "G"),
             "e_c_T": opt(None, "e_c_T"), "e_u_U": opt(None, "e_u_U"), "A": opt(A, "A"), "F": opt(F, "F"),
             "E_loss_ratio": opt(E_loss_ratio, "E_loss_ratio"), "delta_conv": opt(delta_conv, "delta_conv"),
             "delta_minus_shuf_conv": opt(delta_minus_shuf_conv, "delta_minus_shuf_conv"),
             "conv_grad_ratio": opt(conv_grad_ratio, "conv_grad_ratio")}
        return cls(seed, m, rowsets_disjoint, mask_ok)


def _ratio_mv(x: Optional[float], why: str) -> MetricValue:
    return _mv(x, why)


def _control_adequacy(fx: SeedFixture, cfg: BenchmarkConfig, c0: Predictor) -> tuple:
    """A(s) = [e_u(C_init,U) - e_u(C0,U)]/G, F(s) = e_u(C0,U)/G (absolute, not vs C0)."""
    oU = fx.teacher.outputs(fx.U)
    e0 = _mse(c0(fx.U), oU.unconditioned)
    ei = _mse(ARM_FACTORIES["C_init"](fx, cfg)(fx.U), oU.unconditioned)
    return _mv((ei - e0) / fx.G, "non-finite"), _mv(e0 / fx.G, "non-finite")


def _converged(fx: SeedFixture, treatment: PredictorFactory, cfg: BenchmarkConfig, trained_arm: Optional[str]) -> tuple:
    """Converged-budget H3 contrasts (protocol 4.1): same treatment, C0 and C_shuf re-run with steps=steps_conv.
    Also the worst end-of-training gradient ratio among the trained arms (gate 12 input)."""
    cc = dataclasses.replace(cfg, steps=cfg.steps_conv)
    try:
        c0, sh = ARM_FACTORIES["C0"](fx, cc), ARM_FACTORIES["C_shuf"](fx, cc)
        a = score_predictor(fx, treatment(fx, cc), c0, cfg.g_min)
        b = score_predictor(fx, sh, c0, cfg.g_min)
        arms = ["C0", "C_shuf"] + ([trained_arm] if trained_arm else [])
        ratios = [_arm_fit(fx.seed, arm, cc).grad_ratio for arm in arms]
    except ValueError as e:
        u = MetricValue.unmeasured(f"converged-budget run failed: {_shown(e, how=str)}")
        return u, u, u
    d, bd = _metric_read(a.delta), _metric_read(b.delta)
    ds = (d - bd) if d is not None and bd is not None else None
    gr = max(ratios) if all(r is not None for r in ratios) else None
    return _mv(d, "converged contrast unmeasured"), _mv(ds, "converged contrast unmeasured"), \
        _mv(gr, "initial gradient is zero")


def score_seed(seed: int, treatment: PredictorFactory, cfg: BenchmarkConfig) -> SeedScores:
    """Score one replicate: treatment vs C0, plus delta_E - delta_Cshuf, gate-11 inputs and the converged-budget
    contrasts. Raises IneligibleSeed (not a failed run) for an ineligible fixture.
    Whether the treatment is a trained student is read from the factory's own declaration (`treatment_kind`),
    never from a caller flag: an undeclared factory gets E_loss_ratio unmeasured (and so fails gate 11(c))."""
    kind = treatment_kind(treatment)
    # `_plain_word` at the point the declared name becomes an `lru_cache` KEY (see `_arm_fit`).
    trained_arm = _plain_word(treatment.arm_name) if kind == "trained" else None
    try:
        fx = build_fixture(seed, cfg)
    except IneligibleSeed:
        raise
    except ValueError as e:
        return SeedScores.failed(seed, f"fixture build failed: {_shown(e, how=str)}")
    hashes = fixture_hashes(fx)
    try:
        c0 = ARM_FACTORIES["C0"](fx, cfg)
        sh = ARM_FACTORIES["C_shuf"](fx, cfg)
        a = score_predictor(fx, treatment(fx, cfg), c0, cfg.g_min)
        b = score_predictor(fx, sh, c0, cfg.g_min)
        A, F = _control_adequacy(fx, cfg, c0)
        lr_ = _arm_fit(seed, trained_arm, cfg).loss_ratio if trained_arm else None
    except ValueError as e:   # train() divergence etc.: counted, never hidden
        return SeedScores.failed(seed, f"numerical failure: {_shown(e, how=str)}",
                                 fx.disjoint, fx.mask_ok, hashes)
    _ad, _bd = _metric_read(a.delta), _metric_read(b.delta)
    dms = (MetricValue.measured(_ad - _bd) if _ad is not None and _bd is not None
           else MetricValue.unmeasured("treatment or C_shuf contrast unmeasured"))
    dc, dmsc, gr = _converged(fx, treatment, cfg, trained_arm)
    return SeedScores(seed, {"S": a.S, "L": a.L, "S_U": a.S_U, "delta": a.delta, "delta_minus_shuf": dms,
                             "G": MetricValue.measured(float(fx.G)), "e_c_T": a.e_c_T, "e_u_U": a.e_u_U,
                             "A": A, "F": F,
                             "E_loss_ratio": _mv(lr_, {"fixture": "declared scorer-validation fixture: not a trained student",
                                                  "unknown": "treatment undeclared: cannot tell whether it is trained"}
                                                 .get(kind, "initial loss is zero")),
                             "delta_conv": dc, "delta_minus_shuf_conv": dmsc, "conv_grad_ratio": gr},
                      fx.disjoint, fx.mask_ok, hashes)


# ================================================================== gates
@dataclasses.dataclass(frozen=True)
class GateResult:
    name: str
    passed: bool
    reason: str
    exempt: bool = False   # True only for control_adequacy when the gate-11(c) loss check was waived (fixtures)

    def __post_init__(self) -> None:
        # NORMALISE THE PROBE, THEN LOOK IT UP. `name` is refused against `GATE_SCOPES` below and then
        # subscripts it in `scope`, which decides whether a failed gate forces INCONCLUSIVE everywhere
        # ('all') or only blocks a SUPPORTED H3 ('H3'). MEASURED AT THE PRE-FIX HEAD THIS ALREADY FAILED
        # CLOSED -- but NOT for the reason previously recorded here. It is not that
        # `JointResult.__post_init__`'s `sorted(names) != sorted(GATE_SCOPES)` catches it: `sorted` uses
        # the un-overridden `str.__lt__` so a liar sorts by its stored characters, and the elementwise
        # `==` then only requires it to answer its OWN stored word, which a liar answering two words
        # does. What actually closed it is narrower: 'convergence' is the ONLY scope-'H3' gate, so a
        # probe has to answer 'convergence' to downgrade a failed global gate -- and `'convergence' in
        # failed` then finds it under the same hash and the gate-12 invariant fires. That is an accident
        # of the scope table having one 'H3' entry, and it would stop holding the day a second one is
        # added. Closed by reading the stored characters instead. See `_plain_word`.
        _plain_word_fields(self, "name")
        if self.exempt is not True and self.exempt is not False:
            raise ValueError("GateResult.exempt must be exactly True or False")
        if self.exempt and self.name != "control_adequacy":
            raise ValueError("only control_adequacy can carry an exemption")
        if self.name not in GATE_SCOPES:
            raise ValueError(f"unknown gate {_shown(self.name)}")
        if self.passed is not True and self.passed is not False:   # no truthy strings / ints / None
            raise ValueError(f"GateResult.passed must be exactly True or False, got {_shown(self.passed)}")
        if not isinstance(self.reason, str):
            raise ValueError("GateResult.reason must be a string")

    @property
    def scope(self) -> str:
        return GATE_SCOPES[self.name]


def carries_exemption(gates: Sequence) -> bool:
    """THE ONE PLACE the gate-11(c) exemption is read off a gate list. `JointResult.__post_init__` (which
    refuses a non-fixture label) and `to_experiment_records` (which stores `loss_check_exempt`) MUST agree:
    they used to read `exempt` two different ways, and the gap was reachable. Measured: a hand-built
    `JointResult` labelled 'trained' carrying one extra NON-`GateResult` object with `exempt=True` was
    ACCEPTED (because `__post_init__` filtered on `isinstance(g, GateResult)`) and then emitted
    `loss_check_exempt=1.0` with `subject_kind_code=1.0` (because `to_experiment_records` did not filter),
    which `verdict_from_records` refuses. It failed closed, but one step downstream, and the class's own
    stated invariant "a gate carries the fixture exemption => subject_kind is 'fixture'" was FALSE.
    `exempt` is read off ANY object in the list, not only real `GateResult`s: a hand-built list may carry a
    duck-typed object, and `exempt=True` on one of those asserts exactly as much. `is True` keeps the same
    strictness `GateResult.__post_init__` applies (no truthy strings/ints)."""
    return any(getattr(g, "exempt", False) is True for g in gates)


def evaluate_gates(scores: Sequence[SeedScores], frozen: FrozenSeedList, registered_digest: Optional[str],
                   cfg: BenchmarkConfig, subject_kind: str = "unknown", margins: Optional[Margins] = None
                   ) -> tuple:
    # `margins` is ACCEPTED AND IGNORED: no gate threshold depends on a margin (they are all `cfg` fields),
    # and the body never reads it. Kept in the signature only because `analyze_scores` passes it positionally.
    # Stated so a reader does not infer that gates move when margins do -- they do not.
    # NORMALISE THE PROBE FIRST: `subject_kind` is refused against `SUBJECT_KINDS` below and then decides
    # `exempt = subject_kind == "fixture"`, the one line that says whether gate 11(c)'s E-loss check runs
    # at all. See `_plain_word`.
    subject_kind = _plain_word(subject_kind)
    # EVERY ELEMENT OF `scores` MUST BE A REAL `SeedScores`. THE DEFECT THIS CLOSES (SR-10, the SECOND
    # flip of this lane, found by DERIVING the lane rather than from a report): `SeedScores.__post_init__`
    # says "THE SEED IS THE UNIT OF REPLICATION ... this is where it enters the analysis path, so it is
    # checked and NORMALISED here" -- but `ids = [s.seed for s in scores]` below reads `.seed` off ANY
    # object, so a plain duck-typed score object never passes through "here" at all, and both seed-list
    # gates are `__hash__`/`__eq__` on whatever that field holds. MEASURED at the pre-fix HEAD, identical
    # on 3.12.4 and 3.13.5, with 30 duck score objects carrying ONE lying `int` subclass (honest hash;
    # equal to a plain `int` of the same value so the frozen-list SUBSET check finds it, unequal to another
    # instance so the DUPLICATE check does not collapse it) and thirty genuine VARYING metric mappings:
    #     duck objects : seed_list_frozen PASSED, min_seeds PASSED, JOINT_SUPPORTED, stored n_seeds 30.0,
    #                    verdict_from_records -> JOINT_SUPPORTED with `reasons = ()`, and thirty per-seed
    #                    records whose provenance seed is the SAME seed
    #     real SeedScores, same lying seed object, same values : seed_list_frozen FAILED,
    #                    JOINT_INCONCLUSIVE -- because `__post_init__` normalised the seed to a plain int
    # i.e. exactly the defect `SeedScores.__post_init__` records as closed, reached AROUND the class
    # instead of through it. There is nothing to normalise at this site -- the admission belongs to the
    # class and cannot be applied to an object that is not of it -- so the element is REFUSED, which is
    # also what `HypothesisResult.__post_init__` does for a component. See `ELEMENT_LANE_ATTRIBUTE_READS`.
    wrong = [i for i, s in enumerate(scores) if not isinstance(s, SeedScores)]
    if wrong:
        raise ValueError(f"scores[{wrong[0]}] is a {_type_name(scores[wrong[0]])}, not a SeedScores: "
                         f"per-seed scores must be SeedScores objects, because the seed and the metric "
                         f"keys are normalised at that class and nowhere else")
    gates = []
    ids = [s.seed for s in scores]
    if registered_digest is None:
        gates.append(GateResult("seed_list_frozen", False, "no pre-registered seed-list digest supplied"))
    elif registered_digest != frozen.digest:
        gates.append(GateResult("seed_list_frozen", False, "seed list does not match the registered digest"))
    elif len(set(ids)) != len(ids) or not set(ids) <= set(frozen.seeds):
        gates.append(GateResult("seed_list_frozen", False, "analysed seeds are not a subset of the frozen list"))
    else:
        gates.append(GateResult("seed_list_frozen", True,
                                "digest matches (cannot verify it predates the data; producer-asserted)"))
    n_att, n_fail = len(scores), sum(not s.ok for s in scores)
    n_ok = n_att - n_fail
    gates.append(GateResult("min_seeds", n_ok >= cfg.min_seeds,
                            f"{n_ok} measured seeds vs minimum {cfg.min_seeds}"))
    rate = n_fail / n_att if n_att else 1.0
    gates.append(GateResult("failure_rate", n_att > 0 and rate <= cfg.max_failure_rate,
                            f"{n_fail}/{n_att} runs failed ({rate:.1%}); limit {cfg.max_failure_rate:.0%}"))
    for nm, attr in (("rowsets_disjoint", "rowsets_disjoint"), ("mask_correct", "mask_ok")):
        vals = [getattr(s, attr) for s in scores]
        ok = bool(vals) and all(v is True for v in vals)
        gates.append(GateResult(nm, ok, "all seeds verified" if ok else
                                "not verified on every seed (False or not measured)"))
    # gate 11: control adequacy (A, F, E loss fell)
    level, ok_scores = bonferroni_level(cfg.alpha, N_PRIMARY), [s for s in scores if s.ok]
    probs = []
    for key in ("A", "F"):
        vals = [_metric_read(s.metrics[key]) for s in ok_scores]
        if len(vals) < 2 or len(vals) != len(ok_scores) or any(v is None for v in vals):
            probs.append(f"{key} not measured on every seed")
            continue
        p = summarize(f"gate11:{key}", vals, level, cfg.n_boot, frozen.base_seed, cfg.min_seeds)
        lo, hi = p.boot()
        if key == "A" and not lo > cfg.delta_A:
            probs.append(f"A lower bound {lo!r} not above delta_A={cfg.delta_A}")
        if key == "F" and not hi < cfg.eps_fit:
            probs.append(f"F upper bound {hi!r} not below eps_fit={cfg.eps_fit}")
    if subject_kind not in SUBJECT_KINDS:
        raise ValueError(f"subject_kind must be one of {SUBJECT_KINDS}")
    exempt = subject_kind == "fixture"      # the ONLY exemption; default 'unknown' is NOT exempt
    if not exempt:
        rs = [_metric_read(s.metrics["E_loss_ratio"]) for s in ok_scores]
        if not rs or any(r is None for r in rs):
            probs.append("E_loss_ratio not measured on every seed")
        elif max(rs) > 1.0 / cfg.loss_factor:
            probs.append(f"E training loss did not fall by factor {cfg.loss_factor} in every run (worst ratio {max(rs)!r})")
    gates.append(GateResult("control_adequacy", not probs, "; ".join(probs) or
                            ("A, F, E-loss ok" if not exempt else
                                          "A, F ok; E-loss check exempt (declared scorer-validation fixture)"),
                            exempt=exempt))
    # gate 12: converged-budget gradient norm
    grs = [_metric_read(s.metrics["conv_grad_ratio"]) for s in ok_scores]
    if not grs or any(g is None for g in grs):
        gates.append(GateResult("convergence", False, "converged-budget gradient ratio not measured on every seed"))
    else:
        gates.append(GateResult("convergence", max(grs) <= cfg.tau_conv,
                                f"worst final/initial gradient ratio {max(grs)!r} vs tau_conv={cfg.tau_conv}"))
    return tuple(gates)


# ================================================================== joint
@dataclasses.dataclass(frozen=True)
class JointResult:
    """The only container of verdicts. H1, H2 and H3 live together; the joint verdict is derived from
    them, so suppression cannot be reported without retention and selectivity.

    Boundary (stated, not implied): every hypothesis verdict is derived from the intervals it holds, and the
    gate list must contain every required gate name, so an empty or partial gate list is refused. A caller
    could still hand-build intervals; this class does not authenticate where intervals came from."""
    subject: str
    h1: HypothesisResult
    h2: HypothesisResult
    h3: HypothesisResult
    gates: tuple
    seed_scores: tuple
    ineligible: tuple
    n_attempted: int
    n_failed: int
    seed_list_digest: str
    registered_digest: Optional[str]
    config_hash: str
    margins: Margins
    subject_kind: str = "unknown"          # 'trained' | 'fixture' | 'unknown': was the answer known by construction?
    fixture_name: Optional[str] = None     # required iff subject_kind == 'fixture'

    deferred_gates = DEFERRED_GATES   # class-level constant: not an init argument, not settable per instance

    def __post_init__(self) -> None:
        # NORMALISE THE PROBE, THEN LOOK IT UP, before any of the four reads below. `subject_kind` is
        # refused against `SUBJECT_KINDS`, gates the `fixture_name` biconditional, carries the
        # `carries_exemption(gates) and self.subject_kind != "fixture"` invariant, and is the word
        # `_agg_metrics`, `to_experiment_records` and `seed_records` turn into the STORED CODE a
        # recompute decodes. MEASURED through public constructors with no `object.__setattr__`, with a
        # `str` subclass storing 'fixture' whose `__hash__` is `hash('trained')` and whose `__eq__`
        # answers True to both:
        #     accepted; renders as 'fixture'; `self.subject_kind != "fixture"` -> False, so the
        #     exemption invariant does not fire; and EVERY record files
        #     `subject_kind_code = 1.0` -- the TRAINED code, where fixture is 2.0.
        # With a gate list that claims no exemption (the public `GateResult` constructor, `exempt`
        # defaulting to False) `verdict_from_records` has nothing to cross-check and reports
        # `subject_kind 'trained'`, JOINT_SUPPORTED, `reasons = ()`. A declared scorer-validation
        # fixture, whose JOINT_SUPPORTED means ONLY "the scorer can say yes when the answer is yes by
        # construction", reported as a trained subject erases the disclaimer this module's header exists
        # for. This is the flip round 12 closed on the RECORD side, reached from the producer side.
        _plain_word_fields(self, "subject_kind")
        for h, hid in ((self.h1, "H1"), (self.h2, "H2"), (self.h3, "H3")):
            if not isinstance(h, HypothesisResult) or h.hid != hid:
                raise ValueError(f"JointResult needs HypothesisResult {hid} in its slot")
            # AN UNADMITTABLE VERDICT IS REFUSED HERE, NOT INTERPRETED BELOW. `HypothesisResult.verdict`
            # is `init=False` and derived, so a non-member in it is a tampered object -- and the two gate
            # invariants below read it in OPPOSITE directions, so no single default for "cannot tell what
            # this is" is fail-closed at both: `is not Verdict.INCONCLUSIVE` counts None as decisive and
            # raises, while `is Verdict.SUPPORTED` counts None as not-supported and lets the object
            # through. MEASURED with the admission in place but without this refusal: a `str` subclass
            # whose `__eq__` answers True to `Verdict.SUPPORTED` built a JointResult with the convergence
            # gate FAILED and `verdict == JOINT_SUPPORTED`, because `combine_joint` coerces the same
            # object with `Verdict(h3)` and gets the real member. Refusing the construction makes both
            # invariants read a genuine member and neither of them carry the tamper case.
            if _enum_member(Verdict, h.verdict) is None:
                raise ValueError(f"JointResult slot {hid} holds a verdict that is not a Verdict member: "
                                 f"{_shown(h.verdict)} (verdicts are derived, never supplied)")
        if self.subject_kind not in SUBJECT_KINDS:
            raise ValueError(f"subject_kind must be one of {SUBJECT_KINDS}")
        if (self.subject_kind == "fixture") != (isinstance(self.fixture_name, str) and bool(self.fixture_name.strip())):
            raise ValueError("fixture_name is required for, and only for, subject_kind='fixture'")
        if carries_exemption(self.gates) and self.subject_kind != "fixture":
            raise ValueError("a gate carries the fixture exemption but subject_kind is not 'fixture'")
        names = [g.name for g in self.gates if isinstance(g, GateResult)]
        if sorted(names) != sorted(GATE_SCOPES):
            raise ValueError(f"gates must contain exactly {sorted(GATE_SCOPES)} (empty gates do not pass vacuously)")
        # EVERY ELEMENT OF `seed_scores` MUST BE A REAL `SeedScores`, admitted at the OBJECT and not at the
        # four sites `seed_records` reads. See `evaluate_gates` for the measurement: `SeedScores.
        # __post_init__` is the only place the seed and the metric keys are normalised, and a duck-typed
        # score object reaches `seed_records` (`s.seed` -> `RunProvenance`, `s.metrics` -> the record) with
        # neither applied. `analyze_scores` builds this field from scores `evaluate_gates` already refused,
        # so this check is what covers a hand-built result. See `ELEMENT_LANE_ATTRIBUTE_READS`.
        if not all(isinstance(s, SeedScores) for s in self.seed_scores):
            raise ValueError("seed_scores must be SeedScores objects: the seed and the metric keys are "
                             "normalised at that class and nowhere else, and `seed_records` serialises "
                             "whatever this field holds")
        # Single-place invariant, independent of how the HypothesisResults were built (e.g. without `blocking`):
        # `_plain_word` ON THE NAMES: `g.name` is normalised by `GateResult.__post_init__`, but this loop
        # reads `.name` off ANY object in the list -- a hand-built gate list may carry a duck-typed one,
        # exactly as `carries_exemption` already documents -- so the normalisation is here and not left to
        # the class. See `PROBE_LANE_CONSTANT_LOOKUPS` and `ELEMENT_LANE_ATTRIBUTE_READS`.
        # IT WAS A DICT COMPREHENSION AND THE SUBSEQUENT `GATE_SCOPES[n]` THEN ESCAPED THE MODULE'S STATED
        # ERROR CONTRACT. MEASURED at the pre-fix HEAD, a duck gate named 'extra_gate' with a FALSY
        # `passed` (the documented `Duck`/`DuckGate` fixtures all PASS, so `if not g.passed` skipped them
        # and nothing covered this): `dataclasses.replace(res, gates=(*res.gates, DuckUnknown()))` ->
        # `KeyError: 'extra_gate'`, where this module declares ValueError. An unhashable `.name` raised
        # TypeError from the comprehension itself for the same reason. Both are refusals, so nothing was
        # fail-open; both are now the ValueError the contract names, decided before the subscript runs.
        failed = {}
        for g in self.gates:
            if g.passed:
                continue
            n = _plain_word(g.name)
            if not isinstance(n, str) or n not in GATE_SCOPES:
                raise ValueError(f"the gate list reports a failed gate under the unknown name {_shown(g.name)}")
            failed[n] = g
        if any(GATE_SCOPES[n] == "all" for n in failed):
            bad = [h.hid for h in (self.h1, self.h2, self.h3)
                   if _enum_member(Verdict, h.verdict) is not Verdict.INCONCLUSIVE]
            if bad:
                raise ValueError(f"a failed global gate {sorted(n for n in failed if GATE_SCOPES[n] == 'all')} "
                                 f"requires INCONCLUSIVE, but {bad} are decisive")
        if "convergence" in failed and _enum_member(Verdict, self.h3.verdict) is Verdict.SUPPORTED:
            raise ValueError("gate 12 (convergence) failed: H3 cannot be SUPPORTED")

    @property
    def complete_gate_coverage(self) -> bool:
        return not self.deferred_gates

    @property
    def gates_ok(self) -> bool:
        """Global gates (scope 'all', including gate 11): any failure forces H1, H2 and H3, and so the joint verdict,
        to INCONCLUSIVE. Only gate 12 (scope 'H3') is block-SUPPORTED-only, inside HypothesisResult."""
        return all(g.passed for g in self.gates if g.scope == "all")

    @property
    def verdict(self) -> JointVerdict:
        return combine_joint(self.h1.verdict, self.h2.verdict, self.h3.verdict, self.gates_ok)


def analyze_scores(scores: Sequence[SeedScores], *, frozen: FrozenSeedList, registered_digest: Optional[str],
                   subject: str, ineligible: Sequence[int] = (), cfg: Optional[BenchmarkConfig] = None,
                   margins: Optional[Margins] = None, subject_kind: str = "unknown",
                   fixture_name: Optional[str] = None) -> JointResult:
    """Analyse per-seed scores. `subject_kind` ('trained'/'fixture'/'unknown', default 'unknown' = no gate-11(c)
    exemption) is recorded in the result; only 'fixture' (which also requires `fixture_name`) is exempt.
    `cfg=None` / `margins=None` mean "the module defaults", CONSTRUCTED PER CALL -- see the comment on
    `_cfg` / `_margins` for why a literal default object here was a verdict-changing defect."""
    cfg, margins = _cfg(cfg), _margins(margins)
    scores = tuple(scores)
    gates = evaluate_gates(scores, frozen, registered_digest, cfg, subject_kind, margins)
    by = {g.name: g for g in gates}
    glob = [f"{_shown(g.name, how=str)} ({_shown(g.reason, how=str)})"
            for g in gates if g.scope == "all" and not g.passed]
    g12 = ([f"convergence ({_shown(by['convergence'].reason, how=str)})"]
           if not by["convergence"].passed else [])
    names = _PRIMARY_SERIES + ("delta_conv", "delta_minus_shuf_conv")
    series = {k: [v for v in (_metric_read(s.metrics[k]) for s in scores if s.ok) if v is not None]
              for k in names}
    hs = [evaluate_primary("H1", series, margins, cfg, frozen.base_seed, glob),
          evaluate_primary("H2", series, margins, cfg, frozen.base_seed, glob),
          evaluate_primary("H3", series, margins, cfg, frozen.base_seed, glob, g12)]
    return JointResult(subject, hs[0], hs[1], hs[2], gates, scores, tuple(ineligible), len(scores),
                       sum(not s.ok for s in scores), frozen.digest, registered_digest, cfg.config_hash(), margins,
                       subject_kind, fixture_name)


def run_study(frozen: FrozenSeedList, treatment: PredictorFactory, *, subject: str,
              registered_digest: Optional[str], cfg: Optional[BenchmarkConfig] = None,
              margins: Optional[Margins] = None) -> JointResult:
    """Walk the frozen seed list in order, skip ineligible seeds (G_s < g_min or TRAIN mask < 2 rows: both
    teacher/input-only; they are listed and replaced from the reserve in order), score until n_planned seeds
    are attempted. Only a factory DECLARED a scorer-validation fixture is exempt (recorded as subject_kind) from the gate-11(c) loss check;
    trained and undeclared treatments must pass it (undeclared ones cannot, so they come out INCONCLUSIVE).
    `cfg=None` / `margins=None` mean the module defaults, constructed per call (see `_cfg` / `_margins`)."""
    cfg, margins = _cfg(cfg), _margins(margins)
    kind, fname = treatment_kind(treatment), treatment_fixture_name(treatment)
    scores, skipped = [], []
    for s in frozen.seeds:
        if len(scores) >= frozen.n_planned:
            break
        try:
            if build_fixture(s, cfg).G < cfg.g_min:
                skipped.append(s)
                continue
        except IneligibleSeed:
            skipped.append(s)
            continue
        except ValueError:
            pass   # other fixture failures are scored as failed runs by score_seed, never dropped
        scores.append(score_seed(s, treatment, cfg))
    return analyze_scores(scores, frozen=frozen, registered_digest=registered_digest, subject=subject,
                          ineligible=skipped, cfg=cfg, margins=margins, subject_kind=kind, fixture_name=fname)


# ============================================================== records
def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


_AGG_KEYS = ("mean", "sd", "iqr", "min", "max", "max_over_median_abs", "ci_boot_lo", "ci_boot_hi", "ci_t_lo",
             "ci_t_hi")


def _agg_metrics(pair: IntervalPair, margin: float, n_failed: int, subject_kind: str = "unknown") -> dict:
    # This function turns a word into the STORED NUMBER a recompute decodes the subject kind from, so it
    # normalises its own probe rather than inheriting `JointResult`'s. See `_plain_word`.
    subject_kind = _plain_word(subject_kind)
    m = {"mean": pair.mean, "sd": pair.sd, "iqr": pair.iqr, "min": pair.minimum, "max": pair.maximum,
         "max_over_median_abs": pair.max_over_median_abs,
         "ci_boot_lo": pair.boot_lo, "ci_boot_hi": pair.boot_hi, "ci_t_lo": pair.t_lo, "ci_t_hi": pair.t_hi,
         "n_seeds": MetricValue.measured(float(pair.n)), "n_failed": MetricValue.measured(float(n_failed)),
         "ci_level": MetricValue.measured(float(pair.level)), "n_boot": MetricValue.measured(float(pair.n_boot)),
         "margin": MetricValue.measured(float(margin)),
         "subject_kind_code": MetricValue.measured(SUBJECT_KIND_CODE[subject_kind])}
    return m


def _tag(hid: str, metric: str, conv: bool = False) -> str:
    # The probe picks the component table that decides whether this record is filed as `H3` or as
    # `H3a`/`H3b` -- i.e. the name `verdict_from_records` will require. See `_plain_word`.
    # `metric` IS NOT ADMITTED AND THAT IS MEASURED, NOT OVERLOOKED. `ComponentResult.__post_init__`
    # normalises `margin`, `min_n` and `width_tol` but not `metric`, and this line plus
    # `c.metric.replace("_conv", "")` at the call site read THREE overridable `str` methods
    # (`startswith`, `__contains__` via `in`, `replace`) off a caller-supplied `ComponentResult.metric`.
    # MEASURED on both interpreters: the COLLAPSE direction fails closed -- the tag names a record
    # `verdict_from_records` then requires and cannot find (`records missing for [...]`) -- and the SWAP
    # direction is FULLY LATERAL: the same tag set, the same joint verdict, the same reasons, because the
    # a/b split only decides which of two same-shaped records a component is filed in. No consequence, so
    # no admission; recorded here so the next reader does not have to re-derive it. See
    # `ELEMENT_LANE_ATTRIBUTE_READS["to_experiment_records: c.metric"]`.
    hid = _plain_word(hid)
    if len(PRIMARY[hid]) == 1:
        return hid
    return hid + ("a" if metric.startswith("delta") and "minus" not in metric else "b") + ("_conv" if conv else "")


def to_experiment_records(res: JointResult, *, study_id: str, base_seed: int, timestamp_utc: Optional[str] = None,
                          code_version: str = CODE_VERSION, scorer_validation: Optional[bool] = None,
                          prereg_hash: Optional[str] = None, amendments_hash: Optional[str] = None) -> list:
    """Serialise onto ExperimentRecord (EvidenceClass.TOY_RESULT for measured data; SOURCE_OBSERVED is rejected
    by the schema). NO verdict is written to `notes`. Interval bounds, margins, n and gate states are stored as
    metrics, and `verdict_from_records` rebuilds the verdict from them alone. `prereg_hash` / `amendments_hash`
    are included in input_hashes only when supplied (a hash field cannot hold 'unmeasured')."""
    ts = timestamp_utc or _now()
    is_fixture = res.subject_kind == "fixture"
    if scorer_validation is not None and bool(scorer_validation) != is_fixture:
        raise ValueError(f"scorer_validation={_shown(scorer_validation)} contradicts "
                         f"subject_kind={_shown(res.subject_kind)}")
    kind = ("SCORER-VALIDATION FIXTURE (a test of the scorer, not a result about any method)"
            if is_fixture else "toy fixture")
    hashes = {"seed_list": res.seed_list_digest, "config": res.config_hash}
    for k, v in (("registered_seed_list", res.registered_digest), ("prereg", prereg_hash),
                 ("amendments", amendments_hash)):
        if v is not None:
            hashes[k] = v

    def prov(run_id: str, seed: int) -> RunProvenance:
        return RunProvenance(run_id=run_id, timestamp_utc=ts, seed=seed, code_version=code_version,
                             python_version=current_python_version(), toy_only=True, input_hashes=hashes)

    recs = []
    for h in (res.h1, res.h2, res.h3):
        for conv, comps in ((False, h.components), (True, h.converged_components)):
            for c in comps:
                tag = _tag(h.hid, c.metric.replace("_conv", ""), conv)
                ec = EvidenceClass.TOY_RESULT if _metric_ok(c.pair.mean) else EvidenceClass.UNKNOWN
                recs.append(ExperimentRecord(
                    name=f"evalproto/{study_id}/agg/{tag}", provenance=prov(f"{study_id}-agg-{tag}", base_seed),
                    metrics=_agg_metrics(c.pair, c.margin, res.n_failed, res.subject_kind), evidence_class=ec,
                    notes=f"{TOY_LABEL} PRIMARY {h.hid} component {c.metric} [{kind}] subject={res.subject} "
                          f"subject_kind={res.subject_kind} fixture_name={res.fixture_name}. "
                          f"Informational only; flags: {list(c.pair.flags)}"))
    # THE SERIALISED GATE STATES ARE KEYED ON THIS MODULE'S OWN GATE NAMES and read only off objects the
    # class's completeness check actually validated. THE DEFECT THIS CLOSES (SR-10 Finding 1): this was
    # `{f"gate_{g.name}": ... for g in res.gates}`, which reads `.name`/`.passed` off ANY object in the
    # list and lets a DUPLICATE NAME SILENTLY OVERWRITE a genuinely failed gate's stored 0.0 with 1.0. It
    # is the exact sibling of `JointResult.__post_init__`'s `failed` comprehension 145 lines above, which
    # round 13 wrapped in `_plain_word` *because* "this comprehension reads `.name` off ANY object in the
    # list" -- and left this one unguarded: the half-fix pattern this module has already failed to three
    # times. MEASURED, identical on 3.12.4 and 3.13.5, on a study whose `seed_list_frozen` gate GENUINELY
    # FAILS (registered-digest mismatch), with a plain object carrying five class attributes -- no
    # `object.__setattr__`, no `str` subclass, no overridden dunder, `exempt=False` so the exemption guard
    # never fires:
    #     honest : stored gate_seed_list_frozen=0.0  verdict_from_records -> JOINT_INCONCLUSIVE
    #     forged : stored gate_seed_list_frozen=1.0  verdict_from_records -> JOINT_SUPPORTED, reasons=()
    # `JointResult.verdict` stayed honest and `dashboard.render_scorecard` did raise CONTRACT PROBLEM, and
    # THAT BOUND IS NOT A DEFENCE: the SERIALISED EVIDENCE ITSELF was falsified -- the JOINT record stored
    # 1.0 for a gate that failed -- and `verdict_from_records`, documented as rebuilding the verdict "from
    # them alone", reported SUPPORTED with no reason. A records-only consumer never runs the dashboard.
    # A second GENUINE `GateResult` with a duplicate name was already refused upstream, so the hole was
    # exactly the `isinstance` filter at the completeness check plus this unguarded overwrite. Keying on
    # `GATE_SCOPES` means the record set cannot gain, lose, duplicate or reorder a gate whatever the list
    # holds; the two refusals below are reachable only through a duck-typed `res`. See
    # `ELEMENT_LANE_ATTRIBUTE_READS`.
    real = {}
    for g in res.gates:
        if not isinstance(g, GateResult):
            continue      # invisible to the completeness check (documented), and invisible here too
        if g.name in real:
            raise ValueError(f"gates contain two GateResult objects named {_shown(g.name)}; refusing to "
                             f"serialise an ambiguous gate state")
        real[g.name] = g
    absent = [n for n in GATE_SCOPES if n not in real]
    if absent:
        raise ValueError(f"gates are missing GateResult entries for {absent}; refusing to serialise a "
                         f"JOINT record whose gate states are incomplete")
    gate_m = {f"gate_{n}": MetricValue.measured(1.0 if g.passed else 0.0) for n, g in real.items()}
    gate_m.update({"n_seeds": MetricValue.measured(float(res.n_attempted - res.n_failed)),
                   "n_failed": MetricValue.measured(float(res.n_failed)),
                   "n_deferred_checks": MetricValue.measured(float(len(res.deferred_gates))),
                   "subject_kind_code": MetricValue.measured(SUBJECT_KIND_CODE[res.subject_kind]),
                   "loss_check_exempt": MetricValue.measured(
                       1.0 if carries_exemption(res.gates) else 0.0)})
    recs.append(ExperimentRecord(
        name=f"evalproto/{study_id}/agg/JOINT", provenance=prov(f"{study_id}-agg-JOINT", base_seed),
        metrics=gate_m, evidence_class=EvidenceClass.TOY_RESULT,
        notes=f"{TOY_LABEL} [{kind}] subject={res.subject} subject_kind={res.subject_kind} "
              f"fixture_name={res.fixture_name}. Informational only; gate states are metrics. "
              f"Unimplemented checks (any favourable outcome is conditional on them): {list(res.deferred_gates)}."))
    return recs


def _pair_from_record(rec: ExperimentRecord, min_n: Optional[int] = None) -> IntervalPair:
    """Rebuild an `IntervalPair` from a stored record. Every scalar is read through the checked reader and a
    missing metric is a ValueError naming the record, so this function's ONLY failure mode is a ValueError
    inside the module's stated error contract.
    THE DEFECT THIS CLOSES (D4): `int(m["n_seeds"].value)`, `m["ci_level"].value` and `int(m["n_boot"].value)`
    had NO check of any kind -- not even `is_measured`. A forged `n_seeds = 1e9` was accepted in silence and
    cleared protocol 6.1's minimum-n floor (the floor that `_verdict_from_bounds` applies); a forged `nan`
    escaped as a bare `ValueError: cannot convert float NaN to integer` and a forged `None` as a `TypeError`,
    neither of which this module declares. The `MetricValue` fields (mean, sd, the four bounds) need no check
    here because `IntervalPair._bound` reads them through the same reader at the point of use.
    WHICH `flags` SURVIVE THE ROUNDTRIP, decided and stated because a consumer asked (SR-13 was using only
    one direction of `flag present => n < min_n` on the assumption that none of them did). `IntervalPair.
    flags` is a tuple of PRODUCER PROSE and is not stored as a metric: it appears only in the record's
    `notes`, which this module forbids parsing back as evidence. So it cannot be RESTORED. Two of the four
    are instead RECOMPUTED here, exactly, from the stored `n_seeds` and the configuration this recompute is
    already BOUND to:
      * "n below protocol minimum" -- needs `min_n`, so it is derived only when the caller passes it
        (`verdict_from_records` passes `cfg.min_seeds`, and the config-hash binding means that IS the
        producer's `min_seeds`). With `min_n=None` it cannot be derived and is absent; the biconditional
        `flag present <=> n < min_n` therefore holds whenever `min_n` is given, which is the form a
        consumer can rely on.
      * "percentile bootstrap unreliable (n < 20)" -- a fixed constant, so always derived.
    THE OTHER TWO ARE NOT RECOVERABLE AND ARE DELIBERATELY NOT FAKED: "degenerate: all values tied" needs
    the raw per-seed values (`sd == 0.0` is NOT equivalent to it -- see `sample_sd`'s float-floor limit),
    and "heavy tail" is a formatted string whose number is stored (`max_over_median_abs`) but whose text is
    the producer's. Reconstructing prose is not carrying evidence. A roundtripped pair therefore has a
    flags tuple that is a SUBSET of the producer's, never a superset, and never a different one."""
    # The thirteen names below are looked up in a mapping whose KEYS are the producer's objects, so a
    # key storing one word and answering as another would rebuild the interval out of the wrong
    # numbers (a `min` served as `ci_boot_lo`) while the record files neither under the name used.
    m = _word_keyed(rec.metrics)
    need = ("n_seeds", "ci_level", "n_boot", "mean", "sd", "iqr", "min", "max", "max_over_median_abs",
            "ci_boot_lo", "ci_boot_hi", "ci_t_lo", "ci_t_hi")
    absent = [k for k in need if k not in m]
    if absent:
        raise ValueError(f"{_shown(rec.name, how=str)}: record is missing the metrics {absent}; "
                         "cannot rebuild an interval")
    n = _metric_count(m["n_seeds"], f"{_shown(rec.name, how=str)}: n_seeds")
    flags = []
    if min_n is not None and n < min_n:
        flags.append("n below protocol minimum")
    if n < 20:
        flags.append("percentile bootstrap unreliable (n < 20)")
    return IntervalPair(rec.name, n,
                        _metric_required(m["ci_level"], f"{_shown(rec.name, how=str)}: ci_level"),
                        _metric_count(m["n_boot"], f"{_shown(rec.name, how=str)}: n_boot"),
                        m["mean"], m["sd"], m["iqr"], m["min"], m["max"], m["max_over_median_abs"],
                        m["ci_boot_lo"], m["ci_boot_hi"], m["ci_t_lo"], m["ci_t_hi"], tuple(flags))


@dataclasses.dataclass(frozen=True)
class RecomputedVerdict:
    joint: JointVerdict
    h1: Verdict
    h2: Verdict
    h3: Verdict
    subject_kind: str = "unknown"   # decoded from the stored metric, never from notes
    config_hash: Optional[str] = None   # the STORED study config hash this recompute was bound to
    reasons: tuple = ()                 # nonempty ONLY when the recompute failed closed (see below)


def verdict_from_records(records: Sequence[ExperimentRecord], cfg: Optional[BenchmarkConfig] = None
                         ) -> RecomputedVerdict:
    """Rebuild the verdict from stored metrics (interval bounds, margins, n, gate states), BOUND TO THE
    CONFIGURATION THE STUDY RAN UNDER. `notes`, `name` text and every other free-text field are ignored. A
    missing record raises ValueError; a missing or unmeasured gate counts as failed.

    WHICH PARAMETERS COME FROM THE CALLER'S `cfg`, AND WHY THAT IS NOW SAFE (the docstring used to claim
    "ONLY from stored metrics", which was false): `cfg.min_seeds`, `cfg.width_tol` and `cfg.alpha` are not
    stored as metrics, so they can only come from the caller. Before ANY of them is used,
    `cfg.config_hash()` is compared with the `config` hash the records already carry (`to_experiment_records`
    writes `input_hashes = {"seed_list": ..., "config": res.config_hash}` into every record). Three
    conditions FAIL CLOSED -- JOINT_INCONCLUSIVE, all three hypotheses INCONCLUSIVE, the reason in
    `RecomputedVerdict.reasons` -- and never fall back to module defaults:
      * the caller's `cfg` does not hash to the stored config;
      * no stored `config` hash is present (records that predate it cannot be bound);
      * the records disagree among themselves about the stored config hash.
    THE DEFECT THIS CLOSES was an ordinary call, not tampering: `width_tol` was shielded by nothing, so a
    study registered with `width_tol=0.10` recomputed to JOINT_SUPPORTED when called with no `cfg` argument
    (module default 0.25) while its own configuration gave JOINT_INCONCLUSIVE. `alpha` was already pinned by
    the `ci_level` cross-check and `min_seeds` partly by the min-seeds gate; `width_tol` was not.
    NOT covered by the config hash: `Margins` is not a `BenchmarkConfig` field (see `Margins`). The margin
    of every component is read OUT OF THE RECORD (`margin` metric), never from `cfg`, so no margin a
    recompute uses can come from the CALLER. THAT SENTENCE USED TO END "-- so that is sound", WHICH WAS A
    PROVENANCE ARGUMENT OFFERED AS A VALIDITY ARGUMENT: where the margin comes from says nothing about what
    it is allowed to be, and until `_check_margin` there was no bound on the value at all. A stored `margin`
    rewritten to -1.7976931348623157e308 -- a finite float, so `MetricValue` accepts it with no
    `object.__setattr__` needed -- turned a measured JOINT_UNSUPPORTED into JOINT_SUPPORTED with
    `reasons = ()` and an unchanged `config_hash`, i.e. with the exact signature of a clean recompute.
    Every stored scalar this function uses now goes through the module's single checked reader
    (`_metric_read` and its three wrappers), and the margin additionally through `_check_margin`; what
    remains open is a margin that is WITHIN bounds and still vacuous, which no bound can close
    (see `Margins` and `_check_margin`).
    ORDER: the `loss_check_exempt` / `subject_kind_code` forgery checks run BEFORE the config check, so a
    config mismatch can never mask a forgery; `cfg` is not consulted by either of them.
    WHAT THE BINDING DOES NOT DO, stated because "BOUND TO THE CONFIGURATION THE STUDY RAN UNDER" above
    would otherwise overstate it: the stored `config` hash is itself a stored value, so **rewriting it in
    every record and passing the cfg that matches the rewrite reaches JOINT_SUPPORTED with no reason
    recorded.** This is post-hoc tampering in the already-disclosed class, and it requires write access to
    every record. IT WAS ALSO CLAIMED TO "GRANT NOTHING OVER FORGING THE `gate_*` METRICS DIRECTLY", WHICH
    WAS FALSE AND IS CORRECTED HERE: forging `gate_*` can only make gates pass, which at most lifts a
    JOINT_INCONCLUSIVE; it cannot make a component SUPPORTED, because component verdicts are derived from
    the stored bounds and margin. Rewriting the config hash unlocks `min_seeds` / `width_tol` / `alpha`,
    which CAN invert a genuine UNSUPPORTED. The two are not equivalent and the stronger route must be
    stated as the stronger one. The binding defeats the ORDINARY-CALL defect above and an inconsistent or
    absent hash; it is not an authentication of the records.
    THE KEY LANE, added in round 12 because the sentence above was true of the VALUE and said nothing
    about the NAME: `.get("config")` is `__hash__` + `__eq__` on the STORED KEY, so until every mapping
    this function reads went through `_word_keyed` the binding was decided by whichever key answered to
    the word, not by the key that stored it. A key storing "seed_list_2" and answering as "config",
    carrying the hash THIS CALL will ask for, bound a width_tol=0.10 study to the default 0.25 and
    returned JOINT_SUPPORTED with `reasons = ()`. Round 6 had closed the same flip on `input_hashes`
    VALUES in `toy.schema`; it returned through the keys of the same lookup. Every mapping read here --
    the JOINT record's metrics, each component record's metrics, each record's `input_hashes` -- and the
    `by` tag cut out of `r.name` now read the characters the producer's object STORES. The public route
    was closed throughout: `ExperimentRecord` and `RunProvenance` normalise both mapping fields' keys at
    construction (re-verified, not assumed). `object.__setattr__` was one route; the other needed no
    tampering primitive at all, because THIS FUNCTION ENFORCES NO INSTANCE CHECK -- a plain object with
    `name`, `metrics`, `evidence_class` and `provenance` reaches every lookup, and did reach this one."""
    cfg = _cfg(cfg)
    by = {}
    for r in records:
        # THE TAG IS CUT OUT OF THE CHARACTERS THE NAME STORES. `"/agg/" in r.name` is
        # `__contains__` and `r.name.rsplit(...)` is a METHOD, both overridable on a `str` subclass, and
        # `by` is then keyed by whatever `rsplit` handed back -- so a name could file its record under
        # another component's tag. Plain `str.rsplit` on a subclass returns plain `str` slices (measured),
        # and with all seven tags required, moving one record always empties its own slot and raises
        # `records missing for [...]`; so this site was fail-closed before and is now closed by reading
        # rather than by that accident of the 1:1 record set.
        nm = _stored_word(r.name)
        if nm is not None and "/agg/" in nm:
            by[nm.rsplit("/agg/", 1)[1]] = r
    need = ["H1", "H2", "H3a", "H3b", "H3a_conv", "H3b_conv", "JOINT"]
    missing = [k for k in need if k not in by]
    if missing:
        raise ValueError(f"records missing for {missing}")
    for r in by.values():
        if _enum_member(EvidenceClass, r.evidence_class) is not EvidenceClass.TOY_RESULT:
            raise ValueError(f"{_shown(r.name, how=str)}: only TOY_RESULT records can carry a recomputed verdict")

    # ---- subject-kind decode and exemption-forgery checks: no `cfg` is consulted, so they run first and a
    # ---- config mismatch can never mask a forgery.
    # `_word_keyed` ONCE, then every `gm.get(...)` / `gm[...]` below -- including the `gate_*` f-STRING
    # lookup, which is the site a Constant-only AST sweep misses -- is on a plain `dict` with plain `str`
    # keys. See `_word_keyed` for the four measured flips this closes.
    gm = _word_keyed(by["JOINT"].metrics)
    code = _metric_read(gm.get("subject_kind_code"))
    kind = next((k for k, c in SUBJECT_KIND_CODE.items() if code is not None and code == c), "unknown")
    # `_metric_strict`, not `_metric_read`: for a cross-check field a MALFORMED value must raise rather than
    # be laundered into the same outcome as "not recorded". A forged `inf` here used to raise (via the
    # `not in (0.0, 1.0)` branch) and must keep raising, while an honest `unmeasured` must keep being accepted.
    exv = _metric_strict(gm.get("loss_check_exempt"), "loss_check_exempt")
    if exv is not None and exv not in (0.0, 1.0):
        raise ValueError(f"loss_check_exempt must be 0.0 or 1.0, got {_shown(exv)}")
    if exv == 1.0 and kind != "fixture":
        raise ValueError("records claim the gate-11(c) exemption but subject_kind_code is not 'fixture' "
                         "(forged or deleted code)")

    # ---- BIND the recompute to the stored configuration before any cfg-derived parameter is used.
    # `_word_keyed` on the KEYS, because round 6 closed this same flip on the VALUES in `toy.schema` and
    # it came back through the other field of the same lookup: `.get("config")` is `__hash__` + `__eq__`
    # ON THE STORED KEY. A key storing "seed_list_2" that answers as "config", carrying the hash the
    # recompute itself will want, bound a width_tol=0.10 study to the DEFAULT 0.25 and reported
    # JOINT_SUPPORTED with `reasons = ()` -- for a configuration no record filed a config hash for.
    stored = {_word_keyed(r.provenance.input_hashes).get("config") for r in by.values()}
    want_hash = cfg.config_hash()
    bound = next(iter(stored)) if len(stored) == 1 else None
    if None in stored:
        why = ("no stored config hash on at least one record: the recompute cannot be bound to the "
               "configuration the study ran under")
    elif bound is None:
        why = f"records disagree on the stored config hash: {sorted(h[:12] for h in stored)}"
    elif bound != want_hash:
        why = (f"cfg does not match the stored study configuration (cfg {want_hash[:12]} vs stored "
               f"{bound[:12]}): refusing to recompute with a different min_seeds/width_tol/alpha")
    else:
        why = None
    if why is not None:
        return RecomputedVerdict(JointVerdict.JOINT_INCONCLUSIVE, Verdict.INCONCLUSIVE, Verdict.INCONCLUSIVE,
                                 Verdict.INCONCLUSIVE, kind, bound, (why,))

    want_level = bonferroni_level(cfg.alpha, N_PRIMARY)
    # n CROSS-CHECK. A forged `n_seeds` is a legal count, so `_metric_count` cannot catch it; the only
    # defence is a second stored number to compare it against. The JOINT record stores
    # `n_seeds = n_attempted - n_failed` (the number of OK seeds), and a component's `pair.n` is the number
    # of seeds on which THAT series was measured, which is a subset -- so `component n <= joint n` holds by
    # construction for every honest record and a forged n_seeds=1e9 breaks it. Equality is NOT required:
    # the converged-budget series can be measured on fewer seeds than are OK. This is the `pair.n` defect
    # of round 3 in its records form: there, two consumers disagreed about n and a forged n bought a
    # decisive verdict; the lesson applied here is that n must be CHECKED against something, not trusted.
    # IT FAILS CLOSED ON AN ABSENT SECOND SOURCE, and that is a deliberate change: this used to read
    # `... if "n_seeds" in gm else None`, so deleting one dict entry SKIPPED the check silently and n was
    # trusted after all -- in the one guard whose stated purpose is that it is not. Deciding it rather
    # than defaulting it: `to_experiment_records` writes `n_seeds` into EVERY JOINT record, so no honest
    # producer in this kit can omit it, and `verdict_from_records` already raises for a missing `margin`,
    # `ci_level` or any of `_pair_from_record`'s thirteen metrics. A missing `n_seeds` is therefore the
    # same class of malformed record as those, and it gets the same answer. (`toy.dashboard`'s version of
    # this cross-check fails closed for a different reason: its two sources are required dataclass fields
    # with no absent case at all.)
    if "n_seeds" not in gm:
        raise ValueError("JOINT: record stores no n_seeds metric; the component-n cross-check cannot run, "
                         "and a stored n that is not checked against a second source is a trusted n")
    joint_n = _metric_count(gm["n_seeds"], "JOINT: n_seeds")

    def comp(tag, metric, direction):
        r = by[tag]
        rm = _word_keyed(r.metrics)     # the margin and the level are read under the names they are FILED
        for k in ("margin", "ci_level"):
            if k not in rm:
                raise ValueError(f"{tag}: record stores no {k} metric; cannot recompute a component verdict")
        # Both operands of `lo > margin` are now read the same way. The RIGHT one (`margin`) was the
        # half-fix of round 3: `_bound` closed the left and left this on `is_measured` alone, so a stored
        # `margin` of -1.7976931348623157e308 inverted a genuine UNSUPPORTED with `reasons = ()`.
        mg = _metric_required(rm["margin"], f"{tag}: margin")
        lv = _metric_required(rm["ci_level"], f"{tag}: ci_level")
        if abs(lv - want_level) > 1e-12:
            raise ValueError(f"{tag}: ci_level {_shown(lv)} is not the adjusted level "
                             f"{want_level!r} (m={N_PRIMARY})")
        # `_pair_from_record(r)`, NOT `(r, cfg.min_seeds)`: the recomputed `flags` would be
        # UNOBSERVABLE here. `flags` is consumed by nothing in this module's verdict logic (its only
        # other use is `to_experiment_records` writing it into `notes`, which is not evidence), and
        # `RecomputedVerdict` carries no pair -- so passing the minimum at this call site would be dead
        # code dressed as a guard. A measured mutant proved it: dropping the argument changed no test.
        # A DIRECT caller of `_pair_from_record` that wants the flag passes `min_n` itself, and both
        # directions of `flag present <=> n < min_n` are pinned there. The n-below-minimum FACT still
        # reaches the verdict by the route that always carried it: `_verdict_from_bounds` compares
        # `pair.n` with `min_n` itself and returns INCONCLUSIVE, which is asserted across the whole
        # declared range of `min_seeds` by `test_the_declared_input_RANGE_is_swept_not_just_the_default`.
        pair = _pair_from_record(r)
        if pair.n > joint_n:
            raise ValueError(f"{tag}: stored n_seeds {pair.n} exceeds the study's {joint_n} measured seeds "
                             f"(a component cannot be measured on more seeds than succeeded)")
        # `_check_margin` runs again inside `_verdict_from_bounds`; calling it here only buys an error
        # message that names the record. The bound itself lives at the point of use, not at this call site.
        return ComponentResult(metric, direction, _check_margin(mg, f"{tag}: margin"), pair,
                               cfg.min_seeds, cfg.width_tol)

    state = {n: gm.get(f"gate_{n}") for n in GATE_SCOPES}
    # A gate PASSES only on a stored value that reads as exactly the float 1.0. Anything else -- missing,
    # unmeasured, 0.0, out of range, or (D5) the bool `True`, which the old `v.value != 1.0` test let
    # through because `True == 1.0` -- counts as failed. `GateResult.__post_init__` is strict about bools;
    # until now the records path was not.
    failed = [n for n, v in state.items() if _metric_read(v) != 1.0]
    glob = [n for n in failed if GATE_SCOPES[n] == "all"]
    g12 = [n for n in failed if GATE_SCOPES[n] == "H3"]
    h1 = HypothesisResult("H1", (comp("H1", "S", "greater"),), blocking=tuple(glob))
    h2 = HypothesisResult("H2", (comp("H2", "L", "less"),), blocking=tuple(glob))
    h3 = HypothesisResult("H3", (comp("H3a", "delta", "greater"), comp("H3b", "delta_minus_shuf", "greater")),
                          (comp("H3a_conv", "delta_conv", "greater"),
                           comp("H3b_conv", "delta_minus_shuf_conv", "greater")),
                          blocking=tuple(glob), supported_blockers=tuple(g12))
    return RecomputedVerdict(combine_joint(h1.verdict, h2.verdict, h3.verdict, not glob),
                             h1.verdict, h2.verdict, h3.verdict, kind, bound, ())


def _gate_metrics(s: SeedScores) -> dict:
    return {"gate_finite": MetricValue.measured(1.0 if s.ok else 0.0),
            "gate_disjoint": (MetricValue.measured(1.0 if s.rowsets_disjoint else 0.0)
                              if s.rowsets_disjoint is not None else MetricValue.unmeasured("not checked"))}


def seed_records(res: JointResult, *, study_id: str, timestamp_utc: Optional[str] = None,
                 code_version: str = CODE_VERSION, prereg_hash: Optional[str] = None,
                 amendments_hash: Optional[str] = None) -> list:
    """One ExperimentRecord per (arm/subject, seed), named evalproto/<study>/<subject>. Unmeasured metrics stay
    MetricValue.unmeasured. Notes carry no verdict."""
    ts = timestamp_utc or _now()
    out = []
    for s in res.seed_scores:
        hashes = {"seed_list": res.seed_list_digest, "config": res.config_hash, **dict(s.input_hashes)}
        for k, v in (("prereg", prereg_hash), ("amendments", amendments_hash)):
            if v is not None:
                hashes[k] = v
        out.append(ExperimentRecord(
            name=f"evalproto/{study_id}/{res.subject}",
            provenance=RunProvenance(run_id=f"{study_id}-{res.subject}-{s.seed}", timestamp_utc=ts, seed=s.seed,
                                     code_version=code_version, python_version=current_python_version(),
                                     toy_only=True, input_hashes=hashes),
            metrics={**s.metrics, **_gate_metrics(s),
                     "subject_kind_code": MetricValue.measured(SUBJECT_KIND_CODE[res.subject_kind])},
            evidence_class=EvidenceClass.TOY_RESULT if s.ok else EvidenceClass.UNKNOWN,
            notes=f"{TOY_LABEL} arm/subject={res.subject}; PRIMARY inputs; per-seed values only."))
    return out


def planned_slot_records(*, study_id: str, arms: Sequence[str], seeds: Sequence[int], timestamp_utc: Optional[str] = None,
                         code_version: str = CODE_VERSION, seed_list_hash: Optional[str] = None) -> list:
    """Planned-but-unrun (arm, seed) slots: EvidenceClass.UNKNOWN, every metric unmeasured."""
    ts = timestamp_utc or _now()
    hashes = {} if seed_list_hash is None else {"seed_list": seed_list_hash}
    why = "UNKNOWN: registered, not yet run"
    out = []
    for arm in arms:
        for s in seeds:
            m = {k: MetricValue.unmeasured(why) for k in SEED_METRICS + ("gate_finite", "gate_disjoint")}
            out.append(ExperimentRecord(
                name=f"evalproto/{study_id}/{arm}",
                provenance=RunProvenance(run_id=f"{study_id}-{arm}-{s}", timestamp_utc=ts, seed=s,
                                         code_version=code_version, python_version=current_python_version(),
                                         toy_only=True, input_hashes=hashes),
                metrics=m, evidence_class=EvidenceClass.UNKNOWN,
                notes=f"{TOY_LABEL} planned slot arm={arm}; nothing measured."))
    return out
