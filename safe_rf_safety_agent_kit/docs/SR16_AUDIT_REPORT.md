# SR-16 audit report — claim/evidence matrix, residuals and limitations

**Status of this document: THIS IS NOT AN SR-16 COMPLETION.** SR-16 is `[ ]` in
`docs/BUILD_BLUEPRINT.md` and stays `[ ]`. SR-16 declares **`Depends:` SR-15**, and SR-15 is open —
it has never passed an attestation, and one of its four claims ("offline") is **BLOCKED**, not
failed. This file is the *report SR-16 would need*, written now so that the project has a defensible
written state while its final task remains blocked. It marks no checkbox, edits no other file, and
changes no status.

**Written:** 2026-11-11. **Kit HEAD read:** `d0441f5`. **Author:** audit/write-up pass, reading the
tree read-only. **Files written by this pass:** this file only. No commit, no staging, no checkbox
edit. One pre-existing uncommitted change was present in the tree before this pass began and was
left untouched — see §8.4.

---

## 0. How to read this report

### 0.1 Labels

The taxonomy is the project's own. `docs/SR12_INDEPENDENT_REVIEW.md:5` defines it:

> Labels: **SOURCE OBSERVED** (read directly from the cited text or produced by a command recorded in
> section 9), **INFERENCE** (reasoned from observed text, not executed), **UNKNOWN** (not determined).

`docs/METHOD_AUDIT.md:7` gives the same three with the first scoped to text. This report uses:

- **MEASURED** — a command was run and its output recorded. Where I ran it, the command is given and
  the date is today; where the journal ran it, the journal line and the interpreter are given.
- **INFERENCE** — reasoned from observed text, not executed. The project's own wording.
- **UNKNOWN** — not determined. Used, not avoided.

### 0.2 What I ran, and what I did not

I ran `git`, `grep`, `awk`, `sed`, two short read-only Python/AST scripts, and `python3 --version` /
`python3 -m pytest --version`. **I ran no test suite.** Any figure that only a suite run could
establish is reported as UNKNOWN in §7 rather than repeated from a brief. This follows `README.md`'s
own rule, which is sharper than a paraphrase:

> **Do not take a test total from the documentation** — a hard-coded count there has gone stale three
> times and is now deliberately absent; obtain it from a run.

### 0.3 A standard this document holds itself to

The project's central methodological finding (§4) is that its recurring defect was **a sentence
describing a mechanism's reach**, not the mechanism. So: where this report says a mechanism covers
something, it states the enumeration or the measurement that makes the sentence true, or it scopes
the sentence to what was actually driven. Sentences in this report that cannot be pinned that way are
collected in §9 and labelled as liabilities. Figures are given as counted expressions with the
command wherever a count was runnable.

---

## 1. What this kit is, and what it is not

### 1.1 What it is

The kit reproduces and independently audits the **safety research methods and claims** of a
third-party public fork, examined **read-only**. `README.md:3` states the purpose:

> Reproduce and independently audit the *safety research methods and claims* introduced in
> `audited-fork/safeRFdiffusion`, without silently assuming the fork is validated or building a new
> production protein-design engine.

The audited object is a diff, not a program that was run. `docs/FORK_AUDIT.md` records the comparison
as a GitHub compare of `RosettaCommons/RFdiffusion` at shared ancestor
`e22092420281c644b928e64d490044dfca4f9175` against `audited-fork:main`, two fork-only commits
(`12d5426d…`, `5cbd18a3…`), and an exact changed-file inventory.

**MEASURED, by counting the documents rather than retyping their claim.** Counting the table rows
whose first cell is a backticked path or SHA:

```sh
grep -cE '^\| `' docs/FORK_AUDIT.md      # -> 8   (all eight are file paths)
grep -cE '^\| `' docs/DIFF_EVIDENCE.md   # -> 10
grep -oE '^\| `[^`]+`' docs/DIFF_EVIDENCE.md   # -> 8 file paths + 2 fork-only commit SHAs
```

That is SR-01's criterion clause ("enumerates all 8 changed files, 2 commits") satisfied by count
rather than by reading the sentence that asserts it.

### 1.2 What it is not — the binding constraints, quoted

`CLAUDE.md`'s "Safety and honesty" section binds every sentence in this file. Quoted, not
paraphrased:

> - This is a safety research and evaluation tool; no unrestricted biological design engine or
>   unreviewed model training.
> - No synthesis instructions, pathogen/toxin design targets, biological optimization examples,
>   downloads of real generative-model weights, or unrestricted protein design inference in the
>   autonomous loop.
> - Use synthetic non-biological toy matrices and generic software tests for development.
> - Never claim a trained safe checkpoint or measured reduction of biohazardous capability absent
>   independent evidence.
> - Distinguish source-observed facts, hypotheses, mock outputs, and empirical measurements.
> - Do not disable tests or delete failing checks to claim completion.
> - A concept-erasure training *run* is not evidence of selective unlearning or safety.

`docs/ORCHESTRATOR_PROMPT.md` adds, in its own words:

> No live protein generation, fine-tuning, target selection, checkpoint acquisition, or unreviewed
> biological datasets. No secrets or external writes. **A passing demonstration does not establish a
> safer model. Do not mark unsupported external safety claims as validated.**

and scopes the whole exercise in its first line:

> You are the lead orchestrator of a *safeRFdiffusion safety-audit and toy-method replication*, **not
> an operational protein design project**.

### 1.3 The negative claims, each with the measurement that supports it

**No model weights are in the tree. MEASURED:**
`find . -path ./.git -prune -o -type f \( -name '*.pt' -o -name '*.pth' -o -name '*.ckpt' -o -name
'*.safetensors' -o -name '*.bin' -o -name '*.pkl' \) -print` → **no output**.

**`src/toy/` imports only the standard library and itself. MEASURED, as an enumeration rather than a
claim about reach:** the distinct top-level import names across all 11 modules of `src/toy/` are, in
full — `__future__, collections, copy, dataclasses, datetime, enum, fractions, functools, hashlib,
hmac, html, inspect, itertools, json, math, numbers, os, pathlib, random, re, stat, sys, tempfile,
toy, types, typing, unicodedata` (27 names; command:
`grep -rhoE '^(import|from) [a-zA-Z_][a-zA-Z0-9_.]*' src/toy/*.py | awk '{print $2}' | cut -d. -f1 |
sort -u`). Every name is stdlib or the package's own `toy`. No `socket`, no `urllib`, no `torch`, no
`numpy`. This is the enumeration, not a guarantee about future files; the enforcement claim is
`scripts/lint.sh`'s and `tests/toy_tests/test_scripts.py`'s, and the state of that enforcement is
SR-15's, which is open.

**No RFdiffusion inference was run and no biological target was used.** SOURCE OBSERVED across the
tree: nothing imports, vendors or invokes RFdiffusion; `docs/ERROR_REGISTER.md:9` states the position
in its own words — *"All demonstrations are abstract, non-biological, offline, and run in well under a
second. No weights, network, pickle payloads or biological content are involved."* The fork's own
script was read by line number from `docs/METHOD_AUDIT.md` and never executed;
`docs/ERROR_REGISTER.md:11` records even the second-hand nature of that reading — *"I did not re-read
the fork script; line numbers are taken from METHOD_AUDIT and inherit its SOURCE OBSERVED /
INFERENCE status."*

### 1.4 What no statement in this file asserts

**Nothing here implies the audited fork is safe, works, or was measured.** The fork was not run; no
capability, hazard or utility was measured, by this kit or by this report. `docs/FORK_AUDIT.md`'s
"What is **not** established" section is the operative statement and is quoted in full rather than
summarised:

> - No new benchmark/test files were present in the fork-only comparison.
> - No empirical before/after evidence for reduced hazardous biological design capability was located
>   in the changed files.
> - No demonstration of benign-design utility preservation, external validation, calibration or
>   robustness was provided by these two commits.
> - No validated safety-modified model weights were added in the fork-only diff.
> - The example in `main()` is an ordinary helix-motif scaffolding sample, not evidence of a
>   biosecurity evaluation.

`docs/FORK_AUDIT.md`'s interpretation line, attributed to that document: *"The repository is a
proof-of-concept *method attempt* with training-enabling changes. It is not evidence of a
successfully validated safer protein design system."* `docs/ERROR_REGISTER.md:7` is the matching
disclaimer for this kit's own defect findings: *"**No claim that the method is broken, and none that
it is safe.** … A defect pattern being present in the source says nothing about whether the method
works or fails to work, or about any capability."*

---

## 2. The claim–evidence matrix

### 2.1 How the verified list was derived

**Derived from the blueprint, not inherited.** Command:

```sh
grep -oE '^- \[[x ]\] \*\*SR-[0-9]+' docs/BUILD_BLUEPRINT.md
```

Output, in blueprint order: `[x]` for SR-00, SR-01, SR-02, SR-03, SR-04, SR-05, SR-06, SR-07, SR-08,
SR-09; `[ ]` for SR-10, SR-11, SR-12, SR-13, SR-14, SR-15, SR-16, SR-17. Counted with
`grep -cE '^- \[x\] \*\*SR-[0-9]+'` → **10** and `grep -cE '^- \[ \] \*\*SR-[0-9]+'` → **8**.

**MARKED (10): SR-00 through SR-09 inclusive.**
**OPEN (8): SR-10 through SR-17 inclusive.**

This matters because a typed list in the journal got it wrong. `docs/PROGRESS.md:8321` reads
*"**Verified: 10 of 17** — SR-00, SR-01, SR-02, SR-03, SR-05, SR-06, SR-07, SR-08, SR-09"* — **nine
names under a count of ten, with SR-04 dropped.** The journal's own closing entry
(`docs/PROGRESS.md:8592-8608`) records the correction and draws the right rule from it:

> **A verified list is derivable from `docs/BUILD_BLUEPRINT.md` and should be derived, not typed.**

SR-04 belongs in the list because it was unmarked in round 5 for the `MetricValue`
value-substitution defect and **re-marked in round 7** after an independent PASS
(`docs/PROGRESS.md:5251`, `:6643`).

### 2.2 The matrix

Columns: criterion clause (abbreviated from `docs/BUILD_BLUEPRINT.md`); checkbox at HEAD; the
attestation that stands, with the journal line; the evidence; what remains UNKNOWN. "Round N" is the
journal's own round labelling. Evidence figures carry their interpreter where one was recorded.

| Task | Criterion clause (blueprint) | Box | Attestation that stands | Evidence (MEASURED unless noted) | UNKNOWN / open |
|---|---|---|---|---|---|
| **SR-00** | Scaffold, VCS, scripts, README; preserve fork-audit provenance | `[x]` | QA **PASS**, recorded *inside the build entry* at `:31`/`:39` — **there is no `## SR-00 — QA verdict` section** (grep → 0), which is the exact criterion SR-12 used to revert SR-05. §3.10 | `unittest discover` → `Ran 4 tests / OK` (3.12.4); `git show f7eb976 --stat` → 20 files, 380 insertions; QA re-derived the toy arithmetic by hand (`toy_target((3,1),(1,2),s=0.5) = (0.0, 2.5)`; `masked_mse((3,9),(1,0),(T,F)) = 4.0`) so the assertions are non-vacuous | Journal `:59`: *"the suite is 4 trivial contract tests; passing says nothing about RFdiffusion"*. GitHub figures not re-verifiable offline at SR-00 (done in SR-01). D3 was **deferred forward** to SR-05/SR-06 rather than closed (`:56-58`) |
| **SR-01** | Fork-only diff vs shared ancestor; filename/commit evidence matrix; reviewer confirms counts | `[x]` | QA **PASS** (marked), `:145` | `docs/DIFF_EVIDENCE.md` enumerates 8 files + 2 commits — re-counted here (§1.1); per-file add/delete arithmetic recomputed independently in `docs/SR12_INDEPENDENT_REVIEW.md` §C2 | Manual `curl` corroboration is explicitly outside the suite (`README.md`): a human activity. Upstream state ("36 commits beyond the merge base") is a 2026-11-09 observation, not re-checked here |
| **SR-02** | Method-level architecture audit; claims marked SOURCE/INFERENCE/UNKNOWN | `[x]` | QA **PASS (third pass)**, `:1392` — after FAILs at `:501` and a second at `:1130` | Citations traced to source line keys (`S:`/`D:`/`A:`); `docs/SR12_INDEPENDENT_REVIEW.md` rates method fidelity **PASS** on spot-checked citations | Everything the document itself labels UNKNOWN — e.g. effective `p_drop`, prompt freeing of the up-to-4 live model instances (`docs/METHOD_AUDIT.md:35,40`). Runtime reach of every pattern is UNKNOWN by construction |
| **SR-03** | Error/uncertainty register with reproducible generic tests or static evidence | `[x]` | QA **PASS (third pass)**, `:1421` — after a FAIL and rework at `:944`, follow-up `:1157` | 11 entries ER-01…ER-11 each carrying CONFIRMED-IN-SOURCE / PATTERN-DEMONSTRATED / UNKNOWN-NEEDS-EXECUTION / STATIC-ANALYSIS-ONLY labels; generic reproductions in `src/toy/failure_modes.py` | ER-08/ER-09/ER-11 rest on UNKNOWN-NEEDS-EXECUTION or STATIC-ANALYSIS-ONLY. `docs/ERROR_REGISTER.md:41`: *"Severity is the author's judgement of consequence if the defect is reached, with the reach itself unproven; it is not a probability."* |
| **SR-04** | Strict typed experiment schema, run provenance, deterministic seeds | `[x]` | **PASS, round 7**, `:6549`, `:6643` — *re-mark*; the first PASS at `:316` was **withdrawn in round 5** (`:5251`, `:5260`) and round 6 FAILed it (`:5438`) | Round 5's F1 was a public-constructor value substitution: `MetricValue.measured(EqZero(7.0)).value → 0.0`, end-to-end flipping H2 UNSUPPORTED→SUPPORTED and JOINT_UNSUPPORTED→JOINT_SUPPORTED with `reasons = ()` (now recorded at `src/toy/schema.py:365-383`). Round 7's PASS rests on a machine-derived field boundary: **49 fields, 46 covered, 3 exempted** (`:6009`) | The boundary covers **31% of fields** by the round-7 attester's measure (`:6549` heading). `_plain_value`'s container limit and the `__getattribute__` route are live — §3.5, §3.8 |
| **SR-05** | Abstract teacher–student demo on small 2D arrays, non-biological | `[x]` | QA **PASS**, `:1974` — the attestation section SR-12's F13 found missing | Deterministic outputs, frozen teacher, mutable student; residual defects closed post-PASS at `:831`; the "equivalent mutant" adjudication was reopened and corrected by the orchestrator at `:685` | The toy is an analogy. `docs/SR12_INDEPENDENT_REVIEW.md` F6 required disclosing the **sign** of the normalization analogy (toy inflates; source net 0.42) — a correspondence defect, now closed, that shows the analogy's direction is not free |
| **SR-06** | Generic stability checks: finite values, masked losses, empty-mask errors, gradient validity | `[x]` | QA **PASS**, `:1004` — after a FAIL and rework at `:854`, follow-up `:1157` | **Eight distinct truncation mutants** on `check_gradient`'s comparison loop, all killed; QA independently reconstructed and ran the mutants the builder had reported as unrun (M-S4, M-S6, M-S7, M-S8, most of M-S10) — all killed; for `f = 1e-9·x²` a claimed 2e-7 passes at defaults, **2e-6 is caught, and 2e-7 is caught at `atol=1e-12`** | The journal's own count: *"**Two** residual validator holes, routed as follow-ups (not blocking)"* plus two *"Also unpinned"* items (`:1017-1021`). They were **fixed after the PASS** (`:1185-1196`) with **no re-attestation** — and the fixes landed in the *same commit* as the PASS record, so git cannot separate them. **This is the one task whose attested bytes are UNKNOWN: §3.10.** Carried by `test_stability` (57 tests, 1 bare-env skip) |
| **SR-07** | Non-in-place ops; optional device/precision comparison; no RFdiffusion inference | `[x]` | QA **PASS**, `:2067` — marked only once its dependency SR-05 was verified | 89 mutants: 61 killed, 28 survived, real gaps recorded (`:2103`); the "seven equivalent mutants were not equivalent — and two were security-relevant" re-adjudication at `:2312` | **The device leg is almost entirely unexercised here.** `test_tensor_ops` records **110 tests with 82 bare-environment skips** (`scripts/test_baseline.txt`), i.e. the torch/device comparisons do not run without torch. CUDA leg UNKNOWN; ER-09's CUDA half stays UNKNOWN-NEEDS-EXECUTION |
| **SR-08** | Toy checkpoint metadata, provenance hashes, safe reload, no untrusted pickles | `[x]` | QA **PASS**, `:1026` | **20,000 random 2–6-byte edits → 0 accepted**; pretty-printing, BOM, `1.0`→`1e0`, key reordering all rejected *even with a recomputed valid digest*; float fidelity bit-identical over **19,994 random 64-bit patterns** via `struct.pack`; atomic write verified under injected failures at `mkstemp`/`fdopen`/`fsync`/`os.replace`; files mode **0600**; the honest-limit test shows the digest **is not a signature** | `docs/SR12_INDEPENDENT_REVIEW.md` **F1** required correcting "silently incompatible" in `src/toy/checkpoint.py` — upstream shows a **loud** `KeyError` and the claim was INFERENCE. That fix landed **after** the attestation commit; **MEASURED as docstring-only (11 insertions / 6 deletions, no executable line) — §3.10, so it closes.** Residuals recorded at `:1046-1052`, incl. *"**`test_oversize_refused` is vacuous**"* and the AST no-pickle scan being *"a deny-list on one file … hygiene, not proof"* |
| **SR-09** | Benchmark protocol: controls, disconfirming cases, CIs, evidence thresholds; no fabricated results | `[x]` | **PASS, round 7**, `:6362` — at **v1-DRAFT-r10**, *"first PASS for this task since the r3/r4 close-out"*; the earlier `[x]` was **withdrawn in round 6** (`:5372`) | All five criterion clauses checked against the text: controls; disconfirming cases (H3 registered as an expected FAIL); CIs (B=10,000, 98.75% = 1 − 0.05/4, t cross-check, four enumerated assumptions); evidence thresholds; no fabricated measured results. The reviewer's numeric sweep was **method-cross-checked**: 1199 tokens / 79 distinct values from r10, then the same command on the r9 blob → **1116, matching the r9 reviewer exactly** | Two notes (**N-a**, **N-b**) are **deliberately unfixed** (`:6422`): editing the file would make the attested text and the live text differ — *"precisely the defect that unmarked SR-09 in the first place"*. The document's own header still says r10 is unreviewed — a live contradiction, §8.1 |
| **SR-10** | Synthetic benchmark scoring + CI reporting; statistical fixtures and repeatability | `[ ]` | **FAIL, round 12**, `:8462`; previously PASSed at `:2504`, `:5590`, `:6549` and was **unmarked in round 11** (`:8241`, `:8312`) | The round-12 fix closed the stored-key lane: **129/129 agree, 0 complaints** post-fix, from a sweep **derived by walking a real payload** (`:8394`). `test_benchmark` 280 → **301 OK** on 3.12.4 and 3.13.5 | **The probe side of the same lookups is open.** Two **pre-existing** flips (byte-identical at `HEAD~1`), mutant **M9c unkilled**, and the AST tripwire's own coverage sentence is false — §3.1 |
| **SR-11** | Neutral robustness probes (seeds, benign shifts, missing inputs, stability); immutable scorecards | `[ ]` | **FAIL, round 10**, `:7818` (own label "(7th)"). It had PASSed four times (`:1582`, `:3215`, `:3885`, `:4758`) and **regressed from PASS to FAIL** at `:4890`/`:4937`; **six consecutive FAILs since** (`:4890`, `:5253`, `:5440`, `:6549`, `:7094`, `:7818`). The round-11 fix at `:8025` has **never been re-attested** | Round 11's fix: `test_robustness` 164 → **181 OK** on 3.12.4 and 3.13.5; the reason-generator's complaint set went **7 → `[]`**; `scripts/demo.py` → `DEMO OK`, exit 0 | `probe_shift`'s `fixture_factory` escape **cannot be closed by any check** — §3.6. The last recorded blocking finding is **D** (`:7824`, `is` instead of `==` on a `str` Enum), closed by the unattested round-11 fix. Blocked behind SR-10 regardless: SR-11 `Depends:` SR-10. Three of its PASSes were explicitly *"unmarked pending SR-10"* (`:3885`, `:4663`) |
| **SR-12** | Independent QA of method fidelity, unknowns, risk of incorrect safety claims; explicit PASS/FAIL/BLOCKED | `[ ]` | **FAIL**, `docs/SR12_INDEPENDENT_REVIEW.md:11`, journal `:1781` | Verdict table: method fidelity PASS; toy-to-source correspondence PASS with 3 defects; unknowns register PASS with 4 defects; **risk of incorrect safety claims FAIL**; cross-document consistency FAIL; **PROGRESS/BLUEPRINT attestation FAIL**; reproducibility PASS. Four orchestrator failures were found (`:1799` protocol/scorer disagreement F2; `:1811` a checkbox marked with no recorded attestation; `:1818` two tasks marked on unverified dependencies; `:1824` an attestation no longer matching the artifact), and a **fifth** later: `:2019` *"the commit trail is unreliable, in a kit built on provenance"* | SR-12 `Depends:` SR-03 **and SR-11**, which is open, so a re-run is not yet eligible. The review's own §8 "Limits of this review" is the governing scope statement. Whether the F-items are now all closed is **UNKNOWN to this report** — I did not re-run the review |
| **SR-13** | Dashboard: source-diff inventory, toy curves, scorecards, uncertainty labels; missing results render UNKNOWN not 0 | `[ ]` | **FAIL, round 10**, `:7926` (own label "(8th)"). Its last PASS was conditional, round 2, `:3468`; **nine consecutive FAILs since** (`:3907`, `:4273`, `:4469`, `:5011`, `:5253`, `:5590`, `:6439`, `:7188`, `:7926`). The round-11 fix at `:8241` has **never been re-attested** | Round 11's fix: `test_dashboard` 240 → **247 OK** on both interpreters; **8 of 120** forgeries moved the page pre-fix, **0 of 120** post-fix; **81 key forgeries: 77 differed pre-fix, 0 post-fix**; 12 code mutants all killed; `KEY_LANE_FIGURES` asserted at **48/48, 42/42, 4/4** (verified present at `tests/toy_tests/test_dashboard.py:5607-5611`) | Two **declared** `"bare"` residuals remain open by assertion — §3.4. Round 10's Finding B was *"the first breach of the acceptance clause's **POSITIVE** half"* (`:7957`): **"For eight rounds this clause has been read only in its negative direction ('never 0'), which holds"** (`:7969`) — a missing row rendered as **no row at all**, neither UNKNOWN nor 0 |
| **SR-14** | Human review of claims; immutable audit log DRAFT → REVIEWED → SUPPORTED/UNSUPPORTED | `[ ]` | **PASS (4th), round 5, `:5253`** — its last verdict, and **unmarked anyway**. PASSes at `:1765` (then reverted by SR-12), `:3923`, `:4544`, `:5097`, `:5253`; one FAIL, round 2 `:3490`, on **test gaps only** — *"the production code held under every attack"* | *"SR-14 — PASS, unmarked pending SR-13"* (`:4544`), called *"The strongest attestation of the session"*; *"**SR-14 PASSES and stays unmarked**, because its dependency SR-13 does not"* (`:4472`) | Marked `[ ]` **only** because `SR-14 Depends: SR-13`, which is open — the `[x]`-on-an-unchecked-dependency defect SR-12 raised as **F12**, honoured rather than repeated. **The standing PASS is from round 5 and is seven rounds stale** — `awk 'NR>5260 && /SR-14/'` shows SR-14 is not mentioned in the journal after `:5253` except in the OPEN enumeration. But its artifact has **not** drifted: `git log --oneline -- src/toy/claim_ledger.py` ends at `3869655`, and `git merge-base --is-ancestor 3869655 90b8dfa` confirms that commit **precedes** the round-5 era, with **0** later commits touching the file. **MEASURED: the round-5 PASS still covers HEAD's bytes** — so staleness here is calendar, not content |
| **SR-15** | Deterministic CI, lint/test scripts, pinning, offline demo, clean-clone; complete offline regression suite passes | `[ ]` | **FAIL, round 10**, `:7718` (own label "(8th)"). **Never passed, at task level, once: all ten recorded attestations are FAIL** (`:3514`, `:3931`, `:4367`, `:4572`, `:5067`, `:5253`, `:5708`, `:6653`, `:7307`, `:7718`). Per-claim at `:7722`: deterministic **PASS**, pinning **PASS**, **offline BLOCKED**, clean-clone **PASS**, complete offline regression suite **FAIL**. The round-10 fix at `:8128` has **never been re-attested** | Round 10's fix replaced the prose claim with a driven enumeration (`:8128`, *"the enumeration IS the claim"*) and derived the file scope from `CLAUDE.md` itself; `test_scripts` 154 → **156 OK** on 3.13.5 (with `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`) and 3.12.4; `lint.sh` → `LINT: OK`. Its own fix entry concedes the open claim at `:8227`: *"**offline BLOCKED** (control defined, unrun)"* | **"offline" is BLOCKED, not failed** — §3.3, and "offline" is a word in this task's own acceptance clause (*"complete **offline** regression suite passes"*). Both CI **jobs** have never been observed running — §3.9. Three declared evasions of the prose mechanism stand — §3.7 |
| **SR-16** | Final independent QA, claim-evidence matrix, limitations, screenshot/demo, release note | `[ ]` | **Never attested.** No attestation entry for SR-16 exists in the journal | — | `Depends:` SR-15, which is open. Its clause *"all accepted tasks supported"* cannot be satisfied while SR-10, SR-11, SR-13 and SR-15 are open. **This document is an input to SR-16, not its completion** |
| **SR-17** | Human gate: decide whether any real model run, dataset use or biological tuning is appropriate | `[ ]` | **Never attested, by design** | — | Blueprint: *"**Depends:** SR-16 + explicit human review. **Do not auto-start.** No real model weights, PDB training, synthesis, or protein generation are part of SR-00–16."* Blueprint "Definition of done" item 7: *"SR-17 stays blocked pending explicit review; completion signal is for the audit/toy-replication system only."* Status: correctly blocked |

### 2.3 Reading the matrix honestly

Ten of seventeen tasks are verified. Three — SR-11, SR-13, SR-15 — have failed repeatedly, and SR-15
has never passed at task level in **ten** recorded attestations. Two more — SR-14, and SR-11 at its
PASS moments — were held unmarked by dependency discipline rather than by a defect of their own, which
is the right outcome and not a hidden negative: it is SR-12's **F12** being honoured.

Three structural facts are worth reading off the table rather than inferring:

1. **Every open task except SR-16 and SR-17 has a landed fix that has never been attested** — SR-10's
   round-12 fix was attested and failed, but SR-11's (`:8025`), SR-13's (`:8241`) and SR-15's
   (`:8128`) have had no attestation at all. So the current tree is, for three tasks, in a state
   nobody has independently reviewed. That is not a claim that they would fail; it is a statement
   that the question is open.
2. **The three unattested fixes each answer the finding that caused the last FAIL**, with measured
   before/after figures recorded by their owners (the Evidence column). Those figures are the owners'
   and are labelled as such.
3. **Two of the ten marked tasks carry a recorded gap in their own attestation trail** — SR-00 has no
   verdict section, SR-06's attested bytes cannot be separated from its post-PASS fixes (§3.10).

The **methodological findings of §4 and §5 are the most valuable output of this project**, more
valuable than the task count, and they are the part that would survive being ported elsewhere.

---

## 3. The residuals register

Each entry: where it is, what closing it would take, whether it is **declared** (the tree says so and
a test asserts it stays open) or **undeclared**, and its measured consequence.

### 3.1 `benchmark.py`'s probe-side variable-key lookups — UNDECLARED until round 12, now recorded

**Where.** `src/toy/benchmark.py`. The module's two defences against a lying mapping key are an AST
tripwire over the source text and a payload walk over stored mappings. The tripwire's own docstring
(`tests/toy_tests/test_benchmark.py:5033-5036`) states the division:

> OUT OF SCOPE, stated so the sweep does not read as larger than it is: a lookup whose key is a
> VARIABLE (`self.metrics[k]`, `series[metric]`). No static rule resolves what word those hold, and
> **they are covered instead by the payload walk** in `EveryWordLookedUpInAStoredMappingIsSwept`,
> which sees the read however it is spelled because it hooks the mapping rather than the source text.

**That sentence is false in a specific way**, and the round-12 attester located it exactly
(`docs/PROGRESS.md:8516`): *"the walk only reaches record mappings. So a **variable-key lookup into a
module constant** is covered by **neither**, and there the lie is on the **probe**, which
`_word_keyed` cannot help with because the stored keys are honest."* CPython gives the reflected
comparison priority when the probe is a `str` subclass, so a lying probe beats a plain stored key.

**Measured consequence — mutant M9c is unkilled.** `docs/PROGRESS.md:8525`: a new mapping field plus a
verdict-deciding variable-key read of it survives all three module suites (**729 OK**). Recorded with
its own counter-evidence, which is worth keeping: *"two earlier attempts at it were killed
incidentally"* — one by the `len(literals) == 42` pin, one by the normalise-before-checking sweep —
*"The module's defence-in-depth is denser than the key-lane machinery alone."*

**Two pre-existing flips in the same lane**, both reachable through public constructors with **no
`object.__setattr__`**, both measured byte-identical at `HEAD~1` so neither is a regression from the
round-12 fix:

- **FINDING A** (`docs/PROGRESS.md:8484`) — `benchmark.py:1204,1206,1208,1223` and `:1852`.
  `PRIMARY[self.hid]` runs on the caller's `__hash__`/`__eq__`. A `str` subclass storing `'H3'` that
  also answers to `'H1'` makes `PRIMARY[liar]` return **one** component where H3 requires two, **so
  the selectivity component — the shuffled-control comparison — is dropped and never evaluated**, and
  `JointResult`'s `h.hid != hid` check reads False so the construction is accepted.
  **`JOINT_UNSUPPORTED` → `JOINT_SUPPORTED`**, with nothing in the output saying a requirement was
  skipped. The honest short build raises `ValueError: wrong number of components for H3`.
- **FINDING B** (`docs/PROGRESS.md:8500`) — `benchmark.py:1867,1971,2020,2309`. A `subject_kind`
  liar storing `'fixture'` that also answers `'trained'` is accepted, **renders as `'fixture'`**, and
  the JOINT record stores `subject_kind_code = 1.0` — the **trained** code. The recompute then
  reports `subject_kind 'trained'`, `JOINT_SUPPORTED`. **A declared scorer-validation fixture
  reporting as a trained subject, and the recompute does not catch it** — *"so `_word_keyed` has
  nothing to normalise: the record's key is honest and the forged value was already written."*

**What holds, stated beside what does not:** the stored-record lane is fail-closed for Finding A — a
recompute raises `records missing for ['H3a','H3b','H3a_conv','H3b_conv']`. The consequence is for a
consumer reading `JointResult.verdict` or `run_study`'s return directly.

**What closing it would take.** A probe-side normalisation at the lookup sites, or a type gate on
`hid` and `subject_kind` at construction. The attester flagged the scope question rather than hiding
it (*"if the orchestrator judges the probe lane out of SR-10's scope, PASS is defensible"*); the
orchestrator's call was that it is in scope, so **these are why SR-10 is unmarked**
(`docs/PROGRESS.md:8580`).

**Count check, run here.** Re-implementing the tripwire's own rule from its stated description
(AST; `m[k]`, `m.get(k)`, `k in m`; annotation subtrees excluded) over `src/toy/benchmark.py`
reproduces the pinned figures exactly: **42 literal string keys and 1 f-string key**, the f-string
being `f'gate_{n}'` at `src/toy/benchmark.py:2267`. The pin
`tests/toy_tests/test_benchmark.py:5093` asserts `len(literals) == 42`. The attester's **46
variable-key lookups** figure I could **not** reproduce — see §7.3.

### 3.2 `verdict_from_records` enforces no instance check — DECLARED, deliberately not closed

**Where.** `src/toy/benchmark.py:2092`:
`def verdict_from_records(records: Sequence[ExperimentRecord], cfg: Optional[BenchmarkConfig] = None)`.
MEASURED here: `awk 'NR>=2092 && NR<=2260 && /isinstance/' src/toy/benchmark.py` → **no output**. The
annotation is documentation; nothing enforces it.

**Consequence, measured** (`docs/PROGRESS.md:8346`): *"a plain object carrying `name`, `metrics`,
`evidence_class` and `provenance` reaches **every** lookup"*, and pre-fix, with duck-typed records plus
the key liar, the result was **`JOINT_SUPPORTED`, `bound = 6089f9b81710`, `reasons = ()`, no tampering
primitive anywhere.** **So a duck-typed record bypasses every `schema` validator** — hash format,
evidence class, metric types. The journal's conclusion is the sharp one: *"That makes the finding that
unmarked SR-10 strictly more severe than I recorded it."*

**Why it is open, in the owner's words** (`docs/PROGRESS.md:8452`): the key lane is closed for a
duck-typed record either way, *"which is measured"*, but making the annotation load-bearing is a
contract decision the owner declined to take unilaterally, *"partly because one of my own new tests
uses a duck-typed record deliberately to document the route."* The round-12 attester added the reason
the divergence from `schema` is **necessary** rather than merely acceptable (`docs/PROGRESS.md:8567`):
*"`verdict_from_records` enforces no instance check, so its mappings may never have passed a
construction boundary at all — there is nowhere to raise — and raising inside the recompute would
downgrade 'refuse with a named reason' to 'throw', which is **weaker** for a consumer."*

**What closing it would take.** A decision, not a mechanism: either an `isinstance` gate at the
entry (which changes the documented error contract and breaks a deliberate test), or a declared
narrowing of the annotation's meaning.

### 3.3 "offline" is BLOCKED — no network-denied run has ever been attested

This is a **BLOCKED**, not a FAIL, and the distinction is the project's. Round 7
(`docs/PROGRESS.md:6653`) downgraded it from PASS: *"**And 'offline' is downgraded from PASS to
BLOCKED**"*; round 8 (`:7309`) and round 10 (`:7720`) both record it per-claim as **offline
BLOCKED**.

**What is attested, and what is not** — `README.md`, in its own corrected words, which are sharper
than any paraphrase:

> **Every connection the suite makes targets loopback.** The suite *does* attempt connections — the
> guard canary, and the negative controls that prove the guard's **code path** is load-bearing — and
> every one of them targets loopback. **This paragraph used to assert "No step reaches a remote host"
> and that the controls prove the guard is load-bearing; both were stronger than the evidence.** The
> controls prove the guard's code path fires, not that egress is denied, and **no run has ever been
> observed in a network-denied environment** — including the two bare Linux containers that measured
> 1252/95/0, which **had network**. The guard was observed *present* there, not *load-bearing*.

and on the guard's nature:

> It is a tripwire on names, not a sandbox, and it is **not** a claim that the suite opens no socket …
> **This sentence used to end "so nothing leaves the host", and that was an overclaim**: targeting
> loopback is a property of the *addresses the suite asks for*, which is tested; it is not a property
> of the *host's egress*, which has never been observed. **Hermeticity is unattested.**

Round 10 verified that no document asserts hermeticity (`docs/PROGRESS.md:7810`): checked across
`README.md`, `CLEAN_CLONE.md`, `ci.yml` and `run_tests.sh` — *"all state it is **unattested** and
name the unrun measurement."* One wording note, no finding: `ci.yml:9-10` asserts "NO STEP … reaches
a remote host" (arrival, not the address asked for) and is *"rescued only by the following
sentence"*.

**The measurement that would attest it is defined and deliberately unrun.** It lives in
`docs/CLEAN_CLONE.md`'s Known-limits bullet, which `README.md` points to by name. Reproduced
faithfully in §3.3.1 below.

**What closing it would take.** Running exactly that defined procedure in an environment where egress
is actually denied, and recording the result. Nothing in the tree can substitute for it: a loopback
target is a property of the address asked for, not of the host.

### 3.3.1 The unrun measurement, as `docs/CLEAN_CLONE.md` defines it

It is the third bullet of `docs/CLEAN_CLONE.md`'s section *"Known limits of this documentation (read
before trusting CI)"* (`:1040`). Quoted at `:1063-1076`, in full, because a paraphrase would lose the
three-part structure that is the whole point of the definition:

> - **Hermeticity is unattested: a network-denied environment has never been observed.** Every
>   statement in this document about nothing leaving the host rests on (a) the loopback-only targets of
>   the connections the suite really makes, asserted by
>   `test_no_executed_connection_target_in_the_suite_is_non_loopback`, and (b) the runtime socket
>   guard, which is a tripwire on names and not a sandbox. The Linux containers above **had network**,
>   so the guard was observed *present*, not *load-bearing*: **a guard observed running is not a guard
>   observed working.** **The measurement that would attest it, defined here and NOT run:** take the
>   same bare container, remove egress (no default route, or a deny-all egress policy, or an empty
>   network namespace with only `lo` up), and record three things in one session — (1)
>   `./scripts/run_tests.sh --expect none --twice` ends `RESULT: OK` with the same 1252/95/0 and the
>   same skip list as the networked run, so no test is silently passing *because* a connection failed;
>   (2) a positive control in that same environment shows egress really is denied (an outbound TCP
>   connect to a routable address fails with `ENETUNREACH`/`EHOSTUNREACH` rather than `ECONNREFUSED`);
>   (3) `python3 scripts/demo.py` and `./scripts/lint.sh` also pass there. Until all three are
>   recorded, "offline" in the title of this document is a statement about what the kit *asks for*, not
>   an attested property of a run.

Three features of that definition are worth naming, because they are what make it a *definition* and
not an intention:

1. **It specifies the environment three alternative ways** (no default route / deny-all egress policy
   / empty netns with only `lo` up), so it cannot be dodged on a technicality about how egress was
   removed.
2. **It requires a positive control** — `ENETUNREACH`/`EHOSTUNREACH` rather than `ECONNREFUSED`. This
   is the clause that distinguishes "egress denied" from "nothing was listening", and it is exactly
   the distinction round 7 found missing when it downgraded the claim. The journal's own statement of
   the correction (`docs/PROGRESS.md:6662-6667`): *"No network-denied environment has been attested;
   the Linux container had network, so the guard line was observed *present*, not load-bearing. I did
   not test it and do not infer it."* — and the sentence that generalises it: **"A guard observed
   running is not a guard observed working."**
3. **It requires all three recordings in one session**, so a green suite cannot be assembled from a
   networked run plus a separately-claimed denial.

It also carries its own expected figure — *"the same 1252/95/0"* — which is a figure of the `81d450a`
era. Re-running it at HEAD would need the current totals, which are UNKNOWN to this report (§7.1).
That is a detail, not an objection: the three-part structure is what matters and it does not depend on
the number.

### 3.4 The declared `"bare"` lane in `dashboard.py` — DECLARED, asserted still open

**Where.** `src/toy/dashboard.py:698-702` declares the lane and names its two members, and
`STORED_WORDS` carries them at `:710` (`"GateResult": {"name": "key", "reason": "bare"}`) and `:725`
(`"MetricValue": {"reason": "bare"}`). The declaration, quoted:

> `"bare"` a DECLARED RESIDUAL: rendered bare, through the caller's `__str__`, and deliberately NOT
> pinned. Two entries, both refused by an earlier round on the record and neither re-opened here:
> `GateResult.reason` (round 5) and `MetricValue.reason` outside `_untrusted`, which is a note. **The
> pin MEASURES what a lie does to each and asserts the residual is still OPEN, so it cannot be
> forgotten, cannot be silently widened, and goes red if it is ever closed.**

**The assertion exists and I read it**: `tests/toy_tests/test_dashboard.py:5802`,
`test_the_two_bare_string_residuals_are_still_open`, whose body forges `GateResult.reason` and
`MetricValue.reason` and fails with *"`GateResult.reason` is no longer rendered through the caller's
`__str__`: delete this residual and say so"*. It also asserts the bare set is exactly `{"reason"}`.

**Measured consequence**, from that test's own docstring: both are rendered through the caller's
`__str__`, so the text shown is not the text stored — **18 of 90 forgeries moved the gate table with
JOINT_SUPPORTED standing.** The ruling stands because *"that is a display discrepancy in an
explanatory cell, not a figure and not a decisive word"*. Round 11 left both untouched with **0 diff
occurrences** and the right caveat (`docs/PROGRESS.md:8324`): *"nothing I added implies mechanism has
settled the asymmetry."*

**What closing it would take.** Routing both through `_untrusted`/`_word` — and then deleting the
assertion, which is designed to go red on exactly that change.

### 3.5 `_plain_value` walks only `list`/`tuple`/`Mapping` — DECLARED

**Where.** `src/toy/schema.py:122-190`. MEASURED by reading: the function special-cases `None`,
`Enum`, `bool`, `str`, `float`, `int`, `Mapping`, and `(list, tuple)`; its last line is a bare
`return x`. **A container of another type is returned unchanged and its elements are not collapsed.**

**Declared, with the consequence stated rather than left to be discovered** —
`src/toy/robustness.py:1952-1957`:

> ONE LIMIT INHERITED FROM `_plain_value`, stated rather than left to be discovered: it walks `list`,
> `tuple` and `Mapping`, so **a container of ANOTHER type (a `range`, a generator, a custom
> `Sequence`) is returned unchanged and its ELEMENTS are not collapsed here.** The places where such
> elements decide anything re-normalise them: `_check_seeds` (`int.__int__` on every seed),
> `Scorecard.__post_init__` (`_plain_text` on every non-claim), `precision_sweep` (each `param`
> crosses this boundary again, one call down) and `deep_freeze`, which refuses to freeze a container
> it does not recognise at all.

The same comment declares what the boundary is **not**: *"THIS IS NOT A TAMPER BOUNDARY … The
guarantee is that the value a gate INSPECTED is the value the caller's object stores — OR that the
call was refused because the object stored no such value."* That is a disjunction, not a coverage
claim, which is why it survived rounds that killed coverage claims.

**One hole in the identity property, measured and declared** (`docs/PROGRESS.md:7496`):
`schema.py:173`'s `changed = type(x) is not dict` means a non-`dict` `Mapping` (a `mappingproxy`) is
returned as a **new plain dict** — so *"the 88/88 identity property holds only because every
canonical call passes a plain `dict`"* — and `MappingProxyType` is the type `deep_freeze` itself
produces, so round-tripping a frozen `details` through a public parameter hits it. The card is
unaffected (`content_hash` identical); the defect is confined to the allocation-identity claim.

**What closing it would take.** Walking `Sequence` generally (which risks consuming a generator — the
journal notes at `:1196` that *"generators are consumed once"*), or a refusal at the four named
re-normalisation sites. Two one-line resolutions for the `mappingproxy` half were offered and left to
SR-04's owner.

### 3.6 `probe_shift`'s `fixture_factory` — DECLARED, and **cannot be closed by any check**

**Where.** `src/toy/robustness.py:1734-1747`, `_WHY_CALLABLE_FIXTURE`. Quoted from the declaration
itself:

> THE OTHER CONSEQUENCE OF NOT TYPE-CHECKING THE RETURN, measured by round 11's reason-coverage probe
> and **NOT closed**: a factory returning something with no `pred` attribute at all raises
> `AttributeError` out of `probe_shift`, **OUTSIDE the `(ValueError, TypeError, ArithmeticError)`
> family the probe declares.** It is left open, unlike the `rows=Lo(2)` escape … because that one came
> from the MODULE's own code and **this one cannot be closed by a check at all: the factory is the
> caller's callable and may raise any exception before it returns anything, so a return-type gate
> would move the escape rather than remove it.**

**Measured consequence** (`docs/PROGRESS.md:8111`): `fixture_factory=lambda s: object()` raises
`AttributeError` out of the declared family. **No card is produced, so no status flip.** That is the
whole consequence, and saying so is more useful than the exception class.

**What closing it would take: nothing available.** This is the one residual in the register whose
closure is not a matter of effort. A return-type gate relocates the raise; it does not remove the
caller's freedom to raise first. The owner also declined to type-check the fixture intake points,
because that would re-open round 8's deliberate `transform` decision and its pinned 1e33 measurement.

### 3.7 Three evasions of the prose-honesty mechanism — DECLARED, each with a measurement

Round 10 confirmed all three exactly as their author had declared them
(`docs/PROGRESS.md:7803-7816`):

1. **A genuine paraphrase exemption note is accepted.** A declared row noted
   `"because this filesystem distinguishes case"` — a true paraphrase of the live category — is
   **accepted, rc=0**. The note rule is an exact-string/word test, not a semantic one.
2. **One sentence that both asserts and retracts a claim defeats any marker rule.** One sentence in
   `ci.yml` reading *"This header used to say nothing leaves the host, and nothing leaves the host."*
   leaves the needle test **green** — *"a single sentence that both asserts and retracts defeats the
   sentence rule, exactly as its author said it would."* The same shape appeared earlier as a real
   obstacle, not a hypothetical: round 8's F3 (`:7351`) found that
   `scripts/run_tests.sh:291` carries both a retracted phrase and *"It used to be 192.0.2.1:9"*, so
   *"a line-window retraction check cannot pin a claim whose line also carries an unrelated retraction
   marker."*
3. **A `globals()`/`setattr` rebind is invisible to the static parse.** Conceded in the source
   (`scripts/run_tests.sh`, the `EXEMPT_CATEGORIES` block) — *"a binding made through `globals()[...]`
   or `setattr` is not a Name in Store context and so is invisible to it"*. The mitigation sentence
   that followed it is the subject of §4.

**What closing them would take.** (1) and (2) are properties of natural language, not gaps in a
regex; the project's own conclusion is that the loose direction is a **declared legitimate cost** and
the alternative (a four-word note fold) was measured to produce a **legitimate deny** that stops the
run on an honest second category (`:7765`). (3) was addressed by round 9's registry attestation and
then re-opened as a one-line window — §4.

### 3.8 `schema.py`'s `MetricValue.__post_init__` validates through normal attribute access — UNDECLARED in `schema.py`

**Where.** `src/toy/schema.py:352-386`. Every read in the validator is `self.value` / `self.reason` —
normal attribute access. MEASURED consequence, recorded as a cross-owner note at
`docs/PROGRESS.md:8120`:

> `MetricValue.__post_init__` validates `self.value` through *normal attribute access*, so a subclass
> overriding `__getattribute__` makes the constructor validate **and store** a value it was never
> given — `Sub(None, None)` stores `1.0` through the public constructor.

**Why it was not fixed.** `robustness` is immune (both consumers are exact-type) and the resulting
object is indistinguishable from `measured(1.0)`, *"so it grants nothing"*; the one-line fix would be
`object.__getattribute__` in the "store what was checked" line. **`schema.py` was left untouched
because SR-04 is attested** — the same trade, named explicitly, that the project elsewhere records as
*"spending a fresh attestation for a sibling definition is the trade that unmarked SR-09."*

**Status note.** This is **undeclared in `schema.py` itself**: the class docstring at
`src/toy/schema.py:340-344` declares the `object.__setattr__` limit, not this one. It is declared only
in the journal and in `robustness.py`'s reason text. That asymmetry is itself the residual: a reader
of `schema.py` does not learn it.

### 3.9 Linux: the CI *path* is measured; the two CI **jobs** have never been observed running

**What was measured.** `docs/PROGRESS.md:6298`, *"The CI path, measured on Linux at last. Four
standing UNKNOWNs closed."* — two bare `debian_slim` containers on Modal at `cb8812b`, no pip installs
at all, `Linux-4.19.0-gvisor-x86_64-with-glibc2.36`, running **the kit's own runner** rather than a
bare `unittest discover`: `bash scripts/run_tests.sh --expect none --twice`. Results (`:6309-6316`):
**1252 ran / 95 skipped / 0 failed** on **3.12.10** and **3.13.3**, `RESULT: OK`, `run1 == run2` with
identical per-module counts and skip lists, **POLICY tokens none**, filesystem probed case-sensitive,
`packages_present == []`, and the macOS-generated `scripts/test_baseline.txt` passed against it. The
entry states what it closes (`:6320`): *"Both CI jobs go through `run_tests.sh`, and neither had ever
been observed. This is that path, on both matrix interpreters, green."*

**What is still not observed, in the tree's own words.** `docs/CLEAN_CLONE.md:1042-1043`, first bullet
of the same Known-limits section:

> - **The CI workflow has never been executed.** Its two jobs were never run on a hosted runner (none
>   was available); the commands they invoke were run locally and the YAML parses. `optional-deps`
>   remains unverifiable here.

and the Linux bullet, updated *after* the measurement, keeps the distinction explicit
(`docs/CLEAN_CLONE.md:1059-1062`):

> **What one configuration does not establish:** `optional-deps` on Linux, any non-`ubuntu`
> distribution, a hosted GitHub runner (see the first bullet — **the workflow itself still has never
> been executed**), the pinned torch/numpy combination, or hermeticity (next bullet).

The journal makes the same separation and names what CI would and would not catch
(`docs/PROGRESS.md:5830-5836`, *"CI read as text, never executed"*): *"**Would not catch:** F1 or F3 …
Neither job runs `--expect any`; both compare the **macOS-generated** committed baseline against a
Linux run."* Round 7 and round 8 both re-read CI as **text** (`:6746`, *"CI, read as text"*;
`:6755`), after the Linux path measurement.

**The two jobs, MEASURED from the workflow file:**

| job id | `name:` | line | what it runs |
|---|---|---|---|
| `core-no-deps` | `core, nothing installed (py${{ matrix.python }})` | `.github/workflows/ci.yml:53-54` | `ubuntu-latest`, matrix `["3.12","3.13"]`: `./scripts/lint.sh`; `./scripts/run_tests.sh --expect none --twice`; `python scripts/demo.py` (`:74-79`) |
| `optional-deps` | `torch+numpy pinned (py3.12)` | `.github/workflows/ci.yml:81-82` | `ubuntu-latest`, 3.12: the pinned install — **the only step in the workflow that touches a package index** — then `./scripts/lint.sh`; `./scripts/run_tests.sh --expect torch --twice`; `python scripts/demo.py` (`:92-104`) |

So the measured path covers `core-no-deps`'s *commands* on its two matrix interpreters, on one Linux
distribution, in a container rather than a hosted runner; **`optional-deps` has no Linux measurement
at all**, and neither job has been seen to run. The workflow header says so itself
(`.github/workflows/ci.yml:15-16`): *"What the suite tests is the address asked for; **no job has ever
run network-denied**, so hermeticity is UNATTESTED here exactly as it is in docs/CLEAN_CLONE.md."*

**What closing it would take.** One observed run of each job with its log — and for `optional-deps`,
the first execution of the pinned torch/numpy combination anywhere (`docs/CLEAN_CLONE.md` records that
pin as *"untested as a combination"*).

### 3.10 Post-attestation changes to attested artifacts — applied unevenly, and UNDECLARED

This is a residual in the **attestation process**, not in a module, and it is the one a reader of the
checkbox column should know about.

The project has a rule, stated when it was enforced (`docs/PROGRESS.md:1827`): **"An attestation of a
superseded version is not an attestation."** It was enforced twice, hard: SR-05's checkbox was
reverted because its PASS existed only as a phrase and *"the six residual defects fixed after that
PASS were never re-attested"* (`:1812-1816`), and SR-09's was reverted in round 6 because the box
attested r3/r4 while the live protocol was r9 (`:5372`, `:5378`).

**Three currently-marked tasks have the *shape* of that pattern in the journal. I checked each one
against git, and the pattern turns out to be real for only one of them** — the checks are below the
list. First, the shape as the journal records it:

- **SR-00.** `grep -c '^## SR-00 — QA verdict' docs/PROGRESS.md` → **0**. SR-00's PASS lives only
  inside its build entry (`:31`, `:39`) — *the exact criterion SR-12 used to revert SR-05*. And its
  artifact changed after that PASS: D1/D2 at `:50-55` renamed the test package
  `tests/toy/` → `tests/toy_tests/`, deleted a `__path__` hack, added `src/toy/__init__.py` and
  extended `.gitignore`. No SR-00 re-attestation exists.
- **SR-06.** PASS at `:1004` listed *"**Two** residual validator holes, routed as follow-ups (not
  blocking)"* plus two unpinned items (`:1017-1021`); they were then **fixed after the PASS** at
  `:1185-1196` (`ShapeError` for `Mapping`/`set`/`frozenset`, a new `UnderflowError`, report fields
  pinned). No re-attestation.
- **SR-08.** PASS at `:1026`; SR-12's **F1** then required correcting *"silently incompatible"* in
  `src/toy/checkpoint.py:13,45` because upstream shows a **loud** failure and the claim was INFERENCE
  (`:1831-1835`), closed at `:3860`. SR-08 was neither unmarked for it nor re-attested after the fix.

The project did check one of these and clear it: round 6 suspected SR-05 of the same shape because a
commit touched `teacher_student.py` after its attestation, measured the change as *"docstring-only
(`+13`, `0` deletions)"* with two new tests pinning the disclosure, and concluded **"SR-05 stands"**
(`:5420-5425`). **That is the right procedure, and it was never run for SR-00, SR-06 or SR-08. So I ran
it**, with `git log`/`git show` on each attested artifact. The results are three different answers, and
only one of them is a problem:

**SR-00 — CLEAR by measurement.** `git log --oneline -- tests/test_toy.py` returns **exactly one
commit, `f7eb976`**, the scaffold. The attested 4-test file is byte-unchanged at HEAD; the D1/D2
changes were to *packaging* (the test package's name, `src/toy/__init__.py`, `.gitignore`), not to the
file whose assertions QA re-derived by hand. The journal records the same check independently at
`:2001-2003`. **The missing attestation *section* is still real** (0 grep matches) — a provenance gap,
not an evidence gap.

**SR-08 — CLEAR by measurement, and the change is docstring-only.**
`git log --oneline -- src/toy/checkpoint.py` shows its last change at **`d96ec22`**, which
`git merge-base --is-ancestor 905bbfe d96ec22` confirms is a **descendant** of `905bbfe`, the commit
whose message records *"SR-06/08/09 verified (QA PASS)"*. So the artifact did move after the
attestation. `git show --stat d96ec22 -- src/toy/checkpoint.py` → **11 insertions, 6 deletions**, and
reading the diff, **every changed line is inside the module docstring** — the SR-12 **F1** fix, which
replaced *"silently incompatible"* with an explicit split: *"**SOURCE OBSERVED:** the keys differ, so a
checkpoint written by the script would not load into the unmodified upstream sampler. **INFERENCE, not
executed:** because upstream indexes the dict directly (and loads with `strict=True`), the expected
failure is a loud `KeyError`, not a silent one."* No executable line changed, so SR-08's acceptance
criteria (round-trip, corrupted-checkpoint) are untouched. **This one closes.**

**SR-06 — UNRESOLVABLE FROM GIT, and the reason is the project's own Orchestrator failure 5.**
`src/toy/stability.py`'s last change is **`905bbfe`** — *the very commit whose message records SR-06's
QA PASS* — and no commit after it touches the file. But that commit is also where the post-PASS
follow-ups landed: `git show 905bbfe -- src/toy/stability.py` is **31 insertions / 4 deletions**, and
`git show 905bbfe -- src/toy/stability.py | grep -cE '^\+.*(UnderflowError|ShapeError)'` → **3**, i.e.
the commit **introduces** the `UnderflowError` and `ShapeError` that the journal describes as fixes
made *after* the PASS (`:1185-1196`). **The attestation and the changes it does not cover are in one
commit, so git cannot say which bytes the reviewer read.** That is exactly
*"Orchestrator failure 5 — the commit trail is unreliable, in a kit built on provenance"*
(`docs/PROGRESS.md:2019`) landing on a specific checkbox. **Status: UNKNOWN, and it cannot be made
MEASURED from the repository as it stands** — only a re-attestation of SR-06 against HEAD would settle
it.

**What closing the register entry would take.** One re-attestation, of SR-06 only. SR-00 and SR-08 are
closed by the measurements above; SR-00's missing verdict section is a bookkeeping repair, not a
re-review. **So the correct summary is narrower than "three marked tasks rest on stale attestations":
one does (SR-06), one has a documentation-only drift (SR-08), one has none (SR-00).** I state it that
way because the wider sentence was the one I could not pin.

### 3.11 Residuals recorded in the journal but not reflected in the tree's own pinned text

**Where.** `tests/toy_tests/test_benchmark.py:4816` still reads *"So 29 of 129 forgeries move a
verdict, a subject kind or a reasons tuple, and that is the number this round is about."* The
round-12 attester re-ranked that bucket by direction and concluded (`docs/PROGRESS.md:8531`):
*"**13 escalations of 129**, of which 1 moves the joint verdict … 29 is a defensible conservative
bucket that errs toward over-reporting — the right direction for a safety audit — but **it is not the
escalation count. 116 is not usable.**"*

**MEASURED:** `grep -rn 'escalation' tests/ src/` → **no output**. The sharper classification exists
only in `docs/PROGRESS.md`. **What closing it would take:** one docstring edit — and a re-attestation,
which is why it was not taken.

Three further accounting defects in the round-12 fix's own tests and prose are recorded at
`docs/PROGRESS.md:8547-8565` and are **open as of HEAD**: (1) a sweep docstring attributing four flips
to the generator when only one is generator-produced; (2) `_mapping_fields` being a **hardcoded
two-entry tuple** while its docstring says *"walked off the OBJECT, not listed"* (complete today,
measured); (3) the enum table's `combine_joint` row being false, with the `_enum_member` wrap at
`:1140` measured to be a **no-op**. Each is evidence-real and attribution-wrong — the §4 shape, in
miniature, inside the fix that was written to answer §4.

---

## 4. The headline methodological finding

**The recurring defect was not the guard. It was the sentence describing the guard's reach.**

That is the journal's own sentence, at `docs/PROGRESS.md:7761`:

> Three rounds running, the mechanism was real and the sentence describing its reach was stronger than
> the mechanism. The magnitude converged from a class to a single line; the *kind* of defect did not
> change at all. **The recurring defect in this project is not the guard. It is the sentence about the
> guard's reach** — and unlike a withdrawn claim, which D4 pins, a *reach* claim has no mechanism.

### 4.1 The sequence, each round's mechanism beside the sentence that overstated it

Rounds 8–12 each found a **real mechanism** whose **written claim was wider than the mechanism**. The
table is ordered by round; the last two rows are round 6, included because they are the same shape
found earlier and because the rule the project drew from them is the sharpest statement of it:

| Round | The mechanism (real) | The sentence about its reach | What the gap actually was |
|---|---|---|---|
| 8 | runtime row checks on the exemption registry | *"the runtime half below is what covers a bad row **however it arrives**"* (`tests/toy_tests/test_scripts.py:2297-2299`) | **A whole class.** Only *malformed* rows were covered; the mutant the conceded door admits is **well formed**. Measured: `test_scripts` → **151 OK, rc=0. Unkilled**; runtime `RESULT: OK`, no POLICY token in any mode (`:7318`) |
| 9 | the run prints the registry it judged with | *"a row that arrives by **ANY route** — the literal, a rebind, globals(), setattr, an import — is a RED SUITE … `_REGISTRY_USED` closes **the one gap** this placement leaves"* | **One line.** The listing is printed at `:743-747`; the snapshot is taken at `:748`. *"The placement leaves two gaps; only the later one is closed."* Measured: `exemption registry: 2 row(s)` byte-identical to the declared literal, `RESULT: OK`, rc=0, **no POLICY token**, full module `Ran 154 tests … OK` (`:7725`) |
| 10 | `isinstance`-or-collapse on enum-typed parameters | `_WHY_ENUM`: a non-enum spelling is *"either refused by that `isinstance` or collapsed by the field boundary"* | **False for 2 of the 3 parameters it covers.** Neither happens for `ShiftSpec.kind`. True only for `build_scorecard.status_if_summarized` (`:7861`) |
| 10 | the withdrawn-guarantee scan | *"the complete list of routes"* / an enumerated file list | **Short by exactly the files nobody thought of, for the third time** — widened for `CLEAN_CLONE.md` in round 7 and `ci.yml` in round 9, and `README.md` and `lint.sh` still admitted the retracted phrase: `Ran 22 tests … OK` (`:7776`) |
| 6 (the same shape, earlier) | an operator sweep over `test_schema.py`'s sites | `test_schema.py:441`'s *"The last instance the operator sweep turned up"* | **False by four counterexamples** (`:5446`). The journal's extension of the rule is the keeper: *"a sentence claiming a sweep found the last instance is a claim about **absence**, and absence is not demonstrable by sweeping"* (`:5450`) |
| 6 | `Scorecard`'s route disclosure | *"HONEST LIMITS, **the complete list** of routes known to this module"* | Removed as a second **absence claim**, unasked (`:6080`) |

**The fix for an absence claim is deletion, not softening.** Round 6 recorded both removals that way
(`:6077`): the sentence was *"**deleted, not softened**, and replaced with a docstring that names all
four counterexamples and states the rule: **a claim that a sweep found the LAST instance is a claim
about ABSENCE, and sweeping cannot establish absence. A sweep can only report what it found.**"* That
is the one piece of this finding that generalises without any of the project's machinery.

**And the sweeps themselves kept being right to distrust.** Round 11 converted **five** `is`/`is not`
sites against `str`-backed Enum members in `robustness.py`, **three of which were already correct**
behind an `isinstance` gate, and converted them anyway for a stated reason (`:8066`): *"so the
invariant is a flat module-wide rule a test can pin instead of a per-site argument that was wrong
twice."* Round 12 then found **six** such sites in `benchmark.py` pointing in **mixed** directions and
measured that *"running `robustness.py`'s rule verbatim — rewrite to `==` — would have been WRONG
here, and I measured that before concluding it"* (`:8414`). A uniform rule that a test can pin beat a
per-site argument; and the rule still had to be re-derived per module rather than copied.

### 4.2 Why a reach claim is worse than a withdrawn claim

The project built a mechanism (**D4**) that pins a *withdrawn* claim: a retracted sentence that
reappears turns the suite red. **Nothing pinned a *reach* claim.** A withdrawn claim has a referent —
the old words — so a scan can look for it. A reach claim is a true-sounding sentence about a live
mechanism, and `CLAUDE.md` records why a lexical scan cannot find it:

> **A lexical sweep for overstated guarantees does not work; per-sentence assertion does.** Measured:
> of 60 absolute-claim sentences in three modules, 19 co-occurred with a guard term and ~2 were real
> claims — and the worst overclaim found in this project ("so a `MetricValue` built by the public API
> is sound") contains no modal, no "cannot" and no "guarantee". Pin each load-bearing sentence with a
> test whose doc-only mutant dies.

### 4.3 What actually worked: replacing the claim with a driven enumeration

Round 10's SR-15 fix is the project's answer, and its heading is the finding
(`docs/PROGRESS.md:8128`): **"the enumeration IS the claim."** F1 was closed *"and the prose claim is
replaced by a driven enumeration"* (`:8135`); the file scope stopped being a hand-kept list and was
**derived from `CLAUDE.md` itself** (`:8187`, "F3 closed by derivation — from the project's own
rules"); the threshold was *"chosen by measurement rather than by taste"* (`:8173`).

The same shape appears wherever the project stopped failing: SR-13's *"the enumeration is now
PERFORMED, not asserted"* (`:4794`, after `:4474` *"The enumeration was asserted, not performed — and
the defect recurred inside its own fix"*); SR-11's invariant restated as a **disjunction with both
halves asserted** (`:7414`); SR-13's rotten comment figures replaced by an asserted
`KEY_LANE_FIGURES` table *"living next to the loop that produces them"* (`:8270`), demonstrated red by
putting the stale numbers back.

### 4.4 The sibling shape: a limitation *accepted in writing* is the same liability as a reach claim

The reach claim says "this covers X". Its sibling says "this does not cover Y, and that is fine." Both
are sentences about a mechanism's edge, and the project found the second one just as load-bearing.

**The clearest case is SR-04's, and it is the one that cost a checkbox.** SR-04's first PASS listed,
under *"Accepted limitations (no code change possible or warranted)"* (`docs/PROGRESS.md:345-351`):
*"`object.__setattr__` and instance `__dict__` writes bypass any freeze, as for any Python object;
**`float`/`str` subclasses are accepted**; …"*. **That accepted limitation is precisely the route that
unmarked the task four rounds later** — round 5's F1 is a `float` subclass through the public
constructor, `MetricValue.measured(EqZero(7.0)).value → 0.0` (§2.2, SR-04 row). The limitation was
written down, judged harmless, and never driven.

**The second case is sharper still, because the mechanism was understood and the input was avoided on
purpose.** `docs/PROGRESS.md:5279-5289`, quoting the suite's own `_SneakyBound` docstring:

> *"`__eq__` is deliberately NOT overridden, because `MetricValue.__post_init__` normalises
> `value == 0.0` and would replace the instance — so a lying `__eq__` would make this test pass for the
> wrong reason."*

and the journal's conclusion, which is the rule this report takes most seriously:

> **The overridable dunder was identified, its value-replacing effect understood, and the finding was
> filed as a reason to avoid an input.** … **Standing rule, promoted: when you avoid an input because
> it would make your test pass for the wrong reason, that is a finding. Write it down as one.**

That rule is now in `CLAUDE.md`, with its two sibling smells (*"I needed `object.__setattr__` to
reproduce it"* → re-check the public route; *"it only holds for the default parameter"* → the range is
unswept), and it earned its keep twice afterwards: round 8's `subject_kind` finding
(`docs/PROGRESS.md:7237`, *"CLAUDE.md's own rule earned its keep again … and the public route
exists"*) and round 12's (`:8352`, *"The CLAUDE.md smell 'I needed `object.__setattr__`' was pointing
at a real public route, just not the one I checked first"*).

**The generalisable rule, in the project's own terms:** a sentence about coverage is a liability unless
a driven enumeration produces it — and that holds for the negative sentences as much as the positive
ones. This report's §1.3, §3.1 and §3.10 follow that rule deliberately; §9 lists where it could not.

---

## 5. The second methodological finding, with its numbers

**Generators derived from the invariant out-found skilled targeted search, repeatedly and measurably.**

### 5.1 The three measurements

| Case | Targeted search found | The generator found | Journal |
|---|---|---|---|
| SR-11, duck-typed half of the coverage probe (round 9) | **4** routes with status flips | **13** complaints: `benchmark_outcome.metric`, `make_measure_fixture.{rows,width,noise,magnitude_spread}`, `make_order_sensitive_fixture.big`, `probe_precision.param`, `shift_jitter.eps`, `shift_reorder_rows.rel_tol`, `shift_scale.{factor,degree}`, `shift_translate.c`, `standard_shifts.reorder_rel_tol` | `:7400-7408` |
| SR-11, reason-coverage generator (round 11) | **1** complaint plus a note | **7** complaints; 2 known, **5 new** — a truthy-int mask and a short mask accepted by `exact_masked_mse`, a `MetricValue` subclass accepted by `summarize_seeds`, and a non-callable producing a CLEAN measured claim in both `probe_missing_inputs` and `assert_no_silent_default`. Post-fix: **`[]`** | `:8025-8048` |
| SR-10, benchmark key sweep (round 12) | a hand-written list of **three** sites | a **fourth** site, **`gm.get(f"gate_{n}")`** — an f-string key — which **turned a failed global gate**: `loss_check_exempt` (1.0) answering as `gate_seed_list_frozen` (stored **0.0**) → `JOINT_INCONCLUSIVE` → **`JOINT_SUPPORTED`, `reasons = ()`** | `:8375-8383` |

Two of these are strictly stronger, not merely different: `shift_translate.c` and
`make_order_sensitive_fixture.big` **bounced** in round 8's subclass sweep and complained under the
duck spelling (`:7408`). And the round-12 f-string case is the thesis proving itself — in the owner's
words: *"My first AST sweep collected only `ast.Constant` subscripts and did not see it, because the
key is an f-string. … That is the round's own instance of your thesis — the hand-written list would
have been your three, and the fourth was the one that turned a global gate."*

**MEASURED here:** re-deriving the tripwire's rule reproduces **42 literal + 1 f-string**, and the
f-string is `f'gate_{n}'` at `src/toy/benchmark.py:2267` (§3.1). The pin
`tests/toy_tests/test_benchmark.py:5094` additionally asserts `"f'gate_{n}'"` is **not** in the
literal set — the finding turned into a standing assertion.

The journal's own summary (`:8047`): *"Twice now, a generator derived from the invariant has
outperformed targeted search on a module that had just been swept."* With round 12 it is three times.
The structural reason is stated at `:7185`: *"the defence was sound where applied, and the generator
that proves coverage swept one spelling."* The same shape was found in **two modules by two
different attesters in the same hour** (`:7253`): *"Two modules, two attesters, one shape: the
generator that proves coverage sweeps one spelling."*

### 5.2 The corollary the project learned the hard way: "uncovered" is not "consequential"

A larger finding list is worth less than a classified one. The benchmark key sweep's **129 cases** gave
**116 raw complaints** pre-fix, and the owner classified all 129 rather than reporting the raw number
(`docs/PROGRESS.md:8394`, and pinned in
`tests/toy_tests/test_benchmark.py:4805-4817`, measured on 3.12.4):

```
 13  agree already
 73  both raise; only the metric NAMED in the error differs   <- uncovered, NOT consequential
 14  forgery raises where the plainified mapping recomputes    <- fail-closed direction
 12  CONSEQUENTIAL: forgery recomputes where plainified raises
 17  CONSEQUENTIAL: both recompute, verdict / kind / reasons differ
```

So **29 of 129** move a verdict, a subject kind or a reasons tuple; the other 73 are *"a misleading
error string, not a verdict, and I say so rather than counting them as findings."*

**And then the attester sharpened it again, in the same direction.** Re-ranked by **direction**, i.e.
by how much a forger gains (`docs/PROGRESS.md:8531`): **13 ESCALATIONS** (12 turning a hard
`ValueError` into `JOINT_SUPPORTED`, **1** moving `JOINT_INCONCLUSIVE → JOINT_SUPPORTED`), **21
DENIALS** (more conservative than the reference; not exploitable), **9 LATERAL**, and the **73
both-raise** — of which **48** differ only in the metric named and **25** in which refusal fires. The
honest headline:

> **13 escalations of 129**, of which 1 moves the joint verdict … 29 is a defensible conservative
> bucket that errs toward over-reporting — the right direction for a safety audit — but it is not the
> escalation count. **116 is not usable.**

The same discipline was applied to SR-11's 88-parameter duck sweep (`:7869`): of the 15 distinct
parameters that accept a duck, **13 of 15 are harmless, measured** — for every accepted cell a
**plain** object of the same wrong shape is accepted identically, *"so the duck grants nothing over the
plain wrong-typed value the module explicitly delegates to the callee."* The journal calls this *"the
first time this project has done it"* and it is right to: **saying 13 is more useful than saying
116.**

---

## 6. Limitations, and what would change the conclusions

### 6.1 No network-denied run

See §3.3. Every offline statement in this kit is a statement about **the addresses the suite asks
for**, which is tested, not about **the host's egress**, which has never been observed. *What would
change it:* running the procedure of §3.3.1 in an egress-denied environment. Until then "offline" is
BLOCKED and SR-15 cannot pass; and because SR-16 `Depends:` SR-15, SR-16 cannot pass either.

### 6.2 Both CI jobs are unobserved

See §3.9. The CI *path* has been measured on Linux; the **jobs** have not been seen to run. *What
would change it:* one observed run of each job, with its log.

### 6.3 One machine, five interpreters, and figures that differ legitimately between them

All measurements are from a single macOS machine plus two short-lived Linux containers. The five
interpreters, and what each is for:

| Interpreter | Where | Role | Note |
|---|---|---|---|
| **3.12.4** | local | the reference interpreter for most attestations | carries pytest 8.4.1; needs no plugin workaround |
| **3.13.5** (ambient `python3`) | local | second interpreter for cross-checks | **MEASURED today:** a miniconda interpreter, version string `3.13.5 … packaged by Anaconda, Inc.`, **pytest 9.0.1** |
| **bare `venv --without-pip`** | local | the `--expect none` lane | needs no network to create |
| **3.12.10** | Linux container | CI-path measurement | not the local 3.12.4 |
| **3.13.3** | Linux container | CI-path measurement | not the local 3.13.5 |

**The ambient interpreter needs a workaround, and I verified it today rather than quoting it.**
`python3 -m pytest .` in an empty scratch directory fails with
`OSError: Could not find/load shared object file 'libllvmlite.dylib' from resource location:
'llvmlite.binding'`, and `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest .` succeeds
(`collected 0 items`). That reproduces the journal's precondition at `docs/PROGRESS.md:6977-6980` —
*"I took that 3.13.5 measurement with `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1` set and reported it without
the precondition. Without the variable the ambient 3.13.5 baseline is **147 FAILED (failures=4)**"* —
**without running any of this project's tests.** A figure from the ambient interpreter without that
variable is not comparable to one with it.

**Figures differ legitimately between interpreters and between moments.** The journal's own example,
recorded as a correction (`docs/PROGRESS.md:8476`): *"The three-module total is **729**, measured
twice. I had written **807** in one brief — simply wrong — and then retold the history as '807 was a
transposition of 708' **without saying that 708 was the pre-fix figure**. … **A figure carries its
moment as well as its interpreter.**"* Both 708 and 729 were quoted as "the" three-module total, and
both were right at their moment: 280 + 247 + 181 = 708 before the round-12 fix, 301 + 247 + 181 = 729
after.

**MEASURED here, as a counted series rather than a typed number.** Summing `scripts/test_baseline.txt`
at every revision that touched it (`git log --format=%h -- scripts/test_baseline.txt`, then
`awk '!/^#/ && NF {t+=$2; k+=$3}'` on each blob):

| commit | modules | Σ tests | Σ bare-env skips |
|---|---|---|---|
| `eb21eef` (**HEAD's baseline**) | 13 | **1351** | 89 |
| `29bd06b` | 13 | 1330 | 89 |
| `d2521e8` | 13 | 1304 | 89 |
| `ff18bd1` | 13 | 1279 | 89 |
| `cb8812b` | 13 | **1252** | 89 |
| `46bf2ee` | 13 | **1242** | 89 |
| `94ff241` | 13 | 1216 | 89 |
| `afe17c7` | 13 | 1160 | 89 |
| `8469d1c` | 13 | 1100 | 89 |
| `e2adb3c` | 13 | 1040 | 88 |
| `209adfc` | 13 | 1002 | 88 |
| `a574cc2` | 13 | 874 | 87 |

This series is why a bare total cannot be quoted without its commit. It also *corroborates* two
recorded run figures without re-running them: the first Linux measurement's **1242** (`:6132`,
3.12.10 / 3.13.3) is exactly the baseline total at `46bf2ee`, and the CI-path measurement's **1252**
(`:6312`, commit `81d450a`, whose baseline is `cb8812b`'s) is exactly the baseline total there. At
HEAD the baseline total is **1351**. That is a **floor**, not a run (§7.1).

### 6.4 A recorded wall-clock trade

`test_dashboard`'s wall-clock **roughly doubled** for coverage, and the trade is recorded rather than
hidden (`docs/PROGRESS.md:7610`): *"**Cost flag: `test_dashboard` roughly doubles in wall-clock** (600
forgeries × 2 full renders). The owner deliberately did **not** trim it, because the 600 is where the
findings were and 'trimming after the fact would have invalidated the measurement matrix.'"* Round 11
added a further **+17 s (+19%)**, itemised with what it trimmed — each trim **derived** rather than a
hand-written exclusion — and with what it considered and rejected (`:8244`).

### 6.5 The recorded rounds have not reached a fixed point — and the round count is itself a reconstruction

**MEASURED by enumerating the verdict-bearing entries for each task in `docs/PROGRESS.md`** (heading
sweep `grep -nE '^#{1,3} .*\bSR-NN\b'`, plus the per-task verdict lines inside the batch-round
sections, which carry verdicts in body text rather than headings — `:3869-3935` and `:5253` are the two
that do):

- **SR-15: ten recorded attestations, every one a FAIL. It has never passed at task level, once** —
  `:3514`, `:3931`, `:4367`, `:4572`, `:5067`, `:5253`, `:5708`, `:6653`, `:7307`, `:7718`.
- **SR-13: nine consecutive FAILs since its last (conditional) PASS at `:3468`** — `:3907`, `:4273`,
  `:4469`, `:5011`, `:5253`, `:5590`, `:6439`, `:7188`, `:7926`.
- **SR-11: six consecutive FAILs since its last PASS at `:4758`** — `:4890`/`:4937` (a **regression
  from PASS**), `:5253`, `:5440`, `:6549`, `:7094`, `:7818`.

**The journal's own ordinal labels do not agree with those counts** — SR-15's last label is "(8th)"
against ten enumerated events, SR-11's is "(7th)" against six consecutive FAILs — so the ordinals
count something else, and **what they count is UNKNOWN** (§7.4). I have used counted events and said
which lines they are, so the figure can be re-derived or refuted.

**And "twelve rounds" is itself a reconstruction, not a label the journal applies throughout.** The
journal's own round naming runs `# Batch attestation round 1/2/3` (`:3208`, `:3436`, `:3755`), then
`# Third attestation` (`:4469`), `# Fourth attestation` (`:4890`) and `part 2` (`:5011`), then
`# Round 5` (`:5251`) onward. **Every attestation of SR-00…SR-03 and SR-05…SR-08 predates "round 1"
and carries no round label at all.** Where this report writes "round N" it is the journal's label for
the entries from `:5251` on, and an approximation before that.

**The verified count moved repeatedly, and in both directions.** The journal's own tail summary at
`:8321` is *"Count history: 9 → 8 → 11 → 10"*. The full trajectory, read off the journal's own
count-bearing headings, is longer: **9** (`:1472`) → **11** (`:1774`) → **9** (`:2121`) → **10**
(`:2194`) → **9** (`:5251`) → **8** (`:5372`/`:5433`) → **11** (`:6643`) → **10** (`:8241`/`:8312`).
Three of those decreases were *unmarkings of previously attested tasks* — SR-04 in round 5, SR-09 in
round 6, SR-10 in round 11 — and one (11 → 9 at `:2121`) followed SR-12's finding that two tasks were
marked while their dependencies were unverified.

*What would change the conclusions:* a round that produces **no** new finding in SR-10, SR-11, SR-13 or
SR-15. That has not happened yet. Every round from 5 to 12 found at least one real mechanism-vs-prose
gap, which is both the evidence for §4 and the reason no completion claim is available.

### 6.6 What this report did not verify

I did not re-run SR-12's review, did not run any suite, did not execute `scripts/demo.py`, did not
render the dashboard, and did not observe CI. Where the journal's figure could only come from a run, I
report it as UNKNOWN (§7) rather than repeating it. `docs/SR12_INDEPENDENT_REVIEW.md` §8 remains the
only independent capstone review in the tree, and its verdict is **FAIL**.

---

## 7. Figures I could not verify — reported as UNKNOWN rather than repeated

### 7.1 `1351 / 2 / 0` (full suite, 3.12.4) and `1351 / 90 / 0` (bare venv, `--twice`) — UNKNOWN as runs

**The string `1351` does not appear anywhere in `docs/PROGRESS.md`** (`grep -n '1351' docs/PROGRESS.md`
→ no output). The journal's most recent recorded whole-suite figures are at `:6277-6278`, from the
`cb8812b` era on **3.12.4**:

> | bare venv `--expect none --twice`, 3.12.4 | **1252 run, 90 skipped, 0 failed, run1 == run2** |
> | full suite, 3.12.4 | **1252 run, 2 skipped, 0 failed**, both runners |

What I **can** establish: **Σ tests in `scripts/test_baseline.txt` at HEAD = 1351** across **13
modules** (§6.3), and the file is a floor — its header says *"Fewer tests, or (bare mode) fewer skips,
than recorded here fails the run."* A run of 1351 is therefore **consistent** with HEAD and is what a
zero-slack regeneration implies, but **no journal entry attests a run of 1351/2/0 or 1351/90/0.** I
label the totals **UNKNOWN as measurements** and **1351 MEASURED as the baseline floor**. Closing this
needs a suite run, which I did not perform.

### 7.2 The bare skip total: 90 (run) vs 89 (baseline column)

MEASURED: the baseline's bare-skip column sums to **89** at HEAD (`test_failure_modes 2`,
`test_scripts 4`, `test_stability 1`, `test_tensor_ops 82`), and has been 89 since `8469d1c`. The
journal's bare-run total is **90** (`:6277`). These are **not the same quantity**: `scripts/run_tests.sh`
defines `base_excl(reason)` (around `:785-786`) as *"`bool(PYYAML.search(reason)) or
exempt_category(reason) is not None`"* — PyYAML-reason and exempt-category skips are **excluded from
the baseline column by construction**, with the reason stated at the site (*"PyYAML is excluded because
it is the one optional package a developer may have without the others"*).

**INFERENCE, not MEASURED:** the difference of exactly 1 is that single excluded skip. I could not
confirm which skip it is without a run, so the reconciliation is INFERENCE and the identity of the
excluded skip is **UNKNOWN**.

### 7.3 The Linux skip arithmetic, and the "46 variable-key lookups" figure

**Linux skips.** The CI-path run recorded **1252 / 95** (`:6312`, 3.12.10 and 3.13.3) where the local
bare run at the same baseline total recorded **1252 / 90** (`:6277`). The journal settles the Linux
delta by experiment at `:4184-4195`: a case-sensitive repo volume *and* `TMPDIR` give **4** extra
skips (3 in `test_dashboard`, 1 in `test_scripts`), with a table varying one volume at a time. **4 ≠
5.** I cannot account for the fifth skip from the tree, so **the 90 → 95 arithmetic is UNKNOWN by one
skip.** The first Linux run's **1242 / 91** (`:6132`) has the same shape and the same gap.

**"46 variable-key lookups."** `docs/PROGRESS.md:8520` attributes *"**46 variable-key lookups** in the
module (the attester's own count)"*. Re-implementing the tripwire's stated rule reproduces its two
pinned figures exactly (42 literal, 1 f-string) but gives **83** non-string-key sites in
`src/toy/benchmark.py` — a superset, because mine counts every non-string subscript (list and tuple
indexing included), not only mapping lookups. **The selection rule behind 46 is not recorded in a
re-runnable form, so I report 46 as attester-reported and UNREPRODUCED here, and 83 as my own
superset count with its rule stated.** This is the project's own standard applied to its own figure:
*"a measurement whose mutant is not recorded is not reproducible from the tree"* (`:8104`).

### 7.4 Ordinal labels, and a consecutive-failure range the journal does not support

`grep -i consecutive docs/PROGRESS.md` returns **two** hits, neither about attestation counts: `:2786`
(*"four consecutive revisions"*, about SR-09's revisions) and `:3623` (*"three consecutive full runs"*,
about suite runs). **No journal sentence says any task failed 7, 9 or 10 consecutive attestations.**
That framing was handed to this report and is **not supported by the source**; my own counted figures
are in §6.5 — SR-15 **10** (all FAIL), SR-13 **9**, SR-11 **6**.

**The ordinal labels are internally inconsistent in four ways I can point at:**

1. *"SR-13 **FAIL (4th)**"* appears at **both** `:5011` and `:5590`, with an unlabelled SR-13 FAIL at
   `:5253` between them.
2. *"SR-11 **FAIL (6th)**"* appears at **both** `:5440` and `:7094`, with an unlabelled SR-11 FAIL at
   `:6549` between them.
3. **No "(7th)" label exists anywhere for SR-13 or for SR-15** — both jump 6th → 8th. Round 9 contains
   only fix entries (`:7395`, `:7510`, `:7606`) and no attestations, so there is no round-9 attestation
   to be the seventh.
4. SR-15's label series runs *"re-attestation"* (`:4367`) → *"third attestation"* (`:4572`) →
   *"Fourth attestation"* (`:5011`) → *"**FAIL (4th)**"* (`:5708`) → *"**FAIL (8th)**"* (`:7718`).

**Which ordinal series is authoritative is UNKNOWN.** A fifth inconsistency of the same family:
`:5590` records *"SR-10 **PASS** (first time)"* while `:2504` is headed
*"SR-10 — QA verdict PASS at `9d83f8c`"* — **UNKNOWN** whether the earlier PASS was later judged not
to count (it was followed immediately by a FAIL on a post-PASS delta at `:2581`, which would explain
it, but the journal does not say so).

**And the `F<n>` finding-label namespace is overloaded**, by the journal's own admission at `:5416`:
*"**The `F<n>` label namespace is overloaded.** SR-12's required actions are F1–F15; round 5 reused
F1–F5 for unrelated findings (F1 = `MetricValue` value substitution, F2 = `_check_seeds`, …). A mention
count per label is therefore meaningless, and I nearly acted on one."* Round 7 also uses F1–F4 for
SR-11. **So "F1" in this report always carries its task context**, and a bare F-number in any document
of this project should not be resolved without one.

### 7.5 Mutation figures whose mutants are not in the tree

The journal itself flags this class (`:8104`): *"'Mutant T → 14 distinct methods' and 'Mutant G →
exactly 1' — those are mutation measurements and the mutant diffs are not in the tree, so I could not
reproduce them without guessing what T and G were."* The same applies to **M9c**, the unkilled mutant
of §3.1, and to the ~13,500-forged-instance round-8 negative result. These are **recorded
measurements, not reproducible from HEAD**, and this report cites them as the journal's with their
line numbers rather than as its own.

### 7.6 FAIL verdicts with no attestation record, so their content is UNKNOWN

Three FAILs are referred to but never recorded as verdict sections, so what they found cannot be read
from the journal:

- **SR-07's first QA FAIL.** Inferable only from the rework paragraph at `:1236` and from retrospective
  phrases inside the PASS — `:2074` *"The three FAIL defects are closed"* and `:2082` *"the worst
  consequence of the original **D-T3**"*. The three defects are never enumerated; `D-T1` and `D-T2`
  appear nowhere in the file. **Their content is UNKNOWN.**
- **SR-09 r6 and SR-09 r7 FAILs.** Neither has a section. Their existence rests on
  `docs/EVALUATION_PROTOCOL.md:3`'s own ledger and on journal `:2803`, `:3000`, `:3024`.
- A related ambiguity: **whether the r6 FAIL was independent at all.** `:2786` attributes the five r6
  defects to *"The full read **the owner** had skipped for four consecutive revisions"* and `:2789`
  labels three of them *"The orchestrator's three errors"* — owner plus orchestrator, which under
  `CLAUDE.md`'s rule (*"QA must independently attest"*) is a build, not an independent review — yet the
  protocol header counts it as *"reviewed and FAILED"*. **The journal never reconciles this; UNKNOWN.**

A broader instance of the same: the FAILs of SR-02 (second), SR-03 (both), SR-04 (first), SR-05 and
SR-06 exist **only inside "Re-work after QA FAIL" headings**, not as verdict records. The matrix in §2.2
cites those headings as the evidence that a FAIL happened, which is all they can support.

---

## 8. Contradictions found between documents

### 8.1 `docs/EVALUATION_PROTOCOL.md` understates its own review status

`docs/EVALUATION_PROTOCOL.md:3` states, inside a sentence that opens *"Version history, stated
exactly"*:

> **r5 was reviewed and FAILED; r6 was reviewed and FAILED; r7 was reviewed and FAILED (one defect);
> r8 was reviewed and FAILED (three accuracy defects); r9 was reviewed and FAILED (one blocking
> finding, all five criterion clauses passing); **r10 has not been independently reviewed.**

`docs/PROGRESS.md:6362-6364` states the opposite about r10:

> ## SR-09 r10: **PASS**. First PASS for this task since the r3/r4 close-out, and it is earned.
> … Independent round-7 review of `docs/EVALUATION_PROTOCOL.md` at **v1-DRAFT-r10**. **No blocking
> findings.** Four notes, none touching a criterion clause.

**Both citations stand, and the journal explains why the file was not updated** (`:6422-6430`):
*"Editing the document now would make the attested text and the live text differ — which is
**precisely the defect that unmarked SR-09 in the first place** (a PASS covering r3+r4 while the live
text was r9, through four intervening FAILs)."* So the contradiction is **deliberate and reasoned, and
still live**: a reader of `docs/EVALUATION_PROTOCOL.md` alone is told r10 is unreviewed when an
independent PASS of r10 exists. It is a stale status line of the class SR-12 raised as **F3** and
**F11**, created this time on purpose. Resolving it requires a revision plus a re-attestation, which
is exactly the cost the owner declined.

### 8.2 The tree's pinned classification vs the journal's sharpened one

`tests/toy_tests/test_benchmark.py:4816` says **29** is "the number this round is about";
`docs/PROGRESS.md:8531` says **13 escalations** and that *"29 … is not the escalation count. 116 is
not usable."* Full treatment in §3.10. `grep -rn 'escalation' tests/ src/` → no output.

### 8.3 A resolved-but-recorded one: the protocol and the scorer once disagreed on a verdict rule

Recorded for completeness because it is the reason the cross-document check exists.
`docs/SR12_INDEPENDENT_REVIEW.md` **F2** required reconciling `docs/EVALUATION_PROTOCOL.md` (gate 11
scope *"H1 and H2 only"*) with `src/toy/benchmark.py:82-83` (`"control_adequacy": "all"`); the journal
records the fix as amendment **A-1** at `:1871`. I did not re-verify the current reconciliation
beyond reading both records, so its present state is **INFERENCE from the journal**, not MEASURED
here.

### 8.4 A process note, not a document contradiction

My brief stated the working tree was clean. **It was not: `docs/PROGRESS.md` carried an uncommitted
18-line addition before this pass began** (`git diff --stat` → `docs/PROGRESS.md | 18 ++++++`). That
addition is the journal's own SR-04 correction entry quoted in §2.1. I left it untouched, as
instructed, and my closing `git status --porcelain` therefore shows **two** entries rather than one —
reported rather than tidied away, since tidying it would have modified a file this pass was forbidden
to touch.

---

## 9. This document's own liabilities

Applying §4's standard to this file, because a report that states the finding and then violates it is
worth less than no report:

1. **Sentences I can pin.** Every figure in §1.1, §1.3, §2.1, §3.1 (the 42/1 counts), §3.2, §3.9
   (job names), §3.10 (the three git checks), §6.3 and §7.2 was produced by a command reproduced in
   the text. Those are MEASURED and re-runnable.
2. **Sentences I cannot fully pin, and have scoped instead.** §1.3's import enumeration is an
   enumeration of the files at HEAD, **not** a guarantee about `src/toy/` in general; the enforcement
   claim belongs to `scripts/lint.sh` and `tests/toy_tests/test_scripts.py`, whose own task (SR-15) is
   open. §1.4's negative claims rest on reading the tree and on `docs/FORK_AUDIT.md`'s and
   `docs/ERROR_REGISTER.md`'s statements; they are SOURCE OBSERVED, and they are statements about
   **this kit**, never about the fork's behaviour.
3. **Figures I inherited and could not verify** are in §7, labelled UNKNOWN, and are not repeated as
   fact anywhere else in this file. This includes two totals handed to me as the current measured
   state (§7.1).
4. **Residuals I report on the journal's authority, not my own measurement:** mutant **M9c**'s
   unkilled status, the ~13,500-forgery negative result, Findings A and B of §3.1, and every "pre-fix
   vs post-fix" sweep count. Each carries its journal line. Reproducing them needs mutants that are
   not in the tree (§7.5).
5. **The matrix's attestation column is a reading of `docs/PROGRESS.md`, not an independent
   re-attestation.** No task's acceptance criteria were re-tested by this pass. A matrix row saying
   PASS means *the journal records an independent PASS at that line*, nothing more.
6. **The one claim in this file that most deserves suspicion by its own argument** is §3.1's statement
   of what the probe-side gap covers. I have stated it as the attester stated it, with its mutant
   named and its two findings measured — but the *extent* of the probe-side lane rests on a count (46)
   I could not reproduce (§7.3). **Treat the extent as UNKNOWN and the two findings as MEASURED.**
7. **A wider sentence I wrote and then narrowed, recorded because the narrowing is the point.** My
   first draft of §3.10 said three marked tasks rest on attestations whose artifacts moved afterwards.
   Running the checks turned that into: **one does (SR-06), one is documentation-only drift (SR-08),
   one has no drift at all (SR-00).** The wider sentence was true of the journal's *shape* and false of
   the repository. That is this project's own defect class, caught in this document, by the method this
   document recommends.
8. **What is still UNKNOWN after this pass, in one place:** the two current-state suite totals (§7.1);
   the identity of the one skip the baseline column excludes (§7.2); the fifth Linux skip (§7.3); the
   "46 variable-key lookups" figure (§7.3); which ordinal series the journal's FAIL labels belong to
   (§7.4); the contents of three FAIL verdicts that were never recorded (§7.6); and whether SR-06's
   attested bytes are HEAD's (§3.10). None of these is repeated elsewhere in this file as a fact.

**Bottom line.** Ten of seventeen tasks are verified, derived from the blueprint and not inherited.
Three — SR-11, SR-13, SR-15 — have failed repeatedly: **ten recorded attestations for SR-15 with no
PASS at task level, nine consecutive FAILs for SR-13, six for SR-11.** Two more (SR-14, and SR-11 at
its PASS moments) were held unmarked by dependency discipline rather than by a defect of their own.
SR-16 depends on SR-15 and so cannot be marked; SR-17 is correctly blocked and outside the autonomous
loop. **The two methodological findings — that the recurring defect is the sentence describing a
mechanism's reach, and that a generator derived from the invariant beats skilled targeted search — are
this project's most valuable output, and they are better supported than any of its remaining task
claims.** They are also the two results that would transfer to another project unchanged, which the
task count would not.
