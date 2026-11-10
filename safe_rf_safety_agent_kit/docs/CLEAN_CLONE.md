# Clean-clone verification (offline, stdlib only)

**The kit downloads nothing and requires no credentials.** It needs only Python 3.12 or newer (the standard library
is enough). No package manager, no API key, no model weights, no dataset, no network access at test time.
`mse_naive` order-invariance in the robustness tests depends on CPython >= 3.12 compensated `sum()`; do not use
an older interpreter (some assertions would go red; pre-3.12 is unsupported).

## Steps

```sh
git clone <this repository>   # the only network step, and only to obtain the source
cd safe_rf_safety_agent_kit   # the kit root (contains src/, tests/, scripts/)
python3 --version             # 3.12.x or newer
./scripts/lint.sh             # compileall + AST checks; works with nothing installed
./scripts/run_tests.sh --expect none --twice
python3 scripts/demo.py
```

`run_tests.sh` removes `__pycache__`, disables bytecode (`PYTHONDONTWRITEBYTECODE=1`), fixes `PYTHONHASHSEED=0`,
installs a socket guard so any connection attempt fails, runs `python3 -m unittest discover -s tests -v` (and
`python3 -m pytest -q tests` only if pytest happens to be installed), checks skip reasons, and with `--twice`
verifies a second run gives identical counts and an identical skip list. You can also run the suite directly:
`PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests`.

Why no bytecode: a stale `.pyc` contaminated mutation results three times and once caused a misattributed
10-failure spike. After any surprising failure count, clear `__pycache__` and re-run before drawing conclusions.

## Expected counts (measured 2026-11-09 on a working tree of 914 tests; the total keeps growing)

| Environment | unittest | pytest | `--expect` |
|---|---|---|---|
| Nothing installed (the clean-clone case; `venv --without-pip`, Python 3.12.13) | 914 run, **89 skipped**, 0 failed | not run (not installed) | `none` |
| Nothing but PyYAML | one fewer skip than bare; **87 measured at 874 tests, not re-measured at 914** | not run | `none` |
| torch + numpy + pytest + PyYAML (macOS, MPS available) | 914 run, **2 skipped** (identical in two full runs) | 912 passed, 2 skipped | `torch` |
| Case-sensitive APFS stand-in, bare | 914 run, 90 skipped (1 filesystem-case) | not run | `none` |
| Case-sensitive APFS stand-in, torch | 914 run, 3 skipped (1 filesystem-case) | 911 passed, 3 skipped | `torch` |
| Real Linux | **never observed** | | |

All of these were repeated with `--twice` and were identical. The 89 bare skips are 85 torch/numpy skips plus the
optional-PyYAML workflow-parse test plus script tests that need pytest. The stand-in showed 4 filesystem-case skips when
first measured (874 tests, 92 bare / 6 torch); only 1 remains at 914 because the dashboard tests were since changed.
An independent review measured 739 run / 86 skipped bare earlier, and 656 run / 85 skipped bare at the base commit.

Totals grow as tests are added, so the runner does not pin one global number. It enforces, per test module, a
recorded baseline (`scripts/test_baseline.txt`: tests and bare-environment skips for each module). A module with
fewer tests than recorded fails, and in `--expect none` mode so does a module with fewer skips than recorded, so
deleting tests, or turning a torch-guarded test into a silent early-return pass, fails loudly **by module name**.
Regenerate after intentionally adding tests (in a bare environment): `scripts/run_tests.sh --expect none --update-baseline`
(PyYAML skips are excluded from the baseline). A global floor (`MIN_TESTS`, default 650, inclusive) remains as a
second layer.

Skip-reason policy (case-insensitive, applied to **every** skip, recorded exactly by a hook inside the unittest
process rather than scraped from output):
- `--expect none`: each reason must name torch, numpy, pyyaml or pytest and say "not installed", "missing",
  "unavailable" or "not available"; at least 50 skips (`MIN_NONE_SKIPS`); at least one torch and one numpy reason;
  none may say "torch present"; no empty reasons.
- `--expect torch`: each reason must name CUDA, MPS or "torch present" and must not say "not installed", "missing"
  or mention numpy; at most 12 skips. (PyYAML **and pytest** must therefore be installed in this mode: without them the script tests skip as "PyYAML/pytest not installed", which torch mode denies. `requirements-dev.txt` installs both.)

- **Filesystem-case skips** (reason contains "case-sensitive"): allowed in both modes, at most 8, and not counted
  toward the package-skip floor, the torch cap or the baseline. Four tests skip this way on a case-sensitive
  filesystem (three `need_ci` tests in `test_dashboard`, one in `test_scripts`), whose reasons name no package.

These rules are themselves tested with synthetic suites in `tests/toy_tests/test_scripts.py`, including the exact
boundaries (50 passes / 49 fails, 12 / 13, `MIN_TESTS` inclusive).

## Interpreting skips

A skip is a test that did **not run**, not a pass. Without torch the autograd, device and precision tests are
skipped with the reason "torch not installed ..." (CPU-vs-CUDA/MPS comparisons are UNKNOWN, never "passed").
With torch present, the remaining skips are hardware: no CUDA (always on a laptop), no MPS (non-Apple), and one
wiring test that only applies when torch is absent. A clean clone passing with ~88 skips means the stdlib core
passed; it says nothing about torch behaviour. List them with `python3 -m unittest discover -s tests -v | grep skipped`.

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
- `src/toy/` is standard-library only and imports no network library (AST check in `scripts/lint.sh` and in
  `tests/toy_tests/test_scripts.py`).
- `scripts/run_tests.sh` runs the suite under a socket guard that makes any connection attempt fail.
- No weight files are present or loaded (`.gitignore` excludes common weight formats; nothing in `src/` loads them).

Manual source verification is a human activity outside the suite entirely: `docs/SOURCE_SNAPSHOT.json` preserves the
compare metadata for offline audit, and the `curl` commands in `docs/DIFF_EVIDENCE.md` are documentation for a human
who chooses to re-verify against GitHub. No script, test or CI step runs them.

## What the network guard does and does not do

`scripts/run_tests.sh` installs a Python-level guard (a `sitecustomize` module on `PYTHONPATH`) that makes
`socket.socket.connect`, `connect_ex`, `socket.create_connection`, `getaddrinfo` and `gethostbyname` raise (so
`urllib` and `http.client` fail too). Child **Python** processes inherit it while they inherit `PYTHONPATH`, and a
canary refuses to run the suite if the guard is not active. **It is not a sandbox.** Known bypasses, observed by
independent review:
- `_socket.socket().connect(...)` reaches a loopback listener; so does UDP `sendto`.
- `socket.gethostbyname_ex` is not patched.
- A child started with `python -I` (or `-S`, or a changed `PYTHONPATH`) does not load the guard. `-I` also ignores
  `PYTHONDONTWRITEBYTECODE`, so the "no `.pyc`" rule does not hold for such a child either.
- Non-Python children (for example `curl`) are not covered. A connection by `curl` was not demonstrated, but nothing
  prevents it.
The structural checks (`scripts/lint.sh` and `tests/toy_tests/test_scripts.py` reject network-capable imports in
`src/`, `tests/` and `scripts/`, plus `subprocess`, `importlib`, `__import__`, `os.system`/`popen` and non-allow-listed
`eval`/`exec` in `src/`) are the first layer; the runtime guard is a second, partial one. Known gaps in the static
checks: `getattr`/string tricks, code built at runtime, and `os.system("curl ...")` outside `src/`.

## First observation on a case-sensitive filesystem: the script FAILED, and was fixed

The first stand-in for Linux (a case-sensitive APFS volume; **a stand-in, not Linux**) showed that
`run_tests.sh` as originally written would have gone red on `ubuntu-latest` for both CI jobs: four tests skip because
the filesystem is case-sensitive, their reasons name no package, and the skip policy rejected them
(`--expect none`: 874 run, 92 skipped, 4 policy failures; `--expect torch`: 6 skipped, 4 policy failures). The policy
now accepts these skips (see "Filesystem-case skips" above). Expect roughly 4 more skips on Linux than the macOS
figures in the table: **counts above are from the stand-in only**. This is the class of surprise
this document exists to warn about: the macOS-measured counts above are not Linux counts.

## Lint scope: what "structural" does and does not cover

`scripts/lint.sh` (and the same checks in `tests/toy_tests/test_scripts.py`) reject in `src/`: network-capable
imports; `subprocess`, `ctypes`, `importlib`, `posix`, `nt`, `builtins`, `multiprocessing`, `pty`; `__import__`;
`compile`; any bare reference to `eval`/`exec` other than the two allow-listed literal calls in `failure_modes.py`;
and any attribute named like `system`, `popen`, `fork`, `exec*`, `spawn*`, `posix_spawn*`, `import_module`, on any
object (so `import os as o; o.system(...)`, `f = os.system` and `builtins.exec(...)` are caught), plus
`from os import system`-style imports. Network-capable imports are also rejected in `tests/` and `scripts/`.
**Not covered:** `getattr(os, "sys" + "tem")`-style tricks, code or names built at runtime, `os.system("curl ...")`
and similar outside `src/`, and anything in a third-party package. This is hygiene, not a sandbox; the runtime
socket guard is a second, partial layer (see above).

## Known limits of this documentation (read before trusting CI)

- **The CI workflow has never been executed.** Its two jobs were never run on a hosted runner (none was available);
  the commands they invoke were run locally and the YAML parses. A reviewer expects `core-no-deps` to pass given
  bare Python 3.12 and 3.13 local runs, and considers `optional-deps` unverifiable here.
- **Real Linux behaviour of `run_tests.sh` and the tests has never been observed.** Everything ran on macOS; a case-sensitive-APFS stand-in found one failure (above) and may hide others.
- **The torch/numpy pin is untested as a combination.** `constraints.txt` pins torch 2.7.1 + numpy 1.26.4 on Python
  3.12. Locally the suite passes on torch 2.7.1 + numpy 2.4.6 (framework Python 3.12) and torch 2.11.0 + numpy 2.4.4
  (miniconda Python 3.13), so local runs do not test the pinned combination. The pin is kept for reproducibility.
  The `numpy<2` rationale (NumPy/torch ABI mismatch seen in the RFdiffusion repo) holds regardless.
- **Whether `torch==2.7.1` resolves to the CPU wheel via `--extra-index-url` on Linux is untested.**
- **Actions are pinned by tag, not commit SHA** (`actions/checkout@v4`, `actions/setup-python@v5`).
- **The case-sensitive-filesystem counts come from the stand-in**, not from Linux.
- The script tests (see test collection for the count; `scripts/test_baseline.txt` records 13 modules) take about a minute because they run the scripts on synthetic suites and trees.

## What CI does

`.github/workflows/ci.yml`: job `core-no-deps` (Python 3.12 and 3.13, installs nothing, lint, suite twice with
`--expect none`, demo) and job `optional-deps` (Python 3.12, pinned torch 2.7.1 + numpy 1.26.4 (never executed; see limits above), suite twice with
`--expect torch`, unittest and pytest, demo). Read-only permissions, no secrets, no publishing.

## A bug in the runner that corrupted nested runs (fixed)

`run_tests.sh` used to clear bytecode across the whole repo on every invocation. The script's own tests invoke it on
synthetic suites, so they wiped the real repo's `__pycache__` while the surrounding test run was in progress, which
produced failure counts that varied between runs. A run with `--tests-dir` now clears bytecode only under that
directory; the default run still clears the whole tree (the standing rule). A regression test pins this with a
sentinel `__pycache__` outside the synthetic tests dir. After the fix, two consecutive full torch runs gave identical
results (914 run, 2 skipped, 0 failed, pytest 912 passed).
