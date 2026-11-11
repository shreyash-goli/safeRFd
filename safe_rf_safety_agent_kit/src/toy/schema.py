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
"""
from __future__ import annotations

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

    def __post_init__(self) -> None:
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

    def __post_init__(self) -> None:
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

    def __post_init__(self) -> None:
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
