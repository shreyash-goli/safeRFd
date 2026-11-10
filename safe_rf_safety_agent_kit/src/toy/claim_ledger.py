"""SR-14: human review of claims with an append-only, hash-chained audit log.

TOY module. Standard library only. Nothing here asserts that anything is safe.
A claim reaching SUPPORTED means ONLY that a named human reviewer recorded that
the referenced evidence supports the claim as worded. It is not a safety result,
and it never changes the claim's evidence class.

Why this exists: `ExperimentRecord` has no structured verdict field, and its
free-text fields (`name`, `notes`) can carry claim-like strings such as
"verdict: JOINT_SUPPORTED". Here a claim's status is structured, reviewable
data. Prose in a justification or statement is stored but NEVER parsed for status.

States and transitions (the complete table; everything else is rejected):

    (new)      --OPEN-->     DRAFT
    DRAFT      --REVIEW-->   REVIEWED
    REVIEWED   --SUPPORT-->  SUPPORTED     (>= 1 evidence reference REQUIRED)
    REVIEWED   --REJECT-->   UNSUPPORTED
    SUPPORTED  --RETRACT-->  UNSUPPORTED   (explicit named retraction on new evidence)

Terminal-state decision: UNSUPPORTED is truly terminal. SUPPORTED is terminal
except for the one named RETRACT transition, which carries its own action name
and a mandatory justification, so a retraction can never pass as an ordinary
edit. There is no way back from UNSUPPORTED: a new claim id must be opened
instead (re-litigating a rejected claim should be a visible new claim). There is
no SUPPORTED -> REVIEWED or any other backwards step. Skipping REVIEWED, self
transitions and wrong action names are rejected.

Human review: every event carries a reviewer identity, a UTC timestamp and a
non-empty justification. Reviewer identity is a self-asserted string: this
module does not authenticate it and does not enforce a four-eyes rule. Nothing
in the kit auto-advances a claim; the only way to change state is `append` (or
a wrapper) with explicit reviewer-supplied fields.

SUPPORTED without evidence is structurally impossible: the transition table
entry for SUPPORT has `needs_evidence=True`, and the check lives in the single
function (`_validate_and_build`) that every append AND every load/verify replay
goes through. A forged file containing a SUPPORT event with no evidence refs is
therefore rejected on load, even if its hashes were recomputed. Evidence refs
are `content_hash` (e.g. `ExperimentRecord.content_hash()`) or `checkpoint_digest`
sha256 values. They are NOT resolved offline: the ledger checks their shape (and
membership of `known_evidence` if the ledger was constructed with one), not that
the referenced thing exists or is good.

Idempotency: re-submitting an event with the same event id AND identical content
(everything except seq/prev_digest/digest) is a no-op returning the existing
event (`AppendResult.appended is False`). The same event id with different
content raises `DuplicateEventIdError`. Because the timestamp is content, a
retry must reuse the original timestamp (pin it) or it is a conflict.

Hash chain: each event stores `prev_digest` and `digest = sha256(canonical_json(
event without digest))`. `verify_chain()` names the first broken link (index,
event id, reason). HONEST LIMIT: this detects accidental corruption and naive
tampering (editing, deleting or reordering events without recomputing). It is
NOT a signature or MAC and there is no secret key. Anyone who can rewrite the
entire file can recompute every digest and the loader will accept it, provided
the rewritten history is itself a valid sequence of transitions (semantic
replay still rejects impossible histories such as a SUPPORT with no evidence).
It does not authenticate reviewers and cannot detect truncation of the tail.
To pin the history, store `head_digest` through a separate trusted channel.

Honest limits of what the ledger guarantees (read before relying on it):
- Self-verification is opt-out, not absent: `append`, `claim_state()` and `summary()`
  run `verify_chain()` first and raise `ChainIntegrityError` on a tampered in-memory
  ledger (`summary(verify=False)` is a forensic escape hatch). Any OTHER renderer that
  reads `events` directly must call `verify_chain()` or go through `load_ledger` itself.
- Evidence is checked for SHAPE only and review is SELF-ATTESTED. A single reviewer can
  OPEN, REVIEW and SUPPORT a claim citing `sha256(b"nothing at all")` and it will reach
  SUPPORTED. That is the main route to a hollow SUPPORTED. There is no four-eyes rule,
  and `known_evidence` (which would at least require refs to be registered) is OPT-IN and
  OFF by default. A SUPPORTED state therefore proves a reviewer clicked, not that the
  evidence is real or sufficient.
- Future-dated events: per-claim timestamps may not go backwards, so one event dated far
  in the future would brick the claim. `append` therefore rejects timestamps more than
  `max_future_skew_seconds` (default 86400) ahead of the ledger clock
  (`TimestampFutureError`). The bound is applied at append time only; a loaded file is
  verified for ordering, not against today's clock.
- Tail truncation: removing the last N events leaves a valid prefix chain. `load_ledger`
  catches it only because the file's own `head_digest` no longer matches; an attacker who
  also fixes `head_digest` (e.g. erasing a RETRACT so the claim reverts to SUPPORTED) is
  accepted. `head_digest` MUST be pinned out of band (compare the value returned by
  `save_ledger` against a trusted channel) for truncation to be detectable.
- Timestamp is part of an event's content, so a retry with a different timestamp is a
  conflict, not a replay. A caller retrying must reuse the first `timestamp_utc`
  (`AppendResult.event.timestamp_utc`, and `DuplicateEventIdError.original_timestamp_utc`
  report it). Evidence-ref ORDER is content too: the same refs in another order conflict.
  Both are strict and fail closed on purpose.
- Operator workflow: UNSUPPORTED is terminal, so a mistaken REJECT cannot be corrected in
  place (an un-reject would make a REJECT quietly undoable). Open a NEW claim id whose
  statement/justification cites the old claim id and the REJECT event id.
- The AST import check in the tests is an ALLOWLIST of this module's imports plus a ban on
  eval/exec/__import__ names. Still hygiene, not proof (it cannot see what an allowed
  module does, e.g. `os.system`).

Evidence class vs. state: `ClaimState` is not an `EvidenceClass`. A claim's
evidence class is fixed at OPEN and never changes; SUPPORTED never relabels
anything SOURCE_OBSERVED. `summary()` returns structured dicts for the dashboard
(no free-text verdict strings); a SUPPORTED TOY_RESULT claim stays marked toy.

Persistence: canonical JSON via `toy.schema.canonical_json`, atomic write
(tmp file + fsync + os.replace), strict load (size cap, duplicate keys, NaN,
exact key set, canonical-byte check, full chain and semantic re-verification).
No pickle or other object deserialisation is used; a test scans this module's
source for banned imports. That AST deny-list is hygiene, not proof.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Iterable, Optional, Sequence

from toy.schema import EvidenceClass, TOY_LABEL, canonical_json

FORMAT_VERSION = 1
SUPPORTED_FORMAT_VERSIONS = (1,)
LEDGER_LABEL = ("CLAIM LEDGER (human review audit log; a claim state is not an evidence class "
                "and asserts nothing about safety)")
GENESIS_DIGEST = "0" * 64
MAX_LEDGER_BYTES = 8 << 20
MAX_JUSTIFICATION = 10_000
MAX_STATEMENT = 2_000
MAX_REVIEWER = 200
DEFAULT_MAX_FUTURE_SKEW_SECONDS = 86_400
EVIDENCE_KINDS = ("content_hash", "checkpoint_digest")
SUMMARY_CAVEAT = ("A review verdict recorded by a named human about referenced evidence. "
                  "Not a safety claim; no evidence class was changed by it.")

_TS_RE = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", re.ASCII)
_HEX_RE = re.compile(r"[0-9a-f]{64}", re.ASCII)
_ID_RE = re.compile(r"[A-Za-z0-9._:\-]{1,128}", re.ASCII)
_CTRL_RE = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")  # control chars other than \t and \n


# ------------------------------------------------------------- exceptions
class ClaimLedgerError(ValueError):
    """Base class for every ledger failure."""


class EventFormatError(ClaimLedgerError):
    """A field has the wrong type/shape."""


class InvalidTransitionError(ClaimLedgerError):
    """(from_state, to_state, action) is not in the transition table."""


class StateMismatchError(ClaimLedgerError):
    """Claimed from_state differs from the claim's actual current state (forged/stale)."""


class UnknownClaimError(ClaimLedgerError):
    """A non-OPEN event for a claim id that has no OPEN event."""


class ClaimExistsError(ClaimLedgerError):
    """OPEN for a claim id that already exists."""


class MissingJustificationError(ClaimLedgerError):
    """Justification is empty or whitespace."""


class MissingEvidenceError(ClaimLedgerError):
    """SUPPORT without any evidence reference."""


class UnknownEvidenceError(ClaimLedgerError):
    """Evidence ref not in the ledger's `known_evidence` set."""


class TimestampOrderError(ClaimLedgerError):
    """Event timestamp is earlier than the claim's previous event."""


class TimestampFutureError(ClaimLedgerError):
    """Event timestamp is further in the future than the allowed skew (would brick the claim)."""


class DuplicateEventIdError(ClaimLedgerError):
    """Same event id reused with different content. `original_timestamp_utc` is the timestamp
    of the event already stored under that id (a retrying caller must reuse it)."""

    def __init__(self, message: str, original_timestamp_utc: Optional[str] = None):
        super().__init__(message)
        self.original_timestamp_utc = original_timestamp_utc


class ChainIntegrityError(ClaimLedgerError):
    """Hash chain or replay verification failed; `.result` is the ChainVerification."""

    def __init__(self, message: str, result: "ChainVerification | None" = None):
        super().__init__(message)
        self.result = result


class LedgerFormatError(ClaimLedgerError):
    """File-level problem: empty, oversize, not UTF-8/JSON, non-canonical, duplicate keys."""


class LedgerKeyError(LedgerFormatError):
    """Unknown or missing top-level / event keys."""


class LedgerVersionError(LedgerFormatError):
    """Unsupported format_version."""


# ------------------------------------------------------------------ states
class ClaimState(str, Enum):
    DRAFT = "DRAFT"
    REVIEWED = "REVIEWED"
    SUPPORTED = "SUPPORTED"
    UNSUPPORTED = "UNSUPPORTED"


class Action(str, Enum):
    OPEN = "OPEN"
    REVIEW = "REVIEW"
    SUPPORT = "SUPPORT"
    REJECT = "REJECT"
    RETRACT = "RETRACT"


@dataclass(frozen=True)
class _Rule:
    needs_evidence: bool


# (from_state, to_state) -> (action, rule). from_state None means "claim does not exist yet".
TRANSITIONS: dict = {
    (None, ClaimState.DRAFT): (Action.OPEN, _Rule(False)),
    (ClaimState.DRAFT, ClaimState.REVIEWED): (Action.REVIEW, _Rule(False)),
    (ClaimState.REVIEWED, ClaimState.SUPPORTED): (Action.SUPPORT, _Rule(True)),
    (ClaimState.REVIEWED, ClaimState.UNSUPPORTED): (Action.REJECT, _Rule(False)),
    (ClaimState.SUPPORTED, ClaimState.UNSUPPORTED): (Action.RETRACT, _Rule(False)),
}

STATE_LABELS = {
    ClaimState.DRAFT: "DRAFT (unreviewed; not a finding)",
    ClaimState.REVIEWED: "REVIEWED (inspected by a human; no verdict yet)",
    ClaimState.SUPPORTED: "SUPPORTED (human review verdict, conditional on the referenced evidence)",
    ClaimState.UNSUPPORTED: "UNSUPPORTED (rejected or retracted)",
}


# ------------------------------------------------------------- value types
@dataclass(frozen=True)
class EvidenceRef:
    kind: str
    value: str

    def __post_init__(self):
        if self.kind not in EVIDENCE_KINDS:
            raise EventFormatError(f"evidence kind must be one of {list(EVIDENCE_KINDS)}, got {self.kind!r}")
        if not isinstance(self.value, str) or not _HEX_RE.fullmatch(self.value):
            raise EventFormatError("evidence value must be a lowercase 64-char sha256 hex string")
        if self.value == GENESIS_DIGEST:
            raise EventFormatError("evidence value must not be the all-zero placeholder digest")

    def to_dict(self) -> dict:
        return {"kind": self.kind, "value": self.value}


def evidence_from_record(record: Any) -> EvidenceRef:
    """Reference an `ExperimentRecord` by its content hash."""
    return EvidenceRef("content_hash", record.content_hash())


def _parse_class(v: Any) -> EvidenceClass:
    try:
        return EvidenceClass.parse(v)
    except (ValueError, TypeError) as e:
        raise EventFormatError(f"invalid evidence_class: {e}") from None


def _now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _text(name: str, v: Any, limit: int) -> str:
    if not isinstance(v, str):
        raise EventFormatError(f"{name} must be a string, got {type(v).__name__}")
    if len(v) > limit:
        raise EventFormatError(f"{name} longer than {limit} characters")
    if _CTRL_RE.search(v):
        raise EventFormatError(f"{name} contains control characters")
    return v


def _ident(name: str, v: Any) -> str:
    if not isinstance(v, str) or not _ID_RE.fullmatch(v):
        raise EventFormatError(f"{name} must match [A-Za-z0-9._:-]{{1,128}}, got {v!r}")
    return v


def _ts(v: Any) -> str:
    if not isinstance(v, str) or not _TS_RE.fullmatch(v):
        raise EventFormatError(f"timestamp_utc must match YYYY-MM-DDTHH:MM:SSZ, got {v!r}")
    try:
        datetime.strptime(v, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        raise EventFormatError(f"timestamp_utc is not a real date/time: {v!r}") from None
    return v


def _refs(v: Any) -> tuple:
    if not isinstance(v, (list, tuple)):  # not dict/set/str/generator: order is content
        raise EventFormatError("evidence_refs must be a list or tuple of EvidenceRef")
    out = []
    for r in v:
        if isinstance(r, dict):
            if set(r) != {"kind", "value"}:
                raise EventFormatError("evidence ref must have exactly keys kind, value")
            r = EvidenceRef(r["kind"], r["value"])
        if not isinstance(r, EvidenceRef):
            raise EventFormatError(f"evidence_refs entries must be EvidenceRef, got {type(r).__name__}")
        # re-run validation even on EvidenceRef objects built via object.__new__/setattr tricks
        try:
            EvidenceRef(r.kind, r.value)
        except AttributeError:
            raise EventFormatError("malformed EvidenceRef object") from None
        if r in out:
            raise EventFormatError(f"duplicate evidence ref {r.value}")
        out.append(r)
    return tuple(out)


@dataclass(frozen=True)
class EventRequest:
    """What a reviewer supplies. Everything is explicit; nothing is inferred or defaulted
    except the timestamp (real UTC now, unless pinned)."""
    event_id: str
    claim_id: str
    action: Any
    from_state: Any
    to_state: Any
    reviewer: str
    justification: str
    evidence_refs: Sequence = ()
    timestamp_utc: Optional[str] = None
    evidence_class: Any = None   # OPEN only
    statement: Optional[str] = None  # OPEN only


@dataclass(frozen=True)
class LedgerEvent:
    seq: int
    event_id: str
    claim_id: str
    action: Action
    from_state: Optional[ClaimState]
    to_state: ClaimState
    reviewer: str
    timestamp_utc: str
    justification: str
    evidence_refs: tuple
    evidence_class: Optional[EvidenceClass]
    statement: Optional[str]
    prev_digest: str
    digest: str

    def content_dict(self) -> dict:
        """The request-level content used for idempotency (no seq/prev_digest/digest)."""
        return {
            "event_id": self.event_id, "claim_id": self.claim_id, "action": self.action.value,
            "from_state": self.from_state.value if self.from_state else None,
            "to_state": self.to_state.value, "reviewer": self.reviewer,
            "timestamp_utc": self.timestamp_utc, "justification": self.justification,
            "evidence_refs": [r.to_dict() for r in self.evidence_refs],
            "evidence_class": self.evidence_class.value if self.evidence_class else None,
            "statement": self.statement,
        }

    def payload_dict(self) -> dict:
        """Digest-covered object: every key except `digest`."""
        return {**self.content_dict(), "seq": self.seq, "prev_digest": self.prev_digest}

    def to_dict(self) -> dict:
        return {**self.payload_dict(), "digest": self.digest}

    def compute_digest(self) -> str:
        return _digest(self.payload_dict())

    @classmethod
    def from_dict(cls, d: Any) -> "LedgerEvent":
        """Schema-validate one event dict. Does NOT check hashes (see verify_events)."""
        if not isinstance(d, dict):
            raise LedgerFormatError(f"event must be an object, got {type(d).__name__}")
        expected = set(_EVENT_KEYS)
        if set(d) != expected:
            raise LedgerKeyError(f"event key mismatch: unknown {sorted(set(d) - expected)}, "
                                 f"missing {sorted(expected - set(d))}")
        seq = d["seq"]
        if isinstance(seq, bool) or not isinstance(seq, int) or seq < 0:
            raise EventFormatError("seq must be a non-negative int")
        try:
            action = Action(d["action"])
            to_state = ClaimState(d["to_state"])
            from_state = None if d["from_state"] is None else ClaimState(d["from_state"])
        except (ValueError, TypeError):
            raise EventFormatError("unknown action/state value in event") from None
        ec = d["evidence_class"]
        evidence_class = None if ec is None else _parse_class(ec)
        for k in ("prev_digest", "digest"):
            if not isinstance(d[k], str) or not _HEX_RE.fullmatch(d[k]):
                raise EventFormatError(f"{k} must be a lowercase 64-char sha256 hex string")
        stmt = d["statement"]
        if stmt is not None:
            stmt = _text("statement", stmt, MAX_STATEMENT)
        return cls(seq, _ident("event_id", d["event_id"]), _ident("claim_id", d["claim_id"]), action,
                   from_state, to_state, _text("reviewer", d["reviewer"], MAX_REVIEWER),
                   _ts(d["timestamp_utc"]), _text("justification", d["justification"], MAX_JUSTIFICATION),
                   _refs(d["evidence_refs"]), evidence_class, stmt, d["prev_digest"], d["digest"])


_EVENT_KEYS = ("seq", "event_id", "claim_id", "action", "from_state", "to_state", "reviewer",
               "timestamp_utc", "justification", "evidence_refs", "evidence_class", "statement",
               "prev_digest", "digest")


def _digest(payload: dict) -> str:
    if "digest" in payload:
        raise ClaimLedgerError("payload must not contain a digest field")
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class AppendResult:
    appended: bool          # False for an idempotent no-op replay
    event: LedgerEvent


@dataclass(frozen=True)
class ChainVerification:
    ok: bool
    events_checked: int
    first_broken_index: Optional[int] = None
    first_broken_event_id: Optional[str] = None
    reason: Optional[str] = None   # prev_digest_mismatch | digest_mismatch | seq_mismatch |
    #                                invalid_event | <semantic error class name>
    detail: Optional[str] = None


# ------------------------------------------------- the one validation path
def _validate_and_build(req: EventRequest, prior: Sequence[LedgerEvent],
                        claim_state: dict, claim_last_ts: dict,
                        known_evidence: Optional[frozenset]) -> dict:
    """Validate a request against current state and return the event's content dict.
    Used by BOTH append and replay verification, so loading a file cannot bypass a rule."""
    event_id = _ident("event_id", req.event_id)
    claim_id = _ident("claim_id", req.claim_id)
    try:
        action = Action(req.action)
        to_state = ClaimState(req.to_state)
        from_state = None if req.from_state is None else ClaimState(req.from_state)
    except (ValueError, TypeError):
        raise EventFormatError("unknown action/state value") from None
    reviewer = _text("reviewer", req.reviewer, MAX_REVIEWER)
    if not reviewer.strip():
        raise EventFormatError("reviewer identity must be non-empty")
    justification = _text("justification", req.justification, MAX_JUSTIFICATION)
    refs = _refs(req.evidence_refs)
    ts = _ts(req.timestamp_utc)

    entry = TRANSITIONS.get((from_state, to_state))
    if entry is None or entry[0] is not action:
        raise InvalidTransitionError(
            f"transition {from_state.value if from_state else '(new)'} -> {to_state.value} via "
            f"{action.value} is not allowed")
    rule = entry[1]

    current = claim_state.get(claim_id)
    if action is Action.OPEN:
        if current is not None:
            raise ClaimExistsError(f"claim {claim_id!r} already exists in state {current.value}")
    else:
        if current is None:
            raise UnknownClaimError(f"claim {claim_id!r} has no OPEN event")
        if current is not from_state:
            raise StateMismatchError(
                f"event says from_state={from_state.value} but claim {claim_id!r} is {current.value}")

    if action is Action.OPEN:
        if req.evidence_class is None:
            raise EventFormatError("OPEN requires evidence_class")
        evidence_class = _parse_class(req.evidence_class)
        if not isinstance(req.statement, str) or not req.statement.strip():
            raise EventFormatError("OPEN requires a non-empty statement")
        statement = _text("statement", req.statement, MAX_STATEMENT)
    else:
        if req.evidence_class is not None or req.statement is not None:
            raise EventFormatError("evidence_class/statement may only be set on OPEN (fixed per claim)")
        evidence_class, statement = None, None

    if not justification.strip():
        raise MissingJustificationError(f"{action.value} requires a non-empty justification")
    if rule.needs_evidence and not refs:
        raise MissingEvidenceError(f"{action.value} requires at least one evidence reference")
    if known_evidence is not None:
        for r in refs:
            if r.value not in known_evidence:
                raise UnknownEvidenceError(f"evidence {r.value} is not in this ledger's known_evidence")
    last = claim_last_ts.get(claim_id)
    if last is not None and ts < last:
        raise TimestampOrderError(f"timestamp {ts} is earlier than claim's previous event {last}")

    return {
        "event_id": event_id, "claim_id": claim_id, "action": action.value,
        "from_state": from_state.value if from_state else None, "to_state": to_state.value,
        "reviewer": reviewer, "timestamp_utc": ts, "justification": justification,
        "evidence_refs": [r.to_dict() for r in refs],
        "evidence_class": evidence_class.value if evidence_class else None, "statement": statement,
    }


def _request_from_event(e: LedgerEvent) -> EventRequest:
    return EventRequest(e.event_id, e.claim_id, e.action, e.from_state, e.to_state, e.reviewer,
                        e.justification, e.evidence_refs, e.timestamp_utc,
                        e.evidence_class, e.statement)


def verify_events(events: Sequence[LedgerEvent],
                  known_evidence: Optional[frozenset] = None) -> ChainVerification:
    """Verify hash links, sequence numbers AND replay every transition through the same
    validation as `append`. Returns the first broken link; never raises for bad data."""
    prev = GENESIS_DIGEST
    states: dict = {}
    last_ts: dict = {}
    seen_ids: set = set()
    for i, e in enumerate(events):
        def bad(reason, detail=None):
            return ChainVerification(False, i, i, (e.event_id if isinstance(e, LedgerEvent) else None), reason, detail)
        try:
            if type(e.seq) is not int or e.seq != i:
                return bad("seq_mismatch", f"seq {e.seq} at index {i}")
            if e.prev_digest != prev:
                return bad("prev_digest_mismatch")
            if not hmac.compare_digest(e.digest, e.compute_digest()):
                return bad("digest_mismatch")
            if e.event_id in seen_ids:
                return bad("DuplicateEventIdError", f"event id {e.event_id!r} appears twice")
            content = _validate_and_build(_request_from_event(e), events[:i], states, last_ts, known_evidence)
            if content != e.content_dict():
                return bad("invalid_event", "stored content is not in normalised form")
        except ClaimLedgerError as ex:
            return bad(type(ex).__name__, str(ex))
        except (AttributeError, TypeError, ValueError) as ex:
            return bad("invalid_event", str(ex))
        seen_ids.add(e.event_id)
        states[e.claim_id] = e.to_state
        last_ts[e.claim_id] = e.timestamp_utc
        prev = e.digest
    return ChainVerification(True, len(events))


# ------------------------------------------------------------------ ledger
class ClaimLedger:
    """Append-only claim review log. `events` is an immutable tuple snapshot; there is no
    update/delete API. (Python cannot make memory truly immutable; `verify_chain()` exists
    precisely to catch in-process or on-disk tampering.)"""

    def __init__(self, *, known_evidence: Optional[Iterable[str]] = None,
                 max_future_skew_seconds: int = DEFAULT_MAX_FUTURE_SKEW_SECONDS,
                 clock: Optional[Callable[[], str]] = None):
        self._max_skew = max_future_skew_seconds
        self._clock = clock or _now_utc
        self._events: list = []
        self._ids: dict = {}
        self._states: dict = {}
        self._last_ts: dict = {}
        self._known = None if known_evidence is None else frozenset(known_evidence)

    # --- read side
    @property
    def events(self) -> tuple:
        return tuple(self._events)

    @property
    def head_digest(self) -> str:
        return self._events[-1].digest if self._events else GENESIS_DIGEST

    def __len__(self) -> int:
        return len(self._events)

    def __eq__(self, other: object) -> bool:
        return isinstance(other, ClaimLedger) and self._events == other._events

    __hash__ = None  # type: ignore[assignment]

    def _reindex(self) -> None:
        self._ids, self._states, self._last_ts = {}, {}, {}
        for e in self._events:
            self._ids[e.event_id] = e.seq
            self._states[e.claim_id] = e.to_state
            self._last_ts[e.claim_id] = e.timestamp_utc

    def _checked(self) -> None:
        """Fail closed: verify the whole chain and rebuild the derived caches from the events."""
        res = self.verify_chain()
        if not res.ok:
            raise ChainIntegrityError(
                f"ledger fails verification at index {res.first_broken_index} "
                f"({res.first_broken_event_id!r}): {res.reason}", res)
        self._reindex()

    def claim_state(self, claim_id: str) -> ClaimState:
        self._checked()
        try:
            return self._states[claim_id]
        except KeyError:
            raise UnknownClaimError(f"unknown claim {claim_id!r}") from None

    def claim_ids(self) -> tuple:
        return tuple(sorted(self._states))

    def verify_chain(self) -> ChainVerification:
        return verify_events(self._events, self._known)

    # --- write side
    def append(self, req: EventRequest) -> AppendResult:
        """Append one explicit reviewer event, or no-op on an identical replay.

        Same event_id + identical content -> AppendResult(False, existing).
        Same event_id + different content -> DuplicateEventIdError (never silently merged)."""
        if not isinstance(req, EventRequest):
            raise EventFormatError("append requires an EventRequest")
        self._checked()
        ts = req.timestamp_utc if req.timestamp_utc is not None else self._clock()
        req = EventRequest(req.event_id, req.claim_id, req.action, req.from_state, req.to_state,
                           req.reviewer, req.justification, req.evidence_refs, ts,
                           req.evidence_class, req.statement)
        eid = _ident("event_id", req.event_id)
        existing_idx = self._ids.get(eid)
        if existing_idx is not None:
            existing = self._events[existing_idx]
            # Normalise the replay the same way a fresh event would be, but skip state rules
            # (state has legitimately moved on since the original append).
            try:
                probe = EventRequest(eid, req.claim_id, req.action, req.from_state, req.to_state,
                                     req.reviewer, req.justification, req.evidence_refs, ts,
                                     req.evidence_class, req.statement)
                same = _replay_content(probe) == existing.content_dict()
            except ClaimLedgerError:
                same = False
            if same:
                return AppendResult(False, existing)
            raise DuplicateEventIdError(
                f"event id {eid!r} already used with different content; a retry must reuse the original "
                f"timestamp {existing.timestamp_utc} and evidence-ref order", existing.timestamp_utc)
        content = _validate_and_build(req, self._events, self._states, self._last_ts, self._known)
        limit = datetime.strptime(self._clock(), "%Y-%m-%dT%H:%M:%SZ").timestamp() + self._max_skew
        if datetime.strptime(content["timestamp_utc"], "%Y-%m-%dT%H:%M:%SZ").timestamp() > limit:
            raise TimestampFutureError(
                f"timestamp {content['timestamp_utc']} is more than {self._max_skew}s ahead of the ledger clock")
        payload = {**content, "seq": len(self._events), "prev_digest": self.head_digest}
        event = LedgerEvent.from_dict({**payload, "digest": _digest(payload)})
        self._events.append(event)
        self._ids[eid] = event.seq
        self._states[event.claim_id] = event.to_state
        self._last_ts[event.claim_id] = event.timestamp_utc
        return AppendResult(True, event)

    # Thin wrappers: every field is still reviewer-supplied; none infers a verdict.
    def open_claim(self, *, event_id, claim_id, reviewer, justification, statement,
                   evidence_class, timestamp_utc=None, evidence_refs=()) -> AppendResult:
        return self.append(EventRequest(event_id, claim_id, Action.OPEN, None, ClaimState.DRAFT, reviewer,
                                        justification, evidence_refs, timestamp_utc, evidence_class, statement))

    def review(self, *, event_id, claim_id, reviewer, justification, timestamp_utc=None,
               evidence_refs=()) -> AppendResult:
        return self._step(event_id, claim_id, Action.REVIEW, ClaimState.DRAFT, ClaimState.REVIEWED,
                          reviewer, justification, evidence_refs, timestamp_utc)

    def support(self, *, event_id, claim_id, reviewer, justification, evidence_refs,
                timestamp_utc=None) -> AppendResult:
        return self._step(event_id, claim_id, Action.SUPPORT, ClaimState.REVIEWED, ClaimState.SUPPORTED,
                          reviewer, justification, evidence_refs, timestamp_utc)

    def reject(self, *, event_id, claim_id, reviewer, justification, timestamp_utc=None,
               evidence_refs=()) -> AppendResult:
        return self._step(event_id, claim_id, Action.REJECT, ClaimState.REVIEWED, ClaimState.UNSUPPORTED,
                          reviewer, justification, evidence_refs, timestamp_utc)

    def retract(self, *, event_id, claim_id, reviewer, justification, timestamp_utc=None,
                evidence_refs=()) -> AppendResult:
        return self._step(event_id, claim_id, Action.RETRACT, ClaimState.SUPPORTED, ClaimState.UNSUPPORTED,
                          reviewer, justification, evidence_refs, timestamp_utc)

    def _step(self, event_id, claim_id, action, frm, to, reviewer, justification, refs, ts) -> AppendResult:
        return self.append(EventRequest(event_id, claim_id, action, frm, to, reviewer, justification,
                                        refs, ts))

    # --- derived summary for renderers
    def summary(self, *, verify: bool = True) -> list:
        """Structured, JSON-able per-claim summaries derived by replay. Status comes only
        from the state machine, never from any text field. By default the chain is verified
        first and a tampered ledger raises ChainIntegrityError instead of rendering."""
        if verify:
            self._checked()
        out = []
        for cid in self.claim_ids():
            evs = [e for e in self._events if e.claim_id == cid]
            opened = evs[0]
            state = evs[-1].to_state
            ec = opened.evidence_class
            support = next((e for e in reversed(evs) if e.action is Action.SUPPORT), None)
            retracted = any(e.action is Action.RETRACT for e in evs)
            is_toy = ec is EvidenceClass.TOY_RESULT
            label = STATE_LABELS[state]
            if state is ClaimState.SUPPORTED and is_toy:
                label = "SUPPORTED (TOY claim; human review verdict; not a safety claim)"
            out.append({
                "claim_id": cid,
                "state": state.value,
                "state_label": label,
                "evidence_class": ec.value,
                "is_toy": is_toy,
                "toy_label": TOY_LABEL if is_toy else None,
                "human_reviewed": state is not ClaimState.DRAFT,
                "retracted": retracted,
                "supporting_evidence": ([r.to_dict() for r in support.evidence_refs]
                                        if support is not None and state is ClaimState.SUPPORTED else []),
                "reviewers": sorted({e.reviewer for e in evs if e.action is not Action.OPEN}),
                "event_count": len(evs),
                "last_event_digest": evs[-1].digest,
                "last_event_utc": evs[-1].timestamp_utc,
                "statement": opened.statement,
                "statement_is_untrusted_text": True,
                "is_safety_claim": False,
                "caveat": SUMMARY_CAVEAT,
            })
        return out

    # --- persistence
    def to_dict(self) -> dict:
        return {"format_version": FORMAT_VERSION, "label": LEDGER_LABEL,
                "events": [e.to_dict() for e in self._events], "head_digest": self.head_digest}

    def to_json(self) -> str:
        return canonical_json(self.to_dict())

    @classmethod
    def from_dict(cls, data: Any, *, known_evidence: Optional[Iterable[str]] = None) -> "ClaimLedger":
        """Strictly validate and fully re-verify (hashes + every transition). Raises on any problem."""
        if not isinstance(data, dict):
            raise LedgerFormatError(f"top level must be an object, got {type(data).__name__}")
        expected = {"format_version", "label", "events", "head_digest"}
        if set(data) != expected:
            raise LedgerKeyError(f"top-level key mismatch: unknown {sorted(set(data) - expected)}, "
                                 f"missing {sorted(expected - set(data))}")
        v = data["format_version"]
        if isinstance(v, bool) or not isinstance(v, int) or v not in SUPPORTED_FORMAT_VERSIONS:
            raise LedgerVersionError(f"unsupported format_version {v!r}; supported {list(SUPPORTED_FORMAT_VERSIONS)}")
        if data["label"] != LEDGER_LABEL:
            raise LedgerFormatError(f"label must equal {LEDGER_LABEL!r}")
        if not isinstance(data["events"], list):
            raise LedgerFormatError("events must be a list")
        events = [LedgerEvent.from_dict(d) for d in data["events"]]
        ledger = cls(known_evidence=known_evidence)
        res = verify_events(events, ledger._known)
        if not res.ok:
            raise ChainIntegrityError(
                f"ledger verification failed at index {res.first_broken_index} "
                f"({res.first_broken_event_id!r}): {res.reason}", res)
        head = data["head_digest"]
        expected_head = events[-1].digest if events else GENESIS_DIGEST
        if not isinstance(head, str) or not hmac.compare_digest(head, expected_head):
            raise ChainIntegrityError("head_digest does not match the last event (tail truncated or edited)")
        ledger._events.extend(events)
        ledger._reindex()
        return ledger


def _enum(cls, v):
    try:
        return cls(v)
    except (ValueError, TypeError):
        raise EventFormatError(f"unknown {cls.__name__} value {v!r}") from None


def _replay_content(req: EventRequest) -> dict:
    """Normalised content of a request with no state rules applied (idempotency comparison)."""
    return LedgerEvent.from_dict({
        "event_id": req.event_id, "claim_id": req.claim_id,
        "action": _enum(Action, req.action).value,
        "from_state": None if req.from_state is None else _enum(ClaimState, req.from_state).value,
        "to_state": _enum(ClaimState, req.to_state).value, "reviewer": req.reviewer,
        "timestamp_utc": req.timestamp_utc, "justification": req.justification,
        "evidence_refs": [r.to_dict() for r in _refs(req.evidence_refs)],
        "evidence_class": None if req.evidence_class is None else _parse_class(req.evidence_class).value,
        "statement": req.statement, "seq": 0, "prev_digest": GENESIS_DIGEST, "digest": GENESIS_DIGEST,
    }).content_dict()


# ------------------------------------------------------------- file I/O
def save_ledger(path: str | os.PathLike, ledger: ClaimLedger) -> str:
    """Atomically write the ledger; returns its head digest. Refuses to write a ledger that
    does not verify."""
    res = ledger.verify_chain()
    if not res.ok:
        raise ChainIntegrityError(f"refusing to save a ledger that fails verification: {res.reason}", res)
    data = ledger.to_json().encode("utf-8")
    directory = os.path.dirname(os.path.abspath(os.fspath(path)))
    fd, tmp = tempfile.mkstemp(prefix=".toy_ledger_", suffix=".tmp", dir=directory)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, os.fspath(path))
    except BaseException:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass
        raise
    return ledger.head_digest


def _no_dupes(pairs):
    d = {}
    for k, v in pairs:
        if k in d:
            raise LedgerFormatError(f"duplicate JSON key {k!r}")
        d[k] = v
    return d


def _bad_const(name):
    raise LedgerFormatError(f"non-finite JSON constant {name} not allowed")


def load_ledger(path: str | os.PathLike, *, known_evidence: Optional[Iterable[str]] = None) -> ClaimLedger:
    """Read, strictly validate and fully re-verify a ledger file. Never executes anything."""
    with open(os.fspath(path), "rb") as f:
        raw = f.read(MAX_LEDGER_BYTES + 1)
    if not raw:
        raise LedgerFormatError("ledger file is empty")
    if len(raw) > MAX_LEDGER_BYTES:
        raise LedgerFormatError(f"ledger larger than {MAX_LEDGER_BYTES} bytes; refusing")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as e:
        raise LedgerFormatError(f"ledger is not valid UTF-8: {e}") from None
    try:
        data = json.loads(text, object_pairs_hook=_no_dupes, parse_constant=_bad_const)
    except ClaimLedgerError:
        raise
    except json.JSONDecodeError as e:
        raise LedgerFormatError(f"ledger is not valid JSON (truncated or corrupted?): {e}") from None
    except (RecursionError, ValueError) as e:
        raise LedgerFormatError(f"ledger JSON could not be parsed: {e}") from None
    ledger = ClaimLedger.from_dict(data, known_evidence=known_evidence)
    if canonical_json(data) != text:
        raise LedgerFormatError("file bytes are not in canonical form")
    return ledger
