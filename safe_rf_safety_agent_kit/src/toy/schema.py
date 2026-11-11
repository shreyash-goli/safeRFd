"""Strict typed schema for TOY experiment records (SR-04).

Standard library only. Everything recorded through this module is a toy,
synthetic, non-biological result. Nothing here asserts any safety property.

Caveats stated plainly:
- `RunProvenance.toy_only` is a producer-asserted flag, not a verified property
  of the data. The constructor refuses False, but like any Python dataclass it
  can be bypassed (e.g. via `object.__setattr__`).
- Free-text fields (`name`, `notes`, `code_version`, `run_id`) are unconstrained
  and can carry claim-like strings; downstream consumers (SR-14, renderers) must
  never treat them as evidence.
- Rule: an `ExperimentRecord` (a run record) can never be `SOURCE_OBSERVED`.
  That class belongs to audit/claim records (SR-14), not run records, and is
  rejected at construction. It stays in `EvidenceClass` for those consumers.
- SUBCLASS NORMALISATION IS APPLIED AT THE TYPE BOUNDARY, not at a list of
  remembered sites. `_normalise_fields(self)` is the first statement of every
  `__post_init__` here and walks `dataclasses.fields()`, and each `from_dict`
  normalises the whole incoming document with `_plain_value(data)` -- so a new
  field, and a gate a future reader adds to a `from_dict`, are COVERED BY
  DEFAULT. The reason this is a boundary and not a fifth helper: five correct
  helpers (`toy.benchmark._plain_number`, `_plain_parameter`,
  `toy.robustness._plain_text`, `_plain_measure`, `_plain_summary_fields`) were
  applied at twelve hand-chosen call sites, and five consecutive review rounds
  each found the sites nobody remembered -- `input_hashes`, the version and
  label gates, metric NAMES. That procedure cannot terminate, because its audit
  is a person hunting for omissions. Exemptions are declared per class in
  `_NORMALISE_EXEMPT` with a reason, and
  `test_schema.EveryDataclassFieldIsNormalisedOrExplicitlyExempt` fails closed
  on a new field and on a new dataclass. This is NOT a tamper boundary:
  `object.__setattr__` still replaces a field afterwards. It is the guarantee
  that the value a validator inspected is the value the object stores.
- What the boundary does NOT reach: a function PARAMETER and a closure variable
  are not fields (see `toy.robustness.arm_difference` and
  `shift_reorder_rows`), and `Enum` members are deliberately skipped because
  `EvidenceClass` is a `str` subclass by construction.
"""
from __future__ import annotations

import dataclasses
import hashlib
import json
import math
import random
import re
import sys
from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Any, Mapping, Optional

SCHEMA_VERSION = "2"
_TS_RE = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", re.ASCII)
_SHA256_RE = re.compile(r"[0-9a-f]{64}", re.ASCII)
TOY_LABEL = "TOY RESULT (synthetic, non-biological; not a safety finding)"
# SR-12 F15 wording, applied here after the claim_ledger owner drew the distinction: "not a safety
# CLAIM" is an assertion about the labelled content, which nothing in this kit ever classifies, and
# this label is prepended to free text a user supplies (SR-12 Q6: a crop then reads as the kit
# vouching for the user's "model is safe"). "not a safety FINDING" describes THIS RECORD and is
# true by construction, whatever the notes say. Changing it changes the serialized contract, so
# SCHEMA_VERSION is bumped with it.
MAX_SEED = 2**64 - 1


class EvidenceClass(str, Enum):
    """Single source of truth for evidence labels."""
    SOURCE_OBSERVED = "SOURCE_OBSERVED"
    HYPOTHESIS = "HYPOTHESIS"
    TOY_RESULT = "TOY_RESULT"
    NOT_VALIDATED = "NOT_VALIDATED"
    UNKNOWN = "UNKNOWN"

    @classmethod
    def parse(cls, value: Any) -> "EvidenceClass":
        if isinstance(value, cls):
            return value
        if not isinstance(value, str):
            raise ValueError(f"evidence_class must be a string, got {type(value).__name__}")
        try:
            return cls(value)
        except ValueError:
            raise ValueError(f"unknown evidence_class {value!r}; allowed: {[m.value for m in cls]}") from None


def _nonblank(name: str, value: Any) -> None:
    if not isinstance(value, str):
        raise ValueError(f"{name} must be a string, got {type(value).__name__}")
    if not value.strip():
        raise ValueError(f"{name} must not be empty or blank")


def _check_keys(what: str, data: Any, expected: set[str]) -> None:
    """Exact key-set check. NORMALISE THE KEYS BEFORE COMPARING THEM.

    `set(data) - expected` is `__hash__` plus `__eq__` on the caller's keys, and a `str` SUBCLASS whose
    `__hash__` returns `hash("run_id")` and whose `__eq__` returns True is treated as that key: the
    unknown-key check then sees nothing unknown and nothing missing. MEASURED, on a hand-built dict
    (not reachable through `from_json`, whose keys come out of the JSON decoder as plain `str`):
      * at the top level the liar is HARMLESS and that is stated rather than assumed --
        `ExperimentRecord.from_dict` reads its fields by explicit `data["name"]` lookups, which the same
        lying `__eq__` resolves to the same values, so the record built is BYTE-IDENTICAL to the honest
        one. Nothing is gained, because nothing was renamed as far as any reader is concerned.
      * nested, `RunProvenance.from_dict` passes `cls(**data)`, and a mislabelled key then reached the
        constructor as a keyword and raised `TypeError: got multiple values for argument 'b...'` --
        outside this module's stated `ValueError` contract, the same class of escape as the
        `OverflowError` that `toy.benchmark._check_margin` had to close.
    `str.__str__` reads the characters the object holds, so the key set compared is the key set the
    constructor will be handed, and a mislabelled key gets the diagnostic it should: "unknown keys
    [...]" plus "missing keys [...]"."""
    if not isinstance(data, dict):
        raise ValueError(f"{what} must be a JSON object, got {type(data).__name__}")
    keys = {str.__str__(k) if isinstance(k, str) and type(k) is not str else k for k in data}
    unknown = keys - expected
    missing = expected - keys
    if unknown:
        raise ValueError(f"{what}: unknown keys {sorted(unknown)}")
    if missing:
        raise ValueError(f"{what}: missing keys {sorted(missing)}")


# ------------------------------------------------- normalisation AT THE TYPE BOUNDARY
def _plain_value(x: Any) -> Any:
    """Collapse `x`, RECURSIVELY, to the plain `str` / `int` / `float` / `dict` / `list` / `tuple` values
    it STORES. Anything that is not one of those (an `Enum` member, a `bool`, a nested dataclass, a
    callable, `None`, an arbitrary object) is returned unchanged.

    THIS IS THE SINGLE NORMALISER THE WHOLE KIT'S GUARDS WERE MISSING, and the reason it is written as one
    recursive function over a value rather than as another named helper to call by hand: every previous
    round of this project fixed the sites it remembered. `toy.benchmark._plain_number`,
    `_plain_parameter`, `toy.robustness._plain_text`, `_plain_measure` and `_plain_summary_fields` are all
    correct, and between them they were applied at twelve hand-chosen call sites -- so every round the
    attestation found the thirteenth. A hand-maintained list of places to be careful cannot terminate,
    because its audit is a person hunting for omissions. `_normalise_fields` below drives this function
    from `dataclasses.fields()`, so a field is covered BY DEFAULT and an exemption has to be written down
    with a reason.
    WHAT A SUBCLASS BUYS, which is why containers are walked and not just scalars: `str` / `int` / `float`
    satisfy every `isinstance` check and need not lie to `math.isfinite` or to a regex, while `__eq__`,
    `__ne__`, `__hash__`, `__lt__`, `__gt__`, `__float__`, `__int__`, `__str__`, `__mul__` and `__format__`
    are all overridable -- and those operators are what every guard in this kit is WRITTEN IN. A liar
    nested one level down (a mapping VALUE, a tuple element, a mapping KEY) is reached by no scalar check
    at the field itself: `RunProvenance.input_hashes` was format-checked element by element and then
    stored as the caller's object, and `toy.benchmark.verdict_from_records` read one of those values with
    `bound != want_hash`.
    `str.__str__` / `float.__float__` / `int.__int__` are used rather than `str(x)` / `float(x)` / `int(x)`
    DELIBERATELY, for the reason `toy.benchmark._plain_number` states: they read what the object actually
    stores, so a `__str__` / `__float__` / `__int__` override is not consulted at all, and the value
    checked cannot differ from the value stored.
    THREE DECISIONS STATED RATHER THAN LEFT TO BE INFERRED:
    * `Enum` members are returned unchanged, and that is a TYPE rule, not a per-field exemption.
      `EvidenceClass` / `ProbeStatus` / `ShiftKind` are `str` subclasses by construction, so collapsing
      them would destroy the very `isinstance(x, EvidenceClass)` checks this module relies on. A forged
      `str` subclass offered where an enum is required is refused by that `isinstance`, so nothing is
      laundered by the skip.
    * `bool` is returned unchanged (the rule of `toy.benchmark._plain_parameter`): `bool` cannot be
      subclassed, and silently turning `True` into `1` is the D5 defect.
    * A nested dataclass is returned unchanged because it normalises ITS OWN fields in ITS OWN
      `__post_init__`. The boundary composes; it does not reach across one.
    MAPPING KEYS ARE NORMALISED AND COLLISIONS ARE REFUSED, loudly, inside the documented `ValueError`
    family: two keys that are distinct to the caller but equal once plain would otherwise SILENTLY become
    one entry, which on `input_hashes` means a record that carries one provenance anchor where its
    producer wrote two, and on `ExperimentRecord.metrics` a metric that is absent from the canonical JSON
    and therefore from `content_hash()`."""
    if x is None or isinstance(x, (Enum, bool)):
        return x
    if isinstance(x, str):
        return x if type(x) is str else str.__str__(x)
    if isinstance(x, float):
        return x if type(x) is float else float.__float__(x)
    if isinstance(x, int):
        return x if type(x) is int else int.__int__(x)
    if isinstance(x, Mapping):
        out: dict[Any, Any] = {}
        changed = type(x) is not dict
        for k in x:
            pk, pv = _plain_value(k), _plain_value(x[k])
            if pk in out:
                raise ValueError(f"two keys collapse to {pk!r} once normalised: a mapping cannot "
                                 "silently lose an entry to an overridden __hash__/__eq__")
            changed = changed or pk is not k or pv is not x[k]
            out[pk] = pv
        return out if changed else x
    if isinstance(x, (list, tuple)):
        items = [_plain_value(v) for v in x]
        # IDENTITY IS PRESERVED when nothing needed collapsing, for two reasons worth stating: an honest
        # record must be byte-identical AND allocation-identical (a rebuilt container is a behaviour
        # change a reader cannot see), and `MeasureFixture` holds matrices that this walks per fixture.
        if type(x) in (list, tuple) and len(items) == len(x) and all(a is b for a, b in zip(items, x)):
            return x
        return (list if isinstance(x, list) else tuple)(items)
    return x


def _normalise_fields(obj: Any) -> None:
    """Normalise EVERY field of a frozen dataclass instance in place, driven by `dataclasses.fields()`.

    Call this as the FIRST statement of `__post_init__`, before any gate: normalise, THEN compare (the
    ordering rule of `toy.benchmark._plain_number`). Because the field list is read from the class and not
    written here, ADDING A FIELD DEFAULTS TO COVERED -- which is the whole point, and the property no
    previous round's fix had.
    A class exempts a field by declaring, unannotated so that it is a class attribute and not a field
    itself, `_NORMALISE_EXEMPT = MappingProxyType({"<field>": "<why>"})`. The reason is not decoration:
    `test_schema.EveryDataclassFieldIsNormalisedOrExplicitlyExempt` and its `test_robustness` twin
    enumerate `dataclasses.fields()` of every dataclass in each module and require each field to be
    either demonstrably stored plain or named in that mapping with a nonblank reason, so a new field, and
    a new dataclass, FAIL CLOSED rather than being noticed by a reviewer.
    This is not a tamper boundary: `object.__setattr__` still replaces any field afterwards, which is why
    `toy.benchmark._metric_read` exists. It is the guarantee that the value a validator INSPECTED is the
    value the object STORES."""
    exempt = getattr(type(obj), "_NORMALISE_EXEMPT", {})
    for f in dataclasses.fields(obj):
        if f.name in exempt:
            continue
        v = getattr(obj, f.name)
        p = _plain_value(v)
        if p is not v:
            object.__setattr__(obj, f.name, p)


# ---------------------------------------------------------------- seeding
def make_rng(seed: int) -> random.Random:
    """Return an independent generator; never touches the global `random` state.

    Seeded with the PLAIN int `_check_seed` returns, not with the caller's object: see `_check_seed`."""
    return random.Random(_check_seed(seed))


def derive_seed(seed: int, label: str) -> int:
    """Canonical sub-run seed: first 8 bytes of sha256("<seed>:<label>"). No time/PID entropy.

    The seed is FORMATTED into the hashed string, and `__format__` / `__str__` are overridable, so the
    plain int `_check_seed` returns is what gets hashed. MEASURED before that: an `int` subclass whose
    `__str__` returned "7" made `derive_seed(StrSeed(9), "a") == derive_seed(7, "a")`, i.e. two seeds
    that a duplicate check sees as DISTINCT derived the same sub-run seed and therefore the same
    fixture -- "n distinct seeds" with one example behind it (`toy.robustness._check_seeds`'s guarantee).
    """
    seed = _check_seed(seed)
    _nonblank("label", label)
    digest = hashlib.sha256(f"{seed}:{label}".encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big")


def _check_seed(seed: Any) -> int:
    """Validate a seed and RETURN IT AS A PLAIN `int`, so the seed checked is the seed used.

    NORMALISE BEFORE COMPARING, and return what was compared (the pattern of
    `toy.benchmark._plain_number`, which is where it was first measured): `seed < 0` and
    `seed > MAX_SEED` are `type(seed).__lt__` / `__gt__`, so an `int` SUBCLASS answering False to both
    passed this gate holding -5 and 2**200 -- through the public `make_rng` / `derive_seed` /
    `RunProvenance`, with no `object.__setattr__`. `int.__int__` reads the value the object actually
    STORES, which is the value every caller then uses. Callers must use the RETURN VALUE; ignoring it
    (which every caller used to do) leaves the overrides in play one line later."""
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise ValueError(f"seed must be an int, got {type(seed).__name__}")
    seed = int.__int__(seed)
    if seed < 0:
        raise ValueError("seed must be nonnegative")
    if seed > MAX_SEED:
        raise ValueError("seed must be <= 2**64 - 1")
    return seed


def current_python_version() -> str:
    return ".".join(str(p) for p in sys.version_info[:3])


# ------------------------------------------------------------- provenance
@dataclass(frozen=True)
class RunProvenance:
    run_id: str
    timestamp_utc: str  # strict form YYYY-MM-DDTHH:MM:SSZ
    seed: int
    code_version: str
    python_version: str
    toy_only: bool
    input_hashes: Mapping[str, str]

    _NORMALISE_EXEMPT = MappingProxyType({})   # nothing here may keep a caller's subclass

    def __post_init__(self) -> None:
        # NORMALISE AT THE BOUNDARY, BEFORE ANY GATE. `input_hashes` is the field this was measured on:
        # `_SHA256_RE.fullmatch(v)` reads the real characters of a 64-lowercase-hex `str` SUBCLASS and
        # passed it, and the un-normalised object was then STORED -- so
        # `toy.benchmark.verdict_from_records`' config binding, which is `bound != want_hash` over
        # `input_hashes["config"]`, was decided by the value under audit. MEASURED, through the public
        # constructor with no `object.__setattr__`, on a study run at `width_tol=0.10` recomputed with the
        # module default 0.25: JOINT_INCONCLUSIVE ("cfg does not match the stored study configuration")
        # became JOINT_SUPPORTED with h1/h2/h3 all SUPPORTED, `reasons = ()` and `config_hash` reporting
        # a hash that is not the study's -- and the sibling guards could not fire, because `stored` is a
        # `set` built from the same object, so "records disagree" and `None in stored` were defeated by
        # it too. The real hash need not be known and no matching `cfg` is needed. Second consequence,
        # same root: two `input_hashes` entries could collapse to one on an overridden `__hash__`, and
        # `toy.robustness` calls that field "the provenance anchor a reader would check the seeds
        # against".
        _normalise_fields(self)
        _nonblank("run_id", self.run_id)
        _nonblank("timestamp_utc", self.timestamp_utc)
        if not _TS_RE.fullmatch(self.timestamp_utc):
            raise ValueError(f"timestamp_utc must match YYYY-MM-DDTHH:MM:SSZ, got {self.timestamp_utc!r}")
        from datetime import datetime
        try:
            datetime.strptime(self.timestamp_utc, "%Y-%m-%dT%H:%M:%SZ")
        except ValueError:
            raise ValueError(f"timestamp_utc is not a real date/time: {self.timestamp_utc!r}") from None
        object.__setattr__(self, "seed", _check_seed(self.seed))   # store what was checked
        _nonblank("code_version", self.code_version)
        _nonblank("python_version", self.python_version)
        if self.toy_only is not True:
            raise ValueError("toy_only must be True; this kit cannot record non-toy runs")
        if not isinstance(self.input_hashes, Mapping):
            raise ValueError("input_hashes must be a mapping")
        for k, v in self.input_hashes.items():
            _nonblank("input_hashes key", k)
            if not isinstance(v, str) or not _SHA256_RE.fullmatch(v):
                raise ValueError(f"input_hashes[{k!r}] must be a lowercase 64-char sha256 hex string")
        object.__setattr__(self, "input_hashes", MappingProxyType(dict(sorted(self.input_hashes.items()))))

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id, "timestamp_utc": self.timestamp_utc, "seed": self.seed,
            "code_version": self.code_version, "python_version": self.python_version,
            "toy_only": self.toy_only, "input_hashes": dict(self.input_hashes),
        }

    @classmethod
    def from_dict(cls, data: Any) -> "RunProvenance":
        data = _plain_value(data)   # the deserialisation boundary; see `ExperimentRecord.from_dict`
        _check_keys("RunProvenance", data, {
            "run_id", "timestamp_utc", "seed", "code_version", "python_version", "toy_only", "input_hashes"})
        return cls(**data)


# ---------------------------------------------------------------- metrics
@dataclass(frozen=True)
class MetricValue:
    """A metric that is either measured (finite float) or explicitly UNMEASURED.

    Absence is a distinct state (value=None plus a reason), never 0.0: a missing
    measurement must not be readable as a genuine zero. Use `MetricValue.measured`
    / `MetricValue.unmeasured`. Only `float` values are accepted (no int/bool coercion).

    A `float` SUBCLASS is accepted (it IS a float) but is NOT stored: `__post_init__` stores the plain
    double the object holds, so no override on the instance can make the value stored, serialized or
    compared differ from the value validated. What this does NOT do is make a `MetricValue` tamper-proof:
    `object.__setattr__(mv, "value", <anything>)` still replaces the field after construction, which is
    why `toy.benchmark._metric_read` exists and why no consumer may read `.value` for itself.
    """
    value: Optional[float]
    reason: Optional[str] = None

    _NORMALISE_EXEMPT = MappingProxyType({})

    def __post_init__(self) -> None:
        # Normalise at the boundary (see `_normalise_fields`). This makes the `float.__float__` below a
        # no-op for a subclass, and it is kept anyway: it is the line the -0.0 normalisation needs, it is
        # pinned by `test_schema.AMetricStoresTheNumberItChecked`, and a validator that re-reads what it
        # is about to store is the one place in this module where redundancy is the point.
        _normalise_fields(self)
        if self.value is None:
            _nonblank("reason", self.reason)  # also rejects None: unmeasured requires a reason
        else:
            if isinstance(self.value, bool) or not isinstance(self.value, float):
                raise ValueError(f"metric value must be a float, got {type(self.value).__name__}")
            if not math.isfinite(self.value):
                raise ValueError("metric value must be finite (no NaN/inf)")
            # STORE WHAT WAS CHECKED, and the reason this is the root of the whole checked-reader
            # architecture rather than a tidy-up. `isinstance(self.value, float)` admits a float
            # SUBCLASS and `math.isfinite` reads the double the object STORES, which the subclass need
            # not lie about -- but `self.value == 0.0` was `type(self.value).__eq__`, an OVERRIDABLE
            # operation deciding whether to overwrite the stored number. MEASURED, through the public
            # API with no `object.__setattr__` anywhere:
            #     class EqZero(float):
            #         def __eq__(self, o):  return True
            #         def __hash__(self):   return 0
            #     MetricValue.measured(EqZero(7.0)).value   ->  0.0
            # i.e. the schema's own validator SUBSTITUTED the stored measurement. End to end through
            # SeedScores -> analyze_scores -> to_experiment_records -> verdict_from_records, an honest
            # L of 7.00..7.29 against delta_R=0.05 turned H2 UNSUPPORTED -> SUPPORTED and
            # JOINT_UNSUPPORTED -> JOINT_SUPPORTED with `reasons = ()` and an unchanged `config_hash`
            # -- the signature of a clean recompute -- and in the other direction a SUPPORTED S became
            # UNSUPPORTED. `float.__float__` reads that same stored double (a `__float__` override is
            # not consulted second; it is not consulted at all), so the number checked above, the
            # number stored here, the number serialized by `to_dict` and the number every consumer
            # compares are one number. The -0.0 normalisation that this line is FOR is then a
            # comparison between two plain floats. Same inspect-before-normalise pattern, and the same
            # fix, as `toy.benchmark._plain_number` and `toy.robustness._plain_summary_fields`; this is
            # the point UPSTREAM of both of them, so every module that stores a metric inherits it.
            v = float.__float__(self.value)
            object.__setattr__(self, "value", 0.0 if v == 0.0 else v)
            if self.reason is not None:
                raise ValueError("a measured metric must not carry an unmeasured reason")

    @classmethod
    def measured(cls, value: float) -> "MetricValue":
        return cls(value=value)

    @classmethod
    def unmeasured(cls, reason: str) -> "MetricValue":
        return cls(value=None, reason=reason)

    @property
    def is_measured(self) -> bool:
        return self.value is not None

    def render(self) -> str:
        """Human text: unmeasured renders as UNKNOWN, never as 0."""
        return repr(self.value) if self.value is not None else "UNKNOWN"

    def to_dict(self) -> dict[str, Any]:
        return {"value": self.value, "reason": self.reason}

    @classmethod
    def from_dict(cls, data: Any) -> "MetricValue":
        data = _plain_value(data)   # the deserialisation boundary; see `ExperimentRecord.from_dict`
        _check_keys("MetricValue", data, {"value", "reason"})
        return cls(**data)


# ------------------------------------------------------------- experiment
@dataclass(frozen=True)
class ExperimentRecord:
    name: str
    provenance: RunProvenance
    metrics: Mapping[str, MetricValue]
    evidence_class: EvidenceClass
    notes: Optional[str] = None

    _NORMALISE_EXEMPT = MappingProxyType({})

    def __post_init__(self) -> None:
        # Normalise at the boundary, before every gate below (see `_normalise_fields`). `metrics` is
        # walked as a mapping, which is what closes the metric-NAME route: a name was `_nonblank`-checked
        # and never normalised, so a `str` subclass could be stored as a key and a second key could
        # collapse into it -- a metric a recompute reads being absent from the canonical JSON and hence
        # from `content_hash()`.
        _normalise_fields(self)
        _nonblank("name", self.name)
        if not isinstance(self.provenance, RunProvenance):
            raise ValueError("provenance must be a RunProvenance")
        if not isinstance(self.metrics, Mapping):
            raise ValueError("metrics must be a mapping")
        for k, v in self.metrics.items():
            _nonblank("metric name", k)
            if not isinstance(v, MetricValue):
                raise ValueError(f"metrics[{k!r}] must be a MetricValue, got {type(v).__name__}")
        if not isinstance(self.evidence_class, EvidenceClass):
            raise ValueError("evidence_class must be an EvidenceClass (use EvidenceClass.parse for strings)")
        if self.evidence_class is EvidenceClass.SOURCE_OBSERVED:
            raise ValueError("SOURCE_OBSERVED belongs to audit/claim records, not run records")
        if self.notes is not None and not isinstance(self.notes, str):
            raise ValueError("notes must be a string or None")
        object.__setattr__(self, "metrics", MappingProxyType(dict(sorted(self.metrics.items()))))

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "label": TOY_LABEL,
            "name": self.name,
            "provenance": self.provenance.to_dict(),
            "metrics": {k: v.to_dict() for k, v in self.metrics.items()},
            "evidence_class": self.evidence_class.value,
            "notes": self.notes,
        }

    def to_json(self) -> str:
        return _canonical(self.to_dict())

    def content_hash(self) -> str:
        return hashlib.sha256(self.to_json().encode("utf-8")).hexdigest()

    @classmethod
    def from_dict(cls, data: Any) -> "ExperimentRecord":
        # NORMALISE THE WHOLE INCOMING DOCUMENT, not just its keys. `_check_keys` normalises the KEYS and
        # its docstring calls the top-level liar "HARMLESS"; that claim is about keys and does NOT extend
        # to the two VALUE gates below, which were `!=` on the caller's object. MEASURED, through
        # `from_dict` with a hand-built dict and no `object.__setattr__`: a `str` SUBCLASS whose `__eq__`
        # returns True and `__ne__` False laundered a VERSION-1 record into a valid version-2 record
        # (re-serialized with `schema_version="2"` and the canonical `TOY_LABEL`), and a record whose
        # stored label read "VERIFIED SAFETY FINDING" was accepted and silently RELABELLED as a toy
        # result. `from_json` was immune only because the JSON decoder emits plain `str`, so both
        # label-tampering tests went through the one route that could not show it. Normalising here is the
        # deserialisation half of the same boundary `__post_init__` applies to fields: one call that
        # covers these two gates and every gate a future reader adds to this method.
        data = _plain_value(data)
        _check_keys("ExperimentRecord", data, {
            "schema_version", "label", "name", "provenance", "metrics", "evidence_class", "notes"})
        # Version BEFORE label, deliberately. TOY_LABEL's text changed when SCHEMA_VERSION went
        # 1 -> 2, so a version-1 record fails both checks; whichever runs first decides the
        # diagnostic. "unsupported schema_version '1'" tells the reader what is actually wrong;
        # "label must equal ..." sends them hunting for a typo in a record that was correct when
        # it was written.
        if data["schema_version"] != SCHEMA_VERSION:
            raise ValueError(f"unsupported schema_version {data['schema_version']!r}")
        if data["label"] != TOY_LABEL:
            raise ValueError(f"label must equal {TOY_LABEL!r}, got {data['label']!r}")
        if not isinstance(data["metrics"], dict):
            raise ValueError("metrics must be a JSON object")
        return cls(
            name=data["name"],
            provenance=RunProvenance.from_dict(data["provenance"]),
            metrics={k: MetricValue.from_dict(v) for k, v in data["metrics"].items()},
            evidence_class=EvidenceClass.parse(data["evidence_class"]),
            notes=data["notes"],
        )

    @classmethod
    def from_json(cls, text: str) -> "ExperimentRecord":
        if not isinstance(text, str):
            raise ValueError("from_json expects a str")
        return cls.from_dict(_strict_loads(text))


# --------------------------------------------------------------- json util
def canonical_json(obj: Any) -> str:
    """Canonical JSON: sorted keys, compact separators, ASCII-escaped, NaN/inf rejected.

    Public because other modules in this kit (e.g. `toy.checkpoint`) must produce byte-identical
    serialisations to hash over. It was originally private (`_canonical`); depending on a private
    name across modules is fragile, so it is now part of the supported surface and any change to
    its output is a breaking change for every stored `content_hash` and checkpoint digest.
    """
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)


# Backwards-compatible alias for the former private name. Do not use in new code.
_canonical = canonical_json


def _strict_loads(text: str) -> Any:
    def no_dupes(pairs):
        d = {}
        for k, v in pairs:
            if k in d:
                raise ValueError(f"duplicate JSON key {k!r}")
            d[k] = v
        return d

    def bad_const(name):
        raise ValueError(f"non-finite JSON constant {name} not allowed")

    try:
        return json.loads(text, object_pairs_hook=no_dupes, parse_constant=bad_const)
    except json.JSONDecodeError as e:
        raise ValueError(f"invalid JSON: {e}") from None
    except RecursionError:
        raise ValueError("invalid JSON: nesting too deep") from None
