# SR-16 audit report — final independent QA, claim–evidence matrix, limitations, release note

**Reviewer:** independent QA, final pass. I wrote none of this kit's code, none of its documents, and
none of the prior reports. **Date:** 2026-11-13. **Kit HEAD audited:** `75f51e6`. **Working tree:**
clean (`git status --porcelain` empty) before, between every run, and immediately before this file was
written. **Files written by this pass:** this file and `docs/RELEASE_NOTE.md`. No commit, no code edit,
no checkbox edit, no test edit. SR-17 was not started and must not be.

**This file is a rewrite in place, not an update.** It supersedes the 2026-11-11 text written at HEAD
`d0441f5` (last committed at `fcdd3c2`), which remains readable in git history. The reasons for
replacing rather than patching are given in §0.3; the short form is that the old text's own status
header is false at this HEAD, several of its matrix rows cite attestations that have since been
superseded by *different* attestations after their tasks were unmarked and re-attested, and at least
two of its figures are stale by a factor. A 1,210-line document whose unpatched parts are of uncertain
currency is the exact "attested text vs live text" hazard this project has hit four times.

Labels, kept from `docs/SR12_INDEPENDENT_REVIEW.md:5` so the documents read together:
**MEASURED** (a command was run here and its output recorded in §9), **INFERENCE** (reasoned from
observed text, not executed), **UNKNOWN** (not determined). **Nothing in this report asserts that the
audited method works, fails, is safe, or is unsafe.**

---

## 0. Verdict

# FAIL

**Definition, the same one SR-12 used:** FAIL means *"reproducible defects exist that must be fixed
before the kit is described as complete."* It does **not** mean the audit documents are wrong about
the fork, it does **not** mean any task was done badly, and it is **not** a statement about
RFdiffusion, the safeRFdiffusion fork, or any real model.

### 0.1 The three verify clauses, judged separately

| # | Clause (`docs/BUILD_BLUEPRINT.md:29`) | Verdict | Carried by |
|---|---|---|---|
| 1 | **All accepted tasks supported** | **FAIL** | SR-00 is marked `[x]` with **no QA attestation section anywhere in the journal** (§1.2); and the decisive evidence class behind most marks is not reproducible from a clone (§3, SR-12's F17-R, settled here rather than routed on) |
| 2 | **No ungrounded statement that RFdiffusion is 'safe'** | **PASS**, two mechanism gaps | 73-hit widened hostile sweep over every tracked file, the rendered dashboard and the demo's stdout: **zero** claims (§2). Two of the kit's own disclaimer strings are unpinned by any test — I measured both surviving the full 1,493-test suite (§4) |
| 3 | **Reproducible demo passes** | **PASS** | rc=0 and `DEMO OK` on both interpreters from a clean clone, byte-identical dashboard across re-renders *and* across interpreters, and rc=0 under a live network denial on both (§5) |

**The overall verdict is FAIL on clause 1 alone.** Clause 1 is the clause that asks whether a stranger
can check what the checkboxes assert, and the answer at this HEAD is no for the majority of the
evidence and no at all for one task.

### 0.2 Is SR-16 itself complete? — a different question from its verdict

**Yes, SR-16 is complete as a task; no, SR-16 must not be marked `[x]`.** Both halves matter.

- **Complete.** The clause body names four deliverables — claim–evidence matrix, limitations,
  screenshot/demo, release note — plus the final independent QA. All five exist: §2, §6, §7, and
  `docs/RELEASE_NOTE.md`. A FAIL is a completed QA outcome, not an unfinished one.
- **Not markable.** SR-12 was marked `[x]` while returning FAIL on the kit, and that was correct:
  SR-12's clause is *"explicit PASS/FAIL/BLOCKED report, reproducible commands"*, which a FAIL report
  satisfies. **That move is not available to SR-16.** SR-16's clause does not ask for a verdict; it
  states a condition — *"all accepted tasks supported"* — and that condition is not met. Marking
  SR-16 `[x]` over a clause its own report grades FAIL would be the project's single worst
  checkbox, because SR-16 is the one a reader will treat as the project's self-assessment.

### 0.3 Why this file was rewritten rather than updated

MEASURED. Four defects in the superseded text, each checked at this HEAD:

1. Its status header (old `:3-6`) reads *"SR-15 is open — it has never passed an attestation, and one
   of its four claims ('offline') is **BLOCKED**."* SR-15 is `[x]` at `75f51e6` on an attestation
   recorded at `docs/PROGRESS.md:13044`, and the offline measurement was run at `17265e9`.
2. Its SR-06 matrix row cites the QA PASS at `PROGRESS.md:1004`. SR-06 was **unmarked** after that
   (`PROGRESS.md:8693`) and re-attested at `:11314`; the row therefore describes a superseded
   attestation, not the one the checkbox now rests on. The same applies to its SR-10, SR-11 and SR-13
   rows.
3. `1351` occurs 8 times as a suite total; the figure is **1493**. Its SR-06 row carries
   *"`test_stability` (57 tests, 1 bare-env skip)"*; `test_stability` is **106** tests.
4. Its §3.3 — a 45-line section — is titled *"'offline' is BLOCKED — no network-denied run has ever
   been attested"*. One has.

A patch would have had to touch the header, four matrix rows, eight figures and two whole sections,
leaving ~1,000 lines whose currency nobody had checked. `docs/SR12_INDEPENDENT_REVIEW.md` is itself a
rewrite in place of an earlier review, for the same reason and with the same carry-forward discipline;
this file follows that precedent. **Nothing of substance is discarded:** every finding of the old text
that is still live is carried forward in §7 with its status at this HEAD, and the old text is at
`fcdd3c2`.

---

## 1. Clause 1 — "all accepted tasks supported"

Four separate questions. They are not the same question, and the project has conflated them before.

### 1.1 Does any marked task have an unchecked dependency? — **No.** MEASURED, re-derived

Derived by a script that parses `docs/BUILD_BLUEPRINT.md` rather than reading it (§9, C1). 18 rows;
**16 of the 17 in-scope tasks (SR-00…SR-16) are `[x]`**; SR-16 is `[ ]` and SR-17 is out of scope and
`[ ]`. For every `[x]` row the set of unchecked dependencies is **empty**. The only non-empty set is
on SR-17, whose dependency SR-16 is correctly unchecked. This agrees with SR-12 §6.1 and was derived
independently of it.

### 1.2 Does every marked task have a QA attestation record? — **No. SR-00 has none.** MEASURED

`CLAUDE.md` is explicit twice over: *"Never mark a task `[x]` from a build alone; QA must
independently attest to its acceptance criteria"*, and *"After each task: record task ID, evidence,
commands, results, remaining uncertainty, and commit SHA."*

MEASURED (C2): `grep -c "^## SR-00 — QA verdict" docs/PROGRESS.md` → **0**. The only SR-00 section is
`PROGRESS.md:27`, *"## SR-00 — Scaffold, version control, provenance"*, which is the **builder's own**
record (`- **Task ID and date:** SR-00, 2026-11-09`). There is no independent QA verdict for SR-00
anywhere in the journal. SR-00 is the dependency of SR-01 and SR-04, and transitively of everything.

The journal knows. `PROGRESS.md:8677` records, parenthetically: *"(Its missing `## SR-00 — QA verdict`
section is still real: grep → **0**.)"* **A finding recorded in a parenthesis for five rounds and
never closed is still open**, and it is the kind of item this project elsewhere calls a reach claim:
the blueprint's "Definition of done" item 6 says *"Every verified task has QA evidence and a
descriptive commit"*, and for SR-00 that sentence is false.

Completeness of the other fifteen, MEASURED (C3), section-by-section against the six elements
`CLAUDE.md` names:

| Task | Attestation at | Lines | Commit SHA | Commands |
|---|---|---|---|---|
| SR-00 | **none** | — | — | — |
| SR-01 | `:145` | 20 | a sha256 **of the diff**, no commit SHA | no |
| SR-02 | `:1392` | 28 | yes | no |
| SR-03 | `:1421` | 50 | **no** | yes |
| SR-04 | `:6549` | 103 | yes | no |
| SR-05 | `:1974` | 44 | yes | no |
| SR-06 | `:11314` | 104 | yes | yes |
| SR-07 | `:2067` | 53 | **no** | no |
| SR-08 | `:1026` | 30 | **no** | no |
| SR-09 | `:6362` | 76 | yes | no |
| SR-10 | `:11989` | 107 | yes | yes |
| SR-11 | `:12317` | 104 | yes | yes |
| SR-12 | `:12666` | 150 | yes | yes |
| SR-13 | `:12524` | 141 | yes | yes |
| SR-14 | `:12817` | 133 | yes | yes |
| SR-15 | `:13044` | 121 | yes | yes |

**Read this table for its shape, not its cells.** The seven most recent records (SR-06, SR-10, SR-11,
SR-12, SR-13, SR-14, SR-15) are complete and, read in full, are genuinely good: each quotes its
blueprint clause verbatim, each records a FAIL before its PASS, each lists remaining uncertainty as
*open* rather than closed, and several count the orchestrator's own errors. The early records
(SR-01…SR-08, SR-09) are substantive in evidence — I read SR-01's and SR-07's in full and both
re-derive figures rather than accept them — but they predate the discipline, and three carry no commit
SHA at all. **This is a gradient, not a cliff**, and the direction is the right one.

**Caveat on the table, stated because the project's own rule demands it:** the SHA and commands
columns come from a regex over each section. A regex over a construct is not a measurement of what the
section establishes. I read SR-01, SR-05, SR-07 and SR-15 in full and found one false negative in my
own first scan (SR-14's `**Commands.**` line, which names modules rather than the word `unittest`).
Treat the two columns as a floor on completeness, not a verdict on quality.

### 1.3 Is the attested text the committed text? — **Yes, with one exception at this very HEAD.** MEASURED

MEASURED (C4), per task, comparing each deliverable's last-touching commit with its attestation:
`stability.py` → `d9a0dfe`, `benchmark.py` → `afe94eb`, `robustness.py` → `968ebc9`, `dashboard.py` →
`e997943`, `claim_ledger.py` → `3869655`, `EVALUATION_PROTOCOL.md` → `46bf2ee`, `schema.py` →
`46bf2ee`, `run_tests.sh` / `README.md` / `ci.yml` → `17265e9`. Every one of these precedes the
marking commit for its task. No drift.

**The exception is SR-15's own marking commit.** `75f51e6` changed three files:
`docs/BUILD_BLUEPRINT.md` (the checkbox), `docs/PROGRESS.md` (the record) **and
`docs/CLEAN_CLONE.md`** (+12/−3). `docs/CLEAN_CLONE.md` is an SR-15 deliverable — the clause says
"clean-clone instructions". The journal describes this as *"The required correction, applied before
marking"*. MEASURED: **git cannot place it before the attestation, because it is in the same commit as
the mark.** The attester measured a bullet in that file to be false; the orchestrator then rewrote the
bullet; nobody re-attested the rewritten text. This is a mild instance of the shape that unmarked
SR-09 (closed F14) — the edit *weakens* a claim rather than strengthening one, and I read the diff —
but it is the same shape, in the final mark, in the task whose subject is documentation fidelity.

**And the correction it describes is prose-only.** MEASURED (C5): the rewritten bullet says
*"The fix must therefore touch BOTH sites, not only `summarize()`."* No commit touches
`scripts/run_tests.sh` after `17265e9`, and both sites are still first-match at this HEAD —
`scripts/run_tests.sh:355` and `:993` each hold `re.search(r"^Ran (\d+) tests?", …)`. **So the remedy
is declared, not performed.** It cannot change any verdict (the captured transcript only exists
because a test already failed, so `POLICY:UNITTEST_FAILED` fires and the run is red either way); what
degrades is the diagnosis. Graded **Low**, logged as **F22** (§7), and noted here because a sentence
describing a fix is not the fix, which is this project's own headline finding appearing inside the
commit that closed its penultimate task.

### 1.4 Is the evidence reproducible from a clone? — **No, for the dominant evidence class.**

This is SR-12's **F17-R**, routed to SR-16 twice (by SR-11's marking entry and again by SR-15's:
*"SR-12's kit-level FAIL stands, and SR-16 inherits it — that is where F17-R must be settled"*). It is
settled in §3, not routed on.

---

## 2. Clause 2 — "no ungrounded statement that RFdiffusion is 'safe'"

### 2.1 The direct question

**Does the kit anywhere state or imply that RFdiffusion, the safeRFdiffusion fork, or any real model
is safe, or that a measured reduction in biohazardous capability exists? No.**

MEASURED (C6). I widened SR-12's pattern — which returned 27 hits — to add `was safe`, `verified
safe`, `certified safe`, `safer checkpoint`, `safety is/was established|demonstrated|shown|proven`,
`demonstrates safety`, `establishes safety`, `capability reduction`, `removes hazardous`,
`successfully unlearn|erase`, `unlearning works|succeeded|is effective`, `RFdiffusion is`,
`fork is safe|validated`, `proves`, `proven to`. Over every tracked file except the journal and the
two review documents it returns **73 hits across 28 files**. I classified all 73 by reading each line:

- **Denials and scope statements (16).** `README.md:3`; `ERROR_REGISTER.md:8, 213`;
  `EVALUATION_PROTOCOL.md:4, 428`; `METHOD_AUDIT.md:3, 242, 244, 256`; `FORK_AUDIT.md:33`;
  `DIFF_EVIDENCE.md:63`; `ORCHESTRATOR_PROMPT.md:9`; `claim_ledger.py:3`; `robustness.py:14, 219`;
  `tensor_ops.py:6`. `METHOD_AUDIT.md:244` still lists claim 21, *"The method is safe / yields a safer
  model"*, as **UNKNOWN; not asserted by this audit**, with the evidence column reading *none*.
- **Guard material (11)** — the hostile string exists so a test can assert the kit refuses to vouch
  for it: `test_benchmark.py:2593`, `test_claim_ledger.py:418, 1304`, `test_dashboard.py:290`,
  `test_failure_modes.py:310`, `test_schema.py:455, 804, 824`, `claim_ledger.py:140`, `schema.py:59,
  478`.
- **Unrelated technical use (46).** `"type(v) is safe"` about `__class__` lookups in four modules;
  `"that direction is safe"` about hash/eq asymmetry; and the large residue of `proves` / `proves
  nothing` in mutation-reasoning prose and test docstrings, none of which is about safety.

**Zero hits are an assertion.** `CLAUDE.md`'s absolute prohibition is honoured.

### 2.2 Widened to the surfaces a reader actually sees

SR-12 swept files. A hostile quoter does not read files; they screenshot a page or paste a terminal.

**The rendered dashboard** (MEASURED, C7, from `scripts/demo.py --keep`): 534 non-empty text lines.
It opens *and* closes with **"NOTHING ON THIS PAGE IS EVIDENCE ABOUT RFdiffusion, THE FORK, OR ANY
REAL BIOLOGICAL CAPABILITY. No result here bears on real-world safety."** Every one of the 10
`SUPPORTED` cells and the single `JOINT_SUPPORTED` cell is **immediately followed in the markup** by
`(SCORER-VALIDATION FIXTURE; conditional; not a safety finding)`, so the caveat survives a crop that
takes the verdict. The joint line reads `Joint verdict: … CONDITIONAL on 6 unimplemented gate(s)` and
`Complete gate coverage: NO.` Free-text fields are boxed `UNTRUSTED FREE TEXT … - NOT EVIDENCE`. **No
crop of this page that contains a verdict omits its caveat.**

**The demo's stdout** (MEASURED, C8): banner top and bottom; the only quotable line is
`[3] … verdict JOINT_SUPPORTED  [tests the scorer; says nothing about any method]`. The bracket is on
the same line as the verdict, so it too survives a line crop.

**`README.md`**: no claim. Its three most load-bearing sentences are **retractions by name** of its own
earlier overclaims (`:30`, `:33`, `:35`), each quoting the withdrawn wording and saying why it was too
strong. That is the right pattern and it is rare.

**`docs/RELEASE_NOTE.md`**, the artefact I wrote, was run through the same sweep: **3 hits, all three
denials** — it says the kit contains no evidence that RFdiffusion is safe, it quotes
`METHOD_AUDIT.md`'s UNKNOWN entry, and it lists what the kit cannot establish. **I applied this
section's own crop standard to it and it failed once.** Its "limits" paragraph originally wrapped as
`…that RFdiffusion or the safeRFdiffusion fork is safe or` on a line whose governing clause ("cannot
establish") sat two lines earlier — the same construction as `EVALUATION_PROTOCOL.md:428`. It is
rewritten as a list in which **every line containing a claim phrase also contains its negation,
before the phrase, on that same line**, so no line-level crop reverses a meaning (§6.4).

### 2.3 The two gaps — about durability, not content

Clause 2 asks about statements, and there are none, so it **passes**. But the mechanism that keeps it
passing has two measured holes, both new here, both in §4:

- **G1 (F23).** Removing the entire qualifier from the demo's most quotable line — `[tests the
  scorer; says nothing about any method]` — **survives the full 1,493-test suite.**
- **G2 (F24).** Gutting `robustness.STANDARD_NON_CLAIMS[1]`, *"Not a safety claim and not evidence of
  safety, capability reduction, or robustness of any real system."*, down to *"Not a safety claim."*
  **survives the full 1,493-test suite.**

`CLAUDE.md`'s own rule is *"Pin each load-bearing sentence with a test whose doc-only mutant dies."*
These two load-bearing sentences are not pinned. Both are one `assertIn` away from being pinned.

---

## 3. The evidentiary base — F17-R, settled here

### 3.1 What I measured

MEASURED (C9), independently of the brief and of SR-12:

```
git ls-files | grep -icE "mutat|mutant"   →  0
git ls-files scripts/                      →  demo.py  lint.sh  run_tests.sh  test_baseline.txt
grep -ci killed      docs/PROGRESS.md      →  265
grep -ciE '\bmutant' docs/PROGRESS.md      →  287
```

(SR-12 measured 260 and 276 at `9621e42`; the growth is its own entry plus SR-14's and SR-15's. The
*direction* is the point: the unreproducible evidence base is still growing.)

**No mutation tooling has ever been tracked in this repository.** Every harness built across roughly
28 attestation rounds lived in a session scratchpad and is gone.

### 3.2 The judgement SR-16 owes, in three parts

**(a) What a cloner *can* reproduce, and it is more than nothing.** I cloned this repository and
reproduced, today, from the clone and nothing else: both full-suite totals and skip counts on both
interpreters; `Σ scripts/test_baseline.txt = 1493` with zero slack; the bare-interpreter determinism
property; the runner's `RESULT: OK` twice over; the demo's exit code, its stdout, and the dashboard's
bytes; the lint result; the checkbox and dependency audit; the safety-claim sweep; and a live
network-denial measurement with its control. **Every behavioural claim this kit makes about itself is
reproducible.** That is the part of the base a stranger can stand on.

**(b) What a cloner cannot reproduce, and it is the part that carries the marks.** The decisive line in
SR-06's, SR-10's, SR-11's, SR-13's and SR-14's attestations is a mutation count — "11 real-defect
mutants KILLED", "8 killing mutants", "12 code mutants, all killed", "738 forgeries, 0 accepted". None
of it re-runs. The asymmetry matters precisely as SR-12 stated it: where the journal names the edit
(*"a mutant that sorts inside `bootstrap_means` kills it"*), a reader **can** re-derive that single
KILL by hand, because a failing targeted test implies a failing suite. What is irrecoverable is the
**set** — which mutants, by what rule, at which sites — and therefore **every SURVIVE claim and every
equivalence argument is simply gone**, since those assert that *nothing* catches a mutant.

**(c) The journal itself proves this is not a theoretical risk.** MEASURED (C10),
`docs/PROGRESS.md:3696-3706`, in the project's own words:

> **CORRECTION (round 3, 2026-11-10). That mutant is NOT killed — it survives, in both forms** […]
> **Lesson:** "mutant killed" is a claim like any other and I recorded it without re-running it.

**A recorded KILL in this journal has been wrong at least once and was caught only by re-running it.**
Every one of the 265 "killed" lines is now unrerunnable. That is not a presumption of error; it is the
removal of the only control that ever caught one.

### 3.3 The disposition, stated plainly

**F17-R does not retroactively invalidate any mark**, and this report does not unmark anything. Each of
the recent attesters built their own harness and re-derived figures rather than re-reading them, which
is a real control. **But SR-12 was right that the matrix cannot be sound as originally conceived**, so
§2's matrix does not have an "evidence" column. It has a **reproducibility class** column, and most
rows read `UNREPRODUCED`.

**I could not close F17-R and did not pretend to.** Closing it requires tracking a harness in
`scripts/`, which is outside the files I am permitted to write. What I could do instead was measure
how much a stranger loses — §4.

---

## 4. The one thing I could add: my own mutation probe

**This is the only new empirical evidence in this report.** It is built from the code, not from
anyone's prose about it, and — unlike every mutation run before it in this project — **its harness and
mutant table are written down here in full**, so it is re-derivable by anyone from a clean clone.

**Method.** A scratch `git clone` of `75f51e6`. Nine mutants, each chosen by me by reading the code for
the kit's *honesty* mechanisms, not its numerics. One at a time: apply, clear `__pycache__`, run **one
targeted test module** with `PYTHONDONTWRITEBYTECODE=1 … -B` (logically sufficient for a KILL, per
`CLAUDE.md`), restore. Restore is installed on `SIGTERM` and `SIGINT` as well as in `finally`. Every
SURVIVE was then re-run against the **full 1,493-test suite**, because only a SURVIVE asserts that
nothing catches the mutant. An unmutated control run of every target module preceded the set. Nothing
ran concurrently with any suite. Script and exact anchors: §9, C11.

| # | Mutant | Target | Result |
|---|---|---|---|
| M1 | `dashboard.BANNER` → `""` | `test_dashboard` | **KILLED** (2 failures) |
| M2 | `supported_caveat` loses `"; conditional; not a safety finding"` | `test_dashboard` | **KILLED** (3) |
| M3 | `schema.TOY_LABEL` loses its parenthetical | `test_schema` | **KILLED** (3) |
| M4 | `claim_ledger.SAFETY_CLASSIFICATION` `"NOT_PERFORMED"` → `"NONE_FOUND"` | `test_claim_ledger` | **KILLED** (5) |
| M5 | `JointResult.complete_gate_coverage` → `return True` | `test_benchmark` | **KILLED** (1) |
| M6 | demo banner loses `NOT EVIDENCE.` | `test_scripts` | **KILLED** (1) |
| **M7** | demo line 138 loses `[tests the scorer; says nothing about any method]` | `test_scripts` → **full suite** | **SURVIVED** — `Ran 1493 … OK (skipped=2)` |
| **M8** | `robustness.STANDARD_NON_CLAIMS[1]` → `"Not a safety claim."` | `test_robustness` → **full suite** | **SURVIVED** — `Ran 1493 … OK (skipped=2)` |
| M9 | *fix probe, not a defect:* `complete_gate_coverage` → `return not tuple(self.deferred_gates)` | `test_benchmark` | **SURVIVED** (354 tests OK) — SR-12's proposed one-line F21 fix breaks nothing in its own module |

**Seven of eight real mutants die, and the two that live are both safety-disclaimer strings.** That is
the finding. The kit's numeric and structural guards are well pinned; its *prose* guards are pinned
unevenly, and the unpinned two sit on the two surfaces a reader actually sees (§2.2).

**A process finding about my own run, recorded because this project's rule is that an avoided or
mis-controlled check is itself a finding.** My first pass ran in a `git archive` extract with no
`.git` directory. `test_scripts` has a test that calls `git ls-files`, so the control itself failed
with 1 failure — and against that broken control **M7 read as KILLED**. I re-ran the whole set in a
real `git clone`, where the control is `Ran 156 tests … OK`, and **M7 flipped to SURVIVED**. A green
control is not a formality; without it this report would have contained a false KILL, which is
precisely the error `PROGRESS.md:3706` records.

**What this probe is not.** It is nine mutants at sites I chose. It is not a coverage measurement, it
does not sample the journal's lost set, and it says nothing about whether the other 263 "killed" lines
are right. It is a lower bound on the cost of F17-R: **a tracked harness of this size, run once, would
have found G1 and G2.**

---

## 5. Clause 3 — "reproducible demo passes"

All MEASURED from the clean clone (§9, C12–C15).

| Property | Result |
|---|---|
| `python3 scripts/demo.py`, CPython 3.12.4 | **rc=0**, `DEMO OK in 2.6s. All checks passed.` |
| Same, CPython 3.13.5 | **rc=0**, `DEMO OK` |
| Re-run on 3.12.4, stdout diff | identical **except the two lines naming the random temp directory** |
| Dashboard size | **29,375 bytes**, both interpreters |
| Dashboard re-render, same interpreter | **byte-identical** (the demo asserts this itself and I re-checked) |
| Dashboard across interpreters | `sha256 277b9173fe4c8bfd…` — **byte-identical 3.12.4 vs 3.13.5** |
| `scripts/lint.sh` | rc=0, `LINT: OK` |
| `run_tests.sh --expect any --twice`, 3.12.4 | `RESULT: OK`, `unittest: ran=1493 skipped=2 failed=0`, `pytest: passed=1491 skipped=2 failed=0`, `deterministic: run1 == run2` |
| Bare venv (`--without-pip`; torch/numpy/pytest/yaml all absent), `--expect none --twice` | `RESULT: OK`, **ran=1493 skipped=90 failed=0**, `deterministic: run1 == run2` |

**Preconditions, which are part of the claim.** `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1` on any interpreter
that has pytest (§7, F20); `PYTHONDONTWRITEBYTECODE=1`; caches cleared; serial.

### 5.1 Network-denied, with a live control

MEASURED (C15), macOS `/usr/bin/sandbox-exec` with the profile `docs/CLEAN_CLONE.md:971-976`
(`(allow default) (deny network-outbound) (deny network-inbound)`):

| | ambient | inside the sandbox |
|---|---|---|
| `create_connection(("127.0.0.1", 1))` | `ConnectionRefusedError` **errno 61** | `PermissionError` **errno 1 (EPERM)** |
| `getaddrinfo("example.invalid", 80)` | `gaierror` | `gaierror` |

**The loopback row is the only one that discriminates** — which independently confirms the correction
recorded at `PROGRESS.md:13083`, where the orchestrator's "two of three discriminate" was reversed in
the owner's favour. The DNS row looks like a control and is not one.

Under that denial, from the clean clone: demo **rc=0 on both interpreters**; `lint.sh` rc=0 `LINT: OK`;
`run_tests.sh --expect any --twice` → `RESULT: OK`, deterministic; **a bare venv created *inside* the
sandbox** (so venv creation needs no network) then `--expect none --twice` → `RESULT: OK`,
1493/90/0, deterministic. The clone's tree was `git status --porcelain`-clean afterwards.

### 5.2 One reproducibility caveat nobody has recorded

MEASURED (C13). **The demo's step `[2]` prints a different digest on each interpreter:**
`ff7e2cae5b7c7aa5…` on 3.12.4, `17842e792b56c6c0…` on 3.13.5. I chased it rather than noting it: the
checkpoints are byte-identical **except** `"python_version": "3.12.4"` vs `"3.13.5"`, which is inside
the hashed provenance. **This is correct behaviour** — a provenance digest that ignored the
interpreter would be a worse digest — but the line that prints it reads `checkpoint saved + verified`,
and a reader comparing two machines sees a mismatch on a line containing the word "verified". It is
documented nowhere. **Severity: informational (F25).** One parenthetical on that print line closes it.

---

## 6. Deliverables required by the clause body

### 6.1 The claim–evidence matrix

**How to read it.** There is deliberately **no "evidence" column**, because §3 establishes that such a
column would be a list of sentences for most rows. There is a **reproducibility class** instead:

- **R** — reproducible from a clean clone today; I ran it (§9).
- **U** — **UNREPRODUCED**: the attestation's decisive evidence is mutation/forgery work whose harness
  was never tracked and no longer exists. Not disbelieved; **uncheckable**.
- **U\*** — UNREPRODUCED, but the journal names the edit precisely enough that a reader could
  re-derive *that single KILL* by hand with a targeted run.
- **E** — depends on material outside this repository (the fork's source), recoverable by a documented
  human step.

| Task | What the `[x]` asserts | Attestation | Class | What a stranger can check unaided |
|---|---|---|---|---|
| SR-00 | Scaffold, VCS, scripts, README, provenance preserved | **none** | — | The artefacts exist and the suite runs. **No QA ever attested it** (§1.2) |
| SR-01 | Fork-only diff re-checked; 8 files / 2 commits evidence matrix | `:145` | **E** | Internal arithmetic and SHA spellings are self-consistent; the diff itself needs a network fetch a human does |
| SR-02 | Method-level architecture audit, claims marked SOURCE/INFERENCE/UNKNOWN | `:1392` | **E** | That every claim carries a label, and that claim 21 reads UNKNOWN |
| SR-03 | Error/uncertainty register, every issue classified | `:1421` | **R** | The register's own tests and its QA-status section |
| SR-04 | Typed experiment schema, provenance, deterministic seeds | `:6549` | **U\*** | `test_schema` 55 tests pass; the field/lane sweeps behind the PASS are gone |
| SR-05 | Teacher–student toy demo, frozen teacher, mutable student | `:1974` | **U\*** | `test_teacher_student` 55 tests pass; the six post-PASS mutation re-verifications are gone |
| SR-06 | Stability checks: finite values, masked losses, empty-mask, gradient validity | `:11314` | **U** | `test_stability` **106** tests pass. "11 KILLED, 1 equivalent, 44 routes" is unreproducible, and the **equivalence** claim is irrecoverable in principle |
| SR-07 | Non-in-place ops; optional device/precision comparison | `:2067` | **R** | `test_tensor_ops` 110 tests, **82 skips on a bare interpreter**, every skip naming its absent package |
| SR-08 | Checkpoint metadata, provenance hashes, safe reload | `:1026` | **R** | Round-trip and tamper rejection, both driven by the demo itself |
| SR-09 | Evaluation protocol with controls, disconfirming cases, CIs | `:6362` | **R**, but see **F18** | The document; its own `:3` still says r10 was never independently reviewed |
| SR-10 | Benchmark scoring and CI reporting | `:11989` | **U** | Determinism bit-exact, CIs recompute from records, `test_benchmark` 354 pass. The 40-dps reference check and the six-route FAIL are gone |
| SR-11 | Robustness probes; immutable scorecards | `:12317` | **U** | `test_robustness` 203 pass. "30 write routes, 14/14 refused, 8 killing mutants" is unreproducible |
| SR-12 | Independent QA review with explicit verdict | `:12666` | **R** | The review document. **Its verdict on the kit is FAIL**; the `[x]` means the review was *done* |
| SR-13 | Dashboard; missing results render UNKNOWN not 0 | `:12524` | **U** | The page renders byte-identically and carries every caveat (§2.2). The 27-forgery sweep is gone |
| SR-14 | Human review + immutable audit log, DRAFT→REVIEWED→SUPPORTED/UNSUPPORTED | `:12817` | **U** | `test_claim_ledger` 100 pass; chain verification runs in the demo. "500 transitions, 738 forgeries" is unreproducible |
| SR-15 | Deterministic CI, lint/test scripts, pinning, offline demo, clean-clone docs | `:13044` | **R**, with 3 declared PARTIALs | Everything in §5 — I re-ran all of it. **The CI workflow has never executed: `git remote -v` is empty** |

**Four facts the matrix does not hide.** (i) SR-12's `[x]` sits over a **FAIL** verdict on the kit.
(ii) SR-00's rests on no attestation. (iii) Six rows are class **U**: their decisive evidence is
uncheckable. (iv) SR-15's "deterministic CI" limb is **PARTIAL and declared** — the workflow is
deterministic by construction and has never run, and cannot have, because there is no remote.

### 6.2 Limitations — what this report does not establish

1. **Nothing here is evidence about RFdiffusion, the safeRFdiffusion fork, or any real biological
   capability.** No model was run, no weights exist in the tree, no biological data was touched.
2. **It does not establish that the audited method works, fails, is safe, or is unsafe.** The kit
   audits *claims and methods*; `METHOD_AUDIT.md:244` still carries "the method is safe / yields a
   safer model" as **UNKNOWN; not asserted by this audit**, and this report changes nothing about that.
3. **A passing suite is a property of the suite.** 1,493 tests passing says the toy modules behave as
   their tests specify. It says nothing about the adequacy of the specification, and §4 shows two
   places where the specification is silent.
4. **One host, one OS, one mechanism.** The network-denial evidence is macOS `sandbox-exec` on one
   machine, covering `connect()`, name resolution, UDP `sendto`, AF_UNIX connect and TCP bind/listen.
   **Not Linux. Not the CI jobs. Inherited file descriptors unprobed.**
5. **Both CI jobs remain unobserved and unobservable here** — `git remote -v` is empty (MEASURED).
6. **Dependency pinning is partial and declared**: torch 2.7.1 + numpy 1.26.4 pinned, the combination
   untested, transitive dependencies unpinned, no lock file, no `--require-hashes`, actions pinned by
   tag not SHA.
7. **The suite's pass/fail on a developer machine depends on third-party pytest plugins this kit
   neither installs nor bounds** (F20). Documented in `README.md:33`, not fixed in the runner.
8. **The mutation evidence behind most marks cannot be reproduced** (§3). This is the largest
   limitation in the document.
9. **I did not re-verify the fork material.** `DIFF_EVIDENCE.md`'s source files are not in this
   repository and I made no network fetch. §6.1 class **E**, inherited not re-earned.
10. **My own probe is nine mutants.** A lower bound, not a coverage figure.

### 6.3 Screenshot / demo

No image file was produced: I am permitted one new file and it is the release note, and a PNG is not a
byte-reproducible artefact across renderers — which would make it the one deliverable in this kit that
cannot be re-derived. **A text rendering is given instead, and it is reproducible** (C7, C8).

Demo stdout, verbatim at `75f51e6`, CPython 3.12.4 (temp path varies per run; nothing else does):

```
==============================================================================
 TOY DEMO. NOT EVIDENCE.
 Nothing printed or written by this demo is evidence about RFdiffusion, the
 safeRFdiffusion fork, or any real biological capability. All data are
 synthetic non-biological toy matrices; no model weights are used.
==============================================================================

[0] temp dir (all outputs go here): /…/saferf_demo_XXXXXXXX
[1] toy teacher/student: loss 0.2403 -> 0.0579 over 60 steps (evidence class TOY_RESULT)
[2] checkpoint saved + verified, digest ff7e2cae5b7c7aa5...; tampered copy rejected
[3] scorer-validation fixture (ORACLE_GATED) scored on 30 seeds: verdict JOINT_SUPPORTED  [tests the scorer; says nothing about any method]
[4] robustness probe (row reorder on mse_fsum, 12 seeds): status INVARIANCE_HOLDS
[5] claim ledger: 2 events, chain verified, claim state REVIEWED (not SUPPORTED)
[6] dashboard rendered (29375 bytes, byte-identical on re-render): /…/dashboard.html

DEMO OK in 2.6s. All checks passed.
[banner repeated]
```

Rendered dashboard, structure and the decisive block (tags stripped; 534 text lines, sha256
`277b9173fe4c8bfd…`):

```
  line   2 | Audit dashboard: toy results and source metadata
  line   1 | NOTHING ON THIS PAGE IS EVIDENCE ABOUT RFdiffusion, THE FORK, OR ANY REAL
            | BIOLOGICAL CAPABILITY. No result here bears on real-world safety. …
  line   3 | Label legend      [SOURCE OBSERVED | TOY RESULT | HYPOTHESIS | NOT VALIDATED | UNKNOWN]
  line  14 | Source-diff inventory            (SOURCE OBSERVED; static source metadata)
  line  86 | Toy training curves
  line 323 | Benchmark scorecard
  line 333 | SCORER-VALIDATION FIXTURE
            |   a test of the scorer on a fixture whose answer is known by construction;
            |   NOT a result about any method, model or intervention
            |   subject_kind is PRODUCER-ASSERTED …
  line 356 | H1 … SUPPORTED  (SCORER-VALIDATION FIXTURE; conditional; not a safety finding)
  line 416 | Joint verdict:  JOINT_SUPPORTED
  line 418 |   (SCORER-VALIDATION FIXTURE; conditional; not a safety finding)
            |   CONDITIONAL on 6 unimplemented gate(s)
  line 419 | Attempted 30, failed 0. Complete gate coverage: NO.
  line 452 | Uncertainty and protocol limits
            |   Any SUPPORTED verdict is conditional on these. UNKNOWN means unmeasured, never zero.
  line 534 | [banner repeated verbatim]
```

### 6.4 Release note

`docs/RELEASE_NOTE.md`. It is written to the standard this task was given: **a hostile reader quoting
any single sentence of it must not be able to make this kit sound like evidence about RFdiffusion.**
Every paragraph carries its own scope, no sentence's qualifier lives in a neighbouring sentence, and
the verdict (FAIL) and the two uncheckable categories are in the opening, not an appendix.

---

## 7. Status of every SR-12 open item, re-derived at `75f51e6`

Checked at HEAD, not quoted.

| ID | SR-12 severity | **Status at `75f51e6`** | Evidence |
|---|---|---|---|
| **F17-R** | **Verdict-carrying** | **OPEN — settled, not closed.** Cannot be closed from the files I may write. Discharged as SR-12's alternative remedy: every affected row is marked UNREPRODUCED in §6.1 and the cost is measured in §4 | C9, C10, §3 |
| **F16** | Medium | **OPEN, unchanged.** `scripts/demo.py:137-138` still prints `verdict JOINT_SUPPORTED  [tests the scorer; …]`, not `EVALUATION_PROTOCOL.md:126`'s mandated `JOINT_SUPPORTED (conditional on deferred checks: <list>)`. The dashboard complies; the demo does not. **Now worse than SR-12 found it:** F23 shows the bracket it does carry is unpinned | C8, C16 |
| **F18** | Medium | **OPEN, unchanged.** `docs/EVALUATION_PROTOCOL.md:3` still reads *"r10 has not been independently reviewed"* inside *"Version history, stated exactly"*, while SR-09's `[x]` rests on `PROGRESS.md:6362` — *"SR-09 r10: **PASS**"* | C17 |
| **F20** | Medium | **PARTLY ADDRESSED — documented, not fixed.** `README.md:33` now names the failure, the cause and the remedy, and `:42` puts `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1` in the documented command block. `scripts/run_tests.sh` still does **not** set it for its own pytest sub-run (`grep` → 0 hits). **Reproduced at this HEAD:** `unittest discover` on the ambient conda 3.13.5 → `Ran 1493 … FAILED (failures=4, skipped=84)` via `OSError: Could not find/load shared object file 'libllvmlite.dylib'`; with the variable set → `Ran 1493 … OK (skipped=84)` | C18, C19 |
| **F20-b** | **NEW, Low** | **`README.md:18` — "First steps" step 2 — prescribes `python3 -m unittest discover -s tests -v` with no precondition**, and that exact command produces the four failures above on this host. The precondition exists only in a different section 24 lines later | C18 |
| **F21** | Medium | **OPEN, unchanged.** `benchmark.py:2650-2651` is still `return not self.deferred_gates`; `grep -c CONTAINER src/toy/benchmark.py` → **0**. **New datum:** M9 shows the proposed one-line fix (`return not tuple(self.deferred_gates)`) passes all 354 `test_benchmark` tests, so nothing in the module's own suite blocks it | C16, §4 |
| **F22** | **NEW, Low** | **A declared fix that was not performed, inside the final marking commit.** `docs/CLEAN_CLONE.md` (amended in `75f51e6` itself) says the first-match `^Ran` defect *"must therefore touch BOTH sites"*; both sites are unchanged at `run_tests.sh:355` and `:993` | C5, §1.3 |
| **F23** | **NEW, Medium** | **The demo's only safety qualifier is unpinned.** M7 survives the full suite | §4 |
| **F24** | **NEW, Medium** | **`robustness.STANDARD_NON_CLAIMS[1]` is unpinned.** M8 survives the full suite | §4 |
| **F25** | **NEW, Info** | The demo's checkpoint digest differs across interpreters by design (`python_version` is in the hashed provenance) and this is documented nowhere | C13, §5.2 |
| F7 | Low, advisory | **STILL OPEN** by inspection; `teacher_student.py:236-240` unchanged | C20 |
| F8 | Low, advisory | **STILL OPEN** by inspection; `teacher_student.py:176-180` unchanged | C20 |
| F9 | Low, advisory | **STILL OPEN** by inspection; `stability.py:50-54` unchanged | C20 |
| F10 | Low | **STILL OPEN by construction** — commit messages are immutable | — |
| F19 | Low (process) | **STILL OPEN.** `PROGRESS.md:8631-8633` states the ordinal contradiction and calls the authoritative series **UNKNOWN**; a sweep after that line finds no resolution, only SR-12 restating it | C21 |
| M1 | Info | **STILL OPEN.** `docs/FORK_AUDIT.md`, named in `CLAUDE.md` as source of truth #1, does not carry the hedges `METHOD_AUDIT.md` later added | C20 |
| M2 | Info | **STILL OPEN.** The "36 commits behind" figure is time-varying; `DIFF_EVIDENCE.md:27` says so, `README.md:13` and `FORK_AUDIT.md:9` carry only a date | C20 |

**Count at this HEAD: 5 of SR-12's 5 required items are open** (F17-R settled-not-closed; F20 partly
addressed), **5 advisories open**, **5 new items** (F20-b, F22, F23, F24, F25). Two of the new ones
(F23, F24) are in clause 2's mechanism, which is why clause 2 passes with gaps named rather than
cleanly.

---

## 8. Figures I re-derived, and which did not match

Every figure the brief handed me was re-measured. **Eight matched; two needed a condition added; one
was mine to correct.**

| Figure as given | Re-derived | Verdict |
|---|---|---|
| Full suite **1493 / 0 failed**, 3.12.4 skipped 2 | `Ran 1493 … OK (skipped=2)` | **matches** |
| Full suite 1493 / 0 failed, 3.13.5 skipped 84 | `Ran 1493 … OK (skipped=84)` **only with `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`**; without it, `FAILED (failures=4, skipped=84)` | **matches, condition required** — the condition is stated elsewhere in the brief but not on this line |
| Bare-venv determinism **1493 / 90 / 0**, run1 == run2 | `RESULT: OK … ran=1493 skipped=90 failed=0`, `deterministic: run1 == run2` | **matches** |
| Σ `scripts/test_baseline.txt` = 1493, zero slack | 4+354+48+100+265+17+20+203+55+156+106+55+110 = **1493** | **matches** |
| Baseline **skip** column | sums to **89**, not 90; the 90th is the single PyYAML skip in `test_scripts`, excluded by the runner's `BASE_EXCL` "yaml" rule | **matches the journal's reconciliation**; worth repeating because 89 ≠ 90 looks like an error and is not |
| Network-denied: suite, runner, demo, lint all OK on both interpreters | re-measured; `RESULT: OK` + deterministic; demo rc=0 both; `LINT: OK` | **matches** |
| Denial control: EPERM inside vs **ECONNREFUSED errno 61** outside | `PermissionError` errno 1 inside; `ConnectionRefusedError` errno 61 outside | **matches**, and I add that **DNS does not discriminate** (`gaierror` both ways) |
| `git remote -v` empty ⇒ CI never ran on a hosted runner | empty | **matches** |
| `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1` is a required precondition on a developer machine | reproduced exactly, with the `libllvmlite` cause | **matches** |
| `test_stability` is **106**, not the old report's 57 | 106 in the baseline and in the run | **matches** |
| Journal counts "260 killed / 276 mutant" | **265 / 287** at this HEAD | **the brief's figures are SR-12's, measured at `9621e42`, not at `75f51e6`** — not an error, but they are not this HEAD's |

**Of my own figures, one was wrong and I caught it.** My first mutation pass reported **M7 KILLED**.
It was measured against a control that was itself failing for an unrelated reason (§4). On a correct
control M7 **SURVIVES**. Had I reported the first number, this document would have asserted that the
demo's safety qualifier is test-protected when it is not — an error in the direction of reassurance,
in the clause about overclaiming.

---

## 9. Commands

Every command ran at `75f51e6` **from a fresh `git clone` of this repository**, tree clean, caches
cleared, `PYTHONDONTWRITEBYTECODE=1`, `-B`, never `-I`, and **serially — nothing ran alongside a
suite**. `P312=/Library/Frameworks/Python.framework/Versions/3.12/bin/python3`; ambient `python3` is
conda CPython 3.13.5.

```sh
git clone <this repo> clone && cd clone && git rev-parse HEAD && git status --porcelain
```
→ `75f51e6ba35cefc28e2dfd7030bd8d0408339d77`, then nothing. `diff -r` against the working tree, taken
before this pass wrote its two files, differed only by the untracked `.ruff_cache`. **Every command below reproduces from this clone.**

- **C1 checkbox/dependency audit** — a script parsing `BUILD_BLUEPRINT.md` for `- [ ]`/`- [x]` rows and
  `**Depends:**` lists; asserts `UNCHECKED_DEPS` is empty for every `[x]`. → 18 rows, 16 in-scope
  marked, **0 violations**.
- **C2 SR-00 attestation** — `grep -c "^## SR-00 — QA verdict" docs/PROGRESS.md` → **0**.
- **C3 attestation completeness** — per-task section slice between `^## ` headings, tested for a
  7–40 hex SHA and for a commands marker. Table in §1.2. *Weak proxy; see the caveat there.*
- **C4 attested == committed** — `git log -1 --format=%h -- <deliverable>` for all 22 deliverables,
  compared with each marking commit; plus `git show --stat 75f51e6`.
- **C5 the two `^Ran` sites** — `grep -nE 'Ran \(\\d\+\)' scripts/run_tests.sh` → lines **355** and
  **993**.
- **C6 hostile safety sweep** — `git grep -nEi "<pattern>" -- . ':!docs/PROGRESS.md'
  ':!docs/SR16_AUDIT_REPORT.md' ':!docs/SR12_INDEPENDENT_REVIEW.md'` with the widened pattern of §2.1
  → **73 hits / 28 files**, all classified by reading.
- **C7 dashboard** — `TMPDIR=<scratch> $P312 -B scripts/demo.py --keep`, both interpreters; tags
  stripped with a 6-line `re`/`html.unescape` script; `cmp` and `shasum -a 256` across the two.
- **C8 demo stdout** — `$P312 -B scripts/demo.py` ×2 and `python3 -B scripts/demo.py` ×1; `diff`.
- **C9 mutation tooling** — the four commands quoted verbatim in §3.1.
- **C10** — `sed -n '3696,3706p' docs/PROGRESS.md`.
- **C11 mutation probe** — `git clone` to a scratch dir; for each row of the table in §4, a unique
  anchor string replaced once (the script asserts `count == 1` and skips otherwise), caches cleared,
  `PYTHONPATH=<clone>/src PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 $P312 -B -m unittest <module>`, then
  restore; `signal.signal(SIGTERM/SIGINT, restore)` installed before the first mutation; a control
  pass over every target module first; `git status --porcelain` empty afterwards. **Run the control in
  a real `git clone`, not a `git archive` extract** — `test_scripts` calls `git ls-files`.
- **C12 suites** — `PYTHONPATH=src $P312 -B -m unittest discover -s tests`; same on `python3`; same
  again with `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`.
- **C13 checkpoint digests** — `json.load` of both runs' `toy.ckpt.json`, sorted-key dump, `diff` →
  exactly two differing lines: `digest` and `python_version`.
- **C14 runner** — `PATH=<3.12 bin>:$PATH PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 bash ./scripts/run_tests.sh
  --expect any --twice`; and `$P312 -m venv --without-pip <bare>` then
  `PATH=<bare>/bin:$PATH bash ./scripts/run_tests.sh --expect none --twice`.
- **C15 network denial** — profile exactly as `docs/CLEAN_CLONE.md:971-976`;
  `/usr/bin/sandbox-exec -f nonet.sb <command>` for the control, the demo (both interpreters),
  `lint.sh`, both runner invocations, and the venv creation.
- **C16** — `sed -n '2649,2652p' src/toy/benchmark.py`; `grep -c CONTAINER src/toy/benchmark.py` → 0;
  `sed -n '137,138p' scripts/demo.py`; `sed -n '126p' docs/EVALUATION_PROTOCOL.md`.
- **C17** — `sed -n '3p' docs/EVALUATION_PROTOCOL.md`; `sed -n '6362p' docs/PROGRESS.md`.
- **C18/C19** — the 3.13.5 discover run with and without the variable;
  `grep -n PYTEST_DISABLE_PLUGIN_AUTOLOAD scripts/run_tests.sh` → no hits.
- **C20** — `sed` at `teacher_student.py:176-180, 236-240`, `stability.py:50-54`; `FORK_AUDIT.md`,
  `DIFF_EVIDENCE.md:27`, `README.md:13`.
- **C21** — `sed -n '8631,8634p' docs/PROGRESS.md`, then `awk 'NR>8634 && /ordinal/'`.

**Not reproducible from a clone, and labelled as such:** nothing in this report. The one thing I did
*not* attempt is the fork-source re-verification (§6.2 item 9), which needs a network fetch a human
performs.

---

## 10. This document's own liabilities

Held to the standard §4 applies to everyone else.

1. **My mutation probe is nine mutants at sites I picked.** Sites were chosen by reading for honesty
   mechanisms, which biases toward finding prose gaps — and it found two. A different nine would say
   something different. **It is a lower bound, not coverage**, and the word "coverage" appears nowhere
   near it.
2. **§1.2's table is a regex over sections.** My own first version of that scan produced a false
   negative. Treat the SHA/commands columns as a floor; the four sections I read in full are the only
   ones I vouch for individually.
3. **Clause 1's FAIL is a judgement, not a measurement.** The measurements are: SR-00 has no
   attestation; six rows are class U; one deliverable moved inside its marking commit. That those add
   to "not supported" rather than "supported with caveats" is my call, and a reasonable reviewer could
   grade it PASS-with-conditions. I have stated exactly what would flip it (§11) so the disagreement
   would be about a short list rather than about a verdict word.
4. **I inherited SR-12's F17-R analysis and did not re-derive its *reasoning*** — only its facts (C9)
   and one new fact (C10) that supports it. Where I agree with SR-12 I say so; agreement after
   re-measuring the facts is not independent confirmation of the argument.
5. **I did not read all 13,164 lines of `docs/PROGRESS.md`.** I read the 16 attestation sections, the
   ordinal dispute, the F17-R passages and the self-correction at `:3696`. A journal that long can
   hold a contradiction I did not find.
6. **"Zero safety claims" is a claim about 73 classified hits of one pattern family.** `CLAUDE.md`
   itself records that *"a lexical sweep for overstated guarantees does not work; per-sentence
   assertion does"*, and that the worst overclaim this project ever found contained no modal and no
   absolute. §2's PASS is therefore **strong evidence of absence, not proof of absence** — and §4 is
   the per-sentence half, which is why it is in the report at all.

---

## 11. What would flip clause 1 to PASS

In this order. Items 1 and 2 are the clause; 3 and 4 are cheap and belong with them.

1. **Attest SR-00, or unmark it.** One independent QA pass against the clause at
   `BUILD_BLUEPRINT.md:8`, recorded with the six elements. This is hours of work and removes the only
   task in the kit with no attestation at all.
2. **Track a mutation harness in `scripts/`** — a declared mutant table, anchor-uniqueness assertion,
   signal-safe restore, and a control pass; perhaps 150 lines, with the §4 table as its first
   fixtures. **It does not resurrect the lost set and must not claim to.** What it changes is the
   tense: from "hundreds of results nobody can check" to "a named set anybody can re-run, plus a
   labelled historical remainder." Combined with one sentence in `README.md` stating that all
   pre-SR-16 mutation figures are **attester-reported and UNREPRODUCED**, that discharges F17-R
   honestly without overstating the repair.
3. **Pin the two unpinned disclaimer strings** (F23, F24). Two `assertIn`s.
4. **Apply the one-line `complete_gate_coverage` materialisation** (F21); M9 measured that it breaks
   nothing. **Fix F16's one string**, or amend `EVALUATION_PROTOCOL.md:126` — either, but not neither,
   since the protocol's own paragraph says the document and the code must tell the same story.

None of this touches any statement about RFdiffusion, because there is none to touch.

---

*Nothing in this report asserts that the audited method works, fails, is safe, or is unsafe. It
contains no biological content, no model weights, and no network access. `SR-17` was not started.*
