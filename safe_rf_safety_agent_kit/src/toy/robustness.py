"""SR-11: neutral robustness probes for the TOY measurement procedure (seeds, benign numeric shifts,
missing inputs, numerical stability) and immutable scorecards.

TOY / MEASURING-INSTRUMENT module. Standard library only. Synthetic, non-biological, abstract.

WHAT THIS MODULE IS: a set of probes of how a *measurement procedure* (a masked mean-squared-error style
measure, the seed-replication machinery, and the `toy.stability` validators) behaves when its inputs are
perturbed, withheld, or pushed to numerical extremes, plus a genuinely immutable `Scorecard` that records
what a probe saw.

WHAT THIS MODULE IS NOT: an experiment, a result, or a finding. Nothing here runs the experiment of
docs/EVALUATION_PROTOCOL.md or produces a verdict about any method. Every number is a property of a
procedure on a synthetic fixture generator. The statuses (`ProbeStatus`) say whether a *measure*
behaved as declared, never whether anything is safe. Nothing here says anything about RFdiffusion, the
audited fork, or any real model, and a clean probe is not evidence of safety or of robustness of any real
system.

Structural rule against single-example claims (checked at construction, not merely documented):
* `SeedSummary` (the only carrier of mean/SD/IQR/min/max) validates in `__post_init__` that it holds at
  least `SEED_FLOOR` measured values (a COUNT: the values themselves may repeat, e.g. a constant outcome
  is legitimate) and that every statistic equals the recomputed one.
* `summarize_seeds` returns `InsufficientEvidence` (a type with NO numeric statistic fields) whenever the
  number of measured values is below the configurable minimum, which itself cannot be set below
  `SEED_FLOOR`. `summarize_seeds` and `SeedSummary.from_values` see values, not seeds, so they CANNOT
  detect one example repeated: `summarize_seeds([mv] * 10)` returns a summary. Duplicate SEEDS are
  rejected only on the probe path (`_check_seeds`, used by every probe and by `build_scorecard`).
  THAT SENTENCE NAMES THE ONLY DEFENCE, AND THE DEFENCE WAS DEFEATABLE: `_check_seeds` compares
  `len(set(seeds)) != len(seeds)`, i.e. `__hash__` and `__eq__` on the caller's objects, so three
  instances of an `int` subclass with `__hash__ = id` and identity `__eq__` -- stored value 7, three
  times -- were ACCEPTED by every probe (status INVARIANCE_HOLDS, n=3, `violating_seeds=()`) while the
  plain list `[7, 7, 7]` is refused. `SEED_FLOOR = 3` was satisfied by ONE seed. `_check_seeds` now
  normalises to plain ints before the comparison and returns them, so the list compared is the list
  stored, hashed into `seed_digest` and handed to the `outcome`/fixture callbacks; the related
  `derive_seed` route (a seed whose `__str__` lied, making two DISTINCT seeds derive one fixture) is
  closed in `toy.schema._check_seed`. Both are pinned by
  `test_robustness.OneExampleCannotBeRepeatedPastTheSeedGuard`.
* HOW MANY TIMES `SEED_FLOOR` IS DEFENDED, counted rather than remembered, because FIVE different
  numbers have been in circulation here (a test docstring said "three times over", `docs/PROGRESS.md`
  says "five independent points", a previous version of THIS paragraph said "four direct comparisons and
  six paths" -- and the count written to stop the drift introduced the fifth number itself):
  there are FOUR direct comparisons against `SEED_FLOOR` in this module -- `ProbeConfig.__post_init__`,
  `SeedSummary.__post_init__`, `SeedSummary.from_values` and `_recheck_summary` -- and EIGHT paths reach
  them: those four plus FOUR delegations, `_pcfg`'s `ProbeConfig()`, `summarize_seeds`'s
  `ProbeConfig(min_seeds)`, and `Scorecard.__post_init__`'s `ProbeConfig(self.min_seeds)` and
  `_recheck_summary(self.summary)`. ONE OF THE EIGHT USED TO DEFEND LESS THAN THE COUNT IMPLIED, and the
  count was right about the PATH while being wrong about what it bought: `Scorecard.__post_init__`'s
  `ProbeConfig(self.min_seeds)` DISCARDED its return value, so it enforced the absolute FLOOR (the
  constructor still raises below 3) but NOT the configured minimum this docstring also claims it checks
  -- the card's own `len(measured) < self.min_seeds` ran on the un-normalised field. The call now binds
  its result, so all eight paths defend both. "SIX" WAS WRONG: it counted only the two delegations in `Scorecard`
  and silently dropped `_pcfg`'s and `summarize_seeds`'s, although `summarize_seeds`'s is the same kind of
  delegation as `Scorecard`'s and is the one
  `test_robustness.test_probe_config_defaults_are_constructed_per_call` relies on for its "absolute
  floor" message. BOTH numbers are now measured from this module's own AST by
  `test_robustness.ThePolicyParametersAreThemselvesPinned.test_the_number_of_seed_floor_defences_is_counted_not_claimed`
  -- the path count as well as the comparison count, which is what the previous version left to prose and
  is why it could be wrong. The comparison sites are deduplicated BY LINE NUMBER, not by owner name,
  because `ProbeConfig.__post_init__` and `SeedSummary.__post_init__` are both spelled `"__post_init__"`.
  `DEFAULT_MIN_SEEDS = 10` is a separate, weaker thing: a POLICY minimum, not the floor, pinned by value.
* `Scorecard.__post_init__` requires exactly one of {summary, insufficient}, checks the status, labels,
  counts and seed digest agree, and RE-VALIDATES the nested summary / insufficient object (exact type,
  recomputed statistics), so `dataclasses.replace` cannot launder a summary that was tampered with
  after construction. THE "COUNTS" HALF OF THAT SENTENCE WAS FALSE until the `ProbeConfig(self.min_seeds)`
  call on its first lines stopped DISCARDING its result: `len(measured) < self.min_seeds` then ran on the
  caller's own object, and `replace(card, min_seeds=Lo(10))` with a lying reflected `__gt__` produced an
  accepted card reading `{"min_seeds": 10, "summary": {"n": 3}}`. The seed-digest and
  `does_not_establish` halves were defeatable the same way through a `str` subclass (see `_plain_text`).
  All three are normalised before comparison now and pinned by
  `test_robustness.ACardCannotAssertAMinimumItDoesNotMeet`. A card carrying a summary of fewer than `SEED_FLOOR` values, or a subclass of
  `SeedSummary`, cannot be built through the public constructors, `dataclasses.replace`, or the builders.
* WHERE SUBCLASS NORMALISATION NOW LIVES, and why it is not a list of sites any more. Every bullet above
  records a defeated guard of the same shape: a `str` / `int` / `float` SUBCLASS satisfies every
  `isinstance` check and every regex, and the guard is written in `__eq__` / `__ne__` / `__hash__` /
  `__lt__` / `__gt__` / `__mul__` / `__float__`, all of which it overrides. Five correct helpers
  (`toy.benchmark._plain_number`, `_plain_parameter`, this module's `_plain_text`, `_plain_measure`,
  `_plain_summary_fields`) were applied at TWELVE hand-chosen call sites, and five consecutive review
  rounds each found the sites nobody remembered -- most recently `RunProvenance.input_hashes`,
  `arm_difference`'s arm NAMES, `ExperimentRecord.from_dict`'s version and label gates, and
  `shift_reorder_rows`'s `rel_tol` (the un-swept sibling of a `tol` round 5 had just fixed). That
  procedure cannot terminate, because its audit is a person hunting for omissions. Normalisation is
  therefore applied AT THE TYPE BOUNDARY: `toy.schema._normalise_fields(self)` is the first statement of
  `__post_init__` in every dataclass here (`ProbeConfig`, `InsufficientEvidence`, `SeedSummary`,
  `Scorecard`, `MeasureFixture`, `ShiftSpec`), and it walks `dataclasses.fields()` -- so a NEW FIELD IS
  COVERED BY DEFAULT and an exemption must be declared in the class's `_NORMALISE_EXEMPT` with a reason.
  `test_robustness.EveryDataclassFieldIsNormalisedOrExplicitlyExempt` enumerates the fields and the
  classes from the module itself and fails closed on either a new field or a new dataclass.
* AND THE SAME ARGUMENT, MADE ONCE MORE, FOR PARAMETERS -- because the field boundary's own stated gap
  ("a function PARAMETER or a closure variable is not a field, so `arm_difference`'s names,
  `shift_reorder_rows`'s `rel_tol` and `probe_precision`'s `tol` / `param` are normalised where they are
  bound") was a list of remembered sites wearing a boundary's clothes, and round 7 found FOUR more live
  routes in it, none of them on the list: `probe_precision`'s `kind` (the sibling of `tol` and `param`
  IN THE SAME SIGNATURE: a `str` subclass storing "magnitude" and comparing as "cancellation" ran the
  cancellation construction under a card reading `precision:magnitude:200.0`, INSUFFICIENT_EVIDENCE ->
  PRECISION_OK, `UNKNOWN` -> `TOY_RESULT`, and a 12-seed summary where the honest run has NONE);
  `shift_jitter`'s `eps` and `shift_scale`'s `factor` (CLOSURE VARIABLES of a factory, which are exactly
  the factory's own parameters -- SENSITIVITY_EXCEEDS_BOUND -> SENSITIVITY_WITHIN_BOUND with
  `max_abs_dev` IDENTICAL in both runs, and INVARIANCE_DEFECT -> INVARIANCE_HOLDS certifying a
  degree-1 measure as satisfying a declared degree-2 invariance); and `make_measure_fixture`'s `rows`,
  whose `rows < 4` gate is `type(rows).__lt__` and which therefore MEASURED 12 seeds on fixtures the
  module refuses to build. So normalisation is now applied AT THE PARAMETER BOUNDARY as well:
  `_install_parameter_boundary(globals())` wraps EVERY public callable of this module, derived from the
  module namespace and not from a list, and `_plain_value` is applied to every bound argument -- so a NEW
  PUBLIC FUNCTION and a NEW PARAMETER are covered by default, and the boundary itself consults no
  exemption list that anyone could widen. `_PARAMETER_NO_SCALAR` records, per (function, parameter), the
  ones where that call CANNOT collapse anything (a callable, an `Enum`, a dataclass carrier, a strict-bool
  mask) together with the mechanism that does protect them;
  `test_robustness.EveryPublicParameterIsNormalisedOrExplicitlyExempt` derives both lists from the module,
  requires every other parameter to be PROVEN to arrive plain AT THE CALLEE (it asserts the ARGUMENT, not
  the name of the function called), and refuses an entry in `_PARAMETER_NO_SCALAR` whose own probe value
  turns out to be collapsible after all.
  ROUND 8 FOUND THE HALF OF THE CLASS THAT PROOF NEVER SWEPT, and it is recorded here because the
  sentence above was read as more than it was: `_plain_value` collapses a `str`/`int`/`float` SUBCLASS,
  and a DUCK-TYPED scalar of an unrelated class stores nothing to collapse, so it passed the boundary
  untouched. All four routes above came back through it, measured on both interpreters. The invariant that
  actually holds is a DISJUNCTION -- either the boundary collapses the value the object stores, or the
  call is refused -- so the boundary now also REFUSES, by type, a parameter annotated `int` / `float` /
  `str` that is handed an object storing no such scalar (`_annotated_scalar_parameters`), and
  `test_robustness._parameter_coverage_complaints` runs BOTH spellings, a subclass and a non-subclass
  liar, requiring collapse or refusal for each.
  What NEITHER boundary reaches, stated plainly: what a caller-supplied CALLABLE returns (normalised
  where it is consumed -- `_to_metric`, `_plain_measure`, `MeasureFixture.__post_init__` -- each with a
  consequence test), a closure variable of a PRIVATE helper that is not a parameter of anything public,
  and `object.__setattr__`.
* AND THE THIRD BOUNDARY, ROUND 12: the one every MESSAGE crosses. Normalisation makes the value a GATE
  reads the value the caller's object stores; it says nothing about the value a MESSAGE reads, and a
  message is built from `repr` / `str` / `format` / `type(x).__name__` -- four protocols the caller
  implements, applied at the moment this module has decided to refuse. MEASURED on both interpreters,
  through public callables with no `object.__setattr__`: 18 of 60 driven positions ended OUTSIDE the
  `(ValueError, TypeError, ArithmeticError)` family every probe declares, including `guarded`, whose
  docstring promise is that rejection becomes a `MetricValue`; four fail-closed handlers died building
  the reason string of the unmeasured seed they had already decided to record; and two probe ids,
  interpolated after a probe's measurements were complete, took the probe out with a `RuntimeError`.
  Worse than an escape, in `_run_cases`: `repr(v)` sat INSIDE the handler that decides whether the
  measure raised, so a failure in the RECORDING was recorded as the opposite outcome and a measure that
  answered all 15 missing-input cases with a value was CERTIFIED as handling them. The four protocols
  are spelled ONCE each now, in `_shown` and `_type_name`, which degrade to a placeholder rather than
  lose the refusal; every other diagnostic site in this file is decided in writing in
  `test_robustness._DIAGNOSTIC_SITES`, which re-derives the set from this module's AST and fails closed
  on a new one. See the comment block above `_shown`.
Honest limits: Python cannot make this impossible. `object.__setattr__`, `object.__new__`, and
SUBCLASSING `SeedSummary` / `InsufficientEvidence` with a `__post_init__` that skips the checks all build
unvalidated nested objects (a `Scorecard` still refuses such an object, via the exact-type check, but a
bare unvalidated subclass instance exists). `gc.get_referents` reaches the writable dict behind a
`MappingProxyType` (see `Scorecard`, limit (2)). `vars(obj)` / `obj.__dict__` is the SAME writable dict
for every frozen dataclass here, so a plain subscript assignment replaces any field of a built
`Scorecard` or `SeedSummary` (see `Scorecard`, limit (4)): this list named `object.__setattr__` and `gc`
and did not name the plainest spelling of the two, which is why it is written down now. Edits to module
constants also defeat the floor. The
guarantee is "no supported API path", not a security boundary. The same caveat applies to every "frozen"
claim below.

Scope notes, stated plainly:
* An INSUFFICIENT_EVIDENCE card still holds `per_seed`: the raw observations (including a lone
  measured datum). They are data, not a finding: no statistic, status other than INSUFFICIENT_EVIDENCE,
  or verdict is derived from them, and `details` is restricted to identification fields. Read them as
  "what was observed", never as a result.
* A constant outcome across >= min distinct seeds gives status MEASURED with SD 0.0 and the advisory
  `details.zero_variance_warning`. It is deliberately NOT downgraded: zero variance is the expected,
  correct reading for an exact invariance probe (all deviations are 0.0). The flag is a prompt to check
  that the outcome is not ignoring the seed, nothing more.
* Reorder-invariance assertions about `toy.stability` hold on CPython >= 3.12 because `sum()` of floats is
  compensated there. On an older interpreter (QA patched `sum` to a plain loop to confirm) even the default
  random-fixture reorder probe of `mse_naive` flips to INVARIANCE_DEFECT. The reorder result is therefore an
  environmental fact; every scorecard records `details.python_version` for that reason.
* Headline figures quoted in docs or reports (for example the plain-loop violation counts and deviations)
  are specific to the seed list that produced them and vary across seed lists; quote them with the list.
* Probes enumerate cases (missing-input cases, shifts, magnitudes). Anything not enumerated is untried.

Asymmetry stated plainly: one failing seed refutes an invariance, but no number of passing seeds proves
it; passes are "not refuted on these n synthetic fixtures". Scorecards never say more.
"""
from __future__ import annotations

import dataclasses
import functools
import hashlib
import inspect
import math
import sys
from enum import Enum
from fractions import Fraction
from types import MappingProxyType
from typing import Any, Callable, Mapping, Optional, Sequence

from toy import stability
from toy.benchmark import (_metric_ok, _metric_read, _plain_number, _plain_parameter, quantile,
                           sample_sd, seed_list_digest)
from toy.benchmark import mean as _mean
from toy.schema import (SCHEMA_VERSION, TOY_LABEL, EvidenceClass, ExperimentRecord, MetricValue, RunProvenance,
                        canonical_json, current_python_version, derive_seed, make_rng)
from toy.schema import _normalise_fields, _plain_value

CODE_VERSION = "toy-robustness-v1"
SEED_FLOOR = 3            # absolute minimum NUMBER of measured values (seeds) for any summary; not configurable below
DEFAULT_MIN_SEEDS = 10    # PROTOCOL PARAMETER (proposed default, arbitrary, no empirical basis)
EPS = sys.float_info.epsilon  # 2**-52
U = EPS / 2                    # unit roundoff 2**-53

Matrix = tuple
Mask = tuple
Measure = Callable[[Matrix, Matrix, Mask], float]

STANDARD_NON_CLAIMS = (
    "Nothing about RFdiffusion, the audited fork, or any real model.",
    "Not a safety claim and not evidence of safety, capability reduction, or robustness of any real system.",
    "Not an experiment of EVALUATION_PROTOCOL: a probe of a measurement procedure on synthetic fixtures.",
    "Seeds are replicates of a synthetic fixture generator, not independent samples of any real population.",
    "No claim from fewer seeds than the stated minimum; passes mean 'not refuted on these n fixtures'.",
    "On an INSUFFICIENT_EVIDENCE card per_seed holds raw observations only; they support no claim.",
)


# ======================================================= diagnostic construction
# THE THIRD ENUMERATION, derived the same mechanical way as the field list (`dataclasses.fields()`) and
# the parameter list (`inspect.signature`), and for the reason both of those exist: A MESSAGE IS CODE.
# The code that builds one runs on an object the CALLER supplied, usually at the exact moment this
# module has decided to refuse it -- so `repr`, `str`/`format` and `type(x).__name__` are three
# protocols a caller implements, applied where nothing has validated anything, and every one of them can
# RAISE instead of returning text. WHAT THAT COSTS, measured on this module before this round on 3.12.4
# and 3.13.5, through public callables with no `object.__setattr__`:
#   * the family escape. 60 driven positions gave TALLY {RET 20, IN 22, OUT 18}: 18 outcomes OUTSIDE
#     the `(ValueError, TypeError, ArithmeticError)` family every probe declares. A caller-callable's
#     return whose `__repr__` raises `RuntimeError`/`KeyError` escaped from `probe_missing_inputs`,
#     `assert_no_silent_default`, `guarded`, `probe_shift` and `require_summary` -- `guarded`'s own
#     docstring promise ("rejection becomes `MetricValue.unmeasured(reason)` instead of an exception")
#     breached outright -- and a metaclass answering `__name__` with a raising property escaped from
#     `make_measure_fixture`, `probe_precision`, `shift_scale`, `seed_sensitivity_probe`,
#     `arm_difference` (x2), `deep_freeze` and `probe_missing_inputs`. Three of those eight were the
#     PARAMETER BOUNDARY'S OWN refusal message, and one was round 11's own new `TypeError` in
#     `_run_cases`: the fix's refusal escaped the family it was written to honour.
#   * THE FAIL-CLOSED HANDLER DEFEATED WHILE IT IS HANDLING CORRECTLY, which is the sharper half and the
#     shape round 16 found one module over on VALID input. An exception whose OWN `__str__` raises is
#     caught by `probe_shift` / `probe_precision` / `seed_sensitivity_probe` / `guarded`, all four of
#     which then die building `f"{type(e).__name__}: {e}"` -- the reason string of the unmeasured seed
#     the handler had already decided to record. And on the fully VALID path, after a probe has finished
#     measuring: `f"shift:{measure.__name__}:{spec.name}"` is a bare interpolation of two caller-owned
#     objects, so a callable object whose `__name__` has a raising `__format__`, or a duck-typed
#     `ShiftSpec` whose `name` has one, took `probe_shift`, `probe_missing_inputs` and
#     `scorecard_to_record` out with `RuntimeError` while LABELLING a card whose measurements were
#     already complete.
#   * the forged DIAGNOSTIC. `_run_cases` recorded `repr(v)` of a measure's unvalidated return, and
#     `assert_no_silent_default` reads that text to name a returned 0.0 -- "the most dangerous
#     substitution", by its own docstring. A `float` SUBCLASS storing 0.0 whose `__repr__` answers "1.0"
#     moved the `[SILENT ZERO]` tag count from 45 of 45 to 0 of 45 while the complaint still fired.
# SO: a caller's object is described in ONE place, `_shown` (which also covers `str`/`format`, via
# `how=str`), named by type in ONE place, `_type_name`, and asked for its own `__name__` in ONE place,
# `_name_attr`. The first two DEGRADE to a placeholder instead of losing the refusal, because the
# exception TYPE -- what a caller branches on -- matters and the description does not; the third
# REFUSES in family, because a card's label is not a description and cannot be a placeholder. Every
# other diagnostic site in this file is decided in writing by `test_robustness._DIAGNOSTIC_SITES`,
# which re-derives the set from this file's AST -- module body, class bodies, functions AND lambdas --
# and fails closed on a new one. The counts it re-derives and asserts, 75 sites in 79 occurrences:
#   `{x!r}`            -- 8 sites. Every one is a plain `str`/`int`/`float`: SIX by the PARAMETER
#                         BOUNDARY (measured -- with the boundary off, those six are exactly the
#                         positions an undescribable value escapes from), ONE by an `isinstance` gate
#                         plus `_plain_value` in the same function (`arm_difference`'s arm name), and
#                         ONE a parameter NAME this module read off its own signature. [decided]
#   repr()             -- 1 call, `_silent_detail`, on the plain double `_plain_number` returned.
#                         That one is load-bearing and NOT a description: it is what makes the
#                         `[SILENT ZERO]` tag unforgeable.                                [decided]
#   bare `{x}`         -- 60 sites, of which 35 interpolate a string one of the three helpers above
#                         already built, 19 this module's own data (a constant, a `len()`, a literal
#                         field name), 4 a boundary-plain scalar and 2 a gated one.        [routed]
#   type(x).__name__   -- 5 sites: ONE read, in `_type_name`; three assignments or reads of this
#                         module's own function objects; one annotation text from a signature it
#                         wrote itself.                                                   [routed]
#   getattr(x,"__name__") -- 1 site, in `_name_attr`.                                     [routed]
#   `{x!s}` / `{x!a}`  -- 0. Both run a caller's protocol and both belong in `_shown`.    DISCHARGED
# NOT re-decided here, because the parameter boundary already answers it and an attester re-measured
# the answer: this module's own `float()` calls (9 by AST, 8 live) are all on values already plain, or
# `_plain_parameter`-collapsed, or annotated `float`/`int` and so refused by
# `_annotated_scalar_parameters` when they store no scalar. The one exception,
# `scorecard_to_record`'s `float(sc.min_seeds)` on a hand-built namespace, is already a `_WHY_CARRIER`
# note. `len()` is taken 40 times, every one on a tuple or list this module built.
# AND WHAT THIS DOES NOT CLOSE, stated with its measurement rather than left for the next round to
# find: a raising ATTRIBUTE LOOKUP on a caller's object. A duck-typed `ShiftSpec` whose `name` is a
# `property` that raises `RuntimeError` still takes `probe_shift` outside the declared family --
# measured on both interpreters -- and so does any other field of any carrier this module reads,
# because reading an attribute runs code the caller wrote. It is not closable by a check here, for the
# same reason the raising-`__class__` channel is held open kit-wide (an `isinstance` call is itself the
# lookup), and it is a different channel from this one: `type(x)` ignores a `__class__` property and
# `_name_attr` converts the ONE attribute read whose only consumer is a label. Pinned as OPEN by
# `test_robustness.EveryDiagnosticInThisModuleIsDecidedInWriting`
# `.test_the_adjacent_attribute_channel_is_stated_and_left_open`.
_UNCONVERTED = (MemoryError, RecursionError, SystemError)   # spelled as in `toy.stability`, same policy


def _shown(v: Any, how=repr) -> str:
    """`repr(v)` -- or `str(v)`, with `how=str` -- for a MESSAGE, degraded when the caller's own
    protocol raises instead of describing the object.

    A message is DIAGNOSTIC. Losing a refusal because the object being refused cannot describe itself
    is strictly worse than losing the description, and the exception TYPE, which is what every probe's
    `except (ValueError, TypeError, ArithmeticError)` branches on, is unaffected either way. This is the
    same helper, with the same policy, as `toy.stability._shown`; it is written here rather than
    imported because that module is another owner's and this one must not depend on its internals.
    `how=str` is the spelling for a bare `{x}` interpolation, including `{e}` of a caught exception --
    which is the position where a raising `__str__` defeated four fail-closed handlers while they were
    handling correctly. `BaseException`-only exits and `_UNCONVERTED` still propagate."""
    try:
        return how(v)
    except _UNCONVERTED:
        raise
    except Exception as e:      # noqa: BLE001 -- the point of the helper
        return f"<undescribable {_type_name(v)}: {_type_name(e)} raised while describing it>"


def _type_name(v: Any) -> str:
    """`type(v).__name__` for a message, degraded the same way `_shown` is.

    `type(v)` is safe -- it ignores a `__class__` property, which is why the raising-`__class__` channel
    is a SEPARATE and still-open finding rather than this one -- but `__name__` on the resulting class
    is an attribute lookup, and a metaclass can answer it with an exception. Measured: eight public
    positions, three of them the parameter boundary's own refusal message."""
    try:
        return type(v).__name__
    except _UNCONVERTED:
        raise
    except Exception:           # noqa: BLE001 -- the point of the helper
        return "<unnamed type>"


def _name_attr(fn: Any, default: str) -> Any:
    """`fn.__name__` where there is one, `default` where there is none -- and a REFUSAL, inside the
    family every probe declares, where READING it raises.

    THE SITE THE FIRST DERIVATION OF THIS ROUND MISSED, and it is recorded because the miss is the
    lesson: the derived set covered `repr` / `str` / `format` / `type(x).__name__` and
    `getattr(x, "__name__")` is none of the four, so four public positions stayed open while a
    set-equality check over the other seventy reported success. `getattr`'s third argument only answers
    an `AttributeError`: a class whose `__name__` is a PROPERTY that raises anything else propagates.
    MEASURED on 3.12.4 and 3.13.5, with a callable OBJECT (not a function -- a function's `__name__` is
    a plain `str` slot) whose class answers `__name__` with a raising property: `probe_shift`,
    `probe_missing_inputs`, `seed_sensitivity_probe` and `guarded` all propagated `RuntimeError`.
    A `ValueError` rather than a placeholder, and that asymmetry with `_shown` / `_type_name` is
    deliberate: those two describe an object this module has ALREADY decided about, so degrading the
    description costs nothing, while this one is the LABEL a card carries and a card cannot honestly
    carry a name whose source refused to be read."""
    try:
        return getattr(fn, "__name__", default)
    except _UNCONVERTED:
        raise
    except Exception as e:      # noqa: BLE001 -- the point of the helper
        raise ValueError(f"reading __name__ of a supplied callable raised {_type_name(e)}: a probe "
                         "labels its card with that name and will not take it from an attribute that "
                         "refuses to be read") from None


def _callable_name(fn: Any) -> str:
    """The text a card LABELS a caller's callable with, as a string THIS module built.

    `getattr(fn, "__name__", "measure")` returns whatever object the caller put there: a FUNCTION's
    `__name__` must be a `str`, but a callable OBJECT's can be anything, and the two probe ids that
    interpolate it are built on the VALID path, after every measurement of the probe is complete.
    MEASURED on both interpreters before this round: with a callable object whose `__name__` has a
    raising `__format__`, `probe_shift` and `probe_missing_inputs` both propagated `RuntimeError` out of
    a finished probe -- the shape round 16 found one module over, where a message on a correct path
    replaced the module's own outcome.
    `details["measure"]` deliberately keeps the RAW object instead of calling this: `deep_freeze` refuses
    a non-`str` there with a `ValueError`, inside the family every probe declares, and a card refusing to
    carry an object that only pretends to be a name is the right outcome. This helper is for the LABEL,
    and widening it to the field would turn a refusal into an acceptance."""
    return _shown(_name_attr(fn, "measure"), how=str)


def _enum_value(e: Enum) -> Any:
    """Read an `Enum`'s payload.

    This exists only so that the convention held on both this module and `toy.benchmark` -- no attribute
    access named `value` or `is_measured` anywhere, so that the set of stored-metric reads does not have
    to be listed by a reader (see `toy.benchmark`'s `_metric_read` section header) -- needs NO ALLOWLIST.
    `Enum.value` and `MetricValue.value` are indistinguishable by attribute name, so an allowlist would
    have to be hand-maintained, which is exactly the failure mode of the previous rounds' fixes. Here an
    `Enum` payload is spelled `_enum_value(e)` and a stored metric `_metric_read(m)`.
    WHAT ENFORCES THAT, STATED AS WHAT IT IS: a bare `x.value` in either module is caught by the STATIC
    TRIPWIRE in `test_benchmark.TheStaticSpellingRuleIsATripwireNotAGuarantee`, which catches a MEASURED
    11 of 19 spellings of the same read -- it is a tripwire, not a guarantee, and this docstring used to
    describe it as one. What the modules actually rest on is the runtime recording probe in
    `test_benchmark.TheCheckedReaderIsTheOnlyWayToReadAStoredMetric` (blind to
    `object.__getattribute__` / `gc` and to paths its run does not reach) and, load-bearing, the per-site
    consequence tests in `EveryMetricReadSiteIsPinnedByItsConsequence` below.
    The `isinstance` check here is not decoration: it is what stops this function being used as a way
    around the metric reader."""
    if not isinstance(e, Enum):
        raise ValueError(f"_enum_value expects an Enum, got {_type_name(e)} "
                         "(a MetricValue is read with _metric_read, never here)")
    return getattr(e, "value")


class InsufficientEvidenceError(ValueError):
    """Raised by `require_summary` when asked for a scalar that does not exist."""


class SilentDefaultError(AssertionError):
    """Raised by `assert_no_silent_default` when a measure returned a value for an input it should reject."""


class ProbeStatus(str, Enum):
    """Structured verdict-like status of a probe. About a *measure's behaviour*, never about safety."""
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    MEASURED = "MEASURED"                          # descriptive distribution only
    INVARIANCE_HOLDS = "INVARIANCE_HOLDS"          # not refuted on these seeds
    INVARIANCE_DEFECT = "INVARIANCE_DEFECT"        # a declared invariance failed: defect in the measure
    SENSITIVITY_WITHIN_BOUND = "SENSITIVITY_WITHIN_BOUND"
    SENSITIVITY_EXCEEDS_BOUND = "SENSITIVITY_EXCEEDS_BOUND"
    MISSING_INPUT_HANDLED = "MISSING_INPUT_HANDLED"
    SILENT_DEFAULT_DEFECT = "SILENT_DEFAULT_DEFECT"
    PRECISION_OK = "PRECISION_OK"
    PRECISION_LOSS = "PRECISION_LOSS"


# =========================================================== seed policy and summary
@dataclasses.dataclass(frozen=True)
class ProbeConfig:
    min_seeds: int = DEFAULT_MIN_SEEDS

    _NORMALISE_EXEMPT = MappingProxyType({})

    def __post_init__(self) -> None:
        _normalise_fields(self)    # at the boundary, before any gate; see `toy.schema._normalise_fields`
        if isinstance(self.min_seeds, bool) or not isinstance(self.min_seeds, int):
            raise ValueError("min_seeds must be an int")
        # NORMALISE BEFORE COMPARING, and store what was compared. MEASURED defect: `self.min_seeds <
        # SEED_FLOOR` is `type(min_seeds).__lt__`, so an `int` SUBCLASS returning False from `__lt__`
        # passed this gate with a stored value of 1 -- through the PUBLIC constructor, with no
        # `object.__setattr__` -- and `summarize_seeds(per_seed, cfg.min_seeds)` then summarised 3 of 10
        # measured values as if the configured minimum were 1. `SEED_FLOOR` itself still held, because
        # `SeedSummary.from_values` compares a `len()`, which is not overridable; the CONFIGURED minimum did
        # not. Same inspect-before-normalise pattern as `toy.benchmark._check_margin`; see
        # `toy.benchmark._plain_number` for the measurement that found the class.
        object.__setattr__(self, "min_seeds", int.__int__(self.min_seeds))
        if self.min_seeds < SEED_FLOOR:
            raise ValueError(f"min_seeds must be >= {SEED_FLOOR} (absolute floor: no claims from single examples)")


def _pcfg(cfg: Optional[ProbeConfig]) -> ProbeConfig:
    """Resolve a `cfg=None` probe argument to a FRESHLY CONSTRUCTED `ProbeConfig()`.

    Every probe takes `cfg: Optional[ProbeConfig] = None` rather than a literal `cfg = ProbeConfig()`. A
    literal default object is evaluated ONCE at import, so every call that omits the argument shares that one
    instance. `ProbeConfig` is frozen, so ordinary code cannot mutate it -- but this kit's own threat model
    and tests use `object.__setattr__` to simulate tampering (see `Scorecard`'s honest limits), and that
    reaches through the freeze into the shared default. One
    `object.__setattr__(<shared default>, "min_seeds", 1)` would defeat the `SEED_FLOOR` policy for every
    later no-argument probe call in the process, which is exactly the "no claims from single examples"
    guarantee this module is built around. Identical defect class as `toy.benchmark`'s `_cfg` / `_margins`,
    where it was measured to flip a verdict from SUPPORTED to UNSUPPORTED."""
    return ProbeConfig() if cfg is None else cfg


@dataclasses.dataclass(frozen=True)
class InsufficientEvidence:
    """Explicit 'no number' result. Deliberately has NO mean/sd/min/max attributes."""
    n_measured: int
    n_required: int
    reason: str

    _NORMALISE_EXEMPT = MappingProxyType({})

    def __post_init__(self) -> None:
        _normalise_fields(self)    # at the boundary; the hand-placed loop below is now redundant and kept
        # NORMALISE BEFORE COMPARING, and store what was compared (see `ProbeConfig.__post_init__`):
        # `n_measured >= n_required` is an overridable comparison on two fields a direct caller supplies,
        # and `Scorecard.__post_init__` then compares `n_required` with its own `min_seeds`. No verdict
        # or statistic depends on these (an INSUFFICIENT_EVIDENCE card has neither, by type), so this
        # closes a wrong-counts-on-a-card route rather than a verdict route -- stated as what it is.
        for k in ("n_measured", "n_required"):
            v = getattr(self, k)
            if isinstance(v, int) and not isinstance(v, bool) and type(v) is not int:
                object.__setattr__(self, k, int.__int__(v))
        if self.n_measured >= self.n_required:
            raise ValueError("InsufficientEvidence requires n_measured < n_required")
        if not isinstance(self.reason, str) or not self.reason.strip():
            raise ValueError("reason must be a nonblank string")

    def to_dict(self) -> dict:
        return {"status": _enum_value(ProbeStatus.INSUFFICIENT_EVIDENCE), "n_measured": self.n_measured,
                "n_required": self.n_required, "reason": self.reason}


@dataclasses.dataclass(frozen=True)
class SeedSummary:
    """Distribution of an outcome over >= SEED_FLOOR measured seeds. Cannot be built from fewer.
    Scale assumption (cites the floor documented in `toy.benchmark.sample_sd`): SD is exactly 0.0 for a
    constant sample, but a NON-constant sample whose true SD is below ~2.47e-324 (half the smallest
    subnormal) also reports 0.0, because the true value is unrepresentable. Every built-in probe feeds
    O(1)-scale quantities (seed outcomes of the benchmark scorer, relative deviations >= 0 down to ~1e-17 or
    exactly 0.0, relative errors, integer counts), so no built-in probe can reach that floor.
    `details.zero_variance_warning` does not use SD at all: it tests `len(set(values)) == 1`, which is exact
    for any scale, so it is unaffected by the floor even for user-supplied subnormal-scale outcomes.
    Known unguarded corner: finite values near the float maximum are accepted (e.g. three copies of 1.7e308)
    and such a summary serializes; no overflow check is made on the statistics beyond finiteness."""
    n: int
    mean: float
    sd: float
    q1: float
    q3: float
    iqr: float
    minimum: float
    maximum: float
    values: tuple

    _NORMALISE_EXEMPT = MappingProxyType({})

    def __post_init__(self) -> None:
        _normalise_fields(self)    # at the boundary; `_plain_summary_fields` below is kept because
        # `_recheck_summary` calls it on objects built by `object.__new__`, which never ran this method
        vals = tuple(self.values)
        if len(vals) < SEED_FLOOR:
            raise ValueError(f"a summary needs >= {SEED_FLOOR} measured seeds, got {len(vals)} "
                             "(single-example claims are structurally refused)")
        for v in vals:
            if isinstance(v, bool) or not isinstance(v, float) or not math.isfinite(v):
                raise ValueError("summary values must be finite floats")
        object.__setattr__(self, "values", vals)
        vals = _plain_summary_fields(self)          # normalise before comparing; see `_plain_summary_fields`
        object.__setattr__(self, "values", vals)
        exp = _stats(vals)
        got = (self.n, self.mean, self.sd, self.q1, self.q3, self.iqr, self.minimum, self.maximum)
        if got != exp:
            raise ValueError("summary statistics do not match the per-seed values")

    @classmethod
    def from_values(cls, values: Sequence[float]) -> "SeedSummary":
        """Build a summary from a sequence of real numbers.

        ACCEPTED NUMERIC CONTRACT, decided and stated here (pinned by
        `test_robustness.test_from_values_numeric_type_contract`): a value is accepted iff its TYPE provides
        `__float__` or `__index__` AND it is not a `bool` -- so `float`, `int`, `decimal.Decimal`,
        `fractions.Fraction` and any other `numbers.Real` are accepted and converted with `float(v)`.
        Everything else raises `ValueError`, INCLUDING two types that used to slip through:
        * `bool`: refused so that the three places that judge a boolean now agree. `SeedSummary.__post_init__`
          rejects `isinstance(v, bool)` and `_to_metric` records a bool outcome as UNMEASURED, but
          `from_values([True, False, True])` used to SUCCEED, silently coercing to 1.0/0.0. A boolean is never
          a measurement anywhere in this kit.
        * `str` / `bytes`: refused because `float("1")` succeeds, so `from_values(["1","2","3"])` used to
          return a summary of (1.0, 2.0, 3.0). A number parsed out of text is not a measurement either.
        Only a DIRECT caller can reach either case: `summarize_seeds` feeds `MetricValue.value`, and
        `MetricValue` already accepts finite floats only (no int/bool coercion).
        Conversion failures keep the documented `ValueError` family: an int too large for float (10**400)
        raises `ValueError`, never `OverflowError`, and no raised error chains a context (`from None`)."""
        # NOTE: toy.benchmark.sample_sd's docstring cites this cast as the reason the "Python ints beyond 2**53"
        # limit is unreachable from SR-11 (every value is cast to float here, and SeedSummary.__post_init__
        # rejects non-float values). Keep the cast; if it moves, update that citation.
        out = []
        for v in values:
            t = type(v)
            if isinstance(v, bool) or not (hasattr(t, "__float__") or hasattr(t, "__index__")):
                raise ValueError(
                    f"values must be real numbers, got {_type_name(v)}: bool and str are refused on purpose "
                    "(a boolean outcome and a number parsed out of text are not measurements)") from None
            try:
                # `float.__float__` for a value that ALREADY IS a float, `float(v)` for everything else
                # (Decimal, Fraction, int). A bare `float(v)` consults a `__float__` OVERRIDE, so a
                # `float` subclass could store 1.0 -- which is the number `SeedSummary.__post_init__` and
                # `math.isfinite` inspect -- and convert to 1e308, which is the number every statistic
                # would then be computed from. Same inspect-before-normalise pattern as
                # `toy.benchmark._check_margin`; see `toy.benchmark._plain_number`.
                out.append(float.__float__(v) if isinstance(v, float) else float(v))
            except OverflowError:   # e.g. 10**400: keep the documented ValueError family
                raise ValueError("a value is too large to represent as a finite float") from None
            except (TypeError, ValueError) as e:
                raise ValueError(f"values must be real numbers: {_shown(e, how=str)}") from None
        vals = tuple(out)
        if len(vals) < SEED_FLOOR:
            raise ValueError(f"a summary needs >= {SEED_FLOOR} measured seeds, got {len(vals)}")
        return cls(*_stats(vals), values=vals)

    def to_dict(self) -> dict:
        return {"n": self.n, "mean": self.mean, "sd": self.sd, "q1": self.q1, "q3": self.q3, "iqr": self.iqr,
                "min": self.minimum, "max": self.maximum, "values": list(self.values)}


_SUMMARY_SCALARS = ("mean", "sd", "q1", "q3", "iqr", "minimum", "maximum")


def _plain_summary_fields(obj) -> tuple:
    """Collapse any `int`/`float` SUBCLASS among a summary's fields to the plain value it STORES, and
    return the normalised `values` tuple.

    WHY, in one sentence: the values checked must be the values stored, serialized and compared. A `float`
    subclass satisfies `isinstance(v, float)` and need not lie to `math.isfinite`, yet can override
    `__eq__` -- which is the operator the "statistics match the values" invariant is written in -- and
    `__float__`, which `to_dict` / `canonical_json` would consult. Same inspect-before-normalise pattern as
    `toy.benchmark._check_margin`; see `toy.benchmark._plain_number` for the measurement that found it."""
    for k in _SUMMARY_SCALARS:
        x = getattr(obj, k)
        if isinstance(x, float) and type(x) is not float:
            object.__setattr__(obj, k, float.__float__(x))
    n = getattr(obj, "n")
    if isinstance(n, int) and not isinstance(n, bool) and type(n) is not int:
        object.__setattr__(obj, "n", int.__int__(n))
    return tuple(v if type(v) is float else float.__float__(v) for v in obj.values)


def _plain_text(s: Any) -> Any:
    """Collapse a `str` SUBCLASS to the plain text it STORES; anything else is returned unchanged.

    MEASURED AND DECIDED, because the answer looks like a contradiction of this kit's own standard: with
    `toy.schema._normalise_fields` now running first in `Scorecard.__post_init__`, a mutant removing
    EITHER of this function's two call sites there is UNKILLED by `test_schema` / `test_robustness` (188
    tests, CPython 3.13.5), and the same holds for `_plain_summary_fields`'s call in
    `SeedSummary.__post_init__`. The calls are KEPT, and the distinction from the cast round 5 REFUSED to
    add in `_to_metric` is the whole reason: that one never carried a guarantee at all, so adding it would
    have been decoration a reviewer could mistake for a defence. These DID carry the guarantee, alone, for
    a round -- and would again if the boundary regressed. Their removal is unobservable because something
    STRONGER covers them, not because they never did anything, and "the only mechanism is the one added
    last week" is not a property to engineer for. What matters is that neither is any longer the thing a
    reader has to REMEMBER: coverage is asserted from `dataclasses.fields()` by
    `test_robustness.EveryDataclassFieldIsNormalisedOrExplicitlyExempt`.

    The `str` sibling of `toy.benchmark._plain_number` / `_plain_parameter`, and it exists for the same
    reason: a `str` subclass passes `isinstance(v, str)`, `v.strip()` and a regex, and can still override
    `__eq__` / `__ne__` / `__hash__` -- which are the operators this module's text guards are written in.
    `str.__str__` reads the characters the object actually holds (a `__str__` override is not consulted),
    so the text checked is the text stored and serialized. MEASURED on two guards, through
    `dataclasses.replace`, the same route this module's own tampering tests use:
      * `does_not_establish`: `for std in STANDARD_NON_CLAIMS: if std not in dne` is `==` over the
        tuple's elements, so a card whose non-claims were the single string "THIS IS A SAFETY FINDING."
        satisfied "must include every STANDARD_NON_CLAIMS entry" and serialized that text as its
        disclaimers -- the one thing every scorecard in this kit is required to carry.
      * `seed_digest`: `self.seed_digest != seed_list_digest(seeds)` accepted a digest of "0"*64 over a
        real seed list, and `scorecard_to_record` then wrote it into the record's
        `input_hashes["seed_list"]`, i.e. into the provenance anchor a reader would check the seeds
        against."""
    return str.__str__(s) if isinstance(s, str) and type(s) is not str else s


def _stats(vals: tuple) -> tuple:
    s = sorted(vals)
    q1, q3 = quantile(s, 0.25), quantile(s, 0.75)
    return (len(vals), _mean(vals), sample_sd(vals), q1, q3, q3 - q1, s[0], s[-1])


def summarize_seeds(per_seed: Sequence[MetricValue], min_seeds: int = DEFAULT_MIN_SEEDS):
    """SeedSummary if >= min_seeds measured values, else InsufficientEvidence. Never a bare scalar."""
    # The returned object is USED, not discarded: `ProbeConfig.__post_init__` both enforces the floor and
    # NORMALISES `min_seeds`, and `len(measured) < min_seeds` below is an overridable comparison on whatever
    # object the caller passed. An `int` subclass whose `__lt__` returns False used to clear the floor here
    # and reach this function's own comparison unnormalised -- so an InsufficientEvidence(3 of 10) became a
    # SeedSummary(n=3) with a configured minimum of 10. See `ProbeConfig.__post_init__`.
    min_seeds = ProbeConfig(min_seeds).min_seeds
    per_seed = tuple(per_seed)
    # `type(m) is not MetricValue`, NOT `isinstance`: round 6 closed exactly this inconsistency in
    # `Scorecard.__post_init__` (honest limit (3) of its docstring) and left this sibling consumer --
    # which the parameter boundary's own `_WHY_CARRIER_SEQ` claims ALSO refuses anything that is not
    # exactly a `MetricValue` -- on `isinstance`. The round-11 reason-coverage probe, which exercises a
    # declared reason on EVERY parameter it covers instead of on a sample of them, falsified that claim
    # here. MEASURED on 3.12.4 and 3.13.5, through this public function and `require_summary`, with no
    # `object.__setattr__` and no forged field: a `MetricValue` SUBCLASS whose `__getattribute__` answers
    # `value` with 1.0, constructed as `Sub(None, None)` --
    #     honest `MetricValue.unmeasured(...)` x12 -> InsufficientEvidence(0 measured of 12; minimum 10)
    #     the subclass            x12 -> SeedSummary(n=12, mean=1.0, sd=0.0), and `require_summary`
    #                                    hands out that scalar
    # STATED AT ITS REAL WEIGHT, because the first wording of this comment overstated it and the
    # measurement is what corrected it: this is a REASON CORRECTION and a sibling-consistency fix, NOT a
    # status flip. `__post_init__` reads the lying `value` and then stores it, so after construction the
    # object honestly holds 1.0 -- a caller who can build `Sub(None, None)` can write
    # `MetricValue.measured(1.0)` and get the identical object, so the subclass grants them nothing they
    # lack. The two-faced variant that WOULD matter (a subclass whose `to_dict` serialises `unmeasured`
    # while `_metric_read` answers 1.0) was measured too: it produces such a summary, and
    # `build_scorecard` refuses it one level down, so no card can publish the disagreement. What was
    # actually wrong is that three sibling checks in one module disagreed about the same rule while a
    # declared reason asserted they did not.
    if not all(type(m) is MetricValue for m in per_seed):
        raise ValueError("per_seed must be MetricValues (absence must be explicit, never a number); "
                         "subclasses are refused, as on a Scorecard")
    measured = [v for v in (_metric_read(m) for m in per_seed) if v is not None]
    if len(measured) < min_seeds:
        return InsufficientEvidence(
            len(measured), min_seeds,
            f"{len(measured)} measured of {len(per_seed)} seeds; minimum is {min_seeds}")
    return SeedSummary.from_values(measured)


def require_summary(result) -> SeedSummary:
    """Loud accessor: raises unless `result` is a real SeedSummary."""
    if isinstance(result, SeedSummary):
        return result
    raise InsufficientEvidenceError(f"no scalar summary exists: {_shown(result)}")


def _recheck_summary(s) -> None:
    """Re-run SeedSummary validation on an existing object (replace() does not re-run nested validators,
    and a subclass could have skipped them)."""
    if type(s) is not SeedSummary:
        raise ValueError("summary must be exactly a SeedSummary (subclasses are refused)")
    vals = tuple(s.values)
    if len(vals) < SEED_FLOOR:
        raise ValueError(f"summary holds fewer than {SEED_FLOOR} values")
    for v in vals:
        if isinstance(v, bool) or not isinstance(v, float) or not math.isfinite(v):
            raise ValueError("summary values must be finite floats")
    vals = _plain_summary_fields(s)       # a card can be handed an object built by object.__new__
    object.__setattr__(s, "values", vals)
    if (s.n, s.mean, s.sd, s.q1, s.q3, s.iqr, s.minimum, s.maximum) != _stats(vals):
        raise ValueError("summary statistics do not match the per-seed values (tampered?)")


def _recheck_insufficient(x) -> None:
    if type(x) is not InsufficientEvidence:
        raise ValueError("insufficient must be exactly an InsufficientEvidence (subclasses are refused)")
    if (isinstance(x.n_measured, bool) or isinstance(x.n_required, bool) or not isinstance(x.n_measured, int)
            or not isinstance(x.n_required, int) or x.n_measured >= x.n_required):
        raise ValueError("InsufficientEvidence requires int n_measured < n_required")
    if not isinstance(x.reason, str) or not x.reason.strip():
        raise ValueError("reason must be a nonblank string")


def _check_seeds(seeds: Sequence[int]) -> tuple:
    """Validate a seed list and return it AS PLAIN INTS. The returned tuple is what every probe stores.

    NORMALISE BEFORE COMPARING. `len(set(seeds)) != len(seeds)` is the module docstring's named defence
    against one example repeated -- and `set()` is `__hash__` plus `__eq__`, both overridable on an `int`
    SUBCLASS. MEASURED, with no `object.__setattr__` and through every public probe:

        class Seed(int):
            def __hash__(self):   return id(self)
            def __eq__(self, o):  return self is o
            def __ne__(self, o):  return self is not o
        probe_shift(mse_fsum, shift_reorder_rows(), [Seed(7)] * 3, ProbeConfig(3))

    was ACCEPTED with status INVARIANCE_HOLDS, n=3 and `violating_seeds=()`, while the plain list
    `[7, 7, 7]` is correctly refused -- so `SEED_FLOOR = 3` was satisfied by ONE seed, which is SR-11's
    acceptance criterion ("no claims based on single examples") breached directly. The `outcome` callback
    really was called three times with 7, and `make_measure_fixture(Seed(7))` is the identical fixture.
    The card was self-incriminating (it serialises `[7, 7, 7]` and its `seed_digest` matches that), but
    the guard whose whole job is to refuse the list did not, and the decisive status was produced.
    `int.__int__` reads the value the object STORES -- the same value `make_rng` validated and
    `seed_list_digest` hashes -- so the comparison, the fixtures, the stored list and the digest are all
    on one number. `make_rng` is kept as the validator (bool, range, type) and runs FIRST, because
    `int.__int__` would happily normalise a value this module must refuse outright."""
    seeds = tuple(seeds)
    for s in seeds:
        make_rng(s)  # public validation: nonnegative int <= 2**64-1, bool rejected
    seeds = tuple(int.__int__(s) for s in seeds)   # store what was checked; see above
    if len(set(seeds)) != len(seeds):
        raise ValueError("duplicate seeds are rejected: repeating one example does not add evidence")
    return seeds


def _plain_measure(v: Any, what: str) -> float:
    """A number a probe COMPUTES WITH (a measure's return, a declared expectation) as a plain `float`.

    Raises `ValueError` -- inside every probe's own `except (ValueError, TypeError, ArithmeticError)`,
    so the seed is recorded as unmeasured with a reason, never as a number. See `probe_shift` for the
    measurement that made this necessary, and `toy.benchmark._plain_number` for the normaliser."""
    f = _plain_number(v)
    if f is None:
        raise ValueError(f"{what} is not a finite real number: {_shown(v)}")
    return f


def _to_metric(outcome: Callable[[int], float], seed: int) -> MetricValue:
    """Record a user `outcome` callback's return as a MetricValue. Absence is explicit, never 0.0.

    WHY THERE IS NO `float.__float__` HERE, decided and MEASURED rather than left to look like an
    oversight (`SeedSummary.from_values`, 90 lines up, does cast, and the asymmetry is deliberate):
    this function only ever CHECKS and STORES `v`; it never compares or computes with it. Both of its
    checks read the double the object stores -- `isinstance` cannot be fooled by a float subclass and
    `math.isfinite` consults no `__float__` override for a float instance -- and
    `MetricValue.__post_init__` now stores that same double (see `toy/schema.py`), so the number
    checked, stored, serialized and compared are one number without a cast here. This WAS a live hole,
    and a worse-shaped one than the SR-10 entry point: the schema's `value == 0.0` normalisation
    REPLACED the stored value, so a user `outcome` returning a float subclass with a lying `__eq__`
    turned `seed_sensitivity_probe(outcome, range(1, 11))` from `mean=7.55 sd=0.303` into `mean=0.0
    sd=0.0 zero_variance_warning=True` -- at a public probe's data-intake point. It was fixed at the
    schema, not here, because this site stores and the schema is what stores; a cast here is measured
    to be unobservable now (a mutant removing it survives every test), and `_pair_from_record`'s
    comment states the rule: a guard whose removal changes no output is not a guard. Contrast
    `probe_shift`, which DOES normalise at intake, because it subtracts and compares before any
    MetricValue exists."""
    try:
        v = outcome(seed)
    except (ValueError, TypeError, ArithmeticError) as e:
        return MetricValue.unmeasured(f"{_type_name(e)}: {_shown(e, how=str)}")
    if isinstance(v, bool) or not isinstance(v, float):
        return MetricValue.unmeasured(f"outcome must be a float, got {_type_name(v)}")
    if not math.isfinite(v):
        return MetricValue.unmeasured("outcome is non-finite")
    return MetricValue.measured(v)


# ============================================================= immutable freezing
def deep_freeze(x: Any) -> Any:
    """Defensive deep copy into read-only containers: Mapping -> MappingProxyType (str keys, sorted),
    list/tuple -> tuple, scalars str/int/float(finite)/bool/None as-is, Enum -> value."""
    if isinstance(x, Enum):
        return _enum_value(x)
    if x is None or isinstance(x, (bool, int, str)):
        return x
    if isinstance(x, float):
        if not math.isfinite(x):
            raise ValueError("non-finite float cannot be stored in a scorecard")
        return x
    if isinstance(x, Mapping):
        for k in x:
            if not isinstance(k, str):
                raise ValueError(f"scorecard mapping keys must be str, got {_type_name(k)}")
        return MappingProxyType({k: deep_freeze(x[k]) for k in sorted(x)})
    if isinstance(x, (list, tuple)):
        return tuple(deep_freeze(v) for v in x)
    raise ValueError(f"cannot freeze {_type_name(x)} into a scorecard")


def thaw(x: Any) -> Any:
    if isinstance(x, Mapping):
        return {k: thaw(v) for k, v in x.items()}
    if isinstance(x, tuple):
        return [thaw(v) for v in x]
    return x


# ===================================================================== Scorecard
@dataclasses.dataclass(frozen=True)
class Scorecard:
    """Immutable record of one probe. Frozen dataclass; containers are read-only (MappingProxyType / tuple),
    copied defensively at construction.

    HONEST LIMITS -- the routes THIS MODULE KNOWS OF, which is not a claim that they are all of them
    (Python cannot make this impossible, and a sweep for routes cannot establish that none is left; this
    sentence used to say "the complete list of routes known to this module" and a round-6 attestation
    falsified it with a third, (3) below):
    (1) `object.__setattr__` bypasses the freeze and replaces any field outright.
    (2) `gc.get_referents(card.details)[0]` returns the WRITABLE dict behind the `MappingProxyType`, so
        `gc.get_referents(card.details)[0]["injected"] = 1` adds a key to `details` and changes
        `content_hash()`. The proxy is a read-only VIEW of a dict, not a copy of it, and `gc` can reach the
        dict through the view. This grants no power (1) does not already grant, and it is equally detectable
        by the same means, but it is a route and this module's standard is that routes are stated.
        (`to_dict()` is a true defensive copy: mutating its result cannot reach the card.)
    (3) THE ROUTE THAT FALSIFIED THE WORD "COMPLETE" ABOVE, found by a round-6 attestation and now
        CLOSED: `per_seed` was checked with `isinstance(m, MetricValue)` while `_recheck_summary` /
        `_recheck_insufficient` demand `type(x) is ...`, so a `MetricValue` SUBCLASS -- which can
        override `__eq__`, `__ne__` and `to_dict` -- was accepted onto a card. No verdict flip was
        measured from it, and it is stated as what it is: an inconsistency between three sibling checks
        in one method, closed by making all three exact-type. It is recorded here because the sentence
        that said this list was complete was wrong, and a list claimed to be complete has to name what
        proved it was not.
    (4) `vars(card)["probe_id"] = "TAMPERED"`, and every spelling of it -- `card.__dict__[...] = ...`,
        `vars(card).update(...)`, `vars(card.summary)["mean"] = 9.0`, `vars(card).pop(...)`,
        `vars(card).clear()`. A frozen dataclass's freeze is `__setattr__`, and `vars()` does not go
        through it: the instance `__dict__` is an ordinary writable dict. MEASURED, a fresh card per
        route on both interpreters: six routes changed `content_hash()` with no exception, and the two
        that DELETE a field leave a card that raises `AttributeError` out of `to_json()` -- outside the
        family every probe declares. `vars(c)["does_not_establish"] = ("This IS a safety finding.",)`
        serialises that text as the card's only disclaimer and `scorecard_to_record` accepts it, which
        is the outcome `_plain_text`'s docstring names as the worst case; and
        `vars(c)["min_seeds"] = 10` on a real 3-seed card reproduces round 10's lie (JSON
        `min_seeds: 10` beside `summary.n: 3`) with no `object.__setattr__` at all.
        IT GRANTS NOTHING (1) DOES NOT ALREADY GRANT, which is exactly why it is written down: limit (2)
        is here for that same reason, in those words, and this is the PLAINEST spelling of the two --
        one subscript, no `gc`, no `object.__setattr__`, and a spelling the rest of this kit already
        treats as a protocol bypass when it READS it (`toy.benchmark`, `toy.dashboard` and their tests).
        It was unstated at the one place in the kit that enumerates WRITE routes.
        NOT CLOSED, and the alternative was MEASURED rather than argued about:
        `@dataclasses.dataclass(frozen=True, slots=True)` on `Scorecard` and `SeedSummary` does close
        every route above -- `vars(card)` then raises `TypeError: vars() argument must have __dict__
        attribute` -- and `test_schema` (55) still passes, so the field boundary and the
        `object.__setattr__` writes in `__post_init__` survive it. What it costs is the freeze's own
        error contract: `slots=True` makes `dataclasses` build a NEW class object while the generated
        `__setattr__` keeps a cell for the old one, so `card.new_attribute = 1` raises
        `TypeError: super(type, obj): obj (instance of Scorecard) is not an instance or subtype of type
        (Scorecard)` instead of refusing coherently, and
        `TestImmutability.test_direct_assignment_and_deletion_raise` FAILS on both 3.12.4 and 3.13.5
        (193 tests, errors=1; `setattr` on an existing field still gives `FrozenInstanceError`, and
        `dataclasses.replace` still works). So the trade is a route that grants nothing against the
        legibility of the refusal every supported path already gets, and the route is DECLARED. Swept by
        `test_robustness.TestImmutability.test_the_vars_write_route_is_declared_not_discovered`, which
        drives every spelling and fails if one of them starts raising WITHOUT this list changing.
    The card stores no hash of itself (only `seed_digest`, a hash of the seed list), so tampering by ANY
    route is detectable only by comparing a freshly recomputed `content_hash()` with a hash recorded EARLIER,
    for example the one `scorecard_to_record` places in the record's `input_hashes["scorecard"]`; not
    impossible, and not detectable without such a recorded value."""
    probe_id: str
    probe_kind: str
    status: ProbeStatus
    min_seeds: int
    seeds: tuple
    seed_digest: str
    per_seed: tuple
    summary: Optional[SeedSummary]
    insufficient: Optional[InsufficientEvidence]
    evidence_labels: tuple
    details: Mapping
    does_not_establish: tuple

    _NORMALISE_EXEMPT = MappingProxyType({})

    def __post_init__(self) -> None:
        # NORMALISE EVERY FIELD AT THE BOUNDARY, FIRST (see `toy.schema._normalise_fields`). This
        # REPLACES an argument that this method used to make, and the argument is worth recording
        # because it was the shape of the whole defect class: `probe_id` / `probe_kind` were left
        # un-normalised on the reasoning that they are "compared with nothing (AST-checked)" and that a
        # `_plain_text` call there would be "unpinnable code dressed as a guard". That reasoning is sound
        # about a HAND-PLACED call and worthless as a policy: it is an argument that has to be re-made,
        # correctly, for every field of every class in the module, and the four live findings of round 6
        # were all fields for which nobody made it. A boundary driven by `dataclasses.fields()` costs one
        # line per class, covers a new field BY DEFAULT, and makes the exemptions a written list with
        # reasons instead of a reviewer's memory. So the two text fields are now covered like the rest,
        # and the question "is this field normalised?" is answered by the class, not by a sweep.
        _normalise_fields(self)
        for nm in ("probe_id", "probe_kind"):
            v = getattr(self, nm)
            if not isinstance(v, str) or not v.strip():
                raise ValueError(f"{nm} must be a nonblank string")
        if not isinstance(self.status, ProbeStatus):
            raise ValueError("status must be a ProbeStatus")
        # USE THE RESULT. This was the ONLY `ProbeConfig(...)` in the module whose return value was
        # discarded, so `min_seeds` kept the caller's object and the count check 16 lines below --
        # `len(measured) < self.min_seeds` -- ran on it. The subclass is the RIGHT operand there, so the
        # REFLECTED operator decides, which is the same variant already found and fixed in
        # `summarize_seeds` (whose comment states the lesson this line did not apply: "The returned
        # object is USED, not discarded"). MEASURED, via `dataclasses.replace` with no
        # `object.__setattr__`:
        #     class Lo(int):
        #         def __gt__(self, o):  return False
        #         def __ge__(self, o):  return False
        #     replace(three_seed_card, min_seeds=10)      -> refused (3 measured < 10 required)
        #     replace(three_seed_card, min_seeds=Lo(10))  -> ACCEPTED, status MEASURED, JSON
        #                                                    {"min_seeds": 10, "summary": {"n": 3}}
        # i.e. a card asserting a minimum of 10 while carrying a summary of 3. Secondary, now also
        # closed by storing the normalised value: `scorecard_to_record` does
        # `MetricValue.measured(float(sc.min_seeds))`, a second overridable conversion of a
        # never-normalised field, so a card and its own record could disagree about `min_seeds`.
        object.__setattr__(self, "min_seeds", ProbeConfig(self.min_seeds).min_seeds)
        seeds = _check_seeds(self.seeds)
        object.__setattr__(self, "seed_digest", _plain_text(self.seed_digest))   # see `_plain_text`
        if self.seed_digest != seed_list_digest(seeds):
            raise ValueError("seed_digest does not match the seed list")
        per_seed = tuple(self.per_seed)
        # `type(m) is not MetricValue`, not `isinstance`: see honest limit (3) in the class docstring.
        # The two sibling checks on the next few lines (`_recheck_summary`, `_recheck_insufficient`)
        # already refuse a subclass by exact type, and a card is where the three must agree.
        if len(per_seed) != len(seeds) or not all(type(m) is MetricValue for m in per_seed):
            raise ValueError("per_seed must hold exactly one MetricValue per seed (subclasses are refused)")
        if (self.summary is None) == (self.insufficient is None):
            raise ValueError("exactly one of summary / insufficient must be set")
        measured = tuple(v for v in (_metric_read(m) for m in per_seed) if v is not None)
        if self.summary is not None:
            _recheck_summary(self.summary)
            # `==` rather than `is` on all three status comparisons in this module, even though the
            # `isinstance` gate 35 lines up already makes `self.status` a real member here: the identity
            # spelling is the shape that made `ShiftSpec.kind` a finding, and an operator rule that holds
            # everywhere can be pinned by a test, while "correct at this site because the field was
            # gated" has to be re-argued per site and was wrong twice. See `ShiftSpec.__post_init__`.
            if self.status == ProbeStatus.INSUFFICIENT_EVIDENCE:
                raise ValueError("a summarized scorecard cannot have INSUFFICIENT_EVIDENCE status")
            if self.summary.values != measured:
                raise ValueError("summary does not match the measured per-seed values")
            if len(measured) < self.min_seeds:
                raise ValueError("summary present with fewer measured seeds than min_seeds")
        else:
            _recheck_insufficient(self.insufficient)
            if self.status != ProbeStatus.INSUFFICIENT_EVIDENCE:    # `!=`, not `is not`: see above
                raise ValueError("an insufficient scorecard must have INSUFFICIENT_EVIDENCE status")
            if self.insufficient.n_measured != len(measured) or self.insufficient.n_required != self.min_seeds:
                raise ValueError("insufficient-evidence counts do not match per-seed values / min_seeds")
        labels = tuple(sorted({EvidenceClass.parse(x) for x in self.evidence_labels}, key=_enum_value))
        if EvidenceClass.SOURCE_OBSERVED in labels:
            raise ValueError("SOURCE_OBSERVED cannot label a probe scorecard")
        if EvidenceClass.NOT_VALIDATED not in labels:
            raise ValueError("every scorecard must carry NOT_VALIDATED (no independent validation exists)")
        if (EvidenceClass.TOY_RESULT in labels) != (self.summary is not None):
            raise ValueError("TOY_RESULT label if and only if a summary exists")
        if self.summary is None and EvidenceClass.UNKNOWN not in labels:
            raise ValueError("an insufficient scorecard must carry UNKNOWN")
        if any(not _metric_ok(m) for m in per_seed) and EvidenceClass.UNKNOWN not in labels:
            raise ValueError("a scorecard with unmeasured seeds must carry UNKNOWN")
        dne = tuple(self.does_not_establish)
        if not dne or any(not isinstance(s, str) or not s.strip() for s in dne):
            raise ValueError("does_not_establish must be a nonempty tuple of nonblank strings")
        dne = tuple(_plain_text(s) for s in dne)   # before the membership test below; see `_plain_text`
        for std in STANDARD_NON_CLAIMS:
            if std not in dne:
                raise ValueError("does_not_establish must include every STANDARD_NON_CLAIMS entry")
        object.__setattr__(self, "seeds", seeds)
        object.__setattr__(self, "per_seed", per_seed)
        object.__setattr__(self, "evidence_labels", labels)
        object.__setattr__(self, "details", deep_freeze(self.details))
        object.__setattr__(self, "does_not_establish", dne)

    def to_dict(self) -> dict:
        return {
            "schema_version": SCHEMA_VERSION, "label": TOY_LABEL, "kind": "robustness_scorecard",
            "code_version": CODE_VERSION, "probe_id": self.probe_id, "probe_kind": self.probe_kind,
            "status": _enum_value(self.status), "min_seeds": self.min_seeds, "seeds": list(self.seeds),
            "seed_digest": self.seed_digest, "per_seed": [m.to_dict() for m in self.per_seed],
            "summary": self.summary.to_dict() if self.summary else None,
            "insufficient": self.insufficient.to_dict() if self.insufficient else None,
            "evidence_labels": [_enum_value(e) for e in self.evidence_labels],
            "details": thaw(self.details), "does_not_establish": list(self.does_not_establish),
        }

    def to_json(self) -> str:
        return canonical_json(self.to_dict())

    def content_hash(self) -> str:
        return hashlib.sha256(self.to_json().encode("utf-8")).hexdigest()

    def __hash__(self) -> int:  # field containers include mappingproxy (unhashable); hash the content
        return hash(self.content_hash())


def build_scorecard(*, probe_id: str, probe_kind: str, seeds: Sequence[int], per_seed: Sequence[MetricValue],
                    cfg: ProbeConfig, status_if_summarized: ProbeStatus, details_always: Mapping,
                    details_if_summarized: Optional[Mapping] = None, non_claims: Sequence[str] = ()
                    ) -> Scorecard:
    """The only place a scorecard's evidence labels and summary-vs-insufficient branch are decided.

    `details_if_summarized` defaults to None rather than to a literal `MappingProxyType({})`. The
    proxy is read-only, but the dict BEHIND it is reachable via `gc.get_referents` -- the route the
    `Scorecard` docstring lists among its honest limits -- so writes to it persisted into every later
    no-argument call. It was the last container default in this module after the `ProbeConfig` and
    `Margins` defaults were fixed; the stakes were low (it feeds descriptive `details` only, never a
    status, a summary or `min_seeds`), but "low stakes" is not why a shared mutable default should
    survive in a module whose own threat model includes reaching through read-only wrappers."""
    if details_if_summarized is None:
        details_if_summarized = {}
    # A BARE STRING IS A SEQUENCE OF CHARACTERS, and `tuple(non_claims)` would shred it. MEASURED:
    # `non_claims="magnitude"` produced a card carrying nine single-character non-claims
    # ('m', 'a', ...), each of which passes `Scorecard.__post_init__`'s nonblank-string check, so the
    # card's `does_not_establish` read 15 entries of which 9 said nothing. Unreachable for realistic
    # text -- any sentence contains a blank, and a blank "non-claim" is already refused -- so this is a
    # legibility defect rather than a route to a forged verdict; it is closed rather than declared
    # because the refusal is one line and the shredded card is serialised to a reader.
    if isinstance(non_claims, (str, bytes)):
        raise ValueError("non_claims must be a sequence of strings, not a single string "
                         "(a bare string would be shredded into one non-claim per character)")
    seeds = _check_seeds(seeds)
    per_seed = tuple(per_seed)
    result = summarize_seeds(per_seed, cfg.min_seeds)
    labels = {EvidenceClass.NOT_VALIDATED}
    if any(not _metric_ok(m) for m in per_seed):
        labels.add(EvidenceClass.UNKNOWN)
    if isinstance(result, SeedSummary):
        labels.add(EvidenceClass.TOY_RESULT)
        status, summ, insuf = status_if_summarized, result, None
        details = {**dict(details_always), **dict(details_if_summarized)}
    else:
        labels.add(EvidenceClass.UNKNOWN)
        status, summ, insuf = ProbeStatus.INSUFFICIENT_EVIDENCE, None, result
        details = dict(details_always)  # no deviation counts etc. from fewer than the minimum seeds
    details = {"python_version": current_python_version(), **details}   # environmental facts live on every card
    return Scorecard(probe_id, probe_kind, status, cfg.min_seeds, seeds, seed_list_digest(seeds), per_seed,
                     summ, insuf, tuple(labels), details, STANDARD_NON_CLAIMS + tuple(non_claims))


# ------------------------------------------------------------ record mapping
def scorecard_to_record(sc: Scorecard, *, run_id: str, timestamp_utc: str, code_version: str = CODE_VERSION
                        ) -> ExperimentRecord:
    """Map a scorecard onto an ExperimentRecord. TOY_RESULT only when a summary exists, else UNKNOWN
    (an insufficient probe has no result to label). The structured status lives on the scorecard; the record
    carries its content hash as an input hash and the notes string is NOT evidence and must not be parsed."""
    if not sc.seeds:
        raise ValueError("cannot make a run record from a scorecard with no seeds")
    n_meas = float(sum(_metric_ok(m) for m in sc.per_seed))
    metrics = {"n_seeds": MetricValue.measured(float(len(sc.seeds))), "n_measured": MetricValue.measured(n_meas),
               "min_seeds_required": MetricValue.measured(float(sc.min_seeds))}
    s = sc.summary
    for key, val in (("mean", s.mean if s else None), ("sd", s.sd if s else None), ("iqr", s.iqr if s else None),
                     ("min", s.minimum if s else None), ("max", s.maximum if s else None)):
        metrics[key] = (MetricValue.measured(val) if val is not None else
                        MetricValue.unmeasured(
                            f"INSUFFICIENT_EVIDENCE: {_shown(sc.insufficient.reason, how=str)}"))
    prov = RunProvenance(run_id=run_id, timestamp_utc=timestamp_utc, seed=sc.seeds[0], code_version=code_version,
                         python_version=current_python_version(), toy_only=True,
                         input_hashes={"seed_list": sc.seed_digest, "scorecard": sc.content_hash()})
    return ExperimentRecord(
        name=f"robustness:{_shown(sc.probe_id, how=str)}", provenance=prov, metrics=metrics,
        evidence_class=EvidenceClass.TOY_RESULT if s else EvidenceClass.UNKNOWN,
        notes=f"status={_shown(_enum_value(sc.status), how=str)}; structured status is on the scorecard "
              "(hash in input_hashes); "
              "this string is not evidence and must not be parsed")


# ==================================================== 1. seed-sensitivity probe
def seed_sensitivity_probe(outcome: Callable[[int], float], seeds: Sequence[int], cfg: Optional[ProbeConfig] = None,
                           *, probe_id: str = "seed_sensitivity") -> Scorecard:
    """Distribution of `outcome(seed)` across a frozen seed list: mean, SD, IQR, min, max, full vector.
    Fewer than cfg.min_seeds measured seeds => INSUFFICIENT_EVIDENCE scorecard, no scalar.
    `cfg=None` means a freshly constructed `ProbeConfig()`; see `_pcfg`."""
    cfg = _pcfg(cfg)
    seeds = _check_seeds(seeds)
    per_seed = tuple(_to_metric(outcome, s) for s in seeds)
    vals = [v for v in (_metric_read(m) for m in per_seed) if v is not None]
    return build_scorecard(
        probe_id=probe_id, probe_kind="seed_sensitivity", seeds=seeds, per_seed=per_seed, cfg=cfg,
        status_if_summarized=ProbeStatus.MEASURED,
        details_always={"outcome_name": _name_attr(outcome, "outcome")},
        details_if_summarized={"n_unmeasured": len(per_seed) - len(vals), "n_distinct_values": len(set(vals)),
                               "zero_variance_warning": len(set(vals)) == 1},
        non_claims=("Spread across seeds is a property of the fixture generator and scorer, not of any method.",
                    "A tight spread would not show the outcome is insensitive to anything else."))


def benchmark_outcome(factory: Callable, metric: str = "S", cfg=None) -> Callable[[int], float]:
    """Adapter: seed -> `toy.benchmark.score_seed(seed, factory, cfg).metrics[metric]` as a float (read-only
    use of SR-10). Unmeasured metric raises ValueError so the probe records it as unmeasured with a reason."""
    from toy import benchmark as bm
    cfg = cfg or bm.BenchmarkConfig()

    def outcome(seed: int) -> float:
        m = bm.score_seed(seed, factory, cfg).metrics[metric]
        v = _metric_read(m)
        if v is None:
            raise ValueError(f"{metric} unmeasured: {m.reason}")
        return v
    outcome.__name__ = f"benchmark:{metric}"
    return outcome


# ================================================== measures and fixtures (toy)
@dataclasses.dataclass(frozen=True)
class MeasureFixture:
    seed: int
    pred: Matrix
    target: Matrix
    mask: Mask

    _NORMALISE_EXEMPT = MappingProxyType({})

    def __post_init__(self) -> None:
        # A fixture is the INPUT every measure and every shift computes from, and `_rebuild` reconstructs
        # one from caller-supplied rows, so a subclass element reaching a measure's arithmetic is reached
        # by no other guard on this path. Covered by the boundary rather than by a hand-placed cast.
        _normalise_fields(self)


def make_measure_fixture(seed: int, rows: int = 16, width: int = 3, noise: float = 0.1,
                         magnitude_spread: int = 0) -> MeasureFixture:
    """Synthetic fixture. target ~ U(-1,1); pred = target + U(-noise,noise); row r is multiplied by
    10**k_r with k_r in [0, magnitude_spread] (spread=0 => all 1). Mask has >= 2 True and >= 1 False.

    `rows` DEFEATED THE GATE ON THE NEXT LINE, and it is this module's sharpest example of why
    normalisation belongs at the parameter boundary rather than at remembered sites: `rows < 4` is
    `type(rows).__lt__`, so an `int` SUBCLASS storing 3 whose `__lt__` / `__gt__` return False passed it
    and the module built the 3-row fixtures it refuses to build. This is `probe_shift`'s default
    `fixture_factory` and is called directly by `probe_missing_inputs` and `probe_precision`. MEASURED,
    through the public parameter with no `object.__setattr__`, on `probe_shift(mse_fsum,
    shift_reorder_rows(), SEEDS, ProbeConfig(10), fixture_factory=lambda s: make_measure_fixture(s,
    rows=Lo(3)))` over 12 seeds: INSUFFICIENT_EVIDENCE -> INVARIANCE_HOLDS, evidence labels
    (NOT_VALIDATED, UNKNOWN) -> (NOT_VALIDATED, TOY_RESULT), and a 12-seed summary (n=12, mean 0.0,
    n_bitwise_equal 12) where the honest run has none -- a result measured on fixtures the module refuses
    to build. SECOND, SEPARATE CONSEQUENCE, of the class the `OverflowError` escape in
    `toy.benchmark._check_margin` had to close: `rows=2` raises the documented `ValueError` below, but
    `rows=Lo(2)` reached `rng.sample(range(2), 2)`, forced BOTH indices True, and then
    `rng.choice([])` raised `IndexError: Cannot choose from an empty sequence` -- OUTSIDE the
    `(ValueError, TypeError, ArithmeticError)` family every probe declares, so it escaped `probe_shift`'s
    own fail-closed handler and propagated out of a public probe. Both are closed FOR AN `int` SUBCLASS by
    the gate seeing the value the object STORES (`_plain_arguments`): `rows=Lo(2)` raises the documented
    `ValueError`, which the probe records as an unmeasured seed.
    ROUND 8 FALSIFIED THE SENTENCE THAT STOOD HERE -- "Both are closed by the gate now seeing the value
    the object STORES" -- and it is worth keeping the correction rather than the claim. A DUCK-TYPED
    `rows`, an object of an unrelated class answering `__lt__` with False and NOT an `int` subclass,
    stores nothing for `_plain_value` to read, so it passed the boundary unchanged and BOTH consequences
    came back. RE-MEASURED on 3.12.4 and 3.13.5 through this public parameter with no
    `object.__setattr__`: `rows=Duck(3)` built the 3-row fixtures again and the 12-seed probe went
    INSUFFICIENT_EVIDENCE / (NOT_VALIDATED, UNKNOWN) -> INVARIANCE_HOLDS / (NOT_VALIDATED, TOY_RESULT)
    with n_bitwise_equal 12, and `rows=Duck(2)` raised `IndexError: Cannot choose from an empty sequence`
    out of a public probe again. Closed now by the TYPE requirement at the same boundary
    (`_annotated_scalar_parameters`): a parameter annotated `int` must receive something that stores an
    int, so a duck-typed `rows` raises `TypeError` -- inside the declared family -- before this gate runs.
    AND THE EMPTY-CHOICE BRANCH IS GUARDED BELOW rather than argued away. Round 8 recorded a decision not
    to guard it, reasoning that "with the gate seeing the stored value the branch is unreachable, and an
    unpinnable guard is decoration"; both halves rested on a premise that was never measured and are
    false. The branch was reachable through a fully public duck-typed route, and the guard IS pinnable --
    `make_measure_fixture.__wrapped__`, this module's own declared before/after control, reaches the body
    with the boundary off. Pinned by `test_robustness.TheParameterBoundaryClosesFourLiveRoutes` (the
    `*_duck_typed` twins) and `test_the_empty_choice_branch_is_guarded_not_argued_away`."""
    if rows < 4 or width < 1:
        raise ValueError("need rows >= 4 and width >= 1")
    rng = make_rng(derive_seed(seed, "robustness:fixture"))
    t, p = [], []
    for _ in range(rows):
        sc = float(10 ** rng.randint(0, magnitude_spread))
        tr = tuple(rng.uniform(-1.0, 1.0) * sc for _ in range(width))
        pr = tuple(x + rng.uniform(-noise, noise) * sc for x in tr)
        t.append(tr)
        p.append(pr)
    mask = [rng.random() < 0.6 for _ in range(rows)]
    forced = rng.sample(range(rows), 2)
    for i in forced:
        mask[i] = True
    if all(mask):
        spare = [i for i in range(rows) if i not in forced]
        # `rows >= 4` and `len(forced) == 2` make this list nonempty, so with a PLAIN `rows` the line
        # below cannot raise -- but that is a property of a gate twelve lines up and of a boundary one
        # function out, and round 8 measured both failing at once: `rng.choice([])` raised `IndexError`,
        # OUTSIDE the `(ValueError, TypeError, ArithmeticError)` family every probe declares, and it
        # propagated out of a public probe. This states the local invariant instead of inheriting it.
        if not spare:
            raise ValueError("need rows >= 4 and width >= 1: no row is left to mask out")
        mask[rng.choice(spare)] = False
    return MeasureFixture(seed, tuple(p), tuple(t), tuple(mask))


def make_order_sensitive_fixture(seed: int, big: float = 1e8) -> MeasureFixture:
    """Hand-built adversarial fixture: width 1, target all 0, prediction = [+B, -B, six values in (0.5, 1.5)]
    with B = big * (1 + u). Signed sums of these cancel B against -B, and squares of +-B (about big**2)
    swamp the unit-sized terms, so the rounding of a naive left-to-right sum DEPENDS ON ROW ORDER.
    The random fixture of `make_measure_fixture` shows no such dependence (its differences are
    exactly summable); this fixture exists so an order-invariance probe can actually fail."""
    rng = make_rng(derive_seed(seed, "robustness:order_fixture"))
    B = big * (1.0 + rng.random())
    vals = [B, -B] + [0.5 + rng.random() for _ in range(6)]
    return MeasureFixture(seed, tuple((v,) for v in vals), tuple((0.0,) for _ in vals), (True,) * len(vals))


_UNDERFLOW = getattr(stability, "UnderflowError", stability.StabilityError)


def mse_naive(pred, target, mask) -> float:
    """Masked MSE through `toy.stability.masked_squared_error_mean` (left-to-right float summation)."""
    k = sum(1 for b in mask if b is True) if isinstance(mask, (tuple, list)) else 0
    w = len(pred[0]) if isinstance(pred, (tuple, list)) and pred and isinstance(pred[0], (tuple, list)) else 1
    return stability.masked_squared_error_mean(pred, target, mask, k * w)


def mse_fsum(pred, target, mask) -> float:
    """Masked MSE with exactly rounded (`math.fsum`) accumulation; same validators as mse_naive."""
    P = stability.check_finite_matrix(pred, "prediction")
    T = stability.check_finite_matrix(target, "target")
    if len(P) != len(T) or len(P[0]) != len(T[0]):
        raise stability.ShapeError("prediction and target shapes differ")
    M = stability.check_mask(mask, expected_len=len(P))
    terms = []
    for pr, tr, use in zip(P, T, M):
        if use:
            for a, b in zip(pr, tr):
                d = a - b
                sq = d * d
                if sq == 0.0 and a != b:   # same policy as toy.stability._sq: never a silent zero
                    raise _UNDERFLOW("squared error underflowed to 0.0 from distinct inputs "
                                     f"({_shown(a)}, {_shown(b)})")
                terms.append(sq)
    if not all(math.isfinite(x) for x in terms):
        raise stability.NonFiniteError("squared error overflowed")
    try:
        res = math.fsum(terms) / len(terms)
    except OverflowError:
        raise stability.NonFiniteError("sum overflowed") from None
    if not math.isfinite(res):
        raise stability.NonFiniteError("masked mean non-finite")
    return res


def _signed_diffs(pred, target, mask) -> tuple:
    P = stability.check_finite_matrix(pred, "prediction")
    T = stability.check_finite_matrix(target, "target")
    if len(P) != len(T) or len(P[0]) != len(T[0]):
        raise stability.ShapeError("prediction and target shapes differ")
    M = stability.check_mask(mask, expected_len=len(P))
    return tuple(tuple(a - b for a, b in zip(pr, tr)) for pr, tr, use in zip(P, T, M) if use)


def abs_bias_naive(pred, target, mask) -> float:
    """|mean(pred - target)| over selected elements via `stability.masked_mean_checked` (naive, signed sum:
    unlike MSE, cancellation makes the result depend on row order at the rounding level)."""
    d = _signed_diffs(pred, target, mask)
    return abs(stability.masked_mean_checked(d, [True] * len(d), len(d) * len(d[0])))


def abs_bias_fsum(pred, target, mask) -> float:
    """Same quantity with exactly rounded accumulation."""
    d = _signed_diffs(pred, target, mask)
    try:
        res = math.fsum(x for r in d for x in r) / (len(d) * len(d[0]))
    except OverflowError:   # fsum raises OverflowError on intermediate overflow; keep the documented ValueError family
        raise stability.NonFiniteError("signed sum overflowed") from None
    return abs(res)


def exact_masked_mse(pred, target, mask) -> Fraction:
    """Ground truth: exact rational MSE of the given float inputs (no rounding at all).

    THE MASK IS VALIDATED LIKE EVERY SIBLING MEASURE'S, and the round-11 reason-coverage probe is why.
    `_WHY_MASK` -- the reason declared for this parameter in `_PARAMETER_NO_SCALAR`, shared with the five
    other measures -- says a non-bool element is "refused loudly by `toy.stability.check_mask`", and the
    test policing those reasons exercised 3 of the 6 measures it covers, none of them this one. MEASURED
    before the fix: an `int` mask was ACCEPTED here where every sibling raises `MaskTypeError`, and a
    SHORT mask silently measured 2 of 16 rows (`zip` stops at the shortest). The module's own probe
    already said so -- `probe_missing_inputs(exact_masked_mse)` -> SILENT_DEFAULT_DEFECT,
    `n_silent_value_total = 48`, `mask_truthy_not_bool` silent 12/12.
    WHAT IS DELIBERATELY STILL NOT VALIDATED: the matrices. This is the exact oracle the float measures
    are compared against, so it must accept a `Fraction` / `Decimal` element that
    `stability.check_finite_matrix` refuses (pinned by
    `test_a_rational_where_a_float_is_annotated_is_refused_and_the_exact_helpers_are_not`), and it
    therefore still answers some malformed-matrix cases with a value: after this fix
    `probe_missing_inputs(exact_masked_mse)` remains SILENT_DEFAULT_DEFECT on the matrix cases, which is
    the honest report for a helper that validates its mask and not its data. THE POST-FIX FIGURES, here
    rather than only in the test, because round 11's record claimed they were "named and counted in both
    the test and the docstring" and they were in the test alone: `n_silent_value_total` 48 -> 36, and the
    12 remaining silent cases per seed are exactly THREE -- `inf_in_masked_out_row`,
    `nan_in_masked_out_row` and `ragged_columns` (3 x 12 seeds = 36), with all four mask cases
    (`all_false_mask`, `empty_mask`, `mask_is_none`, `mask_truthy_not_bool`) now at 0 silent and 12
    raised. Asserted against this docstring by
    `test_robustness.AProbeCannotCertifyAMeasureItNeverCalled.test_the_exact_oracle_validates_its_mask_like_its_five_siblings`."""
    M = stability.check_mask(mask, expected_len=len(pred))
    num, cnt = Fraction(0), 0
    for pr, tr, use in zip(pred, target, M):
        if use:
            for a, b in zip(pr, tr):
                d = Fraction(a) - Fraction(b)
                num += d * d
                cnt += 1
    return num / cnt


def _exact_sum(values: Sequence[float]) -> Fraction:
    ratios = [v.as_integer_ratio() for v in values]
    den = max(d for _, d in ratios)
    return Fraction(sum(n * (den // d) for n, d in ratios), den)


def _rel_err(approx: float, exact: Fraction) -> float:
    """|approx - exact| / |exact| computed in exact arithmetic (exact != 0 by construction of every probe)."""
    if exact == 0:
        raise ValueError("relative error undefined for an exact value of 0")
    return float(abs(Fraction(approx) - exact) / abs(exact))


# ============================================ 2. benign numeric input shifts
class ShiftKind(str, Enum):
    INVARIANCE_EXACT = "INVARIANCE_EXACT"          # must hold bit-for-bit
    INVARIANCE_TOLERANCE = "INVARIANCE_TOLERANCE"  # must hold within a declared relative tolerance
    SENSITIVITY_BOUNDED = "SENSITIVITY_BOUNDED"    # nonzero movement expected, bounded by a derived bound


@dataclasses.dataclass(frozen=True)
class ShiftSpec:
    """transform(fixture, rng) -> shifted fixture; expected(base) -> value the measure should return on the
    shifted fixture if it behaved ideally; bound(base, expected, shifted_fixture) -> allowed |deviation|
    (ignored, taken as 0, for INVARIANCE_EXACT)."""
    name: str
    kind: ShiftKind
    transform: Callable
    expected: Callable = lambda base: base
    bound: Callable = lambda base, expected, fx: 0.0
    rationale: str = ""

    _NORMALISE_EXEMPT = MappingProxyType({
        "transform": "a callable stores no scalar to collapse; what it RETURNS is normalised where it is "
                     "CONSUMED, by probe_shift's `_plain_measure(measure(fx2...), 'shifted measure')` "
                     "and `_plain_measure(spec.bound(...), 'deviation bound')`. THIS REASON USED TO NAME "
                     "THE WRONG MECHANISM -- it said the return \"is a fixture, which normalises its own "
                     "fields in MeasureFixture.__post_init__\" -- and an attester falsified it: "
                     "probe_shift NEVER type-checks this return, so that `__post_init__` is not what "
                     "protects anything here. MEASURED on shift_translate(1000.0) over 12 seeds, through "
                     "`dataclasses.replace(spec, transform=...)`: a duck-typed SimpleNamespace carrying a "
                     "`float` subclass whose `__abs__` answers 1e36 reached `measure` and `_masked_stats` "
                     "unchallenged and moved `max_dev_over_bound` from 4.034e-02 to 4.042e-35 (a factor "
                     "of ~1e33), while the SAME lying element inside a real MeasureFixture was collapsed "
                     "by that `__post_init__` and reproduced 4.034e-02 exactly. It is recorded as a NOTE "
                     "and not as a finding: no status flip was constructible (the honest probe has 0 "
                     "violations, and the movement is in the direction of a LOOSER bound), and a caller "
                     "who supplies `transform` supplies `bound` too, so it grants them nothing they "
                     "lack. `probe_shift`'s `fixture_factory` parameter is the same shape and carries "
                     "the same corrected reason in `_PARAMETER_NO_SCALAR`",
        "expected": "a callable; its RETURN is normalised where it is consumed, by probe_shift's "
                    "`_plain_measure(spec.expected(base), 'expected value')`",
        "bound": "a callable; its RETURN is normalised where it is consumed, by probe_shift's "
                 "`_plain_measure(spec.bound(...), 'deviation bound')`. A closure variable it computes "
                 "from (`shift_reorder_rows`'s `rel_tol`) is normalised where it is BOUND, because it is "
                 "not a field of anything and this boundary cannot reach it",
    })

    def __post_init__(self) -> None:
        _normalise_fields(self)
        # THE GATE `Scorecard.__post_init__` ALREADY GIVES `status`, and the round-11 finding that it was
        # missing here. `kind` is not data: it SELECTS THE TIER probe_shift judges against (exact /
        # tolerance / bounded) and it is serialised into the card as `details["declared_kind"]`. The two
        # comparisons that read it used `is`, and `ShiftKind` is a `str` subclass by construction, so a
        # PLAIN STRING of the right spelling -- which no isinstance and no normaliser refused, because it
        # stores exactly what it says -- was never equal by identity to the member and silently took the
        # TOLERANCE branch. MEASURED on 3.12.4 and 3.13.5 through this factory's public caller
        # `shift_reorder_rows("INVARIANCE_EXACT", 1e9)`, with the module's own permutation-violating
        # measure over 12 seeds (and identically via `standard_shifts("INVARIANCE_EXACT", 1e9)[0]`):
        #     kind=ShiftKind.INVARIANCE_EXACT -> INVARIANCE_DEFECT, n_violations=12, max_abs_dev=1.4679e-02
        #     kind="INVARIANCE_EXACT"         -> INVARIANCE_HOLDS,  n_violations=0,  max_abs_dev=1.4679e-02
        # i.e. the SAME measured deviations, `max_abs_dev` serialised beside `n_violations = 0`, and
        # `json.dumps(details["declared_kind"])` BYTE-IDENTICAL between the two cards, so neither a reader
        # nor a downstream `==` could tell the verdict had been taken on another tier.
        # WHY A GATE AND NOT ONLY `==` (both were available, and the comparisons below are now `==` too):
        # a gate refuses early, inside the `(ValueError, TypeError, ArithmeticError)` family every probe
        # declares, and it is the only one of the two that keeps a card from CARRYING an unvalidated
        # spelling -- under `==` alone a near-miss (`"INVARIANCE_EXCT"`) is still accepted, matches
        # neither tier, is judged against `bound` and is then serialised as the declared kind. `==` is
        # kept as the independent second line so that neither this gate nor that operator is alone
        # load-bearing; the operator rule is pinned module-wide by
        # `test_robustness.NoIdentityComparisonDecidesAStatusOrATier`.
        if not isinstance(self.kind, ShiftKind):
            raise ValueError(f"kind must be a ShiftKind, got {_type_name(self.kind)} "
                             "(a plain string of the right spelling is refused: it selects the tier "
                             "this spec is judged against and is serialised as declared_kind)")


def _masked_stats(fx: MeasureFixture) -> tuple:
    vals = [abs(v) for pr, tr, m in zip(fx.pred, fx.target, fx.mask) if m for v in pr + tr]
    return max(vals)


def _cast_bound(expected: float, fx: MeasureFixture) -> float:
    """Derivation: each shifted element carries relative rounding <= u, so d=p-t carries absolute error
    <= 2u*M (M = max |element|); by Cauchy-Schwarz the relative MSE error from that is <= 2*(2uM)/rms
    (mean|d| <= rms); +summation slack. We use 4*EPS*M/rms + 64*EPS (a deliberately loose, hand-derived cap)."""
    rms = math.sqrt(expected)
    return expected * (4 * EPS * _masked_stats(fx) / rms + 64 * EPS)


def _rebuild(fx, pred=None, target=None, mask=None) -> MeasureFixture:
    return MeasureFixture(fx.seed, tuple(map(tuple, pred if pred is not None else fx.pred)),
                          tuple(map(tuple, target if target is not None else fx.target)),
                          tuple(mask if mask is not None else fx.mask))


def shift_reorder_rows(kind: ShiftKind = ShiftKind.INVARIANCE_EXACT, rel_tol: float = 0.0) -> ShiftSpec:
    """`rel_tol` is the UN-SWEPT SIBLING of `probe_precision`'s `tol`, and it is normalised for the same
    reason and with the same helper. It is captured in the `bound` closure and multiplied there
    (`rel_tol * abs(e)`), i.e. `type(rel_tol).__mul__`, which decides the allowed deviation. MEASURED,
    through this public factory with no `object.__setattr__`: a `float` subclass STORING 0.0 whose
    `__mul__` / `__rmul__` return 1e9 turned `probe_shift(row_weighted_mse, ...)` from INVARIANCE_DEFECT,
    n_violations=12 into INVARIANCE_HOLDS, n_violations=0 -- with 12 of 12 seeds actually violating, and
    the card self-contradicting itself by serialising `max_abs_dev = 9.11e-03` beside `n_violations = 0`.
    Round 5 fixed `tol` and wrote the lesson in `probe_precision`'s comment; this sibling never received
    it, which is the failure mode of a hand-maintained list of normalisation sites. `_plain_parameter`
    rather than `_plain_number`, for `probe_precision`'s stated reason: it preserves int-vs-float and
    adds no refusal, so an unusable `rel_tol` still fails per seed and is recorded as unmeasured.
    ROUND 7 FOUND THE SIBLINGS THIS LINE DID NOT COVER EITHER -- `shift_jitter`'s `eps` and
    `shift_scale`'s `factor`, one factory down each -- which is the same sentence this docstring already
    wrote about `tol`, one round later. The line below is now ALSO covered by the parameter boundary
    (`_plain_arguments`); it is kept for the reason `_plain_text` records, and MEASURED: a mutant
    deleting it is unkilled by `test_robustness` + `test_schema` + `test_benchmark` BECAUSE the boundary
    covers it, not because it never did anything, and it would carry the guarantee alone again if the
    boundary regressed.
    ROUND 8 RE-OPENED THIS ROUTE TOO, with a DUCK-TYPED `rel_tol` storing 0.0 whose `__mul__` answers
    1e9: RE-MEASURED on 3.12.4 and 3.13.5 through this factory, INVARIANCE_DEFECT (12 violations,
    max_abs_dev 9.115e-03) -> INVARIANCE_HOLDS (0 violations) with that same `max_abs_dev` still
    serialised on the card. Closed by the TYPE requirement the boundary now applies to a parameter
    annotated `float` (`_annotated_scalar_parameters`). ONE CORRECTION TO THE RECORD, because it cuts the
    other way for this factory: `__wrapped__` is NOT a valid before/after control here for a SUBCLASS,
    since the `_plain_parameter` line below still fires on one -- but it IS valid for a DUCK, because
    `_plain_parameter` returns a non-subclass unchanged. The duck-typed before/after measurement above was
    taken that way."""
    rel_tol = _plain_parameter(rel_tol)

    def tf(fx, rng):
        order = list(range(len(fx.pred)))
        rng.shuffle(order)
        return _rebuild(fx, [fx.pred[i] for i in order], [fx.target[i] for i in order], [fx.mask[i] for i in order])
    return ShiftSpec("reorder_rows", kind, tf, bound=lambda b, e, fx: rel_tol * abs(e),
                     rationale="rows (with their mask entries) permuted jointly; a mean over selected rows is "
                               "mathematically permutation-invariant. Float equality depends on the summation.")


def shift_masked_out_rows() -> ShiftSpec:
    def tf(fx, rng):
        p, t = [list(map(list, fx.pred)), list(map(list, fx.target))]
        for i, use in enumerate(fx.mask):
            if not use:
                p[i] = [rng.uniform(-5, 5) for _ in p[i]]
                t[i] = [rng.uniform(-5, 5) for _ in t[i]]
        return _rebuild(fx, p, t)
    return ShiftSpec("replace_masked_out_rows", ShiftKind.INVARIANCE_EXACT, tf,
                     rationale="finite arbitrary values placed only in masked-OUT rows must not change the "
                               "result (ER-02 concerns NON-finite masked-out values; see missing-input probe)")


def shift_scale(factor: float, degree: int = 2) -> ShiftSpec:
    """Scale prediction and target by `factor`: MSE scales by factor**degree (degree 2; 1 for |bias|). Power-of-two factors are exact in
    binary floating point (no overflow/underflow), so they are declared EXACT; others BOUNDED.

    `factor` IS A CLOSURE VARIABLE OF THE `expected` LAMBDA, and `factor ** degree` there is
    `type(factor).__pow__` -- the number the `dev > bound` test is measured against. `math.frexp(factor)`
    on the line below reads the double the object STORES and stays honest, so the card still reads
    INVARIANCE_EXACT and `scale_4.0`. MEASURED through this public factory with no `object.__setattr__`,
    on `abs_bias_fsum` (a genuinely degree-1 measure) with `shift_scale(f, 2)` over 12 seeds, `f` a
    `float` subclass storing 4.0 whose `__pow__` returns 4.0: INVARIANCE_DEFECT (12 violations,
    max_abs_dev 1.225e-01) -> INVARIANCE_HOLDS with `n_bitwise_equal = 12`, i.e. a degree-1 measure
    certified as satisfying a DECLARED degree-2 invariance. A closure variable is not a field, which is
    why the field boundary could not reach it; it IS this factory's own parameter, which is why the
    parameter boundary does.
    ROUND 8 RE-OPENED IT WITH A DUCK-TYPED `factor`: not a `float` subclass, so nothing to collapse.
    RE-MEASURED on 3.12.4 and 3.13.5, `abs_bias_fsum` under a declared degree 2: INVARIANCE_DEFECT (12
    violations, max_abs_dev 1.225e-01) -> INVARIANCE_HOLDS with n_bitwise_equal 12 -- the same
    certification of a degree-1 measure, through the same public factory. Closed by the TYPE requirement
    the boundary now applies to a parameter annotated `float` (`_annotated_scalar_parameters`). Pinned by
    `test_robustness.TheParameterBoundaryClosesFourLiveRoutes` and
    `AClosureVariableOfAFactoryIsItsParameter`."""
    pow2 = math.frexp(factor)[0] == 0.5
    tf = lambda fx, rng: _rebuild(fx, [[x * factor for x in r] for r in fx.pred],
                                  [[x * factor for x in r] for r in fx.target])
    return ShiftSpec(f"scale_{factor!r}", ShiftKind.INVARIANCE_EXACT if pow2 else ShiftKind.SENSITIVITY_BOUNDED,
                     tf, expected=lambda b: b * factor ** degree, bound=lambda b, e, fx: _cast_bound(e, fx),
                     rationale="MSE(f*p, f*t) = f^2 MSE(p, t); rounding of f*x breaks equality unless f=2^k")


def shift_translate(c: float) -> ShiftSpec:
    tf = lambda fx, rng: _rebuild(fx, [[x + c for x in r] for r in fx.pred], [[x + c for x in r] for r in fx.target])
    return ShiftSpec(f"translate_{c!r}", ShiftKind.SENSITIVITY_BOUNDED, tf,
                     bound=lambda b, e, fx: _cast_bound(e, fx),
                     rationale="MSE depends only on p-t, so adding c to both is mathematically a no-op, but "
                               "p+c rounds and low-order bits of p-t are lost (cancellation)")


def shift_column_offsets(offsets: Sequence[float]) -> ShiftSpec:
    offsets = tuple(offsets)

    def tf(fx, rng):
        return _rebuild(fx, [[x + o for x, o in zip(r, offsets)] for r in fx.pred],
                        [[x + o for x, o in zip(r, offsets)] for r in fx.target])
    return ShiftSpec(f"column_offsets_{len(offsets)}", ShiftKind.SENSITIVITY_BOUNDED, tf,
                     bound=lambda b, e, fx: _cast_bound(e, fx),
                     rationale="per-column constant added to prediction and target; same mechanism as translate")


def shift_jitter(eps: float) -> ShiftSpec:
    """Add U(-eps, eps) to the PREDICTION only (a real perturbation, not meaning-preserving in the exact
    sense). By the triangle inequality in the RMS norm, |rms' - rms| <= rms(jitter) <= eps, hence
    |mse' - mse| <= 2*rms*eps + eps^2 (plus float slack).

    `eps` IS THE UN-SWEPT SIBLING of `shift_reorder_rows`'s `rel_tol`, one factory down, and the lie
    happens INSIDE the `bound` closure: `2 * math.sqrt(b) * eps` consults `type(eps).__rmul__` (the right
    operand is a subclass, so the reflected operator decides) and `eps * eps` its `__mul__`. Note what it
    is NOT: the already-closed `spec.bound`-RETURN route. `_plain_measure` collapses that return
    correctly, and it collapses a perfectly plain float, because the arithmetic that produced it has
    already happened. MEASURED through this public factory with no `object.__setattr__`, on
    `abs_bias_fsum` over 12 seeds with a near-zero-bias fixture family (`noise=1e-9`) and `eps` a `float`
    subclass storing 1e-6 whose `__mul__` / `__rmul__` return 1e9: SENSITIVITY_EXCEEDS_BOUND (12
    violations, max_dev_over_bound 2.924e+04) -> SENSITIVITY_WITHIN_BOUND (0 violations,
    max_dev_over_bound 1.287e-16), with `max_abs_dev` IDENTICAL in both runs (2.573404667950953e-07) --
    which is the proof that the applied jitter was unchanged and only the BOUND moved. The card then
    serialises that `max_abs_dev` beside `n_violations = 0`, the exact self-contradiction
    `shift_reorder_rows`'s docstring records.
    ROUND 8 RE-OPENED THIS ROUTE WITH THE SPELLING THE PROOF NEVER SWEPT: the subclass is collapsed, but a
    DUCK-TYPED `eps` -- an unrelated class storing 1e-6 whose `__mul__` / `__rmul__` answer 1e9 -- stores
    nothing to collapse and reached the cell unchanged. RE-MEASURED on 3.12.4 and 3.13.5 through this
    factory with no `object.__setattr__`: SENSITIVITY_EXCEEDS_BOUND (12 violations,
    max_dev_over_bound 2.924e+04) -> SENSITIVITY_WITHIN_BOUND (0 violations, 1.287e-16), with
    `max_abs_dev` IDENTICAL at 2.573404667950953e-07 in both runs. Closed by the TYPE requirement the boundary now applies to a parameter annotated `float`
    (`_annotated_scalar_parameters`): a duck-typed `eps` raises `TypeError` at the boundary, inside the
    declared family. Pinned by `test_robustness.TheParameterBoundaryClosesFourLiveRoutes` and
    `AClosureVariableOfAFactoryIsItsParameter`."""
    def tf(fx, rng):
        return _rebuild(fx, [[x + rng.uniform(-eps, eps) for x in r] for r in fx.pred])
    return ShiftSpec(f"jitter_{eps!r}", ShiftKind.SENSITIVITY_BOUNDED, tf,
                     bound=lambda b, e, fx: 2 * math.sqrt(b) * eps + eps * eps + 64 * EPS * b,
                     rationale="Lipschitz bound of RMS error under bounded perturbation of the prediction")


def standard_shifts(reorder_kind: ShiftKind = ShiftKind.INVARIANCE_EXACT, reorder_rel_tol: float = 0.0) -> tuple:
    return (shift_reorder_rows(reorder_kind, reorder_rel_tol), shift_masked_out_rows(), shift_scale(2.0 ** 10),
            shift_scale(1.7), shift_translate(1000.0), shift_column_offsets((3.0, -7.0, 0.5)), shift_jitter(1e-6))


def probe_shift(measure: Measure, spec: ShiftSpec, seeds: Sequence[int], cfg: Optional[ProbeConfig] = None, *,
                fixture_factory: Callable[[int], MeasureFixture] = make_measure_fixture,
                probe_id: Optional[str] = None) -> Scorecard:
    """Apply `spec` to a seeded fixture, compare the measure to the ideal expectation. Headline per seed:
    |measure(shifted) - expected| / expected. A violated declared invariance is reported as
    INVARIANCE_DEFECT (a defect in the measure); an exceeded sensitivity bound as SENSITIVITY_EXCEEDS_BOUND.
    `cfg=None` means a freshly constructed `ProbeConfig()`; see `_pcfg`."""
    cfg = _pcfg(cfg)
    seeds = _check_seeds(seeds)
    # `==`, NOT `is`: see `ShiftSpec.__post_init__` for the measurement. `ShiftKind` is a `str` subclass,
    # so identity here answered False for a plain string that this module could not distinguish from the
    # member by value, and the exact tier silently became the tolerance tier.
    exact_kind = spec.kind == ShiftKind.INVARIANCE_EXACT
    rows = []   # (seed, dev, expected, bound) for measured seeds
    per_seed = []
    for s in seeds:
        try:
            fx = fixture_factory(s)
            # NORMALISE AT THE DATA-INTAKE POINT. `measure` is this probe's PUBLIC input -- the whole
            # module exists to probe arbitrary measures -- and everything that decides the status is
            # arithmetic ON ITS RETURN VALUE: `dev = abs(val - exp)` and `dev > bound`. A measure
            # returning a `float` SUBCLASS therefore computes its own deviation. MEASURED, on a measure
            # that genuinely violates permutation invariance (row-position weighting), with only
            # `__sub__` / `__rsub__` overridden to return 0.0 and every comparison left honest:
            #     honest -> INVARIANCE_DEFECT, n_violations=12, max_abs_dev=1.47e-02
            #     lying  -> INVARIANCE_HOLDS,  n_violations=0,  max_abs_dev=0.0, n_bitwise_equal=12
            # i.e. the measure under probe decided that it passes, and "one failing seed refutes an
            # invariance" became unenforceable. `_plain_number` (`toy.benchmark`, the kit's single
            # normaliser) returns the double the object STORES or None; None raises here, which the
            # handler below records as an unmeasured seed with a reason -- the fail-closed outcome this
            # probe already uses for a measure that rejects its input. Same reason
            # `SeedSummary.from_values` casts with `float.__float__`.
            base = _plain_measure(measure(fx.pred, fx.target, fx.mask), "base measure")
            fx2 = spec.transform(fx, make_rng(derive_seed(s, "robustness:shift:" + spec.name)))
            val = _plain_measure(measure(fx2.pred, fx2.target, fx2.mask), "shifted measure")
            exp = _plain_measure(spec.expected(base), "expected value")
            if not (math.isfinite(exp) and exp > 0):
                raise ValueError("expected value is not positive; relative deviation undefined")
            dev = abs(val - exp)
            # `_plain_measure`, not a bare `float(...)`: this is the GENERAL FORM of the `rel_tol` defect
            # above, and the last un-normalised number on this path. `spec.bound` is public (a caller
            # supplies the spec), `bound` is the right operand of the `dev > bound` that decides the
            # status, and a bare `float()` consults a `__float__` OVERRIDE -- while `measure`'s and
            # `spec.expected`'s returns, four and seven lines up, both go through `_plain_measure`. A
            # bound that is not a usable number now makes the seed unmeasured with a reason, the
            # fail-closed outcome this probe already uses everywhere else.
            bound = 0.0 if exact_kind else _plain_measure(spec.bound(base, exp, fx2), "deviation bound")
            rows.append((s, dev, exp, bound))
            per_seed.append(MetricValue.measured(float(dev / exp)))
        except (ValueError, TypeError, ArithmeticError) as e:
            per_seed.append(MetricValue.unmeasured(f"{_type_name(e)}: {_shown(e, how=str)}"))
    viol = [r for r in rows if r[1] > r[3]]
    bounded = spec.kind == ShiftKind.SENSITIVITY_BOUNDED   # `==`, not `is`: see `ShiftSpec.__post_init__`
    ok_status = ProbeStatus.SENSITIVITY_WITHIN_BOUND if bounded else ProbeStatus.INVARIANCE_HOLDS
    bad_status = ProbeStatus.SENSITIVITY_EXCEEDS_BOUND if bounded else ProbeStatus.INVARIANCE_DEFECT
    ratios = [r[1] / r[3] for r in rows if r[3] > 0]
    return build_scorecard(
        probe_id=probe_id or f"shift:{_callable_name(measure)}:{_shown(spec.name, how=str)}",
        probe_kind="benign_shift", seeds=seeds, per_seed=per_seed, cfg=cfg,
        status_if_summarized=bad_status if viol else ok_status,
        details_always={"measure": _name_attr(measure, "measure"), "transform": spec.name,
                        "declared_kind": spec.kind, "rationale": spec.rationale,
                        "error_register": ["ER-09 (generic summation-order mechanism only; no device compared)"]
                        if spec.name == "reorder_rows" else
                        ["ER-02 (finite-value case only)"] if spec.name == "replace_masked_out_rows" else []},
        details_if_summarized={
            "n_violations": len(viol), "violating_seeds": [r[0] for r in viol],
            "n_bitwise_equal": sum(r[1] == 0.0 for r in rows), "n_measured": len(rows),
            "max_abs_dev": max((r[1] for r in rows), default=None),
            "max_rel_dev": max((r[1] / r[2] for r in rows), default=None),
            "max_dev_over_bound": max(ratios) if ratios else None,
            "unmeasured_seeds": [sd for sd, m in zip(seeds, per_seed) if not _metric_ok(m)]},
        non_claims=("Bounds are hand-derived caps for this fixture family; a pass does not show the measure "
                    "is robust to any perturbation outside the probed family.",))


# ===================================================== 3. missing-input handling
def arm_difference(arms: Mapping[str, MetricValue], treatment: str, control: str) -> MetricValue:
    """treatment - control as a MetricValue; any absent or unmeasured arm => unmeasured(reason). Never 0.0.

    NORMALISE THE NAMES, AND THE MAPPING'S KEYS, BEFORE THE MEMBERSHIP TEST. `nm not in arms` is
    `__hash__` plus `__eq__` on the caller's name against the caller's keys, and neither was type-checked
    or normalised. MEASURED, through this public function with no `object.__setattr__`, on a `str`
    SUBCLASS holding "E" that hashes as "C0" and answers True to `__eq__`: an absent treatment arm
    returned `MetricValue(value=0.0, reason=None)` instead of `MetricValue(value=None, reason="arm 'E'
    absent")`, and over ten seeds the card that records it went INSUFFICIENT_EVIDENCE ->
    MEASURED, `summary={"n": 10, "mean": 0.0, "sd": 0.0, ...}`, with the UNKNOWN evidence label the
    honest card carries GONE. `test_robustness.test_R_arm_diff_an_unusable_arm_gives_unmeasured_never_zero`
    had already named that exact outcome as forbidden -- "in particular NEVER `measured(0.0)` -- a
    missing arm reading as a zero contrast is the single most dangerous substitution in this kit" -- while
    sweeping only the VALUES axis (`forge(arms[which], bad)`); the NAMES axis was untouched, and it is
    the axis that carried the defect. This is NOT a dataclass field, so the
    `toy.schema._normalise_fields` boundary cannot reach it: a function parameter used as a dict key is
    normalised where it is bound."""
    if not isinstance(arms, Mapping):
        raise ValueError(f"arms must be a mapping, got {_type_name(arms)}")
    arms = _plain_value(arms)       # keys plain, and two keys that collapse to one are refused loudly
    names = []
    for nm in (treatment, control):
        if not isinstance(nm, str) or not nm.strip():
            raise ValueError(f"arm name must be a nonblank string, got {_type_name(nm)}")
        names.append(_plain_value(nm))
    treatment, control = names
    for nm in (treatment, control):
        if nm not in arms:
            return MetricValue.unmeasured(f"arm {nm!r} absent")
        if not isinstance(arms[nm], MetricValue):
            raise ValueError(f"arm {nm!r} must be a MetricValue")
        if not _metric_ok(arms[nm]):
            return MetricValue.unmeasured(f"arm {nm!r} unmeasured: {arms[nm].reason}")
    return MetricValue.measured(_metric_read(arms[treatment]) - _metric_read(arms[control]))


def guarded(measure: Measure) -> Callable[..., MetricValue]:
    """Wrap a measure so rejection becomes MetricValue.unmeasured(reason) instead of an exception.

    THAT SENTENCE WAS BREACHED OUTRIGHT until round 12, and by the two lines that build the reason. A
    measure returning a value whose `__repr__` raises `RuntimeError`, and a measure raising an exception
    whose own `__str__` raises, both came OUT of this wrapper as that exception -- measured on 3.12.4 and
    3.13.5 -- because `{v!r}` and `f"{type(e).__name__}: {e}"` run the caller's protocols after the
    decision to reject has been taken. Both reasons are built through `_shown` / `_type_name` now, so a
    rejection this wrapper cannot DESCRIBE is still a rejection it REPORTS."""
    def run(pred, target, mask) -> MetricValue:
        try:
            v = measure(pred, target, mask)
        except (ValueError, TypeError, ArithmeticError) as e:
            return MetricValue.unmeasured(f"{_type_name(e)}: {_shown(e, how=str)}")
        if isinstance(v, bool) or not isinstance(v, float) or not math.isfinite(v):
            return MetricValue.unmeasured(f"non-float or non-finite result {_shown(v)}")
        return MetricValue.measured(v)
    run.__name__ = _name_attr(measure, "measure")
    return run


def missing_input_cases(fx: MeasureFixture) -> dict:
    p, t, m, n = fx.pred, fx.target, fx.mask, len(fx.pred)
    first_in, first_out = m.index(True), m.index(False)

    def with_value(rows, i, v):
        rows = [list(r) for r in rows]
        rows[i][0] = v
        return tuple(map(tuple, rows))
    return {
        "absent_rows": ((), (), ()),
        "absent_rows_prediction_only": ((), t, m),
        "absent_rows_target_only": (p, (), m),
        "absent_columns": (tuple(() for _ in p), tuple(() for _ in t), m),
        "ragged_columns": (p[:-1] + (p[-1][:-1],), t, m),
        "all_false_mask": (p, t, (False,) * n),
        "empty_mask": (p, t, ()),
        "mask_is_none": (p, t, None),
        "mask_truthy_not_bool": (p, t, tuple(1 if b else 0 for b in m)),
        "missing_value_none": (with_value(p, first_in, None), t, m),
        "nan_in_selected_row": (with_value(p, first_in, math.nan), t, m),
        "nan_in_masked_out_row": (with_value(p, first_out, math.nan), t, m),
        "inf_in_selected_row": (with_value(p, first_in, math.inf), t, m),
        "neg_inf_in_selected_row": (with_value(p, first_in, -math.inf), t, m),
        "inf_in_masked_out_row": (with_value(p, first_out, math.inf), t, m),
    }


def _run_cases(measure: Measure, fx: MeasureFixture) -> dict:
    # REFUSE A MEASURE THAT CANNOT BE CALLED, before any case runs. Every case below treats an exception
    # as the GOOD outcome ("the measure rejected an input it must reject"), so for this probe -- alone
    # among the five -- a `measure` that is not callable at all makes every case pass: the `TypeError`
    # from `measure(*args)` is caught by the same handler. MEASURED round 11:
    #     probe_missing_inputs(42, SEEDS, CFG) -> MISSING_INPUT_HANDLED, labels [NOT_VALIDATED,
    #         TOY_RESULT], summary n=12 mean=0.0, n_silent_value_total=0, 15 of 15 cases "RAISED
    #         TypeError" -- the same headline as an honest run of `mse_fsum`, distinguished only by the
    #         `case_table`'s exception types; and `assert_no_silent_default(42)` returned without a
    #         complaint, i.e. CERTIFIED a measure it never called.
    # A measured 0.0 for a measure that was never invoked is a claim this kit refuses everywhere else,
    # and the sibling probes already fail closed on the same input (`probe_shift`, `probe_precision` and
    # `seed_sensitivity_probe` all return INSUFFICIENT_EVIDENCE with every seed unmeasured; `guarded`
    # returns `MetricValue.unmeasured`), so this is the one that was out of step. `TypeError` is inside
    # the `(ValueError, TypeError, ArithmeticError)` family both public callers declare.
    # AND ROUND 11'S OWN REFUSAL ESCAPED THE FAMILY IT WAS WRITTEN TO HONOUR: `type(measure).__name__`
    # on the line below is an attribute lookup on the caller's class, so a metaclass answering it with a
    # raising property turned this `TypeError` into a propagating `RuntimeError` -- measured on both
    # interpreters. The type name is read through `_type_name` now, like every other one here.
    if not callable(measure):
        raise TypeError(f"measure must be callable, got {_type_name(measure)}: every case here counts "
                        "a raised exception as correct handling, so an uncallable measure would be "
                        "reported as handling every missing input")
    out = {}
    for name, args in missing_input_cases(fx).items():
        # THE RECORD IS TAKEN OUTSIDE THE CLASSIFIER'S `try`, and that is the whole fix. `repr(v)` used
        # to sit INSIDE the handler whose only job is to decide whether the measure raised, so a failure
        # in the RECORDING was recorded as the opposite outcome. MEASURED round 12 on 3.12.4 and 3.13.5,
        # 12 seeds, `ProbeConfig(10)`, a measure returning a value whose `__repr__` raises `ValueError`:
        #     invoked 180 times, returned a value for 15 of 15 cases x 12 seeds, and the card read
        #     MISSING_INPUT_HANDLED, labels [NOT_VALIDATED, TOY_RESULT], summary n=12 mean=0.0,
        #     `n_silent_value_total` = 0, every `case_table` row {"raised": 12, "silent_value": 0} --
        #     while the control (a measure returning a plain 0.0) is SILENT_DEFAULT_DEFECT with 180.
        #     `assert_no_silent_default` returned None, i.e. CERTIFIED it. The forged card differed from
        #     an honest `mse_fsum` card in ONE key: the `case_table`'s `types` column.
        # The same verdict flip as round 11's uncallable measure, through the diagnostic instead of
        # through the call -- so the classification is now decided by WHERE the call returned, and the
        # record built afterwards, from a value the classifier has already finished with.
        try:
            v = measure(*args)
        except (ValueError, TypeError, ArithmeticError) as e:
            out[name] = ("RAISED", _type_name(e))
            continue
        out[name] = ("SILENT_VALUE", _silent_detail(v))
    return out


def _silent_detail(v: Any) -> str:
    """The diagnostic a SILENT_VALUE case records, built from a measure's UNVALIDATED return.

    `_to_metric` is the model, and an attester called the choice it makes a better one than `repr`: it
    reads `type(v).__name__`, not the object's own description. Here BOTH are needed -- the number is
    diagnostically the point, because `assert_no_silent_default` reads this text to name a returned 0.0,
    "the most dangerous substitution" by its own docstring -- so the NUMBER comes from `_plain_number`,
    which reads the double the object STORES and consults no `__float__`/`__repr__` override, and
    anything that is not a number is named by its type with its description appended through `_shown`.
    WHY, measured: a `float` SUBCLASS storing 0.0 whose `__repr__` answers "1.0" moved the
    `[SILENT ZERO]` tag from 45 of 45 cases to 0 of 45 on both interpreters, i.e. the measure chose
    which of its own silent defaults got named, with the complaint still firing. `repr` of a plain
    `float` cannot raise and cannot lie; a `Fraction` (the exact oracle's return) still gets its value
    shown, through the admission."""
    f = _plain_number(v)
    if f is not None:
        return repr(f)
    return f"{_type_name(v)}: {_shown(v)}"


def assert_no_silent_default(measure: Measure, seeds: Sequence[int] = (0, 1, 2)) -> None:
    """Fail LOUDLY (SilentDefaultError) if `measure` returns any value for an input it must reject, and
    separately name a returned 0.0 (the most dangerous substitution)."""
    bad = []
    for s in _check_seeds(seeds):
        for case, (how, detail) in _run_cases(measure, make_measure_fixture(s)).items():
            if how == "SILENT_VALUE":
                bad.append(f"seed {s}: {case} -> {detail}" + ("  [SILENT ZERO]" if detail in ("0.0", "-0.0") else ""))
    if bad:
        raise SilentDefaultError("measure returned a value instead of rejecting: " + "; ".join(bad))


def probe_missing_inputs(measure: Measure, seeds: Sequence[int], cfg: Optional[ProbeConfig] = None, *,
                         probe_id: Optional[str] = None) -> Scorecard:
    """Per seed the headline is the COUNT of missing-input cases answered with a value (0 = every case
    raised/unmeasured; this is a count of defects, not a measurement default). Also runs two structural
    checks once: empty seed list => INSUFFICIENT_EVIDENCE, and absent arm => unmeasured.
    `cfg=None` means a freshly constructed `ProbeConfig()`; see `_pcfg`."""
    cfg = _pcfg(cfg)
    seeds = _check_seeds(seeds)
    per_seed, table = [], {}
    for s in seeds:
        res = _run_cases(measure, make_measure_fixture(s))
        per_seed.append(MetricValue.measured(float(sum(h == "SILENT_VALUE" for h, _ in res.values()))))
        for case, (how, detail) in res.items():
            row = table.setdefault(case, {"raised": 0, "silent_value": 0, "types": []})
            row["raised" if how == "RAISED" else "silent_value"] += 1
            if how == "RAISED" and detail not in row["types"]:
                row["types"].append(detail)
    empty = seed_sensitivity_probe(lambda s: 1.0, (), cfg)
    arm = arm_difference({"C0": MetricValue.measured(0.0)}, "E", "C0")
    structural = {"empty_seed_list_gives_insufficient": empty.status == ProbeStatus.INSUFFICIENT_EVIDENCE
                  and empty.summary is None,
                  "absent_arm_gives_unmeasured": (not _metric_ok(arm)) and arm != MetricValue.measured(0.0)}
    silent_total = sum(r["silent_value"] for r in table.values())
    defect = silent_total > 0 or not all(structural.values())
    return build_scorecard(
        probe_id=probe_id or f"missing_inputs:{_callable_name(measure)}",
        probe_kind="missing_inputs", seeds=seeds, per_seed=per_seed, cfg=cfg,
        status_if_summarized=ProbeStatus.SILENT_DEFAULT_DEFECT if defect else ProbeStatus.MISSING_INPUT_HANDLED,
        details_always={"measure": _name_attr(measure, "measure"), "cases": sorted(missing_input_cases(
            make_measure_fixture(seeds[0] if seeds else 0))),
            "error_register": ["ER-01 (empty/all-False mask must be loud)", "ER-02 (NaN under a mask)"]},
        details_if_summarized={"case_table": table, "structural_checks": structural,
                               "structural_checks_scope": "these test library behaviour (seed-probe and "
                               "arm_difference), NOT the measure under probe; they cannot fail because of the measure",
                               "n_silent_value_total": silent_total},
        non_claims=("Only the enumerated missing-input cases were tried; handling of other malformed inputs "
                    "is unknown.",))


# ===================================================== 4. numerical stability
def plain_loop_mean(values: Sequence[float]) -> float:
    """COUNTERFACTUAL REFERENCE, not kit code: explicit left-to-right float accumulation. CPython >= 3.12
    `sum()` on floats is compensated (Neumaier), so `toy.stability` is more accurate there than this loop;
    CPython < 3.12 `sum()` behaves like this loop. Included to quantify what that dependency hides."""
    t = 0.0
    for v in values:
        t += v
    return t / len(values)


def abs_bias_plain(pred, target, mask) -> float:
    """|mean(pred - target)| with a plain accumulation loop (counterfactual reference measure)."""
    d = _signed_diffs(pred, target, mask)
    return abs(plain_loop_mean([x for r in d for x in r]))


def _precision_outcome(kind: str, param: float, seed: int, measure: Measure = mse_naive) -> dict:
    """-> dict(stab, plain, fsum, plain_bound, silent_zero) relative errors vs exact rational arithmetic.
    'stab' is the actual `toy.stability` path. Raises on loud failure."""
    rng = make_rng(derive_seed(seed, f"robustness:precision:{kind}"))
    if kind == "magnitude":
        fx = make_measure_fixture(seed, rows=8)
        sc = 10.0 ** param
        p = tuple(tuple(x * sc for x in r) for r in fx.pred)
        t = tuple(tuple(x * sc for x in r) for r in fx.target)
        exact = exact_masked_mse(p, t, fx.mask)
        naive = measure(p, t, fx.mask)
        try:
            fs_err = _rel_err(mse_fsum(p, t, fx.mask), exact)
        except (ValueError, TypeError, ArithmeticError):
            fs_err = None   # the comparison path refused loudly; that is recorded as absence, not as a number
        return {"stab": _rel_err(naive, exact), "plain": None, "fsum": fs_err, "plain_bound": None,
                "silent_zero": naive == 0.0 and exact != 0}
    if kind == "cancellation":
        big = 10.0 ** param * (1.0 + rng.random())
        b = 0.5 + rng.random()
        vals = [big, b, -big]
        exact = _exact_sum(vals) / 3
        return {"stab": _rel_err(stability.masked_mean_checked(vals, [True] * 3, 3), exact),
                "plain": _rel_err(plain_loop_mean(vals), exact), "fsum": _rel_err(math.fsum(vals) / 3, exact),
                "plain_bound": U * (abs(big) + b) / b * 1.01 + 2 * U, "silent_zero": False}
    if kind == "accumulation":
        n = int(param)
        vals = [0.05 + 0.1 * rng.random() for _ in range(n)]
        exact = _exact_sum(vals) / n
        return {"stab": _rel_err(stability.masked_mean_checked(vals, [True] * n, n), exact),
                "plain": _rel_err(plain_loop_mean(vals), exact), "fsum": _rel_err(math.fsum(vals) / n, exact),
                "plain_bound": n * U / (1 - n * U), "silent_zero": False}
    raise ValueError(f"unknown precision kind {kind!r}")


def probe_precision(kind: str, param: float, seeds: Sequence[int], cfg: Optional[ProbeConfig] = None, *,
                    tol: float = 1e-12, measure: Measure = mse_naive) -> Scorecard:
    """Quantify precision loss of the `toy.stability` path against exact rational arithmetic.
    kind: 'magnitude' (data scaled by 10**param; squares may under/overflow), 'cancellation' (values
    [M, b, -M], M ~ 10**param), 'accumulation' (mean of `param` positive values). Headline per seed = relative
    error of the stability path. Also reported: the exactly rounded fsum path and a counterfactual plain-loop
    path (see `plain_loop_mean`: the stability path's accuracy depends on the CPython version). A loud failure
    (validators raise, e.g. overflow) makes that seed unmeasured with the reason; a silent total loss
    (underflow to a measured 0.0 whose exact value is nonzero) is counted as `n_silent_zero`. `measure` (used by
    'magnitude' only) lets a test supply a measure without the underflow guard.
    `cfg=None` means a freshly constructed `ProbeConfig()`; see `_pcfg`."""
    cfg = _pcfg(cfg)
    if kind not in ("magnitude", "cancellation", "accumulation"):
        raise ValueError(f"unknown precision kind {kind!r}")
    # NORMALISE BEFORE COMPARING, at this probe's two numeric entry points. `worst > tol` decides
    # PRECISION_OK vs PRECISION_LOSS with `tol` as the RIGHT operand, so the reflected operator of a
    # `float` subclass decides it. MEASURED: `tol=WTol(1e-20)` with `__lt__`/`__gt__` returning False
    # reported PRECISION_OK on a worst relative error of 5.49e-17, while `details["tolerance"]`
    # serialized the honest 1e-20 -- a card whose declared tolerance and whose status disagree.
    # `param` is used as `int(param)` (the number of values accumulated) and recorded as
    # `float(param)`: two independently overridable conversions, so `details["param"]` and `probe_id`
    # said 3.0 while 400 values were actually summed.
    # `_plain_parameter`, not `_plain_number`: it collapses a subclass to the value it stores while
    # PRESERVING int-vs-float and leaving a non-number untouched, so this adds no refusal that did not
    # already happen (an unusable `param` still fails per seed, recorded as unmeasured) and `probe_id`
    # text is unchanged for an int `param`.
    # AND THEIR SIBLING IN THE SAME SIGNATURE, which these two lines did not cover and which round 7
    # found: `kind`. The membership gate above and the construction dispatch in `_precision_outcome`
    # (`kind == "magnitude"`, then `== "cancellation"`, then `== "accumulation"`) are
    # `type(kind).__eq__`, and `refs[kind]` below is `__hash__` plus `__eq__`, while `details["kind"]`
    # and `probe_id` serialise the characters the object STORES. MEASURED through this public parameter
    # with no `object.__setattr__`: a `str` subclass storing "magnitude" that compares and hashes as
    # "cancellation" (`isinstance`, `str.__str__` and `repr` all honest) ran the CANCELLATION
    # construction under a card reading `probe_id='precision:magnitude:200.0'` and
    # `details["kind"]='magnitude'` -- INSUFFICIENT_EVIDENCE -> PRECISION_OK, evidence labels
    # (NOT_VALIDATED, UNKNOWN) -> (NOT_VALIDATED, TOY_RESULT), summary None -> n=12, mean=3.799e-17,
    # sd=2.928e-17: a MEASUREMENT appearing where the honest run has NONE. It is covered now by
    # `_plain_arguments`, not by a third line here -- that is the whole point of the parameter boundary
    # -- and these two lines are kept for the reason `_plain_text` records (their removal is
    # unobservable because something STRONGER covers them, not because they never did anything).
    tol = _plain_parameter(tol)
    param = _plain_parameter(param)
    seeds = _check_seeds(seeds)
    per_seed, rows = [], []
    for s in seeds:
        try:
            r = _precision_outcome(kind, param, s, measure)
        except (ValueError, TypeError, ArithmeticError) as e:
            per_seed.append(MetricValue.unmeasured(f"{_type_name(e)}: {_shown(e, how=str)}"))
            continue
        per_seed.append(MetricValue.measured(r["stab"]))
        rows.append(r)
    worst = max((r["stab"] for r in rows), default=0.0)
    plains = [r for r in rows if r["plain"] is not None]
    refs = {"magnitude": ["ER-02 (non-finite hidden/propagated); silent underflow is not a catalogued ER item"],
            "cancellation": ["ER-09 (generic summation/precision mechanism only; no device compared)"],
            "accumulation": ["ER-09 (same caveat)", "ER-05 (denominator was stated explicitly here)"]}[kind]
    return build_scorecard(
        probe_id=f"precision:{kind}:{param!r}", probe_kind="numerical_stability", seeds=seeds, per_seed=per_seed,
        cfg=cfg, status_if_summarized=ProbeStatus.PRECISION_LOSS if worst > tol else ProbeStatus.PRECISION_OK,
        details_always={"kind": kind, "param": float(param), "tolerance": tol,
                        "reference": "exact rational arithmetic", "python_version": current_python_version(),
                        "error_register": refs},
        details_if_summarized={
            "max_stability_rel_err": worst, "max_fsum_rel_err": max((r["fsum"] for r in rows if r["fsum"] is not None), default=None),
            "max_plain_loop_rel_err": max((r["plain"] for r in plains), default=None),
            "plain_loop_worst_case_bound": max((r["plain_bound"] for r in plains), default=None),
            "max_plain_over_bound": max((r["plain"] / r["plain_bound"] for r in plains), default=None),
            "n_silent_zero": sum(bool(r["silent_zero"]) for r in rows),
            "n_unmeasured_loud": len(seeds) - len(rows)},
        non_claims=("Precision loss is quantified for the named construction only; it says nothing about "
                    "accuracy of any other computation, and nothing about GPU/device variance.",
                    "Results for the stability path depend on the CPython version (sum() is compensated "
                    "from 3.12); they were produced on the version recorded in details.python_version."))


def precision_sweep(kind: str, params: Sequence[float], seeds: Sequence[int], cfg: Optional[ProbeConfig] = None,
                    *, tol: float = 1e-12) -> tuple:
    """`cfg=None` means a freshly constructed `ProbeConfig()`; see `_pcfg`."""
    return tuple(probe_precision(kind, p, seeds, _pcfg(cfg), tol=tol) for p in params)


# ============================================ normalisation AT THE PARAMETER BOUNDARY
# The field boundary (`toy.schema._normalise_fields`, driven by `dataclasses.fields()`) ended the
# hand-maintained list of normalisation sites FOR FIELDS, and its own docstring stated the gap it left:
# "a function PARAMETER or a closure variable is not a field, so `arm_difference`'s names,
# `shift_reorder_rows`'s `rel_tol`, `probe_precision`'s `tol` / `param` ... are normalised where they are
# bound". THAT SENTENCE WAS A LIST, and a list of remembered sites is the defect, not the fix: round 7
# found four live routes in it, all in this module and none of them named -- `probe_precision`'s `kind`
# (the sibling of `tol` and `param` in the SAME signature), `shift_jitter`'s `eps` and `shift_scale`'s
# `factor` (closure variables of a factory, i.e. the factory's own parameters), and
# `make_measure_fixture`'s `rows`, which DEFEATS ITS OWN `rows < 4` GATE because that gate is
# `type(rows).__lt__`. Each was one line at the bind site; three previous rounds ended by writing exactly
# that line at the sites the round happened to find. So the parameter list is computed, like the field
# list: see `_install_parameter_boundary`.

_WHY_CALLABLE_NUMBER = (
    "a callable: a function object stores no scalar for `_plain_value` to collapse, and what it RETURNS "
    "is normalised where it is CONSUMED -- `_to_metric` (an outcome), `_plain_measure` (a measure, an "
    "expectation, a bound) or `_metric_read` -- each with its own consequence test in "
    "`test_robustness.AMeasureCannotDecideItsOwnProbe` / `EveryMetricReadSiteIsPinnedByItsConsequence`. "
    "EXERCISED ON ALL SEVEN PARAMETERS it covers since round 11, in two limbs -- a callable whose return "
    "no normaliser can read, and a value that is not callable at all -- and the second limb found "
    "`probe_missing_inputs`, the one probe for which a raised exception is the GOOD outcome: it reported "
    "MISSING_INPUT_HANDLED with a measured mean of 0.0 for `measure=42`, having invoked 0 of 15 cases, "
    "and `assert_no_silent_default(42)` certified the same measure. Both refuse an uncallable measure "
    "now, in `_run_cases`, where the measurement is written out. "
    "AND THE SENTENCE ABOVE WAS SHORT BY ONE CONSUMER, which round 12 measured: `_run_cases` never "
    "normalises and never type-checks this return at all -- `guarded`, four lines of this module away, "
    "DOES -- it only `repr()`d it, INSIDE the handler that decides whether the measure raised, so a "
    "measure returning a value whose `__repr__` raises `ValueError` was recorded as having RAISED for "
    "15 of 15 cases x 12 seeds and certified MISSING_INPUT_HANDLED, and `assert_no_silent_default` "
    "returned None for it. The classification is taken from WHERE the call returned now, and the record "
    "is built afterwards by `_silent_detail` -- the number from `_plain_number`, which is what makes the "
    "`[SILENT ZERO]` tag unforgeable, and anything else from `_type_name` / `_shown`. THE LANE THAT "
    "FOUND IT is the one this reason is exercised by: `test_robustness._exercise_callable_number` had no "
    "RAISE member until round 12, and no lane in that file had one, while six sweeps carried an "
    "`OUTSIDE the declared family` branch that nothing in the file could make fire")
_WHY_CALLABLE_FIXTURE = (
    "a callable whose return is a fixture; stores no scalar to collapse. STATED AS WHAT IT IS, because "
    "the obvious reason is the wrong one: `probe_shift` does NOT type-check this return, so "
    "`MeasureFixture.__post_init__` is not what protects it -- a duck-typed `SimpleNamespace` reaches "
    "`measure` and `_masked_stats` unchallenged. The protection is consumption-side: `_plain_measure` on "
    "the measure's return and on `spec.bound`'s return. See `ShiftSpec._NORMALISE_EXEMPT['transform']` "
    "for the measurement. THE OTHER CONSEQUENCE OF NOT TYPE-CHECKING THE RETURN, measured by round 11's "
    "reason-coverage probe and NOT closed: a factory returning something with no `pred` attribute at all "
    "raises `AttributeError` out of `probe_shift`, OUTSIDE the "
    "`(ValueError, TypeError, ArithmeticError)` family the probe declares. It is left open, unlike the "
    "`rows=Lo(2)` escape of `test_F4_the_second_consequence...`, because that one came from the MODULE's "
    "own code and this one cannot be closed by a check at all: the factory is the caller's callable and "
    "may raise any exception before it returns anything, so a return-type gate would move the escape "
    "rather than remove it. What it is NOT is a status flip -- every seed is unmeasured or the call "
    "propagates, so no card is produced")
_WHY_CARRIER = (
    "a carrier object (a dataclass instance, or None): a real one normalises its OWN fields at its own "
    "boundary (`_normalise_fields` in its `__post_init__`), and `_plain_value` does not reach across a "
    "dataclass by design, so the boundary composes instead of re-walking. STATED AS WHAT IT IS, because "
    "the sibling claim about `ShiftSpec.transform` was falsified in exactly this way: apart from "
    "`require_summary`, which type-checks, a DUCK-TYPED object carrying the right attributes is NOT "
    "refused here. What protects the values it carries is that each is re-validated where it is read -- "
    "`ProbeConfig(cfg.min_seeds)` on both paths that read a config's minimum (`summarize_seeds` and "
    "`Scorecard.__post_init__`), `_plain_measure` on a spec's callable returns, and "
    "`Scorecard.__post_init__` on every field a real card carries. WHAT THAT LEAVES, measured: "
    "`scorecard_to_record` type-checks nothing either, so a hand-built namespace whose `min_seeds` has a "
    "lying `__float__` yields a record reading `min_seeds_required = 1.0` beside an `input_hashes` entry "
    "for a card that says 10. THE CONSEQUENCE IS SHARPER THAN THAT SENTENCE RECORDED, and round 11 "
    "measured it rather than leaving the weaker number as the note: the same namespace, carrying 12 "
    "measured seeds and a summary while its `content_hash` is bound to a REAL "
    "`INSUFFICIENT_EVIDENCE` card, yields a record whose `evidence_class` is TOY_RESULT (not UNKNOWN) "
    "with `mean = 0.0` and `n_seeds = 12.0`, while `provenance.input_hashes[\"scorecard\"]` IS the hash "
    "of the card whose own honest record reads `3 measured of 3 seeds; minimum is 10` and carries every "
    "statistic as unmeasured -- a summary where the honest run has no measurement at all, the sharpest "
    "shape this kit names, not merely a disagreeing minimum. Still a note and not a closure, for the "
    "unchanged `transform` reasoning: a caller who can hand-build that namespace can write any "
    "`ExperimentRecord` directly, so it grants them nothing they lack")
_WHY_CARRIER_SEQ = (
    "a sequence of `MetricValue` carriers, each of which normalises its own fields in its own "
    "`__post_init__` (`_normalise_fields`, in `toy.schema`); both consumers "
    "(`summarize_seeds`, `Scorecard.__post_init__`) refuse anything that is not EXACTLY a `MetricValue`, "
    "so there is no scalar here for `_plain_value` to reach. THE WORD \"BOTH\" WAS FALSE UNTIL ROUND 11: "
    "`Scorecard.__post_init__` was made exact-type by round 6 (honest limit (3) of its docstring) and "
    "`summarize_seeds` was left on `isinstance`, so a `MetricValue` SUBCLASS reached it. Measured "
    "consequence, written out in that function's own comment and stated at its real weight: a subclass "
    "answering `value` with 1.0 turns `Sub(None, None)` x12 into `SeedSummary(n=12, mean=1.0)` where the "
    "honest spelling gives `InsufficientEvidence(0 of 12)` -- but `__post_init__` then STORES that 1.0, "
    "so the object is one `MetricValue.measured(1.0)` would have been, and the subclass grants a caller "
    "nothing they lack. A reason correction and three sibling checks made to agree, not a status flip")
_WHY_ENUM = (
    "an `Enum` member: `_plain_value` passes an Enum through by a TYPE rule, because `ProbeStatus` / "
    "`ShiftKind` / `EvidenceClass` are `str` subclasses BY CONSTRUCTION and collapsing one would destroy "
    "the `isinstance` checks that refuse a forged spelling. A non-enum spelling offered at ANY of the "
    "three parameters this covers is refused by one of those two `isinstance` gates -- "
    "`Scorecard.__post_init__` for `build_scorecard.status_if_summarized`, `ShiftSpec.__post_init__` for "
    "`shift_reorder_rows.kind` and the `standard_shifts.reorder_kind` that forwards to it. "
    "THE SECOND HALF OF THIS SENTENCE USED TO NAME A MECHANISM THAT DOES NOT EXIST: it said such a "
    "spelling is \"either refused by that `isinstance` or COLLAPSED BY THE FIELD BOUNDARY of the "
    "dataclass it is stored in (`ShiftSpec.kind`)\", and the field boundary collapses NOTHING here -- a "
    "plain `str` already stores exactly itself, so `_plain_value` returns it unchanged and both disjuncts "
    "were false for 2 of the 3 parameters. What that cost is measured in `ShiftSpec.__post_init__`, "
    "which now carries the gate: an honest INVARIANCE_DEFECT on 12 of 12 seeds became INVARIANCE_HOLDS "
    "with n_violations=0 at an IDENTICAL max_abs_dev. The general lesson, and the reason the test that "
    "polices these reasons is now a derived generator: a disjunction is the wrong invariant when one of "
    "its disjuncts is satisfied by an HONEST value -- a plain string collapses to itself, and the defect "
    "was that the comparison reading it used `is`")
_WHY_MASK = (
    "a mask is a sequence of STRICT bools, and `bool` cannot be subclassed, so no element here can lie; "
    "a non-bool element is refused loudly by `toy.stability.check_mask` (\"must be a strict bool ... "
    "truthiness is not accepted\"), inside the documented ValueError family. TRUE OF ALL SIX MEASURES "
    "THIS COVERS, and it was not when the test policing it exercised 3 of them: `exact_masked_mse` "
    "called no validator at all, accepted an `int` mask where every sibling raises `MaskTypeError`, and "
    "silently measured 2 of 16 rows from a SHORT mask. It calls `check_mask` now; what it still does not "
    "validate (its matrices, deliberately, because it is the exact oracle and must accept a `Fraction`) "
    "is stated in its own docstring with the probe number that shows it")

# PER (function, parameter): the parameters for which the boundary's `_plain_value` call cannot collapse
# anything, and WHAT PROTECTS THEM INSTEAD. Two things this map is NOT, because the word "exempt" has
# meant something stronger elsewhere in this kit:
#   * it is not consulted by the boundary. `_install_parameter_boundary` skips nothing, so no entry here
#     can create a hole, and a wrong entry cannot stop a parameter being normalised. (Contrast
#     `_NORMALISE_EXEMPT` on a dataclass, which really does skip the field.)
#   * it is not a reviewer's assertion. `test_robustness.EveryPublicParameterIsNormalisedOrExplicitlyExempt`
#     polices it in BOTH directions: a parameter absent from this map must be PROVEN to arrive plain at
#     the callee when a subclass is passed, and a parameter present in it must be PROVEN unable to carry
#     a collapsible scalar in the first place. An entry written for a parameter that can carry one FAILS.
_PARAMETER_NO_SCALAR = MappingProxyType({
    "summarize_seeds": MappingProxyType({"per_seed": _WHY_CARRIER_SEQ}),
    "require_summary": MappingProxyType({"result": _WHY_CARRIER}),
    "build_scorecard": MappingProxyType({"per_seed": _WHY_CARRIER_SEQ, "cfg": _WHY_CARRIER,
                                         "status_if_summarized": _WHY_ENUM}),
    "scorecard_to_record": MappingProxyType({"sc": _WHY_CARRIER}),
    "seed_sensitivity_probe": MappingProxyType({"outcome": _WHY_CALLABLE_NUMBER, "cfg": _WHY_CARRIER}),
    "benchmark_outcome": MappingProxyType({"factory": _WHY_CALLABLE_NUMBER, "cfg": _WHY_CARRIER}),
    "mse_naive": MappingProxyType({"mask": _WHY_MASK}),
    "mse_fsum": MappingProxyType({"mask": _WHY_MASK}),
    "abs_bias_naive": MappingProxyType({"mask": _WHY_MASK}),
    "abs_bias_fsum": MappingProxyType({"mask": _WHY_MASK}),
    "abs_bias_plain": MappingProxyType({"mask": _WHY_MASK}),
    "exact_masked_mse": MappingProxyType({"mask": _WHY_MASK}),
    "shift_reorder_rows": MappingProxyType({"kind": _WHY_ENUM}),
    "standard_shifts": MappingProxyType({"reorder_kind": _WHY_ENUM}),
    "probe_shift": MappingProxyType({"measure": _WHY_CALLABLE_NUMBER, "spec": _WHY_CARRIER,
                                     "cfg": _WHY_CARRIER, "fixture_factory": _WHY_CALLABLE_FIXTURE}),
    "guarded": MappingProxyType({"measure": _WHY_CALLABLE_NUMBER}),
    "missing_input_cases": MappingProxyType({"fx": _WHY_CARRIER}),
    "assert_no_silent_default": MappingProxyType({"measure": _WHY_CALLABLE_NUMBER}),
    "probe_missing_inputs": MappingProxyType({"measure": _WHY_CALLABLE_NUMBER, "cfg": _WHY_CARRIER}),
    "probe_precision": MappingProxyType({"cfg": _WHY_CARRIER, "measure": _WHY_CALLABLE_NUMBER}),
    "precision_sweep": MappingProxyType({"cfg": _WHY_CARRIER}),
})


# THE SECOND HALF OF THE BOUNDARY, and round 8's correction to it: `_plain_value` can only collapse an
# object that STORES a plain scalar, i.e. a `str`/`int`/`float` SUBCLASS. A DUCK-TYPED scalar -- an object
# of an unrelated class that merely answers the operators a gate is written in -- stores nothing to
# collapse, so `toy.schema._plain_value` returns it unchanged (its last line) and before this round it
# passed through the boundary untouched and reached the gate. The blind spot was written into the proof:
# the coverage probe's generator swept SUBCLASSES only, for the stated reason that "the property under
# test is that the object STORES the plain value" -- a property that cannot be stated about a duck.
# MEASURED on 3.12.4 and 3.13.5, through public parameters with no `object.__setattr__`, over the 30
# scalar-annotated parameters of this module: 17 were already refused by a downstream `isinstance` /
# `check_mask` / `deep_freeze`, and 13 were ACCEPTED -- the four routes round 7 reported closed
# (`shift_jitter.eps`, `shift_scale.factor`, `shift_reorder_rows.rel_tol`, `make_measure_fixture.rows`),
# plus `probe_precision.param`, `shift_scale.degree`, `shift_translate.c`,
# `make_order_sensitive_fixture.big`, `benchmark_outcome.metric` and `rows`'s three siblings
# `width` / `noise` / `magnitude_spread`.
# THE INVARIANT, stated so the rule is derived from it and not from those thirteen names: for every
# parameter this boundary binds, EITHER the value arrives at the callee collapsed to the scalar it stores,
# OR the call is refused inside the `(ValueError, TypeError, ArithmeticError)` family every probe
# declares. The re-opened routes were exactly the parameters that satisfied NEITHER disjunct -- the ones
# whose only guard is a closure cell or a control-flow gate, which is why the field boundary and the
# collapse half of this one both missed them.
# WHAT IS REFUSED, AND WHAT DELIBERATELY IS NOT. A parameter ANNOTATED `int`, `float` or `str` (read from
# the same signature this boundary already reads, so a new annotated parameter is covered without anyone
# remembering) must receive a value this module can read a stored scalar out of: `None`, an `Enum`
# member, or an instance of `str` / `int` / `float` (`bool` included, as an `int`). Anything else is
# refused BY TYPE, here, before any gate runs. A PLAIN SCALAR OF THE WRONG TYPE IS STILL THE CALLEE'S OWN
# BUSINESS -- `rows="4"` reaches `make_measure_fixture` and gets its own diagnostic -- because once
# subclasses are collapsed a plain scalar cannot lie to a gate, and pre-empting those messages would
# replace a dozen pinned diagnostics with one paraphrase, which is the reason arity errors are forwarded
# untouched too.
# OVER-REFUSAL, MEASURED RATHER THAN ASSUMED: what this newly refuses on those 30 parameters is any
# number that is not a `str`/`int`/`float` -- a `Decimal`, a `Fraction`, a third-party scalar. This kit is
# stdlib-only and nothing in it hands one to a public robustness callable; the two places that really do
# take a `Fraction` or a `Decimal` are untouched, `exact_masked_mse` because its parameters carry no
# annotation and `SeedSummary.from_values` because a classmethod is not behind this boundary at all.
# Pinned by `test_robustness.test_a_rational_where_a_float_is_annotated_is_refused_and_the_exact_helpers_are_not`.
_SCALAR_ANNOTATIONS = frozenset({"int", "float", "str"})


def _annotated_scalar_parameters(sig) -> MappingProxyType:
    """{parameter: annotation text} for every parameter of `sig` annotated as a bare scalar.

    `from __future__ import annotations` is in force, so an annotation here is the STRING a reader wrote.
    It is matched AS TEXT and never evaluated: `scripts/lint.sh` names `typing.get_type_hints` as a
    string-evaluating escape from its import blocklist, and this helper must not become a fresh instance
    of that class. `Optional[X]` is read as `X`, because `None` is accepted for every scalar parameter
    anyway and what a missing value means is the callee's own business. A real type object is accepted
    too, for a caller whose module does not use the future import.
    AN ANNOTATION SPELLED ANOTHER WAY (`float | None`, `Union[int, str]`, or none at all) YIELDS NOTHING
    HERE, so this rule FAILS OPEN -- which is exactly why it is not the only line of defence. The
    duck-typed half of `test_robustness._parameter_coverage_complaints` requires every parameter whose
    honest value is a scalar to be refused or declared, and cross-checks the set derived from annotations
    against the set derived from the canonical calls, so a parameter that this helper stops recognising
    fails a test rather than quietly losing its guard."""
    out = {}
    for name, par in sig.parameters.items():
        if par.kind in (par.VAR_POSITIONAL, par.VAR_KEYWORD):
            continue
        text = par.annotation.__name__ if isinstance(par.annotation, type) else par.annotation
        if not isinstance(text, str):
            continue
        text = text.strip()
        if text.startswith("Optional[") and text.endswith("]"):
            text = text[len("Optional["):-1].strip()
        if text in _SCALAR_ANNOTATIONS:
            out[name] = text
    return MappingProxyType(out)


def _stores_a_scalar(v: Any) -> bool:
    """True if there is a plain `str`/`int`/`float` here for `_plain_value` to have read, or nothing to read.

    `None` and an `Enum` member are accepted for the reasons `_plain_value` already states: a default a
    callee fills in itself, and a `str`-subclass enum whose collapse would destroy the `isinstance` checks
    that refuse a forged spelling. `bool` is an `int` and is accepted as one; the gates that must refuse a
    bool (`_check_seed`, `check_mask`, `SeedSummary.from_values`) do so by their own type checks."""
    return v is None or isinstance(v, (Enum, str, int, float))


def _plain_arguments(fn):
    """Wrap `fn` so that EVERY argument it is called with is the plain value the caller's object STORES,
    or the call is REFUSED because the object stored no scalar where the signature annotates one.

    `inspect.signature(fn)` is read ONCE, at wrap time; each call binds the actual arguments to it and
    passes every bound argument through `toy.schema._plain_value`. Nothing is skipped and no name is
    written down here, which is the whole point: a parameter ADDED to any public function of this module
    is normalised without anyone remembering to do it, exactly as a new dataclass FIELD is.

    `_plain_value`, not `_plain_parameter`: on a scalar the two agree (both preserve int-vs-float, both
    return a `bool` and an `Enum` member unchanged, both read what the object stores rather than
    consulting a `__float__` / `__int__` / `__str__` override), and `_plain_value` additionally walks
    CONTAINERS and mapping keys -- which a parameter needs and a field's normaliser already does, because
    `seeds`, `offsets`, `params`, `values`, `arms` and `details_always` are containers whose ELEMENTS and
    KEYS are what the guards downstream compare, hash and serialise.

    ORDER, and why binding happens before anything else: this is the "normalise, THEN compare" rule of
    `toy.benchmark._plain_number` applied one level out. A gate inside the function body -- `rows < 4`,
    `kind == "magnitude"`, `worst > tol` -- is an operator on the caller's object, so any call placed
    inside the body is placed after some gate, and round 6's lesson ("a call after a gate normalises
    nothing the gate used") has a sibling found by round 7's measurements: a call passed the WRONG object
    normalises nothing at all. The argument itself is what must arrive plain, and that is what
    `test_robustness.EveryPublicParameterIsNormalisedOrExplicitlyExempt` asserts -- at the callee, from a
    spy that records what it received.

    A call `fn` would refuse for arity or name reasons is forwarded UNTOUCHED, so the `TypeError` a caller
    sees is `fn`'s own and not `Signature.bind`'s paraphrase of it.
    ONE LIMIT INHERITED FROM `_plain_value`, stated rather than left to be discovered: it walks `list`,
    `tuple` and `Mapping`, so a container of ANOTHER type (a `range`, a generator, a custom `Sequence`)
    is returned unchanged and its ELEMENTS are not collapsed here. The places where such elements decide
    anything re-normalise them: `_check_seeds` (`int.__int__` on every seed), `Scorecard.__post_init__`
    (`_plain_text` on every non-claim), `precision_sweep` (each `param` crosses this boundary again, one
    call down) and `deep_freeze`, which refuses to freeze a container it does not recognise at all.
    THIS IS NOT A TAMPER BOUNDARY, for the reason `_normalise_fields` states: `object.__setattr__` and a
    caller-supplied CALLABLE's return value are both outside it (the latter is normalised where it is
    consumed), and so is `fn.__wrapped__`, which `functools.wraps` leaves reachable and which this
    module's tests use deliberately as the before/after control. Those are bypasses of the type's own
    protocol, not spellings a caller writes by accident. It is the guarantee that the value a gate
    INSPECTED is the value the caller's object stores -- OR that the call was refused because the object
    stored no such value, which is the second disjunct the block of comments above this function states
    and measures."""
    sig = inspect.signature(fn)
    scalars = _annotated_scalar_parameters(sig)     # read ONCE, with the signature: see the comments above

    @functools.wraps(fn)
    def at_parameter_boundary(*args, **kwargs):
        try:
            bound = sig.bind(*args, **kwargs)
        except TypeError:
            return fn(*args, **kwargs)      # let `fn` raise its own diagnostic, unchanged
        for name in list(bound.arguments):
            given = bound.arguments[name]
            plain = _plain_value(given)
            if name in scalars and not _stores_a_scalar(plain):
                raise TypeError(
                    f"{fn.__name__}() parameter {name!r} is annotated {scalars[name]} but was given a "
                    f"{_type_name(given)}, which stores no {scalars[name]} to normalise: a duck-typed "
                    "scalar is refused AT THE PARAMETER BOUNDARY rather than passed to a gate, a closure "
                    "cell or a card that it would then decide")
            if plain is not given:
                bound.arguments[name] = plain
        return fn(*bound.args, **bound.kwargs)

    at_parameter_boundary._AT_PARAMETER_BOUNDARY = True
    return at_parameter_boundary


def _install_parameter_boundary(namespace: dict) -> tuple:
    """Put every PUBLIC callable of this module behind `_plain_arguments`, and return their names.

    The list of callables is READ FROM THE MODULE NAMESPACE (a plain function, a public name, defined here
    -- so the helpers imported from `toy.benchmark` / `toy.schema`, which have their own boundaries and
    their own owners, are not touched). `inspect.isfunction`, not `isinstance(obj, types.FunctionType)`:
    `scripts/lint.sh` bans `from types import FunctionType` in `src/` by name, as a dynamic-code
    construction, and the two spellings test exactly the same thing. That is what makes a NEW PUBLIC
    FUNCTION covered by default rather than
    covered if someone remembers a decorator; `test_robustness` derives the same list the same way and
    fails closed when it moves. Classes are deliberately not touched: a dataclass's arguments ARE its
    fields, and `_normalise_fields` already covers them from `dataclasses.fields()`.

    THE DEFAULTS ARE RE-POINTED, which is not housekeeping: `probe_shift`'s `fixture_factory` default and
    `probe_precision`'s `measure` default were evaluated at `def` time, i.e. BEFORE this installer ran, so
    they referred to the un-wrapped `make_measure_fixture` / `mse_naive`. Left alone, the default path of
    a public probe would be the one path not behind the boundary -- the "it only holds for the default
    parameter" smell this kit's own verification rules name as a finding. The callee is re-pointed, not
    the signature object captured in the wrapper, and no default is APPLIED during binding: an argument a
    caller did not pass is not in `bound.arguments` at all, and `fn` fills it itself."""
    public = {name: obj for name, obj in list(namespace.items())
              if inspect.isfunction(obj) and not name.startswith("_")
              and getattr(obj, "__module__", None) == __name__}
    wrapped = {name: _plain_arguments(obj) for name, obj in public.items()}
    namespace.update(wrapped)
    behind = {id(obj): wrapped[name] for name, obj in public.items()}
    for obj in public.values():
        if obj.__defaults__:
            obj.__defaults__ = tuple(behind.get(id(d), d) for d in obj.__defaults__)
        if obj.__kwdefaults__:
            obj.__kwdefaults__ = {k: behind.get(id(d), d) for k, d in obj.__kwdefaults__.items()}
    unknown = sorted(f"{f}.{p}" for f, ps in _PARAMETER_NO_SCALAR.items() for p in ps
                     if f not in public or p not in inspect.signature(public[f]).parameters)
    if unknown:    # fail at IMPORT, not at review time: a stale entry is a stale reason
        raise ValueError(f"_PARAMETER_NO_SCALAR names parameters that do not exist: {unknown}")
    return tuple(sorted(wrapped))


_PARAMETER_BOUNDARY = _install_parameter_boundary(globals())
