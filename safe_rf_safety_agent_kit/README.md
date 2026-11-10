# SafeRFdiffusion — safety-replication agent kit

**Purpose:** Reproduce and independently audit the *safety research methods and claims* introduced in `audited-fork/safeRFdiffusion`, without silently assuming the fork is validated or building a new production protein-design engine.

This starter includes a source-grounded change audit, dependency-aware task plan, six Claude Code agents, one autonomous orchestration prompt, a one-line Ralph Loop command, a standard-library toy erasure demonstration, and regression tests. It has no external APIs and downloads no protein model weights.

## Verified source anchors
- Fork: https://github.com/audited-fork/safeRFdiffusion
- Upstream: https://github.com/RosettaCommons/RFdiffusion
- Shared ancestor: `e22092420281c644b928e64d490044dfca4f9175`
- Fork-only commits: `12d5426de27bc6411126262cf3f29bac3a0ce0c1`, `5cbd18a39c4607d65bdbf6457be3f79b27a6c3c1`
- Changed files: 8, including the new 691-line `rfdiffusion_erasure_teacher_student.py`.
- Verified by GitHub compare, 2026-11-09. The present upstream `main` is 36 commits beyond the merge base; compare against the merge base to isolate fork-only changes.

## First steps

1. Extract into a fresh repository and inspect `docs/FORK_AUDIT.md`.
2. From the repo root, run `python3 -m unittest discover -s tests -v` to check the mock-only starter.
3. Read `docs/BUILD_BLUEPRINT.md` for the task DAG and completion criteria.
4. Enable Claude Agent Teams in `.claude/settings.json`. Launch `claude` from the repository root. If you want unattended permissions, do so only in an isolated disposable environment without sensitive files or credentials.
5. Paste `docs/ORCHESTRATOR_PROMPT.md` into the main Claude Code session.
6. Once the initial team task is verified, paste the exact one-line `docs/RALPH_COMMAND.txt` (do not wrap the command in Markdown fences).

**Scope:** Source comparison; provenance; code and numerical audits; toy teacher–student learning; generic gradient and stability tests; independent safety/utility evaluation design; reporting and UI. Operational biological generation or protein-model fine-tuning is **not** an autonomous task in this kit. Any real-data or full-model work must be separately reviewed and scoped.

**Termination:** `SR-00` to `SR-16` must have factual evidence, independent QA, passing checks and commits; external scientific claims remain labeled unvalidated until independently supported.

`docs/SOURCE_SNAPSHOT.json` preserves the compare metadata for offline audit. External read-only repository browsing can be used to corroborate it; manual source verification (the `curl` commands in `docs/DIFF_EVIDENCE.md`) is a human activity outside the test suite entirely.

**Correction (SR-12 finding F5).** An earlier version of this line said the `ALLOW_EXTERNAL_NETWORK=false` environment flag "applies to the toy application". That was an overstatement: **no code in this kit reads that flag, or any of the other flags in `.env.example`.** They are declarative markers for a human reader, and setting them changes no behaviour. The kit's actual offline guarantees are structural, not flag-driven — `src/toy/` is standard-library only and imports no network module (enforced by `scripts/lint.sh` and `tests/toy_tests/test_scripts.py`), `scripts/run_tests.sh` runs the suite under a socket guard that makes connections and DNS lookups raise, and no model weights exist anywhere in the tree. See `docs/CLEAN_CLONE.md` for the full statement.

## Offline CI, scripts and clean-clone check (SR-15)
`./scripts/lint.sh`, `./scripts/run_tests.sh --expect none --twice` and `python3 scripts/demo.py` need only Python 3.12+ and no network or credentials. See `docs/CLEAN_CLONE.md` for exact steps, expected test/skip counts and how to read skips. The demo output is a toy tooling check, not evidence about RFdiffusion or any real capability.
