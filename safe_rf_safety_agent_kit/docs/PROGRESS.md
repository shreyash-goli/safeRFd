# Agent progress journal

Durable, append-only record. A task is marked `[x]` in `docs/BUILD_BLUEPRINT.md` **only** after an
independent QA agent attested its acceptance criteria. "Implemented, pending QA" is a distinct and
weaker state, recorded as such.

## Standing limitations (apply to every entry)
- Nothing in this kit measures, demonstrates or implies a reduction in hazardous biological design
  capability. Toy results are synthetic, non-biological numeric exercises.
- No model weights, protein structures, biological datasets or RFdiffusion inference runs are used.
- SR-17 is deliberately outside autonomous scope and remains blocked pending explicit human review.

## Orchestration note (2026-11-09)
The `.claude/agents/*.md` definitions did **not** register as spawnable agent types in this session;
the harness exposed only its built-in types and rejected `fork-auditor`, `toy-researcher`, etc.
Teammates were therefore spawned as real parallel background agents of the generic type, each
carrying its charter text verbatim plus explicit file-ownership and no-commit rules. Parallelism is
genuine; the named-agent-type mechanism is not available here. Commits are serialized by the
orchestrator alone.

The kit was initialized as its own git repository (`git init` at
`safe_rf_safety_agent_kit/`) rather than committing into the surrounding RFdiffusion working tree,
per README step 1 and to avoid writing to that repo's `main`. No remote is configured; nothing is pushed.

---

## SR-00 — Scaffold, version control, provenance

- **Task ID and date:** SR-00, 2026-11-09
- **Assigned agent and file ownership:** orchestrator (repo init); QA teammate (read-only review)
- **Status: PASS** — QA-attested, marked `[x]`
- **Files changed:** initial commit of 20 files (docs, `.claude/agents/`, `src/toy/erasure_demo.py`,
  `tests/test_toy.py`, `.gitignore`, `.env.example`)
- **Evidence and source refs:** all required docs present and non-empty in commit `f7eb976`;
  `docs/SOURCE_SNAPSHOT.json` parses and lists 8 changed files / 2 fork commits summing to +914/−138.
- **Commands actually run and results:**
  - `python3 -m unittest discover -s tests -v` → `Ran 4 tests` / `OK` (Python 3.12.4)
  - `git log --oneline`, `git show f7eb976 --stat` → 20 files, 380 insertions, single commit
- **Independent QA verdict and test log:** **PASS**. QA re-derived the toy arithmetic by hand and
  confirmed the assertions are non-vacuous: `toy_target((3,1),(1,2), s=0.5)` = `(1−0.5·2, 2−0.5·(−1))`
  = `(0.0, 2.5)`; `masked_mse((3,9),(1,0),(T,F))` = `(3−1)²/1` = `4.0`. QA audited every doc for
  safety-claim language and found only negations/caveats — no sentence asserts the fork is safe or
  validated. QA confirmed `.gitignore` excludes `.env` and `*.pt/*.pth/*.ckpt`, and `.env.example`
  holds only non-secret flags.
- **QA defects raised, and resolution by the orchestrator:**
  - **D1 (significant):** `python3 -m unittest discover -s tests` silently discovers **zero** tests in
    a `tests/` subdirectory lacking `__init__.py`, and adding `tests/toy/__init__.py` makes the test
    package shadow the `src/toy` source package (`ModuleNotFoundError: No module named
    'toy.erasure_demo'`). QA reproduced this in a scratch copy of `f7eb976`. The SR-04 builder hit the
    same collision and worked around it by appending to `__path__`. **Resolved structurally:** test
    package renamed `tests/toy/` → `tests/toy_tests/`, the `__path__` hack deleted, and an explicit
    `src/toy/__init__.py` added. Verified below. `.claude/agents/toy-researcher.md` updated to own
    `tests/toy_tests/`.
  - **D2 (minor):** `.gitignore` lacked weight/structure formats. **Resolved:** added
    `*.safetensors`, `*.bin`, `*.npz`, `*.pdb`, `*.cif`.
  - **D3 (minor, deferred to SR-05/SR-06):** `masked_mse` does not check finiteness of masked-out
    elements, and `toy_target`'s negative/non-finite `strength` and length-mismatch branches are
    untested. Assigned forward, not silently closed.
- **Remaining limitations:** the suite is 4 trivial contract tests; passing says nothing about
  RFdiffusion. QA could not re-verify the GitHub figures offline (done independently in SR-01).
- **Git commit SHA:** `f7eb976` (scaffold); integration fixes in the milestone commit below.
- **Next eligible task:** SR-02 (needs SR-01), SR-05 (needs SR-04).

---

## SR-01 — Fork-only diff evidence matrix

- **Task ID and date:** SR-01, 2026-11-09
- **Assigned agent and file ownership:** fork-auditor teammate; owns `docs/DIFF_EVIDENCE.md` only
- **Status: IMPLEMENTED, PENDING INDEPENDENT QA** — blueprint checkbox stays unchecked
- **Files changed:** `docs/DIFF_EVIDENCE.md` (new, 129 lines); orchestrator relabel of
  `docs/SOURCE_SNAPSHOT.json`
- **Evidence and source refs:** six live GitHub API calls, all HTTP 200, with sha256 of each saved
  body recorded in the document.
  - Merge-base compare `e22092…...audited-fork:main`: `status=ahead`, `ahead_by=2`, `behind_by=0`,
    `total_commits=2`, 8 changed files.
  - Reverse compare `audited-fork:main...main`: `status=diverged`, `ahead_by=36`, `behind_by=2`,
    same merge base — i.e. the "36 behind" figure is a *different comparison*, not a contradiction.
    This distinction is the methodological core of SR-01.
  - Per-commit: `12d5426` (2025-10-21) touches all 8 files, +902/−138, creating the new script at 679
    lines; `5cbd18a` (2025-10-23, message "additions") touches only that script, +27/−15.
    679 + 27 − 15 = 691 reconciles the per-commit and net views.
  - No test, benchmark, evaluation-harness or weight file appears in the fork-only diff (verified by
    enumerating the 8 `diff --git` headers and grepping the 1342-line diff, not by copying the prior
    claim). The only `.pt` strings are runtime literals inside the new script, including a hardcoded
    `models/Base_ckpt.pt` input path.
- **Orchestrator independent re-verification (not delegated):** re-fetched both commit objects and the
  reverse compare directly. Confirmed `12d5426` stats `{total:1040, additions:902, deletions:138}`,
  8 files, script `added 679 0`; `5cbd18a` stats `{total:42, additions:27, deletions:15}`, 1 file,
  script `modified 27 15`; reverse compare `diverged ahead 36 behind 2`, merge base `e2209242…`.
  All match the teammate's report exactly.
- **Defect found and fixed:** `docs/SOURCE_SNAPSHOT.json` carried `behind_by: 36` adjacent to
  `ahead_by: 2` as though both came from one comparison. Replaced with
  `behind_by_vs_merge_base: 0`, `behind_by_vs_upstream_main: 36` and an explanatory
  `behind_by_field_note`. An orchestrator follow-up note was appended to `docs/DIFF_EVIDENCE.md` so
  the original finding and its resolution both remain legible.
- **Remaining limitations:** API calls were unauthenticated (rate limits may affect re-runs); the
  "36" is time-varying as upstream advances; the compare pinned the branch name `main`, so a later
  fork push would change results — the commit SHAs pin the content. Semantics of what the changed
  code *does* are deliberately deferred to SR-02.
- **Git commit SHA:** milestone commit below.

---

## SR-04 — Typed experiment schema, provenance, deterministic seeds

- **Task ID and date:** SR-04, 2026-11-09
- **Assigned agent and file ownership:** toy-researcher teammate; owns `src/toy/schema.py`,
  `tests/toy_tests/`
- **Status: IMPLEMENTED, PENDING INDEPENDENT QA** — blueprint checkbox stays unchecked
- **Files changed:** `src/toy/schema.py`, `src/toy/__init__.py`, `tests/toy_tests/__init__.py`,
  `tests/toy_tests/test_schema.py`
- **Evidence:** standard-library only (no numpy/torch), so a clean clone needs no installs.
  Public API: `EvidenceClass` (SOURCE_OBSERVED / HYPOTHESIS / TOY_RESULT / NOT_VALIDATED / UNKNOWN),
  `MetricValue` (`.measured()` / `.unmeasured(reason)`, `.render()`), `RunProvenance`,
  `ExperimentRecord` (`to_json` / `from_json` / `content_hash`), `make_rng`, `derive_seed`,
  `current_python_version`, `SCHEMA_VERSION`.
  - `toy_only=False` is rejected at construction, so the schema is structurally unable to record a
    non-toy run.
  - **Missing evidence is distinct from zero:** an unmeasured metric has `value is None`, renders as
    `UNKNOWN`, is unequal to `measured(0.0)`, survives a JSON round-trip distinctly, and changes
    `content_hash` if swapped for a real `0.0`. This is an explicit acceptance test.
- **Commands actually run and results:** `python3 -m unittest discover -s tests -v` → `Ran 27 tests`
  / `OK` (4 pre-existing + 23 new), after the orchestrator's D1 restructure. Re-verified from a cold
  cache with `__pycache__` removed, and cross-checked under `python3 -m pytest -q tests` → `27 passed`.
- **Points a reviewer should scrutinize (self-reported by the builder, forwarded to QA unresolved):**
  strict float metrics (`measured(1)` and `measured(True)` raise rather than coerce); unmeasured
  metrics require a non-blank reason; records are not `hash()`-able (use `content_hash()`); only
  `YYYY-MM-DDTHH:MM:SSZ` timestamps are accepted; **nothing prevents a toy record from being labelled
  `SOURCE_OBSERVED`** — that gap must be closed by the SR-14 claim ledger or caught by QA; and
  `to_dict()` emits a fixed label string whose content is required to be present but is not validated.
- **Remaining limitations:** schema correctness is unreviewed until QA runs; no downstream consumer
  exists yet.
- **Git commit SHA:** milestone commit below.
