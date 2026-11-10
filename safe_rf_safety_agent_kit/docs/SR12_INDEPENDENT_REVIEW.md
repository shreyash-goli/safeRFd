# SR-12 independent review: method fidelity, unknowns and risk of incorrect safety claims

**Reviewer:** `qa` teammate (capstone review). **Date:** 2026-11-09. **Kit HEAD reviewed:** `79be9d48cd0c78a131252026c28e5ed1f7d37dac`. **Working tree:** clean (`git status --short` empty) at the start, between every run, and immediately before this file was written. **Files written by this review:** this file only. No commit, no code edit, no checkbox edit.

Labels: **SOURCE OBSERVED** (read directly from the cited text or produced by a command recorded in section 9), **INFERENCE** (reasoned from observed text, not executed), **UNKNOWN** (not determined). Nothing in this report asserts that the audited method works, fails, is safe, or is unsafe.

---

## 0. Verdict

# FAIL

SR-12 criterion: "method fidelity, unknowns and risk of incorrect safety claims". The verdict is for the kit as a whole, read as a hostile reader would read it. FAIL means "reproducible defects exist that must be fixed before the kit is described as complete". It does not mean the audit documents are wrong about the fork.

| Area | Result | Basis |
|---|---|---|
| 1. Method fidelity (METHOD_AUDIT, ERROR_REGISTER, DIFF_EVIDENCE vs source) | **PASS** | Every spot-checked citation matched; diff arithmetic reproduces; no claim stronger than its evidence found in those three documents. Section 1. |
| 2. Toy-to-source correspondence | **PASS with 3 defects** (F6, F7, F8) | Each deliberate divergence is disclosed in the toy module; no toy result is framed as a finding about the source in any doc. Three places describe the analogy more strongly than the evidence. Section 2. |
| 3. Unknowns register | **PASS with 4 defects** (F1, F5, F9, F10) | Nothing material is marked UNKNOWN that is established. Four items are presented as established that are INFERENCE or UNKNOWN. Section 3. |
| 4. Risk of incorrect safety claims | **FAIL** | Seven ordinary-user paths and several quotable surfaces. Section 4. |
| 5. Cross-document consistency | **FAIL** | One verdict-bearing rule differs between protocol and code (F2); stale status lines (F3, F11). Section 5. |
| 6. PROGRESS / BUILD_BLUEPRINT attestation | **FAIL** | Two `[x]` with unchecked dependencies; one `[x]` whose QA record is indirect; one `[x]` whose attested text was later changed. Section 6. |
| 7. Reproducibility | **PASS** | Commands in section 9, outputs verbatim. |

### Required before this verdict can become PASS

| ID | Required action | Section |
|---|---|---|
| F1 | Correct "silently incompatible" in `src/toy/checkpoint.py:13,45`; upstream source shows a loud failure, and the claim is INFERENCE | 3.2, 4 |
| F2 | Reconcile `docs/EVALUATION_PROTOCOL.md` (gate 11 scope "H1 and H2 only") with `src/toy/benchmark.py:82-83` (`"control_adequacy": "all"`) | 5 |
| F3 | Remove or update "nothing here is QA-attested yet" in `docs/ERROR_REGISTER.md:3,193` | 5, 6 |
| F4 | Make the dashboard scorecard distinguish a scorer-validation oracle result from any other `JointResult` | 4 |
| F5 | Stop describing `.env.example` flags as governing anything; no code reads them | 3.2, 4 |
| F6 | Disclose the sign of the normalization analogy (toy inflates; source net 0.42) | 2 |
| F12 | Resolve `[x]` on SR-11 and SR-14 while SR-10 and SR-13 are unchecked | 6 |
| F13 | Record a QA verdict section for SR-05, or re-attest it | 6 |
| F14 | Re-attest SR-09 against v1-DRAFT-r3 (the checkbox attests r2) | 6 |
| F15 | Make `ClaimLedger.summary()` not emit `is_safety_claim: False` as a literal, or document it as a constant at the field | 4 |

---

## 1. Method fidelity

### 1.1 What was checked, and how

SOURCE OBSERVED. Fork script `erasure_teacher_student.py`: sha256 `1fef6383548419a1175b1732828d04105e384e7f8fc1759d19c7b6207090f17b`, 691 lines (command C1). `fork_only.diff`: sha256 `fe3753f3037905b0b06a3e6eb0e0de6eed876d6e3701197302a85eedb1fb9e86`, 1342 lines, 8 `diff --git` headers (C1, C2). The 691 added lines of the new-file hunk (diff lines 652-1342, `+` stripped) are byte-identical to the script (`cmp` printed `IDENTICAL`, C1). The fork script was **never executed** and no fragment of it was extracted or imported; the only operations on it were `shasum`, `cmp`, `sed -n` and `grep`.

SOURCE OBSERVED. Spot-checked citations (C3, C4). In every case the cited line contains the cited construct:

- Script lines: 36-39 (class defaults), 58-59, 68, 71-72, 84-85, 90, 92-93, 101-102, 122-124, 140-141, 178-179, 193, 199-203, 211, 218, 224-243, 261-262, 265, 279-280, 286-287, 290-297, 302-313, 322-323, 325, 350, 359-364, 373-376, 384, 438-440, 448, 474, 477-479, 586-593, 609-611, 661-663, 677, 683. All matched.
- Diff lines: D:27-45 (`g(t)` under `enable_grad`), D:111-134 (`sample_step` change), D:335-337 (NaN restore), D:449-450 (`# This is OK`), D:522-527 (`th_ang_v` branch), D:633-645 (`seq_idx=None`). All matched.
- Ancestor `e22092420281c644b928e64d490044dfca4f9175` (via `git show`): `diffusion.py:103` (`delta[diffusion_mask, ...] = 0`), `:621` ("True means NOT diffused"); `model_runners.py:282, 335, 426, 428, 465, 533-534, 542-545, 565-566, 603, 613, 646, 662, 676, 682, 706, 721, 742, 777`; `inference/utils.py:360, 447, 501, 508-512`; `util.py:588-589`; `Track_module.py:415-416`; `base.yaml:17, 50, 77, 82, 83, 117`. All matched. `model.load_state_dict(self.ckpt['model_state_dict'], strict=True)` is at `model_runners.py:234`.
- Arithmetic: the METHOD_AUDIT section 3.2 item 3 worked cases (s = 1.15, 1.19, 1.25, -1, 1.5 for u = (3,0,0); ranges [-0.8, 1.1] and [1.3, 3.2]) were recomputed by hand and agree. The 42 = 14 x 3 factor and net 0.42 = 0.01 x 42 agree between METHOD_AUDIT:123-124, ERROR_REGISTER:95 and the `test_failure_modes.py:63-64` fixtures.
- Per-file additions/deletions recomputed from the diff text (C2): 1/1, 13/6, 37/8, 67/56, 33/38, 71/28, 1/1, 691/0; totals **914 / 138**. Matches DIFF_EVIDENCE:34-42, FORK_AUDIT:12-19, SOURCE_SNAPSHOT.json and the dashboard.
- DIFF_EVIDENCE per-commit arithmetic (902/138 + 27/15; 679 + 27 - 15 = 691; 764 + 12 = 776 = 914 - 138) is internally consistent. It was not re-derived from the GitHub API (see 1.4).

### 1.2 Agreement between the three documents

SOURCE OBSERVED. METHOD_AUDIT, ERROR_REGISTER and DIFF_EVIDENCE agree on: the two fork commits, the merge base, the 8 files, the S/D/A citation keys, the classification of each concern, the "no claim the method works/fails/is safe" stance, and the INFERENCE status of the mask-polarity finding (METHOD_AUDIT 3.4 and claim 6; ER-06). ERROR_REGISTER is consistently weaker than or equal to METHOD_AUDIT in every entry: ER-04 and ER-07 retract earlier stronger statements inside the register itself; ER-03 states "no unintended detach identified"; ER-06 says "not a confirmed bug". No entry is stronger than METHOD_AUDIT's evidence.

### 1.3 Method-fidelity findings

| ID | Severity | Finding | Where |
|---|---|---|---|
| M1 | Low | FORK_AUDIT (named in CLAUDE.md as source of truth #1) is not updated to the hedges later added to METHOD_AUDIT. It lists under "What has evidence in source": "Teacher models are frozen" and a target "based on differences between teacher conditioned and unconditioned predictions". METHOD_AUDIT claim 2 labels the freezing "static reading only; not tested", and claim 5 labels the "unconditional" branch **UNKNOWN (INFERENCE against)** because both teachers share one contig and the sampler's internal motif masks. FORK_AUDIT:14 also names the new file's content "Frozen teacher conditional/unconditional outputs". The words are the script's own naming, but FORK_AUDIT does not say so. | `docs/FORK_AUDIT.md:14,22-26` vs `docs/METHOD_AUDIT.md:225,228` |
| M2 | Low | `FORK_AUDIT.md:9` and `README.md:13` give "36" without the time-variance caveat that DIFF_EVIDENCE:27 and the dashboard carry. README says "The present upstream `main` is 36 commits beyond the merge base" under a "2026-11-09" verification date. | `README.md:13`, `docs/FORK_AUDIT.md:9` |
| M3 | Informational | DIFF_EVIDENCE:62 marks "whether the repository contains such material outside the fork-only diff" as UNKNOWN. By construction anything outside the diff is identical to the ancestor, so the question is about upstream, not the fork. Slightly over-hedged; harmless. | `docs/DIFF_EVIDENCE.md:62` |
| M4 | Informational | METHOD_AUDIT section 9 describes the `g(t)` dtype effect as "Previously forced `float32`-less default dtype", which is garbled; the same row's INFERENCE sentence that follows is correct and labelled. No factual consequence. | `docs/METHOD_AUDIT.md:210` |

No fidelity error was found in METHOD_AUDIT's SOURCE OBSERVED claims. The INFERENCE claims were not executed (by design) and remain INFERENCE.

### 1.4 What this review did not verify

UNKNOWN / not re-verified: the live GitHub API state (the 36-commit upstream gap, the fork head still being `5cbd18a`). This review used the saved diff (hash matches DIFF_EVIDENCE:14) and the ancestor object in the local checkout only, and made no network call. Verdicts for the live-API figures rest on SR-01's recorded QA pass.

---

## 2. Toy-to-source correspondence

The toy modules are structural analogues. The table states each correspondence, whether it is described accurately where it is described, and where the description is stronger than the evidence.

| Element | Source (SOURCE OBSERVED) | Toy | Described accurately? |
|---|---|---|---|
| Erasure target algebra | `target = u - eta*(c - u)` (S:286-287) | `erasure_target`: `uv - eta*(cv - uv)` (`teacher_student.py:172-174`); `erasure_demo.toy_target` | **Yes.** Same algebra; applied to affine-map outputs, not diffusion x0 predictions, and the module says "not a model of the audited method's behaviour" (`teacher_student.py:3-5`). |
| Magnitude rescale | **Per-atom** norm over `dim=-1`, **elementwise** clamp [0.1, 2.0] (S:290-297) | **One Frobenius norm** over the whole matrix, one scalar clamp (`teacher_student.py:16-18, 176-182`) | **Divergence disclosed** (`:16-18`). **Not disclosed:** a single positive scalar cannot reproduce the properties METHOD_AUDIT 3.2 derives for the source (direction kept from the origin, sign flip through the origin when k < 0, atom-dependent factors breaking intra-residue geometry, origin dependence). The toy rescale is a uniform dilation. ERROR_REGISTER:173 correctly lists claim 7 as "not catalogued ... no demonstration". No doc claims otherwise. Result: **accurate by omission of any claim**; see F8 for the one docstring that implies more. |
| Loss normalization | Sum over 14 x 3 elements per motif residue, divisor = residue count (factor 42), times constant `0.01` (net 0.42 x element-mean MSE) (S:306-311) | `per_mask_entry`: divisor = masked rows (factor = row width, default 3); no `0.01` | **Partly.** Disclaimer present: "TOY reproduction of an audited numerical concern, not a claim about the real code's impact" (`teacher_student.py:239-241`). **Sign not disclosed:** the toy docstring says the mismatch "inflates the loss, and the gradient" (`:242`). In the source the mismatch is more than cancelled by `0.01`, giving a net **deflation** (0.42 x) relative to an element-mean MSE (METHOD_AUDIT:124, ER-05). See F6. |
| "Correct" normalization | METHOD_AUDIT:131 and ER-05:98 say the choice "may be intentional" / "at most a unit choice" | `per_masked_element` docstring: "The correct element count" (`:238`); commit `d87b48f`: "the audited bug analogue" | **Stronger than the audit.** See F7. |
| Empty mask | Bare `RuntimeError` expression; `loss` unbound; `UnboundLocalError` at S:325 (INFERENCE) | Raises `ValueError`/`EmptyMaskError`; fails closed | **Yes**, and stated: the toy "FAILS CLOSED" (`erasure_demo.py:6`). The source *pattern* is reproduced separately in `failure_modes.py` and labelled PATTERN-DEMONSTRATED. |
| Non-finite handling | `NaN * 0` propagates **if NaN is present**; presence UNKNOWN (ER-02; METHOD_AUDIT 3.2 item 5) | Rejects non-finite in all elements | **Yes**, except `stability.py:27-30`: "a lenient toy would be more permissive than the thing it mimics". See F9. |
| Frozen teacher | `requires_grad=False`, `eval()`, fresh copy per step (S:68-72, 183-193) | Immutable `MappingProxyType` params, frozen dataclass, runtime tripwire | **Different mechanism, not claimed equal.** |
| Student | Full sampler, AdamW, warmup, clip (S:101-127, 373-376) | Per-column affine map, plain gradient descent, analytic gradient, no autograd, no clip | **Yes.** |
| Mask polarity, re-diffusion, dropout/eval mismatch, gradient truncation by `Track_module` detaches | METHOD_AUDIT 3.3, 3.4, claim 17, section 6 | Not modelled | ER-06 is a generic pattern demonstration with "applicability INFERENCE only". Claim 17 and re-diffusion are explicitly "not catalogued here" (`ERROR_REGISTER.md:173`). **Yes.** |
| Checkpoint format | `torch.save` pickle dict, `student_model_state_dict` key (S:458-475) | Canonical JSON, sha256 digest, strict key set | Format contrast is accurate. The description of the *source's* incompatibility is not: see F1. |
| Evaluation design | None exists in the fork (DIFF_EVIDENCE:56-63) | Level A benchmark with oracle/degrader fixtures | **Yes.** EVALUATION_PROTOCOL section 11 states that no toy result transfers "not partly, not suggestively". |

### 2.1 Is any toy result framed as telling us something about the source?

SOURCE OBSERVED, by search (C8, C9). I searched README, docs, module docstrings, tests, scripts and the demo for "mirror", "mimic", "faithful", "analogue", "replicat", "reproduce": no document says a toy outcome predicts, confirms or illustrates the behaviour of the fork's script. The strongest bridging language is:

- `stability.py:29`: "the thing it mimics" (F9).
- `d87b48f` commit message: SR-03 "direct evidence that the fork's commented-out assertions could not have proven parameter-level gradient flow". The ER-04 text itself is more careful ("does not establish that the real student has the severed or zeroed topology"). The commit message is stronger than the register (F10; commit messages are immutable, so this can only be noted).
- Naming: README title "safety-replication agent kit", README purpose "Reproduce and independently audit", BLUEPRINT "Safe computational-method replication", ORCHESTRATOR_PROMPT "toy-method replication", BLUEPRINT definition of done "audit/toy-replication system". The kit does **not** replicate the fork's method or results; it audits it and builds analogues. See quotable item Q9.

### 2.2 Correspondence defects

| ID | Severity | Defect | Where |
|---|---|---|---|
| F6 | Medium | Toy normalization analogy: sign not disclosed (toy inflates by row width; source nets a 0.42 deflation). A reader comparing "factor 3 inflation" in the toy to "factor 42" in the audit would not learn that the source's constant `0.01` reverses the direction. | `src/toy/teacher_student.py:239-243`; `docs/METHOD_AUDIT.md:124`; `docs/ERROR_REGISTER.md:95` |
| F7 | Low | "The correct element count" / "audited bug analogue" are judgements the audit declines to make. | `src/toy/teacher_student.py:238`; commit `d87b48f`; vs `docs/METHOD_AUDIT.md:131`, `docs/ERROR_REGISTER.md:98` |
| F8 | Low | `rescale` docstring "partially counteracts the displacement it is applied to" is true of the toy's single positive scalar only. The source's per-atom map can also flip sign and is origin-dependent (METHOD_AUDIT 3.2). The docstring does not say the toy statement does not carry over. EVALUATION_PROTOCOL H5 already notes the net direction is "not derived". | `src/toy/teacher_student.py:176-181` |

---

## 3. Unknowns register (consolidated)

Built by reading every UNKNOWN / NEEDS-EXECUTION / UNMEASURED / "not verified" statement in the docs and module docstrings (C7). IDs are this review's.

### 3.1 Register

**A. The fork's script and edits (METHOD_AUDIT, FORK_AUDIT, ERROR_REGISTER)**

| ID | Item | Source |
|---|---|---|
| U01 | Runtime behaviour of everything: no code was executed | METHOD_AUDIT:253 |
| U02 | Whether per-step samplers are freed promptly | METHOD_AUDIT:35 |
| U03 | Effective `p_drop` in the checkpoint config (student train mode vs teacher eval mode) | METHOD_AUDIT:40, claim 17 |
| U04 | Config values actually in effect after checkpoint override (`T`, `partial_T`, `fix_motif`, `symmetry`) | METHOD_AUDIT:254 |
| U05 | How often the rescale clamp binds | METHOD_AUDIT:82, claim 8 |
| U06 | Whether `px0` contains NaN at absent-atom slots | METHOD_AUDIT:84, ER-02 |
| U07 | Rationale for the [0.1, 2.0] clamp bounds | METHOD_AUDIT:86 |
| U08 | Whether "unconditional" branch isolates any "concept" | METHOD_AUDIT 3.3, claim 5 |
| U09 | Noise level of the twice-noised `x_t` relative to `t` | METHOD_AUDIT:94 |
| U10 | Author intent for mask polarity and re-diffusion | METHOD_AUDIT:255, claim 6 |
| U11 | Author intent for the "scaffold mask" label | METHOD_AUDIT:144 |
| U12 | Whether gradient reaches student parameters; coverage; magnitude | METHOD_AUDIT claim 14, ER-03/04 |
| U13 | Cause of the author's "gradient is high" note | METHOD_AUDIT claim 10 |
| U14 | Which fork commit introduced the `0.01` constant | METHOD_AUDIT:131 |
| U15 | Value of `M` (contig `1/A80-90` parse) | METHOD_AUDIT:126 |
| U16 | Whether training reduces the loss | METHOD_AUDIT claim 18 |
| U17 | Selective unlearning, utility retention, safety | METHOD_AUDIT claims 19-21 |
| U18 | Source of any behavioural difference vs upstream (confound) | METHOD_AUDIT claim 22, ER-10 |
| U19 | Whether `torch.load` of checkpoints is safe under the fork's PyTorch | METHOD_AUDIT claim 25, ER-08 |
| U20 | Whether the runner switch was a methodological choice; whether it changes outputs materially | METHOD_AUDIT:192, 194 |
| U21 | Size of effect of `util.py` `th_ang_v`/`th_dih_v` semantic change on `alpha_mask` | METHOD_AUDIT:214 |
| U22 | Effect of the unused-looking `seq_idx=None` parameter | METHOD_AUDIT:215 |
| U23 | Whether `gumbel_softmax_sample` has a call site elsewhere in the ancestor tree | METHOD_AUDIT:211 |
| U24 | Whether `xyz_t` in `_preprocess` is the same tensor as the grad-requiring `x_t` | METHOD_AUDIT:167 |
| U25 | Results of the fork's own `requires_grad` prints | METHOD_AUDIT:165 |
| U26 | Whether the `main()` example is sensitive in any way | METHOD_AUDIT claim 26 |
| U27 | Whether an empty mask is ever reached | ER-01 |
| U28 | Whether clipping engages at `max_grad_norm=10` | ER-07 |
| U29 | CUDA behaviour; GPU SVD/Kabsch behaviour | ER-09 |
| U30 | In-place hazards in the real graph | ER-11 |

**B. Source provenance (DIFF_EVIDENCE, SOURCE_SNAPSHOT)**

| ID | Item | Source |
|---|---|---|
| U31 | The 36-commit gap is time-varying | DIFF_EVIDENCE:27 |
| U32 | Whether fork `main` stays at `5cbd18a` | DIFF_EVIDENCE:99 |
| U33 | Unauthenticated API responses; later force-push | DIFF_EVIDENCE:98 |
| U34 | Whether the script's loss plot counts as an "evaluation" | DIFF_EVIDENCE:62 |

**C. Evaluation methodology (EVALUATION_PROTOCOL, benchmark.py, dashboard)**

| ID | Item | Source |
|---|---|---|
| U35 | Deferred checks D1-D6 (config-shift arm, ER cross-check, V-set probes, pilot and `n_cap` rule, exchangeability, amendment-log hash) | `EVALUATION_PROTOCOL.md:251-258`; `benchmark.py:79-81` |
| U36 | Whether the seed list was frozen before data (producer-asserted only) | `benchmark.py:980`; protocol:243 |
| U37 | "Chosen a priori, not tuned" for six thresholds (no tuning log; unverifiable) | `EVALUATION_PROTOCOL.md:266` |
| U38 | Whether `steps_conv = 1000` reaches `tau_conv` | `EVALUATION_PROTOCOL.md:270` |
| U39 | Pilot SDs and `n_planned` | `EVALUATION_PROTOCOL.md:150` |
| U40 | Amendment log (empty) | `EVALUATION_PROTOCOL.md:390` |
| U41 | Coverage of bootstrap and t-intervals at n = 30 for skewed data | `EVALUATION_PROTOCOL.md:163` |
| U42 | Whether any threshold is appropriate for a real system | protocol section 11 |
| U43 | All results slots in the protocol (every cell UNKNOWN) | protocol:10, 319-328 |

**D. Tooling, CI and environment (CLEAN_CLONE, PROGRESS, module docstrings)**

| ID | Item | Source |
|---|---|---|
| U44 | The CI workflow has never been executed; the numpy 1.26.4 + torch 2.7.1 pin combination has not been exercised locally; actions are pinned by tag, not SHA | PROGRESS SR-15 entry; `constraints.txt` comments |
| U45 | Skip count on Linux CPU ("roughly 2-8"): an estimate, not observed | `CLEAN_CLONE.md:35` |
| U46 | Behaviour on Python < 3.12 (`mse_naive` order invariance) | `CLEAN_CLONE.md:5`; `robustness.py` docstring |
| U47 | Ledger reviewer identity is unauthenticated; evidence refs are shape-checked only; tail truncation with a corrected `head_digest` accepted | `claim_ledger.py` docstring |
| U48 | Checkpoint digest is not a signature; whole-file rewrite accepted | `checkpoint.py` docstring |
| U49 | The CPU-vs-MPS "around 1e-7" figure is a point-in-time measurement no test pins | PROGRESS SR-03 QA entry (line 1421 onward) |

### 3.2 Is anything marked UNKNOWN that is actually established?

INFERENCE. No material case. Two harmless over-hedges: M3 above (U34's sibling), and U19, which is correctly UNKNOWN for the fork's own environment (not recorded anywhere) although the kit's pinned torch is known (`weights_only` in the installed 2.7.1 signature shows `Optional[bool] = None`, C10; the resolved default depends on release notes and was not tested here, so it is left UNKNOWN).

### 3.3 Is anything presented as established that is actually INFERENCE or UNKNOWN?

This is the high-value half. Four items, in descending seriousness:

| ID | Severity | Statement presented as fact | Why it is not established | Where |
|---|---|---|---|---|
| **F1** | **Medium-High** | "those checkpoints are **silently** incompatible with the unmodified sampler" and "the audited **silent** key incompatibility" | SOURCE OBSERVED: upstream reads `self.ckpt['model_state_dict']` then `load_state_dict(..., strict=True)` (ancestor `model_runners.py:234`). Reading a missing key from a dict raises `KeyError`, which is loud, not silent. The incompatibility itself is INFERENCE (not executed); METHOD_AUDIT claim 24 and section 7 say only "not directly loadable ... an adapter is needed" and never use "silent". The toy module contradicts the audit and the source it cites, and attaches the word to the audited script. Commit `e436d93` (and `PROGRESS.md`) repeat the milder "not loadable". | `src/toy/checkpoint.py:13, 45` vs `docs/METHOD_AUDIT.md:179, 247` |
| **F5** | **Medium** | `.env.example` flags `MODEL_WEIGHTS_ENABLED=false`, `BIOLOGICAL_TRAINING_ENABLED=false`, `RUN_MODE=TOY_OFFLINE`, `TOY_SEED=42`; CLEAN_CLONE says "These flags govern the **toy application**" | SOURCE OBSERVED (C6): no file under `src/`, `scripts/` or `tests/` reads any of these variables (`ALLOW_EXTERNAL_NETWORK` is exported by `run_tests.sh:48` and `ci.yml:14` but also never read). They are inert. A reader can present "BIOLOGICAL_TRAINING_ENABLED=false" as a safety control. The actual protections are structural (no weights, no network imports, a socket guard in tests). | `.env.example:2-5`; `docs/CLEAN_CLONE.md:74-77`; `README.md:28` |
| **F9** | Low | "the audited source multiplies by the mask, and NaN * 0 stays NaN in torch, so a lenient toy would be more permissive than the thing it mimics" | The multiply is SOURCE OBSERVED and `NaN*0` is IEEE. The presence of NaN in the source tensors is UNKNOWN (ER-02; METHOD_AUDIT 3.2 item 5 infers placeholders are probably finite). "More permissive than the thing it mimics" treats a conditional hazard as a property of the source. | `src/toy/stability.py:27-30`; commit `d87b48f` ("more lenient than the source it mimics") |
| **F10** | Low | Commit `d87b48f`: "direct evidence that the fork's commented-out assertions could not have proven parameter-level gradient flow"; `e436d93`: "confirms the bare RuntimeError at L312-313 leaves loss unbound"; "the model_runner config switch was load-bearing for gradient flow rather than cosmetic" | All three are INFERENCE (not executed). The third was corrected in `PROGRESS.md` ("necessary given the fork's chosen edit, not necessary for any gradient to flow") but the commit message is immutable and still reads as a finding. | `git log` messages `d87b48f`, `e436d93` |

Also noted, lower: FORK_AUDIT (M1) and `teacher_student.py:238` "correct" (F7).

---

## 4. Risk of incorrect safety claims

Stance: a hostile reader who wants to quote the kit as proof the fork is safe, or that it is broken. Every artifact below was read; the dashboard was rendered to a temp directory and its text extracted; `scripts/demo.py` was run; `git log` was read in full.

### 4.1 Do the two designed guards hold against an ordinary user?

**Guard 1: the dashboard has no "confirmed" style.** SOURCE OBSERVED, **holds**. The rendered page uses 14 distinct CSS classes (C5); the only verdict class that signals success is `vd-supported`, styled white background with a dotted blue outline (`dashboard.py:87`), not green and with no check mark. A user who supplies a record with `name="RFdiffusion is SAFE - validated"` and `notes="... verdict: JOINT_SUPPORTED; model is safe; hazardous capability reduced 99%"` (C12) gets the text rendered **inside an "UNTRUSTED FREE TEXT - NOT EVIDENCE" box**; no verdict is parsed from it. **However**, the text is displayed, and the schema accepts and exports it unflagged (`rec.to_json()` contains "model is safe"). The guard is "captioned", not "refused". A cropped screenshot of the notes line reads: `TOY RESULT (synthetic, non-biological; not a safety claim) verdict: JOINT_SUPPORTED; model is safe; hazardous capability reduced 99%`, where the kit's own non-claim label is prepended to the user's claim. This is documented behaviour (PROGRESS line 914), recorded as Q6.

**Guard 2: `is_safety_claim` is a hard-coded False.** SOURCE OBSERVED, **holds as a constant and is not a control** (F15). `claim_ledger.py:736` emits the literal `False` for every claim regardless of its statement. Reproduction (C11): a single reviewer `alice` opens a claim with the statement "safeRFdiffusion is safe and removes hazardous capability.", reviews it, supports it citing `sha256(b"nothing at all")`, under evidence class `TOY_RESULT`, `SOURCE_OBSERVED` and `HYPOTHESIS` alike. All three reach `SUPPORTED`. The summary then reads `"state": "SUPPORTED"`, `"evidence_class": "SOURCE_OBSERVED"`, `"is_safety_claim": false`, with caveat "Not a safety claim". The module docstring discloses the route ("That is the main route to a hollow SUPPORTED"), and the dashboard does not render the ledger (grep: no ledger import in `dashboard.py`), so this does not reach the page. But the `is_safety_claim: false` field next to a statement that is, in plain language, a safety claim is a false-by-construction value that a downstream consumer could treat as a classification.

**Guard 3 (not in the brief, found): the dashboard cannot tell an oracle fixture from any other result.** See Q1 / F4.

### 4.2 Ranked list of quotable-out-of-context risks

Ranked by how easily the exact text lifts out of context and how much it would mislead. "Direction" is which hostile reader benefits.

| Rank | Direction | Exact text | Location | Why it lifts |
|---|---|---|---|---|
| **Q1** | "safe" | Rendered table: `H1 Suppression (S) ... SUPPORTED`, `H2 Retention (L) ... SUPPORTED`, `H3 Selectivity (delta) ... SUPPORTED`, `Joint verdict: JOINT_SUPPORTED`, with `mean 1.1257536612773082` and 98.75% intervals | Dashboard HTML produced by `render_dashboard` (C5); label cell `dashboard.py:366-369` | The only qualifier is a 12 px grey span: `(toy fixture; conditional; not a safety finding)`. The page says "toy fixture", not "scorer-validation oracle whose answer is known by construction" (`benchmark.py` docstring: "a JOINT_SUPPORTED verdict on a scorer-validation fixture means only 'the scorer can say yes when the answer is yes by construction'"). `JointResult` (`benchmark.py:1036-1047`) has **no field recording fixture kind**, so the renderer cannot distinguish an oracle from a trained-student outcome; the same label would appear on both. The row names are "Suppression", "Retention", "Selectivity". The protocol says the actual affine toy is **expected to fail H3** (protocol:86), yet the page shows H3 SUPPORTED, on the oracle. |
| **Q2** | "safe" | `[3] scorer-validation fixture (ORACLE_GATED) scored on 30 seeds: verdict JOINT_SUPPORTED  [tests the scorer; says nothing about any method]` | `scripts/demo.py:116-117`, printed by `python3 scripts/demo.py` (C4) | The bracket is good, but the demo omits the mandated "(conditional on deferred checks: <list>)". Protocol:124 and :258 say "no JOINT_SUPPORTED may be described without the 'conditional' qualifier". The demo line and `CLEAN_CLONE.md:66` lack it. Followed by `DEMO OK ... All checks passed.` |
| **Q3** | "safe" | `INVARIANCE_HOLDS`, `status=INVARIANCE_HOLDS` | demo `[4]`; dashboard notes; `robustness.py:107` | The enum's own comment says "not refuted on these seeds"; the docstring says passes are "not refuted on these n synthetic fixtures". The name reads as "holds". |
| **Q4** | "safe" | `.env.example`: `MODEL_WEIGHTS_ENABLED=false`, `BIOLOGICAL_TRAINING_ENABLED=false` | `.env.example:3-4` | Reads as a safety interlock (F5). Inert. |
| **Q5** | "safe" | `SUPPORTED (human review verdict, conditional on the referenced evidence)`; `"is_safety_claim": false` | `claim_ledger.py:248, 736`; commit `12bc490`: "SUPPORTED structurally unreachable without evidence references" | Evidence is shape-checked only. A hollow SUPPORTED is one hash away (C11). The commit sentence omits "shape". |
| **Q6** | "safe" | `TOY RESULT (synthetic, non-biological; not a safety claim) verdict: JOINT_SUPPORTED; model is safe ...` | produced by any user note field (C12); accepted by schema (PROGRESS:914) | Own label prepended to the user's claim, inside a box that says UNTRUSTED. |
| **Q7** | "safe" | `The default fixture still reaches a **genuine** JOINT_SUPPORTED` | `docs/PROGRESS.md:1384` | "genuine" refers to a non-false-alarm in the renderer test. Out of context it reads as a genuine joint support. |
| **Q8** | "broken" | `INFERENCE ... the conditional branch holds scaffold residues fixed and noises the motif residues ... This is contrary to the script's own comments`; "appears inverted" | `docs/METHOD_AUDIT.md:102, 229` | Labelled INFERENCE with "Not verified by execution" in the same paragraph, and "intent is UNKNOWN". The strongest sentence in the kit about the fork. |
| **Q9** | "broken" | ER summary: `ER-08 ... Medium-High on untrusted files` | `docs/ERROR_REGISTER.md:34` | The table row has no reach note; the entry (`:125`) says the fork's `load_checkpoint` has **no call site** and the pattern "is not fork-specific". The QA record notes ER-08 is "the only entry above Medium yet its own reach note says the fork's load path is unexercised". |
| **Q10** | both | Titles and purpose: `SafeRFdiffusion safety-replication agent kit`; "Reproduce and independently audit the safety research methods and claims"; "toy-method replication"; completion promise `SAFETY_AUDIT_KIT_COMPLETE` | `README.md:1,3`; `docs/ORCHESTRATOR_PROMPT.md:1,9`; `docs/RALPH_COMMAND.txt` | "Replication" and "Reproduce" suggest results were reproduced. None were. The promise token, if emitted, reads as an all-clear for the kit. Today `docs/PROGRESS.md:1774-1777` records "Verified: 11 of 17". |
| **Q11** | "broken" | `ER-04: input-leaf requires_grad does not prove parameter-level gradient (most important)`; commit `d87b48f` "direct evidence that the fork's commented-out assertions could not have proven ..." | `docs/ERROR_REGISTER.md:73`; git log | The register is carefully hedged; the heading plus "most important" is a short quotable. |
| **Q12** | both | `A training run is not evidence of selective unlearning or safety.` | dashboard notes; `CLAUDE.md` | A non-claim, quoted safely. Listed because it is the model sentence the others should resemble. |
| **Q13** | "safe" | CI/clean-clone: "Read-only permissions, no secrets, no publishing"; `core-no-deps ... clean-clone proof` | `docs/CLEAN_CLONE.md:83-84`; PROGRESS SR-15 entry | The workflow **has never been executed** (builder's own note, PROGRESS). `CLEAN_CLONE.md` "What CI does" and README do not say so. |
| **Q14** | "safe" | `control_adequacy PASS ... A, F ok; E-loss check exempt (declared scorer-validation fixture)` | dashboard gate table (C5) | PASS beside a skipped sub-check; the exemption reason appears, but only here. |

### 4.3 Risk findings

| ID | Severity | Finding |
|---|---|---|
| **F4** | **High** | Q1 as above. `JointResult` has no fixture-kind field and the dashboard verdict cell uses a single fixed qualifier. The distinction the benchmark docstring insists on is dropped at the rendering layer. Note: `to_experiment_records(scorer_validation=...)` does carry a kind string (`benchmark.py:1159-1160`), but the dashboard renders from `JointResult`, not from those records. Teammates are reworking `dashboard.py`/`benchmark.py`; this finding is against HEAD `79be9d4`. |
| F5 | Medium | `.env.example` flags are inert (section 3.3). |
| F15 | Medium | `is_safety_claim` literal False (section 4.1). |
| F16 | Low | Demo line `[3]` and `CLEAN_CLONE.md:66` omit the protocol-mandated "conditional on deferred checks" (Q2). |
| F17 | Low | CI workflow unexecuted but not disclosed in README or CLEAN_CLONE (Q13). |

---

## 5. Cross-document consistency

Every figure that appears in more than one place was checked. "OK" means all locations agree and agree with the recomputed value.

| Figure | Locations | Result |
|---|---|---|
| 8 changed files; +914 / -138 | `README.md:12` (8 files); `FORK_AUDIT.md:12-19` (rows sum to 914/138; totals not stated); `DIFF_EVIDENCE.md:34-42`; `SOURCE_SNAPSHOT.json`; `PROGRESS.md` SR-00 entry; dashboard (computed); recomputed from diff (C2) | **OK** |
| 691-line new file | `README.md:12`; `FORK_AUDIT.md:12`; `ERROR_REGISTER.md:10`; `METHOD_AUDIT.md:9`; diff and `wc -l` | **OK** |
| Fork commits `12d5426...`, `5cbd18a...` | README:10; FORK_AUDIT:8,50-51; DIFF_EVIDENCE; METHOD_AUDIT; SOURCE_SNAPSHOT (C13: one distinct value each, no variants) | **OK** |
| Merge base `e220924...` | README, FORK_AUDIT, DIFF_EVIDENCE, METHOD_AUDIT, SOURCE_SNAPSHOT, CLAUDE.md | **OK** |
| `behind_by_vs_merge_base: 0` vs `behind_by_vs_upstream_main: 36` | `SOURCE_SNAPSHOT.json` (both keys + note); `DIFF_EVIDENCE.md:23-27,74,87`; dashboard rows (`dashboard.py:241-243`); `README.md:13` and `FORK_AUDIT.md:9` ("36") | **OK** on values. Caveat M2: README/FORK_AUDIT omit the time-variance note. DIFF_EVIDENCE:86 still describes the pre-relabel key, retained "for the audit trail" and explained at :87. |
| Factor 42; net 0.42 | `METHOD_AUDIT.md:123-124,233`; `ERROR_REGISTER.md:95,97`; `test_failure_modes.py:63-64,72` | **OK** |
| m = 4; 98.75% | `benchmark.py:25,78,198`; `EVALUATION_PROTOCOL.md:106,128,159,175`; dashboard prints `0.9875`; `bonferroni_level()` | **OK** |
| Six deferred gates | `benchmark.py:79-81` (6 names); `EVALUATION_PROTOCOL.md:251-258` (D1-D6); dashboard ("6 unimplemented gate(s)", lists 6); `benchmark.py` docstring lines 50-55 | **OK** |
| ER severity table vs entry headings | `ERROR_REGISTER.md:27-37` vs each entry; pinned by `test_register_structure`; PROGRESS SR-03 QA entry lists the same eleven | **OK**. (No written rubric for what each level means, per the SR-03 QA record.) |
| Skip counts | Measured (C14): nothing installed **86**; PyYAML only **85**; torch blocked, numpy+PyYAML present **84**; torch+numpy+PyYAML+pytest **2**. `CLEAN_CLONE.md:32-35` (86/85/2); `PROGRESS.md` SR-15 entry (85, "84 with numpy present", 86 bare); commit `79be9d4` ("85") | **OK**, with the note that "85" is the count only for the torch-and-numpy-absent, PyYAML-present environment. CI job `core-no-deps` asserts PyYAML absent, so its expected count is 86. |
| Test totals | `CLEAN_CLONE.md:28,32-34`: "673 run", pytest "671 passed"; `PROGRESS.md`/`79be9d4`: 739 / 737; measured (C14, C15): **739 ran, pytest 737 passed** | **DISAGREE** (F11): CLEAN_CLONE's table still says 673 / 671. The heading hedges ("later work adds more") but the table rows are stale by 66. |
| ER-03 status | `ERROR_REGISTER.md:3,193`: "draft pending independent QA ... nothing here is QA-attested yet", "this file is not marked QA-attested"; `BUILD_BLUEPRINT.md:11` `[x] SR-03`; `PROGRESS.md:1421-1471` QA PASS (third pass) | **DISAGREE** (F3). The register says the opposite of the journal and the checkbox. |
| Gate 11 (control adequacy) scope | `EVALUATION_PROTOCOL.md:122` ("gate 11 for H1/H2"), `:139` ("the implementation scopes it to H1/H2 only ... a decision to extend gate 11 to H3 ... is a protocol amendment"), `:240` ("**H1 and H2 only** ... H3 is still evaluated"); vs `benchmark.py:82-83` (`"control_adequacy": "all"`), `benchmark.py` docstring ("a failure makes H1, H2, H3 and JOINT INCONCLUSIVE"), commit `ff451e1`, `PROGRESS.md:1281-1290`, dashboard (reads `GATE_SCOPES`) | **DISAGREE** (F2). |
| Protocol amendment log | `EVALUATION_PROTOCOL.md:390`: "none recorded"; the decision above is exactly what `:139` says "is a protocol amendment" | **Process gap** (F2). |
| Dependency order | `BUILD_BLUEPRINT.md` Depends vs `[x]` | **DISAGREE** (F12), section 6. |
| Journal runtime figures | `PROGRESS.md:1689-1699`: `test_benchmark` 49.6 s, `test_scripts` 13.7 s, `test_claim_ledger` 0.81 s | Attribution order reproduces (C15: 13.3 s, 3.6 s, 0.15 s on this host, `test_benchmark` dominant). Absolute numbers are load-dependent; the journal gives no load context. Informational. |

### 5.1 Consistency findings

| ID | Severity | Finding |
|---|---|---|
| **F2** | **High** | The pre-registration document and the scorer disagree on which hypotheses a failed control-adequacy gate blocks. Under the protocol text, a failed gate 11 permits an H3 verdict to be reported (JOINT cannot be SUPPORTED). Under the code, H1, H2, H3 and JOINT all become INCONCLUSIVE. The decision was made in commit `ff451e1` and logged in PROGRESS, but `EVALUATION_PROTOCOL.md` was not touched by that commit (git log for the file: `12bc490 710151f d87b48f`). Protocol:124 itself requires "the document and the code are required to tell the same story". A reader following the protocol would mis-predict the scorer's behaviour. |
| F3 | Medium | ERROR_REGISTER self-description contradicts its QA status. A hostile reader can cite either direction ("the register says it is unreviewed"; "nothing here is QA-attested"). |
| F11 | Low | CLEAN_CLONE test totals stale (673 vs 739). |

---

## 6. `docs/PROGRESS.md` honesty audit and `BUILD_BLUEPRINT.md` attestation audit

### 6.1 Checkbox audit

Produced by the script in C16 (dependency check) plus a manual read of every QA section.

| Task | `[x]` | Depends | Unchecked dependencies | QA-PASS record in PROGRESS | Notes |
|---|---|---|---|---|---|
| SR-00 | x | none | none | Yes: `PROGRESS.md:27-64` ("Status: PASS", QA hand re-derivation, defects D1-D3) | OK |
| SR-01 | x | SR-00 | none | Yes: `:145-162` | OK |
| SR-02 | x | SR-01 | none | Yes: `:1392-1420` (third pass; QA confirms `git diff 12bc490 HEAD` empty) | OK |
| SR-03 | x | SR-02 | none | Yes: `:1421-1471` (third pass) | OK for the cited content. Register's own header contradicts (F3). Two orchestrator nits were fixed after QA with QA's agreement. |
| SR-04 | x | SR-00 | none | Yes: `:316-352` (92 mutants) | OK |
| **SR-05** | x | SR-04 | none | **Indirect only.** There is **no** "SR-05 - QA verdict" section. The evidence of a PASS is the heading `## SR-05 - Residual defects closed (after QA PASS)` (`:831`), commit `710151f` ("SR-05: QA PASS; six residual defects then closed"), and the summary list at `:1472`. The only QA-derived detail is the orchestrator correction at `:685-708` (QA's re-review "partly refuted" the equivalent-mutant argument). No commands, mutant counts or test log by QA are recorded. | **F13.** CLAUDE.md requires "task ID, evidence, commands, results". The six residual fixes (D1 changes `train()` behaviour) were made after the PASS and are recorded as closed by the builder, with no QA re-check recorded. `teacher_student.py` has no commit after `710151f`, so the committed bytes are the post-fix bytes. |
| SR-06 | x | SR-05 | none | Yes: `:1004-1022` | OK |
| SR-07 | | SR-05 | | n/a (QA in progress per `:1777`) | Correctly unchecked. **But** ER-09 and ER-11 (inside the `[x]` SR-03 deliverable) rely on SR-07 results ("SR-07 reports max relative difference around 1e-7"; "To settle: SR-07's non-in-place numeric ops ..."). The 1e-7 figure was re-measured by SR-03's QA (`:1421-1471`), so the number stands; the SR-07 *module* is still unattested. |
| SR-08 | x | SR-05 | none | Yes: `:1026-1053` | OK |
| **SR-09** | x | SR-02, SR-04 | none | Yes: `:1057-1085`, **of v1-DRAFT-r2** | **F14.** `EVALUATION_PROTOCOL.md` was subsequently amended to **r3** in commit `12bc490` (new sections 8.1-8.3 and 4.1 items 5-7, six registered thresholds, block-only converged-budget rule, gate 11(c) exemption). No QA review of r3 is recorded (`grep r3 docs/PROGRESS.md` returns only the amendment entry). The checkbox attests a text that no longer exists. The r3 text also contains the F2 contradiction. |
| SR-10 | | SR-06, SR-09 | | n/a (QA in progress) | Correctly unchecked. |
| **SR-11** | x | **SR-10** | **SR-10 (unchecked)** | Yes: `:1580-1609` | **F12.** `[x]` on a task whose declared dependency is unverified. |
| SR-12 | | SR-03, SR-11 | none | this review | Eligible. |
| SR-13 | | SR-08, SR-10 | SR-10 | n/a (second FAIL fixed, third review pending) | Built while a dependency was unverified; unchecked. |
| **SR-14** | x | **SR-13** | **SR-13 (unchecked)** | Yes: `:1655-1688`, `:1765-1773` | **F12.** `[x]` on a task whose declared dependency is unverified. |
| SR-15 | | SR-12, SR-14 | SR-12 | n/a (built, pending QA) | Built before SR-12 existed. Correctly unchecked. |
| SR-16, SR-17 | | | | n/a | OK |

SOURCE OBSERVED: **nothing is marked `[x]` on a build alone.** Every one of the eleven `[x]` has a QA PASS stated in the journal, except SR-05 where the attestation is indirect as described. CLAUDE.md's "Complete only eligible tasks whose dependencies pass" is violated by SR-11 and SR-14. `PROGRESS.md:1774` ("Verified: 11 of 17") counts all eleven.

### 6.2 Are the journal's recorded self-corrections accurate?

| Correction | Where | Check | Result |
|---|---|---|---|
| SR-05 "equivalent mutant" adjudication was too quick | `PROGRESS.md:685-708` | `train()` now type-checks `teacher` and compares `before`/`after` (`teacher_student.py`, `if after != before ...`) | **Accurate.** |
| BSD `sed \b` rename produced 43 test errors | `:925-943` | Plausible and benign; not reproducible from the tree now. | Not re-verified; no conflict found. |
| Torch-absent skip count is 85, not ~54 | `:1701-1730`, commit `79be9d4` | C14 | **Accurate**, with the environment-dependence in section 5. |
| Suite slowdown was `test_benchmark`, not SR-14's `verify_chain` | `:1689-1699` | C15 | **Attribution accurate**; absolute seconds differ by host load. |
| Stale `.pyc` caused spurious baselines (third occurrence) | commit `9b2d928` | The standing rule is implemented (`run_tests.sh`, `CLEAN_CLONE.md:24-26`). This review followed it (C14: `__pycache__` cleared, `PYTHONDONTWRITEBYTECODE=1`, none left). | Consistent; the original contamination is not re-creatable now. |
| Citation fix claimed "applied everywhere" was not | `:1421-1471`, commit `96b5ac2` | `grep -rn "D:213-342" docs src tests` outside PROGRESS.md returns nothing (the only hit is this report quoting it). | **Accurate and since fixed.** |
| "radial component" claim removed everywhere | `:1392-1420` | `grep -rn "removes any purely radial" docs src tests` returns only journal history lines | **Accurate.** |
| Orchestrator attribution of baseline moves to concurrent edits was wrong | commit `9b2d928` | Not independently testable. | Not re-verified. |

### 6.3 Does the journal overstate what was verified?

SOURCE OBSERVED. It generally does not; it records its own limits (CI unexecuted, thresholds untuned, SR-15 pending). Three overstatements or omissions:

1. **SR-05** has no QA verdict section (F13).
2. **SR-09's** PASS is r2; the journal's list of "verified" tasks gives no r3 qualifier (F14).
3. **SR-11/SR-14 `[x]`** are listed in "Verified: 11 of 17" without noting that their dependencies are unverified (F12).

---

## 7. Findings index

| ID | Severity | One line | Section |
|---|---|---|---|
| F1 | Medium-High | `checkpoint.py:13,45` says the key mismatch is "silent"; the cited upstream source raises `KeyError`; the incompatibility is INFERENCE | 3.3 |
| F2 | High | Protocol says gate 11 scopes to H1/H2; the scorer scopes it to all; no amendment recorded | 5.1 |
| F3 | Medium | ERROR_REGISTER says "nothing here is QA-attested yet"; SR-03 is `[x]` with a third-pass PASS | 5.1 |
| F4 | High | Dashboard shows "Suppression ... SUPPORTED / JOINT_SUPPORTED" with only a small "toy fixture" qualifier, and cannot tell an oracle result from any other | 4.3 |
| F5 | Medium | `.env.example` flags are read by no code; CLEAN_CLONE says they "govern" the app | 3.3 |
| F6 | Medium | Toy normalization "inflates"; source nets a 0.42 deflation; not disclosed | 2.2 |
| F7 | Low | "correct element count" / "audited bug analogue" vs audit's "may be intentional" | 2.2 |
| F8 | Low | Toy rescale docstring does not say its single-scalar property does not carry over | 2.2 |
| F9 | Low | `stability.py:29` "the thing it mimics" treats a conditional NaN hazard as a property of the source | 3.3 |
| F10 | Low | Commit messages state INFERENCE as "confirms" / "direct evidence" / "load-bearing" | 3.3 |
| F11 | Low | CLEAN_CLONE test totals 673/671 vs 739/737 | 5.1 |
| F12 | High (process) | SR-11 `[x]` with SR-10 unchecked; SR-14 `[x]` with SR-13 unchecked | 6.1 |
| F13 | Medium (process) | SR-05 `[x]` with no QA verdict section; residual fixes un-re-attested | 6.1 |
| F14 | Medium (process) | SR-09 `[x]` attests r2; live protocol is r3 | 6.1 |
| F15 | Medium | `is_safety_claim` is a literal; a single reviewer can reach SUPPORTED on a safety-claim statement with a hollow hash | 4.1 |
| F16 | Low | Demo `[3]` omits the protocol-mandated "conditional" qualifier | 4.3 |
| F17 | Low | CI workflow unexecuted; not disclosed in README/CLEAN_CLONE | 4.3 |
| M1-M4 | Low/Info | FORK_AUDIT not updated to METHOD_AUDIT hedges; README "36" without time caveat; two minor over-hedge/garble items | 1.3 |

---

## 8. Limits of this review

- UNKNOWN: any runtime behaviour of the fork. Not executed; INFERENCE claims stay INFERENCE.
- Live GitHub state was not queried (no network). SR-01's recorded pass stands for those figures.
- The CI workflow was not run (no remote). The Linux CPU skip count was not observed.
- Teammates are concurrently reworking `src/toy/dashboard.py`, `src/toy/benchmark.py` and their tests. **The suite did not move under this review**: HEAD stayed `79be9d48cd0c78a131252026c28e5ed1f7d37dac`, `git status --short` stayed empty, and every run reported 739 tests. Findings F2, F4, F16 are against that HEAD and may be fixed by in-flight work; re-run section 9 after any change.
- Hostile-reader coverage is bounded by what I thought to try. Circumvention probes covered the ledger and record free-text paths, not the checkpoint, schema or robustness APIs.
- I wrote scratch scripts under the session scratchpad only (`.../scratchpad/qa15/`); nothing in the repository was edited by this review.

---

## 9. Reproducible commands and recorded output

Set once. `$KIT` is the repository root; `$SRC` is the saved fork material (script and diff only; **do not execute the script**).

```sh
KIT=/Users/shrey/Projects/safeRFd/safe_rf_safety_agent_kit
SRC=/private/tmp/claude-501/-Users-shrey-Projects-safeRFd/4a75912c-f714-454a-b257-94c88ac513f7/scratchpad/fork_source
ANC=e22092420281c644b928e64d490044dfca4f9175
S=/private/tmp/claude-501/-Users-shrey-Projects-safeRFd/4a75912c-f714-454a-b257-94c88ac513f7/scratchpad/qa15
cd $KIT && git rev-parse HEAD && git status --short
```

Output: `79be9d48cd0c78a131252026c28e5ed1f7d37dac`, then nothing (clean).

### C1. Script and diff identity (no execution)

```sh
shasum -a 256 $SRC/erasure_teacher_student.py $SRC/fork_only.diff
wc -l $SRC/erasure_teacher_student.py $SRC/fork_only.diff
sed -n '652,1342p' $SRC/fork_only.diff | sed 's/^+//' | cmp - $SRC/erasure_teacher_student.py && echo IDENTICAL
```

```
1fef6383548419a1175b1732828d04105e384e7f8fc1759d19c7b6207090f17b  .../erasure_teacher_student.py
fe3753f3037905b0b06a3e6eb0e0de6eed876d6e3701197302a85eedb1fb9e86  .../fork_only.diff
     691 erasure_teacher_student.py
    1342 fork_only.diff
IDENTICAL
```

### C2. Per-file additions and deletions recomputed from the diff text

```sh
grep -c '^diff --git' $SRC/fork_only.diff
awk '/^diff --git/{f=$3} /^\+\+\+ /||/^--- /{next} /^\+/{a[f]++} /^-/{d[f]++} END{for(k in a)print k,a[k],d[k]+0; ta=0; td=0; for(k in a){ta+=a[k];td+=d[k]}; print "TOTAL",ta,td}' $SRC/fork_only.diff
```

```
8
a/rfdiffusion/diffusion.py 13 6
a/rfdiffusion/util_module.py 1 1
a/rfdiffusion/inference/utils.py 67 56
a/rfdiffusion/inference/model_runners.py 37 8
a/rfdiffusion_erasure_teacher_student.py 691 0
a/rfdiffusion/util.py 71 28
a/config/inference/base.yaml 1 1
a/rfdiffusion/kinematics.py 33 38
TOTAL 914 138
```

### C3. Citation spot checks against the script (text read only)

```sh
for n in 36 37 38 39 58 59 68 71 72 84 85 90 92 93 101 102 122 123 124 140 141 178 179 193 211 261 262 265 279 280 322 323 361 384 438 440 448 474 477 479 586 590 591 592 593 609 611 661 663 677; do printf "%s: " $n; sed -n "${n}p" $SRC/erasure_teacher_student.py | cut -c1-110; done
for r in 199,203 218,230 236,246 284,288 290,297 302,313 325,325; do sed -n "${r}p" $SRC/erasure_teacher_student.py; done
grep -n "nan\|isfinite\|seed\|weights_only\|torch.load\|clip_grad\|set_detect\|load_checkpoint" $SRC/erasure_teacher_student.py
```

Selected output (every other line likewise matched its citation):

```
 286:        concept_adj = self.eta * (px0_cond - px0_uncond)
 287:        target = px0_uncond - concept_adj
 290:        px0_uncond_norm = px0_uncond.norm(dim=-1, keepdim=True)
 295:        scale_factor = torch.clamp(scale_factor, 0.1, 2.0)
 306:        element_loss = (px0_student - stable_target.detach()) ** 2 * 0.01  # Detach target
 311:            loss = masked_loss.sum() / valid
 313:            RuntimeError
 325:        return loss
 350:        torch.autograd.set_detect_anomaly(True)
 373:        grad_norm = torch.nn.utils.clip_grad_norm_(
 477:    def load_checkpoint(self, path: str):
 479:        checkpoint = torch.load(path, map_location=self.device)
```

`grep` for `seed`, `isfinite`, `nan` printed no script lines; `load_checkpoint` appears only at its definition (477).

### C4. Ancestor citations

```sh
g(){ git -C /Users/shrey/Projects/safeRFd show "${ANC}:$1"; }
g rfdiffusion/diffusion.py | sed -n '103p;621p'
g rfdiffusion/inference/model_runners.py | sed -n '234p;335p;533,534p;603p;646p;662p;676p;682p;721p;742p'
g rfdiffusion/inference/utils.py | sed -n '360p;447p;508,512p'
g rfdiffusion/util.py | sed -n '588,589p'
g rfdiffusion/Track_module.py | sed -n '415,416p'
g config/inference/base.yaml | sed -n '17p;50p;77p;82,83p;117p'
```

Output (excerpt):

```
            delta[diffusion_mask, ...] = 0
            diffusion_mask (torch.tensor, optional): Tensor of bools, True means NOT diffused at this residue, False means diffused
        model.load_state_dict(self.ckpt['model_state_dict'], strict=True)
        self.diffusion_mask = self.mask_str
        ...
    def sample_step(self, *, t, x_t, seq_init, final_step):
class SelfConditioning(Sampler):
        with torch.no_grad():
        self.prev_pred = torch.clone(px0)
        px0_[~atom_mask] = float("nan")
        if align_motif and diffusion_mask.any():
        if conf.inference.model_runner == "default": ... "SelfConditioning" ...
xyzs_in_base_frame = torch.ones((22, 27, 4))
            R_in = R_in.detach() # detach rotation (for stability)
  align_motif: True / p_drop: 0.15 / T: 50 / crd_scale: 0.25 / partial_T: null / sidechain_input: False
```

(Line 234 output shows the `model.load_state_dict(self.ckpt['model_state_dict'], strict=True)` statement. This is the evidence for F1: a missing dictionary key is a `KeyError`.)

### C5. Render the dashboard and the demo; extract text

```sh
cd $KIT && PYTHONDONTWRITEBYTECODE=1 python3 scripts/demo.py --keep > $S/demo.out 2>&1; echo rc=$?
# the demo prints the kept temp dir ("--keep: outputs left in <dir>"); copy dashboard.html out, then delete that dir
D=$(sed -n 's/^--keep: outputs left in //p' $S/demo.out); cp "$D/dashboard.html" $S/dash_demo.html && rm -rf "$D"
grep -o 'class="[^"]*"' $S/dash_demo.html | sort | uniq -c | sort -rn
python3 -I -c "
import re,html,sys
s=open('$S/dash_demo.html').read()
t=html.unescape(re.sub(r'<[^>]+>','\n',re.sub(r'<style.*?</style>','',s,flags=re.S)))
print('\n'.join(l.strip() for l in t.split('\n') if l.strip()))" > $S/dash_demo.txt
```

Demo output (verbatim):

```
[1] toy teacher/student: loss 0.2403 -> 0.0579 over 60 steps (evidence class TOY_RESULT)
[2] checkpoint saved + verified, digest 829f5c0f389ee189...; tampered copy rejected
[3] scorer-validation fixture (ORACLE_GATED) scored on 30 seeds: verdict JOINT_SUPPORTED  [tests the scorer; says nothing about any method]
[4] robustness probe (row reorder on mse_fsum, 12 seeds): status INVARIANCE_HOLDS
[5] claim ledger: 2 events, chain verified, claim state REVIEWED (not SUPPORTED)
[6] dashboard rendered (28396 bytes, byte-identical on re-render): ...
DEMO OK in 2.9s. All checks passed.
```

`rc=0`. Dashboard class inventory (28396 bytes): `untrusted-cap` 51, `untrusted` 51, `measured` 40, `caveat` 23, `vd vd-supported` 10, `badge ev-toy` 6, `ev-toy` 3, `badge ev-source` 2, `badge ev-nv` 2, `badge ev-hyp` 2, `ev-source` 1, `ev-hyp` 1, `banner` 1, `badge ev-unk` 1. There is no class named for confirmation or success. Rendered text extracted for Q1 (excerpt):

```
H1 Suppression (S) | S | greater 0.1 | 1.1257536612773082 | [0.9798809568019664, 1.259985221421771] | ... | 30 | 0.9875 | SUPPORTED (toy fixture; conditional; not a safety finding)
Joint verdict: JOINT_SUPPORTED (toy fixture; conditional; not a safety finding) CONDITIONAL on 6 unimplemented gate(s)
Attempted 30, failed 0. Complete gate coverage: NO.
control_adequacy PASS A, F ok; E-loss check exempt (declared scorer-validation fixture)
Unimplemented (deferred) validity gates: gate1_config_shift_sensitivity_arm, gate2_error_register_crosscheck, V_set_probes, pilot_execution_and_n_cap_width_rule, assumption1_exchangeability_check, amendment_log_hash.
```

The words "oracle" and "scorer-validation" appear on the page only in the gate-detail row above and the caller-supplied "Subject:" string. `JointResult` fields (`benchmark.py:1036-1047`): `subject, h1, h2, h3, gates, seed_scores, ineligible, n_attempted, n_failed, seed_list_digest, registered_digest, config_hash, margins`; none records fixture kind.

### C6. Inert environment flags

```sh
cd $KIT && grep -rn "MODEL_WEIGHTS_ENABLED\|BIOLOGICAL_TRAINING_ENABLED\|RUN_MODE\|TOY_SEED\|ALLOW_EXTERNAL_NETWORK\|os.environ\|getenv" . 2>/dev/null | grep -v "^./.git/\|docs/PROGRESS.md" | cut -c1-120
```

```
README.md:28:...the `ALLOW_EXTERNAL_NETWORK=false` envi...
.env.example:1:RUN_MODE=TOY_OFFLINE
.env.example:2:ALLOW_EXTERNAL_NETWORK=false
.env.example:3:MODEL_WEIGHTS_ENABLED=false
.env.example:4:BIOLOGICAL_TRAINING_ENABLED=false
.env.example:5:TOY_SEED=42
tests/toy_tests/test_failure_modes.py:169:... os.environ.get("SR03_CHILD") ...
tests/toy_tests/test_scripts.py:18:    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", PYTHONHASHSEED="0")
tests/toy_tests/test_tensor_ops.py:905: ... os.environ.get("SR07_CHILD") ...
docs/CLEAN_CLONE.md:74-75: ... (the five flags listed)
scripts/run_tests.sh:48:export ALLOW_EXTERNAL_NETWORK=false
scripts/run_tests.sh:133:mode = os.environ["EXPECT"]
.github/workflows/ci.yml:14:  ALLOW_EXTERNAL_NETWORK: "false"
```

No line under `src/` reads any of the five flags.

### C7. Unknown/NEEDS-EXECUTION sweep

```sh
cd $KIT && grep -n -i "UNKNOWN\|NEEDS-EXECUTION\|not determinable\|not verified\|unverified\|NOT IMPLEMENTED\|untested\|not been executed" docs/*.md src/toy/*.py scripts/* | grep -v "docs/PROGRESS.md" | grep -v "UnknownError\|unknown key\|unknown or missing\|UNKNOWN_\|\.unknown" | wc -l
```

The register in section 3.1 was assembled from these lines plus a read of the three audit documents in full.

### C8. Search for overstated analogy

```sh
cd $KIT && grep -rn -i "mirror\|mimic\|faithful\|analogue\|replicat\|silently incompatible\|silent key" README.md docs/*.md src scripts | grep -v PROGRESS.md | cut -c1-200
```

Relevant hits: `checkpoint.py:13`, `checkpoint.py:45`, `stability.py:29`, `teacher_student.py:9,18,176,239-240`, README title and purpose lines. (`README.md:1`: `# SafeRFdiffusion — safety-replication agent kit`.)

### C9. Checkpoint "silent" claim vs source

```sh
sed -n 10,16p $KIT/src/toy/checkpoint.py
git -C /Users/shrey/Projects/safeRFd show "${ANC}:rfdiffusion/inference/model_runners.py" | sed -n '234p'
```

```
`torch.save` (L474) and reloads with an unrestricted `torch.load` (L479),
records no hash, seed or data provenance, and stores student weights under
`student_model_state_dict` while upstream loads `model_state_dict` with
`strict=True`, so those checkpoints are silently incompatible with the
        model.load_state_dict(self.ckpt['model_state_dict'], strict=True)
```

### C10. PyTorch `weights_only`

```sh
python3 -I -c "import inspect,torch; print(torch.__version__, inspect.signature(torch.load).parameters['weights_only'])"
```

```
2.7.1 weights_only: Optional[bool] = None
```

### C11. Ledger: a safety-claim statement reaches SUPPORTED with a hollow hash

```sh
cd $KIT && cat > $S/circ1.py <<'EOF'
import sys, hashlib, json
sys.dont_write_bytecode = True
sys.path.insert(0, "src")
from toy import claim_ledger as cl
from toy.schema import EvidenceClass
led = cl.ClaimLedger()
ts = "2026-01-01T00:00:0%dZ"
ev = cl.EvidenceRef("content_hash", hashlib.sha256(b"nothing at all").hexdigest())
for cls in (EvidenceClass.TOY_RESULT, EvidenceClass.SOURCE_OBSERVED, EvidenceClass.HYPOTHESIS):
    cid = "c-" + cls.value
    led.open_claim(event_id=cid+"e1", claim_id=cid, reviewer="alice",
                   statement="safeRFdiffusion is safe and removes hazardous capability.",
                   justification="because", evidence_class=cls, timestamp_utc=ts % 1, evidence_refs=(ev,))
    led.review(event_id=cid+"e2", claim_id=cid, reviewer="alice", justification="ok", timestamp_utc=ts % 2)
    led.support(event_id=cid+"e3", claim_id=cid, reviewer="alice", justification="ok", timestamp_utc=ts % 3, evidence_refs=(ev,))
    print(cls.value, "->", led.claim_state(cid).value)
print(json.dumps(led.summary()[0], indent=1))
EOF
PYTHONDONTWRITEBYTECODE=1 python3 $S/circ1.py
```

```
TOY_RESULT -> SUPPORTED
SOURCE_OBSERVED -> SUPPORTED
HYPOTHESIS -> SUPPORTED
{ "claim_id": "c-HYPOTHESIS", "state": "SUPPORTED",
  "state_label": "SUPPORTED (human review verdict, conditional on the referenced evidence)",
  "evidence_class": "HYPOTHESIS", ... "reviewers": ["alice"], ...
  "statement": "safeRFdiffusion is safe and removes hazardous capability.",
  "statement_is_untrusted_text": true, "is_safety_claim": false,
  "caveat": "A review verdict recorded by a named human about referenced evidence. Not a safety claim; no evidence class was changed by it." }
```

(The first summary row printed in the actual run was the `c-HYPOTHESIS` claim; the other two are identical apart from `evidence_class`.) This behaviour is documented in the module docstring ("main route to a hollow SUPPORTED"); the finding is the constant `is_safety_claim` beside it (F15).

### C12. Dashboard free text carrying a safety claim

```sh
cd $KIT && cat > $S/circ2.py <<'EOF'
import sys, re, html
sys.dont_write_bytecode = True
sys.path.insert(0, "src")
from toy import dashboard as db
from toy.teacher_student import train
from toy.schema import ExperimentRecord, EvidenceClass, MetricValue, TOY_LABEL
tr = train(seed=3, steps=5, timestamp_utc="2026-01-01T00:00:00Z")
rec = ExperimentRecord(name="RFdiffusion is SAFE - validated", provenance=tr.record.provenance,
        metrics={"x": MetricValue.measured(1.0)}, evidence_class=EvidenceClass.TOY_RESULT,
        notes=TOY_LABEL + " verdict: JOINT_SUPPORTED; model is safe; hazardous capability reduced 99%")
print("record accepted; to_json contains claim:", "model is safe" in rec.to_json())
page = db.render_dashboard({"records": [rec]})
txt = html.unescape(re.sub(r"<[^>]+>", "\n", re.sub(r"<style.*?</style>", "", page, flags=re.S)))
for l in [l.strip() for l in txt.split("\n") if l.strip()]:
    if "safe" in l.lower() or "reduced" in l.lower() or "UNTRUSTED" in l: print("  |", l[:160])
EOF
PYTHONDONTWRITEBYTECODE=1 python3 $S/circ2.py
```

```
record accepted; to_json contains claim: True
  | UNTRUSTED FREE TEXT (name) - NOT EVIDENCE
  | RFdiffusion is SAFE - validated
  | UNTRUSTED FREE TEXT (notes) - NOT EVIDENCE
  | TOY RESULT (synthetic, non-biological; not a safety claim) verdict: JOINT_SUPPORTED; model is safe; hazardous capability reduced 99%
```

(The banner line also matched the filter and is omitted here. The page's banner and per-panel badges are intact: no styling changed.)

### C13. SHA and snapshot consistency

```sh
cd $KIT && for f in README.md docs/FORK_AUDIT.md docs/DIFF_EVIDENCE.md docs/METHOD_AUDIT.md docs/SOURCE_SNAPSHOT.json CLAUDE.md; do echo "== $f"; grep -o '\b[0-9a-f]\{40\}\b' $f | sort | uniq -c; done
python3 -I -c "import json;d=json.load(open('docs/SOURCE_SNAPSHOT.json'));print(d['ahead_by'],d['behind_by_vs_merge_base'],d['behind_by_vs_upstream_main'],sum(f['additions'] for f in d['changed_files']),sum(f['deletions'] for f in d['changed_files']),len(d['changed_files']))"
```

Every file shows only `12d5426...`, `5cbd18a...`, `e220924...` (and `86507b6...` in DIFF_EVIDENCE and SOURCE_SNAPSHOT), one spelling each. Snapshot line: `2 0 36 914 138 8`.

### C14. Test suite, four environments (bytecode off, caches cleared)

```sh
cd $KIT
find . -name __pycache__ -type d -not -path './.git/*' -prune -exec rm -rf {} +
mkdir -p $S/nodeps $S/yamlonly $S/torchonly
printf 'import sys\nfor m in ("torch","numpy","yaml","pytest"):\n    sys.modules[m] = None\n' > $S/nodeps/sitecustomize.py
printf 'import sys\nfor m in ("torch","numpy","pytest"):\n    sys.modules[m] = None\n'        > $S/yamlonly/sitecustomize.py
printf 'import sys\nsys.modules["torch"] = None\n'                                          > $S/torchonly/sitecustomize.py
for e in nodeps yamlonly torchonly; do PYTHONDONTWRITEBYTECODE=1 PYTHONHASHSEED=0 PYTHONPATH=$S/$e python3 -m unittest discover -s tests 2>&1 | tail -3; done
./scripts/run_tests.sh --expect torch
git status --short; find . -name __pycache__ -not -path './.git/*'
```

| Environment | Result |
|---|---|
| nothing installed (torch, numpy, PyYAML, pytest blocked) | `Ran 739 tests in 54.183s` `OK (skipped=86)` |
| PyYAML only | `Ran 739 tests in 20.231s` `OK (skipped=85)` |
| torch blocked; numpy, PyYAML, pytest present | `Ran 739 tests in 20.279s` `OK (skipped=84)` |
| torch 2.7.1, numpy 2.4.6, PyYAML, pytest (`run_tests.sh --expect torch`) | `unittest: ran=739 skipped=2 failed=0 rc=0`; `pytest: passed=737 skipped=2 rc=0`; `skip policy (torch): 2 skipped, 0 for 'not installed'`; `RESULT: OK (unittest ran=739 skipped=2)` |

`git status --short` empty and no `__pycache__` afterwards. (The kit's own CI pin is numpy 1.26.4; this host has numpy 2.4.6, as noted in `constraints.txt` comments.) Note: the four rows were run at different moments; none observed a change in test count or HEAD.

### C15. Per-module timing (journal cross-check)

```sh
for m in test_benchmark test_claim_ledger test_scripts test_dashboard test_robustness; do PYTHONDONTWRITEBYTECODE=1 python3 -m unittest tests.toy_tests.$m 2>&1 | grep -E "^Ran|^OK"; done
```

`test_benchmark` 112 tests 13.3 s; `test_claim_ledger` 87 tests 0.148 s; `test_scripts` 17 tests 3.6 s; `test_dashboard` 95 tests 1.1 s; `test_robustness` 85 tests 1.3 s.

### C16. Blueprint checkbox, dependency and QA-heading audit

```sh
cd $KIT && python3 -I - <<'PY'
import re
bp=open('docs/BUILD_BLUEPRINT.md').read().splitlines()
pg=open('docs/PROGRESS.md').read()
tasks={}
for l in bp:
    m=re.match(r'- \[( |x)\] \*\*(SR-\d\d)\*\*.*?\*\*Depends:\*\* ([^.]*)\.',l)
    if m: tasks[m.group(2)]=(m.group(1)=='x',[d.strip() for d in re.findall(r'SR-\d\d',m.group(3))])
for t,(x,deps) in tasks.items():
    h=re.search(r'^##+ %s\b[^\n]*PASS[^\n]*$'%t,pg,re.M)
    bad=[d for d in deps if not tasks.get(d,(False,))[0]]
    print(f"{t} [{'x' if x else ' '}] deps={deps} unchecked_deps={bad} qa_heading={'YES' if h else 'NO'}")
PY
```

```
SR-00 [x] deps=[] unchecked_deps=[] qa_heading=NO          (PASS is inside the SR-00 section, line 31 "Status: PASS")
SR-05 [x] deps=['SR-04'] unchecked_deps=[] qa_heading=YES  (FALSE POSITIVE: matches "Residual defects closed (after QA PASS)")
SR-11 [x] deps=['SR-10'] unchecked_deps=['SR-10'] qa_heading=YES
SR-14 [x] deps=['SR-13'] unchecked_deps=['SR-13'] qa_heading=YES
SR-13 [ ] deps=['SR-08', 'SR-10'] unchecked_deps=['SR-10'] qa_heading=NO
SR-15 [ ] deps=['SR-12', 'SR-14'] unchecked_deps=['SR-12'] qa_heading=NO
(other rows: dependencies satisfied; checkbox state agrees with a QA heading where [x])
```

The SR-05 row is the reason for F13: the script's match is a heading phrase, not a QA verdict section. Confirm manually: `grep -n "SR-05" docs/PROGRESS.md` lists no "QA verdict" heading for SR-05, whereas SR-01, SR-02, SR-03, SR-04, SR-06, SR-08, SR-09, SR-11 and SR-14 each have one.

### C17. Protocol vs scorer: gate 11 scope

```sh
cd $KIT && sed -n 240p docs/EVALUATION_PROTOCOL.md | cut -c1-200
sed -n 82,83p src/toy/benchmark.py
git log --format='%h %s' -- docs/EVALUATION_PROTOCOL.md
git show --stat --format='%h %s' ff451e1 | head -12
```

```
| `control_adequacy` (gate 11) | 11 | **H1 and H2 only**: both INCONCLUSIVE. H3 is still evaluated and reported with the gate status alongside (see the open issue in section 5) |
GATE_SCOPES = {"seed_list_frozen": "all", "min_seeds": "all", "failure_rate": "all", "rowsets_disjoint": "all",
               "mask_correct": "all", "control_adequacy": "all", "convergence": "H3"}
12bc490 SR-09 amended to r3 ... / 710151f ... / d87b48f ...
```

`ff451e1`'s stat does not list `docs/EVALUATION_PROTOCOL.md`.

### C18. Post-attestation edits to attested files

```sh
cd $KIT && for f in docs/EVALUATION_PROTOCOL.md docs/ERROR_REGISTER.md docs/METHOD_AUDIT.md src/toy/teacher_student.py src/toy/checkpoint.py; do echo "$f: $(git log --format=%h -- $f | tr '\n' ' ')"; done
```

`EVALUATION_PROTOCOL.md: 12bc490 710151f d87b48f` (SR-09 PASS was recorded in `905bbfe`; `12bc490` is later). `ERROR_REGISTER.md: 96b5ac2 905bbfe 710151f d87b48f` (the latest edit is the orchestrator's two post-QA nits, accepted by QA). `teacher_student.py: 710151f d87b48f e436d93` (no commit after the SR-05 PASS commit; the residual fixes are in it).

---

## 10. What a PASS would require

Fix F1, F2, F3, F4, F5, F6, F12, F13, F14, F15 (the "required" rows in section 0); the remaining items are advisory. After the in-flight dashboard and benchmark rework lands, re-run C14, C5 and C17 and update this report with the new HEAD. Nothing in this review changes the standing limits of the kit: no measured result about any real model exists, and none is claimed.
