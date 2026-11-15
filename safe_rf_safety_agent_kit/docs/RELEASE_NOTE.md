# Release note — SafeRFdiffusion safety-replication audit kit

**Version:** `7bd6c75` (superseding `75f51e6`) · **Date:** 2026-11-13, revised 2026-11-15 · **Status of the release: FAIL on final QA
(`docs/SR16_AUDIT_REPORT.md`). Do not describe this kit as complete.**

---

## Read this first

**This kit contains no evidence that RFdiffusion is safe, that the safeRFdiffusion fork is safe, or
that any biological capability has been reduced, and it never produced any.** No model was run, no
model weights exist anywhere in this repository, no biological data was used, and no protein was
designed. Every number this kit produces comes from synthetic, non-biological toy matrices.

**This kit also contains no evidence that RFdiffusion or the fork is unsafe or broken.** It is an
audit of *methods and claims*, read-only, and it takes no position on the audited work's merits. Its
own method audit records "the method is safe / yields a safer model" as **UNKNOWN, not asserted by
this audit**, with no supporting evidence of any kind, and that entry is unchanged by this release.

**A passing test suite here is a fact about this test suite.** It is not a fact about RFdiffusion,
about the fork, about any checkpoint, or about any real-world risk. No quotation from this repository
can be made into such a fact, and no sentence in this note should be read as one.

---

## What this release is

A local, standard-library-only toy audit kit: a source-diff provenance record, a method-level
architecture audit with every claim labelled SOURCE / INFERENCE / UNKNOWN, an error and uncertainty
register, a toy teacher–student numeric demo on 2-D synthetic arrays, generic numerical-stability and
tensor-operation tests, a toy checkpoint format with provenance hashes, an evaluation-protocol
specification containing **zero measured results**, a synthetic benchmark scorer with confidence
intervals, robustness probes, a claim ledger with an immutable audit log, a local HTML dashboard, and
an offline test/lint/demo toolchain.

It needs no network, no credentials, no API keys and no model weights to run, and it has none.

## What final QA found

Independent QA at `75f51e6` returned **FAIL**, on one of its three criteria. The full reasoning is in
`docs/SR16_AUDIT_REPORT.md`; the summary is:

- **"No ungrounded statement that RFdiffusion is 'safe'" — PASS.** A hostile sweep of 73 matches
  across every tracked file, the rendered dashboard and the demo's terminal output found **zero**
  such statements: every match is a denial, a test fixture that exists so the kit can refuse to
  endorse the string, or an unrelated technical use of the word "safe". Two of the kit's own
  disclaimer strings were found to be unprotected by any test, and are listed as open defects below.
- **"Reproducible demo passes" — PASS.** Verified from a clean clone on two interpreters, including
  under an operating-system-level network denial with a control proving the denial was live.
- **"All accepted tasks supported" — FAIL.** Two reasons, below. Neither is a finding about
  RFdiffusion or about the fork; both are findings about this repository's record of its own work.

### Why it failed

1. ~~**One of the 16 completed tasks was marked complete without any independent QA record.**~~
   **WITHDRAWN 2026-11-15 — THIS CLAIM WAS FALSE, AND IT WAS A FALSE CLAIM ABOUT THIS PROJECT'S OWN
   WORK IN ITS READER-FACING ARTIFACT.** SR-00 **is** independently attested.
   `docs/PROGRESS.md:27` carries *"**Independent QA verdict and test log:** **PASS**"* with
   hand-re-derived arithmetic (`toy_target((3,1),(1,2),s=0.5)` = `(0.0, 2.5)`;
   `masked_mse((3,9),(1,0),(T,F))` = `4.0`), three QA-raised defects, remaining limitations and a
   commit SHA — every element `CLAUDE.md:13-14` requires. Defect D1 forced a structural repository
   change (`tests/toy/` → `tests/toy_tests/`): a rubber stamp does not rename a test package.
   **How the error was made:** `docs/SR16_AUDIT_REPORT.md` §1.2 inferred the absence from a single
   heading grep, `grep -c "^## SR-00 — QA verdict"` → 0. That count is true; the inference from it is
   not, because the attestation sits under a different heading. A count of a construct is not a
   measurement of its behaviour — the project's own rule, applied here to the project's own review.
   Verified independently at three HEADs, byte-identical, and traced to `04a393b`, the commit that
   flips the checkbox, so it was not added later.
   **Clause 1 does not fail on SR-00.** It fails on reason 2 alone.
2. **The evidence behind most of the completed tasks cannot be re-run by anyone.** Across roughly 28
   review rounds, the decisive evidence for a majority of the marks was mutation testing — deliberately
   breaking the code to confirm a test notices. **No mutation tool was ever committed to this
   repository.** The journal holds 265 lines recording a mutant as "killed" and a reader can reproduce
   none of them. The project's own journal records one occasion where such a claim was later measured
   to be false. Everything about the kit's *present behaviour* — test counts, determinism, offline
   operation, the demo, the rendered page, the lint result — was re-run and reproduced by QA from a
   clean clone; it is the project's account of *why it believes its tests bind* that is uncheckable.

**What this does not mean.** It does not mean any task was done badly, and no mark was withdrawn. The
seven most recent attestation records are detailed, independently measured, and each records a failure
before its pass. It means a stranger cannot check them.

## Known open defects at this version

| | Defect |
|---|---|
| 1 | ~~SR-00 is marked complete with no independent QA attestation.~~ **WITHDRAWN — FALSE.** SR-00 is attested at `docs/PROGRESS.md:27`; the claim rested on a heading grep. See above. |
| 2 | Mutation evidence behind most marks is unreproducible. **Half amended:** a harness IS now tracked (`scripts/mutate.py`, `scripts/mutants.json`), 15 mutants, 15/15 KILLED on two platforms. The ~313 historical claims in the journal remain unreproducible and no harness can make them otherwise, and the 15 mutants pin THIS round's fixes rather than re-deriving any mark's evidence. **Still open.** |
| 3 | The demo prints a joint verdict in a form the project's own evaluation protocol forbids, in the same paragraph where the protocol requires the document and the code to agree. |
| 4 | The demo's single safety qualifier, and one of the robustness module's standard non-claim strings, are not pinned by any test: removing either left all 1,493 tests passing. **CLOSED:** all seven disclaimer strings now carry pins, each proven against removal, gutting, weakening and relocation, and two against inversion; the demo's three stdout qualifiers have tracked mutants that die. |
| 5 | `benchmark.py`'s `complete_gate_coverage` is a truth test on a container, so a container that misreports its own length makes the result contradict itself. A one-line fix is known and was measured not to break anything. |
| 6 | The evaluation protocol's own header states it has never been independently reviewed, while the task that shipped it was marked on a recorded independent pass. |
| 7 | On a machine with pytest installed, whether the suite passes depends on third-party pytest plugins this kit neither installs nor bounds. Set `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`. The README's "First steps" command omits that precondition. |
| 8 | A documentation fix described in the final marking commit as required was applied to the prose only; the two code sites it names are unchanged. |

## Verified properties of this version

Each was re-run by independent QA from a clean clone at `75f51e6`. Each is a statement about this
repository's own code and nothing else.

- 1,512 tests, 0 failures, on CPython 3.12.4 and on CPython 3.13.5. (This figure was 1,493 at `75f51e6`; every count in this note was re-measured at `7bd6c75`.)
- Deterministic: two consecutive runs give identical per-module counts and an identical skip list.
- On a bare interpreter with nothing third-party installed: 1,512 run, 90 skipped, 0 failed, with
  every skip naming the package it is missing.
- `scripts/demo.py` exits 0 and renders a dashboard that is byte-identical across re-renders and
  across both interpreters.
- The suite, the linter, the demo and the test runner all pass under a macOS `sandbox-exec` profile
  denying inbound and outbound network, with a control confirming the denial was active. **This was
  measured on one host, one operating system and one mechanism; it is not a hermeticity guarantee,
  and nothing was measured on Linux.**
- The continuous-integration workflow in this repository **has never been executed**: there is no
  configured git remote, so no hosted runner has ever run it.

## Limits of this release, stated once and plainly

Each line below is a thing this kit **cannot establish and does not attempt to establish**. Each is
written so that the line can be quoted on its own without reversing its meaning.

- This kit establishes nothing about whether any concept-erasure method works or fails.
- This kit establishes nothing about whether any real checkpoint is safer or less safe than another.
- This kit establishes nothing about whether RFdiffusion or the safeRFdiffusion fork is safe, or
  about whether either is unsafe.
- This kit establishes nothing about whether any real capability is reduced or retained.
- This kit establishes nothing about whether any threshold used here is appropriate for a real
  evaluation.

Any of those questions requires independent measurement on real systems. That measurement is
explicitly outside this kit's scope and was never performed.

The decision about whether any real model run, dataset use, or biological model tuning is appropriate
is a **separate human review gate** (`SR-17`). It is unstarted, it is not part of this release, and
nothing in this release should be read as an input to it other than as a record of what was and was
not measured.

## If you are quoting this release

Quote the FAIL. Any sentence here that records a passing check is a statement about this repository's
test suite; it carries no implication about RFdiffusion, about the fork, or about biological risk, and
reproducing it alongside the name of either project would misrepresent it.

---

*Standard library only. No network, no credentials, no model weights, no biological content.
Findings and commands: `docs/SR16_AUDIT_REPORT.md`. Prior independent review:
`docs/SR12_INDEPENDENT_REVIEW.md`. Task graph and completion state: `docs/BUILD_BLUEPRINT.md`.*
