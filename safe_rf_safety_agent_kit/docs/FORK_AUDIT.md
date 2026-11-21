# Source-grounded fork audit

**Audit date:** 2026-11-09
**Fork:** https://github.com/audited-fork/safeRFdiffusion
**Upstream:** https://github.com/RosettaCommons/RFdiffusion
**Common ancestor:** `e22092420281c644b928e64d490044dfca4f9175`
**Fork-only commits:** `12d5426de27bc6411126262cf3f29bac3a0ce0c1` ("Add concept erasure training with fixes ... gradient is high and needs to be looked at"), `5cbd18a39c4607d65bdbf6457be3f79b27a6c3c1` ("additions").

**M1 — HOW TO READ THIS FILE, AND WHAT GRADES ITS CLAIMS.** `CLAUDE.md` names this document source of
truth #1, and it is the shortest, so it is where a reader starts. It is written as plain prose and carries
**no label vocabulary**, while `docs/METHOD_AUDIT.md` grades all 27 of its claims
**SOURCE OBSERVED / INFERENCE / UNKNOWN** (12 / 6 / 9) and `docs/ERROR_REGISTER.md` grades each error
**CONFIRMED-IN-SOURCE / PATTERN-DEMONSTRATED / STATIC-ANALYSIS-ONLY / UNKNOWN-NEEDS-EXECUTION**. This file is
therefore WEAKER THAN THE REGISTERS IT SUMMARISES, not stronger: where the two differ, the graded document
wins. In particular, **"What has evidence in source" below is SOURCE OBSERVED throughout — statements about
what the code says, never about what it does.** No code in the fork was executed, by anyone, at any point in
this audit. The six "potential correctness concerns" are the graded registers' subjects, not findings about
runtime behaviour, and item 1's *"may leave `loss` unset"* is INFERENCE (`METHOD_AUDIT.md` row 13), as is
every statement about gradient flow (rows 14-15).

**Method:** GitHub compare `RosettaCommons/RFdiffusion` at shared ancestor versus `audited-fork:main`. Do *not* compare fork's old base directly with latest upstream `main` and label unrelated newer upstream commits as fork differences. GitHub reports fork 2 ahead / 36 behind upstream main as of audit. **M2: the 36 is time-varying** — it counts upstream's movement since the shared ancestor and grows with every upstream commit, so "as of audit" dates it without saying it will drift. `docs/DIFF_EVIDENCE.md:27` grades it **UNKNOWN**. The 2-ahead figure, the 8 changed files and the ancestor do not move.

## Exact changed-file inventory
| Path | Add | Delete | Classification | Observation |
| --- | ---: | ---: | --- | --- |
| `rfdiffusion_erasure_teacher_student.py` | 691 | 0 | Main safety-method attempt | Frozen teacher conditional/unconditional outputs, trainable student, erasure-target computation, optimizer, checkpoints, plots. |
| `config/inference/base.yaml` | 1 | 1 | Configuration | `model_runner` changed from `SelfConditioning` to `default`. |
| `rfdiffusion/diffusion.py` | 13 | 6 | Gradient/runtime | Changes use of autograd in diffusion coefficient calculation. |
| `rfdiffusion/inference/model_runners.py` | 37 | 8 | Gradient/runtime | Adds gradient-enabled sampler path and tensor/device handling; defines a Gumbel-softmax helper. |
| `rfdiffusion/inference/utils.py` | 67 | 56 | Geometry/runtime | Revises alignment using PyTorch and adjusts tensor/CPU/GPU conversions. |
| `rfdiffusion/kinematics.py` | 33 | 38 | Gradient/numerics | Reduces some in-place mutation; changes geometry calculations. |
| `rfdiffusion/util.py` | 71 | 28 | Gradient/numerics | Changes angle/vector utility behavior and numerical handling. |
| `rfdiffusion/util_module.py` | 1 | 1 | Minor runtime | Small implementation adjustment. |

## What has evidence in source
- An attempted Genie-style, teacher/student concept-erasure process is in code.
- Teacher models are frozen; a student is optimized.
- The student is compared against an adjusted target based on differences between teacher conditioned and unconditioned predictions.
- Training reports loss, gradient norms and saves checkpoints.
- Several upstream operations were modified to enable gradient propagation.
- The first fork commit itself acknowledges high gradients still needing investigation.

## What is **not** established
- No new benchmark/test files were present in the fork-only comparison.
- No empirical before/after evidence for reduced hazardous biological design capability was located in the changed files.
- No demonstration of benign-design utility preservation, external validation, calibration or robustness was provided by these two commits.
- No validated safety-modified model weights were added in the fork-only diff.
- The example in `main()` is an ordinary helix-motif scaffolding sample, not evidence of a biosecurity evaluation.

## Potential correctness concerns that require independent investigation
1. Training code handles an empty mask with `else: RuntimeError` rather than `raise RuntimeError(...)`; this does not actually raise an exception and may leave `loss` unset.
2. Two vital autograd assertions in the training script are commented out; gradient presence is not an enforced acceptance gate.
3. Some tensor-to-NumPy conversions explicitly detach, so end-to-end gradient propagation must not be inferred from PyTorch use elsewhere.
4. The sample loss and masking semantics need dimension/normalization review before drawing conclusions.
5. The default inference model runner changed; baseline-equivalence tests are needed to distinguish safety effects from unrelated configuration effects.
6. Large gradients were explicitly noted by the author; no demonstrated convergence or safety outcome follows from saved training curves alone.

## Interpretation
The repository is a proof-of-concept *method attempt* with training-enabling changes. It is not evidence of a successfully validated safer protein design system. The build plan targets replication of the safety audit and neutral computational-method properties, not autonomous biological capability development.

## Verification references
- https://github.com/audited-fork/safeRFdiffusion/commit/12d5426de27bc6411126262cf3f29bac3a0ce0c1
- https://github.com/audited-fork/safeRFdiffusion/commit/5cbd18a39c4607d65bdbf6457be3f79b27a6c3c1
- https://github.com/audited-fork/safeRFdiffusion/blob/main/rfdiffusion_erasure_teacher_student.py
