"""SR-08: TOY checkpoint metadata, provenance hash and safe (non-executable) reload.

TOY module. Standard library only. Handles only small synthetic numeric
parameter vectors (for example `TrainResult.final_params` from
`toy.teacher_student`). It is not a protein model, handles no real weights, and
makes no claim about safety of anything.

Why this exists (audit context, SR-02 / ER-08; STATIC-ANALYSIS-ONLY facts about
the audited fork script, not re-executed here): the fork script saves with
`torch.save` (L474) and reloads with an unrestricted `torch.load` (L479),
records no hash, seed or data provenance, and stores student weights under
`student_model_state_dict` (S:461/S:481), while upstream reads
`self.ckpt['model_state_dict']` (A:model_runners.py:234). SOURCE OBSERVED: the
keys differ, so a checkpoint written by the script would not load into the
unmodified upstream sampler. INFERENCE, not executed: because upstream indexes
the dict directly (and loads with `strict=True`), the expected failure is a
loud `KeyError`, not a silent one. This module is a *toy-data counterpart* that shows the
contrasting properties (non-executable format, recorded provenance, verified
digest, strict key set). It does NOT fix, patch or validate anything in
RFdiffusion or in the audited script.

Format: UTF-8 canonical JSON (sorted keys, compact separators, ASCII-only,
no NaN/Infinity), with no trailing newline. The file is plain data. Loading never executes
code: no object deserialisation machinery is used (the source is checked by a
test to import none of the banned modules).

Top-level keys (the EXACT set; anything else is rejected):
  format_version  int, currently 1
  label           the TOY label string from toy.schema
  created_utc     YYYY-MM-DDTHH:MM:SSZ; real UTC time by default, or pinned by
                  the caller for a reproducible file/digest (same convention as
                  `teacher_student.train`)
  provenance      a `RunProvenance.to_dict()` record
  params          list of finite floats (the toy parameters)
  digest          lowercase sha256 hex, see below

Digest coverage (exact): sha256 over the UTF-8 bytes of the canonical JSON
serialisation of the object containing ALL top-level keys EXCEPT `digest`, i.e.
format_version, label, created_utc, provenance (every field, including
input_hashes) and params. The digest field itself is the only thing not
covered. Additionally the loader requires the whole file to be byte-for-byte the
canonical serialisation of what it parsed, so whitespace, key order, number
spelling, escape-case or trailing-byte changes that would parse to the same
content are rejected too. Net effect: any single-byte change to the file is
detected (tested exhaustively on a sample file).

Key-set guard: the loader fails loudly on any unknown or missing top-level key.
This is the generic analogue of the audited key incompatibility
(`student_model_state_dict` vs `model_state_dict`, see the module docstring
head; that failure is inferred, not executed, to be a loud KeyError): here a
producer and consumer that disagree on key names get an error naming both the
unknown and the missing keys, not a quiet partial load.

Float fidelity: Python's `json` writes floats with `repr` (shortest string that
round-trips) and parses them exactly, so -0.0, subnormals (5e-324) and large
finite values survive bit-for-bit. Parameters must be `float` (not int/bool).

Atomic write: data is written to a temporary file in the destination directory,
flushed and fsynced, then moved over the target with `os.replace`. An
interrupted save leaves either the previous file or nothing, never a
half-written checkpoint under the target name.

HONEST LIMITS of the digest. A plain sha256 digest stored inside the file
detects accidental corruption (bit rot, truncation, partial copies) and naive
tampering (editing a value without fixing the digest). It is NOT a signature or
MAC and has no secret key: anyone who can rewrite the whole file can edit the
content and recompute a matching digest, and the loader will accept it. It does
not authenticate who produced the file, does not prove the parameters are
meaningful or "good", and says nothing about the safety of any model. To bind
a file to a trusted origin, compare the digest returned by `save_checkpoint`
against a value obtained through a separate trusted channel.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import math
import os
import re
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Sequence

from toy.schema import TOY_LABEL, RunProvenance, canonical_json
from toy.stability import NonFiniteError, StabilityError

FORMAT_VERSION = 1
SUPPORTED_FORMAT_VERSIONS = (1,)
MAX_CHECKPOINT_BYTES = 1 << 20  # 1 MiB cap: toy files are tiny; refuse to slurp huge input
EXPECTED_KEYS = frozenset({"format_version", "label", "created_utc", "provenance", "params", "digest"})
_PAYLOAD_KEYS = EXPECTED_KEYS - {"digest"}
_TS_RE = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", re.ASCII)
_DIGEST_RE = re.compile(r"[0-9a-f]{64}", re.ASCII)


# ------------------------------------------------------------- exceptions
class CheckpointError(StabilityError):
    """Base class for every checkpoint failure (a ValueError)."""


class CheckpointFormatError(CheckpointError):
    """Empty / truncated / non-JSON / non-UTF-8 / wrong top-level type / non-canonical bytes."""


class CheckpointKeyError(CheckpointError):
    """Unknown or missing top-level keys (the key-set mismatch guard)."""


class CheckpointVersionError(CheckpointError):
    """format_version missing-type or not supported."""


class CheckpointIntegrityError(CheckpointError):
    """Digest absent, malformed or not equal to the recomputed digest."""


class CheckpointProvenanceError(CheckpointError):
    """The provenance record is malformed (rejected by RunProvenance)."""


class CheckpointTypeError(CheckpointError):
    """A field has the wrong type."""


class CheckpointNonFiniteError(CheckpointError, NonFiniteError):
    """A parameter is NaN or infinite."""


@dataclass(frozen=True)
class Checkpoint:
    format_version: int
    created_utc: str
    provenance: RunProvenance
    params: tuple
    digest: str

    def payload_dict(self) -> dict[str, Any]:
        """The digest-covered object (every key except `digest`)."""
        return {"format_version": self.format_version, "label": TOY_LABEL,
                "created_utc": self.created_utc, "provenance": self.provenance.to_dict(),
                "params": list(self.params)}


# ----------------------------------------------------------------- digest
def compute_digest(payload: dict[str, Any]) -> str:
    """sha256 hex of the canonical JSON of `payload`, which must NOT contain `digest`."""
    if "digest" in payload:
        raise CheckpointError("compute_digest: payload must not contain the digest field")
    try:
        text = canonical_json(payload)
    except (ValueError, TypeError) as e:
        raise CheckpointError(f"cannot canonically serialise payload: {e}") from None
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ------------------------------------------------------------- validation
def _validate_timestamp(ts: Any) -> str:
    if not isinstance(ts, str):
        raise CheckpointTypeError(f"created_utc must be a string, got {type(ts).__name__}")
    if not _TS_RE.fullmatch(ts):
        raise CheckpointFormatError(f"created_utc must match YYYY-MM-DDTHH:MM:SSZ, got {ts!r}")
    try:
        datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        raise CheckpointFormatError(f"created_utc is not a real date/time: {ts!r}") from None
    return ts


def _validate_params(params: Any) -> tuple:
    if not isinstance(params, (list, tuple)):
        raise CheckpointTypeError(f"params must be a list, got {type(params).__name__}")
    if len(params) == 0:
        raise CheckpointTypeError("params must not be empty")
    for i, v in enumerate(params):
        if isinstance(v, bool) or not isinstance(v, float):
            raise CheckpointTypeError(f"params[{i}] must be a float, got {type(v).__name__}")
        if not math.isfinite(v):
            raise CheckpointNonFiniteError(f"params[{i}] is not finite ({v!r})")
    return tuple(params)


def _validate_provenance(prov: Any) -> RunProvenance:
    if isinstance(prov, RunProvenance):
        return prov
    try:
        return RunProvenance.from_dict(prov)
    except (ValueError, TypeError) as e:
        raise CheckpointProvenanceError(f"malformed provenance: {e}") from None


def _validate_version(v: Any) -> int:
    if isinstance(v, bool) or not isinstance(v, int):
        raise CheckpointVersionError(f"format_version must be an int, got {type(v).__name__}")
    if v not in SUPPORTED_FORMAT_VERSIONS:
        raise CheckpointVersionError(
            f"unsupported format_version {v}; supported: {list(SUPPORTED_FORMAT_VERSIONS)}")
    return v


# ------------------------------------------------------------------- save
def save_checkpoint(path: str | os.PathLike, params: Sequence[float], provenance: RunProvenance,
                    *, created_utc: str | None = None) -> str:
    """Atomically write a TOY checkpoint and return its digest (hex).

    created_utc: None records the real current UTC time (the file/digest then
    differ between runs); pass a pinned YYYY-MM-DDTHH:MM:SSZ for a reproducible
    file. Inputs are validated before anything is written."""
    if created_utc is None:
        created_utc = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    cp_params = _validate_params(params)
    prov = _validate_provenance(provenance)
    if not isinstance(prov, RunProvenance):  # pragma: no cover - defensive
        raise CheckpointProvenanceError("provenance must be a RunProvenance")
    payload = {"format_version": FORMAT_VERSION, "label": TOY_LABEL,
               "created_utc": _validate_timestamp(created_utc),
               "provenance": prov.to_dict(), "params": list(cp_params)}
    digest = compute_digest(payload)
    data = canonical_json({**payload, "digest": digest}).encode("utf-8")

    directory = os.path.dirname(os.path.abspath(os.fspath(path)))
    fd, tmp = tempfile.mkstemp(prefix=".toy_ckpt_", suffix=".tmp", dir=directory)
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
    return digest


# ------------------------------------------------------------------- load
def _no_dupes(pairs):
    d = {}
    for k, v in pairs:
        if k in d:
            raise CheckpointFormatError(f"duplicate JSON key {k!r}")
        d[k] = v
    return d


def _bad_const(name):
    raise CheckpointNonFiniteError(f"non-finite JSON constant {name} not allowed")


def load_checkpoint(path: str | os.PathLike) -> Checkpoint:
    """Read, strictly validate and return a TOY checkpoint. Never executes
    anything from the file. Raises a CheckpointError subclass on any problem."""
    with open(os.fspath(path), "rb") as f:
        raw = f.read(MAX_CHECKPOINT_BYTES + 1)
    if len(raw) == 0:
        raise CheckpointFormatError("checkpoint file is empty")
    if len(raw) > MAX_CHECKPOINT_BYTES:
        raise CheckpointFormatError(f"checkpoint larger than {MAX_CHECKPOINT_BYTES} bytes; refusing")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as e:
        raise CheckpointFormatError(f"checkpoint is not valid UTF-8: {e}") from None
    try:
        data = json.loads(text, object_pairs_hook=_no_dupes, parse_constant=_bad_const)
    except CheckpointError:
        raise
    except json.JSONDecodeError as e:
        raise CheckpointFormatError(f"checkpoint is not valid JSON (truncated or corrupted?): {e}") from None
    except (RecursionError, ValueError) as e:
        raise CheckpointFormatError(f"checkpoint JSON could not be parsed: {e}") from None
    if not isinstance(data, dict):
        raise CheckpointFormatError(f"top level must be a JSON object, got {type(data).__name__}")

    keys = set(data)
    if "digest" not in keys:
        raise CheckpointIntegrityError("digest field is missing")
    unknown, missing = keys - EXPECTED_KEYS, EXPECTED_KEYS - keys
    if unknown or missing:
        raise CheckpointKeyError(
            f"top-level key mismatch: unknown {sorted(unknown)}, missing {sorted(missing)}; "
            f"expected exactly {sorted(EXPECTED_KEYS)}")

    version = _validate_version(data["format_version"])
    if data["label"] != TOY_LABEL:
        raise CheckpointFormatError(f"label must equal {TOY_LABEL!r}")
    created = _validate_timestamp(data["created_utc"])
    params = _validate_params(data["params"])
    prov = _validate_provenance(data["provenance"])
    stored = data["digest"]
    if not isinstance(stored, str):
        raise CheckpointTypeError(f"digest must be a string, got {type(stored).__name__}")
    if not _DIGEST_RE.fullmatch(stored):
        raise CheckpointIntegrityError("digest is not a lowercase 64-char sha256 hex string")

    payload = {k: data[k] for k in _PAYLOAD_KEYS}
    if not hmac.compare_digest(stored, compute_digest(payload)):
        raise CheckpointIntegrityError("digest mismatch: content does not match the recorded digest")
    if canonical_json(data) != text:
        raise CheckpointFormatError("file bytes are not in canonical form (content parses but was altered)")
    return Checkpoint(version, created, prov, params, stored)
