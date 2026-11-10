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
