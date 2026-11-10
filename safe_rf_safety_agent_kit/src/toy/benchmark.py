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
  `min_seeds` gate; no component verdict exists below the minimum.
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
  gradient ratio 1.1e-3..3.4e-3 vs tau_conv=1e-3) fail, while base seeds 7, 11 and 99 give JOINT_SUPPORTED. The
  defaults for `eps_fit` and `tau_conv` therefore need setting at registration (they are PROTOCOL PARAMETERS);
  this is a property of the defaults, not of the fixtures' logic.
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
Matrix = tuple
Predictor = Callable[[Sequence[Sequence[float]]], Matrix]


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
    Why that is nevertheless sufficient for recomputation, precisely: every component record stores its own
    `margin` as a measured metric (`_agg_metrics`), and `verdict_from_records` reads the margin OUT OF THE
    RECORD it is recomputing -- never from a caller's `cfg`, never from `config_hash`. So the margin a
    recompute uses is always the margin that produced the record, and a changed margin shows up as a changed
    `margin` metric rather than as a silently reused one.
    What the gap DOES cost: `config_hash` alone is not a complete provenance key for a study. Do not quote it
    as one; quote the per-component `margin` metrics (or `JointResult.margins`) alongside it."""
    delta_S: float = 0.10
    delta_R: float = 0.05
    delta_sel: float = 0.10

    def __post_init__(self) -> None:
        for k in ("delta_S", "delta_R", "delta_sel"):
            v = getattr(self, k)
            if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
                raise ValueError(f"{k} must be a finite number")


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

    def __post_init__(self) -> None:
        for k in ("width", "n_train", "n_eval", "steps", "n_boot", "min_seeds", "steps_conv"):
            v = getattr(self, k)
            if isinstance(v, bool) or not isinstance(v, int) or v < 0:
                raise ValueError(f"{k} must be a nonnegative int")
        if self.width < 1 or self.n_eval < 1 or self.n_boot < 1:
            raise ValueError("width, n_eval and n_boot must be >= 1")
        if self.n_train < 16:
            raise ValueError("n_train must be >= 16 (protocol: masked subset needs >= 2 distinct values)")
        for k in ("lr", "eta_star", "g_min", "alpha", "max_failure_rate", "width_tol", "tau_conv", "delta_A",
              "eps_fit", "loss_factor", "tail_ratio_max"):
            v = getattr(self, k)
            if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or v < 0:
                raise ValueError(f"{k} must be a finite nonnegative number")
        if self.lr <= 0 or not 0 < self.alpha < 1:
            raise ValueError("lr must be > 0 and alpha in (0,1)")

    def config_hash(self) -> str:
        """sha256 over the canonical JSON of all 18 fields; every field changes it (no collisions found).
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
        raise ValueError(f"{what} needs a sequence of numbers, got {type(v).__name__}")
    return list(v)


def _check_finite(v: Sequence[float], what: str) -> None:
    try:
        ok = all(isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x) for x in v)
    except OverflowError:      # a Python int too large for float, e.g. 10**400
        ok = False
    if not ok:
        raise ValueError(f"{what} needs finite numbers (no inf/nan/non-numeric/too-large int)")


def mean(v: Sequence[float]) -> float:
    """Public mean: finite numeric sequences only (ValueError otherwise)."""
    v = _as_list(v, "mean")
    _check_finite(v, "mean")
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
    _check_finite(v, "sample SD")          # without this, [inf,inf,inf] would give 0.0 (constant) or nan
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
    """Linear-interpolation quantile (the 'type 7' definition): position p*(n-1) in the sorted sample."""
    if not 0.0 <= p <= 1.0:
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
    if not 0 < alpha < 1 or isinstance(m, bool) or not isinstance(m, int) or m < 1:
        raise ValueError("need 0 < alpha < 1 and integer m >= 1")
    return 1.0 - alpha / m


def _check_level(level: float) -> None:
    if isinstance(level, bool) or not isinstance(level, (int, float)) or not 0 < level < 1:
        raise ValueError("level must be in (0, 1)")


def percentile_interval(stats: Sequence[float], level: float) -> tuple[float, float]:
    """Percentile interval of already-computed resample statistics (type-7 quantiles at
    (1-level)/2 and 1-(1-level)/2)."""
    _check_level(level)
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
    _check_finite(vals, "bootstrap")
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
    _check_level(level)
    values = _as_list(values, "t-interval")
    _check_finite(values, "t-interval")      # BEFORE any arithmetic: no raw TypeError/OverflowError from _mean
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
            return True, f"{nm} bound on different sides of margin {margin!r} (bootstrap {b!r}, t {t!r})"
    wb, wt = boot[1] - boot[0], tint[1] - tint[0]
    big = max(wb, wt)
    if big > 0 and abs(wb - wt) / big > width_tol:
        return True, f"widths differ by more than {width_tol:.0%} (bootstrap {wb!r}, t {wt!r})"
    return False, "agree"


# ============================================================ interval pair
def _mv(x: Optional[float], reason: str) -> MetricValue:
    if x is None or isinstance(x, bool) or not math.isfinite(x):
        return MetricValue.unmeasured(reason)
    return MetricValue.measured(float(x))


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
        fail-closed case, so a forged bound can no longer produce a verdict in either direction."""
        v = getattr(m, "value", None)
        if isinstance(v, bool) or not isinstance(v, float) or not math.isfinite(v):
            return None
        return v

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
    _check_level(level)
    vals = [float(v) for v in values]
    if not all(math.isfinite(v) for v in vals):
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
        flags.append(f"heavy tail: max|v|/median|v| = {ratio:.3g} > {tail_ratio_max} (flag only)")
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
    n < min_n (default 30) is always INCONCLUSIVE."""
    return _verdict_from_bounds(pair.n, pair.boot(), pair.tint(), margin, direction, min_n, width_tol)


def combine_joint(h1: Verdict, h2: Verdict, h3: Verdict, gates_ok: bool) -> JointVerdict:
    """Protocol section 5. A failed validity gate gives INCONCLUSIVE first (section 5 last line,
    section 7 stop rule); then any UNSUPPORTED => JOINT_UNSUPPORTED; all three SUPPORTED =>
    JOINT_SUPPORTED; otherwise INCONCLUSIVE."""
    vs = (Verdict(h1), Verdict(h2), Verdict(h3))
    if not gates_ok:
        return JointVerdict.JOINT_INCONCLUSIVE
    if Verdict.UNSUPPORTED in vs:
        return JointVerdict.JOINT_UNSUPPORTED
    if all(v is Verdict.SUPPORTED for v in vs):
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
        if self.hid not in PRIMARY:
            raise ValueError(f"{self.hid!r} is not a primary hypothesis")
        if len(self.components) != len(PRIMARY[self.hid]):
            raise ValueError("wrong number of components for " + self.hid)
        if self.hid != "H3" and self.converged_components:
            raise ValueError("only H3 has converged-budget components")
        if len(self.converged_components) > len(CONVERGED):
            raise ValueError("too many converged-budget components")
        if not all(isinstance(c, ComponentResult) for c in self.components + self.converged_components):
            raise ValueError("components must be ComponentResult objects (verdicts are derived, not supplied)")
        vs = [c.verdict for c in self.components]
        reasons = [f"{c.metric}: {c.reason}" for c in self.components]
        if self.blocking:
            verdict = Verdict.INCONCLUSIVE
            reasons = [f"gate failed: {g}" for g in self.blocking] + reasons
        elif Verdict.UNSUPPORTED in vs:
            verdict = Verdict.UNSUPPORTED
        elif not all(v is Verdict.SUPPORTED for v in vs):
            verdict = Verdict.INCONCLUSIVE
        elif self.hid != "H3":
            verdict = Verdict.SUPPORTED
        elif self.supported_blockers:
            verdict = Verdict.INCONCLUSIVE
            reasons += [f"cannot be SUPPORTED, gate failed: {g}" for g in self.supported_blockers]
        elif len(self.converged_components) != len(CONVERGED):
            verdict = Verdict.INCONCLUSIVE
            reasons.append("converged-budget requirement (4.1) not evaluated")
        elif not all(c.verdict is Verdict.SUPPORTED for c in self.converged_components):
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
    if hid not in PRIMARY:
        raise ValueError(f"{hid!r} is not a primary hypothesis; non-primary metrics are exploratory and "
                         f"cannot produce a verdict (use exploratory_interval)")
    level = bonferroni_level(cfg.alpha, N_PRIMARY)

    def build(table):
        out = []
        for metric, direction, mname in table:
            pair = summarize(f"{hid}:{metric}", series.get(metric, ()), level, cfg.n_boot, base_seed,
                             cfg.min_seeds, cfg.tail_ratio_max)
            out.append(ComponentResult(metric, direction, float(getattr(margins, mname)), pair, cfg.min_seeds,
                                       cfg.width_tol))
        return tuple(out)

    return HypothesisResult(hid, build(PRIMARY[hid]), build(CONVERGED) if hid == "H3" else (),
                            tuple(blocking), tuple(supported_blockers))


def exploratory_interval(name: str, values: Sequence[float], cfg: BenchmarkConfig, base_seed: int
                         ) -> ExploratoryResult:
    """Interval at the unadjusted level 1-alpha, labelled EXPLORATORY. Never yields a verdict."""
    if name in PRIMARY:
        raise ValueError(f"{name!r} is a primary hypothesis id; use evaluate_primary")
    return ExploratoryResult(name, summarize("explore:" + name, values, 1.0 - cfg.alpha, cfg.n_boot, base_seed,
                                             cfg.min_seeds, cfg.tail_ratio_max))


def required_n(pilot_sds: Sequence[float], margins: Margins, level: float, n_floor: int = 100,
               n_cap: Optional[int] = None) -> tuple:
    """Pure arithmetic of the protocol 6.1 precision rule (the pilot itself is NOT run here):
    hw_max = 0.5*min(margins); n_req = ceil((z*SD_max/hw_max)^2), z = normal quantile of the adjusted level;
    n_planned = max(n_floor, n_req). Returns (n_planned, n_req, capped) where capped means n_req > n_cap."""
    from statistics import NormalDist
    _check_level(level)
    sds = [float(s) for s in pilot_sds]
    if not sds or any(not math.isfinite(s) or s < 0 for s in sds):
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
    one declared factor and share TRAIN, lr, student init (derive_seed(seed,'student_init'))."""
    if arm not in ARM_NAMES:
        raise ValueError(f"unknown arm {arm!r}; allowed {ARM_NAMES}")
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
    return _arm_fit(seed, arm, cfg).params


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
    if t and getattr(treatment, "arm_name", None) not in ARM_NAMES:
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
        return _all_unmeasured(f"G_s={fx.G!r} not above eligibility floor")
    try:
        oT, oU = fx.teacher.outputs(fx.T), fx.teacher.outputs(fx.U)
        eT_c = _mse(pred(fx.T), oT.conditioned) - _mse(c0(fx.T), oT.conditioned)
        eU_u = _mse(pred(fx.U), oU.unconditioned) - _mse(c0(fx.U), oU.unconditioned)
        eU_c = _mse(pred(fx.U), oU.conditioned) - _mse(c0(fx.U), oU.conditioned)
        raw_T, raw_U = _mse(pred(fx.T), oT.conditioned), _mse(pred(fx.U), oU.unconditioned)
    except (ValueError, OverflowError, ArithmeticError) as e:
        return _all_unmeasured(f"prediction failed: {e}")
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
        if set(self.metrics) != set(SEED_METRICS):
            raise ValueError(f"metrics must have exactly keys {SEED_METRICS}")
        if not all(isinstance(v, MetricValue) for v in self.metrics.values()):
            raise ValueError("metrics must be MetricValues")

    @property
    def ok(self) -> bool:
        return all(self.metrics[k].is_measured for k in _PRIMARY_SERIES)

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
        u = MetricValue.unmeasured(f"converged-budget run failed: {e}")
        return u, u, u
    d = a.delta.value if a.delta.is_measured else None
    ds = (a.delta.value - b.delta.value) if a.delta.is_measured and b.delta.is_measured else None
    gr = max(ratios) if all(r is not None for r in ratios) else None
    return _mv(d, "converged contrast unmeasured"), _mv(ds, "converged contrast unmeasured"), \
        _mv(gr, "initial gradient is zero")


def score_seed(seed: int, treatment: PredictorFactory, cfg: BenchmarkConfig) -> SeedScores:
    """Score one replicate: treatment vs C0, plus delta_E - delta_Cshuf, gate-11 inputs and the converged-budget
    contrasts. Raises IneligibleSeed (not a failed run) for an ineligible fixture.
    Whether the treatment is a trained student is read from the factory's own declaration (`treatment_kind`),
    never from a caller flag: an undeclared factory gets E_loss_ratio unmeasured (and so fails gate 11(c))."""
    kind = treatment_kind(treatment)
    trained_arm = treatment.arm_name if kind == "trained" else None
    try:
        fx = build_fixture(seed, cfg)
    except IneligibleSeed:
        raise
    except ValueError as e:
        return SeedScores.failed(seed, f"fixture build failed: {e}")
    hashes = fixture_hashes(fx)
    try:
        c0 = ARM_FACTORIES["C0"](fx, cfg)
        sh = ARM_FACTORIES["C_shuf"](fx, cfg)
        a = score_predictor(fx, treatment(fx, cfg), c0, cfg.g_min)
        b = score_predictor(fx, sh, c0, cfg.g_min)
        A, F = _control_adequacy(fx, cfg, c0)
        lr_ = _arm_fit(seed, trained_arm, cfg).loss_ratio if trained_arm else None
    except ValueError as e:   # train() divergence etc.: counted, never hidden
        return SeedScores.failed(seed, f"numerical failure: {e}", fx.disjoint, fx.mask_ok, hashes)
    dms = (MetricValue.measured(a.delta.value - b.delta.value) if a.delta.is_measured and b.delta.is_measured
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
        if self.exempt is not True and self.exempt is not False:
            raise ValueError("GateResult.exempt must be exactly True or False")
        if self.exempt and self.name != "control_adequacy":
            raise ValueError("only control_adequacy can carry an exemption")
        if self.name not in GATE_SCOPES:
            raise ValueError(f"unknown gate {self.name!r}")
        if self.passed is not True and self.passed is not False:   # no truthy strings / ints / None
            raise ValueError(f"GateResult.passed must be exactly True or False, got {self.passed!r}")
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
        vals = [s.metrics[key].value for s in ok_scores]
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
        rs = [s.metrics["E_loss_ratio"].value for s in ok_scores]
        if not rs or any(r is None for r in rs):
            probs.append("E_loss_ratio not measured on every seed")
        elif max(rs) > 1.0 / cfg.loss_factor:
            probs.append(f"E training loss did not fall by factor {cfg.loss_factor} in every run (worst ratio {max(rs)!r})")
    gates.append(GateResult("control_adequacy", not probs, "; ".join(probs) or
                            ("A, F, E-loss ok" if not exempt else
                                          "A, F ok; E-loss check exempt (declared scorer-validation fixture)"),
                            exempt=exempt))
    # gate 12: converged-budget gradient norm
    grs = [s.metrics["conv_grad_ratio"].value for s in ok_scores]
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
        for h, hid in ((self.h1, "H1"), (self.h2, "H2"), (self.h3, "H3")):
            if not isinstance(h, HypothesisResult) or h.hid != hid:
                raise ValueError(f"JointResult needs HypothesisResult {hid} in its slot")
        if self.subject_kind not in SUBJECT_KINDS:
            raise ValueError(f"subject_kind must be one of {SUBJECT_KINDS}")
        if (self.subject_kind == "fixture") != (isinstance(self.fixture_name, str) and bool(self.fixture_name.strip())):
            raise ValueError("fixture_name is required for, and only for, subject_kind='fixture'")
        if carries_exemption(self.gates) and self.subject_kind != "fixture":
            raise ValueError("a gate carries the fixture exemption but subject_kind is not 'fixture'")
        names = [g.name for g in self.gates if isinstance(g, GateResult)]
        if sorted(names) != sorted(GATE_SCOPES):
            raise ValueError(f"gates must contain exactly {sorted(GATE_SCOPES)} (empty gates do not pass vacuously)")
        # Single-place invariant, independent of how the HypothesisResults were built (e.g. without `blocking`):
        failed = {g.name: g for g in self.gates if not g.passed}
        if any(GATE_SCOPES[n] == "all" for n in failed):
            bad = [h.hid for h in (self.h1, self.h2, self.h3) if h.verdict is not Verdict.INCONCLUSIVE]
            if bad:
                raise ValueError(f"a failed global gate {sorted(n for n in failed if GATE_SCOPES[n] == 'all')} "
                                 f"requires INCONCLUSIVE, but {bad} are decisive")
        if "convergence" in failed and self.h3.verdict is Verdict.SUPPORTED:
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
    glob = [f"{g.name} ({g.reason})" for g in gates if g.scope == "all" and not g.passed]
    g12 = [f"convergence ({by['convergence'].reason})"] if not by["convergence"].passed else []
    names = _PRIMARY_SERIES + ("delta_conv", "delta_minus_shuf_conv")
    series = {k: [s.metrics[k].value for s in scores if s.ok and s.metrics[k].is_measured] for k in names}
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
    m = {"mean": pair.mean, "sd": pair.sd, "iqr": pair.iqr, "min": pair.minimum, "max": pair.maximum,
         "max_over_median_abs": pair.max_over_median_abs,
         "ci_boot_lo": pair.boot_lo, "ci_boot_hi": pair.boot_hi, "ci_t_lo": pair.t_lo, "ci_t_hi": pair.t_hi,
         "n_seeds": MetricValue.measured(float(pair.n)), "n_failed": MetricValue.measured(float(n_failed)),
         "ci_level": MetricValue.measured(float(pair.level)), "n_boot": MetricValue.measured(float(pair.n_boot)),
         "margin": MetricValue.measured(float(margin)),
         "subject_kind_code": MetricValue.measured(SUBJECT_KIND_CODE[subject_kind])}
    return m


def _tag(hid: str, metric: str, conv: bool = False) -> str:
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
        raise ValueError(f"scorer_validation={scorer_validation!r} contradicts subject_kind={res.subject_kind!r}")
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
                ec = EvidenceClass.TOY_RESULT if c.pair.mean.is_measured else EvidenceClass.UNKNOWN
                recs.append(ExperimentRecord(
                    name=f"evalproto/{study_id}/agg/{tag}", provenance=prov(f"{study_id}-agg-{tag}", base_seed),
                    metrics=_agg_metrics(c.pair, c.margin, res.n_failed, res.subject_kind), evidence_class=ec,
                    notes=f"{TOY_LABEL} PRIMARY {h.hid} component {c.metric} [{kind}] subject={res.subject} "
                          f"subject_kind={res.subject_kind} fixture_name={res.fixture_name}. "
                          f"Informational only; flags: {list(c.pair.flags)}"))
    gate_m = {f"gate_{g.name}": MetricValue.measured(1.0 if g.passed else 0.0) for g in res.gates}
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


def _pair_from_record(rec: ExperimentRecord) -> IntervalPair:
    m = rec.metrics
    return IntervalPair(rec.name, int(m["n_seeds"].value), m["ci_level"].value, int(m["n_boot"].value),
                        m["mean"], m["sd"], m["iqr"], m["min"], m["max"], m["max_over_median_abs"],
                        m["ci_boot_lo"], m["ci_boot_hi"], m["ci_t_lo"], m["ci_t_hi"])


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
    NOT covered by the config hash: `Margins` is not a `BenchmarkConfig` field (see `Margins`). That is
    sound here because the margin of every component is read OUT OF THE RECORD (`margin` metric), never from
    `cfg` -- so no margin a recompute uses can come from the caller at all.
    ORDER: the `loss_check_exempt` / `subject_kind_code` forgery checks run BEFORE the config check, so a
    config mismatch can never mask a forgery; `cfg` is not consulted by either of them.
    WHAT THE BINDING DOES NOT DO, stated because "BOUND TO THE CONFIGURATION THE STUDY RAN UNDER" above
    would otherwise overstate it: the stored `config` hash is itself a stored value, so **rewriting it in
    every record and passing the cfg that matches the rewrite reaches JOINT_SUPPORTED with no reason
    recorded.** This is post-hoc tampering in the already-disclosed class -- it grants nothing over forging
    the `gate_*` metrics directly, and requires write access to every record -- but it was not stated for the
    config hash specifically, and this module's standard is that the routes are stated rather than left to be
    discovered. The binding defeats the ORDINARY-CALL defect above and an inconsistent or absent hash; it is
    not an authentication of the records."""
    cfg = _cfg(cfg)
    by = {}
    for r in records:
        if "/agg/" in r.name:
            by[r.name.rsplit("/agg/", 1)[1]] = r
    need = ["H1", "H2", "H3a", "H3b", "H3a_conv", "H3b_conv", "JOINT"]
    missing = [k for k in need if k not in by]
    if missing:
        raise ValueError(f"records missing for {missing}")
    for r in by.values():
        if r.evidence_class is not EvidenceClass.TOY_RESULT:
            raise ValueError(f"{r.name}: only TOY_RESULT records can carry a recomputed verdict")

    # ---- subject-kind decode and exemption-forgery checks: no `cfg` is consulted, so they run first and a
    # ---- config mismatch can never mask a forgery.
    gm = by["JOINT"].metrics
    code = gm.get("subject_kind_code")
    kind = next((k for k, c in SUBJECT_KIND_CODE.items() if code is not None and code.value == c), "unknown")
    ex = gm.get("loss_check_exempt")
    if ex is not None and ex.is_measured and ex.value not in (0.0, 1.0):
        raise ValueError(f"loss_check_exempt must be 0.0 or 1.0, got {ex.value!r}")
    if ex is not None and ex.is_measured and ex.value == 1.0 and kind != "fixture":
        raise ValueError("records claim the gate-11(c) exemption but subject_kind_code is not 'fixture' "
                         "(forged or deleted code)")

    # ---- BIND the recompute to the stored configuration before any cfg-derived parameter is used.
    stored = {r.provenance.input_hashes.get("config") for r in by.values()}
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

    def comp(tag, metric, direction):
        r = by[tag]
        mg, lv = r.metrics["margin"], r.metrics["ci_level"]
        if not mg.is_measured:
            raise ValueError(f"{tag}: margin unmeasured")
        if not lv.is_measured or abs(lv.value - want_level) > 1e-12:
            raise ValueError(f"{tag}: ci_level {lv.value!r} is not the adjusted level {want_level!r} (m={N_PRIMARY})")
        return ComponentResult(metric, direction, mg.value, _pair_from_record(r), cfg.min_seeds, cfg.width_tol)

    state = {n: gm.get(f"gate_{n}") for n in GATE_SCOPES}
    failed = [n for n, v in state.items() if v is None or v.value != 1.0]
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
