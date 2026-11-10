# SafeRFdiffusion Safety Replication — Claude Code operating rules

## Source of truth
1. `docs/FORK_AUDIT.md` describes independently verified repository differences.
2. `docs/BUILD_BLUEPRINT.md` is the task dependency graph, not a claim tasks are done.
3. `docs/PROGRESS.md` is the durable journal; reload it every iteration.
4. Original sources: `audited-fork/safeRFdiffusion` and ancestor `e22092420281c644b928e64d490044dfca4f9175` in `RosettaCommons/RFdiffusion`.

## Architecture and autonomy
- Main Claude Code session owns orchestration and integration. Spawn/coordinate named teammates; no overlapping file ownership.
- Planner/auditor: source-grounded diff audit; researcher: abstract toy experiments; numerical engineer: generic gradient tests; evaluation: benchmark design; UI/infra: audit dashboard and CI; QA: independent read-only review.
- Complete only eligible tasks whose dependencies pass. Implement acceptance tests first when possible. Keep one commit per verified task or coherent milestone. Main orchestrator serializes commits in a shared worktree.
- After each task: record task ID, evidence, commands, results, remaining uncertainty, and commit SHA; then resume next eligible work.
- Never mark a task [x] from a build alone; QA must independently attest to its acceptance criteria.
- On missing external access or data, report BLOCKED/UNKNOWN rather than inventing results.

## Safety and honesty
- This is a safety research and evaluation tool; no unrestricted biological design engine or unreviewed model training.
- No synthesis instructions, pathogen/toxin design targets, biological optimization examples, downloads of real generative-model weights, or unrestricted protein design inference in the autonomous loop.
- Use synthetic non-biological toy matrices and generic software tests for development.
- Never claim a trained safe checkpoint or measured reduction of biohazardous capability absent independent evidence.
- Distinguish source-observed facts, hypotheses, mock outputs, and empirical measurements.
- Do not disable tests or delete failing checks to claim completion.
- No credentials, secret files, network writes, deployment or remote pushes without explicit authorization. Running permission-bypass mode is only appropriate in a disposable isolated environment.

## Verification requirements
- Run `python3 -m unittest discover -s tests -v` after logic changes.
- For each feature: concrete proof and relevant negative/edge cases.
- A concept-erasure training *run* is not evidence of selective unlearning or safety.
- Include utility retention, uncertainty, and robustness in any claims framework.
