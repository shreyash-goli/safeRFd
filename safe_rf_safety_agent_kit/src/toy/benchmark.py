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
* Only H1, H2, H3 can produce a verdict (Bonferroni family, m=3). Anything else
  is an `ExploratoryResult`, which has no verdict field at all.
* Verdicts are reported only inside one `JointResult`; there is no standalone
  suppression getter. The verdict is a structured enum object; the
  `ExperimentRecord.notes` string is a serialisation fallback and must never be
  parsed back as evidence (schema gap reported for SR-14).
* The deterministic RNG is `make_rng(derive_seed(...))`; global `random` state
  is never touched.

Known limits stated plainly: a "frozen" seed list is verified only as "the
digest supplied by the caller equals the digest of the seeds analysed"; this
code cannot prove the digest was recorded *before* any arm was run. Gates that
the protocol assigns to SR-11 or to other registers (configuration-shift
sensitivity arm, ERROR_REGISTER cross-check, V-set) are NOT implemented here;
`JointResult.deferred_gates` lists them and `complete_gate_coverage` is False.
"""
from __future__ import annotations

import dataclasses
import functools
import hashlib
import json
import math
from datetime import datetime, timezone
from enum import Enum
from typing import Callable, Mapping, Optional, Sequence

from toy.schema import (TOY_LABEL, EvidenceClass, ExperimentRecord, MetricValue, RunProvenance,
                        current_python_version, derive_seed, make_rng)
from toy.teacher_student import Teacher, erasure_target, make_teacher, predict, train

CODE_VERSION = "toy-benchmark-v1"
PINNED_TS = "2000-01-01T00:00:00Z"  # internal: train() records need a timestamp; not used as evidence
N_PRIMARY = 3                       # H1, H2, H3
DEFERRED_GATES = ("config_shift_sensitivity_arm", "error_register_crosscheck", "V_set_probes")
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
    """PROTOCOL PARAMETERS (proposed defaults, arbitrary, no empirical basis), in G_s units."""
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

    def __post_init__(self) -> None:
        for k in ("width", "n_train", "n_eval", "steps", "n_boot", "min_seeds"):
            v = getattr(self, k)
            if isinstance(v, bool) or not isinstance(v, int) or v < 0:
                raise ValueError(f"{k} must be a nonnegative int")
        if self.width < 1 or self.n_eval < 1 or self.n_boot < 1:
            raise ValueError("width, n_eval and n_boot must be >= 1")
        if self.n_train < 16:
            raise ValueError("n_train must be >= 16 (protocol: masked subset needs >= 2 distinct values)")
        for k in ("lr", "eta_star", "g_min", "alpha", "max_failure_rate", "width_tol"):
            v = getattr(self, k)
            if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or v < 0:
                raise ValueError(f"{k} must be a finite nonnegative number")
        if self.lr <= 0 or not 0 < self.alpha < 1:
            raise ValueError("lr must be > 0 and alpha in (0,1)")

    def config_hash(self) -> str:
        return hashlib.sha256(json.dumps(dataclasses.asdict(self), sort_keys=True,
                                         separators=(",", ":")).encode()).hexdigest()


# ============================================================ statistics
def mean(v: Sequence[float]) -> float:
    if len(v) == 0:
        raise ValueError("mean of empty sample")
    return math.fsum(v) / len(v)


def sample_sd(v: Sequence[float]) -> float:
    """Sample SD, divisor n-1."""
    n = len(v)
    if n < 2:
        raise ValueError("sample SD needs n >= 2")
    m = mean(v)
    return math.sqrt(math.fsum((x - m) ** 2 for x in v) / (n - 1))


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
    """Per-hypothesis two-sided confidence level 1 - alpha/m (alpha=.05, m=3 -> 0.98333...)."""
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
    if len(values) < 1 or isinstance(n_boot, bool) or not isinstance(n_boot, int) or n_boot < 1:
        raise ValueError("need a nonempty sample and n_boot >= 1")
    n = len(values)
    vals = list(values)
    return [math.fsum(rng.choices(vals, k=n)) / n for _ in range(n_boot)]


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
    n = len(values)
    if n < 2:
        raise ValueError("t-interval needs n >= 2")
    m, se = mean(values), sample_sd(values) / math.sqrt(n)
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

    def boot(self) -> Optional[tuple[float, float]]:
        return (self.boot_lo.value, self.boot_hi.value) if self.boot_lo.is_measured and self.boot_hi.is_measured else None

    def tint(self) -> Optional[tuple[float, float]]:
        return (self.t_lo.value, self.t_hi.value) if self.t_lo.is_measured and self.t_hi.is_measured else None


def summarize(name: str, values: Sequence[float], level: float, n_boot: int, base_seed: int,
              min_n: int = 30) -> IntervalPair:
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
    mom = _mv(max(abs(v) for v in vals) / med if med > 0 else None, "median |value| is 0")
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
def interval_verdict(pair: IntervalPair, margin: float, direction: str, width_tol: float = 0.25
                     ) -> tuple[Verdict, str]:
    """Protocol section 7 for one component. direction 'greater': SUPPORTED iff lower > margin,
    UNSUPPORTED iff upper <= margin. direction 'less': SUPPORTED iff upper < margin, UNSUPPORTED iff
    lower >= margin. The bootstrap interval decides; the t-interval can only veto via the disagreement rule."""
    if direction not in ("greater", "less"):
        raise ValueError("direction must be 'greater' or 'less'")
    b, t = pair.boot(), pair.tint()
    if b is None or t is None:
        return Verdict.INCONCLUSIVE, "interval not computable (n < 2): unmeasured, not zero"
    bad, why = intervals_disagree(b, t, margin, width_tol)
    if bad:
        return Verdict.INCONCLUSIVE, "bootstrap/t disagreement: " + why
    lo, hi = b
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


@dataclasses.dataclass(frozen=True)
class ComponentResult:
    metric: str
    direction: str
    margin: float
    pair: IntervalPair
    verdict: Verdict
    reason: str


@dataclasses.dataclass(frozen=True)
class HypothesisResult:
    hid: str
    components: tuple
    verdict: Verdict
    reasons: tuple
    label: str = "PRIMARY"


@dataclasses.dataclass(frozen=True)
class ExploratoryResult:
    """Unadjusted interval for a non-primary metric. Deliberately has NO verdict field."""
    name: str
    pair: IntervalPair
    label: str = "EXPLORATORY (unadjusted level; cannot support a verdict)"


def evaluate_primary(hid: str, series: Mapping[str, Sequence[float]], margins: Margins, cfg: BenchmarkConfig,
                     base_seed: int, gate_failures: Sequence[str] = ()) -> HypothesisResult:
    """Evaluate one primary hypothesis at the Bonferroni level. Refuses anything outside {H1,H2,H3}."""
    if hid not in PRIMARY:
        raise ValueError(f"{hid!r} is not a primary hypothesis; non-primary metrics are exploratory and "
                         f"cannot produce a verdict (use exploratory_interval)")
    level = bonferroni_level(cfg.alpha, N_PRIMARY)
    comps = []
    for metric, direction, mname in PRIMARY[hid]:
        margin = float(getattr(margins, mname))
        pair = summarize(f"{hid}:{metric}", series.get(metric, ()), level, cfg.n_boot, base_seed, cfg.min_seeds)
        v, why = interval_verdict(pair, margin, direction, cfg.width_tol)
        comps.append(ComponentResult(metric, direction, margin, pair, v, why))
    vs = [c.verdict for c in comps]
    if gate_failures:
        verdict, reasons = Verdict.INCONCLUSIVE, tuple(f"gate failed: {g}" for g in gate_failures)
    else:
        if Verdict.UNSUPPORTED in vs:
            verdict = Verdict.UNSUPPORTED
        elif all(v is Verdict.SUPPORTED for v in vs):
            verdict = Verdict.SUPPORTED
        else:
            verdict = Verdict.INCONCLUSIVE
        reasons = tuple(f"{c.metric}: {c.reason}" for c in comps)
    return HypothesisResult(hid, tuple(comps), verdict, reasons)


def exploratory_interval(name: str, values: Sequence[float], cfg: BenchmarkConfig, base_seed: int
                         ) -> ExploratoryResult:
    """Interval at the unadjusted level 1-alpha, labelled EXPLORATORY. Never yields a verdict."""
    if name in PRIMARY:
        raise ValueError(f"{name!r} is a primary hypothesis id; use evaluate_primary")
    return ExploratoryResult(name, summarize("explore:" + name, values, 1.0 - cfg.alpha, cfg.n_boot, base_seed,
                                             cfg.min_seeds))


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


@functools.lru_cache(maxsize=4096)
def build_fixture(seed: int, cfg: BenchmarkConfig) -> SeedFixture:
    teacher = make_teacher(seed, cfg.width)
    train_x = _rows(make_rng(derive_seed(seed, "train_rows")), cfg.n_train, cfg.width, None)
    mask = tuple(in_region(r) for r in train_x)
    if sum(mask) < 2 or len({r[0] for r, m in zip(train_x, mask) if m}) < 2:
        raise ValueError("degenerate fixture: fewer than 2 distinct masked rows")
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
ARM_NAMES = ("E", "C0", "C_init", "C_rand", "C_shuf", "C_all")


@functools.lru_cache(maxsize=4096)
def _arm_params(seed: int, arm: str, cfg: BenchmarkConfig) -> tuple:
    """Trained student parameters for (seed, arm, cfg). Pure function of its arguments; arms differ from
    E in exactly one declared factor and share TRAIN, steps, lr, student init (derive_seed(seed,'student_init'))."""
    if arm not in ARM_NAMES:
        raise ValueError(f"unknown arm {arm!r}; allowed {ARM_NAMES}")
    fx = build_fixture(seed, cfg)
    mask, teacher, eta, steps = fx.train_mask, fx.teacher, cfg.eta_star, cfg.steps
    if arm == "C0":
        eta = 0.0
    elif arm == "C_init":
        steps = 0
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
    return train(seed, steps=steps, lr=cfg.lr, eta=eta, x=fx.train_x, mask=mask, teacher=teacher,
                 timestamp_utc=PINNED_TS).final_params


def _student_factory(arm: str) -> PredictorFactory:
    def factory(fx: SeedFixture, cfg: BenchmarkConfig) -> Predictor:
        params = _arm_params(fx.seed, arm, cfg)
        return lambda rows: predict(params, tuple(tuple(r) for r in rows))
    factory.__name__ = f"arm_{arm}"
    return factory


ARM_FACTORIES: Mapping[str, PredictorFactory] = {a: _student_factory(a) for a in ARM_NAMES}


# --------------------------------------------- scorer-validation fixtures
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
    return factory


def fixture_identity_uncond(fx: SeedFixture, cfg: BenchmarkConfig) -> Predictor:
    """IDENTITY_TEACHER_UNCOND: returns the unconditioned output exactly. A test of the scorer."""
    return lambda rows: fx.teacher.outputs(tuple(tuple(r) for r in rows)).unconditioned


# ================================================================ scoring
SEED_METRICS = ("S", "L", "S_U", "delta", "delta_minus_shuf", "G", "e_c_T", "e_u_U")
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

    def __post_init__(self) -> None:
        if set(self.metrics) != set(SEED_METRICS):
            raise ValueError(f"metrics must have exactly keys {SEED_METRICS}")
        if not all(isinstance(v, MetricValue) for v in self.metrics.values()):
            raise ValueError("metrics must be MetricValues")

    @property
    def ok(self) -> bool:
        return all(self.metrics[k].is_measured for k in _PRIMARY_SERIES)

    @classmethod
    def failed(cls, seed: int, reason: str, rowsets_disjoint=None, mask_ok=None) -> "SeedScores":
        return cls(seed, {k: MetricValue.unmeasured(reason) for k in SEED_METRICS}, rowsets_disjoint, mask_ok)

    @classmethod
    def from_values(cls, seed: int, S: float, L: float, delta: float, delta_minus_shuf: float,
                    S_U: Optional[float] = None, G: Optional[float] = None, rowsets_disjoint=None, mask_ok=None
                    ) -> "SeedScores":
        na = MetricValue.unmeasured("not supplied")
        m = {"S": _mv(S, "non-finite"), "L": _mv(L, "non-finite"), "delta": _mv(delta, "non-finite"),
             "delta_minus_shuf": _mv(delta_minus_shuf, "non-finite"),
             "S_U": _mv(S_U, "not supplied") if S_U is not None else na,
             "G": _mv(G, "not supplied") if G is not None else na, "e_c_T": na, "e_u_U": na}
        return cls(seed, m, rowsets_disjoint, mask_ok)


def score_seed(seed: int, treatment: PredictorFactory, cfg: BenchmarkConfig) -> SeedScores:
    """Score one replicate: treatment vs C0, plus delta_E - delta_Cshuf (C_shuf scored vs C0 the same way)."""
    try:
        fx = build_fixture(seed, cfg)
    except ValueError as e:
        return SeedScores.failed(seed, f"fixture build failed: {e}")
    try:
        c0 = ARM_FACTORIES["C0"](fx, cfg)
        sh = ARM_FACTORIES["C_shuf"](fx, cfg)
        a = score_predictor(fx, treatment(fx, cfg), c0, cfg.g_min)
        b = score_predictor(fx, sh, c0, cfg.g_min)
    except ValueError as e:   # train() divergence etc.: counted, never hidden
        return SeedScores.failed(seed, f"numerical failure: {e}", fx.disjoint, fx.mask_ok)
    dms = (MetricValue.measured(a.delta.value - b.delta.value) if a.delta.is_measured and b.delta.is_measured
           else MetricValue.unmeasured("treatment or C_shuf contrast unmeasured"))
    return SeedScores(seed, {"S": a.S, "L": a.L, "S_U": a.S_U, "delta": a.delta, "delta_minus_shuf": dms,
                             "G": MetricValue.measured(float(fx.G)), "e_c_T": a.e_c_T, "e_u_U": a.e_u_U},
                      fx.disjoint, fx.mask_ok)


# ================================================================== gates
@dataclasses.dataclass(frozen=True)
class GateResult:
    name: str
    passed: bool
    reason: str


def evaluate_gates(scores: Sequence[SeedScores], frozen: FrozenSeedList, registered_digest: Optional[str],
                   cfg: BenchmarkConfig) -> tuple:
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
    return tuple(gates)


# ================================================================== joint
@dataclasses.dataclass(frozen=True)
class JointResult:
    """The only container of verdicts. H1, H2 and H3 live together; the joint verdict is derived from
    them, so suppression cannot be reported without retention and selectivity."""
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
    deferred_gates: tuple = DEFERRED_GATES
    complete_gate_coverage: bool = False   # always False in SR-10: see module docstring

    def __post_init__(self) -> None:
        for h, hid in ((self.h1, "H1"), (self.h2, "H2"), (self.h3, "H3")):
            if not isinstance(h, HypothesisResult) or h.hid != hid:
                raise ValueError(f"JointResult needs HypothesisResult {hid} in its slot")

    @property
    def gates_ok(self) -> bool:
        return all(g.passed for g in self.gates)

    @property
    def verdict(self) -> JointVerdict:
        return combine_joint(self.h1.verdict, self.h2.verdict, self.h3.verdict, self.gates_ok)


def analyze_scores(scores: Sequence[SeedScores], *, frozen: FrozenSeedList, registered_digest: Optional[str],
                   subject: str, ineligible: Sequence[int] = (), cfg: BenchmarkConfig = BenchmarkConfig(),
                   margins: Margins = Margins()) -> JointResult:
    scores = tuple(scores)
    gates = evaluate_gates(scores, frozen, registered_digest, cfg)
    failing = [f"{g.name} ({g.reason})" for g in gates if not g.passed]
    series = {k: [s.metrics[k].value for s in scores if s.ok] for k in _PRIMARY_SERIES}
    hs = [evaluate_primary(h, series, margins, cfg, frozen.base_seed, failing) for h in ("H1", "H2", "H3")]
    return JointResult(subject, hs[0], hs[1], hs[2], gates, scores, tuple(ineligible), len(scores),
                       sum(not s.ok for s in scores), frozen.digest, registered_digest, cfg.config_hash(), margins)


def run_study(frozen: FrozenSeedList, treatment: PredictorFactory, *, subject: str,
              registered_digest: Optional[str], cfg: BenchmarkConfig = BenchmarkConfig(),
              margins: Margins = Margins()) -> JointResult:
    """Walk the frozen seed list in order, skip ineligible seeds (G_s < g_min, a teacher-only criterion;
    they are listed, replaced from the reserve in order), score until n_planned seeds are attempted."""
    scores, skipped = [], []
    for s in frozen.seeds:
        if len(scores) >= frozen.n_planned:
            break
        try:
            if build_fixture(s, cfg).G < cfg.g_min:
                skipped.append(s)
                continue
        except ValueError:
            pass   # fixture failure is scored as a failed run by score_seed, never dropped
        scores.append(score_seed(s, treatment, cfg))
    return analyze_scores(scores, frozen=frozen, registered_digest=registered_digest, subject=subject,
                          ineligible=skipped, cfg=cfg, margins=margins)


# ============================================================== records
def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _agg_metrics(pair: IntervalPair, margin: Optional[float], n_failed: int) -> dict:
    m = {"mean": pair.mean, "sd": pair.sd, "iqr": pair.iqr, "min": pair.minimum, "max": pair.maximum,
         "max_over_median_abs": pair.max_over_median_abs,
         "ci_boot_lo": pair.boot_lo, "ci_boot_hi": pair.boot_hi, "ci_t_lo": pair.t_lo, "ci_t_hi": pair.t_hi,
         "n_seeds": MetricValue.measured(float(pair.n)), "n_failed": MetricValue.measured(float(n_failed)),
         "ci_level": MetricValue.measured(float(pair.level))}
    m["margin"] = (MetricValue.measured(float(margin)) if margin is not None
                   else MetricValue.unmeasured("exploratory: no margin"))
    return m


def to_experiment_records(res: JointResult, *, study_id: str, base_seed: int, timestamp_utc: Optional[str] = None,
                          code_version: str = CODE_VERSION, scorer_validation: bool = False) -> list:
    """Serialise onto ExperimentRecord (always EvidenceClass.TOY_RESULT for measured data; SOURCE_OBSERVED
    is rejected by the schema). The structured verdict lives in `res`; the verdict text in `notes` is a
    serialisation fallback only and must not be parsed or treated as evidence."""
    ts = timestamp_utc or _now()
    kind = ("SCORER-VALIDATION FIXTURE (a test of the scorer, not a result about any method)"
            if scorer_validation else "toy fixture")
    hashes = {"seed_list": res.seed_list_digest, "config": res.config_hash}
    if res.registered_digest is not None:
        hashes["registered_seed_list"] = res.registered_digest

    def prov(run_id: str, seed: int) -> RunProvenance:
        return RunProvenance(run_id=run_id, timestamp_utc=ts, seed=seed, code_version=code_version,
                             python_version=current_python_version(), toy_only=True, input_hashes=hashes)

    recs = []
    for h in (res.h1, res.h2, res.h3):
        for c in h.components:
            tag = h.hid if len(h.components) == 1 else h.hid + ("a" if c.metric == "delta" else "b")
            ec = EvidenceClass.TOY_RESULT if c.pair.mean.is_measured else EvidenceClass.UNKNOWN
            recs.append(ExperimentRecord(
                name=f"evalproto/{study_id}/agg/{tag}", provenance=prov(f"{study_id}-agg-{tag}", base_seed),
                metrics=_agg_metrics(c.pair, c.margin, res.n_failed), evidence_class=ec,
                notes=f"{TOY_LABEL} PRIMARY {h.hid} [{kind}] subject={res.subject}; component verdict "
                      f"{c.verdict.value}; hypothesis verdict {h.verdict.value} (serialisation fallback; "
                      f"structured verdict is in JointResult; not evidence). Flags: {list(c.pair.flags)}"))
    recs.append(ExperimentRecord(
        name=f"evalproto/{study_id}/agg/JOINT", provenance=prov(f"{study_id}-agg-JOINT", base_seed),
        metrics={"n_seeds": MetricValue.measured(float(res.n_attempted - res.n_failed)),
                 "n_failed": MetricValue.measured(float(res.n_failed))},
        evidence_class=EvidenceClass.TOY_RESULT,
        notes=f"{TOY_LABEL} [{kind}] subject={res.subject}; joint verdict {res.verdict.value} (serialisation "
              f"fallback; not evidence). Gates failed: {[g.name for g in res.gates if not g.passed]}. "
              f"Deferred (unimplemented) gates: {list(res.deferred_gates)}; a JOINT_SUPPORTED here is "
              f"conditional on them."))
    return recs


def seed_records(res: JointResult, *, study_id: str, timestamp_utc: Optional[str] = None,
                 code_version: str = CODE_VERSION) -> list:
    """One ExperimentRecord per scored seed. Unmeasured metrics stay MetricValue.unmeasured."""
    ts = timestamp_utc or _now()
    hashes = {"seed_list": res.seed_list_digest, "config": res.config_hash}
    out = []
    for s in res.seed_scores:
        out.append(ExperimentRecord(
            name=f"evalproto/{study_id}/{res.subject}/seed",
            provenance=RunProvenance(run_id=f"{study_id}-{res.subject}-{s.seed}", timestamp_utc=ts, seed=s.seed,
                                     code_version=code_version, python_version=current_python_version(),
                                     toy_only=True, input_hashes=hashes),
            metrics=dict(s.metrics),
            evidence_class=EvidenceClass.TOY_RESULT if s.ok else EvidenceClass.UNKNOWN,
            notes=f"{TOY_LABEL} per-seed values; PRIMARY inputs; no verdict at this level."))
    return out
