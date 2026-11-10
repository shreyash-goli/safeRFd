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
- After logic changes, run the **module suites your change touches**, plus any module that imports
  them: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python3 -m unittest tests.toy_tests.test_<module>`.
  The **orchestrator** runs the full suite (`./scripts/run_tests.sh`) before each commit; an
  individual owner is not expected to, and should not when other owners are working in the tree.
  *(Reconciled after a builder flagged the conflict: this file used to require
  `python3 -m unittest discover -s tests -v` — the whole suite — while task briefs forbade it. The
  briefs were right for owners and this file was right for the orchestrator, and a builder had to
  guess which to obey. Reason the full suite is the orchestrator's job: it takes ~2 minutes of CPU
  but far longer in wall-clock under concurrency, and a shared-tree run while others are editing
  produces failures belonging to someone else's in-flight work — which was misattributed repeatedly
  in this project before the cause was found.)*
- **Never run anything else concurrently with a suite run, including your own repro or mutation
  scripts.** Doing so produced a phantom 16-failure spike that vanished on a serial re-run, and the
  same hazard class as the stale-`.pyc` incident. If you see a failure set you cannot explain,
  **re-run it serially before attributing it to anything.**
- Clear `__pycache__` and set `PYTHONDONTWRITEBYTECODE=1` for every measurement. Stale bytecode has
  produced both a false mutation survivor and a misattributed 10-failure spike here.
- For each feature: concrete proof and relevant negative/edge cases.
- A concept-erasure training *run* is not evidence of selective unlearning or safety.
- Include utility retention, uncertainty, and robustness in any claims framework.
