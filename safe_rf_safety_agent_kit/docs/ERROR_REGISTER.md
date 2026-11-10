# ERROR_REGISTER: error/uncertainty register for the audited fork script (task SR-03)

**Owner:** numerics teammate. **Basis:** `docs/METHOD_AUDIT.md` (SR-02) and `docs/FORK_AUDIT.md`. **Status:** draft pending independent QA review of every classification (SR-03 verify clause); nothing here is QA-attested yet.

## READ THIS FIRST: what this register is and is not

- **Pattern demonstrations do not establish runtime behaviour of the audited program.** Each executable reproduction in `src/toy/failure_modes.py` shows that a *class* of defect behaves as stated on abstract numbers in isolation. Whether the audited script actually reaches that code path with those values is a separate question that can only be settled by executing it. Executing it (or any RFdiffusion code) is out of scope for this kit, and nothing here imports, runs or simulates it.
- **No claim that the method is broken, and none that it is safe.** The register reports mechanical facts and labelled uncertainty. A defect pattern being present in the source says nothing about whether the method works or fails to work, or about any capability.
- All demonstrations are abstract, non-biological, offline, and run in well under a second. No weights, network, pickle payloads or biological content are involved.
- Source citations use the METHOD_AUDIT keys: `S:Ln` = line n of the fork script (`rfdiffusion_erasure_teacher_student.py`, 691 lines, sha256 `1fef6383...f17b`); `D:Ln` = line n of `fork_only.diff`; `A:path:Ln` = ancestor `e220924` file. I did not re-read the fork script; line numbers are taken from METHOD_AUDIT and inherit its SOURCE OBSERVED / INFERENCE status.

### Classification vocabulary

| Label | Meaning |
|---|---|
| CONFIRMED-IN-SOURCE | The defect-relevant text is directly observable in the audited source. Says nothing about runtime reach. |
| PATTERN-DEMONSTRATED | A generic executable reproduction shows the pattern behaves as claimed. Says nothing about the audited program. |
| UNKNOWN-NEEDS-EXECUTION | Cannot be settled without running something that is out of scope, or hardware not present. |
| STATIC-ANALYSIS-ONLY | Reasoned from text or documented API behaviour; no executable reproduction here, by design or because none is meaningful. |

An entry may carry two labels (e.g. CONFIRMED-IN-SOURCE for the text plus PATTERN-DEMONSTRATED for the behaviour of that text). The runtime-reach question stays UNKNOWN-NEEDS-EXECUTION unless stated.

### Summary

| ID | Concern | Labels | Severity | Generic reproduction |
|---|---|---|---|---|
| ER-01 | Bare `RuntimeError` is not raised (empty mask) | CONFIRMED-IN-SOURCE + PATTERN-DEMONSTRATED | Low-Medium (if path reached; loud crash) | `bare_exception_statement_is_a_no_op` |
| ER-02 | NaN masked by multiplication survives | CONFIRMED-IN-SOURCE (mask multiply) + PATTERN-DEMONSTRATED; NaN presence UNKNOWN-NEEDS-EXECUTION | Medium | `nan_times_zero_is_nan` |
| ER-03 | Detach severs parameter gradient (generic pattern; no unintended detach identified) | PATTERN-DEMONSTRATED + CONFIRMED-IN-SOURCE (existence of the detach calls only) | Low (no unintended detach identified) | `detach_severs_gradient` |
| ER-04 | Output `requires_grad` does not prove parameter gradient; checks commented out | CONFIRMED-IN-SOURCE + PATTERN-DEMONSTRATED; flow itself UNKNOWN-NEEDS-EXECUTION | Medium | `input_leaf_requires_grad_does_not_prove_parameter_gradient` |
| ER-05 | Loss normalization omits trailing dims | CONFIRMED-IN-SOURCE (arithmetic) + PATTERN-DEMONSTRATED | Low-Medium | `normalization_mismatch_scale_factor` |
| ER-06 | Ambiguous mask polarity is silent | PATTERN-DEMONSTRATED; applicability INFERENCE only | Medium | `mask_polarity_inversion` |
| ER-07 | General pattern: a post-clip norm in a log cannot show gradient magnitude (the script itself logs the pre-clip value) | PATTERN-DEMONSTRATED (pattern only); script's logged value STATIC-ANALYSIS-ONLY | Informational (script); pattern recorded as a caution | `gradient_clipping_hides_magnitude` |
| ER-08 | Unrestricted `torch.load`/pickle trust | STATIC-ANALYSIS-ONLY (no demo, by design) | Medium-High on untrusted files | none |
| ER-09 | Cross-device (CPU/GPU) numerical variance | UNKNOWN-NEEDS-EXECUTION (CUDA leg); CPU-vs-MPS measured generically by SR-07 | Unknown | `tests/toy_tests/test_tensor_ops.py` (`TestCpuVsMps`, `TestCpuVsCuda`) |
| ER-10 | Baseline-mode confound (`model_runner` switch) | CONFIRMED-IN-SOURCE (diff) + STATIC-ANALYSIS-ONLY; effect UNKNOWN-NEEDS-EXECUTION | Medium (validity of comparisons) | none (design only) |
| ER-11 | In-place mutation of tensors needed by autograd | STATIC-ANALYSIS-ONLY / UNKNOWN-NEEDS-EXECUTION | Low-Medium | none |

Severity is the author's judgement of *consequence if the defect is reached*, with the reach itself unproven; it is not a probability.

---

## ER-01: bare `RuntimeError` expression does not raise (empty-mask path)

- **Where:** `S:312-313` (`else: RuntimeError`), `return loss` at `S:325`; METHOD_AUDIT section 4 ("Empty-mask path") and claims-register #13; FORK_AUDIT concern 1.
- **Classification:** CONFIRMED-IN-SOURCE (text observed in METHOD_AUDIT) + PATTERN-DEMONSTRATED. Whether an empty mask ever occurs at runtime: UNKNOWN-NEEDS-EXECUTION.
- **Severity: Low-Medium if reached (lowered from High, then from Medium for consistency with ER-11, another loud-failure entry).** The failure is loud, not silent corruption: the intended `RuntimeError` is replaced by an `UnboundLocalError` crash at `return loss`, with a less informative message and the wrong type. QA established that the script contains **no** `except RuntimeError`; its only handlers are `except Exception` at `S:663` and `S:683`, which **would** catch the resulting `UnboundLocalError`, so the type change would not by itself bypass handling. Reaching the path at all is UNKNOWN (one fixed `(pdb, contig)` pair).
- **Reproduction:** `bare_exception_statement_is_a_no_op`; test `TestStdlibPatterns.test_bare_exception_is_noop_and_unboundlocalerror`.
- **Demonstrated (exact):** evaluating the bare name or an un-raised `RuntimeError('...')` raises nothing; the function then raises `UnboundLocalError` (message, Python 3.12: `cannot access local variable 'loss' where it is not associated with a value`; wording is version-dependent, type is not). `issubclass(UnboundLocalError, RuntimeError)` is `False`. Control with `raise RuntimeError("empty mask")` raises `RuntimeError`. Non-empty mask returns normally.
- **Does not establish:** that the audited script ever has `valid == 0`; what happens after the `except Exception` handlers at `S:663`/`S:683` catch it (not examined here); any behaviour of the real call chain.
- **To settle:** a generic stand-in with the same control flow cannot answer reach. Needs execution of the script on its configured input, or an author statement that the mask is provably non-empty. The static fact (no raise) needs nothing further.

## ER-02: masking by multiplication does not remove NaN

- **Where:** `S:306-311` (`element_loss * scaffold_mask`, `.sum() / valid`); METHOD_AUDIT section 4 "No finite check" (INFERENCE). Related: fork alignment writes NaN at `~atom_mask` positions (`D:335-337`: comment at D:335, `nan_tensor` at D:336, `torch.where` at D:337; METHOD_AUDIT 3.2 item 5). That write-back can only restore NaN already present in `px0`, it does not create or remove any. `atom_mask` is set all-True at `S:199-200`. The `clamp` in the renormalization (`S:295`) is not a NaN remover.
- **Classification:** CONFIRMED-IN-SOURCE (`S:307` multiplies the element loss by the mask, and `S:311` sums then divides) + PATTERN-DEMONSTRATED (multiplication does not remove NaN). Presence of NaN in the real `px0` tensors: UNKNOWN-NEEDS-EXECUTION. METHOD_AUDIT 3.2 item 5 infers absent-atom slots are probably finite placeholders rather than NaN, which would make the hazard dormant; not verified.
- **Severity: Medium.** If any masked-out element is non-finite the loss and every gradient become NaN while the mask appears to be applied. `set_detect_anomaly(True)` (`S:350`) might surface this, but that is also unobserved.
- **Reproduction:** `nan_times_zero_is_nan`; test `test_nan_times_zero_is_nan`.
- **Demonstrated (exact):** `0.0 * nan` and `0.0 * inf` are both `nan`; for values `(1.0, nan, 3.0)` with keep `(T, F, T)` the multiplicative sum is `nan`, the selection-based sum is `4.0`. With all-finite input both agree (the pattern is harmless there).
- **Does not establish:** that NaN/Inf reach the script's loss; that NaN is present. With torch, the demo also confirms `(v*m).sum()` is NaN, selection gives `4.0`, and `torch.clamp(nan, 0.1, 2.0)` stays NaN (`torch_check`; skipped without torch).
- **To settle:** a finiteness probe on the real intermediate tensors (needs execution, gated), or confirmation that padded atoms are zero-filled rather than NaN-filled.

## ER-03: detach severs parameter gradient

- **Where:** detach sites `S:218, 243, 306` (teacher outputs and target; intended), `D:173-200` (`get_next_frames` `.cpu().detach()...numpy()`; the `x_t_1` path, discarded by the script), ancestor `A:rfdiffusion/Track_module.py:415-416, 435-436, 456-457` (`R_in.detach()`, `T_in.detach()`); METHOD_AUDIT section 6; FORK_AUDIT concern 3.
- **Classification:** PATTERN-DEMONSTRATED + CONFIRMED-IN-SOURCE for the detach sites. Net effect on which student parameters get gradient: UNKNOWN-NEEDS-EXECUTION.
- **Severity: Low (lowered from Medium).** The script's detaches (teacher outputs, target) are intended and the upstream `Track_module` detaches are by design (`# detach rotation (for stability)`); I have identified **no unintended detach** on the student path. "CONFIRMED" here refers only to the existence of the calls, not to any defect. The register keeps the entry because the pattern bears on what ER-04's check must discriminate, and because upstream `Track_module` detaches truncate only the cross-block rotation/translation chain (METHOD_AUDIT section 6): each block's own parameters, and the final block's, still receive gradient, and overall parameter coverage is undetermined (UNKNOWN-NEEDS-EXECUTION). Severity would rise only if a gated run showed parameters that should learn receiving no gradient.
- **Reproduction:** `detach_severs_gradient` (torch); test `TestTorchPatterns.test_detach_severs_gradient` (skipped without torch).
- **Demonstrated (exact):** with `out = (w1*x).detach().sum() + (w2*x).sum()`, `x=(1,2)`: `w1.grad is None`, `w2.grad == [1.0, 2.0]`, `out.requires_grad` is `True`, and the detached branch has `requires_grad == False`.
- **Does not establish:** which of the real model's parameters are reached, or whether the real student path contains any unintended detach.
- **To settle:** per-parameter `.grad` coverage on the real student after one backward (gated run); the generic analogue is the ER-04 discriminating check.

## ER-04: input-leaf `requires_grad` does not prove parameter-level gradient (most important)

- **Where:** `x_t_student = x_t.clone().detach().requires_grad_(True)` at `S:261` (a leaf input, not in the optimizer, `S:101-106`); assertions `# if not px0_student.requires_grad: raise ...` at `S:279-280` and `# if not loss.requires_grad: raise ...` at `S:322-323` are **commented out**; diagnostic prints `S:314-317` also commented out; the logged student-parameter gradient norm (`S:373`, `S:384`, `S:425`, `S:430-435`) is present and is the existing indirect evidence; fork-added `requires_grad` prints `D:131-157`. METHOD_AUDIT section 6, claims-register #14 and #15; FORK_AUDIT concern 2.
- **Classification:** CONFIRMED-IN-SOURCE (assertions commented out; input leaf has `requires_grad=True`) + PATTERN-DEMONSTRATED (the inference gap). Whether student parameters actually receive non-zero gradient: **UNKNOWN-NEEDS-EXECUTION** (claims-register #14 stays UNKNOWN).
- **Severity: Medium (lowered from High).** An earlier version of this entry said the only evidence of flow was the commit message plus output `requires_grad`; that was wrong. The script also computes, logs and stores the **student-parameter gradient norm** (`S:373`, `S:384`, `S:425`, `S:430-435`), and a norm of exactly 0 would reveal absent parameter gradient (METHOD_AUDIT section 6); the author's own note says the gradient is high, which is weak indirect evidence that something reaches the parameters. What is genuinely missing is an automated per-parameter coverage gate, and the commented-out `requires_grad` assertions would not discriminate even if restored (input-leaf effect). That is a narrower gap than "no evidence of flow", and the logged norm is a total over parameters, so it cannot show *which* parameters are reached.
- **Reproduction:** `input_leaf_requires_grad_does_not_prove_parameter_gradient` (torch); test `TestTorchPatterns.test_input_leaf_requires_grad_does_not_prove_parameter_gradient` (skipped without torch).
- **Demonstrated (exact), input `x=(1,2)` leaf, parameter `w=(0.5,0.5)`:**

  | graph | `out.requires_grad` | `x.grad` | `w.grad` | discriminating check (some `p.grad` not None and non-zero) |
  |---|---|---|---|---|
  | severed (`w` through `.detach()`) | True | [2.0, 2.0] | None | False |
  | zeroed (`0.0 * w`) | True | [2.0, 2.0] | [0.0, 0.0] | False |
  | control (`x * w`) | True | [0.5, 0.5] | [1.0, 2.0] | True |

  The naive predicate is True in all three rows; only the per-parameter gradient check separates them.
- **Does not establish:** that the real student has the severed or zeroed topology (it may well be connected; that is the point: source alone cannot say). It also does not show that a non-zero gradient implies useful learning; non-zero is necessary for parameter-level flow, not sufficient for anything else.
- **To settle:** inspect the logged gradient-norm series from an actual run (a norm of exactly 0 would show absent parameter gradient; it cannot show per-parameter coverage), and after `backward()` check that parameters have non-None, non-zero `.grad` (a per-parameter check; note SR-06's `require_parameter_gradient` takes one flat gradient and reports no coverage, so a per-parameter coverage report is not yet provided by any kit module). For the real model this requires one gated forward/backward, outside the autonomous loop (SR-17).

## ER-05: normalization mismatch (divisor omits trailing dimensions)

- **Where:** `S:302-311` (`masked_loss.sum() / valid` where `valid = scaffold_mask.sum()` counts residues, while summed elements are `M x 14 x 3`); METHOD_AUDIT section 4 and claims-register #9; FORK_AUDIT concern 4.
- **Classification:** CONFIRMED-IN-SOURCE for the arithmetic, given the shape premise `(L,14,3)` (itself SOURCE OBSERVED from the cited slices) + PATTERN-DEMONSTRATED.
- **Severity: Low-Medium.** It is a constant factor (42 = 14*3), further multiplied by the `0.01` constant at `S:306`, for a net `0.42 x` element-mean MSE (METHOD_AUDIT section 4). By itself it does not explain the author's "high gradient" remark (claims-register #10 stays UNKNOWN); it matters for comparability with any other loss and for tuning `eta`/learning rate.
- **Reproduction:** `normalization_mismatch_scale_factor` (arguments `leading`, `trailing`); test `test_normalization_mismatch_factor`.
- **Demonstrated (exact, via `Fraction`):** observed factor equals `prod(trailing)` for `(4,(14,3))->42`, `(1,(2,))->2`, `(7,(5,1,3))->15`, `(3,())->1` (no trailing dims, no mismatch), `(2,(14,3))->42`. The factor does not depend on the leading count.
- **Does not establish:** the real tensors' shapes at runtime, or that any particular loss scale is wrong for the method's purpose (the choice may be intentional).
- **To settle:** print `px0.shape` and `scaffold_mask.shape` once (execution), or an author statement.

## ER-06: ambiguous boolean-mask polarity is silent

- **Where:** `diffusion_mask = ~motif_mask` (`S:203, S:207`) and all-`True` (`S:228, S:232`) versus ancestor docstring "True means NOT diffused" (`A:rfdiffusion/diffusion.py:621`); METHOD_AUDIT section 3.4 and claims-register #6; also the "scaffold mask" label on a motif-derived mask (`S:299-302`, METHOD_AUDIT section 5, claims #11/#12).
- **Classification:** PATTERN-DEMONSTRATED (generic). Applicability to the script: **INFERENCE only** (METHOD_AUDIT 3.4: "appears inverted vs ancestor docstring"; author intent UNKNOWN). Treat as UNKNOWN-NEEDS-EXECUTION / author confirmation, not as a confirmed bug.
- **Severity: Medium.** A polarity error would run without any exception and produce a plausible-looking but different number, so it cannot be detected by crash-testing.
- **Reproduction:** `mask_polarity_inversion`; test `test_mask_polarity_inversion_is_silent`.
- **Demonstrated (exact):** for squared errors `(1,4,9,16)` and mask `(T,F,T,F)`: True-selects reads indices `[0,2]`, loss `5.0`; False-selects reads `[1,3]`, loss `10.0`; the index sets are disjoint and cover everything; nothing raised. A degenerate mask yields an empty selection reported as `None` (not an exception) in the demo.
- **Does not establish:** that the script's polarity is wrong, or that its uses are inconsistent beyond what METHOD_AUDIT already reasons.
- **To settle:** a unit test of the real `diffuse_pose` mask convention on a synthetic tensor (SR-02's suggestion), or author confirmation.

## ER-07: general pattern: a post-clip norm cannot show gradient magnitude (does NOT apply to the script's logged value)

- **Where:** `clip_grad_norm_` at `S:373-376`, `max_grad_norm=10` in `main()` (`S:661`), logged `grad_norm` `S:384, S:425, S:430-435` (`S:373` assigns the return value of `clip_grad_norm_`; `S:385` is `lr`); the author's own commit note "gradient is high and needs to be looked at" (commit `12d5426`; FORK_AUDIT concern 6); METHOD_AUDIT section 4 (last paragraph).
- **Classification:** PATTERN-DEMONSTRATED (generic). What the script logs: STATIC-ANALYSIS-ONLY (INFERENCE from API: `clip_grad_norm_` returns the **pre-clip** total norm, so the script's logged value is likely not hidden; checked on a stand-in tensor only). Actual gradient magnitudes: UNKNOWN-NEEDS-EXECUTION.
- **Severity: Informational for this script (the pattern itself is recorded as a general caution).** The pattern (a bounded post-clip norm is compatible with arbitrarily large raw gradients) is real, but the source shows the script assigns the return of `clip_grad_norm_` at `S:373`, which PyTorch documents as the pre-clip total norm, and logs that (`S:384`, `S:425`). So **the register does not claim the script hides gradient magnitude**; that claim would be false per its own source. The residual concerns are that the author flagged high gradients, that `max_grad_norm=10` means clipping may or may not engage (UNKNOWN), and that clipped updates are not evidence of conditioning. METHOD_AUDIT's caveat applies: the logged norm is the pre-clip value by API behaviour (INFERENCE, checked here only on a stand-in tensor). **This register makes no claim of stability from clipping.**
- **Reproduction:** `gradient_clipping_hides_magnitude`; test `test_gradient_clipping_hides_magnitude`.
- **Demonstrated (exact):** vector `(3,4)*s` with `max_norm=1`: pre-clip norms `50, 5e3, 5e6, 5e9` (a `1e8` span) all clip to post-clip norm `1.0` (agree to <1e-4). With `max_norm=100` and `s=1`, pre-clip `5.0` is untouched. With torch present, `clip_grad_norm_` on grad `(3e3,4e3)` returns `5000.0` and leaves norm `1.0`.
- **Does not establish:** the script's actual gradient scale, whether clipping engages (with `max_grad_norm=10` it may rarely engage if norms are below 10: UNKNOWN), or whether training converges.
- **To settle:** pre-clip norms with seeds and uncertainty over steps from a run (gated), plus a conditioning study on a generic model.

## ER-08: unrestricted `torch.load` / pickle trust property (STATIC ONLY, no demo)

- **Where:** `torch.load(path, map_location=self.device)` with no `weights_only` argument at `S:479`; save at `S:474`; same pattern in upstream (`A:rfdiffusion/inference/model_runners.py:183, 821, 826`); METHOD_AUDIT section 7 and claims-register #25.
- **Classification:** STATIC-ANALYSIS-ONLY. Effect under the installed PyTorch version: UNKNOWN-NEEDS-EXECUTION (the `weights_only` default is version-dependent and this audit did not pin or test it).
- **Severity: Medium-High when loading files of unknown origin; Low for files the user created.** Not fork-specific. **Reach note:** `load_checkpoint` (`S:477`) has no call site in the script, so the fork's own load path is defined but not exercised by the script; the load path that is exercised is upstream's `torch.load` at `A:rfdiffusion/inference/model_runners.py:183` (model weights, not the fork's checkpoints). Read the concern accordingly: it applies to whoever later calls `load_checkpoint` or loads untrusted files through upstream.
- **Property, stated in prose only:** Python's `pickle`, which `torch.load` uses for general checkpoint objects, reconstructs objects by calling callables named inside the file. Loading therefore runs code chosen by whoever wrote the file, with the privileges of the loading process. "Loading a checkpoint" is thus equivalent to "running a program supplied by the checkpoint's author" unless the loader is restricted to plain tensors and primitive containers. The checkpoint dict at `S:458-475` also embeds a resolved config container, and no hash or provenance is stored, so a file cannot be tied to its origin by its contents (METHOD_AUDIT section 7).
- **Deliberately not done:** no payload is built, no file is written that would execute on load, and no function in `failure_modes.py` loads anything (a test asserts the module contains no pickle or `torch.load` text).
- **Mitigation direction (SR-08):** the toy checkpoint will use a non-pickle format (for example JSON metadata plus plain numeric data), record provenance hashes, verify them before use, and reject corrupted or unexpected content, with round-trip and corrupted-file tests. For tensors, a weights-only loader is the standard safer approach, but its availability and exact behaviour depend on the PyTorch version, which is to be pinned.
- **Does not establish:** that any file in this workflow is hostile, or that the installed PyTorch would execute anything.
- **To settle:** pin the PyTorch version and read its documented `weights_only` default; no execution of untrusted input is ever required.

## ER-09: cross-device (CPU/GPU) numerical variance

- **Where:** device/dtype plumbing edits `D:88-101` (`_preprocess`), `D:173-212` and `D:343-365` (`inference/utils.py`), `.to(device)` calls throughout the script (for example `S:268-277`); the fork rewrote NumPy SVD alignment in torch (`torch.linalg.svd`, `torch.det`, `torch.sign`, `D:213-342`), which can differ across devices and precisions; METHOD_AUDIT sections 8 and 9 (class DEV).
- **Classification:** **UNKNOWN-NEEDS-EXECUTION** for the audited program on any device, and for any CUDA comparison. This host (macOS) has **MPS available and CUDA unavailable** (an earlier version of this entry said "no GPU", which was wrong). Nothing here is a finding about the audited program's device variance.
- **Severity: Unknown.** Floating-point reductions, SVD sign/ordering choices and `det`-based reflection fixes are generic sources of device-dependent differences; their size for the audited code is not measured.
- **Reproduction (SR-07, generic):** `tests/toy_tests/test_tensor_ops.py` `TestCpuVsMps` compares CPU and MPS float32 on synthetic tensors (sum of squares, matmul, normalize) and reports measured differences (SR-07 reports max relative difference around 1e-7, not bitwise identical; see that file for the exact values); `TestCpuVsCuda` is skip-gated and reports skipped, with a reason naming this entry, when CUDA is absent. MPS float64 is not supported and is skipped with a reason. `linalg.svd` falls back to CPU on MPS, so no SVD/Kabsch comparison on a GPU was made.
- **Remaining UNKNOWN:** (1) any CUDA result (not runnable here); (2) GPU behaviour of SVD/determinant-based alignment (MPS falls back to CPU; CUDA untested); (3) anything about the real model or script on any device.
- **To settle:** run the existing `TestCpuVsCuda` and an added SVD/Kabsch battery (random finite and near-degenerate point sets) on a CUDA host, with tolerances documented and maximum absolute/relative differences recorded; real-model equivalence needs a gated run (SR-17).
- **Does not establish:** anything about the audited program on any device.

## ER-10: baseline-mode confound (`model_runner: SelfConditioning` -> `default`)

- **Where:** `config/inference/base.yaml` change (`D:1-13`); selector `A:rfdiffusion/inference/utils.py:508-512`; `SelfConditioning.sample_step` hard-codes `with torch.no_grad():` (`A:rfdiffusion/inference/model_runners.py:721`) and has signature `(self, *, t, x_t, seq_init, final_step)` with **no `enable_grad` parameter** (`A:...:682`); the fork's grad-enabling edit exists only in `Sampler.sample_step` (`D:111-160`); the script calls `sample_step(..., enable_grad=...)` (`S:211-217, 241-242, 268-274`). METHOD_AUDIT section 8 and claims-register #22; FORK_AUDIT concern 5.
- **Classification:** CONFIRMED-IN-SOURCE (the diff and the two signatures) + STATIC-ANALYSIS-ONLY (the reasoning that follows). Size of the effect: UNKNOWN-NEEDS-EXECUTION.
- **Severity: Medium for validity of any comparison**; this is not a numerical defect. Two facts hold together:
  1. **Necessary given the fork's chosen edit (INFERENCE per SR-02); not shown necessary for any gradient flow:** under `SelfConditioning` the `enable_grad=` keyword would raise `TypeError` and the body is `no_grad`, so the switch to `default` was the minimal way to let gradients flow.
  2. **Still a confound for baseline comparison:** `default` omits the self-conditioning input (previous x0-prediction fed back as a template) that the pre-fork default used, so "upstream default" versus "fork, trained" differs by (a) the runner, (b) the other numeric/geometry edits that run for all users (METHOD_AUDIT section 9), (c) training, and (d) stochasticity, and nothing in the sources separates them.
- **Reproduction:** none; a toy analogue would add nothing beyond the design below and would risk implying behaviour.
- **Does not establish:** that outputs differ materially between the two runners, or that the runner change is methodologically wrong.
- **To settle:** the four-arm design in METHOD_AUDIT section 8 (A: ancestor `SelfConditioning`; B: ancestor `default`; C: fork code, untrained; D: fork code, trained), seeds pre-registered, paired differences with uncertainty. The arms use real weights and belong to the SR-17 human gate. The weight-free part (original-vs-patched numeric helpers on synthetic tensors) is within SR-07 scope.

## ER-11: in-place mutation relevant to autograd

- **Where:** the fork removed some in-place ops (`D:370-460`, `kinematics.py`: `v /= ...` to `v = v / ...`, `torch.where`); `_preprocess` NaN masking is guarded with `.clone()` (`D:77-91`); retained in-place indexed fills, for example `c6d[...,0][c6d[...,0] >= DMAX] = 999.9` with the comment "This is OK" (`D:449-450`); METHOD_AUDIT section 9.
- **Classification:** STATIC-ANALYSIS-ONLY; whether any retained in-place write touches a tensor autograd needs: UNKNOWN-NEEDS-EXECUTION.
- **Severity: Low-Medium.** Autograd typically reports a version-counter error at `backward()` when a saved tensor was modified, which is loud rather than silent; but in-place writes on non-saved tensors, or on views, can change values without an error, and the retained "This is OK" claim is unverified.
- **Reproduction:** none. A stand-in would only restate documented autograd behaviour without bearing on which tensors the real code saves.
- **Does not establish:** that any in-place hazard exists in the real graph.
- **To settle:** SR-07's non-in-place numeric ops plus an in-place-vs-out-of-place equality test on synthetic tensors; for the real graph, execution with anomaly detection (gated).

---

## Items not demonstrated generically, and why

| Concern | Why no generic demonstration |
|---|---|
| ER-08 pickle/`torch.load` trust | Demonstrating it requires constructing a payload; prohibited. Prose only. |
| ER-09 CUDA comparison and GPU SVD | CUDA is not available on this host; MPS covered generically by SR-07 (SVD falls back to CPU there). |
| ER-10 baseline-mode confound | A property of two configurations of unavailable code, not of a numeric pattern. |
| ER-11 in-place hazards | Which tensors the real graph saves is unknowable without running it. |
| Whether any pattern is reached at runtime (all of ER-01..07) | Requires executing the audited script, out of scope. |
| Dropout/eval-mode mismatch (METHOD_AUDIT claim #17), radial-component loss under per-atom renormalization (claim #7), re-diffusion of already-noised input (3.3) | Not in the SR-03 list; method-level inferences needing a synthetic numeric study or execution. Not catalogued here to avoid unverified entries. |

## Known limits of this kit's own checks

- The "no pickle / `torch.load` text" test is a deny-list over a few strings (it also scans this register for fenced code that is not a plain test command, and for a few executable-payload tokens); it would not catch other vectors (for example other serialization modules), and nothing scans this register for such content. It is a tripwire, not a guarantee.
- The two `exec` calls in `failure_modes.py` (`exec("evaluated += 1; RuntimeError", ns)` and `exec("evaluated += 1; RuntimeError('never raised')", ns)`) use constant strings with no external input; they are the demonstration of ER-01 and are harmless.
- The register's prose is only partly coupled to the tests: `test_register_structure` pins the ER id set, the required fields per entry and a valid label per entry, but cannot check that the prose is correct. Correctness of classifications rests on the independent QA review.
- The torch import guard catches any `Exception` (not just `ImportError`) so a broken install (for example an ABI mismatch raising `OSError`/`RuntimeError`) yields skips rather than a module error; this is tested with simulated failing importers.

## How to reproduce

```
python3 -m unittest tests.toy_tests.test_failure_modes -v     # from the kit root
python3 -m unittest discover -s tests -v
```
Torch-dependent tests (ER-03, ER-04) report as **skipped**, never silently passed, when torch is not importable; a child-process test blocks the `torch` import and checks this. A further test checks that this file names every ER id and function, and that the four classification labels and the "does not establish" statements are present.

## QA status

All classifications above are the numerics teammate's proposals. Per the SR-03 verification clause, an independent QA reviewer must review each; this file is not marked QA-attested.
