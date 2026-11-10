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
  - `toy_only` other than `True` is rejected at construction. **Corrected wording after QA
    challenge:** an earlier draft of this entry said the schema was "structurally unable to record a
    non-toy run". That was an overstatement of exactly the kind this kit exists to catch. `toy_only`
    is a *producer-asserted flag*, not a verified property of the data; it constrains nothing about
    the contents, and like any Python dataclass field it is bypassable — the orchestrator confirmed
    `object.__setattr__(prov, "toy_only", False)` succeeds. The honest claim is: the constructor
    rejects any value other than `True`.
  - **Missing evidence is distinct from zero:** an unmeasured metric has `value is None`, renders as
    `UNKNOWN`, is unequal to `measured(0.0)`, survives a JSON round-trip distinctly, and changes
    `content_hash` if swapped for a real `0.0`. This is an explicit acceptance test.
- **Commands actually run and results:** `python3 -m unittest discover -s tests -v` → `Ran 27 tests`
  / `OK` (4 pre-existing + 23 new), after the orchestrator's D1 restructure. Re-verified from a cold
  cache with `__pycache__` removed, and cross-checked under `python3 -m pytest -q tests` → `27 passed`.
- **Points a reviewer should scrutinize (self-reported by the builder, forwarded to QA unresolved):**
  strict float metrics (`measured(1)` and `measured(True)` raise rather than coerce); unmeasured
  metrics require a non-blank reason; `RunProvenance` and `ExperimentRecord` are not `hash()`-able
  (use `content_hash()`) while `MetricValue` *is* — orchestrator-verified by direct probe, correcting
  an earlier blanket claim that no record was hashable; only
  `YYYY-MM-DDTHH:MM:SSZ` timestamps are accepted; **nothing prevents a toy record from being labelled
  `SOURCE_OBSERVED`** — that gap must be closed by the SR-14 claim ledger or caught by QA; and
  `to_dict()` emits a fixed label string whose content is required to be present but is not validated.
- **Remaining limitations:** schema correctness is unreviewed until QA runs; no downstream consumer
  exists yet.
- **Git commit SHA:** milestone commit below.

---

## SR-01 — QA verdict: PASS (marked `[x]`)

- **Date:** 2026-11-09. **Reviewer:** independent QA teammate, read-only.
- **Independent QA evidence:** QA re-ran every GitHub API call itself (all HTTP 200, no rate
  limiting), re-derived the file table line by line, and recomputed all arithmetic rather than
  trusting the document: 8 files sum to +914/−138; 679 + 27 − 15 = 691; gross +929/−153 minus the 15
  re-edited lines = +914/−138; per-commit net 764 + 12 = 776 = 914 − 138. Re-fetched the diff and
  reproduced sha256 `fe3753f3…9e86` with 1342 lines and exactly 8 `diff --git` headers. Confirmed the
  six `test|benchmark|.pt|.pth|.ckpt|safetensors` grep hits are all runtime string literals inside
  the added script, at diff lines 710, 736, 1091, 1100, 1237, 1332 — no test, benchmark or weight
  file is present. Confirmed the orchestrator's `SOURCE_SNAPSHOT.json` relabel is accurate.
- **QA nits (accepted, not blocking):** `DIFF_EVIDENCE.md:8` labels local tool versions SOURCE
  OBSERVED though a reviewer cannot verify them remotely; `:35` "autograd-related lines changed" is a
  light interpretation labelled SOURCE OBSERVED (it is supported by `torch.autograd.grad`,
  `enable_grad` and `.detach()` appearing in the diff).
- **Remaining limitations:** unauthenticated API calls; the "36 behind" figure is time-varying; the
  compare pins branch names, so the commit SHAs are the durable anchor.
- **Status: PASS — blueprint checkbox marked `[x]`.**

---

## SR-02 — Method-level architecture audit

- **Task ID and date:** SR-02, 2026-11-09
- **Assigned agent and file ownership:** fork-auditor teammate; owns `docs/METHOD_AUDIT.md` only
- **Status: IMPLEMENTED, PENDING INDEPENDENT QA**
- **Files changed:** `docs/METHOD_AUDIT.md` (new) — 10 required sections plus a 26-row claims register
- **Source-confirmed findings (file:line in the fork script, sha256 `1fef6383…f17b`):**
  - L72 / L94: teacher parameters frozen, student trainable.
  - L218 / L243: both teacher outputs detached and computed under `no_grad`.
  - L261: `x_t_student.requires_grad_(True)` is applied to an *input*, not a parameter.
  - L286-287: `target = (1+η)·u − η·c`, a CFG-style extrapolation with weight −η. `main()` uses η=5,
    giving `6u − 5c`.
  - L290-297: the renormalization takes norms along `dim=-1` (per-atom radius from the origin).
    Unclamped it preserves the target's direction but restores `u`'s radius, and makes the result
    origin-dependent. **Corrected after QA:** an earlier draft of this line said the rescale removes
    "any purely radial component of the erasure displacement". QA showed that is mathematically
    wrong. Only the output *radius* equals ‖u‖; the displacement ‖u‖(t̂ − û) retains a radial
    component ‖u‖(cos θ − 1), which QA computed as −1.13 in a worked example. QA further showed the
    related claim that a purely radial `c − u` leaves no erasure signal fails at the edge: with
    `c = s·u` and `6 − 5s < 0` (i.e. s > 1.2), the target direction flips, giving `−u` — at s = 1.5,
    `u = (3,0,0)` maps to `(−3,0,0)`.
  - **L302-311 normalization mismatch, quantified:** the numerator sums 42·M elements
    (14 atoms × 3 coordinates × M motif residues) while the divisor is M — a constant factor of 42.
    With the `0.01` factor the loss is 0.42 × a true per-element MSE. The auditor marked the cause of
    the author's reported "high gradient" as UNKNOWN rather than attributing it to this factor.
  - L312-313: the bare `RuntimeError` does not raise, so `loss` is unbound at L325 (an
    `UnboundLocalError` on the empty-mask path, not a clean diagnostic error).
  - L279-280 / L322-323: both autograd assertions commented out. Critically, **even if re-enabled
    they would not prove parameter-level gradient flow**, because the input leaf alone makes
    `requires_grad` true.
  - L474 / L479: `torch.save` plus an unrestricted `torch.load`; no hash, SHA, seed or data
    provenance recorded.
  - L299-301: the mask-intent comment ends mid-sentence ("As such,") and is internally inconsistent;
    the code matches its "motif" wording rather than the `scaffold_mask` name. Intent **UNKNOWN**.
- **Orchestrator independent re-verification of the two most consequential new findings:**
  - *Checkpoint incompatibility — CONFIRMED.* The script saves under key `student_model_state_dict`
    (L461, L481); the ancestor loads `self.ckpt['model_state_dict']` with `strict=True`
    (`rfdiffusion/inference/model_runners.py:234`). Checkpoints written by this script cannot be
    loaded by the unmodified upstream sampler without an adapter.
  - *The config change is load-bearing, not cosmetic — CONFIRMED.* In the ancestor, both
    `Sampler.sample_step` (line 603) and `SelfConditioning.sample_step` (line 682) hardcode
    `with torch.no_grad():` (lines 631 and 721) and take no `enable_grad` argument. In the fork diff,
    the only `sample_step` to gain `enable_grad=False` / `torch.set_grad_enabled(enable_grad)` is the
    one at hunk `@@ -600,7 +616,7 @@`, i.e. **`Sampler`** (the `default` runner). `SelfConditioning`
    (ancestor lines 676-785) receives no hunk at all. **Wording corrected after QA:** an earlier
    draft said the switch was "necessary for any gradient to flow". The defensible claim is narrower
    — it was *necessary given the fork's chosen edit*. The fork only added `enable_grad` to
    `Sampler.sample_step`; `SelfConditioning.sample_step` takes no such argument, so calling it with
    one would raise `TypeError`, and `prev_pred` is assigned only at ancestor `model_runners.py:742`,
    so a fresh sampler at t<T would raise `AttributeError`. A different edit could in principle have
    enabled gradients in `SelfConditioning` instead. So the config change is load-bearing for *this
    implementation*, not a logical necessity. **It nevertheless remains a confound** for baseline
    comparison, because the two runners also differ behaviourally (self-conditioning affects
    sampling), so a measured difference cannot be attributed to erasure without a
    baseline-equivalence experiment.
- **Further auditor findings, all labelled INFERENCE and NOT independently re-verified by the
  orchestrator (flagged to QA for scrutiny):** possible mask-polarity inversion versus the ancestor
  `diffuse_pose` docstring (`diffusion.py:621`, True = NOT diffused) given `~motif_mask` at L203 and
  all-True at L228; the "unconditional" branch may not be unconditional (same contig, sampler-internal
  motif masks unchanged, and the two branches draw independent unseeded random samples); possible
  double-noising (L205 noises coordinates `sample_init` already noised); upstream gradient truncation
  via detach between blocks (`Track_module.py:415-457`); the persistent teacher (L68) being used only
  for `t_step_input` (L361) while up to four model copies are alive per step; `randint` excluding
  `t_step_input`; NaN × 0 remaining NaN in the masked loss; student in train mode vs teacher in eval
  with dropout present; `gumbel_softmax_sample` having no caller; and `util.py` returning (cos=1,
  sin=0) for invalid angles on every path.
- **Explicitly NOT established:** whether gradient actually reaches student *weights* (UNKNOWN — this
  is the author's own commit-message claim and cannot be settled from source text alone); that the
  gradient is large (rests solely on the commit message; no logs in the sources); which commit
  introduced the `0.01` factor.
- **Method note:** the auditor read ancestor text from local git objects in the surrounding
  RFdiffusion checkout. No claim depends on post-ancestor upstream code. The fork script's 691 lines
  match the diff's added lines byte for byte.
- **Remaining limitations:** nothing here was executed; no model was run; every dynamic claim remains
  UNKNOWN pending generic tests (SR-03/SR-06). Nothing in this audit says the method works, fails, or
  affects any real capability.

---

## SR-05 — Abstract teacher–student toy demo

- **Task ID and date:** SR-05, 2026-11-09
- **Assigned agent and file ownership:** toy-researcher teammate; owns `src/toy/teacher_student.py`,
  `tests/toy_tests/test_teacher_student.py`, `tests/toy_tests/test_erasure_demo_edges.py`
- **Status: IMPLEMENTED (after one orchestrator-ordered rework), PENDING INDEPENDENT QA**
- **Evidence:** standard-library only; 2D data as tuples of tuples. Frozen teacher enforced by a
  frozen dataclass over read-only mappings; mutable student updated by explicit gradient descent;
  `erasure_target` = `uncond − eta·(cond − uncond)`; opt-in magnitude rescale analogous to the
  source's clamped `[0.1, 2.0]` scale factor; analytic gradient returned alongside the loss for
  finite-difference checking in SR-06; `train()` emits an `ExperimentRecord` with `TOY_RESULT`.
- **Both loss normalizations are provided as a named, explicit choice**, defaulting to the correct
  `per_masked_element`. `per_mask_entry` is the toy analogue of the audited source concern and is
  documented as a *reproduction of an audited concern*, not as a bug "fixed" in RFdiffusion.
- **Orchestrator independent numerical verification (not delegated):** the inflation ratio between
  the two normalizations equals the row width *exactly* — measured 1.000000, 2.000000, 3.000000,
  5.000000, 8.000000 for widths 1, 2, 3, 5, 8. Separately confirmed `erasure_target` agrees
  bit-for-bit with the pre-existing `erasure_demo.toy_target`, and that `eta=0` returns `uncond`
  exactly. Note the real script's two `unsqueeze(-1)` calls mean its factor is the product of the
  trailing dims (42 per SR-02), not a single width.
- **Two defects the orchestrator caught on review and sent back; both fixed:**
  1. **False provenance timestamp.** Every record was stamped with a hardcoded
     `FIXED_TIMESTAMP = "1970-01-01T00:00:00Z"`. Writing a knowingly false timestamp into a
     provenance record is exactly the failure mode this kit audits for. Now `train()` takes
     `timestamp_utc: str | None`, defaulting to the real current UTC time; pinning is an explicit
     caller choice, and the trade-off (honest time vs reproducible `content_hash`) is documented.
  2. **Silent gradient ascent.** Only finiteness of `lr` was checked, so a negative learning rate was
     accepted and the loop maximised the loss while reporting a normal-looking history. Now
     `lr > 0` is enforced in both `train()` and `Student.step`, with a monotonic-non-increasing
     regression test that would have caught it.
- **Commands and results:** `python3 -m unittest discover -s tests -v` → `Ran 69 tests` / `OK`
  (also under `-W error`); `python3 -m pytest -q tests` → `69 passed`.
- **Known `erasure_demo.py` issues pinned by tests but deliberately NOT fixed (routed to SR-06):**
  `masked_mse` checks finiteness only of *selected* elements, so a NaN under a False mask is silently
  ignored; the mask accepts non-bool entries by truthiness.
- **Remaining limitations:** a toy structural analogue only. It reproduces the *shape* of an audited
  numerical concern on abstract numbers and says nothing about RFdiffusion, proteins, or safety.

---

## SR-04 — Re-work after QA FAIL

- **Date:** 2026-11-09. **Status: RE-IMPLEMENTED, PENDING QA RE-REVIEW.**
- **First QA verdict was FAIL.** QA used mutation testing — break a protection, check whether the
  suite notices — and found two tests that were **vacuous**:
  - the duplicate-JSON-key test fed input that would fail on *missing* keys regardless, so replacing
    the duplicate-key `raise` with `pass` left the suite green;
  - the NaN test passed even with the `parse_constant` hook removed, because `MetricValue`'s own
    finite check caught it first.
- **Other QA defects:** `_SHA256_RE`/`_TS_RE` used `$` and `\d`, accepting a trailing-newline sha256
  and full-width Unicode-digit timestamps; **`label` was never validated on `from_dict`**, so a
  record could carry `"VALIDATED SAFE"`, be silently normalised back by `to_dict()`, and still match
  the untampered `content_hash` — a provenance-laundering path in a kit whose purpose is to stop
  unsupported safety claims being presented as validated; unbounded seeds; `0.0`/`-0.0` comparing
  equal but hashing differently; and a weak `assertRaises(Exception)` frozenness test that survived
  removing `frozen=True` from `MetricValue`.
- **Design gap closed structurally rather than deferred:** `ExperimentRecord` now **rejects**
  `EvidenceClass.SOURCE_OBSERVED`, since a *run record* can never be a source observation. The enum
  member remains for SR-14 audit/claim records.
- **Builder re-work:** all of D1–D7 fixed, each accompanied by the specific mutation proving the new
  test is non-vacuous. Suite: 79 tests, passing under both unittest and pytest.
- **Orchestrator independent re-probe (8 attacks, all now rejected):** tampered `label`
  `"VALIDATED SAFE"` → rejected; `null` label → rejected; `from_json(t).to_json() == t` → True;
  `SOURCE_OBSERVED` run record → rejected ("belongs to audit/claim records, not run records");
  sha256 with trailing newline → rejected; full-width-digit timestamp → rejected; `seed=2**200` →
  rejected; duplicate key in otherwise-valid JSON → rejected; `-0.0` normalises to `0.0`.
- **Not self-certified:** these orchestrator probes do not substitute for QA. An independent QA
  re-review of SR-04 and a first review of SR-05 are in flight.

---

## SR-04 — QA verdict: PASS (marked `[x]`)

- **Date:** 2026-11-09. **Reviewer:** independent QA teammate, read-only.
- **Method:** mutation testing — 92 mutants applied one at a time against the full suite. 74 were
  caught. Of the 18 survivors, 4 were demonstrated *equivalent* mutants (redundant defence-in-depth
  layers) and the rest were in SR-05, not SR-04.
- **Every D1–D7 fix confirmed real and non-vacuous**, each killed by a specific mutant: duplicate-key
  hook removed; `parse_constant` removed; timestamp `re.ASCII` removed; SHA `fullmatch`→`match` and
  →`search`; label check removed; seed bound removed and `MAX_SEED` shifted by one in both
  directions, with `make_rng`, `derive_seed` and `RunProvenance` each losing their check separately;
  `-0.0` normalisation removed; `frozen=True` removed from each of the three classes individually;
  and the `SOURCE_OBSERVED` rule removed.
- **Regression sweep (QA's own probes):** `derive_seed` output always ≤ `2**64-1` across 2000 seeds;
  a record with seed `2**64-1` round-trips; `MetricValue(-0.0) == MetricValue(0.0)` with identical
  hashes; round-trip exactness held across 4 evidence classes × 6 `notes` variants (including `None`,
  whitespace, RTL unicode, emoji, a NUL byte and claim-like text) × 3 metric sets (empty, unmeasured,
  and extremes `5e-324` / `1e308` / `-0.0`) with a non-ASCII `name` — `from_json(to_json(r)) == r`,
  byte-identical text and identical hash in every case. Near-miss labels all rejected: trailing/
  leading space, trailing newline, zero-width space, Cyrillic `е`, lowercase, truncated prefix, and
  "not a safety claim" edited to "a safety claim". `dataclasses.replace` re-runs validation, so
  `replace(r, evidence_class=SOURCE_OBSERVED)` and `replace(prov, toy_only=False)` are both rejected.
- **Two follow-ups raised and fixed after the PASS:**
  - **S2 (defect):** `from_json` leaked `RecursionError` on deeply nested input
    (`"["*100000`), which is not a `ValueError`, breaking the module's documented contract for callers
    guarding untrusted input. Now caught and re-raised as `ValueError("invalid JSON: nesting too
    deep")`, with tests for both reproductions.
  - **S1 (test gap):** the bad-label test admitted a weakened `"TOY RESULT" in label` mutant, which
    would have allowed `"TOY RESULT ... validated safe"` — the exact claim-laundering path D4 closed.
    Eight near-miss labels added; the weakening no longer survives.
- **Accepted limitations (no code change possible or warranted):** free-text fields (`name`, `notes`,
  `code_version`, `python_version`, `run_id`) are unconstrained and can carry claim-like strings — no
  schema can prevent this, so the SR-14 ledger and all renderers must never treat them as evidence
  (now stated in the module docstring); `object.__setattr__` and instance `__dict__` writes bypass
  any freeze, as for any Python object; `float`/`str` subclasses are accepted; `deepcopy`/`pickle`
  fail on `mappingproxy` (pre-existing, not a regression); timestamps are accepted for any year
  0001–9999.
- **Status: PASS — blueprint checkbox marked `[x]`.** Schema tests 35/35 in isolation.

---

## SR-05 — Re-work after QA FAIL

- **Date:** 2026-11-09. **Status: RE-IMPLEMENTED, PENDING QA RE-REVIEW.**
- **QA verdict was FAIL (narrow).** All three acceptance properties (determinism, frozen teacher,
  mutable student) held under QA's own independent probes — QA wrote its own loss and central-
  difference implementation and found max analytic-vs-FD error 1.8e-10 across 5 random cases, and
  confirmed the normalization ratio equals the row width exactly for widths 1,2,3,4,5,7,8,13,50. The
  failure was that key behaviour was **unprotected by tests**:
  - **T1 (the serious one):** `train()`'s default `normalization` was untested. QA flipped the
    default to `per_mask_entry` — *the toy analogue of the audited normalization bug* — and all 79
    tests still passed. The recorded `grad_norm` was also untested; swapping L2 for L1 survived.
  - **T2:** the provenance `config` hash was untested; dropping `lr` or `normalization` from it
    survived, so two different configurations could share provenance inputs.
  - **T3:** `test_outputs_unchanged_by_training` **could not fail** — it compared `teacher_before`
    against `teacher_after`, both recomputed from the same object.
- **Fixes, each with the mutation proving the new test non-vacuous:** default normalization pinned
  (flipping it now fails two tests); `grad_norm` asserted to be the L2 norm of the recomputed
  gradient; config hash tested against a change in each of `steps`, `lr`, `eta`, `rescale`,
  `normalization`, `mask`, `teacher` and `x`; `test_outputs_unchanged_by_training` rebuilt around an
  explicit `Teacher` with hand-computed literal outputs and a deep-copied snapshot.
- **Disagreement recorded honestly:** the builder argues QA's `after = before` mutant is an
  *equivalent* mutant, since the teacher is structurally immutable and the two values can never
  differ. The orchestrator accepts this reasoning; the builder also added the stronger snapshot-based
  test QA was actually asking for, which does fail under a real mutation.
- **T4 defects fixed:** `rows=0`/`width=0`/`rows=True` and non-integer or negative `steps` now raise
  `ValueError` (`steps=0` allowed); `as_matrix([[10**400]])` raises a validation error rather than
  `OverflowError`; a diverging learning rate now reports "training diverged at step k (learning rate
  too large?)" instead of the misleading "grad must be finite and match params length", and a failed
  `Student.step` leaves parameters untouched; a `width`/`x` contradiction now raises instead of
  silently ignoring one. `TOY_LABEL` is imported from `toy.schema` so the two cannot drift.
- **`src/toy/erasure_demo.py` hardened to fail closed.** QA found the toy was **more lenient than the
  source it mimics**, which defeats its purpose: `masked_mse((1.0,2.0),(1.0,0.0),(0,"no"))` returned
  `4.0` because the mask accepted truthy non-bool entries and the string `"no"` selected; finiteness
  was checked only on *selected* elements, so a NaN under a False mask was ignored — whereas the
  audited source multiplies by the mask and `NaN * 0` stays `NaN` in torch, so the real code would
  propagate it. Also `toy_target(ToyPrediction((1e308,),(-1e308,)), 10.0)` returned `(-inf,)` from
  finite inputs. Now: strictly boolean mask entries required; finiteness checked on **all** elements;
  loss and target overflow raise; `bool` rejected as `strength`. The pinning tests in
  `test_erasure_demo_edges.py` were **converted, not deleted**, with a comment recording that the
  behaviour changed in the SR-05 rework following QA and why. The 4 original tests in
  `tests/test_toy.py` still pass unmodified.
- **Honest scope note now in the module docstring:** the toy uses a single Frobenius norm over the
  whole matrix, whereas the audited source takes per-atom norms along `dim=-1`. It is a structural
  analogue, not a numerical replica.

---

## SR-03 — Error and uncertainty register

- **Task ID and date:** SR-03, 2026-11-09
- **Assigned agent and file ownership:** numerics teammate; owns `docs/ERROR_REGISTER.md`,
  `src/toy/failure_modes.py`, `tests/toy_tests/test_failure_modes.py`
- **Status: IMPLEMENTED, PENDING INDEPENDENT QA**
- **Design:** 11 entries ER-01…ER-11, each with source location cross-referenced to
  `docs/METHOD_AUDIT.md`, a classification (CONFIRMED-IN-SOURCE / PATTERN-DEMONSTRATED /
  UNKNOWN-NEEDS-EXECUTION / STATIC-ANALYSIS-ONLY), severity with justification, a minimal executable
  reproduction **on abstract objects**, and an explicit statement of what it does *not* establish.
- **Demonstrated behaviour (orchestrator independently re-ran ER-01 and ER-04):**
  - **ER-01:** a bare `RuntimeError` statement does nothing; the later use of the unassigned variable
    raises `UnboundLocalError: cannot access local variable 'loss' where it is not associated with a
    value`. Confirmed `issubclass(UnboundLocalError, RuntimeError)` is **False**, so the pattern does
    not even produce the exception type it appears to name. A `raise` control gives
    `RuntimeError('empty mask')`.
  - **ER-04 — the audit's most important methodological claim, now empirically substantiated.**
    Across three graphs, `out.requires_grad` is `True` in **all three**, while the parameter gradient
    is `None` (severed by `detach`), `[0.0, 0.0]` (multiplied by zero), and `[1.0, 2.0]` (control)
    respectively; the *input* leaf has a non-zero gradient in all three. This is direct evidence that
    an assertion of the form `assert out.requires_grad` — which is what the fork's two commented-out
    checks at L279-280 and L322-323 would have done — **cannot distinguish a learning model from one
    whose parameters receive no gradient at all.**
  - **ER-05:** the normalization inflation factor equals the product of the trailing dims *exactly*,
    verified with `Fraction` to avoid floating-point ambiguity: `(14,3)`→42, `(2,)`→2, `(5,1,3)`→15,
    no trailing dims→1. The 42 matches SR-02's independent derivation.
  - **ER-02:** `0*nan` and `0*inf` are both `nan`; mask-by-multiplication sums to `nan` where
    selection-based masking gives `4.0`.
  - **ER-03:** a detached parameter's `grad` is `None` while the live one is `[1.0, 2.0]`.
  - **ER-06:** the two mask-polarity readings select disjoint complementary sets, giving losses `5.0`
    and `10.0` — a polarity error is **silent**, not a crash.
  - **ER-07:** raw gradient norms spanning 1e8 (50 to 5e9) all clip to a post-clip norm of 1.0, and
    `clip_grad_norm_` returns the *pre*-clip value `5000.0`. A clipped norm in a training log is
    therefore not evidence of a well-conditioned problem — consistent with the charter's rule not to
    claim stability from clipping.
- **ER-08 (`torch.load`/pickle trust) is prose-only by design.** No pickle payload was constructed or
  executed; a test asserts the module contains no pickle or `torch.load` text. Mitigation direction
  is deferred to SR-08.
- **ER-09 (cross-device) is UNKNOWN-NEEDS-EXECUTION:** no GPU is present. The register specifies the
  comparison SR-07 must add and that it must report *skipped*, never silently pass, without CUDA.
- **ER-10 (baseline mode)** cross-references SR-02's finding; **ER-11 (in-place mutation)** is
  static-analysis only.
- **Commands and results:** `unittest discover` → 149 tests, OK, 1 skipped; `pytest -q` → 148 passed,
  1 skipped. **With torch blocked** (scratch `sitecustomize.py` setting `sys.modules['torch']=None`;
  nothing uninstalled): 149 tests OK with 2 skipped, and `pytest -rs` 147 passed / 2 skipped — the
  torch-dependent ER-03 and ER-04 report as *skipped with a reason*, never as silent passes. A test
  runs a child process with torch blocked and asserts the skip wiring itself.
- **Stated limitation, prominent in the register:** demonstrating that a *pattern* misbehaves in
  isolation does **not** establish that the audited program misbehaves at runtime; that would require
  executing it, which is out of scope. The register also notes line numbers were taken from
  `METHOD_AUDIT.md` without re-reading the fork script.

---

## SR-06 — Generic stability validators

- **Task ID and date:** SR-06, 2026-11-09
- **Assigned agent and file ownership:** second numerics teammate; owns `src/toy/stability.py`,
  `tests/toy_tests/test_stability.py`
- **Status: IMPLEMENTED, PENDING INDEPENDENT QA**
- **Design:** `StabilityError(ValueError)` so existing `except ValueError` handling still works, with
  a distinct subclass per failure: `NonNumericError`, `NonFiniteError`, `ShapeError`,
  `MaskTypeError`, `MaskLengthError`, `EmptyMaskError`, `NormalizationMismatchError`,
  `GradientMismatchError`, `DegenerateGradientError`, `MissingGradientError`, `NoOpUpdateError`.
  Errors name the offending index or `(row, col)` and its value rather than only reporting that a
  problem exists. Standard library only.
- **Key guarantees:** masks accept only strict `bool` entries (`0`, `1`, `None`, truthy objects and
  numpy scalars are all rejected); an empty or all-False mask raises rather than producing a loss;
  `masked_mean_checked` raises unless the denominator is exactly `sum(mask) * width`, with a
  dedicated hint for the "off by the row width" case that mirrors the audited concern;
  `strict_masked_out=True` is the **default**, so a NaN hidden by a mask raises.
- **`check_gradient` is a real check, not decoration.** It rejects non-finite, identically-zero
  (including all-`-0.0`) and `None` gradients as *not evidence of a working gradient path*, rejects
  wrong-length gradients and callables that mutate their input, and documents the step-size/round-off
  trade-off and that it can fail a *correct* gradient if misconfigured. Verified failure paths at
  default tolerance (step 1e-6, rtol 1e-4, atol 1e-6) against `masked_mse_loss_and_grad` on a 3×2
  fixture (correct gradient passes, max abs error 8.7e-11): sign flip caught (−0.5125 vs +0.5125);
  ×2 scaling caught; a single coordinate offset by 0.5 caught; **the `per_mask_entry` width-inflated
  gradient caught**; all-zero, flat-function and all-`-0.0` gradients rejected as
  `DegenerateGradientError`; NaN/±inf rejected. A 0.1% perturbation passes at rtol 1e-2 and fails at
  rtol 1e-5, so the tolerance is load-bearing; a correct cubic gradient fails at `step=0.5`,
  demonstrating the documented misconfiguration limit.
- **`require_parameter_gradient`** is the explicit "this does not prove learning" guard: a `None`
  parameter gradient raises *even when a finite input gradient exists*, and says so in the message —
  the defensive counterpart to SR-03's ER-04 demonstration.
- **Honest limits recorded by the builder:** `check_gradient` can pass a wrong gradient whose error
  falls below `atol + rtol*|g|`; it checks a single point; a point with a genuinely zero gradient is
  rejected by design; numpy scalar mask entries are rejected, which is stricter than numpy-style code
  expects (a deliberate choice).
- **Stale-docstring defect caught by the orchestrator and fixed:** `stability.py` asserted that
  `erasure_demo.masked_mse` ignores masked-out non-finite values. That was true at `e436d93` but
  false after the SR-05 rework hardened it. Both docstrings now state the old behaviour as a
  historical fact about that specific commit and describe current behaviour correctly.
- **Commands and results:** `test_stability.py` 39/39; full suite `unittest discover` → 149 tests OK,
  1 skipped; `pytest -q` → 148 passed, 1 skipped.

---

## SR-02 — QA verdict: FAIL (minor revision required); rework in flight

- **Date:** 2026-11-09. **Reviewer:** independent QA teammate, read-only. **Blueprint checkbox stays
  unchecked.**
- **What QA independently confirmed:** the script hash `1fef6383…f17b`; that the 691 added diff
  lines are byte-identical to the script; the target algebra `(1+η)u − ηc` with `ETA = 5` (S:590,
  passed at S:658) giving `6u − 5c`; the empty-mask snippet raising `UnboundLocalError` on Python
  3.12.4; `NaN × 0 = NaN`; and that `clip_grad_norm_` returns the pre-clip norm (9.59 returned
  against 0.001 after clipping).
- **The factor of 42 is CONFIRMED and is derivable from source, not UNKNOWN.** `px0` is (L,14,3) via
  `A:model_runners.py:650` (`px0.squeeze()[:,:14]`, docstring A:613, same line in the fork at D:133);
  `allatom` returns (B,L,27,3) (`util_module.py:333-334`); `motif_mask` is (L,) so `scaffold_mask` is
  (L,1,1). Numerator sums 42·M slot elements against a divisor of M; numerically loss/MSE =
  0.41999998. Two caveats must be added: it assumes L > 1 (otherwise the squeeze collapses), and the
  14 are *slots*, not necessarily real atoms.
- **The input-leaf methodological claim is CONFIRMED** by QA's own four-case torch demonstration:
  `requires_grad` is necessary but not sufficient evidence of parameter-level flow; the commented-out
  assertions would catch only *total* disconnection and would miss partial coverage. The
  discriminating test is checking `p.grad` after `backward()`. This independently corroborates
  SR-03's ER-04.
- **Defects requiring revision (sent back to the builder):**
  1. **§3.2 item 2 is mathematically wrong** — "zero radial component by construction" is false; only
     the output *radius* equals ‖u‖, and the displacement ‖u‖(t̂−û) retains a radial component
     ‖u‖(cos θ−1), computed as −1.13 in QA's example.
  2. **§3.2 item 3 is wrong at the edge** — a purely radial `c−u` does *not* always leave no erasure
     signal: with `c = s·u` and `6−5s < 0` (s > 1.2) the direction flips to `−u`; at s = 1.5,
     `u=(3,0,0)` maps to `(−3,0,0)`.
  3. §9's claim that the `1e-8` sign convention differs is unsupported — `sqrt(clamp_min(1−cos²,0)+eps)`
     is equivalent to `sqrt(1−cos²+eps)` because cos is clamped.
  4. `th_dih_v` overstated — `nan_to_num` makes NaN inputs give (0,0), not (1,0); only `th_ang_v`
     returns (1,0) (D:526-527). Missing point: upstream `_preprocess` uses NaN in `alpha` to clear
     `alpha_mask` (A:565-566), so the change alters that model input.
  5. §3.4 imprecise — with an all-True mask `diffuse_pose` adds zero delta (A:diffusion.py:103), so
     `x_t_u` is the recentred, already-T-noised `sample_init` output, not noise-free.
  6. §6 overstated — the detach is at the *start* of each block, so each block's own parameters still
     receive gradient and the final block reaches `px0` directly; only the chain *across* blocks is
     truncated.
  7. §11 marks readable config values UNKNOWN; the ancestor `base.yaml` gives `p_drop: 0.15`, `T: 50`,
     `sidechain_input: False` etc. (checkpoint config may override). This also settles `randint`:
     with T=50, `t ∈ 1..49`.
  8. Claims-register label inconsistencies (#8/#13 SOURCE OBSERVED vs INFERENCE elsewhere; #9 needs
     the L>1 and placeholder caveats; #2 infers runtime behaviour from static flags; #26 calls the
     `main()` example "generic", which source cannot establish — it shows `5TPN.pdb` and "Alpha helix
     motif scaffolding" at S:618).
  9. Citation drift: `utils.py:500`→501; grad_norm S:385→S:384; D:333-335→D:335-337; D:21/49-54→
     D:22-23 and D:53-55; D:111-150 loose; the `prev_pred` grep misses A:740 and A:777 is
     `def symmetrise_prev_pred`; the "repository-wide grep" for a `gumbel_softmax_sample` caller was
     only over D and S; and **§9 mischaracterises hunk D:461-480 — the edit is to `dist_to_onehot`,
     with `xyz_to_bbtor` only appearing as hunk-header context.**
  10. Two omissions to add: the scheduler starts at `lr = 0` (`lr_lambda(0) = 0`), so the first
      optimiser step is a no-op; and `x_t_student` is a grad-requiring leaf that `_preprocess`
      modifies in place (the fork clones only in the `else` branch) — under `sidechain_input: True`
      the write would hit the leaf, though the default is False.
- **QA verdicts on the INFERENCE-only findings:** mask polarity inverted — *supported statically*
  (docstring A:diffusion.py:621 plus the sampler's own use at A:426/335, with `motif_mask` True at
  the motif and the script passing `~motif_mask` at S:203 and all-True at S:228); "unconditional"
  branch not unconditional — *supported*; double-noising — *supported* (resulting noise level
  unknown); detach truncation — *partly supported* (see defect 6); persistent teacher used only for
  `t_step_input` with four construction sites — *supported*; `randint` exclusion — *supported*;
  NaN×0 — *supported, demonstrated*; train-vs-eval dropout — *supported and stronger than stated*;
  `gumbel_softmax_sample` uncalled — *supported for D and S only*; `util.py` (1,0) — *partly
  supported* (see defect 4).
- **Both orchestrator-verified findings re-confirmed by QA**, with one wording correction accepted:
  the runner switch should be described as **necessary given the fork's chosen edit**, not
  "necessary for any gradient to flow" — calling `SelfConditioning.sample_step` with `enable_grad`
  would raise `TypeError`, and `prev_pred` is assigned only at A:742 so a fresh sampler at t<T would
  raise `AttributeError`, but a different edit could have enabled gradients there instead. QA also
  added that the upstream config loader reads `ckpt['config_dict']` inside a bare `try/except`
  (A:210-213) while the fork saves `config`, so config assembly would silently do nothing.
- **Orchestrator self-correction:** two statements in this journal were wrong and have been fixed in
  place above — the "removes any purely radial component" claim, and "necessary for any gradient to
  flow". Both originated in the orchestrator's own relay of the audit, not in QA.
- **Safety language:** QA found nothing asserting the method works, fails, or is safe. Two phrasings
  to soften were flagged ("partially undoes", and "false" verdicts in the claims register).
- **Unmeasured and still UNKNOWN (nothing was executed):** gradient flow to parameters, whether
  dropout fires, NaN/placeholder behaviour of `px0`, clamp trigger frequency, the effect of mask
  polarity, and the effect of the runner switch. Whether the 42 factor relates to the author's "high
  gradient" note is UNKNOWN; the factor itself is solid.

---

## SR-09 — Independent evaluation protocol

- **Task ID and date:** SR-09, 2026-11-09
- **Assigned agent and file ownership:** evaluation teammate; owns `docs/EVALUATION_PROTOCOL.md` only
- **Status: IMPLEMENTED, PENDING INDEPENDENT QA**
- **Zero measured results**, by construction: every results slot and both templates read UNKNOWN or
  are unmeasured placeholders. `docs/EVALUATION_TEMPLATE.md` is superseded but untouched.
- **Pre-registered hypotheses, each with its disconfirming condition:** H1 suppression on held-out
  targeted rows exceeds the eta=0 control; H2 retention loss on untargeted rows stays below δ_R;
  H3 selectivity (targeted minus untargeted exceeds δ_sel and exceeds the shuffled-mask arm);
  H4 (secondary) the `per_mask_entry` vs `per_masked_element` difference is explained by effective
  step size alone — disconfirmed if it persists after scaling `lr` by 1/width; H5 (secondary)
  `rescale=True` reduces suppression.
- **H3 is the registered expected-failure hypothesis**, and the reasoning is stated as an inference
  to be confirmed by derivation and unit test, not as a result: the toy student is one per-column
  affine map shared across rows and the erasure target is also affine in `x`, so the mask only
  chooses which rows supply the fit and untargeted rows should move with it. H2 should fail for the
  same reason. A *SUPPORTED* H3 therefore triggers a scorer-bug and leakage review rather than being
  read as a discovery — the protocol can distinguish a real effect from a procedure that always says
  yes. **Scorer-validation fixtures** make the scorer falsifiable both ways: an oracle gated
  predictor must pass, a global degrader must fail, and an unconditioned-output identity must show
  no suppression beyond the eta=0 control.
- **Joint acceptance rule:** JOINT_SUPPORTED requires H1, H2 **and** H3 all SUPPORTED with every
  validity gate passing; any UNSUPPORTED makes it JOINT_UNSUPPORTED; anything else INCONCLUSIVE.
  Suppression alone is satisfied by a global degrader and retention alone by doing nothing, so
  neither number may be reported in isolation. Even JOINT_SUPPORTED is recorded as `TOY_RESULT`.
  Retention is measured against the **eta=0 control, not the untouched teacher**, because at eta=0
  the target equals the unconditioned output, so that arm still trains the student — comparing
  against the teacher would miscount training drift as erasure.
- **Uncertainty:** the seed is the unit of replication, minimum 30 and 100 planned, with the seed
  list frozen and hashed. Primary interval is a percentile bootstrap over seeds, 10,000 resamples,
  RNG derived from the kit's seed utilities. Bonferroni across the three primary hypotheses (≈98.33%
  each); everything else is exploratory and cannot support a verdict. A t-interval runs as a
  secondary check, and disagreement on which side of a margin a bound falls — or widths differing by
  more than 25% — forces INCONCLUSIVE. Assumptions stated: seed exchangeability, no shared state, no
  dropped runs, n ≳ 30; declared invalid for n < 20, heavy tails, outcome-dependent failures, or
  shared teachers/eval rows. SD, IQR, min, max and the per-seed vector are mandatory.
- **Stop rule fixed in advance:** no optional stopping, no efficacy look before the last frozen seed;
  >5% numerical failures makes the whole family INCONCLUSIVE; extending n requires a timestamped
  protocol amendment with a reason and fresh seeds.
- **Level A / Level B separation holds the safety boundary.** Level B (what a real evaluation would
  require) is stated purely as process requirements — pre-registration, independent target and
  benchmark definition, holdouts, controls, blinding, replication, power. It names no target, hazard
  category, probe, assay, dataset or elicitation method. Its one concrete element is the SR-02
  four-arm baseline-equivalence design, which concerns code configuration, not content. Deliberately
  **not** specified, and deferred to SR-17: the content of a real utility battery and suppression
  metric, adversarial-recovery designs, sealed-holdout construction for a real concept, and
  calibrated margins/power (which would need effect sizes only real measurements could supply).
- **Gaps reported for other owners, not silently patched:** `ExperimentRecord` has no structured
  verdict field and no amendment field, so the verdict currently goes in `notes` and an
  amendment-log hash in `input_hashes` — flagged for SR-14 rather than changing the schema. The
  pre-analysis precision simulation for n=100 was not run, so the adequacy of 100 seeds is UNKNOWN.

---

## SR-02 — Re-work after QA FAIL

- **Date:** 2026-11-09. **Status: RE-IMPLEMENTED, PENDING QA RE-REVIEW.**
- All eight defects, the citation corrections, both omissions and the two factor-42 caveats were
  applied to `docs/METHOD_AUDIT.md`. A pre-edit copy was preserved in the scratch directory.
- **Corrections of substance:**
  - §3.2 item 2: only the output *radius* equals ‖u‖; the displacement ‖u‖(t̂−û) has radial component
    ‖u‖(cos θ−1) and magnitude 2‖u‖sin(θ/2).
  - §3.2 item 3: rewritten as a property of the target map with no verdict on the method. With
    `c = s·u` and η = 5 the target is `(6−5s)·u`, flipping sign for s > 1.2.
  - §9: the unsupported `1e-8` sign-convention claim was dropped (D:522-523 and the old D:535 are
    equivalent because cos is clamped).
  - `th_dih_v`: NaN inputs give (0,0) there; the (1,0) path fires only on non-finite *results*; only
    `th_ang_v` returns (1,0) for invalid input (D:525-527). Added that upstream `_preprocess` uses
    NaN in `alpha` to clear `alpha_mask` (A:565-566), so the fork's change alters that model input.
  - §3.4: with an all-True mask `diffuse_pose` adds zero delta (A:diffusion.py:103), so `x_t_u` is
    the recentred, already-T-noised `sample_init` output — not noise-free.
  - §6: only the gradient chain *across* blocks is truncated; each block's own parameters, and the
    final block's, still receive gradient.
  - §11: ancestor `base.yaml` values are now SOURCE OBSERVED — `T: 50`, `partial_T: null`,
    `crd_scale: 0.25`, `p_drop: 0.15`, `align_motif: True`, `sidechain_input: False` — so
    `t ∈ 1..49`; register #17 becomes an INFERENCE conditional on the effective `p_drop`. A
    checkpoint-config override remains possible; `fix_motif` and `symmetry` stay UNKNOWN.
  - Claims register: the rows previously asserting something was "false" now report mechanical facts
    only (#8, #9, #11, #13, #16, #23, #26); #2 separates static flags from runtime inference; #9
    carries the L>1 and slot caveats; #13 splits "does not raise" from "UnboundLocalError if
    reached"; #26 no longer calls the `main()` example "generic".
  - Omissions added: `lr_lambda(0) = 0`, so the first optimiser step is a no-op; and the in-place
    write on the grad-requiring leaf under `sidechain_input: True` (A:542-543, fork clones only in
    the `else` branch) — not triggered under the default config, and the builder honestly notes it
    did not trace whether `xyz_t` inside `_preprocess` is the same tensor as `x_t`.
  - Placeholder slots are now an INFERENCE from A:`util.py:588-589`
    (`xyzs_in_base_frame = torch.ones(...)`, `base_indices = 0`), so they count in both the loss sum
    and the per-atom renormalisation.
  - The runner sentence now reads "necessary given the fork's chosen edit", with the `TypeError` and
    `AttributeError` supporting detail.
- **A QA citation was itself wrong, and the builder was right to push back.** QA cited ancestor
  `rfdiffusion/inference/utils.py:329` for the NaN write-back in `align_to_xt_motif`; the builder
  cited 360. **Orchestrator adjudication: the builder is correct.** Direct inspection of the ancestor
  commit shows `px0_[~atom_mask] = float("nan")` at line **360**; line 353 is a separate
  `px0[~atom_mask] = 0  # convert nans to 0`. The conclusion drawn from the citation is unchanged.
  Recorded because review must be bidirectional: a reviewer's finding is not automatically correct.
- **Unverified by the builder, stated honestly:** it did not re-run the numeric checks, so the
  0.41999998 figure and the worked examples in the document rest on QA's computation rather than its
  own. Flagged for the QA re-review.

---

## Orchestrator correction — the SR-05 "equivalent mutant" adjudication was too quick

- **Date:** 2026-11-09.
- Earlier in this journal the orchestrator accepted the SR-05 builder's argument that QA's
  `after = before` mutant was an *equivalent* mutant and recorded it as settled. The QA re-review
  **partly refuted** it, and the orchestrator was wrong to close the question on the builder's
  reasoning alone.
- **What is true:** for the stock `Teacher`, the argument holds. Its params are a frozen
  `MappingProxyType` of tuples, `outputs()` is pure, and `train` never touches it, so
  `teacher_before` and `teacher_after` genuinely cannot differ.
- **What is false:** the argument was stated about the *public API*, and `train` never type-checks
  `teacher`. QA passed a stateful `Teacher` subclass, and separately a duck-typed object exposing
  only `outputs()`; both were accepted, both produced `teacher_before != teacher_after`, and `train`
  still returned a record labelled `TOY_RESULT`. The config hash covers only `teacher.params`, which
  was *empty* for the duck-typed probe — so the provenance record misrepresented the run. The
  `after` field is therefore a genuine runtime tripwire that nothing currently checks.
- **Process lesson, recorded deliberately:** an "equivalent mutant" claim is a proof obligation about
  the whole reachable input space, not about the one class the author had in mind. The orchestrator
  should have asked for that argument rather than accepting the narrower one. Routed to the builder
  as defect D1 with a requirement to validate the teacher type and assert
  `teacher_before == teacher_after`.

---

## SR-07 — Non-in-place ops, mutation detection, device/precision comparison

- **Task ID and date:** SR-07, 2026-11-09. **Owner:** numerics teammate.
  **Files:** `src/toy/tensor_ops.py`, `tests/toy_tests/test_tensor_ops.py`.
- **Status: IMPLEMENTED, PENDING INDEPENDENT QA.** 70 tests in-file (69 pass, 1 skipped).
- **MPS was genuinely available on this machine**, so a *real* second-device comparison was performed
  rather than everything skipping. CPU vs MPS float32 on sum-of-squares, matmul and normalize each
  showed max relative difference ≈1e-7 and **was not bitwise identical**; a large sum showed an
  absolute difference of 3.1e-5. MPS does not support float64, which is reported as *skipped with a
  reason*, not as a zero difference.
- **Measured float32 vs float64 divergence (CPU, float64 reference):** `(1+x)−1` for x∈[1e-9,1e-7] →
  max abs 5.9e-8, max rel 0.59; the single value `(1+1e-8)−1` → rel 1.0 (float32 returns exactly 0);
  a 50,000-term sequential sum of 0.1 (true ≈5000) → abs 2.53, rel 5.1e-4; control (sum of squares of
  O(1) values) → abs 3.7e-7, rel 7.3e-10; **Kabsch rotation on well-spread points → rel 1.8e-7, but
  on near-collinear points → rel 1.17.** Nothing was bitwise identical. Documented as a *quantified
  sensitivity*, not a defect, and the tests assert the stressed fixtures exceed the control by >1000×.
  Generically relevant because the fork rewrote alignment code in `inference/utils.py` — but this is
  a property of the arithmetic, **not** a claim about the fork.
- **In-place autograd probe (torch 2.7.1), seven recorded cases:** a write into a grad-requiring leaf
  raises `RuntimeError` ("a leaf Variable that requires grad is being used in an in-place
  operation"); a view of a leaf is non-leaf but still raises; a non-leaf write does *not* raise at the
  write and is caught at `backward()` only if a saved tensor was modified; a non-leaf write autograd
  did not save is **silent** with the gradient still correct; `no_grad` bypasses the leaf check but a
  graph built earlier then fails at `backward()`; clone-then-write is the safe pattern. Tied in the
  docstring to ER-11 and to SR-02's `x_t_student` leaf finding. RFdiffusion is neither imported nor run.
- **Mutation detector limits tested, not just asserted:** a write through `.data` changes values
  without bumping `_version`; writing the same value bumps the version only; mutate-then-restore
  (`mul_` then `div_`) bumps the version only. Objects it cannot compare go to `unchecked`, never
  reported as clean. It sees inputs only — not globals, nor tensors reachable via object attributes.
- **Unmeasured ≠ measured zero:** with fewer than two comparable configurations the diffs are
  `MetricValue.unmeasured` and `bitwise_identical` is `None`, with a test asserting this is not equal
  to a measured 0.0.
- **UNKNOWN for want of hardware:** all CPU-vs-CUDA comparisons; CUDA nondeterminism (e.g. atomics in
  `scatter_add`); Kabsch SVD sign/ordering on a real GPU (on MPS `linalg.svd` falls back to CPU, so it
  would not be a GPU test and no MPS SVD comparison was claimed); float64 on any GPU; cross-machine
  and cross-BLAS variance.
- **Caveat recorded:** the leaf exception message is torch-version dependent; the test asserts the
  substring and the evidence records `torch_version`.
- **Torch-blocked run:** 266 tests OK with 54 skipped; every torch/CUDA/MPS test skips *with a reason*.

---

## SR-08 — Safe toy checkpoints with provenance and integrity digest

- **Task ID and date:** SR-08, 2026-11-09. **Owner:** toy-researcher teammate.
  **Files:** `src/toy/checkpoint.py`, `tests/toy_tests/test_checkpoint.py`.
- **Status: IMPLEMENTED, PENDING INDEPENDENT QA.** 47 new tests.
- **No pickle, by construction.** The module imports none of `pickle`, `torch`, `dill`, `marshal`,
  `shelve`; an **AST scan** test enforces this and was shown non-vacuous against 13 bad snippets while
  correctly ignoring docstring mentions. This is the direct counterpart to ER-08 / the audited script's
  unrestricted `torch.load` at L479.
- **Digest coverage is exact and tested:** sha256 over the canonical JSON of every top-level key
  except `digest` itself — covering `format_version`, `label`, `created_utc`, every provenance field
  including `input_hashes`, and every param including `-0.0` vs `0.0`. A test mutates **each** covered
  field in turn and confirms the digest changes. The loader additionally requires the file bytes to be
  byte-identical to a canonical re-serialisation of what it parsed, catching changes that parse to the
  same content (whitespace, key order, number spelling, escape case).
- **Orchestrator independent verification:** exhaustive single-byte mutation over the whole 386-byte
  file with masks 0x01/0x20/0xFF — **0 of 1158 mutations undetected**. `-0.0`, `5e-324` and `1.0`
  round-tripped exactly.
- **Corruption matrix**, each with a specific exception: byte flip/delete/insert at *every* offset;
  truncation at 8 points; empty file; non-JSON and non-UTF-8 bytes; top-level array or scalar;
  duplicate key; non-canonical key order; oversize (>1 MiB); deep nesting; unknown key added
  (including a `student_model_state_dict` key); any of 5 keys removed; a key renamed to
  `model_state_dict`; digest removed/altered/malformed/non-string; unsupported `format_version`
  (2, 0, −1, 1e9); NaN/±Infinity/±1e999 params; wrong types in params; malformed provenance. Unknown
  or renamed keys are rejected *before* the digest check, so they fail even with a recomputed digest.
  This is the generic analogue of the audited silent `student_model_state_dict` key incompatibility.
- **Honest statement of the limit, with a test that demonstrates it:** the digest detects accidental
  corruption and naive tampering, but is **not a signature or MAC** — an attacker who can rewrite the
  whole file may edit content, recompute the digest, and the loader will accept it.
  `test_attacker_recomputed_digest_is_accepted_documented_limit` exists precisely to pin that. It also
  says nothing about whether the parameters are good or safe.
- **Atomic write** (temp + `os.replace`): a simulated failure in `os.replace` or `os.fsync` leaves no
  target file and no temp leftovers, and a failed overwrite leaves the previous valid file intact.

---

## SR-10 — Synthetic benchmark scoring and confidence intervals

- **Task ID and date:** SR-10, 2026-11-09. **Owner:** evaluation teammate.
  **Files:** `src/toy/benchmark.py`, `tests/toy_tests/test_benchmark.py`.
- **Status: IMPLEMENTED, PENDING INDEPENDENT QA.** 56 new tests. Standard library only — the
  statistics are hand-implemented precisely so they can be checked against known values.
- **The protocol's experiment was NOT run.** The erasure arm `E` is never run as a study; only `C0`
  and `C_shuf` appear in the scorer-validation fixtures. Both the module docstring and the test header
  state that every number produced is a property of the *scorer* on a fixture whose answer is known by
  construction — not a result about the toy method, and not about RFdiffusion.
- **Statistics validated against hand-computed values:** t quantile at 0.975 for df=1 = `tan(0.475π)`
  = 12.7062; df=2 = `0.95/sqrt(2·0.975·0.025)` = 4.30265; textbook values for df=4, 9, 29 and the
  large-df limit 1.96; `t_cdf(1, df=1) = 0.75`; the t-interval for [1,2,3,4,5] = [1.036757, 4.963243]
  (sd 1.5811, se 0.7071, t 2.7764) — **the builder's first hand-computed figure contained an
  arithmetic slip, the test caught it, and the comment was corrected**; type-7 quantiles of
  [10,20,30,40]; the percentile interval of 0..100 = [2.5, 97.5]; and for a bootstrap of [1,2,3] all
  27 resamples enumerated exactly (mean 2, variance 2/9, P(all ones) = 1/27), matched to ≈5σ of
  sampling noise. Known-answer checks: constant sample → zero-width interval; symmetric sample →
  exactly symmetric t-interval; width scales as 1/√n across n = 30, 120, 480.
- **The scorer is falsifiable in both directions** — the property that makes it worth anything:
  ORACLE_GATED → JOINT_SUPPORTED (H1, H2, H3 all SUPPORTED); **GLOBAL_DEGRADER → H1 SUPPORTED but H2
  UNSUPPORTED, giving JOINT_UNSUPPORTED** (the required "must fail" case, proving suppression alone
  cannot pass); IDENTITY_TEACHER_UNCOND → H1 UNSUPPORTED. A separate test confirms the scorer is
  neither always-yes nor always-no.
- **One-sided reporting is structurally impossible:** `JointResult` is the only holder of verdicts and
  its `.verdict` is a derived property that cannot be set. `ExploratoryResult` has **no verdict field
  at all**. Verdicts are returned as a structured object, with `notes` only a labelled fallback.
- **All 27 H1/H2/H3 combinations** are tested against the joint rule, with gates passing and failing.
  Gates fire on <30 seeds, >5% failures (2-of-32 fails, 1-of-31 passes), an unfrozen or mismatched
  seed list, and unverified row-set disjointness; a gate failure overrides UNSUPPORTED. The
  disagreement rule was verified on a constructed case (29 zeros and one 10) where the bootstrap lower
  bound is 0 while the t lower bound is below −0.2, correctly forcing INCONCLUSIVE.
- **Nine points where the protocol was ambiguous were reported rather than silently resolved**,
  including the §4-vs-§7 H3 rule conflict, how to combine H3's two conditions, gate-vs-UNSUPPORTED
  precedence, what the 25% width tolerance is relative to, incomplete gate coverage
  (`complete_gate_coverage` stays **False** and `deferred_gates` is populated, since a literal reading
  of the protocol would make JOINT_SUPPORTED unattainable), the unnamed bootstrap quantile method
  (type 7 chosen), and that "frozen" is only checkable as a digest match and so remains
  producer-asserted. Several of these fed directly into the SR-09 revision below.
- **Reduced-cost note, stated honestly:** the scorer-validation studies used 30 frozen seeds and
  **2,000** bootstrap resamples to keep the suite fast; the production default remains 10,000.

---

## SR-05 — Residual defects closed (after QA PASS)

- **Date:** 2026-11-09. All six residuals closed; 333 tests green at that point.
- **D1 (provenance integrity, the one that mattered):** `train` now rejects any non-`Teacher` object
  (subclasses still allowed) and snapshots the teacher's params up front, refusing to record the run
  if `teacher_after != teacher_before`. This closes the hole QA found, where a duck-typed object with
  an empty `params` produced a `TOY_RESULT` record whose provenance misrepresented the run. Proven
  non-vacuous: short-circuiting the tripwire fails `test_mutating_teacher_is_caught_not_recorded`, and
  neutering the isinstance branch fails `test_non_teacher_object_rejected`.
- **D2:** `eta` is normalised to float before hashing, so `eta=1` and `eta=1.0` no longer produce
  different config hashes for identical runs.
- **D3:** `run_id` now embeds the first 12 hex of the config hash, so different configs no longer
  collide on `run_id`.
- **D4:** `TrainResult` gained `loss_increased`, surfaced as a metric and an explicit WARNING in the
  record notes, so a runaway-but-finite learning rate (0.92 → 47.5 at `lr=3.0`) can no longer be
  recorded as an unremarkable `TOY_RESULT`. Gradient norm now uses `math.hypot`, and huge finite
  inputs report "numeric overflow … input magnitude too large" instead of the schema's generic message.
- **D5/D6:** `erasure_demo` exception types and `bool` policy made consistent via a `_real()` helper;
  the stale "pins CURRENT behaviour / Source is unchanged" comments corrected, including the
  inaccurate claim about which tests originally existed.

---

## SR-06 — Re-work after QA FAIL

- **Date:** 2026-11-09. **Status: RE-IMPLEMENTED, PENDING QA RE-REVIEW.** `test_stability.py` 39 → 50.
- **M-S1 was the critical gap and is fixed.** QA truncated `check_gradient`'s comparison loop to
  coordinate 0 and **every test still passed** — every wrong-gradient fixture happened to be wrong at
  index 0 or everywhere, so an error at indices 1…n would have gone undetected by the kit's core
  gradient-verification tool. New fixtures place the error at index 1, an interior index and the last
  index, each as an offset, a sign flip and a 2× scale, and require the message to name the right
  index. The truncation mutant now dies.
- **D-S1 (contract defect) fixed:** `float(v)` in the masked path raised a bare `OverflowError` for a
  huge int, violating the module's stated contract that every error derives from
  `StabilityError(ValueError)`. Now `NonFiniteError`. Proven by removing the handler.
- **D-S2:** the `-0.0` docstring overclaim was corrected rather than papered over — the sign-preserving
  promise now covers only the `check_finite_*` validators, and `masked_mean_checked` returning `0.0`
  for all-`-0.0` input is pinned by a test.
- **Mutants M-S2, M-S3, M-S5, M-S11 confirmed killed** by applying each one. Tests were added for
  M-S4, M-S6, M-S7, M-S8–M-S10, but the builder **honestly reports it did not run those mutants**, so
  those tests are not yet demonstrated to kill them. Recorded as an open limitation.
- **A real limitation now documented loudly instead of quietly:** with `f = 1e-9·x²` (true gradient
  2e-9) a claimed gradient **100× too large** passes at the default tolerances; it is caught at 2e-6,
  or at 2e-7 with `atol=1e-12`. This matters because the audited loss carries a `0.01` factor. A test
  pins all of it and the docstring states that a pass on a small-scale loss is not evidence.
- **Methodological note worth preserving:** the builder found that same-size source edits within the
  same second can reuse a stale `.pyc`, contaminating mutation results; its first M-S3 and M-S11
  results were affected and were re-run with the cache cleared. Any future mutation testing in this
  kit must disable bytecode caching.

---

## SR-09 — Re-work after QA FAIL (v1-DRAFT-r2)

- **Date:** 2026-11-09. **Status: RE-IMPLEMENTED, PENDING QA RE-REVIEW.** Builder agreed with all four
  findings. Still zero measured results; Level A / Level B separation preserved.
- **P2 (the serious one):** the "no selectivity mechanism" claim is now restricted to the **converged
  limit**, still labelled an inference to be confirmed by derivation and unit test. A new §4.1 records
  that at a finite budget, partial convergence plus extrapolation off the fitted region produces
  *apparent* selectivity that is **not** a mask mechanism, with magnitude depending on `steps` and
  `lr`. `steps` and `lr` are now registered, the end-of-training gradient norm is recorded per run, a
  new `C_conv` arm re-runs `E` and the shuffled-mask arm at a converged budget fixed in advance, and
  new validity gate 12 covers this. A finite-budget SUPPORTED on H3 now triggers the
  scorer/leakage/convergence review rather than counting as a finding, and H3 can be SUPPORTED only if
  it also holds at the converged budget. **None of QA's probe numbers appear in the document** — QA
  explicitly flagged them as non-results (12 seeds, SD ≈ 0.23–0.32, its own fixture), and the point
  was used qualitatively only.
- **P1:** H3 split into H3a (`Δ_E > δ_sel`) and H3b (`Δ_E − Δ_Cshuf > δ_sel`); the `Δ_Call` condition
  **removed** because it had no operational definition; the primary family is now four simultaneous
  intervals, so m = 4 at 98.75% each, with both JOINT labels read from those intervals rather than
  from an unadjusted union; and H3's disconfirmation condition now matches the §7 verdict table.
- **P3:** H4 **withdrawn as a hypothesis** — QA showed it is an identity (trajectories at `lr/width`
  are bit-identical to ~1e-17), so its "CI excludes 0" disconfirmation could only fire on rounding
  noise or a bug. Replaced by an exact-identity unit test ("I-norm") handed to SR-10; the equal-`lr`
  cross-normalisation difference remains exploratory and descriptive.
- **P4:** new gate 11 requires `C0` to be genuinely trained relative to `C_init` (which was previously
  defined but unused), plus a bounded absolute fit and a fall in `E`'s own training loss — closing the
  hole where an undertrained `C0` would make H2 SUPPORTED vacuously. The vague n=100 "precision check"
  is replaced by a concrete rule: pilot seeds *disjoint from the frozen list* estimate the per-seed SD,
  a formula sets `n_planned = max(100, n_req)` with a cap, and the rule runs once before registration
  is frozen. And **verdicts are now always recomputed by the scorer from stored metrics, the seed-list
  hash and the registered parameters; `notes` is never parsed, and a `notes` string disagreeing with
  the recomputed verdict marks the report invalid** — closing the gap QA demonstrated, where
  `notes="verdict: JOINT_SUPPORTED; model is safe"` is accepted by the schema under `TOY_RESULT`.
- **Smaller corrections:** the "at least 2 masked rows" requirement is now enforced via seed
  eligibility instead of holding by chance; n ≥ 30 is labelled a convention of this protocol rather
  than a cited result, and below 30 completed seeds the protocol now yields no verdict and no
  registered interval (matching the bootstrap assumption); every planned-but-unrun slot is `UNKNOWN`,
  with `HYPOTHESIS` reserved for the single pre-registration record; the SR-06/SR-05 attribution is
  fixed; and **H5's expected direction was withdrawn** — it is now two-sided and exploratory, because
  the rescale factor clamped to [0.1, 2.0] can move the target *farther* from the conditioned output.

---

## Orchestrator integration fix — private API coupling, and a self-inflicted breakage

- **Date:** 2026-11-09.
- **Defect:** `src/toy/checkpoint.py` imported `_canonical` — a **private** name — from
  `src/toy/schema.py`, because it must produce byte-identical serialisations to hash over. Two
  modules depending on another module's private helper is fragile, and it would have spread as more
  modules needed canonical bytes. Fixed by promoting it to a public `canonical_json()` with a
  docstring recording that any change to its output is a breaking change for every stored
  `content_hash` and checkpoint digest, keeping `_canonical` as a documented backwards-compatible
  alias, and updating `checkpoint.py` to the public name.
- **Self-inflicted breakage, recorded rather than hidden:** the orchestrator's first attempt used
  `sed -i '' 's|\b_canonical(|canonical_json(|g'`, but **BSD/macOS `sed` does not support `\b`**, so
  the call sites were not renamed while the import was — leaving `_canonical` undefined in
  `checkpoint.py` and producing **43 test errors**. Caught immediately by running the suite, and fixed
  by completing the rename. Lesson for this kit's own tooling: prefer exact-match edits over
  regex-with-word-boundaries in shell on macOS, and always re-run the suite after a mechanical rename.

---

## SR-03 — Re-work after QA FAIL

- **Date:** 2026-11-09. **Status: RE-IMPLEMENTED, PENDING QA RE-REVIEW.**
- **Severity calibration corrected** — the register's value depends on being calibrated, so an
  overstated row is as damaging as an understated one:
  - **ER-07** retitled to describe the general *pattern* and explicitly marked as **not applying to
    the script's logged value**; severity split (Low for the script, Medium for the pattern), with the
    caveat that `S:373` assigns the pre-clip return value which is then logged at `S:384`/`S:425`.
    Previously the title claimed a problem in the real program that the entry's own body denied.
  - **ER-01** lowered High → Medium: a loud crash, not silent corruption. Records that the script has
    no `except RuntimeError`, and that `except Exception` at `S:663`/`S:683` *would* catch the
    resulting `UnboundLocalError`.
  - **ER-03** lowered Medium → Low: no *unintended* detach was identified, and "CONFIRMED" is now
    stated to refer only to the existence of the calls.
  - **ER-04** stays High (justified — the acceptance gate is absent and would not discriminate), but
    the false claim that SR-06 reports a gradient-coverage fraction was removed;
    `require_parameter_gradient` takes one flat gradient and reports none.
- **ER-02 strengthened where QA found it too conservative:** now also CONFIRMED-IN-SOURCE for the mask
  multiply at `S:307`, cites `S:199-200` for the all-True `atom_mask`, adds the caveat that the NaN
  write-back can only restore NaN already present and that absent-atom slots may be finite
  placeholders, and the torch demonstration now shows `clamp` preserves NaN.
- **Both inherited citation errors fixed:** ER-07 `S:385` → `S:384`; ER-02 `D:333-335` → `D:335-337`.
- **Test gaps closed, with mutations confirming each:** float-inexact configurations `(7,(14,3))`,
  `(1,(7,))`, `(9,(3,3,3))` now require `Fraction` (previously a `float` substitution survived because
  every tested case happened to be float-exact); `PATTERN_FUNCTIONS` key set pinned; the `exec` demos
  return an asserted evaluated count so replacing them with `pass` no longer passes vacuously; the
  `ValueError` path in `mask_polarity_inversion` and the equal-losses case covered; **the torch import
  guard now catches any `Exception`**, with tests simulating `OSError` and `RuntimeError` failures (the
  previous `except ImportError` would have made the whole module error instead of skip on a broken
  install or ABI mismatch); and a new structural register test pins ER-01…ER-11, the required fields
  per entry, a valid label per entry, and the absence of sentence-initial "The method is
  broken/safe". Mutants verified killed: the float substitution, dropping the ER-07 key, `exec` →
  `pass`, deleting the ER-09 section, and inserting "The method is broken."
- **The runner-divergence report was MY mischaracterisation, and the builder corrected it.** The
  orchestrator relayed the unittest-green / pytest-red observation as evidence of a runner difference.
  The builder could not reproduce any runner dependence: paths were already resolved from `__file__`,
  and the only `sys.modules` mutation happens inside child processes. The actual causes were all in
  its own files and runner-independent: (1) `test_register_structure` was written against register
  fields that did not yet exist — **the doc and its test were being edited concurrently, so each
  runner observed a different on-disk state**; (2) an over-broad deny-list matched the register's own
  sentence "no claim that the method is broken", now restricted to sentence-initial matches; and
  (3) the blocked-torch child process re-ran the whole test module, so one register failure surfaced
  as two apparently independent failures — the child now runs only the stdlib and torch-pattern
  classes and asserts exactly 2 skips. **Recorded at the builder's explicit request as "tests coupled
  to a doc under concurrent edit; fixed by decoupling and pinning structure explicitly", not as a
  proven runner difference.** The orchestrator should not have asserted a root cause it had not
  established.
- **Second instance of the same tooling trap:** the builder's first fix attempt was a BSD `sed -i`
  that silently did nothing because the shell `&&` chain aborted — the same class of failure that bit
  the orchestrator during the `canonical_json` rename. Two independent occurrences in one session;
  worth a standing rule for this kit.
- **Order-independence verified explicitly:** the file alone (14 passed, 1 skipped), from a different
  cwd (same), and in first, middle and last positions in the suite — all consistent.
- **Commands:** `unittest discover` → 347 tests OK, 2 skipped; `pytest -q` → 345 passed, 2 skipped;
  torch-blocked `unittest` → 347 OK, 54 skipped; torch-blocked `pytest` → 293 passed, 54 skipped.
  **Orchestrator independently re-ran all of these and confirms the tree is green under both runners,
  including the file in isolation.**
