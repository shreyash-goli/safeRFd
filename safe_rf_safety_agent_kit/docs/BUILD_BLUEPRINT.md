# Safety replication and audit blueprint — task DAG

## Completion semantics
All tasks begin unchecked. An agent may mark `[x]` only after actual commands ran, independent QA passed, and evidence was appended to `docs/PROGRESS.md`. Only the orchestrator integrates and commits in a shared worktree. Tasks may run concurrently if all dependencies are satisfied and files do not overlap.

## Foundation + fork audit
- [x] **SR-00** — Scaffold project, version control, scripts, README; preserve fork audit provenance. **Depends:** none. **Verify:** `python3 -m unittest discover -s tests -v`; `git status`; docs exist.
- [x] **SR-01** — Recheck the exact fork-only diff against shared ancestor; produce a filename/commit evidence matrix with source URLs and SHA. **Depends:** SR-00. **Verify:** `docs/DIFF_EVIDENCE.md` enumerates all 8 changed files, 2 commits; reviewer independently confirms counts. No unexplained changes.
- [x] **SR-02** — Produce method-level architecture audit: teacher, student, loss, masking, checkpoints, config, baseline differences; mark claims as SOURCE/INFERENCE/UNKNOWN. **Depends:** SR-01. **Verify:** traced citations to source sections; no unverified safety claims.
- [x] **SR-03** — Produce error/uncertainty register: gradient/NaN/empty-mask/cross-device/baseline-mode concerns with reproducible generic tests or static evidence. **Depends:** SR-02. **Verify:** independent QA reviews every issue classification.

## Safe computational-method replication (synthetic non-biological only)
- [ ] **SR-04** — Formalize strict typed experiment schema, run provenance and deterministic seeds. **Depends:** SR-00. **Verify:** JSON/typed validation tests include invalid inputs and missing evidence.
- [x] **SR-05** — Implement an abstract teacher–student demo on small 2D numeric arrays. Keep all examples non-biological. **Depends:** SR-04. **Verify:** unit tests show deterministic outputs, frozen teacher and mutable student state.
- [x] **SR-06** — Implement generic stability checks for finite values, masked losses, empty-mask errors and gradient-validity assertions. **Depends:** SR-05. **Verify:** adversarial numeric unit cases fail safely.
- [x] **SR-07** — Write non-in-place numerical operations and optional device/precision comparison tests for generic tensors; do not modify or run RFdiffusion inference. **Depends:** SR-05. **Verify:** tests demonstrate behavior, document optional GPU skips.
- [x] **SR-08** — Add toy checkpoint metadata, provenance hashes and safe reload (no untrusted pickles). **Depends:** SR-05. **Verify:** round-trip and corrupted-checkpoint tests; no real protein weights.

## Evaluation methodology
- [x] **SR-09** — Design an independent safety/utility benchmark protocol with pre-registered hypotheses, retained-utility criteria and uncertainty. **Depends:** SR-02, SR-04. **Verify:** `docs/EVALUATION_PROTOCOL.md` specifies controls, disconfirming cases, confidence intervals, and evidence thresholds; do not fabricate measured results.
- [ ] **SR-10** — Implement generic synthetic benchmark scoring and confidence interval reporting; avoid actual biological sequence generation or target optimization. **Depends:** SR-06, SR-09. **Verify:** statistical test fixtures and repeatability.
- [ ] **SR-11** — Implement neutral robustness probes (seeds, benign numeric input shifts, missing inputs, numerical stability). **Depends:** SR-10. **Verify:** immutable scorecards; no claims based on single examples.
- [ ] **SR-12** — Independent QA review of method fidelity, unknowns and risk of incorrect safety claims. **Depends:** SR-03, SR-11. **Verify:** explicit PASS/FAIL/BLOCKED report, reproducible commands.

## Productized research dashboard + release
- [ ] **SR-13** — Build local experiment dashboard showing source-diff inventory, toy training curves, benchmark scorecards and uncertainty labels. No biological design generator/UI. **Depends:** SR-08, SR-10. **Verify:** smoke test; missing results render as UNKNOWN, not 0.
- [ ] **SR-14** — Implement human review of claims and immutable audit log for transitions: DRAFT -> REVIEWED -> SUPPORTED or UNSUPPORTED. **Depends:** SR-13. **Verify:** duplicate event/idempotency and invalid transition tests.
- [ ] **SR-15** — Add deterministic CI, lint/test scripts, dependency pinning, offline demo and clean-clone instructions. **Depends:** SR-12, SR-14. **Verify:** complete offline regression suite passes.
- [ ] **SR-16** — Final independent QA, claim-evidence matrix, limitations, screenshot/demo, release note. **Depends:** SR-15. **Verify:** all accepted tasks supported; no ungrounded statement that RFdiffusion is 'safe'; reproducible demo passes.

## Separate human review gate (not part of autonomous loop)
- [ ] **SR-17** — Decide whether any real RFdiffusion model run, dataset use, or biological model tuning is appropriate. **Depends:** SR-16 + explicit human review. **Do not auto-start.** No real model weights, PDB training, synthesis, or protein generation are part of SR-00–16.

## Definition of done
1. Source-specific audit identifies both fork-only commits and all changed files.
2. Toy methodology is reproducible without API keys, external model weights or biological training data.
3. Generic error handling and numerical correctness tests pass.
4. Independent evaluation methodology distinguishes measured outcomes from conjecture.
5. Dashboard shows source provenance and uncertainty.
6. Every verified task has QA evidence and a descriptive commit.
7. SR-17 stays blocked pending explicit review; completion signal is for the audit/toy-replication system only.
