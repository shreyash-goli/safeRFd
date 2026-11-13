# SR-12 independent review: method fidelity, unknowns and risk of incorrect safety claims

**Reviewer:** independent QA, second capstone pass. **Date:** 2026-11-12. **Kit HEAD reviewed:** `9621e42`. **Working tree:** clean (`git status --porcelain` empty) at the start, between every run, and immediately before this file was written. **Files written by this review:** this file only. No commit, no code edit, no checkbox edit. **This file supersedes the 2026-11-09 review at HEAD `79be9d4`** (commit `853e820`), whose findings are carried forward item by item in section 7 with their status at this HEAD; it is a rewrite in place rather than a new file, because the blueprint, `docs/SR16_AUDIT_REPORT.md` and the journal all reference this path.

Labels: **SOURCE OBSERVED** (read directly from the cited text or produced by a command recorded in section 9), **INFERENCE** (reasoned from observed text, not executed), **UNKNOWN** (not determined). Nothing in this report asserts that the audited method works, fails, is safe, or is unsafe.

The previous reviewer wrote none of the code and neither did I; I wrote none of the previous review. Every figure below was measured at this HEAD by the command named in section 9. Where I carry a figure forward from the prior review or from `docs/PROGRESS.md` without re-measuring it, the row says so.

---

## 0. Verdict

# FAIL

Same definition the prior review used, so the two documents can be read together: **FAIL means "reproducible defects exist that must be fixed before the kit is described as complete."** It does not mean the audit documents are wrong about the fork, and it is a materially milder FAIL than `853e820`'s.

**The three areas SR-12 names all PASS.** Method fidelity, the unknowns register, and risk of incorrect safety claims are each clean at this HEAD, the last having moved from FAIL to PASS on fixes I verified rather than accepted. **Every High-severity finding of the prior review is closed.** The kit contains no statement and no implication, anywhere outside a guard test, that RFdiffusion or any real model is safe, or that any reduction in biohazardous capability has been measured.

**The verdict is FAIL on one thing, and it is the thing SR-12's own "reproducible commands" clause points at: the evidentiary base of 13 of the 17 in-scope checkboxes is not reproducible from a clone.** Hundreds of mutation results — the dominant category of evidence behind the marks — were produced by harnesses that were never tracked in this repository and no longer exist. A reader can re-run every suite and reproduce every test count; they cannot reproduce a single mutation claim. Four smaller reproducible defects (F16, F18, F20, F21) accompany it. See 0.2 for why this is not routed away to SR-15.

| Area | Prior (2026-11-09) | **Now (2026-11-12)** | Basis |
|---|---|---|---|
| 1. Method fidelity | PASS | **PASS (inherited, limit stated)** | Internal arithmetic and SHA consistency re-derived (C2). The external fork material was **not** re-verified by me; see 1.2. |
| 2. Toy-to-source correspondence | PASS, 3 defects | **PASS, 2 defects** (F7, F8) | F6 closed at length. Section 2. |
| 3. Unknowns register | PASS, 4 defects | **PASS, 2 defects** (F9, F10) | F1 and F5 closed. Section 3. |
| 4. Risk of incorrect safety claims | **FAIL** | **PASS, 1 defect** (F16) | F4 and F15 closed and verified at HEAD, not accepted. Section 4. |
| 5. Cross-document consistency | **FAIL** | **PASS, 1 defect** (F18, new) | F2, F3, F11 closed. One marked task's deliverable denies its own attestation. Section 5. |
| 6. PROGRESS / BLUEPRINT attestation | **FAIL** | **PASS, 1 defect** (F19, new) | F12, F13, F14 closed; the four new marks audited. The ordinal series is still self-contradictory. Section 6. |
| 7. Reproducibility of the evidence | PASS | **FAIL** (F17-R, F20, F21) | Section 8. **This is the verdict.** |

### 0.1 Required before this verdict can become PASS

| ID | Required action | Section |
|---|---|---|
| **F17-R** | Track a mutation harness, or demote every unreproducible mutation claim in `docs/PROGRESS.md` to **attester-reported, UNREPRODUCED**, and say so wherever a mark cites one. SR-16's claim-evidence matrix cannot be sound while this is open. | 8.1 |
| **F16** | `scripts/demo.py:137-138` prints `verdict JOINT_SUPPORTED` with no conditionality marker; `EVALUATION_PROTOCOL.md:126` says such a verdict **"must be reported as `JOINT_SUPPORTED (conditional on deferred checks: <list>)`"** and that "the document and the code are required to tell the same story". The dashboard complies; the demo does not. Same defect class as the closed F2. | 4.3 |
| **F18** | `docs/EVALUATION_PROTOCOL.md:3` states **"r10 has not been independently reviewed"**, inside a sentence opening *"Version history, stated exactly"*, while SR-09's `[x]` rests on `PROGRESS.md:6362` — *"SR-09 r10: PASS … No blocking findings."* A marked task's deliverable denies its own attestation. | 5.1 |
| **F20** | The suite's pass/fail is hostage to third-party `pytest11` entry-point plugins installed on the host. Measured at this HEAD: 4 failures in `test_scripts` on the ambient 3.13.5 interpreter, caused by a broken `llvmlite` plugin outside this repository; 0 failures with `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`. The kit already fixed the **absent**-optional-tool case (`ruff`, README:37); **present-but-broken** is the uncovered sibling. | 8.2 |
| **F21** | `benchmark.py` carries no admission for **containers**, and `JointResult.complete_gate_coverage` is a truth test (`return not self.deferred_gates`). Record it producer-side. Reproduced at this HEAD: a container holding the honest six whose `__len__` answers 0 makes the property return **True** while `tuple(joint.deferred_gates)` still yields six names — a result that contradicts itself. | 8.3 |

Advisory, not required: F7, F8, F9, F10, F19, M1, M2.

### 0.2 Why F17-R is graded here and not routed to SR-15

SR-11's marking entry routes the mutation-tooling gap to SR-15 and SR-16 and states it "does not block" SR-11's own mark. I agree with both halves and still grade it here, for a reason that belongs to SR-12 and to no other task. SR-12's clause is the only one in the blueprint that names **reproducible commands**, and SR-12 is the only task whose subject is *the project's claims about itself*. SR-15's clause is about the suite; SR-16's is about a matrix. Neither asks whether the evidence behind a checkbox can be re-derived by a stranger. That question is this task's, it is answerable, and the answer at this HEAD is no for the majority of the evidence. Routing it onward a third time would be the project's own recorded defect — a finding described rather than priced.

---

## 1. Method fidelity

### 1.1 What reproduces at this HEAD

SOURCE OBSERVED (C2). `docs/SOURCE_SNAPSHOT.json` parses to `ahead_by 2`, `behind_by_vs_merge_base 0`, `behind_by_vs_upstream_main 36`, **8** changed files, **914** additions, **138** deletions. Those figures agree with `README.md:12-13`, `docs/FORK_AUDIT.md:12-19` and `docs/DIFF_EVIDENCE.md:34-42`. Every 40-hex SHA in `README.md`, `FORK_AUDIT.md`, `DIFF_EVIDENCE.md`, `METHOD_AUDIT.md`, `SOURCE_SNAPSHOT.json` and `CLAUDE.md` has **exactly one spelling**: `12d5426…`, `5cbd18a…`, `e220924…`, plus `86507b6…` in `DIFF_EVIDENCE` and the snapshot. No variant, no drift.

### 1.2 What this review did NOT re-verify, and what that costs

UNKNOWN. The prior review verified the citations and the diff arithmetic against saved copies of `erasure_teacher_student.py` and `fork_only.diff` held in a session scratchpad (its commands C1–C4). **Those files are not in this repository and are not on this host.** I could not re-run C1–C4 and did not attempt a network fetch. Section 1's PASS is therefore **inherited from the prior review**, not re-earned: I confirmed that the numbers derived from that material are internally consistent and have not drifted, which is a weaker property than confirming they match the source.

This is itself an instance of F17-R: the evidence for the kit's single most load-bearing factual claim — *what the fork actually changed* — lives outside the repository. Unlike the mutation harnesses it is recoverable (the URLs and SHAs are recorded in `docs/DIFF_EVIDENCE.md` and the fetch is a documented human step), so it is a weaker instance. It is still an instance.

Carried forward unchanged, both advisory: **M1** (`FORK_AUDIT.md`, named in `CLAUDE.md` as source of truth #1, is not updated to the hedges METHOD_AUDIT later added) and **M2** (the "36 commits beyond the merge base" figure is time-varying; `DIFF_EVIDENCE.md:27` says so outright — *"UNKNOWN: the 36 figure is time-dependent"* — while `README.md:13` carries only a verification date and `FORK_AUDIT.md:9` only "as of audit"). Neither is wrong; both are weaker than the register they derive from.

---

## 2. Toy-to-source correspondence

**F6 — CLOSED, and closed well.** `src/toy/teacher_student.py:244-256` now carries an explicit paragraph headed **"THE SIGN DOES NOT CARRY OVER, and the analogy is misleading if read without this paragraph."** It states that the toy inflates by the row width, that the source's same mismatch is a factor of 42 sitting beside a `0.01` multiplier, that the net is **0.42 — a DEFLATION**, that "the toy's gradient goes up where the source's net goes down", and that the toy reproduces the *shape* and "not its magnitude and not its direction". It then declines the further claim: "Nothing here says the source's net 0.42 is harmful, or that it explains the author's 'gradient is high' note; METHOD_AUDIT records that cause as UNKNOWN." This is more than the finding asked for.

**F7 — STILL OPEN** (Low, advisory, unchanged). `teacher_student.py:238` still calls `per_masked_element` "The correct element count", a judgement the audit declines to make: `ERROR_REGISTER.md:98` says the register **"does not establish … that any particular loss scale is wrong for the method's purpose (the choice may be intentional)"**, and `METHOD_AUDIT.md:131` concludes only that the mismatch "by itself does **not** explain a *high* gradient".

**F8 — STILL OPEN** (Low, advisory, unchanged). `teacher_student.py:176-179`: "this rescale partially counteracts the displacement it is applied to" is true of the toy's single positive scalar; the source's per-atom map can also flip sign and is origin-dependent. The docstring does not say the toy property fails to carry over — which is exactly the omission F6's new paragraph repairs one function away. The fix is the same shape and three lines long.

Everything else in the prior review's correspondence table was re-read and still holds: each deliberate divergence is disclosed in the toy module, and no document frames a toy outcome as telling the reader anything about the fork.

---

## 3. Unknowns register

The 49-item register (U01–U49) in the prior review was re-read; nothing in it has been established since, and nothing established has been re-hedged into it. Two of its four defects are closed.

**F1 — CLOSED, verified at source.** `src/toy/checkpoint.py:13-18` now splits the claim in two: *"**SOURCE OBSERVED:** the keys differ, so a checkpoint written by the script would not load into the unmodified upstream sampler. **INFERENCE, not executed:** because upstream indexes the dict directly (and loads with `strict=True`), the expected failure is a loud `KeyError`, not a silent one."* The word "silently" is gone from both sites; the second site (`checkpoint.py:47-51`, the key-set guard) now reads "that failure is inferred, not executed, to be a loud KeyError". `git grep -n silent` over `src/` returns no occurrence attaching silence to the audited script.

**F5 — CLOSED.** `docs/CLEAN_CLONE.md:813-816` now states of the five `.env.example` flags: **"No code reads any of them"** and "`BIOLOGICAL_TRAINING_ENABLED=false` does not constrain anything." `README.md:30` carries an explicit, signed correction naming F5 and describing the real, structural protections. Verified independently (C6): `grep -rn "getenv\|os.environ" src/` returns **nothing**. Residual, not a defect in the required action: `.env.example` is itself a bare five-line file with no inert marker, so the quotable surface Q4 stands (section 4.2).

**F9 — STILL OPEN** (Low, advisory). `src/toy/stability.py:52` (was `:29`) still reads "a lenient toy would be more permissive than **the thing it mimics**", treating a conditional NaN hazard as a property of the source when ER-02 records the presence of NaN there as UNKNOWN.

**F10 — STILL OPEN by construction.** Commit messages `d87b48f` and `e436d93` state INFERENCE as "confirms" / "direct evidence". Commit messages are immutable; this can only ever be noted, and the journal has noted it.

---

## 4. Risk of incorrect safety claims

**This is the section SR-12 exists for, and it is the section that moved.** Re-run in full at this HEAD, hostile stance: a reader who wants to quote the kit as proof that the fork — or RFdiffusion — is safe, or that it is broken.

### 4.1 The direct question

**Does the kit anywhere state or imply that RFdiffusion, or any real model, is safe, or that a measured reduction in biohazardous capability exists?** **No.** SOURCE OBSERVED (C7): a `git grep` for `is safe|are safe|proven safe|shown safe|model is safe|safer model|reduc…(biohazard|hazardous|capability)|hazardous capability` across every tracked file except the journal and this report returns **27 hits, and every one of them is a denial, a guard test, or an unrelated technical use of the word "safe"**:

- Denials: `ERROR_REGISTER.md:8, 213`; `EVALUATION_PROTOCOL.md:4, 428` (*"It cannot establish … that any real checkpoint is safer; that RFdiffusion or the fork is safe or unsafe; that a real capability is reduced"*); `METHOD_AUDIT.md:3, 244` (claim 21, "The method is safe / yields a safer model" → **UNKNOWN; not asserted by this audit**); `FORK_AUDIT.md:33`; `claim_ledger.py:3`; `robustness.py:14`; `SR16_AUDIT_REPORT.md:138`.
- Guard tests, i.e. the string exists so that a test can assert the kit refuses to vouch for it: `test_benchmark.py:2593`, `test_claim_ledger.py:418, 1304`, `test_dashboard.py:290`, `test_failure_modes.py:310`, `claim_ledger.py:140`, `schema.py:59`.
- Unrelated: `"type(v) is safe"` in four modules, about `__class__` lookups.

The rendered dashboard opens and closes with **"NOTHING ON THIS PAGE IS EVIDENCE ABOUT RFdiffusion, THE FORK, OR ANY REAL BIOLOGICAL CAPABILITY. No result here bears on real-world safety."** (C5). `CLAUDE.md`'s absolute prohibition is honoured.

### 4.2 The two designed guards, and the one the prior review found broken

**Guard 1 (dashboard has no "confirmed" style) — holds**, unchanged.

**Guard 2 (`is_safety_claim`) — F15 CLOSED, verified not accepted.** C11 reproduced: three claims whose statement is *"safeRFdiffusion is safe and removes hazardous capability."* still reach `SUPPORTED` on one self-attesting reviewer and a hollow hash — that route is documented and was never F15. What F15 asked for is done: the field `is_safety_claim` is **gone**. `led.summary()[0]` now contains `"safety_claim_classification": "NOT_PERFORMED"` and a 70-word note beginning *"This ledger performs NO classification … The absence of a classification is NOT a finding that the claim is harmless or out of scope."* `"is_safety_claim" in summary` → **False**, so a stale consumer gets a `KeyError` rather than a confident `false`. `src/toy/claim_ledger.py:138-150` records the reasoning, including why documenting a constant was judged insufficient.

**Guard 3 — F4 CLOSED, and this is what moved area 4 off FAIL.** The prior review's Q1/F4 was the single High finding in this section: `JointResult` had no field recording fixture kind, so the dashboard rendered `Suppression … SUPPORTED` and `Joint verdict: JOINT_SUPPORTED` on a scorer-validation oracle with only a 12 px grey "(toy fixture; conditional; not a safety finding)". At this HEAD, `benchmark.py:2562-2563` adds `subject_kind` ('trained' | 'fixture' | 'unknown') and `fixture_name` (required iff kind is 'fixture'), both normalised and cross-checked in `__post_init__` against the gate list's exemption flag. The rendered page (C5, from `python3 scripts/demo.py`) now reads:

```
SCORER-VALIDATION FIXTURE
a test of the scorer on a fixture whose answer is known by construction;
NOT a result about any method, model or intervention
subject_kind is PRODUCER-ASSERTED: it records what the producer declared, not an
authenticated fact. …
H1 …  SUPPORTED  (SCORER-VALIDATION FIXTURE; conditional; not a safety finding)
Joint verdict: JOINT_SUPPORTED (SCORER-VALIDATION FIXTURE; conditional; not a
safety finding) CONDITIONAL on 6 unimplemented gate(s)
Attempted 30, failed 0. Complete gate coverage: NO.
```

Every verdict cell carries the kind. The producer-asserted limit is stated on the page rather than only in a docstring. A post-construction relabel is detected and reported as an integrity failure. This is a complete fix of F4 and better than the finding asked for.

### 4.3 Quotable surfaces at this HEAD

| Rank | Direction | Status | Note |
|---|---|---|---|
| Q1 | "safe" | **CLOSED** | Was F4. The oracle is now named on the page. |
| **Q2** | "safe" | **OPEN — F16** | `scripts/demo.py` `[3]` prints `verdict JOINT_SUPPORTED  [tests the scorer; says nothing about any method]`, then `DEMO OK … All checks passed.` The bracket is good and arguably stronger than "conditional" for a hostile-quoting purpose. It is still **not the form `EVALUATION_PROTOCOL.md:126` mandates**, in the same paragraph that says the document and the code must tell the same story. The dashboard complies; the demo, which the README tells a reader to run, does not. One string. |
| Q3 | "safe" | OPEN, advisory | `INVARIANCE_HOLDS` still reads as "holds"; the enum comment and docstring still say "not refuted on these seeds". Unchanged, Low. |
| Q4 | "safe" | OPEN, residual | `.env.example:3-4` still reads as a safety interlock when cropped. The docs now deny it (F5 closed); the file carries no marker of its own. |
| Q5 | "safe" | OPEN, documented | A hollow `SUPPORTED` is one hash away (C11). Disclosed in the module docstring and now beside a `NOT_PERFORMED` classification. |
| Q6 | "safe" | **OPEN, and the prior review's framing was wrong** | The prior review reported that the kit "prepends its own non-claim label to the user's claim". **Refuted at this HEAD (C12b):** the kit prepends nothing — the old fixture supplied `TOY_LABEL` itself. A record with `notes="model is safe; hazardous capability reduced 99%"`, or even `"VERIFIED SAFETY FINDING: model is safe"`, is accepted and rendered verbatim inside an `UNTRUSTED FREE TEXT (notes) - NOT EVIDENCE` box, under the page banner. The residual is real and unchanged in kind — the guard captions, it does not refuse — but it is the user's text beside the kit's captions, not the kit's label wrapped around the user's claim. |
| Q7, Q10 | both | OPEN, advisory | `PROGRESS.md:1384` "a **genuine** `JOINT_SUPPORTED`" (journal history, immutable by this project's convention); `README.md:1,3` "safety-replication agent kit" / "Reproduce and independently audit"; the `SAFETY_AUDIT_KIT_COMPLETE` promise token in `ORCHESTRATOR_PROMPT.md:11`. The kit replicates no result; README:5 and :47 now substantially qualify this. |
| Q13 | "safe" | **CLOSED** | Was F17. `CLEAN_CLONE.md:1042` now states plainly **"The CI workflow has never been executed."** Two bare Linux containers were measured at `81d450a` (1252/95/0 on 3.12.10 and 3.13.3) and the rows say what they are. `README.md:30,33` retract two earlier overclaims by name -- the host-egress claim and the remote-host claim, both **withdrawn** and deliberately not restated here, because restating a withdrawn guarantee inside a review of withdrawn guarantees is the defect this scan exists to catch -- and label hermeticity **unattested**. |

No new "safe"-direction surface was found. One new "broken"-direction item is F18 (section 5.1): a reader can now quote the kit's own protocol saying it was never reviewed.

---

## 5. Cross-document consistency

**F2 — CLOSED.** The gate-11 scope divergence is resolved **in the direction of the code, by a logged amendment**, which is the correct direction given the code shipped first. `EVALUATION_PROTOCOL.md:141` and `:249` now read "**Global (amendment A-1, post-hoc)**: H1, H2, H3 and JOINT are all INCONCLUSIVE. A true gate, not block-only", matching `benchmark.py:181-182` `"control_adequacy": "all"`. The amendment log at `:449-451` carries A-1 with its provenance, and `:460-497` records a correction to A-1's own first version for a false provenance claim, plus the pre-existing r2 divergence as a separate item. `git log -- docs/EVALUATION_PROTOCOL.md` confirms the file has moved r3 → r10 across six commits since.

**F3 — CLOSED.** `ERROR_REGISTER.md:3` now reads **"Status: QA-attested"** and `:191-213` carries a QA-status section naming the three passes, the scope of the attestation, the two caveats QA attached, and a closing paragraph restating what no amount of QA here establishes. The "nothing here is QA-attested yet" sentences are gone.

**F11 — CLOSED / NO LONGER APPLICABLE.** The stale 673/671 totals are gone. `README.md:47` now instructs: **"Do not take a test total from the documentation — a hard-coded count there has gone stale three times and is now deliberately absent; obtain it from a run."** Removing the figure rather than refreshing it is the right remedy and the kit applied it.

### 5.1 New finding

| ID | Severity | Finding |
|---|---|---|
| **F18** | **Medium** | **A marked task's deliverable denies its own attestation.** `docs/EVALUATION_PROTOCOL.md:3` states *"r9 was reviewed and FAILED (one blocking finding…); **r10 has not been independently reviewed**"*, inside a sentence that opens *"Version history, stated exactly"*. `PROGRESS.md:6362` records *"SR-09 r10: **PASS**. … **No blocking findings.**"*, and SR-09's `[x]` rests on exactly that PASS. The sentence was true when written and is false now. It is **deliberate**: the r10 reviewer declined to apply two one-phrase fixes because *"editing the document now would make the attested text and the live text differ — which is precisely the defect that unmarked SR-09 in the first place"* (`PROGRESS.md:6424-6428`). That reasoning is sound and the trade is real; it does not make the sentence true. `docs/SR16_AUDIT_REPORT.md` raised this and put it in its residuals register; it is still live at this HEAD. Minimum resolution: amend the sentence **and** re-attest, which the project's own rule requires anyway, or move the review-status sentence out of the attested body into a status line that is explicitly allowed to move. |

---

## 6. `docs/PROGRESS.md` honesty audit and `BUILD_BLUEPRINT.md` attestation audit

### 6.1 Checkbox and dependency audit, re-derived

SOURCE OBSERVED (C16, a script that parses the blueprint rather than reading it). **13 of the 17 in-scope tasks (SR-00…SR-16) are `[x]`**; SR-12, SR-14, SR-15, SR-16 are open, and SR-17 is out of scope and `[ ]`.

**No marked task has an unchecked dependency.** Verified independently of the orchestrator's claim: for all 18 rows the `UNCHECKED_DEPS` set is empty for every `[x]` row. The only non-empty sets are on unchecked rows (SR-15 on SR-12 and SR-14; SR-16 on SR-15; SR-17 on SR-16), which is correct.

**F12 — CLOSED.** The condition that produced it (SR-11 `[x]` over unchecked SR-10; SR-14 `[x]` over unchecked SR-13) cannot now hold anywhere in the file. More than that, the rule has been internalised: `PROGRESS.md:6431-6438` records SR-09 holding an independent PASS and **declining to mark itself** because SR-04 was unmarked, naming F12 as the reason.

**F13 — CLOSED.** `PROGRESS.md:1974` is a full `## SR-05 — QA verdict: PASS` section whose opening sentence is *"This section exists because SR-12 found SR-05 had been marked `[x]` with no recorded QA verdict anywhere in this journal."* It records all three acceptance properties verified by the reviewer's own probes with figures, and all six post-PASS fixes re-verified by mutation in a scratch copy. `SR-00` also has a QA-verdict heading now (grep → 1).

**F14 — CLOSED, and generalised into a rule.** The protocol's last commit is `46bf2ee` (r10); SR-09's attestation is at `81d450a`, which is **later**. `git log -- docs/EVALUATION_PROTOCOL.md` shows no commit after `46bf2ee`. **The attested text is the committed text.** The project also turned F14 into standing practice — see the quotation in F18 — which is a stronger outcome than the finding asked for.

### 6.2 Audit of the four marks made since the prior review

Audited the way section 6.1 of the prior review audited the earlier ones: for each, does a real QA **PASS** record exist in `docs/PROGRESS.md` carrying task ID, evidence, commands, results, remaining uncertainty and commit SHA as `CLAUDE.md` requires, and is the attested text the committed text?

| Task | Marking commit | QA PASS record | ID | Evidence | Commands | Results | Uncertainty | SHAs | Attested == committed | Verdict |
|---|---|---|---|---|---|---|---|---|---|---|
| **SR-06** | `a04efa4` | `PROGRESS.md:11314` | yes, clause quoted from `BUILD_BLUEPRINT.md:15` | 11 real-defect mutants KILLED, 1 proven equivalent, 67 verdict-flip cases, ~20k cells over six environments, single-conversion-read measured, independent route enumeration 46 − 2 = 44 agreeing | per-module on both interpreters × {normal, `-OO`} × {numpy, none}; two-interpreter matrix | full suite 1466/0 at the marked tree | **5 items**, incl. the raising-`__class__` channel OPEN at 28 of 44 routes and an explicit *"Marking SR-06 does not close it and must not be read as closing it"* | `4982b90`, `ab46e0e`, `d9a0dfe` | `stability.py` last commit is `d9a0dfe`, within the attested set; the entry proves the three commits are documentation-and-test only by **AST comparison with docstrings stripped** | **OK** |
| **SR-10** | `96aed7c` | `PROGRESS.md:11989` | yes, clause quoted | determinism bit-exact (two digests over hashseed × interpreter × repeat); CIs reproduce bitwise from records; no shared RNG (5 sites); failed seeds do not perturb survivors; statistics validated against a 40-dps mpmath reference; the FAIL (six routes past the min-seeds floor) and its close | per-module × both interpreters × {normal, `-OO`}; `run_tests.sh --expect none --twice`; baseline regenerated | bare-venv 1482/90/0; full suite 1482/0 both interpreters | **6 items**, incl. the record-label channel OPEN with a pin that fails when it closes, and bootstrap order-dependence measured at 57 distinct `boot_lo` values | `775dedf`, `afe94eb` | `benchmark.py` has no commit after `afe94eb` other than this entry's own | **OK** |
| **SR-11** | `34f303a` | `PROGRESS.md:12317` | yes, clause quoted | 30 write routes driven from the code (14/14 supported-API writes refused), 8 killing mutants on the immutability machinery; the FAIL (`assert_no_silent_default` certifying from zero fixtures) and its structural cause; the attester planting a **new public certifier in both bookkeeping tables** so only behaviour could see it — and it was caught | per-module × both interpreters × {bare, `-OO`}; `--expect none --twice`; baseline regenerated | bare-venv 1488/90/0; full suite 1488/0 both | **5 items**, incl. the `vars()` write route OPEN with its measurement, and `_check_seeds`'s `int.__int__` declared redundant | `968ebc9` | `robustness.py` has no commit after `968ebc9` | **OK** |
| **SR-13** | `9621e42` | `PROGRESS.md:12524` | yes, clause quoted | half 1 smoke test measured on both interpreters × {plain, `-OO`} with byte counts, section counts, CSP, and zero hits for biological-generator markers; half 2 failed verbatim at HEAD through the **fully public API with no `object.__setattr__`** and was closed; attester's own 9-site × 3-shape sweep, 27 forgeries, 0 findings on three environments | per-module × both × {plain, `-OO`}; `--expect none --twice`; baseline regenerated | bare-venv **1493/90/0, run1 == run2** | **4 items**, plus the producer-side gap routed to this review | `e997943` | `dashboard.py` has no commit after `e997943` | **OK** |

**All four are sound records** and are markedly better than the project's earlier ones: each quotes its blueprint clause verbatim, each records a FAIL before the PASS, each lists remaining uncertainty as open rather than closed, and each ends with an "orchestrator errors this task" section counting the integrator's own mistakes (six on SR-10, two on SR-11, zero on SR-13). I found no case where the attested text differs from the committed text, and no case where a mark rests on a build alone.

**One qualification, and it is F17-R again.** In all four, the decisive evidence is mutation evidence — "11 mutants KILLED", "8 killing mutants", "a mutant that sorts inside `bootstrap_means` kills it", "proved at AST level". None of it is re-runnable from this repository (section 8.1). The records are internally excellent and externally unverifiable.

### 6.3 New finding

| ID | Severity | Finding |
|---|---|---|
| **F19** | **Low (process)** | **The journal's attestation ordinals contradict each other and the contradiction is recorded as unresolved.** Numeric labels and word ordinals disagree: SR-13 is labelled `(4th)`, `(5th)`, `(6th)`, `(8th)` — **no `(7th)`** — then "fails **tenth**" (`:9988`) and "**eleventh** attestation" (`:12424`); SR-11 runs `(6th)`, `(7th)`, then "fails **eighth**" (`:10191`). `PROGRESS.md:8631-8633` states the problem in the journal's own words — *"the journal's own ordinals disagree with the count … **Which series is authoritative is UNKNOWN**"* — and a sweep of everything after that line finds **no resolution**. The orchestrator quoted these counts to reviewers before catching it. **Judgement: this matters, but less than it looks, and not for the reason it first appears.** It is not cosmetic, because the ordinals are the only record of how many independent passes a mark rests on, and "nine FAILs then a PASS" and "five FAILs then a PASS" are different claims about a checkbox. It is nonetheless Low, because the *substance* each ordinal labels is intact and individually datable from `git log` and the section headings — the count is recoverable by derivation, which is this project's own prescribed remedy ("a verified list is derivable from `docs/BUILD_BLUEPRINT.md` and should be derived, not typed"). The integrity defect is that a **typed** figure was relayed as authoritative; the audit's substance does not rest on it. Minimum fix: derive the counts once and state that the typed labels are historical. |

### 6.4 SR-14: may it be marked on its old PASS?

**The premise routed to me is refuted. SR-14's attestation is against bytes that still exist.**

The concern was that `79be9d4` recorded SR-14's PASS and that `50cb3d3` and `3869655` then modified `src/toy/claim_ledger.py`, making the attestation F14-shaped. That is true **of the PASS the prior review cited**, and the prior review's F12 correctly unmarked SR-14 on a different ground. But SR-14 has been **independently re-attested twice since**, and the later of the two is after every change to its files (C18):

- `8e3faf2` — round-3 record, "SR-11/14 PASS unmarked". **Older** than `3869655`.
- `3869655` — last commit to touch `src/toy/claim_ledger.py`.
- `958cd0f` — last commit to touch `tests/toy_tests/test_claim_ledger.py`.
- **`eef9341`** — `PROGRESS.md:5097`, *"SR-14 — PASS a third time, and re-measured rather than re-read"*: 500 transition combinations (5 accepted, 0 illegal acceptances, 0 legal refusals), 6 events × 14 fields × 9 values = 738 forgeries, 0 accepted, both documented residuals open and unchanged, and `N1` recorded as surviving *"neither closed nor silently fixed"*. **Newer** than both.

Verified: `git diff eef9341 HEAD -- src/toy/claim_ledger.py tests/toy_tests/test_claim_ledger.py` is **empty**. The module imports only three names from a file that did change (`src/toy/schema.py`, +242/−11 since): `EvidenceClass`, `TOY_LABEL` and `canonical_json`. I compared all three by AST at `eef9341` and at HEAD — **all three identical** (C19). `SCHEMA_VERSION` likewise.

**Plain statement: SR-14's existing PASS is a valid attestation of the committed bytes, and nothing in F14's shape blocks marking it.** Two things that are *not* byte questions, and that are the orchestrator's call rather than mine:

1. **The PASS is dated 2026-11-10, round 4.** Twenty-three attestation rounds have happened since, during which this project discovered four defect classes it had not been testing for — the parameter lane, the probe lane, the element lane, and the container/`__len__` lane — and those discoveries unmarked SR-04, SR-06, SR-09 and SR-10 and failed SR-11 and SR-13 repeatedly. `claim_ledger.py` has never been swept for any of them. SR-14's PASS is sound **by the standard in force when it was given**; whether that standard is the one now applied to this kit's other modules is a question with an obvious answer.
2. SR-14's blueprint clause ("duplicate event/idempotency and invalid transition tests") is narrower than the clauses those sweeps failed, so the gap may well be immaterial. **That is INFERENCE, not a measurement**, and I did not drive a lying container or a duck-typed operand into the ledger to check.

---

## 7. Status of every finding in the superseded review

| ID | Prior severity | **Status at `9621e42`** | Evidence |
|---|---|---|---|
| F1 | Medium-High | **CLOSED** | `checkpoint.py:13-18, 47-51`; §3 |
| F2 | High | **CLOSED** | protocol r10 §141, §249 vs `benchmark.py:181-182`; amendment A-1 logged; §5 |
| F3 | Medium | **CLOSED** | `ERROR_REGISTER.md:3, 191-213`; §5 |
| F4 | High | **CLOSED (verified, not accepted)** | `benchmark.py:2562-2563`; rendered page, C5; §4.2 |
| F5 | Medium | **CLOSED** (Q4 residual) | `CLEAN_CLONE.md:813-816`; `README.md:30`; C6; §3 |
| F6 | Medium | **CLOSED** | `teacher_student.py:244-256`; §2 |
| F7 | Low | **STILL OPEN** (advisory) | `teacher_student.py:238` |
| F8 | Low | **STILL OPEN** (advisory) | `teacher_student.py:176-179` |
| F9 | Low | **STILL OPEN** (advisory) | `stability.py:52` |
| F10 | Low | **STILL OPEN by construction** | immutable commit messages |
| F11 | Low | **NO LONGER APPLICABLE** | figure removed, not refreshed; `README.md:47` |
| F12 | High (process) | **CLOSED** | C16; §6.1 |
| F13 | Medium (process) | **CLOSED** | `PROGRESS.md:1974` |
| F14 | Medium (process) | **CLOSED, and generalised into a rule** | `git log -- docs/EVALUATION_PROTOCOL.md`; `PROGRESS.md:6424-6428` |
| F15 | Medium | **CLOSED (verified, not accepted)** | `claim_ledger.py:138-150`; C11; §4.2 |
| F16 | Low | **STILL OPEN, re-graded Medium** | `scripts/demo.py:137-138` vs protocol `:126`; §4.3 |
| F17 | Low | **CLOSED** | `CLEAN_CLONE.md:1042`; §4.3 Q13 |
| M1–M4 | Low/Info | M1, M2 **STILL OPEN** (advisory); M3, M4 immaterial | §1.2 |

**New at this HEAD:** F17-R (§8.1), F18 (§5.1), F19 (§6.3), F20 (§8.2), F21 (§8.3).

---

## 8. Reproducibility — the area that fails

### 8.1 F17-R: the evidentiary base is not reproducible from a clone

SOURCE OBSERVED (C20), verified independently rather than taken from the brief:

```
git ls-files | grep -iE "mutat|mutant"      →  (nothing)
git ls-files scripts/                        →  demo.py  lint.sh  run_tests.sh  test_baseline.txt
grep -ci killed  docs/PROGRESS.md            →  260
grep -ciE '\bmutant' docs/PROGRESS.md        →  276
```

**No mutation tooling has ever been tracked in this repository.** Every harness built across roughly 27 attestation rounds lived in a session scratchpad and is gone. The journal records this itself, in SR-11's marking entry, in the strongest terms available to it: *"every mutation result in this journal — hundreds of KILLED/unkilled claims, including most of the evidence behind the marks — is UNREPRODUCIBLE FROM THE REPOSITORY."*

**Judgement of what it costs.** Three things, in order:

1. **The claims most of the marks rest on cannot be checked by anyone.** Section 6.2's four marks are typical, not exceptional: the decisive line in each is a mutation count. SR-04, SR-05 and SR-08's records are the same shape. A reader who clones this repository can reproduce **every test count, every skip, the determinism property, the demo, the dashboard bytes and the lint result** — I did, in section 9 — and **not one** KILLED claim. The project's own standard, stated in `CLAUDE.md` and applied repeatedly to its own owners, is that *a count of a construct is not a measurement of its behaviour* and that an asserted enumeration must be performed. By that standard, 260 lines of this journal are assertions.
2. **It is not total, and saying so would be the opposite error.** Mutation evidence supports a claim of the form "this test catches that defect". Where the journal names the edit precisely — and often it does, e.g. *"a mutant that sorts inside `bootstrap_means` kills it"*, *"reverting to `(5,5)` is KILLED"* — a reader **can** re-derive the kill by hand in a scratch copy and a targeted test run, which `CLAUDE.md` itself notes is logically sufficient for a KILL. What is irrecoverable is the **set**: which mutants were generated, by what rule, at which sites, and therefore what a **survivor** means. SURVIVE claims, which assert that *nothing* catches a mutant, are the ones that are simply gone. The journal's own equivalence arguments (SR-06's one equivalent mutant; SR-14's `N1`) are in that category.
3. **It compounds, because the kit is a provenance kit.** This is a project whose subject is whether other people's safety claims are supported by reproducible evidence, and whose own central finding across 27 rounds is that *a sentence describing a mechanism's reach is not the mechanism*. Its own strongest evidence is a set of sentences describing mutation runs. The asymmetry is the finding.

**This does not retroactively invalidate any mark.** Each of the four audited in 6.2 was attested by someone who built their own harness and re-derived the figures independently, which is a real control and better than re-reading. It does mean that **SR-16's claim-evidence matrix cannot be sound as currently conceived**, since the "evidence" column for most marks would have to read UNREPRODUCED, and that **SR-15's "complete offline regression suite passes" is a narrower guarantee than the project's evidence base**.

### 8.2 F20: the suite's pass/fail is hostage to third-party pytest plugins

**Measured at this HEAD (C14), serially, caches cleared, `PYTHONDONTWRITEBYTECODE=1`:**

| Run | Result |
|---|---|
| 3.12.4 (`/Library/Frameworks/…/3.12/bin/python3`, numpy 2.4.6, torch 2.7.1), `unittest discover` | **Ran 1493 tests — OK (skipped=2)** |
| 3.13.5 (ambient `python3`, numpy 2.4.4, no torch), `unittest discover` | **Ran 1493 tests — FAILED (failures=4, skipped=84)** |
| 3.13.5, same command, `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`, `test_scripts` only | **Ran 156 tests — OK** |
| bare venv 3.12.4 (`--without-pip`, nothing third-party), `./scripts/run_tests.sh --expect none --twice` | **`RESULT: OK` — ran=1493 skipped=90 failed=0; `deterministic: run1 == run2`, identical per-module counts and skip list** |

The four failures are `test_scripts.TestRunTestsMechanics.{test_pytest_failing_while_unittest_passes_is_POLICY_PYTEST_FAILED, test_pytest_skip_count_mismatch_is_compared, test_pytest_unittest_count_mismatch_fails}` and `TestRunTestsPolicyDetails.test_pytest_unittest_skip_count_mismatch_fails`. All four spawn `scripts/run_tests.sh` with pytest enabled; all four fail with `POLICY:PYTEST_FAILED` / `POLICY:PYTEST_COLLECTED pytest collected 0 tests`, and the sub-run's log carries:

```
OSError: Could not find/load shared object file 'libllvmlite.dylib'
        from resource location: 'llvmlite.binding'
```

**Attributed, not guessed.** The same crash reproduces from `python3 -m pytest -q .` in an empty scratch directory containing one trivial passing test, i.e. it is a property of the host's miniconda environment and not of this repository. The cause is a broken `llvmlite`/`numba` installation reached through a `pytest11` entry point; `importlib.metadata.entry_points(group='pytest11')` on that interpreter lists seven third-party plugins. Disabling autoload turns the module green.

**Why it is a finding and not just a broken laptop.** `README.md:33` says the documented commands "need only Python 3.12+ and no network or credentials". That is true of a bare interpreter — the fourth row proves it. It is **not** true of a developer machine, where whether the suite passes is decided by `pytest11` entry points that nothing in this kit installs, declares or bounds. This kit has already been bitten by exactly this class once and fixed half of it: `README.md:37` records that *"for one round the commands below failed on any machine without `ruff`"*, and the fix was that "an absent optional tool now changes **which tests run**, never whether the suite passes." **A present-but-broken optional tool is the uncovered half of that same sentence**, and it is live. Minimum fixes, either sufficient: have `run_tests.sh` treat a pytest process that crashes before collection as `pytest unusable → skipped` with a loud note rather than `POLICY:PYTEST_FAILED`; or set `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1` for the sub-run and document it.

**This also corrects a figure I was given.** "Full suite 1493 ran / 0 failed on both interpreters" reproduces exactly on 3.12.4 and **does not** reproduce on the ambient 3.13.5 interpreter in this environment without `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`. The ran count (1493) and the skip count (84) match; the failure count does not.

### 8.3 F21: a producer-side container gap in `benchmark.py`

**Reproduced at this HEAD (C21), through class-level assignment with no `object.__setattr__` and no instance mutation:**

```
HONEST:  verdict JOINT_SUPPORTED | complete_gate_coverage = False | len(deferred) 6
ROUTE A (bm.JointResult.deferred_gates = a tuple subclass holding the honest six
          whose __len__ answers 0):
         complete_gate_coverage = True
         tuple(joint.deferred_gates) -> 6 names still present
ROUTE B (object.__setattr__ on the instance):   complete_gate_coverage = True
ROUTE C (plain assignment):  FrozenInstanceError cannot assign to field 'deferred_gates'
```

`JointResult.complete_gate_coverage` is `return not self.deferred_gates` (`benchmark.py:2650-2651`), a truth test, so the container's `__len__` decides a flag whose meaning is *"every protocol check has been implemented and run"*. The result object then **contradicts itself**: the flag says coverage is complete and the list it is derived from still holds six names.

**Judgement on the routing: it was right. SR-10 should NOT be unmarked.** Three grounds, the first two agreeing with the attester and the third correcting the reason recorded for the agreement:

1. **The clause.** SR-10's blueprint clause is *"statistical test fixtures and repeatability"*. `complete_gate_coverage` is neither a statistic nor an interval. For every value the module's own constructors can produce it is correct, deterministic and repeatable — measured above.
2. **No public argument reaches it.** `deferred_gates` is **not a dataclass field** (C21: `dataclasses.fields(JointResult)` lists 15 names, and `deferred_gates` is not among them); the constructor rejects it as a keyword; `dataclasses.replace` cannot set it; the frozen `__setattr__` refuses it. The only routes are patching the class object or `object.__setattr__`. A caller who can do the former can equally replace `DEFERRED_GATES`, `GATE_SCOPES` or `combine_joint`; under that threat model nothing in any module is defensible, and it is not the threat model that failed SR-11 or SR-13 — in both of those the hostile object arrived as an **argument to a public function**.
3. **The reason recorded for the agreement is wrong, and the right reason is stronger.** `PROGRESS.md:12613` says *"the forgery needs post-construction `object.__setattr__`"*. It does not: Route A above is a class-attribute assignment and reproduces the flag flip. `benchmark.py:115-116` already documents the class-level route — but with the payload `()`, an **honestly empty** tuple, which makes the flag and the list agree. The lying container is a different outcome: not "coverage was redefined" but "the object now contradicts itself". The defensible reason to keep SR-10 marked is **"nothing a caller can pass reaches this"**, not "it needs `object.__setattr__`" — and the distinction matters, because this project's own rule is that *"I needed `object.__setattr__` to reproduce it"* is a smell that should send you back to re-check the public route. Someone did send me back, and the public route is genuinely closed; the sentence that said why was not.

**Recorded producer-side, as the attester's condition required, and not as "the dashboard handles it."** `dashboard.py` does handle it, completely and deliberately: `dashboard.py:2448-2457` reads both the flag and the list and raises `deferred_ok = deferred is not None and cover is not bool(deferred)`, rendering *"NO (the result's own deferred-gate list CONTRADICTS its complete_gate_coverage flag, which the scorer derives from that list; the list is what is shown)"* and withholding every decisive verdict. That is one consumer's cross-check, and the finding survives it on three grounds: `git grep complete_gate_coverage` shows `dashboard.py` is today the **only** reader outside tests and the two protocol paragraphs; **nothing makes the next reader cross-check**, and SR-14, SR-15 and SR-16 may each add one; and `benchmark.py` carries `_plain_number`, `_plain_parameter`, `_metric_read`, `_plain_word`, `_plain_word_fields` and three declared lane tables (`PROBE_LANE_CONSTANT_LOOKUPS`, `ELEMENT_LANE_ATTRIBUTE_READS`, `KEY_LANE_…`) for stored **values**, **attributes** and **keys**, and **nothing whatever for containers** (C21: the string `CONTAINER` does not occur in the file). That is a categorical gap with three precedents in the same module for how it is normally closed. The cheapest honest producer-side fix is one line — derive the flag from a materialised read, `return not tuple(self.deferred_gates)`, or better, report a contradiction rather than a boolean.

**Credit where due:** `EVALUATION_PROTOCOL.md:126` and `:260` already disclose that the flag "is derived from a class-level list that code could override; not tamper-proof", so the protocol does not overclaim. The defect is that the producer's own self-consistency is left to a consumer.

---

## 9. Reproducible commands and recorded output

Every command below was run at HEAD `9621e42` with a clean tree, caches cleared, `PYTHONDONTWRITEBYTECODE=1`, and **serially — nothing ran alongside a suite**. Each row says whether it reproduces from a clean clone.

```sh
KIT=/Users/shrey/Projects/safeRFd/safe_rf_safety_agent_kit
S=<session scratchpad>/qa12
cd $KIT && git rev-parse --short HEAD && git status --porcelain
```
→ `9621e42`, then nothing. **Reproduces from a clean clone at this commit.**

### C2. Snapshot arithmetic and SHA spellings — **reproduces**

```sh
python3 -c "import json;d=json.load(open('docs/SOURCE_SNAPSHOT.json'));print(d['ahead_by'],d['behind_by_vs_merge_base'],d['behind_by_vs_upstream_main'],len(d['changed_files']),sum(f['additions'] for f in d['changed_files']),sum(f['deletions'] for f in d['changed_files']))"
for f in README.md docs/FORK_AUDIT.md docs/DIFF_EVIDENCE.md docs/METHOD_AUDIT.md docs/SOURCE_SNAPSHOT.json CLAUDE.md; do echo -n "$f: "; grep -o '\b[0-9a-f]\{40\}\b' $f | sort -u | tr '\n' ' '; echo; done
```
→ `2 0 36 8 914 138`; one spelling per SHA in every file (§1.1).

### C5. Demo and dashboard — **reproduces** (byte counts are timestamp-pinned in the demo)

```sh
find . -name __pycache__ -type d -not -path './.git/*' -prune -exec rm -rf {} +
PYTHONDONTWRITEBYTECODE=1 python3 -B scripts/demo.py --keep > $S/demo.out 2>&1; echo rc=$?
D=$(sed -n 's/^--keep: outputs left in //p' $S/demo.out); cp "$D/dashboard.html" $S/dash.html && rm -rf "$D"
python3 -B -c "import re,html;s=open('$S/dash.html').read();print(html.unescape(re.sub(r'<[^>]+>','\n',re.sub(r'<style.*?</style>','',s,flags=re.S))))" > $S/dash.txt
grep -n -i 'SUPPORTED\|coverage\|fixture\|conditional\|deferred' $S/dash.txt
```
`rc=0`. Demo output verbatim is in §4.3 Q2; the dashboard excerpt is in §4.2. Page: 29,375 bytes, byte-identical on re-render.

### C6. Inert environment flags — **reproduces**

```sh
grep -rn "getenv\|os.environ" src/
```
→ nothing.

### C7. Hostile safety-claim sweep — **reproduces**

```sh
git grep -n -iE "is safe|are safe|proven safe|shown safe|model is safe|safer model|reduc[a-z]* (in |of )?(biohazard|hazardous|capability)|hazardous capability" -- ':!docs/PROGRESS.md' ':!docs/SR12_INDEPENDENT_REVIEW.md'
```
→ 27 hits, classified in §4.1. No affirmative claim.

### C11 / C12 / C12b. Ledger and free-text probes — **reproduce** (scripts in §9 of the superseded text, re-run with the current API)

C11 output: three `SUPPORTED` states; summary contains `"safety_claim_classification": "NOT_PERFORMED"`; `"is_safety_claim" in summary` → `False`.
C12b output: `notes="model is safe; hazardous capability reduced 99%"` **accepted**, rendered verbatim under `UNTRUSTED FREE TEXT (notes) - NOT EVIDENCE`; `notes="VERIFIED SAFETY FINDING: model is safe"` likewise. The kit prepends no label of its own (§4.3 Q6).

### C14. The suites — **three of four rows reproduce from a clean clone; one is host-dependent**

```sh
find . -name __pycache__ -type d -not -path './.git/*' -prune -exec rm -rf {} +
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src /Library/Frameworks/Python.framework/Versions/3.12/bin/python3 -B -m unittest discover -s tests
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python3 -B -m unittest discover -s tests
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python3 -B -m unittest tests.toy_tests.test_scripts
/Library/Frameworks/Python.framework/Versions/3.12/bin/python3 -m venv --without-pip $S/venv
PATH="$S/venv/bin:$PATH" ./scripts/run_tests.sh --expect none --twice
```

| | Result | Reproduces? |
|---|---|---|
| 3.12.4 | `Ran 1493 tests in 373.654s` / `OK (skipped=2)` | yes |
| 3.13.5, as-is | `Ran 1493 tests in 248.546s` / `FAILED (failures=4, skipped=84)` | **host-dependent — see F20**; the 4 failures are caused by a broken third-party pytest plugin outside this repository |
| 3.13.5, plugins off, `test_scripts` | `Ran 156 tests in 61.378s` / `OK` | yes |
| bare venv, `run_tests.sh --expect none --twice` | `unittest: ran=1493 skipped=90 failed=0 rc=0`; `deterministic: run1 == run2 (… identical per-module counts and skip list)`; `RESULT: OK` | yes — **this is the clean-clone row** |

`git status --porcelain` empty and no `__pycache__` after every run.

**Baseline check, re-derived:** Σ `scripts/test_baseline.txt` test column = `4+354+48+100+265+17+20+203+55+156+106+55+110` = **1493**, i.e. **zero slack** against the measured total. The bare run's `RESULT: OK` in `--expect none` mode includes the per-module `POLICY:BASELINE_SKIPS` and test-count comparisons, so the floor is enforced and met.

### C15. The 90-vs-89 skip reconciliation — **reproduces, and closes an UNKNOWN**

`docs/SR16_AUDIT_REPORT.md` left open: *"the bare skip total **90** against the baseline column's **89** … the identity of the excluded skip is **UNKNOWN**."* Measured:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src $S/venv/bin/python3 -B -m unittest tests.toy_tests.test_scripts -v 2>&1 | grep -i skipped | sed "s/.*skipped //" | sort | uniq -c
```
→ `4 'pytest not installed (optional)'`, `1 'PyYAML not installed (optional); structural text checks above still ran'`, `OK (skipped=5)`.

Σ baseline skip column = `0+0+0+0+0+0+2+0+0+4+1+0+82` = **89**; `test_scripts` runs **5** skips against a baseline column of **4**. **The excluded skip is the single PyYAML skip in `toy_tests.test_scripts`**, dropped from the baseline column by `run_tests.sh`'s `BASE_EXCL` "yaml" rule. 89 + 1 = 90. **No longer UNKNOWN.** (The run reports "90 skipped across 4 modules", and exactly four modules carry a non-zero baseline column, so no other module can carry the extra.)

### C16. Checkbox and dependency audit — **reproduces**

```sh
python3 -B - <<'PY'
import re
bp=open('docs/BUILD_BLUEPRINT.md').read().splitlines()
tasks={}; order=[]
for l in bp:
    m=re.match(r'- \[( |x)\] \*\*(SR-\d\d)\*\*.*?\*\*Depends:\*\* ([^.]*)\.',l)
    if m: tasks[m.group(2)]=(m.group(1)=='x',re.findall(r'SR-\d\d',m.group(3))); order.append(m.group(2))
for t in order:
    x,deps=tasks[t]; bad=[d for d in deps if not tasks.get(d,(False,))[0]]
    print(f"{t} [{'x' if x else ' '}] deps={deps} UNCHECKED_DEPS={bad}")
print("checked:",sum(1 for t in order if tasks[t][0]),"of",len(order))
PY
```
→ every `[x]` row has `UNCHECKED_DEPS=[]`; `checked: 13 of 18` (18 rows = SR-00…SR-17; **13 of the 17 in scope**).

### C18 / C19. SR-14's attested bytes — **reproduce**

```sh
git log --format='%h %s' -- src/toy/claim_ledger.py tests/toy_tests/test_claim_ledger.py
git log -S "PASS a third time, and re-measured rather than re-read" --format='%h %s' -- docs/PROGRESS.md
git diff --stat eef9341 HEAD -- src/toy/claim_ledger.py tests/toy_tests/test_claim_ledger.py     # empty
python3 -B - <<'PY'   # AST-compare the three imported schema symbols
import subprocess, ast, hashlib
src=lambda r: subprocess.run(['git','show',f'{r}:src/toy/schema.py'],capture_output=True,text=True).stdout
for name in ('canonical_json','EvidenceClass','TOY_LABEL','SCHEMA_VERSION'):
    h=[]
    for rev in ('eef9341','HEAD'):
        seg=None
        for n in ast.parse(src(rev)).body:
            if isinstance(n,(ast.FunctionDef,ast.ClassDef)) and n.name==name: seg=ast.unparse(n)
            if isinstance(n,ast.Assign) and any(getattr(x,'id',None)==name for x in n.targets): seg=ast.unparse(n)
        h.append(hashlib.sha256((seg or '').encode()).hexdigest()[:12])
    print(name, h, 'SAME' if h[0]==h[1] else 'DIFFERENT')
PY
```
→ diff empty; all four symbols `SAME`.

### C20. Mutation tooling — **reproduces**

```sh
git ls-files | grep -iE "mutat|mutant"; git ls-files scripts/
grep -ci killed docs/PROGRESS.md; grep -ciE '\bmutant' docs/PROGRESS.md
```
→ nothing; four files; 260; 276.

### C21. The container gap — **reproduces**

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python3 -B - <<'PY'
import sys, dataclasses; sys.dont_write_bytecode = True
from toy import benchmark as bm
cfg = bm.BenchmarkConfig(n_boot=200); fz = bm.freeze_seed_list(7, 30)
j = bm.run_study(fz, bm.fixture_oracle_gated, subject="demo scorer-validation fixture",
                 cfg=cfg, registered_digest=fz.digest)
print("HONEST:", j.verdict.value, j.complete_gate_coverage, len(j.deferred_gates))
class Lying(tuple):
    def __len__(self): return 0
L = Lying(bm.DEFERRED_GATES)
bm.JointResult.deferred_gates = L
print("ROUTE A:", j.complete_gate_coverage, "| names still present:", len(tuple(j.deferred_gates)))
bm.JointResult.deferred_gates = bm.DEFERRED_GATES
object.__setattr__(j, "deferred_gates", L); print("ROUTE B:", j.complete_gate_coverage)
object.__delattr__(j, "deferred_gates")
try: j.deferred_gates = L
except Exception as e: print("ROUTE C:", type(e).__name__)
print("fields:", [f.name for f in dataclasses.fields(bm.JointResult)])
print("'CONTAINER' in benchmark.py:", "CONTAINER" in open("src/toy/benchmark.py").read())
PY
```
Output is quoted verbatim in §8.3.

### C22. Lint — **reproduces**

```sh
./scripts/lint.sh
```
→ `LINT: OK`, rc=0. `ruff: OK`; 4 advisory unused-import warnings and 3 pyflakes findings, all advisory by design.

---

## 10. Limits of this review

- **The fork itself was not re-verified.** Section 1's PASS is inherited; the saved script and diff are not in this repository (§1.2). No network call was made, by this review or in any command above.
- **UNKNOWN:** every runtime behaviour of the fork. Not executed. INFERENCE claims stay INFERENCE.
- **I ran no mutation campaign of my own**, and so I did not independently confirm or refute any KILLED claim in the journal. That is the subject of F17-R, not an escape from it: building one harness for one claim would have told me about that claim, not about the 260.
- **I did not drive the four late-discovered defect lanes into `claim_ledger.py`** (§6.4 item 2). The gap is an avoided input and is recorded as a finding rather than glossed.
- **Hostile-reader coverage is bounded by what I thought to try.** I probed the dashboard record path, the ledger, the scorecard container lane and the environment flags; I did not probe the checkpoint, schema or robustness public APIs for quotable surfaces.
- **The 3.13.5 failure set is attributed to this host's environment** by reproducing the crash outside the repository and by clearing it with `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`. I did not reinstall `llvmlite` to confirm the converse.
- Scratch scripts were written to the session scratchpad only. Nothing in the repository was edited by this review except this file.

## 11. What a PASS would require

Close **F17-R**, **F16**, **F18**, **F20** and **F21** (section 0.1). The advisory items — F7, F8, F9, F10, F19, M1, M2 — are not blocking and several (F10, and the journal-history half of Q7) are immutable by this project's own conventions and can only be noted.

Nothing in this review changes the standing limits of the kit, and this sentence is carried forward from the superseded version because it is still exactly true: **no measured result about any real model exists, and none is claimed.** A passing demonstration does not establish a safer model.
