"""SR-14 tests. TOY only: synthetic, non-biological; nothing here asserts safety."""
import ast
import copy
import itertools
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from toy import claim_ledger as cl
from toy.claim_ledger import (Action, ChainIntegrityError, ClaimExistsError, ClaimLedger, ClaimLedgerError,
                              ClaimState, DuplicateEventIdError, EventFormatError, EventRequest,
                              EvidenceRef, InvalidTransitionError, LedgerEvent, LedgerFormatError,
                              LedgerKeyError, LedgerVersionError, MissingEvidenceError,
                              MissingJustificationError, StateMismatchError, TimestampOrderError,
                              UnknownClaimError, UnknownEvidenceError, load_ledger, save_ledger,
                              verify_events)
from toy.schema import EvidenceClass, TOY_LABEL, canonical_json
from toy.teacher_student import train

T0, T1, T2, T3 = ("2025-01-02T03:04:0%dZ" % i for i in (5, 6, 7, 8))
H1, H2 = "a1" * 32, "b2" * 32
EV = (EvidenceRef("content_hash", H1),)
BANNED = ("pickle", "cPickle", "_pickle", "torch", "dill", "marshal", "shelve")
S = ClaimState


def banned_imports(source):
    hits = []
    for node in ast.walk(ast.parse(source)):
        names = []
        if isinstance(node, ast.Import):
            names = [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            names = [node.module or ""]
        elif isinstance(node, ast.Name) and node.id in ("__import__", "importlib"):
            hits.append(node.id)
        elif isinstance(node, ast.Attribute) and node.attr in ("import_module", "__import__"):
            hits.append(node.attr)
        hits += [n for n in names if n.split(".")[0] in BANNED or n.split(".")[0] == "importlib"]
    return hits


def req(eid, cid, action, frm, to, **kw):
    d = dict(reviewer="rev-a", justification="because", evidence_refs=(), timestamp_utc=T1)
    d.update(kw)
    return EventRequest(eid, cid, action, frm, to, **d)


def ledger_in(state, cid="c1", **kw):
    """A ledger whose claim `cid` is in `state`, reached only via legitimate explicit events."""
    lg = ClaimLedger(**kw)
    if state is None:
        return lg
    lg.open_claim(event_id="e-open", claim_id=cid, reviewer="a", justification="draft", statement="toy claim",
                  evidence_class=EvidenceClass.TOY_RESULT, timestamp_utc=T0)
    if state is S.DRAFT:
        return lg
    lg.review(event_id="e-rev", claim_id=cid, reviewer="a", justification="read it", timestamp_utc=T1)
    if state is S.REVIEWED:
        return lg
    if state is S.SUPPORTED or state == "RETRACTED":
        lg.support(event_id="e-sup", claim_id=cid, reviewer="a", justification="ok", evidence_refs=EV,
                   timestamp_utc=T2)
        return lg
    lg.reject(event_id="e-rej", claim_id=cid, reviewer="a", justification="no", timestamp_utc=T2)
    return lg


def full_ledger():
    lg = ledger_in(S.SUPPORTED)
    lg.open_claim(event_id="e2-open", claim_id="c2", reviewer="a", justification="d", statement="s2",
                  evidence_class=EvidenceClass.HYPOTHESIS, timestamp_utc=T2)
    lg.review(event_id="e2-rev", claim_id="c2", reviewer="b", justification="r", timestamp_utc=T3)
    lg.retract(event_id="e-ret", claim_id="c1", reviewer="b", justification="new evidence", timestamp_utc=T3)
    return lg


def rewrite(dicts):
    """Recompute prev_digest/digest over edited event dicts: what a full-file rewriter can do."""
    prev, out = cl.GENESIS_DIGEST, []
    for i, d in enumerate(dicts):
        d = dict(d, seq=i, prev_digest=prev)
        d.pop("digest", None)
        d["digest"] = cl._digest(d)
        prev = d["digest"]
        out.append(d)
    return out


def doc(dicts):
    return {"format_version": 1, "label": cl.LEDGER_LABEL, "events": dicts,
            "head_digest": dicts[-1]["digest"] if dicts else cl.GENESIS_DIGEST}


def verify_dicts(dicts):
    return verify_events([LedgerEvent.from_dict(d) for d in dicts])


class TransitionMatrix(unittest.TestCase):
    ACTIONS = {(None, S.DRAFT): Action.OPEN, (S.DRAFT, S.REVIEWED): Action.REVIEW,
               (S.REVIEWED, S.SUPPORTED): Action.SUPPORT, (S.REVIEWED, S.UNSUPPORTED): Action.REJECT,
               (S.SUPPORTED, S.UNSUPPORTED): Action.RETRACT}
    SETUP = {None: None, S.DRAFT: S.DRAFT, S.REVIEWED: S.REVIEWED, S.SUPPORTED: S.SUPPORTED,
             S.UNSUPPORTED: S.UNSUPPORTED}

    def test_table_is_exactly_the_documented_five(self):
        self.assertEqual(set(cl.TRANSITIONS), set(self.ACTIONS))
        for k, a in self.ACTIONS.items():
            self.assertIs(cl.TRANSITIONS[k][0], a)

    def test_every_invalid_state_pair_with_every_action_is_rejected(self):
        froms = [None] + list(S)
        n = 0
        for frm, to, act in itertools.product(froms, list(S), list(Action)):
            if self.ACTIONS.get((frm, to)) is act:
                continue
            with self.subTest(frm=frm, to=to, act=act):
                lg = ledger_in(self.SETUP[frm])
                before = lg.events
                kw = dict(evidence_refs=EV)
                if act is Action.OPEN:
                    kw.update(evidence_class=EvidenceClass.TOY_RESULT, statement="x")
                with self.assertRaises(InvalidTransitionError):
                    lg.append(req("e-x", "c1" if frm else "c9", act, frm, to, **kw))
                self.assertEqual(lg.events, before)
                n += 1
        self.assertEqual(n, 5 * 4 * 5 - 5)

    def test_every_valid_transition_succeeds(self):
        for (frm, to), act in self.ACTIONS.items():
            with self.subTest(frm=frm, to=to):
                lg = ledger_in(self.SETUP[frm])
                kw = {}
                if act is Action.OPEN:
                    kw = dict(evidence_class=EvidenceClass.TOY_RESULT, statement="x")
                r = lg.append(req("e-x", "c1" if frm else "c9", act, frm, to, evidence_refs=EV,
                                    timestamp_utc=T3, **kw))
                self.assertTrue(r.appended)
                self.assertIs(lg.claim_state("c1" if frm else "c9"), to)

    def test_terminal_states_and_named_retraction(self):
        lg = ledger_in(S.UNSUPPORTED)
        for to in S:
            with self.assertRaises(InvalidTransitionError):
                lg.append(req("e-t", "c1", Action.REJECT, S.UNSUPPORTED, to, evidence_refs=EV))
        # retraction is a distinct action: SUPPORTED->UNSUPPORTED via REJECT is refused
        lg = ledger_in(S.SUPPORTED)
        with self.assertRaises(InvalidTransitionError):
            lg.append(req("e-t", "c1", Action.REJECT, S.SUPPORTED, S.UNSUPPORTED))
        with self.assertRaises(MissingJustificationError):
            lg.retract(event_id="e-t", claim_id="c1", reviewer="a", justification="  ", timestamp_utc=T3)
        lg.retract(event_id="e-t2", claim_id="c1", reviewer="a", justification="new evidence", timestamp_utc=T3)
        self.assertTrue(lg.summary()[0]["retracted"])
        self.assertEqual(lg.summary()[0]["supporting_evidence"], [])

    def test_wrong_from_state_and_unknown_and_reopen(self):
        lg = ledger_in(S.REVIEWED)
        with self.assertRaises(StateMismatchError):  # claims to be DRAFT->REVIEWED but is REVIEWED
            lg.append(req("e-x", "c1", Action.REVIEW, S.DRAFT, S.REVIEWED))
        with self.assertRaises(UnknownClaimError):
            lg.review(event_id="e-y", claim_id="nope", reviewer="a", justification="j", timestamp_utc=T1)
        with self.assertRaises(ClaimExistsError):
            lg.open_claim(event_id="e-z", claim_id="c1", reviewer="a", justification="j", statement="s",
                          evidence_class="TOY_RESULT", timestamp_utc=T2)
        with self.assertRaises(UnknownClaimError):
            lg.claim_state("nope")


class RequiredFields(unittest.TestCase):
    def test_support_without_evidence_refs_fails(self):
        for refs in ((), [], None):
            lg = ledger_in(S.REVIEWED)
            with self.assertRaises((MissingEvidenceError, EventFormatError)):
                lg.support(event_id="e-s", claim_id="c1", reviewer="a", justification="j",
                           evidence_refs=refs, timestamp_utc=T2)
            self.assertIs(lg.claim_state("c1"), S.REVIEWED)

    def test_support_empty_refs_is_specifically_missing_evidence(self):
        lg = ledger_in(S.REVIEWED)
        with self.assertRaises(MissingEvidenceError):
            lg.support(event_id="e-s", claim_id="c1", reviewer="a", justification="j", evidence_refs=(),
                       timestamp_utc=T2)

    def test_justification_required_for_every_human_step(self):
        for bad in ("", "   ", "\n\t"):
            for step, setup in (("review", S.DRAFT), ("support", S.REVIEWED), ("reject", S.REVIEWED),
                                ("retract", S.SUPPORTED)):
                with self.subTest(step=step, bad=bad):
                    lg = ledger_in(setup)
                    kw = dict(event_id="e-n", claim_id="c1", reviewer="a", justification=bad, timestamp_utc=T3)
                    if step == "support":
                        kw["evidence_refs"] = EV
                    with self.assertRaises(MissingJustificationError):
                        getattr(lg, step)(**kw)

    def test_reviewer_and_timestamp_validation(self):
        lg = ledger_in(S.DRAFT)
        for rev in ("", "  ", None, 5, "x\x00y"):
            with self.assertRaises(EventFormatError):
                lg.review(event_id="e-n", claim_id="c1", reviewer=rev, justification="j", timestamp_utc=T1)
        for ts in ("1970", "2025-13-01T00:00:00Z", "2025-01-01 00:00:00", 5):
            with self.assertRaises(EventFormatError):
                lg.review(event_id="e-n", claim_id="c1", reviewer="a", justification="j", timestamp_utc=ts)

    def test_default_timestamp_is_real_utc_not_pinned_epoch(self):
        lg = ClaimLedger()
        r = lg.open_claim(event_id="e", claim_id="c", reviewer="a", justification="j", statement="s",
                          evidence_class="TOY_RESULT")
        self.assertGreaterEqual(r.event.timestamp_utc, "2025-01-01T00:00:00Z")
        self.assertNotIn("1970", r.event.timestamp_utc)

    def test_evidence_ref_shape(self):
        for kind, val in (("nope", H1), ("content_hash", "abc"), ("content_hash", H1.upper()),
                          ("content_hash", "0" * 64), ("content_hash", 5)):
            with self.assertRaises(EventFormatError):
                EvidenceRef(kind, val)
        lg = ledger_in(S.REVIEWED)
        with self.assertRaises(EventFormatError):
            lg.support(event_id="e", claim_id="c1", reviewer="a", justification="j",
                       evidence_refs=(EV[0], EV[0]), timestamp_utc=T2)
        with self.assertRaises(EventFormatError):
            lg.support(event_id="e", claim_id="c1", reviewer="a", justification="j",
                       evidence_refs=("not-a-ref",), timestamp_utc=T2)

    def test_known_evidence_registry_when_supplied(self):
        lg = ledger_in(S.REVIEWED, known_evidence={H2})
        with self.assertRaises(UnknownEvidenceError):
            lg.support(event_id="e", claim_id="c1", reviewer="a", justification="j", evidence_refs=EV,
                       timestamp_utc=T2)
        lg.support(event_id="e", claim_id="c1", reviewer="a", justification="j",
                   evidence_refs=(EvidenceRef("checkpoint_digest", H2),), timestamp_utc=T2)

    def test_evidence_from_real_record_and_checkpoint_digest(self):
        r = train(seed=1, steps=2, timestamp_utc="2025-01-02T03:04:05Z")
        ref = cl.evidence_from_record(r.record)
        self.assertEqual(ref.value, r.record.content_hash())
        lg = ledger_in(S.REVIEWED)
        self.assertTrue(lg.support(event_id="e", claim_id="c1", reviewer="a", justification="j",
                                   evidence_refs=(ref,), timestamp_utc=T2).appended)

    def test_open_requires_class_and_statement_and_others_forbid_them(self):
        lg = ClaimLedger()
        for kw in (dict(evidence_class=None, statement="s"), dict(evidence_class="TOY_RESULT", statement=""),
                   dict(evidence_class="BOGUS", statement="s")):
            with self.assertRaises((EventFormatError, ValueError)):
                lg.open_claim(event_id="e", claim_id="c", reviewer="a", justification="j", timestamp_utc=T0, **kw)
        lg = ledger_in(S.DRAFT)
        with self.assertRaises(EventFormatError):  # cannot relabel the evidence class mid-life
            lg.append(req("e-r", "c1", Action.REVIEW, S.DRAFT, S.REVIEWED, evidence_class="SOURCE_OBSERVED"))

    def test_timestamp_must_not_go_backwards_per_claim(self):
        lg = ledger_in(S.DRAFT)
        with self.assertRaises(TimestampOrderError):
            lg.review(event_id="e", claim_id="c1", reviewer="a", justification="j",
                      timestamp_utc="2024-01-01T00:00:00Z")


class Idempotency(unittest.TestCase):
    def test_identical_replay_is_noop_and_digest_unchanged(self):
        lg = ledger_in(S.DRAFT)
        r1 = lg.review(event_id="e-r", claim_id="c1", reviewer="a", justification="j", timestamp_utc=T1)
        head, n, evs = lg.head_digest, len(lg), lg.events
        r2 = lg.review(event_id="e-r", claim_id="c1", reviewer="a", justification="j", timestamp_utc=T1)
        self.assertTrue(r1.appended)
        self.assertFalse(r2.appended)
        self.assertEqual(r2.event, r1.event)
        self.assertEqual((lg.head_digest, len(lg), lg.events), (head, n, evs))
        self.assertTrue(lg.verify_chain().ok)

    def test_replay_of_old_event_after_state_moved_on_is_still_noop(self):
        lg = ledger_in(S.SUPPORTED)
        head = lg.head_digest
        r = lg.review(event_id="e-rev", claim_id="c1", reviewer="a", justification="read it", timestamp_utc=T1)
        self.assertFalse(r.appended)
        self.assertEqual(lg.head_digest, head)

    def test_replay_of_support_and_open_noop(self):
        lg = ledger_in(S.SUPPORTED)
        head = lg.head_digest
        self.assertFalse(lg.support(event_id="e-sup", claim_id="c1", reviewer="a", justification="ok",
                                    evidence_refs=EV, timestamp_utc=T2).appended)
        self.assertFalse(lg.open_claim(event_id="e-open", claim_id="c1", reviewer="a", justification="draft",
                                       statement="toy claim", evidence_class=EvidenceClass.TOY_RESULT,
                                       timestamp_utc=T0).appended)
        self.assertEqual(lg.head_digest, head)

    def test_same_id_different_content_is_rejected_for_each_field(self):
        base = dict(event_id="e-sup", claim_id="c1", reviewer="a", justification="ok", evidence_refs=EV,
                    timestamp_utc=T2)
        variants = dict(reviewer="mallory", justification="ok!", evidence_refs=(EvidenceRef("content_hash", H2),),
                        timestamp_utc=T3)
        for field, val in variants.items():
            with self.subTest(field=field):
                lg = ledger_in(S.SUPPORTED)
                head = lg.head_digest
                with self.assertRaises(DuplicateEventIdError):
                    lg.support(**{**base, field: val})
                self.assertEqual(lg.head_digest, head)
        lg = ledger_in(S.SUPPORTED)  # same id, different claim / action
        with self.assertRaises(DuplicateEventIdError):
            lg.append(req("e-sup", "c1", Action.REJECT, S.REVIEWED, S.UNSUPPORTED, timestamp_utc=T2))
        with self.assertRaises(DuplicateEventIdError):
            lg.review(event_id="e-sup", claim_id="c-other", reviewer="a", justification="j", timestamp_utc=T2)

    def test_duplicate_id_in_forged_file_is_rejected(self):
        d = [e.to_dict() for e in ledger_in(S.REVIEWED).events]
        d.append(dict(d[1], justification="again"))
        with self.assertRaises(ChainIntegrityError):
            ClaimLedger.from_dict(doc(rewrite(d)))


class HashChain(unittest.TestCase):
    def setUp(self):
        self.lg = full_ledger()
        self.dicts = [e.to_dict() for e in self.lg.events]

    def test_clean_chain_verifies(self):
        res = self.lg.verify_chain()
        self.assertTrue(res.ok)
        self.assertEqual(res.events_checked, len(self.lg))
        self.assertIsNone(res.first_broken_index)

    def test_field_tampering_detected_at_that_event(self):
        idx = 2  # e-sup: has evidence refs
        self.assertEqual(self.dicts[idx]["event_id"], "e-sup")
        edits = {"justification": "totally fine", "reviewer": "someone-else", "timestamp_utc": "2025-01-02T03:04:09Z",
                 "to_state": "REVIEWED", "from_state": "DRAFT", "action": "REVIEW",
                 "evidence_refs": [{"kind": "content_hash", "value": H2}]}
        for field, val in edits.items():
            with self.subTest(field=field):
                d = copy.deepcopy(self.dicts)
                d[idx][field] = val
                res = verify_dicts(d)
                self.assertFalse(res.ok)
                self.assertEqual(res.first_broken_index, idx)
                self.assertEqual(res.first_broken_event_id, "e-sup")
                self.assertEqual(res.reason, "digest_mismatch")

    def test_in_memory_tamper_detected(self):
        lg = full_ledger()
        object.__setattr__(lg._events[1], "justification", "edited")
        res = lg.verify_chain()
        self.assertFalse(res.ok)
        self.assertEqual((res.first_broken_index, res.first_broken_event_id), (1, "e-rev"))

    def test_deleting_middle_event_detected(self):
        for i in (1, 2, 3):
            with self.subTest(deleted=i):
                d = copy.deepcopy(self.dicts)
                del d[i]
                res = verify_dicts(d)
                self.assertFalse(res.ok)
                self.assertEqual(res.first_broken_index, i)

    def test_reordering_detected(self):
        d = copy.deepcopy(self.dicts)
        d[1], d[2] = d[2], d[1]
        res = verify_dicts(d)
        self.assertFalse(res.ok)
        self.assertEqual(res.first_broken_index, 1)
        self.assertIn(res.reason, ("seq_mismatch", "prev_digest_mismatch"))

    def test_seq_renumbered_but_not_rehashed_detected(self):
        d = copy.deepcopy(self.dicts)
        d[1], d[2] = d[2], d[1]
        d[1]["seq"], d[2]["seq"] = 1, 2
        res = verify_dicts(d)
        self.assertEqual((res.ok, res.first_broken_index, res.reason), (False, 1, "prev_digest_mismatch"))

    def test_tail_truncation_caught_by_head_digest_on_load(self):
        data = doc(self.dicts[:-1])
        data["head_digest"] = self.lg.head_digest
        with self.assertRaises(ChainIntegrityError):
            ClaimLedger.from_dict(data)

    def test_first_break_is_the_first_of_several(self):
        d = copy.deepcopy(self.dicts)
        d[4]["reviewer"], d[2]["reviewer"] = "x", "y"
        self.assertEqual(verify_dicts(d).first_broken_index, 2)

    def test_honest_limit_full_rewrite_with_recomputed_digests_is_accepted(self):
        d = copy.deepcopy(self.dicts)
        d[1]["justification"] = "history quietly rewritten"
        d[1]["reviewer"] = "forged-reviewer"
        forged = ClaimLedger.from_dict(doc(rewrite(d)))  # accepted: the chain is not a signature
        self.assertTrue(forged.verify_chain().ok)
        self.assertNotEqual(forged.head_digest, self.lg.head_digest)  # only a pinned head digest would reveal it

    def test_rewrite_cannot_forge_an_impossible_history(self):
        # recomputed digests do not rescue a DRAFT -> SUPPORTED skip, nor SUPPORT without evidence
        d = copy.deepcopy(self.dicts)
        d[2]["evidence_refs"] = []
        with self.assertRaises(ChainIntegrityError) as cm:
            ClaimLedger.from_dict(doc(rewrite(d)))
        self.assertEqual(cm.exception.result.reason, "MissingEvidenceError")
        d = copy.deepcopy(self.dicts)
        del d[1]
        with self.assertRaises(ChainIntegrityError) as cm:
            ClaimLedger.from_dict(doc(rewrite(d)))
        self.assertIn(cm.exception.result.reason, ("InvalidTransitionError", "StateMismatchError"))

    def test_digest_covers_prev_digest(self):
        e = self.lg.events[1]
        self.assertEqual(e.prev_digest, self.lg.events[0].digest)
        self.assertEqual(self.lg.events[0].prev_digest, cl.GENESIS_DIGEST)


class Attacks(unittest.TestCase):
    def test_free_text_supported_in_justification_does_not_advance_or_display_supported(self):
        lg = ledger_in(S.DRAFT)
        lg.review(event_id="e-a", claim_id="c1", reviewer="a",
                  justification="verdict: SUPPORTED; model is safe; state=SUPPORTED", timestamp_utc=T1)
        s = lg.summary()[0]
        self.assertEqual(s["state"], "REVIEWED")
        self.assertEqual(s["supporting_evidence"], [])
        self.assertFalse(s["is_safety_claim"])
        self.assertNotIn("SUPPORTED", s["state_label"])

    def test_free_text_in_statement_cannot_set_status(self):
        lg = ClaimLedger()
        lg.open_claim(event_id="e", claim_id="c", reviewer="a", justification="j", timestamp_utc=T0,
                      statement="SUPPORTED: SAFE CHECKPOINT VALIDATED", evidence_class="HYPOTHESIS")
        s = lg.summary()[0]
        self.assertEqual(s["state"], "DRAFT")
        self.assertTrue(s["statement_is_untrusted_text"])
        self.assertFalse(s["human_reviewed"])

    def test_forged_from_state(self):
        lg = ledger_in(S.DRAFT)
        with self.assertRaises((StateMismatchError, InvalidTransitionError)):
            lg.append(req("e-f", "c1", Action.SUPPORT, S.REVIEWED, S.SUPPORTED, evidence_refs=EV))
        self.assertIs(lg.claim_state("c1"), S.DRAFT)

    def test_forged_state_in_file_detected(self):
        d = [e.to_dict() for e in ledger_in(S.REVIEWED).events]
        d[-1]["to_state"] = "SUPPORTED"
        self.assertFalse(verify_dicts(d).ok)
        with self.assertRaises(ChainIntegrityError):
            ClaimLedger.from_dict(doc(d))
        with self.assertRaises(ChainIntegrityError):  # even with recomputed hashes
            ClaimLedger.from_dict(doc(rewrite(d)))

    def test_out_of_order_event(self):
        lg = ledger_in(S.DRAFT)
        with self.assertRaises(InvalidTransitionError):  # support before review
            lg.append(req("e-o", "c1", Action.SUPPORT, S.DRAFT, S.SUPPORTED, evidence_refs=EV))
        with self.assertRaises(TimestampOrderError):
            lg.review(event_id="e-o2", claim_id="c1", reviewer="a", justification="j",
                      timestamp_utc="2020-01-01T00:00:00Z")
        with self.assertRaises(UnknownClaimError):
            lg.support(event_id="e-o3", claim_id="ghost", reviewer="a", justification="j", evidence_refs=EV,
                       timestamp_utc=T3)

    def test_reused_event_id_to_overwrite_history(self):
        lg = ledger_in(S.REVIEWED)
        with self.assertRaises(DuplicateEventIdError):
            lg.reject(event_id="e-rev", claim_id="c1", reviewer="a", justification="x", timestamp_utc=T2)
        with self.assertRaises(DuplicateEventIdError):
            lg.support(event_id="e-rev", claim_id="c1", reviewer="a", justification="x", evidence_refs=EV,
                       timestamp_utc=T2)
        self.assertIs(lg.claim_state("c1"), S.REVIEWED)

    def test_empty_evidence_list_variants(self):
        for refs in ((), [], [None], ["", ""], [{}], [{"kind": "content_hash", "value": ""}],
                     [{"kind": "content_hash", "value": "0" * 64}]):
            lg = ledger_in(S.REVIEWED)
            with self.assertRaises(ClaimLedgerError):
                lg.support(event_id="e", claim_id="c1", reviewer="a", justification="j", evidence_refs=refs,
                           timestamp_utc=T2)
            self.assertIs(lg.claim_state("c1"), S.REVIEWED)

    def test_tampered_file_on_disk_rejected_with_recomputed_digest_but_no_evidence(self):
        lg = ledger_in(S.SUPPORTED)
        d = [e.to_dict() for e in lg.events]
        d[-1]["evidence_refs"] = []
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "l.json"
            p.write_text(canonical_json(doc(rewrite(d))))
            with self.assertRaises(ChainIntegrityError):
                load_ledger(p)

    def test_no_auto_promotion_api(self):
        lg = ledger_in(S.DRAFT)
        for name in dir(lg):
            self.assertNotRegex(name, r"(?i)promote|advance|auto|approve|confirm")
        lg.summary(); lg.verify_chain(); lg.to_json()
        self.assertIs(lg.claim_state("c1"), S.DRAFT)

    def test_supported_toy_claim_stays_toy_and_never_source_observed(self):
        lg = ledger_in(S.SUPPORTED)
        s = lg.summary()[0]
        self.assertEqual(s["state"], "SUPPORTED")
        self.assertEqual(s["evidence_class"], "TOY_RESULT")
        self.assertTrue(s["is_toy"])
        self.assertEqual(s["toy_label"], TOY_LABEL)
        self.assertFalse(s["is_safety_claim"])
        self.assertIn("TOY", s["state_label"])
        self.assertNotEqual(s["evidence_class"], EvidenceClass.SOURCE_OBSERVED.value)
        self.assertEqual({e.evidence_class for e in lg.events} - {None}, {EvidenceClass.TOY_RESULT})
        json.dumps(s)

    def test_state_is_not_an_evidence_class(self):
        self.assertFalse({m.value for m in S} & {m.value for m in EvidenceClass})

    def test_summary_values_are_structured_only(self):
        for s in full_ledger().summary():
            self.assertIn(s["state"], {m.value for m in S})
            self.assertIn(s["evidence_class"], {m.value for m in EvidenceClass})
            self.assertIs(s["is_safety_claim"], False)


class Persistence(unittest.TestCase):
    def test_roundtrip_exact_and_stable_digest(self):
        lg = full_ledger()
        with tempfile.TemporaryDirectory() as td:
            p, q = Path(td) / "a.json", Path(td) / "b.json"
            d1 = save_ledger(p, lg)
            back = load_ledger(p)
            self.assertEqual(back, lg)
            self.assertEqual(back.events, lg.events)
            self.assertEqual(back.head_digest, d1)
            self.assertEqual(save_ledger(q, back), d1)
            self.assertEqual(p.read_bytes(), q.read_bytes())
            self.assertEqual(back.summary(), lg.summary())
            # a loaded ledger keeps working and keeps idempotency
            self.assertFalse(back.review(event_id="e-rev", claim_id="c1", reviewer="a", justification="read it",
                                         timestamp_utc=T1).appended)
            self.assertEqual(os.listdir(td).count("a.json"), 1)
            self.assertFalse([f for f in os.listdir(td) if f.endswith(".tmp")])

    def test_empty_ledger_roundtrip(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "e.json"
            save_ledger(p, ClaimLedger())
            self.assertEqual(load_ledger(p).head_digest, cl.GENESIS_DIGEST)

    def test_file_is_plain_json(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "e.json"
            save_ledger(p, full_ledger())
            raw = p.read_bytes()
            self.assertTrue(raw.startswith(b"{"))
            json.loads(raw.decode("ascii"))

    def test_corrupted_files_rejected_with_specific_errors(self):
        good = full_ledger().to_dict()

        def mut(f):
            d = copy.deepcopy(good)
            f(d)
            return canonical_json(d).encode()
        cases = [
            ("empty", b"", LedgerFormatError),
            ("truncated", canonical_json(good).encode()[:-20], LedgerFormatError),
            ("not utf8", b"\xff\xfe{}", LedgerFormatError),
            ("array", b"[]", LedgerFormatError),
            ("oversize", b" " * (cl.MAX_LEDGER_BYTES + 1), LedgerFormatError),
            ("dup key", b'{"format_version":1,"format_version":1}', LedgerFormatError),
            ("NaN", b'{"format_version":NaN}', LedgerFormatError),
            ("extra key", mut(lambda d: d.update(x=1)), LedgerKeyError),
            ("missing key", mut(lambda d: d.pop("head_digest")), LedgerKeyError),
            ("bad version", mut(lambda d: d.update(format_version=2)), LedgerVersionError),
            ("bool version", mut(lambda d: d.update(format_version=True)), LedgerVersionError),
            ("bad label", mut(lambda d: d.update(label="x")), LedgerFormatError),
            ("events not list", mut(lambda d: d.update(events={})), LedgerFormatError),
            ("event extra key", mut(lambda d: d["events"][0].update(x=1)), LedgerKeyError),
            ("event bad state", mut(lambda d: d["events"][0].update(to_state="SAFE")), EventFormatError),
            ("tampered justification", mut(lambda d: d["events"][1].update(justification="z")), ChainIntegrityError),
            ("bad head", mut(lambda d: d.update(head_digest="1" * 64)), ChainIntegrityError),
            ("deleted event", mut(lambda d: d["events"].pop(1)), ChainIntegrityError),
        ]
        with tempfile.TemporaryDirectory() as td:
            for name, data, exc in cases:
                with self.subTest(name):
                    p = Path(td) / "c.json"
                    p.write_bytes(data)
                    with self.assertRaises(exc) as cm:
                        load_ledger(p)
                    self.assertIs(type(cm.exception) is exc or isinstance(cm.exception, exc), True)

    def test_non_canonical_bytes_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "c.json"
            p.write_text(json.dumps(full_ledger().to_dict(), indent=2))
            with self.assertRaises(LedgerFormatError):
                load_ledger(p)

    def test_save_refuses_tampered_ledger_and_leaves_no_file(self):
        lg = full_ledger()
        object.__setattr__(lg._events[0], "reviewer", "evil")
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(ChainIntegrityError):
                save_ledger(Path(td) / "x.json", lg)
            self.assertEqual(os.listdir(td), [])


class SourceHygiene(unittest.TestCase):
    SRC = Path(cl.__file__).read_text()

    def test_no_banned_imports(self):
        self.assertEqual(banned_imports(self.SRC), [])

    def test_scanner_is_not_vacuous(self):
        for s in ("import pickle", "from pickle import loads", "import torch", "import shelve", "import marshal",
                  "__import__('pickle')", "import importlib", "x.import_module('a')"):
            self.assertTrue(banned_imports(s), s)
        self.assertEqual(banned_imports("import json\n'pickle in a string'"), [])
        self.assertTrue(banned_imports(self.SRC + "\nimport pickle\n"))

    def test_scanned_file_is_the_ledger_module(self):
        self.assertTrue(cl.__file__.endswith(os.path.join("toy", "claim_ledger.py")))
        self.assertIn("def verify_events", self.SRC)


if __name__ == "__main__":
    unittest.main()
