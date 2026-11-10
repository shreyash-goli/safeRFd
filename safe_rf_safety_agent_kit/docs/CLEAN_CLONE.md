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

## Expected counts (HEAD `9b2d928` plus the SR-15 files: 673 tests; later work adds more)

| Environment | unittest | pytest | `--expect` |
|---|---|---|---|
| Nothing installed (the clean-clone case) | 673 run, **86 skipped** | not run (not installed) | `none` |
| Nothing but PyYAML | 673 run, 85 skipped | not run | `none` |
| torch + numpy + pytest + PyYAML (macOS, MPS available) | 673 run, **2 skipped** | 671 passed, 2 skipped | `torch` |
| torch + numpy (Linux CPU) | 673 run, roughly 2-8 skipped (CUDA/MPS classes; not yet observed on Linux) | same skip count | `torch` |

The 86 = 85 torch/numpy skips + 1 skip of the optional PyYAML workflow-parse test. (At the base commit alone: 656 run,
85 skipped with nothing installed, 2 with torch+numpy.) The totals grow as tests are added; `run_tests.sh` enforces a floor (`MIN_TESTS`, default 650), not an exact number.
The skip policy is deliberately loose on the exact count but strict on reasons: with `--expect none` there must be
at least 50 skips, including ones that say "torch not installed" and "numpy not installed"; with `--expect torch`
no skip may say "not installed" and there may be at most 12 skips.

## Interpreting skips

A skip is a test that did **not run**, not a pass. Without torch the autograd, device and precision tests are
skipped with the reason "torch not installed ..." (CPU-vs-CUDA/MPS comparisons are UNKNOWN, never "passed").
With torch present, the remaining skips are hardware: no CUDA (always on a laptop), no MPS (non-Apple), and one
wiring test that only applies when torch is absent. A clean clone passing with ~86 skips means the stdlib core
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

## Network flags

`.env.example` sets `RUN_MODE=TOY_OFFLINE`, `ALLOW_EXTERNAL_NETWORK=false`, `MODEL_WEIGHTS_ENABLED=false`,
`BIOLOGICAL_TRAINING_ENABLED=false`, `TOY_SEED=42`. These flags govern the **toy application** (which never opens a
socket). They do **not** govern manual source verification: `docs/SOURCE_SNAPSHOT.json` preserves the compare
metadata for offline audit, and the `curl` commands recorded in `docs/DIFF_EVIDENCE.md` are documentation for a
human who chooses to re-verify against GitHub. No script, test or CI step runs them. No `.env` file is needed or read.

## What CI does

`.github/workflows/ci.yml`: job `core-no-deps` (Python 3.12 and 3.13, installs nothing, lint, suite twice with
`--expect none`, demo) and job `optional-deps` (Python 3.12, pinned torch 2.7.1 + numpy 1.26.4, suite twice with
`--expect torch`, unittest and pytest, demo). Read-only permissions, no secrets, no publishing.
