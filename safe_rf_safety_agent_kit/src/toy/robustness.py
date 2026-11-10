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
* `Scorecard.__post_init__` requires exactly one of {summary, insufficient}, checks the status, labels,
  counts and seed digest agree, and RE-VALIDATES the nested summary / insufficient object (exact type,
  recomputed statistics), so `dataclasses.replace` cannot launder a summary that was tampered with
  after construction. A card carrying a summary of fewer than `SEED_FLOOR` values, or a subclass of
  `SeedSummary`, cannot be built through the public constructors, `dataclasses.replace`, or the builders.
Honest limits: Python cannot make this impossible. `object.__setattr__`, `object.__new__`, and
SUBCLASSING `SeedSummary` / `InsufficientEvidence` with a `__post_init__` that skips the checks all build
unvalidated nested objects (a `Scorecard` still refuses such an object, via the exact-type check, but a
bare unvalidated subclass instance exists). `gc.get_referents` reaches the writable dict behind a
`MappingProxyType` (see `Scorecard`, limit (2)). Edits to module constants also defeat the floor. The
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
import hashlib
import math
import sys
from enum import Enum
from fractions import Fraction
from types import MappingProxyType
from typing import Any, Callable, Mapping, Optional, Sequence

from toy import stability
from toy.benchmark import quantile, sample_sd, seed_list_digest
from toy.benchmark import mean as _mean
from toy.schema import (SCHEMA_VERSION, TOY_LABEL, EvidenceClass, ExperimentRecord, MetricValue, RunProvenance,
                        canonical_json, current_python_version, derive_seed, make_rng)

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

    def __post_init__(self) -> None:
        if isinstance(self.min_seeds, bool) or not isinstance(self.min_seeds, int):
            raise ValueError("min_seeds must be an int")
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

    def __post_init__(self) -> None:
        if self.n_measured >= self.n_required:
            raise ValueError("InsufficientEvidence requires n_measured < n_required")
        if not isinstance(self.reason, str) or not self.reason.strip():
            raise ValueError("reason must be a nonblank string")

    def to_dict(self) -> dict:
        return {"status": ProbeStatus.INSUFFICIENT_EVIDENCE.value, "n_measured": self.n_measured,
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

    def __post_init__(self) -> None:
        vals = tuple(self.values)
        if len(vals) < SEED_FLOOR:
            raise ValueError(f"a summary needs >= {SEED_FLOOR} measured seeds, got {len(vals)} "
                             "(single-example claims are structurally refused)")
        for v in vals:
            if isinstance(v, bool) or not isinstance(v, float) or not math.isfinite(v):
                raise ValueError("summary values must be finite floats")
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
                    f"values must be real numbers, got {t.__name__}: bool and str are refused on purpose "
                    "(a boolean outcome and a number parsed out of text are not measurements)") from None
            try:
                out.append(float(v))
            except OverflowError:   # e.g. 10**400: keep the documented ValueError family
                raise ValueError("a value is too large to represent as a finite float") from None
            except (TypeError, ValueError) as e:
                raise ValueError(f"values must be real numbers: {e}") from None
        vals = tuple(out)
        if len(vals) < SEED_FLOOR:
            raise ValueError(f"a summary needs >= {SEED_FLOOR} measured seeds, got {len(vals)}")
        return cls(*_stats(vals), values=vals)

    def to_dict(self) -> dict:
        return {"n": self.n, "mean": self.mean, "sd": self.sd, "q1": self.q1, "q3": self.q3, "iqr": self.iqr,
                "min": self.minimum, "max": self.maximum, "values": list(self.values)}


def _stats(vals: tuple) -> tuple:
    s = sorted(vals)
    q1, q3 = quantile(s, 0.25), quantile(s, 0.75)
    return (len(vals), _mean(vals), sample_sd(vals), q1, q3, q3 - q1, s[0], s[-1])


def summarize_seeds(per_seed: Sequence[MetricValue], min_seeds: int = DEFAULT_MIN_SEEDS):
    """SeedSummary if >= min_seeds measured values, else InsufficientEvidence. Never a bare scalar."""
    ProbeConfig(min_seeds)  # enforces the floor
    per_seed = tuple(per_seed)
    if not all(isinstance(m, MetricValue) for m in per_seed):
        raise ValueError("per_seed must be MetricValues (absence must be explicit, never a number)")
    measured = [m.value for m in per_seed if m.is_measured]
    if len(measured) < min_seeds:
        return InsufficientEvidence(
            len(measured), min_seeds,
            f"{len(measured)} measured of {len(per_seed)} seeds; minimum is {min_seeds}")
    return SeedSummary.from_values(measured)


def require_summary(result) -> SeedSummary:
    """Loud accessor: raises unless `result` is a real SeedSummary."""
    if isinstance(result, SeedSummary):
        return result
    raise InsufficientEvidenceError(f"no scalar summary exists: {result!r}")


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
    seeds = tuple(seeds)
    for s in seeds:
        make_rng(s)  # public validation: nonnegative int <= 2**64-1, bool rejected
    if len(set(seeds)) != len(seeds):
        raise ValueError("duplicate seeds are rejected: repeating one example does not add evidence")
    return seeds


def _to_metric(outcome: Callable[[int], float], seed: int) -> MetricValue:
    try:
        v = outcome(seed)
    except (ValueError, TypeError, ArithmeticError) as e:
        return MetricValue.unmeasured(f"{type(e).__name__}: {e}")
    if isinstance(v, bool) or not isinstance(v, float):
        return MetricValue.unmeasured(f"outcome must be a float, got {type(v).__name__}")
    if not math.isfinite(v):
        return MetricValue.unmeasured("outcome is non-finite")
    return MetricValue.measured(v)


# ============================================================= immutable freezing
def deep_freeze(x: Any) -> Any:
    """Defensive deep copy into read-only containers: Mapping -> MappingProxyType (str keys, sorted),
    list/tuple -> tuple, scalars str/int/float(finite)/bool/None as-is, Enum -> value."""
    if isinstance(x, Enum):
        return x.value
    if x is None or isinstance(x, (bool, int, str)):
        return x
    if isinstance(x, float):
        if not math.isfinite(x):
            raise ValueError("non-finite float cannot be stored in a scorecard")
        return x
    if isinstance(x, Mapping):
        for k in x:
            if not isinstance(k, str):
                raise ValueError(f"scorecard mapping keys must be str, got {type(k).__name__}")
        return MappingProxyType({k: deep_freeze(x[k]) for k in sorted(x)})
    if isinstance(x, (list, tuple)):
        return tuple(deep_freeze(v) for v in x)
    raise ValueError(f"cannot freeze {type(x).__name__} into a scorecard")


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

    HONEST LIMITS, the complete list of routes known to this module (Python cannot make this impossible):
    (1) `object.__setattr__` bypasses the freeze and replaces any field outright.
    (2) `gc.get_referents(card.details)[0]` returns the WRITABLE dict behind the `MappingProxyType`, so
        `gc.get_referents(card.details)[0]["injected"] = 1` adds a key to `details` and changes
        `content_hash()`. The proxy is a read-only VIEW of a dict, not a copy of it, and `gc` can reach the
        dict through the view. This grants no power (1) does not already grant, and it is equally detectable
        by the same means, but it is a route and this module's standard is that routes are stated.
        (`to_dict()` is a true defensive copy: mutating its result cannot reach the card.)
    The card stores no hash of itself (only `seed_digest`, a hash of the seed list), so tampering by EITHER
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

    def __post_init__(self) -> None:
        for nm in ("probe_id", "probe_kind"):
            v = getattr(self, nm)
            if not isinstance(v, str) or not v.strip():
                raise ValueError(f"{nm} must be a nonblank string")
        if not isinstance(self.status, ProbeStatus):
            raise ValueError("status must be a ProbeStatus")
        ProbeConfig(self.min_seeds)
        seeds = _check_seeds(self.seeds)
        if self.seed_digest != seed_list_digest(seeds):
            raise ValueError("seed_digest does not match the seed list")
        per_seed = tuple(self.per_seed)
        if len(per_seed) != len(seeds) or not all(isinstance(m, MetricValue) for m in per_seed):
            raise ValueError("per_seed must hold exactly one MetricValue per seed")
        if (self.summary is None) == (self.insufficient is None):
            raise ValueError("exactly one of summary / insufficient must be set")
        measured = tuple(m.value for m in per_seed if m.is_measured)
        if self.summary is not None:
            _recheck_summary(self.summary)
            if self.status is ProbeStatus.INSUFFICIENT_EVIDENCE:
                raise ValueError("a summarized scorecard cannot have INSUFFICIENT_EVIDENCE status")
            if self.summary.values != measured:
                raise ValueError("summary does not match the measured per-seed values")
            if len(measured) < self.min_seeds:
                raise ValueError("summary present with fewer measured seeds than min_seeds")
        else:
            _recheck_insufficient(self.insufficient)
            if self.status is not ProbeStatus.INSUFFICIENT_EVIDENCE:
                raise ValueError("an insufficient scorecard must have INSUFFICIENT_EVIDENCE status")
            if self.insufficient.n_measured != len(measured) or self.insufficient.n_required != self.min_seeds:
                raise ValueError("insufficient-evidence counts do not match per-seed values / min_seeds")
        labels = tuple(sorted({EvidenceClass.parse(x) for x in self.evidence_labels}, key=lambda e: e.value))
        if EvidenceClass.SOURCE_OBSERVED in labels:
            raise ValueError("SOURCE_OBSERVED cannot label a probe scorecard")
        if EvidenceClass.NOT_VALIDATED not in labels:
            raise ValueError("every scorecard must carry NOT_VALIDATED (no independent validation exists)")
        if (EvidenceClass.TOY_RESULT in labels) != (self.summary is not None):
            raise ValueError("TOY_RESULT label if and only if a summary exists")
        if self.summary is None and EvidenceClass.UNKNOWN not in labels:
            raise ValueError("an insufficient scorecard must carry UNKNOWN")
        if any(not m.is_measured for m in per_seed) and EvidenceClass.UNKNOWN not in labels:
            raise ValueError("a scorecard with unmeasured seeds must carry UNKNOWN")
        dne = tuple(self.does_not_establish)
        if not dne or any(not isinstance(s, str) or not s.strip() for s in dne):
            raise ValueError("does_not_establish must be a nonempty tuple of nonblank strings")
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
            "status": self.status.value, "min_seeds": self.min_seeds, "seeds": list(self.seeds),
            "seed_digest": self.seed_digest, "per_seed": [m.to_dict() for m in self.per_seed],
            "summary": self.summary.to_dict() if self.summary else None,
            "insufficient": self.insufficient.to_dict() if self.insufficient else None,
            "evidence_labels": [e.value for e in self.evidence_labels],
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
                    details_if_summarized: Mapping = MappingProxyType({}), non_claims: Sequence[str] = ()
                    ) -> Scorecard:
    """The only place a scorecard's evidence labels and summary-vs-insufficient branch are decided."""
    seeds = _check_seeds(seeds)
    per_seed = tuple(per_seed)
    result = summarize_seeds(per_seed, cfg.min_seeds)
    labels = {EvidenceClass.NOT_VALIDATED}
    if any(not m.is_measured for m in per_seed):
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
    n_meas = float(sum(m.is_measured for m in sc.per_seed))
    metrics = {"n_seeds": MetricValue.measured(float(len(sc.seeds))), "n_measured": MetricValue.measured(n_meas),
               "min_seeds_required": MetricValue.measured(float(sc.min_seeds))}
    s = sc.summary
    for key, val in (("mean", s.mean if s else None), ("sd", s.sd if s else None), ("iqr", s.iqr if s else None),
                     ("min", s.minimum if s else None), ("max", s.maximum if s else None)):
        metrics[key] = (MetricValue.measured(val) if val is not None else
                        MetricValue.unmeasured(f"INSUFFICIENT_EVIDENCE: {sc.insufficient.reason}"))
    prov = RunProvenance(run_id=run_id, timestamp_utc=timestamp_utc, seed=sc.seeds[0], code_version=code_version,
                         python_version=current_python_version(), toy_only=True,
                         input_hashes={"seed_list": sc.seed_digest, "scorecard": sc.content_hash()})
    return ExperimentRecord(
        name=f"robustness:{sc.probe_id}", provenance=prov, metrics=metrics,
        evidence_class=EvidenceClass.TOY_RESULT if s else EvidenceClass.UNKNOWN,
        notes=f"status={sc.status.value}; structured status is on the scorecard (hash in input_hashes); "
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
    vals = [m.value for m in per_seed if m.is_measured]
    return build_scorecard(
        probe_id=probe_id, probe_kind="seed_sensitivity", seeds=seeds, per_seed=per_seed, cfg=cfg,
        status_if_summarized=ProbeStatus.MEASURED,
        details_always={"outcome_name": getattr(outcome, "__name__", "outcome")},
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
        if not m.is_measured:
            raise ValueError(f"{metric} unmeasured: {m.reason}")
        return m.value
    outcome.__name__ = f"benchmark:{metric}"
    return outcome


# ================================================== measures and fixtures (toy)
@dataclasses.dataclass(frozen=True)
class MeasureFixture:
    seed: int
    pred: Matrix
    target: Matrix
    mask: Mask


def make_measure_fixture(seed: int, rows: int = 16, width: int = 3, noise: float = 0.1,
                         magnitude_spread: int = 0) -> MeasureFixture:
    """Synthetic fixture. target ~ U(-1,1); pred = target + U(-noise,noise); row r is multiplied by
    10**k_r with k_r in [0, magnitude_spread] (spread=0 => all 1). Mask has >= 2 True and >= 1 False."""
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
        mask[rng.choice([i for i in range(rows) if i not in forced])] = False
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
                    raise _UNDERFLOW(f"squared error underflowed to 0.0 from distinct inputs ({a!r}, {b!r})")
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
    """Ground truth: exact rational MSE of the given float inputs (no rounding at all)."""
    num, cnt = Fraction(0), 0
    for pr, tr, use in zip(pred, target, mask):
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
    binary floating point (no overflow/underflow), so they are declared EXACT; others BOUNDED."""
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
    |mse' - mse| <= 2*rms*eps + eps^2 (plus float slack)."""
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
    exact_kind = spec.kind is ShiftKind.INVARIANCE_EXACT
    rows = []   # (seed, dev, expected, bound) for measured seeds
    per_seed = []
    for s in seeds:
        try:
            fx = fixture_factory(s)
            base = measure(fx.pred, fx.target, fx.mask)
            fx2 = spec.transform(fx, make_rng(derive_seed(s, "robustness:shift:" + spec.name)))
            val = measure(fx2.pred, fx2.target, fx2.mask)
            exp = spec.expected(base)
            if not (math.isfinite(exp) and exp > 0):
                raise ValueError("expected value is not positive; relative deviation undefined")
            dev = abs(val - exp)
            bound = 0.0 if exact_kind else float(spec.bound(base, exp, fx2))
            rows.append((s, dev, exp, bound))
            per_seed.append(MetricValue.measured(float(dev / exp)))
        except (ValueError, TypeError, ArithmeticError) as e:
            per_seed.append(MetricValue.unmeasured(f"{type(e).__name__}: {e}"))
    viol = [r for r in rows if r[1] > r[3]]
    bounded = spec.kind is ShiftKind.SENSITIVITY_BOUNDED
    ok_status = ProbeStatus.SENSITIVITY_WITHIN_BOUND if bounded else ProbeStatus.INVARIANCE_HOLDS
    bad_status = ProbeStatus.SENSITIVITY_EXCEEDS_BOUND if bounded else ProbeStatus.INVARIANCE_DEFECT
    ratios = [r[1] / r[3] for r in rows if r[3] > 0]
    return build_scorecard(
        probe_id=probe_id or f"shift:{getattr(measure, '__name__', 'measure')}:{spec.name}",
        probe_kind="benign_shift", seeds=seeds, per_seed=per_seed, cfg=cfg,
        status_if_summarized=bad_status if viol else ok_status,
        details_always={"measure": getattr(measure, "__name__", "measure"), "transform": spec.name,
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
            "unmeasured_seeds": [sd for sd, m in zip(seeds, per_seed) if not m.is_measured]},
        non_claims=("Bounds are hand-derived caps for this fixture family; a pass does not show the measure "
                    "is robust to any perturbation outside the probed family.",))


# ===================================================== 3. missing-input handling
def arm_difference(arms: Mapping[str, MetricValue], treatment: str, control: str) -> MetricValue:
    """treatment - control as a MetricValue; any absent or unmeasured arm => unmeasured(reason). Never 0.0."""
    for nm in (treatment, control):
        if nm not in arms:
            return MetricValue.unmeasured(f"arm {nm!r} absent")
        if not isinstance(arms[nm], MetricValue):
            raise ValueError(f"arm {nm!r} must be a MetricValue")
        if not arms[nm].is_measured:
            return MetricValue.unmeasured(f"arm {nm!r} unmeasured: {arms[nm].reason}")
    return MetricValue.measured(arms[treatment].value - arms[control].value)


def guarded(measure: Measure) -> Callable[..., MetricValue]:
    """Wrap a measure so rejection becomes MetricValue.unmeasured(reason) instead of an exception."""
    def run(pred, target, mask) -> MetricValue:
        try:
            v = measure(pred, target, mask)
        except (ValueError, TypeError, ArithmeticError) as e:
            return MetricValue.unmeasured(f"{type(e).__name__}: {e}")
        if isinstance(v, bool) or not isinstance(v, float) or not math.isfinite(v):
            return MetricValue.unmeasured(f"non-float or non-finite result {v!r}")
        return MetricValue.measured(v)
    run.__name__ = getattr(measure, "__name__", "measure")
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
    out = {}
    for name, args in missing_input_cases(fx).items():
        try:
            v = measure(*args)
            out[name] = ("SILENT_VALUE", repr(v))
        except (ValueError, TypeError, ArithmeticError) as e:
            out[name] = ("RAISED", type(e).__name__)
    return out


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
    structural = {"empty_seed_list_gives_insufficient": empty.status is ProbeStatus.INSUFFICIENT_EVIDENCE
                  and empty.summary is None,
                  "absent_arm_gives_unmeasured": (not arm.is_measured) and arm != MetricValue.measured(0.0)}
    silent_total = sum(r["silent_value"] for r in table.values())
    defect = silent_total > 0 or not all(structural.values())
    return build_scorecard(
        probe_id=probe_id or f"missing_inputs:{getattr(measure, '__name__', 'measure')}",
        probe_kind="missing_inputs", seeds=seeds, per_seed=per_seed, cfg=cfg,
        status_if_summarized=ProbeStatus.SILENT_DEFAULT_DEFECT if defect else ProbeStatus.MISSING_INPUT_HANDLED,
        details_always={"measure": getattr(measure, "__name__", "measure"), "cases": sorted(missing_input_cases(
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
    seeds = _check_seeds(seeds)
    per_seed, rows = [], []
    for s in seeds:
        try:
            r = _precision_outcome(kind, param, s, measure)
        except (ValueError, TypeError, ArithmeticError) as e:
            per_seed.append(MetricValue.unmeasured(f"{type(e).__name__}: {e}"))
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
