# Clean-clone verification (offline, stdlib only)

**The kit downloads nothing and requires no credentials.** It needs only Python 3.12 or newer (the standard library
is enough). No package manager, no API key, no model weights, no dataset, and **every connection the suite makes is
to loopback.** That is deliberately narrower than "the suite opens no socket", because it does: the runner's guard
canary and the negative-control tests that drive the runner with `--no-network-guard` (which is what makes them
controls) really attempt connections, and every target is **loopback** — a closed port on `127.0.0.1`, a loopback
bind, or an AF_UNIX socket. The loopback property is asserted by
`test_no_executed_connection_target_in_the_suite_is_non_loopback`; see "Connection attempts the suite itself
makes" below. This used to say "no network access at test
time" while four of those attempts went to a routable
address on every run, and it then said **"nothing the suite does leaves this host"**, which is one claim too
strong for what has been measured: **no run of this kit has ever been observed in a network-denied environment**,
so hermeticity is asserted by construction and not attested. See "Hermeticity is unattested" under "Known limits
of this documentation", which defines the measurement that would attest it.
`mse_naive` order-invariance in the robustness tests depends on CPython >= 3.12 compensated `sum()`; do not use
an older interpreter (some assertions would go red; pre-3.12 is unsupported).
"The standard library is enough" is a claim about whether the suite **passes**, and it was false for one round:
a test gated on the optional linter `ruff` carried a skip reason the skip policy rejected, so the documented
`--expect none` and `--expect torch` steps failed on any machine without `ruff` — which is every clean clone and
both CI jobs. It is true again, and the thing that made it false is now a named, capped skip category. An absent
optional developer tool changes **which tests run**, never whether the suite passes; see "The documented steps
used to fail without `ruff`" below.

## Steps

**Precondition for `--expect none`: a BARE interpreter.** `--expect none` does not merely tolerate the absence of
torch/numpy/pytest/PyYAML, it **asserts** it. On a genuinely clean clone that is already true. On a developer
machine that has any of them importable it **fails by design**: independent review ran the sequence below
verbatim on a host interpreter that had them and recorded `RESULT: FAIL` with 8 policy failures
(`POLICY:NONE_REASON`, `POLICY:TORCH_PRESENT`, `POLICY:MIN_NONE_SKIPS`, `POLICY:NO_NUMPY_REASON`,
4x `POLICY:BASELINE_SKIPS`). That is the check working, not a bug — but the steps below have to say so, because
they did not, and the documented sequence therefore failed as written.

```sh
git clone <this repository>   # the only network step, and only to obtain the source
cd safe_rf_safety_agent_kit   # the kit root (contains src/, tests/, scripts/)
python3 --version             # 3.12.x or newer
./scripts/lint.sh             # compileall + AST checks; works with nothing installed

# Is this interpreter bare? (no output = bare = use `--expect none` directly)
for m in torch numpy pytest yaml; do python3 -c "import $m" 2>/dev/null && echo "installed: $m"; done

# (a) BARE interpreter -- the clean-clone case:
./scripts/run_tests.sh --expect none --twice

# (b) the loop above printed something, and you want to use this interpreter anyway. `--expect any` keeps the
#     consistency, determinism, cap and per-module TEST-count checks and drops EVERY skip-REASON check plus the
#     baseline's SKIP-column comparison (both of those live inside `if mode == "none"` / `elif mode == "torch"`):
./scripts/run_tests.sh --expect any --twice

# (c) the loop printed something, and you want the clean-clone assertion anyway: make a bare interpreter.
#     `--without-pip` needs no network. Keep it OUTSIDE the repo: `.venv` and `venv` are the only venv names
#     pruned from the bytecode sweep AND ignored by git, so a differently-named venv inside the tree would be
#     swept and tracked. (`venv/` was missing from `.gitignore` when this sentence was written, so half of what
#     it promised was absent -- in the direction it exists to warn about, since the line above tells you to
#     create exactly that. Fixed, and the two lists are now compared to each other by
#     `test_every_directory_pruned_from_the_bytecode_sweep_is_git_ignored`, which parses the prune list out of
#     the script rather than restating it.)
python3 -m venv --without-pip "${TMPDIR:-/tmp}/kit-bare"
PATH="${TMPDIR:-/tmp}/kit-bare/bin:$PATH" ./scripts/run_tests.sh --expect none --twice

# (d) torch AND numpy AND pytest AND PyYAML are all installed -- the opposite assertion:
./scripts/run_tests.sh --expect torch --twice

python3 scripts/demo.py       # works in every case above
```

Pick exactly one of (a)-(d). CI uses (a) in `core-no-deps` (the runner installs nothing) and (d) in
`optional-deps`. `README.md` carries the same precondition in one line.

`run_tests.sh` removes `__pycache__`, disables bytecode (`PYTHONDONTWRITEBYTECODE=1`), fixes `PYTHONHASHSEED=0`,
installs the socket guard described under "What the network guard does and does not do" (patched names, not
all sockets), runs `python3 -m unittest discover -s tests -v` (and
`python3 -m pytest -q tests` only if pytest happens to be installed), checks skip reasons, and with `--twice`
verifies a second run gives identical counts and an identical skip list. You can also run the suite directly:
`PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests`.

Why no bytecode: a stale `.pyc` contaminated mutation results three times and once caused a misattributed
10-failure spike. After any surprising failure count, clear `__pycache__` and re-run before drawing conclusions.

## Expected counts, and why no suite total is written here

**Do not take a suite total from this document.** The total grows with every task, and a hard-coded figure here
has already been restated wrongly twice and silently dropped once. Measure it; the runner prints it on its last
line, and `--twice` proves the figure is stable:

```sh
./scripts/run_tests.sh --expect any --twice     # ... RESULT: OK (unittest ran=<N> skipped=<K>)
```

Every figure below is a **historical record stamped with the commit it was measured at**, not a target. A larger
total is normal and is never a failure. A *smaller* per-module count is what the baseline catches (below).

| Environment | unittest | pytest | `--expect` | measured at |
|---|---|---|---|---|
| Nothing installed (`venv --without-pip`), Python 3.12.13 | 914 run, 89 skipped, 0 failed | not run (not installed) | `none` | pre-SR-15 (`86a52ed` era) |
| Nothing installed (`venv --without-pip`), Python 3.12.4 | 1000 run, 89 skipped, 0 failed | not run (not installed) | `none` | SR-15 — see below |
| Nothing installed (`venv --without-pip`), Python 3.12.4 | 1002 run, 89 skipped, 0 failed; deterministic across `--twice` | not run (not installed) | `none` | `209adfc` (baseline regeneration) |
| Nothing installed (`venv --without-pip`), **Python 3.13.11** | 1002 run, 89 skipped, 0 failed; deterministic across `--twice` | not run (not installed) | `none` | `209adfc` — **first 3.13 measurement**, see below |
| Nothing but PyYAML | one fewer skip than bare; 87 at a 874-test tree, **never re-measured since** | not run | `none` | stale |
| torch + numpy + pytest + PyYAML (macOS, MPS available) | 914 run, 2 skipped (identical in two full runs) | 912 passed, 2 skipped | `torch` | pre-SR-15 |
| Case-sensitive APFS stand-in, bare | 914 run, 90 skipped (**1** filesystem-case — an artefact; see below) | not run | `none` | pre-SR-15 |
| Case-sensitive APFS stand-in, torch | 914 run, 3 skipped (**1** filesystem-case — same artefact) | 911 passed, 3 skipped | `torch` | pre-SR-15 |
| **Bare Linux container, CPython 3.12.10** | 1252 run, 95 skipped, 0 failed; deterministic across `--twice` | not run (not installed) | `none` | `81d450a` — **the first real-Linux measurement** |
| **Bare Linux container, CPython 3.13.3** | 1252 run, 95 skipped, 0 failed; deterministic across `--twice` | not run (not installed) | `none` | `81d450a` — same container image |

All rows were repeated with `--twice` and were identical. The bare skips are overwhelmingly torch/numpy skips,
plus the optional-PyYAML workflow-parse test and the script tests that need pytest. Earlier independent reviews
measured 739 run / 86 skipped bare, and 656 run / 85 skipped bare at the base commit.

**Linux is no longer unobserved, and this row used to read `| Real Linux | never observed |`.** At `81d450a`,
`bash scripts/run_tests.sh --expect none --twice` was run in two bare Linux containers (nothing installed, no
venv): **1252 ran / 95 skipped / 0 failed on both CPython 3.12.10 and 3.13.3**, `RESULT: OK`, `run1 == run2`
with identical per-module counts and identical skip lists, **POLICY tokens: none**, the filesystem probed
**case-sensitive**, and `packages_present == []`. Two things that had only ever been predicted here are now
measured: the **4** filesystem-case skips (see the next section — exactly 4, not the stand-in's 1) and the
**1** absent-optional-developer-tool skip. Those five are the whole difference between **95** skips on Linux and
**90** locally, because `ruff` is installed on the local machine and so does not skip there. The
**macOS-generated `scripts/test_baseline.txt` was compared against the Linux run and passed**, which is the
first evidence that the committed per-module floor is not macOS-specific.
**What this does NOT establish: hermeticity.** The container **had network**. The socket guard was observed
*present* on that run, not *load-bearing*; see "Hermeticity is unattested" under "Known limits of this
documentation" for the measurement that would attest it.

### SR-15 re-measurement (what was actually run, and on what)

```
$ python3 -m venv --without-pip "$TMPDIR/kit-bare"      # Python 3.12.4, no pip, no site-packages
$ PATH="$TMPDIR/kit-bare/bin:$PATH" ./scripts/run_tests.sh --expect none --twice
...
unittest: ran=1000 skipped=89 failed=0 rc=0
skip policy (none): 89 skipped across 4 modules; 1000 tests started
== pytest == SKIPPED: pytest is not installed (optional; unittest results above are authoritative)
deterministic: run1 == run2 (ran=1000 skipped=89 failed=0, identical per-module counts and skip list)
RESULT: OK (unittest ran=1000 skipped=89)
```

Two things about this measurement, because it is the kind of figure this document keeps getting wrong:

1. **It is not a clean-commit measurement.** It was taken on a working tree at commit `4f80c83` **plus
   uncommitted work from two owners** (this SR-15 change set, and in-flight changes to `src/toy/benchmark.py` and
   `src/toy/robustness.py`). Expect the total to differ at the commit that lands.
2. **An earlier attempt on the same day reported 3 failures in `toy_tests.test_benchmark` and was a false red.**
   All three passed in isolation immediately afterwards, and `src/toy/benchmark.py` carried an mtime from the
   middle of that run: another owner edited the module while the suite was reading it. Treat any failure confined
   to a module whose files are `git`-dirty as suspect until re-run on a quiet tree. This is the same class of
   cross-agent interference that the stale-`.pyc` rule exists for, and the `--twice` determinism check is what
   caught it: the two passes of the run above agree exactly.

The 89 bare skips **of that run**, by module, were: `test_tensor_ops` 82, `test_scripts` 4 (three needed pytest,
one needed PyYAML), `test_failure_modes` 2, `test_stability` 1 — *and that measurement was taken on a machine
that happened to have `ruff`.* Zero filesystem-case skips, because this machine's repo volume and `TMPDIR` are
both case-insensitive — which is the whole subject of the next section.

Read those per-module figures as the record of that one run. Two of them have since moved, and this paragraph had
been **cut in half by a later insertion** — `test_failure_modes` 2, `test_stability` 1 were orphaned from the
list they belong to, three sentences below it — which is how its own stale "three need pytest" survived. At the
commit that closed the fourth SR-15 FAIL the same bare machine has `test_scripts` **5** (**four** need pytest,
one needs PyYAML) and **90** skips in total **with** `ruff` present, and `test_scripts` **6** for **91** skips
**without** it: the extra one is the optional-developer-tool skip described under "The documented steps used to
fail without `ruff`". (The previous version of this sentence put the with-`ruff` figure, 90, under the
without-`ruff` heading.) That extra skip does **not** move `scripts/test_baseline.txt`, by construction; before
the fix it did not add a skip at all, it failed the run.

### Filesystem-case skips: **4** on Linux, and the earlier "1" was a measurement artefact

**Measured on Linux at `81d450a`: exactly 4**, in two bare containers, printed as
`note: 4 skip(s) for a case-sensitive filesystem (expected on Linux)` — this section used to say only "expect
4", from the stand-in plus reasoning. Expect **4** filesystem-case skips on Linux. Three are the `need_ci()` tests of `IdentityAndCaseGuards` in
`tests/toy_tests/test_dashboard.py`; one is `test_case_varied_tmpdir_into_repo_is_refused_before_anything_is_written`
in `tests/toy_tests/test_scripts.py`.

An earlier version of this document said both "1 filesystem-case" and "four tests skip this way", and explained
the 1 by claiming that the dashboard tests had been changed in the meantime. **That explanation was false and has
been deleted.** All three `need_ci()` call sites are intact and were never changed or removed. The real cause is
**which filesystem each test probes**:

- the three `test_dashboard` tests gate on `_fs_case_insensitive(self.tmp)`, where `self.tmp` comes from
  `tempfile.TemporaryDirectory()` — that is **`TMPDIR`, not the repository volume**;
- the one `test_scripts` test probes the **repository** volume (`tempfile.mkdtemp(dir=ROOT)`).

The "case-sensitive APFS stand-in" rows above put only the **repo** on a case-sensitive volume while `TMPDIR`
stayed on the case-insensitive system volume. Only the repo-probing test could skip, so the count was 1.
**Those two rows therefore under-predict Linux and must not be read as Linux figures.** On Linux `/tmp` is
case-sensitive as well, so all four fire.

Measured on a case-sensitive APFS disk image, varying one volume at a time (SR-15; each line is a real run):

| repo volume | `TMPDIR` volume | `test_dashboard` skips | `test_scripts` skip | total |
|---|---|---|---|---|
| case-sensitive | case-INsensitive | 0 | 1 | **1** — this is the stand-in, and the source of the wrong figure |
| case-INsensitive | case-sensitive | 3 | 0 | **3** |
| case-sensitive | case-sensitive | 3 | 1 | **4** — the Linux configuration |

The three dashboard skips are produced purely by moving `TMPDIR`, with the repository left where it was. That
alone disproves the deleted explanation: nothing about the dashboard tests changed between the measurements.

The *policy* is already correct at 4 and is not changed: driven with both real reason strings the script prints
`note: 4 skip(s) for a case-sensitive filesystem (expected on Linux)` and `RESULT: OK`. The cap is 8.
`_fs_case_insensitive` is also correct as written — it probes where the dashboard actually writes — and is
deliberately left alone.

### The per-module baseline is a FLOOR, and it goes stale — read this before trusting it

`scripts/test_baseline.txt` records, per test module, `<module> <tests> <bare-environment skips>`. A module with
**fewer** tests than recorded fails the run, and under `--expect none` so does a module with **fewer** bare skips,
so deleting tests — or turning a torch-guarded test into a silent early-return pass — fails loudly **by module
name** instead of disappearing into a loose global total.

**It is a floor, not an equality check, and that has a cost that was previously undisclosed:**

- More tests than recorded always passes. The file goes stale the moment anyone adds a test, and **nothing warns
  you that it has.** It only prints a note for a module it has never seen at all.
- **Stale slack is deletable surface.** The gap between the recorded figure and the live figure is exactly how
  many tests can be deleted from that module before anything goes red. Measured by regenerating against the live
  tree during SR-15 (`--update-baseline`, bare, the run quoted above):

  | module | recorded | live | slack |
  |---|---|---|---|
  | `toy_tests.test_dashboard` | 103 | 150 | +47 |
  | `toy_tests.test_benchmark` | 182 | 214 | +32 |
  | `toy_tests.test_scripts` | 71 | 97 | +26 |
  | `toy_tests.test_claim_ledger` | 87 | 100 | +13 |
  | `toy_tests.test_robustness` | 87 | 93 | +6 |
  | `toy_tests.test_teacher_student` | 53 | 55 | +2 |
  | **total** | **874** | **1000** | **+126** |

  So 126 tests could have been deleted with nothing going red — and the figure had itself been reported as "+40"
  earlier the same day, from counts typed from memory rather than read off a run. The bare-skip column was stale
  too (`test_scripts` recorded 2, live 3). The global `MIN_TESTS` floor (default 650, inclusive) is much looser
  still and leaves hundreds more. **Take these numbers as an illustration of the mechanism, not as current: the
  only trustworthy slack figure is the diff your own `--update-baseline` produces.**
- So this check is **sharp only immediately after it is regenerated.** Treat an un-regenerated baseline as
  evidence about the *module list*, not about test counts.

Regenerate it in a **bare** environment, from a real run rather than by editing numbers:

```sh
PATH="${TMPDIR:-/tmp}/kit-bare/bin:$PATH" ./scripts/run_tests.sh --expect none --update-baseline
git diff -- scripts/test_baseline.txt      # the diff is the point: review it
```

PyYAML, filesystem-case and optional-developer-tool skips are excluded from the recorded skip figures — in
generation as well as in comparison, from one regex used by both — so a machine that has PyYAML, a case-sensitive
filesystem, or `ruff`, does not shift the baseline. **`--baseline` must name a FILE**: a directory is rejected as
a usage error at start-up, because `mv` into a directory succeeds and used to leave an untracked `base.staged`
inside it while reporting `RESULT: OK` (see "A re-opened write defect" at the end of this document). Regenerate
**last**, after all test-adding work for a milestone has landed; a baseline regenerated mid-milestone is stale
before it is committed, which is the defect this note exists to describe. A regeneration that *lowers* a module's
figure is a real signal — check why that module shrank before accepting the diff.

Skip-reason policy (case-insensitive, applied to **every** skip, recorded exactly by a hook inside the unittest
process rather than scraped from output):
- `--expect none`: each reason must name torch, numpy, pyyaml or pytest and say "not installed", "missing",
  "unavailable" or "not available"; at least 50 skips (`MIN_NONE_SKIPS`); at least one torch and one numpy reason;
  none may say "torch present"; no empty reasons.
- `--expect torch`: each reason must name CUDA, MPS or "torch present" and must not say "not installed", "missing"
  or mention numpy; at most 12 skips. (PyYAML **and pytest** must therefore be installed in this mode: without them the script tests skip as "PyYAML/pytest not installed", which torch mode denies. `requirements-dev.txt` installs both.)

- **Filesystem-case skips** (reason **begins with** the declared phrase `\Acase[- ]sensitive filesystem\b`, i.e.
  `case-sensitive filesystem` or `case sensitive filesystem` at position 0, ending on a word boundary): allowed
  in both modes, at most 8, and not counted toward the package-skip floor, the torch cap or the baseline.
  **Four** tests skip this way on a case-sensitive filesystem (three `need_ci` tests in `test_dashboard`, one in
  `test_scripts`), whose reasons name no package. Four is the figure Linux really shows (measured at `81d450a`;
  see "Filesystem-case skips: **4** on Linux" above for why the case-sensitive-APFS stand-in rows show 1).
  **This bullet used to say `reason contains "case-sensitive"`, and that rule was DELETED in round 6** — it was
  an unanchored `re.search`, and `case-sensitive filesystem: variants differ; libtorch is gone` was exempt in all
  three modes under it. Measured against the live policy, a reason worded as the withdrawn rule described is
  **rejected**: `filesystem is case-sensitive; case variants are different directories here` and
  `case-sensitive: this test is disabled for now` are both `POLICY:NONE_REASON`, `RESULT: FAIL`, in
  `--expect none`. The phrase above is not prose here — it is parsed out of `EXEMPT_CATEGORIES` in
  `scripts/run_tests.sh` and required to appear in this section by
  `test_the_normative_skip_policy_section_states_the_rules_the_script_really_applies`.
- **Optional-developer-tool skips** (reason **begins with** ``optional developer tool `<name>` is not on PATH``,
  and `<name>` is on the `TOOLS` allowlist): the second category that legitimately names no package, treated
  exactly like the first — allowed in every mode, at most 4 (`POLICY:TOOL_CAP`), and excluded from the
  package-skip floor, the torch cap and the baseline in **generation as well as comparison**. **One** test skips
  this way: the behavioural half of the fatal-`ruff` guarantee
  (`test_ruff_correctness_findings_are_fatal_not_advisory`). Any other `<name>` is **`POLICY:TOOL_UNDECLARED`**,
  a failure in **every** mode including `--expect any`. See "The documented steps used to fail without `ruff`"
  below for why the category exists and what the wording is load-bearing for.
- **What bounds those two exemptions.** Two rules, neither sufficient alone, and **the caps are the real bound**:
  1. **A reason that names any package this kit measures gets no exemption** — it is judged as a package skip
     instead, in the mode that is running (and `--expect any` runs no reason check, so there it is judged by
     nothing; that is the honest statement of it). The package list is the single `PKGS` tuple in
     `scripts/run_tests.sh`, from which the none-mode reason check, **both** package patterns and the baseline's
     PyYAML exclusion are now all built — the exclusion used to be an independently typed `\b(?:py)?yaml\b`
     beside a comment claiming it came from `PKGS`. The tests derive their cases from the tuple too. The rule
     that denies an exemption (`PKG_EXEMPT`) is a **containment** test — `"|".join(PKGS)`, case-insensitive — so
     any affix on either side is caught: `torchrun`, `torch2`, `libtorch`, `_torch`, `mytorch`, `yamllint`.
     **This paragraph used to read "as a word and as a prefix", with `\btorch\b` does not match `torchrun` as
     the example, and that was the rule round 6 REPLACED**: a prefix test has a word boundary of its own on the
     left, so it caught `torchrun` and could never catch `libtorch`, PyTorch's own C++ distribution. The
     normative summary therefore contradicted this document's own history sections, which say "containment" three
     times further down. The *accept* rules stay word tests (`PKG`, and the baseline's PyYAML exclusion) for the
     reasons given under "What is still exempt, stated plainly".
  2. **The tool name must be DECLARED** in the `TOOLS` allowlist, which is a closed set (currently just `ruff`)
     **derived from the suite's own skip sites** — not a judgement about which names look like packages. See
     "A spelling rule with evadable word boundaries" below. Since round 8, declaring a name also *works*: the
     span of a declared name is blanked out of the reason before the containment test runs, so a declared name
     that happens to contain a package substring is exempt. Before that the allowlist was **inert** for every
     such name — measured with `TOOLS = ("ruff", "yamllint", "shellcheck")`, ``optional developer tool
     `yamllint` is not on PATH`` was `POLICY:NONE_REASON` / `RESULT: FAIL` in `--expect none` (the mode both CI
     jobs run) both before and after declaring it, while the control `shellcheck` was exempt. The rail: an
     allowlist entry that **is** a measured package (`torch`, `numpy`, `yaml`, `pyyaml`, `pytest`) is
     `POLICY:INTERNAL` and the run stops before judging any skip, so round 4's defect cannot be declared into
     existence. The cost, stated plainly: a declared `torchfix` would be exempt, bounded by `TOOL_CAP` (4), the
     baseline, and the test-time requirement that a real skip site exist for every declared name.
- **Neither rule makes an exemption "sound"**, and this document and the script both said so for a round. An
  exemption *can* hide a skip — that is what an exemption is. What limits the damage is arithmetic: at most
  `TOOL_CAP` (4, one in use) + `FS_CAP` (8) skips can be exempt at all, and **re-parking an existing skip into
  either category lowers that module's recorded bare-skip column and fails `POLICY:BASELINE_SKIPS`**. So the
  exposure is a handful of *new* tests parked behind an environment claim, not an open door.

These rules are themselves tested with synthetic suites in `tests/toy_tests/test_scripts.py`, including the exact
boundaries (50 passes / 49 fails, 12 / 13, 8 / 9 filesystem-case, 4 / 5 optional-tool, `MIN_TESTS` inclusive).

### The documented steps used to fail without `ruff`, and that is why there is a second skip category

The steps above were **measured failing** on a machine with no `ruff`, which is the clean clone and the CI runner
they are written for. A test of the fatal-`ruff` behaviour carried
`@unittest.skipUnless(shutil.which("ruff"), "ruff is not installed (optional linter)")`, and that reason names no
package, so:

```
$ ./scripts/run_tests.sh --expect none --twice               # steps (a) and (c)
FAIL: POLICY:NONE_REASON skip reason does not say a package is missing:
  toy_tests.test_scripts.TestLintPolicy.test_ruff_correctness_findings_are_fatal_not_advisory
  :: 'ruff is not installed (optional linter)'
RESULT: FAIL

$ ./scripts/run_tests.sh --expect torch --twice              # step (d)
FAIL: POLICY:TORCH_MODE_MISSING torch expected but skipped as missing: ... :: 'ruff is not installed ...'
RESULT: FAIL
```

| documented step | clean machine, no `ruff` (before) |
|---|---|
| (a) `--expect none --twice` | **FAIL** `POLICY:NONE_REASON` |
| (b) `--expect any --twice` | unaffected (`NONE_REASON` sits inside `if mode == "none":`) |
| (c) bare venv + `--expect none` | **FAIL**, same path |
| (d) `--expect torch --twice` | **FAIL** `POLICY:TORCH_MODE_MISSING` (the reason says "not installed"; `requirements-dev.txt` installs pytest and pyyaml, not `ruff`) |

`ruff` is named in no requirements file, no `constraints.txt`, no CI step and no documented command; **nothing in
this kit installs it.** The bareness probe in the Steps (`for m in torch numpy pytest yaml`) cannot see it either,
and deliberately still does not: `ruff` is not an optional *dependency* of the kit, so its absence must not be
something the reader has to check. The defect was therefore **invisible on any machine that had `ruff`**, which is
why two independent measurements — including the one that introduced it — both read `OK (skipped=89)`. It
falsified the first line of this document ("needs only Python 3.12 or newer") and `README.md`'s "use it only on a
bare interpreter" in exactly the environments those sentences are about.

**The policy was right; the reason was wrong.** The fix follows the filesystem-case precedent already in the
script rather than inventing a parallel mechanism: a named category, with its own `POLICY:` token, a cap, and the
same exclusions. Three things about it are load-bearing:

- The phrase is **anchored** and structured, not a password: the tool is named in backticks and the reason must
  **begin** with the phrase, so prose that merely sounds like it ("optional linter absent") gets no exemption —
  and neither does prose that *carries* it. For one round `TOOL` was an unanchored substring search, and
  ``an optional developer tool `ruff` is not on PATHological systems`` collected the exemption; measured.
  The anchor is written twice (`\A` in the pattern, `.match` at the call) and **the two terms are mutually
  redundant**: `\A` can match only at position 0, so `.search` on an `\A` pattern *is* `.match`, and `.match` on
  a pattern without `\A` is anchored by the method. Measured consequence for anyone mutation-testing this: a
  mutant that drops either term alone is an **equivalent mutant** and its survival says nothing; the hole needs
  both. The two-term mutant is killed by two cases in
  `test_tool_reason_cannot_launder_a_missing_package_or_torch_present` (leading prose, clean
  `is not on PATH` ending, a *declared* tool name) — added in the fifth round, because the six prose candidates
  that were there before were all rejected by the trailing `\b` or by never containing the phrase, so **the
  table did not exercise the anchor at all**: with those two cases deleted, the two-term mutant survives.
- It says **"is not on PATH", not "is not installed"**, which keeps the category's own wording honest — but that
  is a courtesy to the reader and **not** the anti-laundering defence, which is the rule in the skip-policy list
  above: the reason may not name `torch`, `numpy`, `pyyaml` or `pytest` at all. This bullet used to claim that
  torch mode's three deny spellings were the defence, and they were not: see the next section.
  **The retraction did not reach the code comment**, which went on asserting the withdrawn reasoning
  (*"torch mode denies the latter on EVERY skip, tool skips included, so the category cannot launder a missing
  package"*) in `tests/toy_tests/test_scripts.py` for two further rounds — the third time in this project that a
  withdrawn guarantee outlived its withdrawal in a comment. A docstring assertion cannot reach a comment and
  neither can a doc grep, so there is now a source-text test over the comment lines of the script and that file
  **and over the whole of this document** (`test_no_withdrawn_guarantee_is_restated_in_a_comment`): each
  withdrawn claim may appear only inside a window that marks it as history, and must still appear *somewhere*,
  because deleting the record is how the sentence comes back. **This document was added to that scope in round
  8, and it is where the next two instances were found:** the normative skip-policy section that a clean clone
  is sent to stated the withdrawn filesystem-case rule (*reason contains "case-sensitive"*) and the withdrawn
  package rule (*as a word and as a prefix*) as if both were current.
  **A line window cannot adjudicate a claim whose own line carries an unrelated retraction marker**, which is
  what round 8 found in `scripts/run_tests.sh`: the canary comment used to say *"'connection refused' from the
  local stack and nothing leaves the host"* in the same sentence as *"It used to be 192.0.2.1:9"*, a correct
  history note about a different fact, so a line window of **any** half-width from 0 to 7 reads the second
  marker as this claim's.
  **THE PER-NEEDLE LINE WINDOWS ARE NOW GONE, AND SO IS THE ENUMERATED FILE LIST — round 10's F3.** Both were
  short in the same way, and the widths went first because they were never a fact about a needle: a marker's
  distance is a property of **prose** and moves whenever a paragraph is rewritten, measured three times in one
  round (a needle that failed at half-widths 0–4 and passed from 5; a needle whose minimum width was **2**
  where this bullet had claimed 6; a needle whose binding occurrence moved to another file twice). Every needle
  is adjudicated by the **sentence rule** that the `ci.yml` ceiling already applied to one whole file: the
  marker must stand **before** the claim and **inside its own sentence**, in the prose block joined across the
  hard wrap. Four live sentences in this kit had to be reworded to satisfy it — in `scripts/run_tests.sh`, in
  `.github/workflows/ci.yml` and twice in this document — and that is the cost, paid once instead of
  re-measured per paragraph.
  **And the file list is DERIVED instead of enumerated.** It had gone short three times — widened to this
  document in round 7, to `.github/workflows/ci.yml` in round 9, and found short again in round 10 by
  `scripts/lint.sh`'s 43-line normative header **and by `README.md`, the file that retracted "nothing leaves
  the host" in the first place**, where unmarked prose asserting *"…cannot launder a missing package, and
  nothing leaves the host"* was measured **green** in both. The scope is now every file in `git ls-files`
  except the one this project's own `CLAUDE.md` designates as the durable journal, with the per-file reading
  rule taken from the suffix (full-line comments in `.py`/`.sh`/`.yml`, the whole prose of a document). A new
  file carrying normative prose about what the kit does and does not guarantee therefore lands in the scope
  **without an edit to the test**, and the test additionally asserts that nothing tracked is outside the scope
  but the journal, so the derivation cannot quietly shrink either.
  **Why the journal is out, measured rather than assumed:** at the time of this round's measurement
  `docs/PROGRESS.md` held **15** needle occurrences, **12** of them failing the sentence rule, every one a *quotation* of a
  finding inside a dated entry — the journal records claims, it does not make them — so adjudicating it with a
  prose rule would be a category error. The exclusion is read out of `CLAUDE.md`'s own sentence rather than
  typed into the test, so renaming the journal moves the exclusion with it and deleting that sentence turns the
  suite red instead of silently widening the scope.
  **One scope boundary is declared rather than closed, and the measurement is what fixes it there.** A `.py`
  file is read for **full-line** comments only, and that is no longer an accident: widening it to docstrings
  and trailing comments immediately flags `src/toy/robustness.py:62` (*"`dataclasses.replace` cannot launder a
  summary that was tampered with"*) and `tests/toy_tests/test_benchmark.py:498` (*"# cannot launder a primary
  id either"*) — two innocent uses of the same two words in a different domain, in files this discipline does
  not own. Closing the boundary needs needles specific to the skip policy, and the withdrawn-claim needle `cannot launder` is not one of those.
  The test's name still says "in a comment" because `docs/PROGRESS.md` cites it by name.
  The same sweep found two definitions that were **withdrawn**: `scripts/run_tests.sh` defined a sound exemption
  as one that "cannot be spent on hiding a package skip", and the filesystem-case exclusion claimed it "cannot
  hide a torch test" — both false in the same way, since an exemption can hide one and the bound is the
  category's cap plus the baseline. Both are corrected in place.
  **`.github/workflows/ci.yml` was brought into this discipline in round 8** — its normative header was outside
  it entirely, while asserting that nothing in the workflow touched a remote host except one pip-install step,
  which is false for both jobs (each fetches `actions/checkout@v4`, `actions/setup-python@v5` and this
  repository from github.com, independently of hermeticity). **Its replacement was reworded again in round 10,
  and a needle now covers the rephrasing.** That header used to read *"NO STEP THAT RUNS … reaches a remote
  host"* — arrival, which is the property `README.md` retracted, rather than the address a step asks for — and
  it was rescued only by the sentence after it, so a reader who stopped at the colon got the withdrawn claim.
  It states the address now, and the retracted wording `reaches a remote host` is a needle in its own right.
- The baseline exclusion applies to **generation**, not only comparison. `scripts/test_baseline.txt` records a
  bare-skip column per module; without the generation-side exclusion a machine without `ruff` would record one
  more skip for `toy_tests.test_scripts` than a machine with it, and the committed file would depend on whose
  laptop last ran `--update-baseline`.

**What a skip here costs, stated plainly:** on a machine without `ruff` the *behavioural* half of the fatal-`ruff`
guarantee is not measured — the run says so, by name, in the skip list. The *structural* half
(`test_lint_script_makes_ruff_correctness_fatal_structurally`) never skips and fails everywhere if anyone removes
`FAIL=1` from the `ruff` branch of `scripts/lint.sh`, which is the regression that let an undefined `Any` ship. A
structural assertion cannot show that `ruff` runs, or that `E9,F63,F7,F82` are the right rules; that is what the
skipped test is for, and declaring the gap is the point of the category.

### An exemption that could be laundered, and the wording rule that did not stop it

The two sentences above were **false for one round** when they promised the category **cannot launder** a
missing package, and the test named in them passed throughout, because it tried only the two laundered reasons that
happened to contain one of the three spellings torch mode denies (`not installed`, `missing`, `numpy`).
Everything else worked. Measured, by driving the live script on synthetic suites:

| skip reason | mode | before | now |
|---|---|---|---|
| ``optional developer tool `torch` is not on PATH`` | `torch` | **RESULT: OK** | `POLICY:TORCH_MODE_UNEXPLAINED` + `POLICY:TOOL_UNDECLARED` |
| the same with `pytest`, `pyyaml` or any other measured package as the tool name | `torch` | **RESULT: OK** | `POLICY:TORCH_MODE_UNEXPLAINED` + `POLICY:TOOL_UNDECLARED` |
| the live `ruff` reason with `(torch unavailable)` appended | `torch` | **RESULT: OK** | `POLICY:TORCH_MODE_UNEXPLAINED` |
| ``an optional developer tool `ruff` is not on PATHological systems`` | `none` | **RESULT: OK** | `POLICY:NONE_REASON` |
| ``optional developer tool `torch` is not on PATH`` | `none` | **RESULT: OK** (and it spent one of the 50 skips) | `POLICY:NONE_REASON` + `POLICY:TOOL_UNDECLARED` |
| `case-sensitive filesystem; torch unavailable` | `torch` | **RESULT: OK** | `POLICY:TORCH_MODE_UNEXPLAINED` |

Two things that review had not seen. First, `unavailable` is a spelling `--expect none` *itself* accepts as "a
package is missing", so the deny list and the accept list disagreed about the same words — a wording rule kept by
hand in three places. Second, **the filesystem-case category had the identical hole**: it was not a defect of the
tool category but of the shape of an exemption.

The fix is the one-line rule in the skip-policy list above (*a reason that names a measured package gets no
exemption*), applied to both categories and derived from one `PKGS` tuple, plus the anchoring of the tool phrase.
Bounds, for the record: the hole was never unbounded — `POLICY:TOOL_CAP` is 4 (1 in use) and the per-module
baseline skip column would have caught a *re-parked* existing test, because moving a torch skip into an exempt
category lowers that module's recorded count and fails `POLICY:BASELINE_SKIPS`. What it did allow was up to three
*new* tests parked behind a package claim with the suite green.

**The obvious fix was measured and rejected**: widening torch mode's deny list to `unavailable|not available|
absent`. That list is applied to *every* skip, and two reasons the suite really emits in that mode are
`torch present; unavailable path is exercised in the subprocess test` and `CUDA not available: CPU-vs-CUDA
comparison (ER-09) is UNKNOWN, not passed`, so widening it turns documented step (d) red on every machine. Both
reasons are now driven through `--expect torch` by `test_live_torch_mode_skip_reasons_stay_accepted`, so the
proposal fails a test instead of a CI job. The residue of not widening it: a reason naming a package in one of
those spellings is reported as `POLICY:TORCH_MODE_UNEXPLAINED` rather than `POLICY:TORCH_MODE_MISSING` — a less
precise token for a run that is red either way.

### A spelling rule with evadable word boundaries: the allowlist that replaced it

The rule above (`PKG = \b(?:py)?(?:torch|numpy|yaml|pytest)\b`) **is** a list of spellings, and a record that
said otherwise was wrong. As the only gate on the tool category it was an **open set**: every name that is not
one of those four words collected the exemption. Measured by driving the live script on synthetic suites, each of
these was **EXEMPT in `--expect none` AND `--expect torch`**, and round 4's actual defect
(``optional developer tool `torch` is not on PATH``) is **one suffix** from the first two:

| skip reason | before | now |
|---|---|---|
| ``optional developer tool `torchrun` is not on PATH`` (PyTorch's own console script) | **EXEMPT, RESULT: OK** | `POLICY:TOOL_UNDECLARED` |
| ``optional developer tool `libtorch` is not on PATH`` (its C++ distribution) | **EXEMPT, RESULT: OK** | `POLICY:TOOL_UNDECLARED` |
| the same with `torchvision`, `torchaudio`, `torch_geometric`, `torch2`, `_torch`, `numpy2`, `pytestx`, `mypy`, `black`, `yamllint` | **EXEMPT, RESULT: OK** | `POLICY:TOOL_UNDECLARED` |
| the live `ruff` reason + `; torchrun is gone` | **EXEMPT, RESULT: OK** | not exempt (`PKG_EXEMPT`, a *containment* rule since round 6; it was a prefix rule here) |
| `case-sensitive filesystem …; torch2 is gone` | **EXEMPT, RESULT: OK** | not exempt (same) |
| the live `ruff` reason + ``; `mypy` would have run it`` | **EXEMPT, RESULT: OK** | **still exempt** — the "every backticked name must be declared" rule was WITHDRAWN in round 6 as a legitimate deny; see below |
| ``optional developer tool `pytest-cov` is not on PATH``, `torch-cpu`, `TORCH`, `pytorch`, `py-torch`, `numpy-stubs` | already rejected | unchanged |

**The fix is a positive allowlist, and the allowlist is derived, not hand-maintained.** `TOOLS` in
`scripts/run_tests.sh` is the one declaration the policy reads;
`test_the_TOOLS_allowlist_is_exactly_the_tools_this_suite_gates_on` parses that tuple **and** parses every
tool-gated skip site out of `tests/toy_tests/` (the `@unittest.skipUnless(...)` / `skipTest(...)` reasons that
match the runner's own `TOOL` pattern, itself parsed from the script) and requires the two sets to be **equal**.
So a **new** tool-gated test is a red suite naming the tool and the tuple to declare it in — and
`POLICY:TOOL_UNDECLARED` at runtime in every mode — never a silent exemption; and a name left in the tuple after
its test is deleted fails the same test. **The word-boundary problem is closed on both sides of the word, and
that sentence used to read "closed twice over", which was false**: it was closed by the allowlist on the *name*
and by `PKG_EXEMPT` as a *prefix* test on the rest of the reason, and a prefix test has a word boundary of its
own on the left. Measured on the live script, exempt in all three modes: ``optional developer tool `ruff` is not
on PATH; libtorch is gone`` and `case-sensitive filesystem …; _torch is gone` — `libtorch` is PyTorch's own C++
distribution, and there is no `\b` before `torch` in it. `PKG_EXEMPT` is the same `PKGS` tuple as a
**containment** test now (`"|".join(PKGS)`, case-insensitive), so any affix on either side is caught. It is
used **only** to deny an exemption, never to accept a reason: as the bare-mode accept rule it would read
``optional developer tool `torchrun` is not on PATH; it is missing`` as an honest package skip, and as the
baseline exclusion it would drop any reason mentioning `yamllint` out of a module's recorded skip column.

**What is still exempt, stated plainly.** A *declared* tool's reason (or a filesystem-case reason) with a prose
tail that names no measured package — ``optional developer tool `ruff` is not on PATH; mypy is gone`` — is still
exempt, because no regex can tell a true claim from a false one. **The clause "and backticks no other name" used
to stand here and has been withdrawn**: a backticked name is no longer read as a tool name, because that rule
denied honest reasons (see the round-6 section below, F2). The bound is the one stated under the skip policy:
`TOOL_CAP` 4 (one in use) + `FS_CAP` 8, and the baseline catches any *re-parked* existing skip. Four more
measured residues: a tool name containing a newline or a zero-width space is rejected by the phrase's name class
(`[\w.+-]+`) rather than by the allowlist, so it lands on `POLICY:NONE_REASON` instead of
`POLICY:TOOL_UNDECLARED`; `--expect any` applies no reason check, so a *package-naming* exempt-shaped reason is
accepted there (it buys nothing — that mode has no skip floor and compares no skip column); and because the
package rule is a **substring** rule and nothing more, a tail that spells a package with a character the name
does not contain (`; t0rch is gone`) or that describes it without naming it (`; the deep-learning framework is
gone`) keeps the exemption. Those last two are asserted as **accepted** by
`test_no_environment_exemption_may_name_a_package_the_kit_MEASURES`, so the sentence cannot drift away from
what the rule does.

### A guard installed at hand-chosen sites: the exemption-category registry that replaced it

Round 5 gave the optional-developer-tool category **three** anchoring guards (`\A` in the phrase, `.match` at
the call site, a trailing `\b`) **and** a closed allowlist (`TOOLS = ("ruff",)`). The filesystem-case category
is the same *kind* of exemption and got **none of the four**: it was `FS = re.compile(r"case[- ]sensitive",
re.I)`, applied **unanchored** with `.search`. Reviewing two hand-written guards for symmetry is what failed, so
the two categories are now **one declaration** — `EXEMPT_CATEGORIES` in `scripts/run_tests.sh` — and every
guard, cap, exclusion and failure token is applied by the loop that reads it.

**F1 — the filesystem-case exemption was an open set.** Measured on the live script, **zero policy tokens in all
three modes** before, with the fix beside it:

| skip reason | before | now |
|---|---|---|
| `case-sensitive filesystem: variants differ; libtorch is gone` (also `_torch`, `mytorch`) | **EXEMPT, OK / OK / OK** | `POLICY:NONE_REASON` / `POLICY:TORCH_MODE_UNEXPLAINED`; not exempt in `any` |
| `case-sensitive filesystem: …; optional developer tool `black` is not on PATH` | **EXEMPT, OK / OK / OK** | `POLICY:EXEMPT_AMBIGUOUS` in **all three** modes |
| ``the optional developer tool `mypy` is not on PATH (case-sensitive filesystem)`` | **EXEMPT, OK / OK / OK** | `POLICY:NONE_REASON` / `POLICY:TORCH_MODE_UNEXPLAINED`; not exempt in `any` |
| `case-sensitive: this test is disabled for now` | **EXEMPT, OK / OK / OK** | same — `case-sensitive` alone is not the phrase |
| the live `ruff` reason + `; torchrun is gone` (control: the tool category worked) | already rejected | unchanged |

The declared phrase is `\Acase[- ]sensitive filesystem\b`. Two consequences worth stating: a **prefix** evasion
(`libtorch`, `_torch`) was permitted while the symmetric **suffix** evasion (`torchrun`, `numpy2`) was denied,
because `PKG_EXEMPT` was a prefix test — it is a containment test now; and the suite's own laundering table
enumerated **only** suffixes, with `libtorch` and `_torch` ninety lines further down as tool *names*, where the
allowlist rejects them. The names were in the file, in the wrong table.

**The same hole bypassed the round-5 derivation test.** `_suite_tool_gates` finds a tool gate with `.match`, so
a skip reason that does not *begin* with the tool phrase is invisible to it. Measured on a byte-identical copy
of the repo: a probe site reading ``optional developer tool `mypy` is not on PATH`` makes
`test_the_TOOLS_allowlist_is_exactly_the_tools_this_suite_gates_on` **fail** (the derivation works), and the
same reason **led** by the filesystem-case phrase — ``case-sensitive filesystem: optional developer tool `mypy`
is not on PATH`` — makes it **pass**, while the skip was exempt at run time in all three modes: a test gated on
an undeclared tool, green at test time *and* at run time. (Appending ` (case-sensitive filesystem)` does **not**
bypass it; `.match` still sees the leading phrase. The bypass needs the other phrase in front.)

**The bound, measured, and not overstated.** Re-parking an *existing* baseline-counted skip was
`POLICY:BASELINE_SKIPS` throughout — the hole could not hide a skip the baseline counts. *Adding* laundered
filesystem-case skips was OK up to 8 and `POLICY:FS_CAP` at 9. So the reach was **≤ 8 newly parked tests**, ≤ 4
on a Linux runner where the real case-sensitivity skips occupy the bucket.

**F2 — every backticked token was treated as a tool name, and that was a legitimate deny.** The rule "every
backticked name in a tool-shaped reason must be a declared tool" turned honest reasons red: the live `ruff`
reason plus `` (see `scripts/lint.sh`) `` was `POLICY:TOOL_UNDECLARED` in **all three** modes, `RESULT: FAIL`,
with advice that cannot be followed (*"`scripts/lint.sh` is not in the TOOLS allowlist … declare the tool
there"*), and the same for a backticked rule code (`` `F821` ``). That is round 3's defect shape exactly —
honest reason, red suite, unfollowable guidance — and it was latent only because the live reason happens to
backtick just `ruff`. What replaced it is narrower and derived from the registry: **every occurrence of a
declared category phrase** is checked, not every pair of backticks. The cost, stated plainly: a bare
`` `mypy` `` in a prose tail is exempt now — the same verdict `; mypy is gone` already got, so what the old rule
really did was make the verdict depend on typography. ``; also optional developer tool `black` is not on PATH``
is still `POLICY:TOOL_UNDECLARED`, and `; `torchrun` is gone` is still denied by the package rule.

**F3 — a per-category cap was evadable by appending the other category's phrase.** Measured in `--expect any`
with 5 identical skips: the live `ruff` reason ×5 → `POLICY:TOOL_CAP` (×4 → OK, the documented 4/5 boundary);
the same reason + `" (case-sensitive filesystem)"` ×5 → **OK**, reported as *"note: 5 skip(s) for a
case-sensitive filesystem"*, ×8 → OK, `FS_CAP` only at 9. The combined 12-skip ceiling was never breached; what
broke was the per-category bound these documents name as the thing that bounds tool parking — and the run then
**printed tool parks as the Linux filesystem figure** a reader is told to expect. A reason may now claim exactly
one category: carrying a second category's phrase is `POLICY:EXEMPT_AMBIGUOUS` in every mode.

**What the registry gives that two guarded sites could not.** Each row declares a token, an anchored
`\b`-terminated phrase, a cap, a closed allowlist (and where it lives) if the phrase carries a name, and how the
run reports it. A row that is wrong is `POLICY:INTERNAL` **before any skip is judged** — driven for five bad
declarations, including round 4's open set in one line (a name class with no allowlist) — and
`tests/toy_tests/test_scripts.py` **parses the tuple** and generates from it: the structural contract, a
laundering table per category in all three modes, the cap boundary for each cap, the cross-category case over
ordered pairs, the per-row equality between a category's allowlist and the names the suite's own skip sites gate
on, the opposite direction (a site carrying a phrase must claim the category), and the `POLICY:` tokens a
category must have a test for.

**Two of those sentences were measured FALSE in round 7 and the paragraph above used to overstate the rest.**
What it claimed was that a category "cannot arrive with fewer guards or no tests". Both halves had a hole:

- the allowlist equality was bound to the `TOOLS` **tuple**, not to the registry **row** the policy reads. A
  one-token change at the row — `…, 4, "TOOLS", TOOLS,` → `…, 4, "TOOLS", ("ruff", "shellcheck"),` — left
  `TOOLS = ("ruff",)` literally true and that equality green, while `shellcheck` was exempt in all three modes
  with no `POLICY:` token (control on the unmodified copy: `POLICY:TOOL_UNDECLARED` in all three). The equality
  is now asserted **per row**, for every category whose phrase carries a name, by
  `test_every_named_categorys_allowlist_is_exactly_the_names_this_suite_gates_on`.
- the contract was asserted on **source text** and the loop reads a **value**. One line after the literal's
  `)` — `EXEMPT_CATEGORIES = EXEMPT_CATEGORIES + (("ZED", r"\Aonly on zed\b", 2, "", (), "for zed"),)` — gave a
  fully functional category with a working cap (`n=2` → OK, `n=3` → `POLICY:ZED_CAP`), no token, in all three
  modes, invisible to every generated check because none of them can see past the literal. A variant whose
  `note` column copied the filesystem-case note verbatim printed its parked skips as
  *"note: N skip(s) for a case-sensitive filesystem (expected on Linux)"*. The registry is now required to be
  bound **exactly once**, by a module-level assignment whose value is a literal tuple of literal tuples, parsed
  as a program rather than grepped (`test_the_category_registry_is_assigned_exactly_once_and_never_rebound`),
  and the loop rejects a duplicate or blank token **and a duplicate or blank note** as `POLICY:INTERNAL`.
  **Round 8 found both halves of that fix short, and this is what they are now.** (i) The note test was
  **exact-string**, so the same variant worded one word longer — *"(expected on Linux runners)"* against
  *"(expected on Linux)"* — was accepted and printed its parked skips as the Linux figure this document tells a
  reader to expect. Notes are now compared **folded** (lowercase words, punctuation discarded) and a note may
  not equal another, contain another, or be **within one word edit** of another; each of the three was measured
  accepted before and `POLICY:INTERNAL` after, with an unrelated note as the control.
  **The third clause used to be a four-word PREFIX test, and it refused an honest declaration — round 10's F2,
  which is round 3's shape in the note rule.** A row noted *"for an absent optional runtime library"* declared
  beside the live *"for an absent optional developer tool"* was `POLICY:INTERNAL` in all three modes with the
  run stopping before a single skip was judged, **and the message blamed the live, correct row**, because the
  inserted row is scanned first and the complaint was attached to the row being declared. No reader confuses
  "runtime library" with "developer tool"; the notes differ exactly where English notes differ, in the last two
  words, and this project's own naming convention (`for an absent optional …`) makes a four-word collision the
  **likely** case rather than the pathological one. The threshold of **one** word edit is forced by measurement
  rather than chosen: at one edit that pair is accepted (it is two edits apart) while every variant the rule
  exists for is still refused — the m7b note, one word longer, by the containment clause; the same note shouted
  or repunctuated, by folding to equality; and a single-word substitution (*"(expected on Linux)"* →
  *"(expected on Zedland)"*), by this clause. A threshold of two would re-refuse the honest pair. The message
  now names **both** rows with their positions in the literal and blames neither, because by the time the check
  runs both are in the literal and it cannot know which one is new; it says to reword whichever row is being
  added, by more than one word.
  **The deny cost, which this document used to disclose only in the permit direction.** Two declared notes must
  differ by more than one word edit and neither may contain the other, so a second category **cannot** be
  distinguished from an existing one by refining a single word: *"for an absent optional developer tools"*
  beside *"for an absent optional developer tool"* is refused, and so is any note that is another plus or minus
  one word. That is fail-closed on purpose — the note is the only thing a reader of the output sees — but it is
  a real cost to an honest author, and the run states it, names both rows and stops before judging any skip.
  The permit residue is unchanged and still open: a paraphrase two or more edits away
  (*"because this filesystem distinguishes case"*, or *"(typical on Linux boxes)"* against
  *"(expected on Linux)"*) is accepted, and what bounds it is the registry attestation plus the caps and the
  baseline, not this rule. (ii) The static
  "bound exactly once" check conceded that a binding made through `globals()[…]` or `setattr` is invisible to
  it and then claimed the runtime half covered such a row **however it arrived**. That was false: the runtime
  half rejects a **malformed** row, and the measured mutant is well-formed. One line after the literal,
  `globals()["EXEMPT_CATEGORIES"] = EXEMPT_CATEGORIES + (…)`, gave `RESULT: OK` with no `POLICY:` token in any
  mode, a working cap, parked skips printed under a note of its choosing, and the whole script suite green at
  151 OK. So **every run now prints the registry it judged with** — one `exemption registry row:` JSON line per
  row, rendered from the value the policy reads — and
  `test_the_registry_the_run_really_uses_equals_the_declared_literal` requires that listing to equal the parsed
  literal, row for row and column for column.
  **Round 9's version of that fix carried a sentence about its own reach, and the sentence was wrong by exactly
  one line — round 10's F1.** It said a row arriving by *any* route was a red suite and that the end-of-block
  snapshot closed *"the one gap this placement leaves"*. The placement left **two**: the listing was printed
  from the live registry **before** the snapshot was taken, so a `globals()["CATS"] = CATS + […]` line inserted
  **between the listing and the snapshot** was invisible to both halves — the listing came from the pre-mutation
  value, the snapshot from the post-mutation one, and the compare at the end of the block therefore passed.
  Measured on the round-9 script in `--expect none`, the mode both CI jobs run: `exemption registry: 2 row(s)`
  with the listing **byte-identical** to the declared literal, then *"note: 4 skip(s) for a case-sensitive
  filesystem (expected on Linux)"*, `RESULT: OK`, rc=0, **no `POLICY:` token**, against a base control of four
  `POLICY:NONE_REASON` and rc=1 — round 7's m7b and round 8's F1 both fully restored, because a rebind bypasses
  the declaration loop entirely so no declaration guard applies.
  **Three things changed, and no sentence about reach replaced them.** The snapshot is taken **first** and the
  listing is rendered **from the snapshot**, so there is no value the listing can come from that the compare
  does not re-check. The compare runs **twice** — after the caps and again after the registry's last consumer,
  the baseline branches that reach it through `base_excl` — so no position in the policy program sits after the
  last compare. And the listing carries **every** column of a row, the **loose pattern** included: it used to
  omit column 3, and measured on the round-9 script, replacing that column with a never-matching pattern left
  the listing byte-identical while a reason carrying a second category's phrase in its tail went from
  `POLICY:EXEMPT_AMBIGUOUS` to `RESULT: OK` **and exempt**, and one carrying an undeclared tool name in its tail
  from `POLICY:TOOL_UNDECLARED` to `RESULT: OK` **and exempt** (a package-naming tail stayed denied, because
  `PKG_EXEMPT` reads the whole reason). Two behavioural tests do kill that mutant — but not the attestation,
  which is the thing that claims to cover routes. The column count is checked against the row too, so a new
  `CATS` column cannot be added and left out of the attestation silently.
  **What replaces the reach claim is an enumeration, not a wider sentence.**
  `test_every_insertion_position_around_the_registry_attestation_is_driven` inserts one working, well-formed row
  at **each** position around the attestation — before the snapshot, between the snapshot and the listing,
  inside the listing loop, after the listing, after the cap loop, after the first compare, and after the last
  consumer — and asserts the outcome at each: the first position leaves the run green and is killed by the
  listing/literal comparison, every later one is `POLICY:INTERNAL` with the listing still equal to the
  declaration, which is what makes the script-side compare the load-bearing half rather than the listing. The
  enumeration is the claim; the prose above states where the boundary is and nothing about what lies beyond it.

**What is true now, stated as what the tests do rather than as what they aspire to, with the count measured
instead of hedged.** A category declared in the one literal is covered the moment it is declared, and a
declared *untested* category is refused by **7 test methods / 8 failure records** — measured by placing a
functional extra row inside the literal on the round-8 tree: `test_every_exemption_category_is_declared_with_
the_same_guards`, `…_has_its_own_cap_and_its_boundary_is_driven`,
`…_is_claimed_properly_by_the_sites_that_use_it`, `…_rejects_the_same_laundering`,
`test_no_reason_may_claim_two_exemption_categories_at_once`,
`test_every_policy_token_is_asserted_by_some_test` and
`test_the_normative_skip_policy_section_states_the_rules_the_script_really_applies` (the figure replaces an
"at least six" that had never been re-enumerated). A bad row is `POLICY:INTERNAL` and **the run stops before
judging any skip** — with a near-duplicate note that is now 112 failure records across the module, because
every synthetic run that expects a green script goes red. A second binding of the name, or a row whose
allowlist does not match the suite's own gating sites, is a red suite.
**The residue, since a residue is what the last four rounds were made of.** A binding made through
`globals()[…]` or `setattr` is still not an assignment the static parse can see — what is new is that it no
longer has to be: the run's own registry listing is compared against the declaration, so the route stops
mattering. What remains unreachable by any of this, **restated in round 10 because its own author understated
it in the project's favour**: a row that is **well-formed, declared in the literal and dishonest** is not
bounded by the declaration, but the declaration is **not the free column the earlier wording described**. Such
a row is refused by **three** derivations at once — the carrier-equality check (`every name on a category
allowlist is really exemptable`, and `every declared category is claimed properly by the sites that use it`,
which requires a real skip site in `tests/` carrying the row's phrase), the per-row cap-and-boundary test, and
the normative-section test that requires this document to state the row's phrase. So a declared dishonest row
costs its author **a committed skip site in the suite and a committed sentence in this document** as well as
the row. The residue stands — the *behaviour* of such a row is bounded by the caps and the baseline and by
nothing in the declaration — but it is not cost-free, which is what the earlier sentence implied. And two
notes that a reader would confuse but that contain nothing of each other and are more than one word edit apart
(a paraphrase) are still accepted.

**A real site was wrong, and the loose scan found it.** `tests/toy_tests/test_scripts.py` skipped with
`"filesystem is case-sensitive; case-varied path does not alias the repo"` — the phrase **mid-sentence**,
claiming nothing. Under the anchored phrase that skip is judged as a package skip, so the documented
`--expect none` run would have gone red with `POLICY:NONE_REASON` on every case-sensitive filesystem, i.e. on
both CI runners. It is worded as the declared phrase now, and every skip site in `tests/` that carries a
declared phrase is driven through the live script and required to be reported as exempt.

**What that scan could not read, and what is done about it (round 8).** The derivations above collect skip
reasons that are **one string literal**, and they used to look in `tests/toy_tests/` only. Two real sites build
their reason with an f-string (`tests/toy_tests/test_tensor_ops.py:29` and `:31`) and `tests/test_toy.py` is in
the discovered suite (`discover -s tests`) and was outside the scan altogether. Measured today: 17 literal
sites, 2 computed ones, and no skip at all in `tests/test_toy.py`, so widening the scan to the whole discovered
suite changed no derivation. It still matters, because the filesystem-case category carries **no name** for the
runtime to check: a *computed* reason claiming that phrase would have been bounded by `FS_CAP` (8) and the
per-module baseline and by nothing else, with no test-time derivation able to see it. So a reason the static
derivations cannot read may not **carry** a declared phrase in any fragment a static reader can see
(`test_no_computed_skip_reason_carries_a_declared_exemption_phrase`, with a positive control for the extractor);
write it as one literal, or gate the test on something the derivation can read.

### `lint.sh` probed one optional linter through PATH and the other through the interpreter

`ruff` was gated on `command -v ruff`; `pyflakes` was gated on `python3 -m pyflakes --version` — **through the
interpreter**. `_toolfree_bin()` in `tests/toy_tests/test_scripts.py` builds a PATH directory holding only a
`python3` symlink so that a lint run genuinely has no optional linter on PATH, and its docstring claimed *"A
directory we construct cannot drift that way."* **It can:** the symlinked interpreter brings its own
site-packages, so with pyflakes importable `RAN_ANY=1` and the *"no optional linter (ruff/pyflakes) installed;
skipped"* branch never fired — `test_missing_optional_tools_never_fail` measured the opposite branch from the
one it names, and **failed**:

```
# CPython 3.13.5 (conda), pyflakes 3.4.0 importable
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python3 -m unittest \
    tests.toy_tests.test_scripts
  -> Ran 137 tests, FAILED (failures=1)
     FAIL: TestLintPolicy.test_missing_optional_tools_never_fail
# CPython 3.12.4, neither linter importable -> Ran 137 tests, OK
```

The asymmetry *is* the defect — two gates on the same kind of thing, written differently, and the one nobody
looked at drifted — so **both linters are gated on PATH** now, and
`test_every_optional_linter_is_gated_on_PATH_not_on_the_interpreter` asserts that structurally over the
`== optional linters ==` section (comment lines stripped, so the record of the old probe is allowed to stay).
**What the change costs, measured:** `python3 -m pyflakes` works wherever pyflakes is *importable*, and
`command -v pyflakes` needs its console script on PATH. On the development host both are present and both print
the same three advisory findings, so nothing is lost there; what is lost in general is the advisory run (and,
with `LINT_STRICT=1`, its fatality) where pyflakes is importable but its console script is not on PATH. The
trade is taken because the `-m` form also tied the linter to whichever `python3` the PATH resolves while the
console script carries its own interpreter, so the probe and the run could disagree about what is installed.
That pyflakes still *runs* when it is on PATH is pinned by
`test_a_pyflakes_on_PATH_runs_and_stays_advisory_unless_LINT_STRICT`, which drives a **stub** `pyflakes` rather
than the real one — so it never skips, and no second name has to go on the `TOOLS` allowlist. **Neither CI job
installs a linter**, so there this test measures the branch it names and passed before the fix as well.

## Interpreting skips

A skip is a test that did **not run**, not a pass. Without torch the autograd, device and precision tests are
skipped with the reason "torch not installed ..." (CPU-vs-CUDA/MPS comparisons are UNKNOWN, never "passed").
With torch present, the remaining skips are hardware — no CUDA (always on a laptop), no MPS (non-Apple) — plus
one wiring test that only applies when torch is absent, **and, on a machine without `ruff`, the
optional-developer-tool skip**: that last one is why `--expect torch` on this host measures 3 skips without
`ruff` and 2 with it, and the sentence used to list only the first two kinds. A clean clone passing with most of its skips in that state
means the stdlib core passed; **it says nothing about torch behaviour.** (An earlier version of this paragraph
gave a rounded figure of about 88 skips where its own table and its own measurement both said 89. Take the number
from your own run, not from here.) List them with `python3 -m unittest discover -s tests -v | grep skipped`.

## Optional: torch + numpy

```sh
python3 -m venv .venv && . .venv/bin/activate
pip install -c constraints.txt -r requirements-dev.txt numpy torch
./scripts/run_tests.sh --expect torch --twice
```

This is the only step that uses the network (pip). `constraints.txt` pins `numpy==1.26.4` (numpy < 2) because the
surrounding RFdiffusion repo hit a NumPy/torch ABI mismatch. These are dev/optional dependencies; the kit does not
require them.

## Demo

`python3 scripts/demo.py` (about 3 seconds) builds a toy teacher/student run, saves and verifies a checkpoint
(and confirms a tampered copy is rejected), scores a scorer-validation fixture, runs a robustness probe, opens
and reviews a claim in the ledger, and renders the dashboard twice (byte-identical) into a temporary directory
that is deleted afterwards. It writes nothing into the repository, exits non-zero on any failure, and prints
that **nothing it produces is evidence about RFdiffusion, the fork, or any real biological capability.**
Use `--keep` to retain the temp output for inspection.

## The `.env.example` flags are declarative markers only

`.env.example` lists `RUN_MODE=TOY_OFFLINE`, `ALLOW_EXTERNAL_NETWORK=false`, `MODEL_WEIGHTS_ENABLED=false`,
`BIOLOGICAL_TRAINING_ENABLED=false`, `TOY_SEED=42`. **No code reads any of them** (not in `src/`, `scripts/`, tests
or CI). They document intent for a human reader. **Setting or changing them changes no behaviour**, and setting
`BIOLOGICAL_TRAINING_ENABLED=false` does not constrain anything. No `.env` file is needed or read.

The kit's guarantees are structural. Each of these is checked (with the scope limits described under "Lint scope" and "What the network guard does and does not do" below):
- `src/` imports only the standard library, the kit's own `toy` package, and the one documented optional
  dependency `torch` (whose tests skip when it is absent). This is a **positive** check against
  `sys.stdlib_module_names`, in `scripts/lint.sh` and in `tests/toy_tests/test_scripts.py`
  (`test_src_toy_imports_only_the_standard_library`). **It was added in SR-15 and did not exist before:** this
  document previously cited an "AST check" for it in both places and *neither* performed one — `import numpy`,
  `import pandas`, `import scipy` and `import yaml` in `src/toy/` all passed lint with rc=0 and 0 errors. Until
  SR-15 the claim was true only by inspection.
- `src/toy/` imports no network library. This is a **blocklist** of module names, and therefore a tripwire rather
  than a guarantee — see "Lint scope" below for what it does and does not name.
- `scripts/run_tests.sh` runs the suite under a socket guard that makes the patched `socket` entry points raise.
  The patched and the deliberately-unpatched names are tuples in the script; the suite asserts every member of
  the family is in one of them. The suite's own negative controls run with the guard off, against loopback
  targets only.
- No weight files are present or loaded (`.gitignore` excludes common weight formats; nothing in `src/` loads them).

Manual source verification is a human activity outside the suite entirely: `docs/SOURCE_SNAPSHOT.json` preserves the
compare metadata for offline audit, and the `curl` commands in `docs/DIFF_EVIDENCE.md` are documentation for a human
who chooses to re-verify against GitHub. No script, test or CI step runs them.

## What the network guard does and does not do

`scripts/run_tests.sh` installs a Python-level guard (a `sitecustomize` module on `PYTHONPATH`) that replaces
socket's connection and name-resolution entry points with a function that raises (so `urllib` and `http.client`
fail too). Child **Python** processes inherit it while they inherit `PYTHONPATH`, and a canary refuses to run the
suite if the guard is not active.

**Do not read the patched list from this document.** It is the `_BLOCK_MODULE` and `_BLOCK_SOCKET` tuples in the
guard block of `scripts/run_tests.sh`, and the names deliberately left alone are the `_NOT_BLOCKED` tuple beside
them, each with its reason. Read them there. A hand-written prose copy lived here and went stale twice — most
recently it counted the patched functions as "five" three lines after correctly listing seven of them — so
`tests/toy_tests/test_scripts.py` now parses those three tuples out of the script and asserts that

- **every** member of `socket`'s connection and name-resolution family, enumerated from the live `socket` module
  rather than from a list (`create_connection`, `create_server`, and every `get(addrinfo|fqdn|host*|name*|serv*|proto*)`,
  plus `connect*`, `bind`, `listen`, `accept*`, `send*` on `socket.socket`), is in exactly one of the three tuples:
  patched, or disclosed with a reason. A name in neither fails the suite;
- every patched name has a test that **drives it through the real script**, generated from the patch list, with a
  negative control in which all of them fail under `--no-network-guard`.

That structure exists because the alternative was measured three times: `gethostbyname_ex`, then `getnameinfo`,
then `gethostbyaddr` and `getfqdn` were each found unpatched by the next reviewer who tried a name nobody had
tried before, and each round patched the names that reviewer happened to test rather than the family.
`gethostbyaddr` is the sharpest of them: for a non-local address it issues a reverse-DNS query that leaves the
host, and `getfqdn` leaks through it.

**It is not a sandbox.** Known bypasses, tested against a loopback listener by independent review (nothing left
the host):
- `_socket.socket().connect(...)` reaches a loopback listener. The guard patches the `socket` module, not the
  `_socket` C extension underneath it. (UDP `sendto` was in this bullet and is now patched on `socket.socket`;
  `_socket`-level `sendto` is not, for the same reason.)
- A child started with `python -I` (or `-S`, or a changed `PYTHONPATH`) does not load the guard. `-I` also ignores
  `PYTHONDONTWRITEBYTECODE`, so the "no `.pyc`" rule does not hold for such a child either.
- Non-Python children (for example `curl`) are not covered. A connection by `curl` was not demonstrated, but nothing
  prevents it.
- The `socket.socket` methods and module functions named in `_NOT_BLOCKED`: `gethostname`, `getservbyname`,
  `getservbyport`, `getprotobyname` (purely local lookups — the host's own name, `/etc/services`,
  `/etc/protocols` — which originate no traffic; `gethostbyname` and `getfqdn`, which do resolve, are patched,
  so `gethostbyname(gethostname())` is still blocked) and `send`, `sendall`, `sendfile`, `accept` (reachable
  only through a `connect`/`bind`/`listen` that is patched).
  Plus one **Linux-only** name, `sendmsg_afalg`, which was a real hole in the family enumeration and is **not
  a measured observation on Linux** — see the next bullet.
- **`sendmsg_afalg`: found by reading, never executed here.** `socket.socket.sendmsg_afalg` exists only on Linux
  (typeshed declares it under `if sys.platform == "linux"`), `socket.socket.__mro__` includes `_socket.socket`
  so `dir()` reaches it, and the test's `send\w*` pattern matches it. So on Linux — and only there — it joined the
  enumerated family while being in neither patch tuple nor the disclosure, and
  `test_every_family_member_is_either_patched_or_disclosed` would have failed with
  `unaccounted == ['sendmsg_afalg']`. On macOS the family has exactly 10 socket-method members and the test's
  anti-vacuity floor is `>= 10`, so nothing here could see it. **This was reasoned from the source, not run: no
  Linux was available at the time** (the Linux runs recorded at `81d450a` were `--expect none` suite runs and
  did not re-check this enumeration; see "Real Linux behaviour ... is now OBSERVED"), and the floor is now also
  backed by the four member names it used to pin only by count.
  It is **disclosed rather than patched** because it is not an egress path: it is valid only on a socket in the
  `AF_ALG` family — the Linux kernel *crypto* socket family, whose addresses are algorithm names such as
  `("hash", "sha256")` rather than host/port pairs — and its extra arguments (`op`, `iv`, `assoclen`, `flags`)
  are cipher parameters, not addressing. An `AF_ALG` socket has no network peer, no route and no interface; its
  only correspondent is the local kernel. On an `AF_INET` socket it raises, and the `AF_INET` path is
  `socket.sendmsg`, which **is** patched. Patching it would also mean `setattr`-ing a name onto `socket.socket`
  that does not exist on macOS, putting a `_BLOCK_SOCKET` member outside the live family; and the enumeration is
  deliberately **not** made platform-aware, because enumerating from the live module is the mechanism that
  stopped this guard from being patched one reviewer-tested name at a time.
- Anything that opens a socket without going through the patched `socket`-module functions and methods — the
  guard is a tripwire on names, not a sandbox.

`connect`, `connect_ex`, `create_connection`, `getaddrinfo`, `gethostbyname`, `gethostbyname_ex`, `getnameinfo`,
`urlopen`, `HTTPConnection`, `asyncio.open_connection` and `ftplib.FTP(host)` have each been confirmed blocked by
independent review; `gethostbyaddr` and `getfqdn` were confirmed **not** blocked by the most recent one and are
now patched and pinned.

### Connection attempts the suite itself makes, and why they are loopback-only

The guard's negative controls have to run with the guard **off** — that is the whole point of a control — so the
suite genuinely attempts connections on every run. They are:

| where | call | target |
|---|---|---|
| `scripts/run_tests.sh`, every guarded run | `create_connection` canary | `127.0.0.1:1` (closed port) |
| `test_network_guard_blocks_every_patched_entry_point`, `--no-network-guard` arm | one per patched name | closed loopback port, loopback bind, loopback UDP `sendto`/`sendmsg`, AF_UNIX `listen`, numeric lookups |
| `test_missing_guard_is_detected_by_canary` | the runner's canary under `python -S` | `127.0.0.1:1` |

Each one therefore ends in `ECONNREFUSED` (or `EINVAL`) **from the local stack**, and no packet reaches a network
interface. Until this round every one of them aimed at `192.0.2.1:9`. `192.0.2.0/24` is TEST-NET-1, which is
non-routable **by convention, not by the kernel**: on the development host `route -n get 192.0.2.1` returns
`gateway: 10.43.220.1, interface: en0`, and the tests' own comment — "without the guard these must fail fast, not
hang for ~75 s" — was a description of TCP SYN retransmission, i.e. of packets being sent and dropped. So a bare
run of this suite made three outbound connection attempts from the synthetic control suite and a fourth from the
runner's own canary, while this document said "no network access at test time". A test in
`TestNetworkGuardSurfaceAndDisclosure` now scans what the runner and every test module *execute* (code lines and
non-docstring string literals) and fails on any non-loopback target, so the address cannot drift back.

`socket.listen` is the one awkward case: `listen()` on an unbound INET socket auto-binds to the **wildcard**
address, so driving it that way would briefly open a listener on all interfaces in the unguarded arm. It is
driven on an AF_UNIX socket instead, which answers the same question (did the guard fire?) with no listener at
all.

The structural checks in `scripts/lint.sh` and `tests/toy_tests/test_scripts.py` are the first layer and the
runtime guard is a second, partial one. **Neither is complete**; see "Lint scope" immediately below for what the
static checks actually are.

## First observation on a case-sensitive filesystem: the script FAILED, and was fixed

The first stand-in for Linux (a case-sensitive APFS volume; **a stand-in, not Linux**) showed that
`run_tests.sh` as originally written would have gone red on `ubuntu-latest` for both CI jobs: four tests skip because
the filesystem is case-sensitive, their reasons name no package, and the skip policy rejected them
(`--expect none`: 874 run, 92 skipped, 4 policy failures; `--expect torch`: 6 skipped, 4 policy failures). The policy
now accepts these skips (see "Filesystem-case skips" above). Expect **4** more skips on Linux than the macOS
figures in the table — not 1. The stand-in rows in the table show 1 only because the stand-in moved the repo to a
case-sensitive volume and left `TMPDIR` on the case-insensitive one, so the three `TMPDIR`-probing dashboard tests
still ran; see "Filesystem-case skips: **4** on Linux" above. **Counts in the table are from the stand-in only.**
This is the class of surprise this document exists to warn about: the macOS-measured counts are not Linux counts,
and a stand-in that differs from Linux in one variable will under-predict it.

## Lint scope: what the check actually is

**What it is, precisely:** `scripts/lint.sh` applies (a) a **blocklist of module names**, (b) a **blocklist of
attribute names**, matched on any base object, and (c) in `src/` only, a **positive standard-library-only check**
against `sys.stdlib_module_names`. (a) and (b) are tripwires. A blocklist of a finite set of names cannot be
complete against a standard library that offers many ways to execute code or open a socket, so **a passing run is
not evidence that `src/` cannot execute code or reach the network.** Only (c) is a positive guarantee, and it
guarantees only *which distributions* are imported, not what they are used for.

In `src/` it rejects: network-capable imports; the process/dynamic-loading modules `subprocess`, `ctypes`,
`_ctypes`, `importlib`, `posix`, `nt`, `builtins`, `multiprocessing`, `pty`; the stdlib **code-execution** modules
`runpy`, `code`, `codeop`, `pdb`, `bdb`, `cProfile`, `profile`, `trace`, `timeit`, `doctest`, `marshal`, `pickle`,
`shelve`, `zipimport`, `pkgutil`, `site`, `venv`, `py_compile`, `compileall`, `modulefinder`, plus `ensurepip`
(runs pip, hence the network), `sqlite3` (loads native extensions) and `tkinter`/`turtle` (Tcl `exec`);
`concurrent.futures` (`ProcessPoolExecutor` is the same capability as `multiprocessing`); `__import__`; `compile`;
any bare reference to `eval`/`exec` other than the two allow-listed literal calls in `failure_modes.py`; any
non-stdlib import; and any attribute named like `system`, `popen`, `fork`, `exec*`, `spawn*`, `posix_spawn*`,
`import_module`, `resolve_name`, `runsource`, `run_module`, `run_path`, `load_module`, `exec_module`,
`FunctionType`, `CodeType`, `addsitedir`, `getnode`, `uuid1`, `browse`, `listen`, `testmod`,
`ProcessPoolExecutor`, `attrgetter`, `methodcaller`, `load_extension`, `check_output`, `get_type_hints`,
`getattr_static`, `breakpointhook` — plus the bare builtin `breakpoint` — on any base object, so
`import os as o; o.system(...)`, `f = os.system` and `builtins.exec(...)` are caught — plus
`from <anything> import <one of those names>` and `from x import *`.

Network-capable module names (including `_socket`, `socketserver`, `asyncio`, `selectors`, `webbrowser`,
`nntplib`, `smtpd`, `wsgiref`, `cgi`, `pydoc` and `antigravity`, and the dotted `logging.config` and
`logging.handlers`) are rejected in `tests/` and `scripts/` as well as `src/`. That one list lives in
`scripts/lint.sh` and `tests/toy_tests/test_scripts.py` **parses it out of the script** rather than restating it
(see `_lint_blocklists`), because the two hand-maintained copies had diverged: the script named 27 modules and the
test named 18, so `import asyncio` in `src/toy/` was rejected by the script and missed by the test that this
document cited as co-enforcing the rule.

**Most of the names above were added in SR-15 because review found them passing.** Every one of these was a plain
static import with a literal attribute call — *not* a `getattr` or runtime-name trick — and passed with rc=0 and 0
errors: `code.InteractiveInterpreter().runsource(...)`, `runpy.run_module(...)`, `pdb.run(...)`,
`cProfile.run(...)`, `trace.Trace().run(...)`, `timeit.timeit(...)`,
`types.FunctionType(marshal.loads(b), globals())()`, `zipimport.zipimporter(p).load_module(...)`,
`doctest.testmod(...)`, `pickle.loads(blob)`, `shelve.open(...)`, `logging.config.listen(9999)`,
`pydoc.browse(port=...)`, `import antigravity`, `venv.EnvBuilder(with_pip=True).create(d)`,
`concurrent.futures.ProcessPoolExecutor()`, `site.addsitedir(...)`, `uuid.getnode()`, and above all
**`pkgutil.resolve_name('os:system')('echo pwned')`, which defeated the entire attribute blocklist in one line**
by returning the function without ever naming it as an attribute. An earlier version of this section listed only
four "not covered" buckets — `getattr`-style tricks, runtime-built names, things outside `src/`, and third-party
packages — and **none of those nineteen fell into any of them**, so the enumeration implied that plain static
attribute calls were covered when they were not.

**One whole class is closed by a rule rather than by more names.** `src/` may import **no underscore-prefixed
top-level module** (`__future__` excepted). The private C-extension counterparts of the banned modules were a
systematic evasion — `_socket` and `_ctypes` were named, which shows that two members had been thought of, while
`_pickle` (arbitrary code via `__reduce__`, demonstrated), `_imp` (`create_dynamic`/`exec_dynamic` load a native
extension), `_posixsubprocess.fork_exec`, `_multiprocessing`, `_asyncio`, `_sqlite3`, `_tkinter` and `_curses`
were not. `unittest.TestLoader().loadTestsFromName("os.system")` and `sys._getframe().f_builtins["exec"]` were
closed too, because they are the same shape as `pkgutil.resolve_name` (a static call with a literal string) and
cost one name each. This class was reported as **not** part of the failing criterion, and was closed because it
was cheap; chasing completeness is explicitly not the goal.

**Three more were reported, agreed to be outside any failing criterion, and closed anyway because they cost one
name each.** Each *executed a shell command* and linted with `0 error(s)`, and none of them uses
`eval`/`exec`/`compile`/`getattr`/`__dict__`/`vars`/`getmembers`:
- `typing.get_type_hints(f)` where `f`'s **return annotation is the string**
  `"__import__('os').system('echo pwned')"` — a string literal **evaluated** with no `eval` token in the file;
- `inspect.getattr_static(os, "system")("…")` — returns the function with no attribute access the blocklist can
  see, the same shape and the same power as `pkgutil.resolve_name`;
- `sys.breakpointhook("…")` with `PYTHONBREAKPOINT=os.system`, and the bare builtin `breakpoint()`, which reaches
  `pdb` — a module named in the blocked `PROC` set — through **no import at all**.

These are hygiene, closed because they were cheap. **Chasing completeness is explicitly not the goal, and the
list below is not an enumeration of everything that still passes** — it is what was checked and left.

**Still not covered** (checked, and left uncovered deliberately — extending a tripwire forever is not the goal):
- **String annotations and every other place a name is spelled as data rather than as code.** `get_type_hints`
  is now named, so the demonstrated form is caught, but the **class** is open: any other standard-library
  function that evaluates a string it is handed is a fresh instance of it.
- Reflection through a **mapping** rather than an attribute: `vars(os)["system"]`, `os.__dict__["system"]`,
  `dict(inspect.getmembers(os))["system"]`. All three pass, all three are a plain static call with a literal
  string, and all three are a different shape from the attribute blocklist. Left open on purpose: banning the
  names `vars`/`__dict__`/`getmembers` in `src/` would reject ordinary introspection, and the subscript form
  would need a new rule for each container.
- `getattr(os, "sys" + "tem")`-style tricks and any name or code built at runtime.
- `os.system("curl ...")` and similar **outside** `src/`: the process and code-execution rules are `src/`-only by
  design, since `tests/` and `scripts/` legitimately use `subprocess` to drive the scripts.
- Anything inside a third-party package.
- Named modules that still pass and were confirmed to pass: `select`, `mmap`, `threading`, `gc`, `platform`,
  `tarfile`/`zipfile` (archive extraction can write outside the target directory), and the `xml` packages other
  than the banned `xmlrpc`. None of these on its own executes arbitrary code or opens an outbound connection,
  which is why they are not banned — not because they were shown to be harmless in general.
- And, unavoidably, any stdlib code-execution or server entry point nobody has thought of yet.

This is hygiene, not a sandbox; the runtime socket guard is a second, partial layer (see above).

## Known limits of this documentation (read before trusting CI)

- **The CI workflow has never been executed.** Its two jobs were never run on a hosted runner (none was available);
  the commands they invoke were run locally and the YAML parses. `optional-deps` remains unverifiable here.
  **The Python-version basis for expecting `core-no-deps` to pass is now measured rather than assumed.** This bullet
  previously said "given bare Python 3.12 and 3.13 local runs" while the SR-15 reviewer had measured 3.12.4 only and
  listed 3.13 as explicitly unestablished; the 3.13 mention below was about *torch* versions, not a bare suite run.
  Both legs of the `["3.12", "3.13"]` matrix have now been run bare at `209adfc`:
  **3.12.4 and 3.13.11 each give `Ran 1002 tests` / `OK (skipped=89)`, with identical per-module counts and an
  identical skip list, and each is deterministic across `--twice`.** So the interpreter version is no longer a
  source of doubt about that job. **What this does NOT establish:** anything about Linux, which is a separate
  variable and still unobserved (next bullet).
- **Real Linux behaviour of `run_tests.sh` and the tests is now OBSERVED, in one configuration.** This bullet
  used to read *"has never been observed. Everything ran on macOS; a case-sensitive-APFS stand-in found one
  failure (above) and may hide others."* At `81d450a`, `bash scripts/run_tests.sh --expect none --twice` was run
  in two bare Linux containers: **1252 ran / 95 skipped / 0 failed on both CPython 3.12.10 and 3.13.3**,
  `RESULT: OK`, `run1 == run2` with identical per-module counts and skip lists, no `POLICY:` tokens, filesystem
  probed case-sensitive, `packages_present == []`, and the macOS-generated `scripts/test_baseline.txt` passed
  against it. The predicted **4** filesystem-case skips are measured at exactly 4 (the stand-in's 1 was the
  artefact described above) and the predicted **1** absent-developer-tool skip is measured at 1. **What one
  configuration does not establish:** `optional-deps` on Linux, any non-`ubuntu` distribution, a hosted GitHub
  runner (see the first bullet — the workflow itself still has never been executed), the pinned
  torch/numpy combination, or hermeticity (next bullet).
- **Hermeticity is unattested: a network-denied environment has never been observed.** Every statement in this
  document about nothing leaving the host rests on (a) the loopback-only targets of the connections the suite
  really makes, asserted by `test_no_executed_connection_target_in_the_suite_is_non_loopback`, and (b) the
  runtime socket guard, which is a tripwire on names and not a sandbox. The Linux containers above **had
  network**, so the guard was observed *present*, not *load-bearing*: a guard observed running is not a guard
  observed working. **The measurement that would attest it, defined here and NOT run:** take the same bare
  container, remove egress (no default route, or a deny-all egress policy, or an empty network namespace with
  only `lo` up), and record three things in one session — (1) `./scripts/run_tests.sh --expect none --twice`
  ends `RESULT: OK` with the same 1252/95/0 and the same skip list as the networked run, so no test is silently
  passing *because* a connection failed; (2) a positive control in that same environment shows egress really is
  denied (an outbound TCP connect to a routable address fails with `ENETUNREACH`/`EHOSTUNREACH` rather than
  `ECONNREFUSED`); (3) `python3 scripts/demo.py` and `./scripts/lint.sh` also pass there. Until all three are
  recorded, "offline" in the title of this document is a statement about what the kit *asks for*, not an
  attested property of a run.
- **The torch/numpy pin is untested as a combination.** `constraints.txt` pins torch 2.7.1 + numpy 1.26.4 on Python
  3.12. Locally the suite passes on torch 2.7.1 + numpy 2.4.6 (framework Python 3.12) and torch 2.11.0 + numpy 2.4.4
  (miniconda Python 3.13), so local runs do not test the pinned combination. The pin is kept for reproducibility.
  The `numpy<2` rationale (NumPy/torch ABI mismatch seen in the RFdiffusion repo) holds regardless.
- **Whether `torch==2.7.1` resolves to the CPU wheel via `--extra-index-url` on Linux is untested.**
- **Actions are pinned by tag, not commit SHA** (`actions/checkout@v4`, `actions/setup-python@v5`).
- **Only the direct optional dependencies are pinned; their transitive dependencies are not.**
  `constraints.txt` and `requirements-dev.txt` pin what the `optional-deps` job asks for by name, and `pip`
  then resolves everything underneath them freely: there is no `--require-hashes` and no lock file, so that job
  is not byte-reproducible over time. Nothing in the kit claims otherwise — this bullet exists because the
  limit had never been written down, not because a claim was wrong. The `core-no-deps` job and every documented
  clean-clone step install nothing at all and are unaffected.
- **The determinism check is deliberately redundant, and four of its terms are individually unpinned.**
  `--twice` compares `$RAN`, `$SKIPPED`, `$BAD` and `$UT_RC` *and* the canonical per-module/skip-list file.
  Mutating any one of those four terms alone leaves the check still failing, because the canon comparison or
  the remaining terms catch the same difference (`$RAN`/`$SKIPPED` are strictly subsumed by the canon: a
  differing total implies a differing `ran`/`skip` line). Only the canon comparison and the `$BAD`-with-`$UT_RC`
  pair are pinned individually. This is defensible redundancy rather than a set of masked tests, but it is four
  terms, not the one the record previously named.
- **The 1/3/4 variable-by-variable table comes from the stand-in; the Linux TOTAL does not, any more.** The
  table under "Filesystem-case skips" is from a real case-sensitive APFS disk image, which is still a stand-in:
  it shows which *variable* drives each skip. The **4** it predicts for the Linux configuration is now measured
  on Linux (`81d450a`, two bare containers, `note: 4 skip(s) for a case-sensitive filesystem (expected on
  Linux)`); what the stand-in still cannot show is that Linux behaves identically in any other respect.
- **Step (b), `--expect any` on a machine that has the packages, has not been run against the full suite here.**
  It is correct by construction rather than by measurement: in `scripts/run_tests.sh` every policy that the
  host-interpreter run tripped (`NONE_REASON`, `TORCH_PRESENT`, `MIN_NONE_SKIPS`, `NO_NUMPY_REASON`, and the
  baseline *skip* comparison) sits inside `if mode == "none":` / `elif mode == "none":`, with no `else` branch, so
  `any` cannot reach them; the baseline *test-count* comparison, which does apply in every mode, compares counts
  that do not depend on which packages are installed (a skipped test still starts, so it is still counted). The
  mode's behaviour is exercised by the synthetic-suite tests, not by a full real-suite run in this environment.
  **The same sentence read "keeps every consistency, determinism and baseline check" in step (b) above, which
  was loose in exactly the direction that matters:** `any` keeps no *reason* check at all and does not compare
  the baseline's skip column. Measured: six exempt-shaped reasons that each name a measured package give
  `rc=0` under `--expect any`. The two statements now agree, and the only skip-reason policy that does apply in
  that mode is `POLICY:TOOL_UNDECLARED` (plus `EMPTY_REASON` and the two caps).
- The script tests (see test collection for the count; `scripts/test_baseline.txt` records 13 modules) take one
  to two minutes because they run the scripts on synthetic suites and trees — **112 s for the 128 tests of
  `tests/toy_tests/test_scripts.py`** on the host interpreter, and **117 s for the same 128 on a bare
  `venv --without-pip` 3.12.4**, both measured serially at the commit that closed the third SR-15 FAIL, and
  longer under any concurrent load. (The previous figure here, "92 s for the 110 tests", was hedged against a
  live count of 111; the count is read off a run now rather than typed.) Do not read a figure here as current;
  the point is the order of magnitude and that it grows with the module. The module is **137 tests** at the
  commit that closed the fifth FAIL (132 at the fourth) and takes **142 s** serially on the host interpreter;
  the five added for the fifth cost about 30 s between them, three of them because they drive the script once
  per mode or once per laundering table. The suite is **1165 tests** at that commit, and
  `scripts/test_baseline.txt` still records `toy_tests.test_scripts 132 4`, so that row carries five tests of
  slack until it is regenerated — green by design, because the column is a floor. At the commit that closed the
  SIXTH FAIL the module is **147 tests** and takes **158 s** on CPython 3.12.4 and **51 s** on a conda CPython
  3.13.5 (`PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`; that interpreter has pytest, so four of the module's skips run
  there instead) — a suite result is not a fact about this repository unless the interpreter that produced it is
  recorded beside it. The ten added tests are generated per exemption category, so most of their cost is one run
  of the script per category per mode. The baseline row recorded `toy_tests.test_scripts 137 4` when they were
  written, which carries ten tests of slack; the bare-skip column is still **4** (the four pytest skips: nothing
  added skips in a bare environment, and both exempt categories' exclusions are unchanged). At the fourth FAIL, the four new ones cost about 6 s between them: the laundering tables
  they drive are long, so each is driven as ONE run of the script carrying every candidate reason as its own
  skip, and attributed by test id — 48 separate runs of the same table cost 57 s for no more information.
  That bare, no-`ruff` run gives **6 skips in this module**: 4 need pytest, 1 needs PyYAML, 1 is the
  optional-developer-tool skip — so its **baseline skip column is 4**, which is the figure excluding PyYAML,
  filesystem-case and tool skips, and it is the same number on a machine that has `ruff`.
- **Four `POLICY:` tokens were emitted by `scripts/run_tests.sh` and asserted by no test at all** —
  `BASELINE_WRITE`, `RECORDER`, `SKIP_RECORD` and `PYTEST_FAILED` — which is how the directory-destination write
  above slipped past review: it fell into an unasserted branch. The first three were found by review; the fourth
  was found by the coverage check below, and is the sharpest of them, because a run in which pytest goes red
  while unittest stays green is exactly the case a reader would otherwise call a pass. Each now has a test that
  drives the branch, the `BASELINE_WRITE` one by creating the directory *during* the run, which is the only
  input the start-up check cannot see. A token-coverage check
  (`test_every_policy_token_is_asserted_by_some_test`) now fails if any `POLICY:` token the script can print is
  not named in a non-docstring string literal of `tests/toy_tests/test_scripts.py`, so the next one cannot be
  added unasserted. It is a staleness tripwire, not a measurement: it cannot show that the assertion drives the
  branch, only that somebody reached for the token.
  The live count is **26** tokens (25 before `POLICY:TOOL_UNDECLARED` was added), all 26 asserted, 0
  unasserted. **Three counts get confused here, so all three:** 26 distinct *emission* tokens; **28 distinct
  names** matched by the looser regex (the 26 plus two non-emissions — the header's `POLICY:<NAME>` placeholder
  and a comment's `POLICY:BASELINE_*` wildcard); and **45 loose *occurrences*** in the file, because nine of
  those names are written more than once. A record saying "`POLICY:` appears 27 times by a looser regex" was
  mixing the second count with the third: at that commit the figures were 25 / 27 / 33, so 27 was the
  distinct-name count and never the occurrence count. Only the first two are worth recording — the occurrence
  count moves whenever a comment mentions a token, which is why the test asserts the distinct sets and not it. **The check's own anti-vacuity floor was `>= 24` against 25**, so one token
  could have been deleted without it firing; it is now the real count, and alongside it every `POLICY:`
  occurrence in the script must be accounted for as either an emission the token regex found or one of those two
  non-emissions — which is the hazard the floor was standing in for (a token count that moves is not a bug; a
  token regex that silently stops matching is).

## A re-opened write defect: the staged baseline and a directory destination

`--update-baseline` stages the new baseline and the shell moves it into place only if the whole run ends
`RESULT: OK`. That design is sound and unchanged. What it did **not** check was that the destination is a file:

```
$ MIN_TESTS=1 MIN_NONE_SKIPS=1 ./scripts/run_tests.sh --expect none \
      --tests-dir <synth> --baseline scripts --update-baseline
baseline staged for .../scripts (1 modules); it is written only if this run ends RESULT: OK
baseline written: .../scripts ( modules)
RESULT: OK      exit=0
$ git status --porcelain
?? scripts/base.staged          # untracked, and not in .gitignore
```

`mv file dir` **succeeds** — it drops the file inside — so a user who asked for a baseline somewhere got an
untracked junk file **inside the repository**, reported as `RESULT: OK`, in a kit whose `demo.py` carries an
inode-identity guard precisely so that nothing can write there. The same shape as the `--baseline none` defect
(D1). The only hint was the empty `( modules)`: the count came from `$(grep -cv '^#' "$BASELINE" || true)`, read
*after* the move from a path that was not a file, and `|| true` discarded both grep's status and its
"Is a directory" message. The comparison branch was broken by the same input differently —
`os.path.exists(base)` is true for a directory, so `open(base)` raised `IsADirectoryError` and the run died with
a traceback and no `POLICY:` token at all.

Now: a directory destination is a **start-up usage error** (`exit 2`, before the suite runs, covering both
branches); a directory that appears at that path *during* the run is caught at write time as
`POLICY:BASELINE_WRITE` with the staged file left where it is; and the module count is taken from the staged file
*before* the move, with an explicit `0` fallback instead of `|| true`, so the count can no longer be empty.

## What CI does

`.github/workflows/ci.yml`: job `core-no-deps` (Python 3.12 and 3.13, installs nothing, lint, suite twice with
`--expect none`, demo) and job `optional-deps` (Python 3.12, pinned torch 2.7.1 + numpy 1.26.4 (never executed; see limits above), suite twice with
`--expect torch`, unittest and pytest, demo). Read-only permissions, no secrets, no publishing.

## A bug in the runner that corrupted nested runs (fixed)

`run_tests.sh` used to clear bytecode across the whole repo on every invocation. The script's own tests invoke it on
synthetic suites, so they wiped the real repo's `__pycache__` while the surrounding test run was in progress, which
produced failure counts that varied between runs. A run with `--tests-dir` now clears bytecode only under that
directory; the default run still clears the whole tree (the standing rule). After the fix, two consecutive full
torch runs gave identical results (914 run, 2 skipped, 0 failed, pytest 912 passed — measured pre-SR-15; see
"Expected counts" on why not to rely on that total).

**Both halves of that fix are now pinned behaviourally, and one of them was not.** The scoped half is pinned by
`test_scoped_run_does_not_touch_bytecode_outside_its_tests_dir` (a sentinel `__pycache__` outside the synthetic
tests dir, which must survive). The default half was pinned only by a **grep** for the literals
`if [ "$SCOPED" = 0 ]; then` and `SCOPED=1`, and review showed that to be vacuous: a mutant inserting `SCOPED=1`
immediately above the top-level `clear_bytecode` call keeps both literals, so the grep passed while the default
run silently stopped clearing anything outside `tests/` — and the other two bytecode tests passed as well, because
one drives the scoped path via `--tests-dir` and the other only asserts that the scoped path does *not* delete. The
grep has been replaced by `test_default_run_clears_bytecode_in_the_whole_tree_not_only_under_tests`, which plants
canaries outside `tests/`, drives the **default** path against a throwaway repo root holding a copy of the live
script, and asserts the canaries are gone *before the suite starts* as well as after. That mutant now fails it.
