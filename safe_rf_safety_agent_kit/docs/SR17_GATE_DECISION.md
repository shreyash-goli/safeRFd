# SR-17 — human-review gate decision: whether to attempt a real model run

**Task (`docs/BUILD_BLUEPRINT.md:32`):** *"Decide whether any real RFdiffusion model run, dataset use,
or biological model tuning is appropriate. **Depends:** SR-16 + explicit human review. **Do not
auto-start.** No real model weights, PDB training, synthesis, or protein generation are part of
SR-00–16."*

**What this file is.** SR-17's deliverable is a **decision**, not a run. This file is that decision,
written to be countersigned. It is the only task in the project whose output is a judgement rather
than an artifact, and it is the only one that was never started autonomously.

**Author:** orchestrator, 2026-11-15. **Not countersigned.** **Status: DECIDED — DO NOT PROCEED at this gate.** Re-open conditions P1–P5 below are concrete and
checkable; three of the five are not software tasks.

---

## 1. What "proceeding" would concretely mean

Executing `rfdiffusion_erasure_teacher_student.py` from
`audited-fork/safeRFdiffusion` (the fork's only added file, 691 lines). From the source audit
(`docs/METHOD_AUDIT.md`, `docs/DIFF_EVIDENCE.md`) that requires, at minimum:

- real RFdiffusion weights at the script's hardcoded `models/Base_ckpt.pt` (diff line 1237) — a
  download `CLAUDE.md` prohibits in this loop;
- a GPU, and real protein structures: `main()` names `5TPN.pdb` with contig `1/A80-90`;
- a *choice of erasure target*, which the fork does not supply and which is the sensitive decision.

It would produce loss curves and `checkpoint_step_{step}.pt` / `checkpoint_final.pt`.

## 2. Why not — four reasons, each sufficient alone

### R1. The stated dependency is unmet

SR-17 depends on SR-16. SR-16 returned **FAIL** on its clause 1 and is deliberately unmarked
(`docs/SR16_AUDIT_REPORT.md` §0). **This reason is time-limited and has partly expired**: `scripts/mutate.py` and `scripts/mutants.json` are now tracked, and mutation results are re-derivable from a clone for the first time in the project's history. The journal's ~265 historical kill claims remain unreproducible and no harness can retroactively make them otherwise. R2–R4 are not time-limited and do not expire with any amount of work inside this repository.

### R2. A run would not answer the question, and would manufacture a quotable artifact

`docs/METHOD_AUDIT.md` rows 19, 20 and 21 — *selective unlearning*, *benign utility retained*, *the
method is safe* — are **UNKNOWN with no evidence of any kind**. What each needs is stated in the row:
pre-registered capability measurements on held-out cases with controls, utility metrics with
confidence intervals against a baseline, plus external validation and adversarial testing.

A training run supplies **none** of that. The fork adds no tests, no benchmark, no evaluation harness
(`docs/DIFF_EVIDENCE.md` §5, derived by enumerating all 8 `diff --git` headers). `CLAUDE.md` states
the rule directly: *"A concept-erasure training run is not evidence of selective unlearning or
safety."*

So the output of proceeding today is a checkpoint with no interpretation attached — and a checkpoint
that exists invites exactly the claim this kit was built to refuse. That is a worse epistemic position
than having nothing.

### R3. Six unresolved source defects would be measured instead of the method

From `docs/METHOD_AUDIT.md` and `docs/FORK_AUDIT.md`, all SOURCE OBSERVED or INFERENCE:

| # | Defect | Row |
|---|---|---|
| 1 | Empty-mask branch is a bare `RuntimeError` **name**, which does not raise; `loss` is then unset → `UnboundLocalError` | 13 |
| 2 | Both autograd assertions are commented out; that gradient reaches student parameters is asserted only by a commit message | 14, 15 |
| 3 | Magnitude renormalization replaces `-eta*d` with `‖u‖(t_hat - u_hat)`: origin-dependent, can change direction, can flip sign through the origin | 7, 8 |
| 4 | Loss divisor is `M` while `42M` elements are summed | 9 |
| 5 | Mask is built from `motif_mask` with no inversion, while the comment calls it the scaffold mask | 11, 12 |
| 6 | `config/inference/base.yaml` changes `model_runner` from `SelfConditioning` to `default`, confounding any comparison with upstream | 22 |

The fork's own first commit message says the gradient *"is high and needs to be looked at."* Running
code with six open defects measures the defects. Fixing them first changes the method under audit,
which is a separate decision with its own write-up.

### R4. The gate's real subject is not a software question

Choosing an erasure target, specifying the held-out evaluation set, and deciding who may read the
result are institutional judgements with a named accountable human. `CLAUDE.md` forbids
*"pathogen/toxin design targets"* and *"biological optimization examples"* precisely because naming
the target **is** the sensitive act — it does not become safe by being embedded in a safety project.
No amount of work inside this repository converts that into an autonomous call, and a go-ahead typed
into a terminal is not the review the gate names.

## 3. What would change the answer — P1 through P5

| | Precondition | Kind |
|---|---|---|
| **P1** | SR-16 clause 1 at PASS: F17-R closed by a tracked harness, every mark's evidence re-derivable from a clone | software; in progress |
| **P2** | A pre-registered evaluation instantiating `docs/EVALUATION_PROTOCOL.md` §§4–8 on real metrics, frozen before any run — including the `eta=0` control arm and the four-arm design of `METHOD_AUDIT.md` §8 to deconfound the runner change | software + design |
| **P3** | The six R3 defects resolved, or accepted in writing with the method's behaviour restated accordingly | software + author |
| **P4** | A named human owner for the erasure target and held-out set, under institutional biosecurity review outside this repository | **not software** |
| **P5** | Provenance and loading: checkpoint provenance metadata (row 23), the `student_model_state_dict` vs `model_state_dict` key mismatch (row 24), `weights_only=True` loading of untrusted checkpoints (row 25) | software |

P1, P2, P3 and P5 are tractable here. **P4 is not, and it is the binding one.**

## 4. What is available instead, today, with no model and no weights

The mechanism rows do **not** need a real model, because they are questions about arithmetic and
wiring rather than about biology: rows 7, 8, 9, 13, 14, 15, 24 are all answerable against a generic
stand-in with the same structure, which is what `src/toy/` is. Several already carry toy evidence
(SR-06 for gradient-validity assertions, SR-08 for provenance metadata, and
`teacher_student.erasure_target(rescale=True)` for the magnitude-rescale algebra). **Closing out the mechanism rows is the highest-value remaining work
that does not touch this gate**, and it is strictly more informative than a run that nobody can
interpret.

## 5. Countersignature

This decision is a recommendation to the human reviewer the task names. It is not final until signed.

```
Reviewer: ______________________    Date: ____________
[ ] Concur — DO NOT PROCEED; re-open on P1–P5
[ ] Dissent — proceed, with the following authorization and scope: ____________
```

**Nothing in this file asserts that the audited method works, fails, is safe, or is unsafe.** It
asserts only that a run today could not tell anyone which.
