# Clean-clone verification (offline, stdlib only)

**The kit downloads nothing and requires no credentials.** It needs only Python 3.12 or newer (the standard library
is enough). No package manager, no API key, no model weights, no dataset, and **nothing the suite does leaves this
host.** That is deliberately narrower than "the suite opens no socket", because it does: the runner's guard canary
and the negative-control tests that drive the runner with `--no-network-guard` (which is what makes them controls)
really attempt connections, and every target is **loopback** — a closed port on `127.0.0.1`, a loopback bind, or an
AF_UNIX socket. See "Connection attempts the suite itself makes" below; this used to say "no network access at test
time" while four of those attempts went to a routable address on every run.
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

# (b) the loop above printed something, and you want to use this interpreter anyway. `--expect any` keeps every
#     consistency, determinism and baseline check and drops only the "nothing is installed" assertion:
./scripts/run_tests.sh --expect any --twice

# (c) the loop printed something, and you want the clean-clone assertion anyway: make a bare interpreter.
#     `--without-pip` needs no network. Keep it OUTSIDE the repo: only `.venv`/`venv` are pruned from the
#     bytecode sweep and ignored by git, so a differently-named venv inside the tree would be swept and tracked.
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
| Real Linux | **never observed** | | | |

All rows were repeated with `--twice` and were identical. The bare skips are overwhelmingly torch/numpy skips,
plus the optional-PyYAML workflow-parse test and the script tests that need pytest. Earlier independent reviews
measured 739 run / 86 skipped bare, and 656 run / 85 skipped bare at the base commit.

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

The 89 bare skips, by module, were: `test_tensor_ops` 82, `test_scripts` 4 (three need pytest, one needs PyYAML),
*and that measurement was taken on a machine that happened to have `ruff`.* A bare machine **without** `ruff`
has one more — the optional-developer-tool skip described under "The documented steps used to fail without
`ruff`" — so expect `test_scripts` 5 and a total of 90 there. That extra skip does **not** move
`scripts/test_baseline.txt`, by construction. Before the fix it did not add a skip at all: it failed the run.
`test_failure_modes` 2, `test_stability` 1. Zero filesystem-case skips, because this machine's repo volume and
`TMPDIR` are both case-insensitive — which is the whole subject of the next section.

### Filesystem-case skips: **4** on Linux, and the earlier "1" was a measurement artefact

Expect **4** filesystem-case skips on Linux. Three are the `need_ci()` tests of `IdentityAndCaseGuards` in
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

- **Filesystem-case skips** (reason contains "case-sensitive"): allowed in both modes, at most 8, and not counted
  toward the package-skip floor, the torch cap or the baseline. **Four** tests skip this way on a case-sensitive
  filesystem (three `need_ci` tests in `test_dashboard`, one in `test_scripts`), whose reasons name no package.
  Four is the figure to expect on Linux; see "Filesystem-case skips: **4** on Linux" above for why the
  case-sensitive-APFS stand-in rows show 1.
- **Optional-developer-tool skips** (reason matches ``optional developer tool `<name>` is not on PATH``): the
  second category that legitimately names no package, treated exactly like the first — allowed in every mode, at
  most 4 (`POLICY:TOOL_CAP`), and excluded from the package-skip floor, the torch cap and the baseline in
  **generation as well as comparison**. **One** test skips this way: the behavioural half of the fatal-`ruff`
  guarantee (`test_ruff_correctness_findings_are_fatal_not_advisory`). See "The documented steps used to fail
  without `ruff`" below for why the category exists and what the wording is load-bearing for.

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

- The phrase is **structured**, not a password: the tool is named in backticks and the whole phrase must match, so
  prose that merely sounds like it ("optional linter absent") gets no exemption and still fails `POLICY:NONE_REASON`.
- It says **"is not on PATH", not "is not installed"**. Torch mode's deny list reads *every* skip, tool skips
  included, so a reason that also claims a package is missing is still rejected — the category cannot launder
  `torch not installed` past `--expect torch`. That is the same rule the filesystem-case category has.
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

## Interpreting skips

A skip is a test that did **not run**, not a pass. Without torch the autograd, device and precision tests are
skipped with the reason "torch not installed ..." (CPU-vs-CUDA/MPS comparisons are UNKNOWN, never "passed").
With torch present, the remaining skips are hardware: no CUDA (always on a laptop), no MPS (non-Apple), and one
wiring test that only applies when torch is absent. A clean clone passing with most of its skips in that state
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
  Linux was available** (see "Real Linux behaviour ... has never been observed"), and the floor is now also
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
- **Real Linux behaviour of `run_tests.sh` and the tests has never been observed.** Everything ran on macOS; a case-sensitive-APFS stand-in found one failure (above) and may hide others.
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
- **The case-sensitive-filesystem counts come from the stand-in**, not from Linux. The 1/3/4 table under
  "Filesystem-case skips" is from a real case-sensitive APFS disk image, which is still a stand-in: it shows
  which *variable* drives each skip, not that Linux behaves identically in other respects.
- **Step (b), `--expect any` on a machine that has the packages, has not been run against the full suite here.**
  It is correct by construction rather than by measurement: in `scripts/run_tests.sh` every policy that the
  host-interpreter run tripped (`NONE_REASON`, `TORCH_PRESENT`, `MIN_NONE_SKIPS`, `NO_NUMPY_REASON`, and the
  baseline *skip* comparison) sits inside `if mode == "none":` / `elif mode == "none":`, with no `else` branch, so
  `any` cannot reach them; the baseline *test-count* comparison, which does apply in every mode, compares counts
  that do not depend on which packages are installed (a skipped test still starts, so it is still counted). The
  mode's behaviour is exercised by the synthetic-suite tests, not by a full real-suite run in this environment.
- The script tests (see test collection for the count; `scripts/test_baseline.txt` records 13 modules) take one
  to two minutes because they run the scripts on synthetic suites and trees — **112 s for the 128 tests of
  `tests/toy_tests/test_scripts.py`** on the host interpreter, and **117 s for the same 128 on a bare
  `venv --without-pip` 3.12.4**, both measured serially at the commit that closed the third SR-15 FAIL, and
  longer under any concurrent load. (The previous figure here, "92 s for the 110 tests", was hedged against a
  live count of 111; the count is read off a run now rather than typed.) Do not read a figure here as current;
  the point is the order of magnitude and that it grows with the module.
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
