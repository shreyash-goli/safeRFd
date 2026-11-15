#!/usr/bin/env python3
"""Tracked mutation harness. Closes SR-12's F17-R.

WHY THIS FILE EXISTS
--------------------
For roughly 28 attestation rounds this project built mutation harnesses in session scratchpads and
threw them away. `docs/PROGRESS.md` says "killed" 265 times and mentions a mutant 287 times; at the
same time `git ls-files | grep -icE "mutat|mutant"` returned 0. So the single decisive evidence class
behind most of the kit's checkboxes was not reproducible from a clone, which is what SR-16 graded its
clause 1 FAIL on. `docs/PROGRESS.md:3696-3706` records a KILL claim that later measured FALSE, caught
only because someone happened to re-run it; after that round the control no longer existed.

A harness in the repository is the whole fix. A mutant result is only evidence if a stranger can
re-derive it.

THE FIVE TRAPS THIS HARNESS IS BUILT AROUND
-------------------------------------------
Each one cost this project a wrong conclusion. They are encoded as refusals, not as advice.

1. THE BARE-EXTRACT TRAP. `tests/toy_tests/test_scripts.py` shells out to `git ls-files`. A plain
   `git archive HEAD` extract is not a git repository, so those tests fail in the CONTROL -- and a
   failing control makes every mutant read KILLED. SR-16 nearly shipped the opposite conclusion from
   this. Fix: `git init` the extract, and run the control FIRST and refuse to proceed if it fails.

2. THE `_FailedTest` TRAP. Requiring `Ran 1 test` does NOT separate a loader failure from a kill:
   when a named test method does not exist, unittest synthesises a `_FailedTest` that RUNS and FAILS,
   so a typo in a killer name looks exactly like a kill. Fix: resolve every killer through the real
   unittest loader before anything is mutated, and scan each run's output for loader markers.

3. THE UNAPPLIED-PATCH TRAP. A `find` string that no longer occurs matches nothing, the file is left
   pristine, the tests pass, and the mutant reports SURVIVED -- the most dangerous possible direction
   of error, because SURVIVED is the result that gets written down as a finding. Fix: the occurrence
   count must be exactly 1, and anything else fails the RUN, not the mutant.

4. THE RESTORE TRAP. Killing a harness with SIGTERM skips `finally`. One real run left
   `IntervalPair.__post_init__` replaced by `pass` in the working tree. Fix: this harness NEVER
   touches the working tree -- it mutates only its own extract -- and it verifies that invariant
   against `git status --porcelain` at entry and at every exit, including both signal paths.

5. THE ASYMMETRY. A targeted run PROVES a kill: a failing test implies a failing suite, at ~20x less
   cost. Nothing proves a survival -- only the full suite can assert that NOTHING catches a mutant.
   Fix: SURVIVED is reported as `SURVIVED_UNCONFIRMED` unless `--full` was passed, and the two are
   never collapsed in the output.

Usage:
    python3 scripts/mutate.py                 # every mutant in scripts/mutants.json
    python3 scripts/mutate.py --id Z-demo4-delete --id F16-empty-gates
    python3 scripts/mutate.py --full          # upgrade survivals to full-suite confirmation
    python3 scripts/mutate.py --list

Exit status is 0 only if every selected mutant was KILLED. An unapplied patch, a failed control, an
unresolvable killer, a loader failure or any survival is a nonzero exit.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = Path(__file__).resolve().parent / "mutants.json"

# Substrings that mean "unittest could not load what it was asked to run". Any of these in a run's
# output makes the result an ERROR, never a KILL -- trap 2.
LOADER_MARKERS = (
    "_FailedTest",
    "Failed to import test module",
    "has no attribute",
    "ModuleNotFoundError",
    "AttributeError: module",
)

KILLED, SURVIVED, ERROR = "KILLED", "SURVIVED", "ERROR"


class RunFailure(RuntimeError):
    """The harness itself is broken or its inputs are stale. Never a statement about a mutant."""


def tree_fingerprint(subject: Path = ROOT) -> str:
    """Hash of the subject tree's state. Trap 4: compared at entry and at every exit.

    In a git repository this is the dirty state (`status --porcelain` + `diff`), which is the sharp check.
    In an exported tree there is no index to diff against, so it is the sorted (path, size, mtime_ns) of
    every file -- weaker, but it still catches a harness that failed to restore, which is what trap 4 is
    for. It deliberately does NOT distinguish "the harness changed this tree" from "someone else did":
    a mutation result taken while the tree moved underneath it is not evidence, and refusing to certify
    it is the point.
    """
    if (subject / ".git").exists():
        out = subprocess.run(["git", "status", "--porcelain"], cwd=subject, capture_output=True,
                             text=True, check=True).stdout
        diff = subprocess.run(["git", "diff"], cwd=subject, capture_output=True, text=True,
                              check=True).stdout
        return hashlib.sha256((out + "\0" + diff).encode()).hexdigest()
    rows = []
    for f in sorted(subject.rglob("*")):
        if f.is_file() and "__pycache__" not in f.parts:
            st = f.stat()
            rows.append(f"{f.relative_to(subject)}\0{st.st_size}\0{st.st_mtime_ns}")
    return hashlib.sha256("\n".join(rows).encode()).hexdigest()


def make_extract(dest: Path, tree: Path | None = None) -> Path:
    """`git archive HEAD` into dest (or copy `tree` instead), then `git init` it. Trap 1.

    `tree` exists for workers that have no repository: a remote runner gets an EXPORTED tree, because
    `git archive HEAD` needs a commit and shipping `.git` is not an option -- commit objects carry author
    identity. The `git init` afterwards is NOT optional in either mode: `tests/toy_tests/test_scripts.py`
    shells out to `git ls-files`, so a plain extract fails the CONTROL, and a failing control makes every
    mutant read KILLED. SR-16 nearly shipped the opposite conclusion from exactly that.
    """
    dest.mkdir(parents=True, exist_ok=True)
    if tree is not None:
        if not (tree / "scripts" / "mutants.json").is_file():
            raise RunFailure(f"--tree {tree} does not look like this kit: scripts/mutants.json is absent")
        for item in tree.iterdir():
            if item.name == ".git":          # never copied, and never shipped to a worker
                continue
            (shutil.copytree if item.is_dir() else shutil.copy2)(item, dest / item.name)
    else:
        tar = dest.parent / "head.tar"
        with tar.open("wb") as fh:
            subprocess.run(["git", "archive", "HEAD"], cwd=ROOT, stdout=fh, check=True)
        subprocess.run(["tar", "-xf", str(tar), "-C", str(dest)], check=True)
        tar.unlink()
    env = {**os.environ, "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_SYSTEM": "/dev/null"}
    subprocess.run(["git", "init", "-q"], cwd=dest, check=True, env=env)
    subprocess.run(["git", "add", "-A"], cwd=dest, check=True, env=env)
    # A commit is not needed: `git ls-files` reads the index. No identity is configured, so no
    # author name or email is written anywhere by this harness.
    listed = subprocess.run(["git", "ls-files"], cwd=dest, capture_output=True, text=True,
                            check=True).stdout.split()
    if "scripts/demo.py" not in listed:
        raise RunFailure(f"extract's git index is wrong: {len(listed)} files, scripts/demo.py absent")
    return dest


def resolve_killers(extract: Path, names: list[str]) -> None:
    """Load every killer through the real unittest loader. Trap 2, done before any mutation."""
    env = {**os.environ, "PYTHONPATH": str(extract / "src"), "PYTHONDONTWRITEBYTECODE": "1",
           "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1"}
    probe = (
        "import sys, unittest\n"
        "bad = []\n"
        "for name in sys.argv[1:]:\n"
        "    try:\n"
        "        suite = unittest.defaultTestLoader.loadTestsFromName(name)\n"
        "    except Exception as exc:\n"
        "        bad.append(f'{name}: {type(exc).__name__}: {exc}'); continue\n"
        "    flat = list(suite)\n"
        "    while flat and isinstance(flat[0], unittest.TestSuite):\n"
        "        flat = [t for s in flat for t in s]\n"
        "    if not flat:\n"
        "        bad.append(f'{name}: loaded 0 tests')\n"
        "    for t in flat:\n"
        "        if type(t).__name__ == '_FailedTest':\n"
        "            bad.append(f'{name}: unittest synthesised _FailedTest -- the method does not exist')\n"
        "print('\\n'.join(bad))\n"
        "sys.exit(1 if bad else 0)\n"
    )
    r = subprocess.run([sys.executable, "-c", probe, *names], cwd=extract, env=env,
                       capture_output=True, text=True, timeout=300)
    if r.returncode != 0:
        raise RunFailure("killer test(s) do not resolve in a clean extract, so a run against them "
                         "could not distinguish a kill from a loader failure:\n" + r.stdout + r.stderr)


def run_tests(extract: Path, targets: list[str], timeout: int = 1800) -> subprocess.CompletedProcess:
    env = {**os.environ, "PYTHONPATH": str(extract / "src"), "PYTHONDONTWRITEBYTECODE": "1",
           "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1"}
    for pc in extract.rglob("__pycache__"):
        shutil.rmtree(pc, ignore_errors=True)
    return subprocess.run([sys.executable, "-m", "unittest", *targets], cwd=extract, env=env,
                          capture_output=True, text=True, timeout=timeout)


def classify(r: subprocess.CompletedProcess) -> tuple[str, str]:
    """KILLED only on a NAMED test failure. Anything else nonzero is an ERROR.

    THIS USED TO REPORT A FALSE KILL, found by independent QA. The old rule was "nonzero rc and no
    loader marker -> KILLED", with a marker list of five strings. MEASURED: a mutant that deleted one
    character so `src/toy/benchmark.py` no longer PARSES came back
    `KILLED  rc=1; no FAIL/ERROR line` and the run exited 0. No test discriminated anything; the
    harness credited a kill.

    Two things were wrong, and the second is the structural one:

    * the marker list missed `SyntaxError`, `IndentationError`, `ImportError` and anything else raised
      at module import -- a blocklist of strings, which is the shape this project distrusts everywhere
      else;
    * the loader PRE-FLIGHT runs on the UNMUTATED extract, so it can never catch a load failure
      CAUSED BY the mutation. `mutate.py`'s own header claimed that pre-flight closed this; it closes
      only the typo-in-a-killer-name half.

    So the test is now an ALLOWLIST on the evidence a kill is supposed to leave: unittest must report
    that it RAN tests (`Ran N test...`) and must name at least one `FAIL:`/`ERROR:` line. A crash
    before or during import satisfies neither and is reported as ERROR, which fails the RUN. This is
    the "reassuring direction of error" rule: an unexplained nonzero exit is not evidence.
    """
    blob = r.stdout + r.stderr
    hit = [m for m in LOADER_MARKERS if m in blob]
    if hit:
        return ERROR, f"loader markers present ({', '.join(hit)}): a load failure, not a kill"
    ran = re.search(r"(?m)^Ran (\d+) tests?", blob)
    named = [ln for ln in blob.splitlines() if ln.startswith(("FAIL:", "ERROR:"))]
    if r.returncode != 0:
        if ran is None:
            return ERROR, (f"rc={r.returncode} but unittest never reported `Ran N tests` -- the module "
                           f"did not load or the run died before collecting. NOT a kill")
        if not named:
            return ERROR, (f"rc={r.returncode}, {ran.group(1)} test(s) ran, but no FAIL:/ERROR: line "
                           f"names a failure. An unexplained nonzero exit is not evidence")
        return KILLED, f"rc={r.returncode}; " + "; ".join(named[:3])
    return SURVIVED, f"rc=0; {blob.strip().splitlines()[-1] if blob.strip() else 'no output'}"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--id", action="append", default=[], help="mutant id; repeatable")
    ap.add_argument("--full", action="store_true", help="confirm survivals against the full suite")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--keep", action="store_true", help="keep the extract for inspection")
    ap.add_argument("--tree", help="use this exported tree instead of `git archive HEAD` (for a worker "
                                   "with no repository); it is copied, never mutated in place")
    args = ap.parse_args()

    mutants = json.loads(MANIFEST.read_text())["mutants"]
    ids = [m["id"] for m in mutants]
    if len(set(ids)) != len(ids):
        raise RunFailure(f"duplicate mutant ids in {MANIFEST}")
    if args.list:
        for m in mutants:
            print(f"{m['id']:<28} {m['file']:<34} {len(m['killers'])} killer(s)  {m['note'][:60]}")
        return 0
    if args.id:
        unknown = set(args.id) - set(ids)
        if unknown:
            raise RunFailure(f"unknown mutant id(s): {sorted(unknown)}")
        mutants = [m for m in mutants if m["id"] in args.id]

    subject = Path(args.tree).resolve() if args.tree else ROOT
    _applied: dict[str, str] = {}      # extract path -> original text, for the signal path to restore
    before = tree_fingerprint(subject)
    tmp = Path(tempfile.mkdtemp(prefix="saferf_mut_"))

    def bail(signum, _frame):
        """Trap 4 on the signal path. RESTORE FIRST, THEN REMOVE -- it used to be the other way round.

        Found by independent QA: this removed the extract while a mutation was still applied, so the
        inner `finally: target.write_text(original)` then raised `FileNotFoundError`, which is not a
        `RunFailure`, so `__main__`'s handler did not catch it. The process died on an unhandled
        traceback with **exit 1, never 130** -- and `scripts/modal_mutants.py` reads any nonzero exit
        as NOT KILLED, i.e. it would report an interrupted or preempted container AS A FINDING. That is
        the exact direction this project says gets written down as a finding.

        The safety half was never in doubt and is re-checked here: the working tree is not touched.
        """
        for path, text in list(_applied.items()):
            try:
                Path(path).write_text(text)
            except OSError as exc:
                print(f"[signal {signum}] COULD NOT RESTORE {path}: {exc}", file=sys.stderr)
        state = "UNCHANGED" if tree_fingerprint(subject) == before else "*** CHANGED ***"
        print(f"\n[signal {signum}] aborting; {len(_applied)} mutation(s) restored first. "
              f"subject tree: {state}", file=sys.stderr)
        shutil.rmtree(tmp, ignore_errors=True)
        sys.exit(130)

    signal.signal(signal.SIGTERM, bail)
    signal.signal(signal.SIGINT, bail)

    try:
        extract = make_extract(tmp / "head", Path(args.tree) if args.tree else None)
        print(f"extract: {extract}")
        all_killers = sorted({k for m in mutants for k in m["killers"]})
        resolve_killers(extract, all_killers)
        print(f"killers resolve: {len(all_killers)} target(s)")

        t0 = time.time()
        control = run_tests(extract, all_killers)
        kind, why = classify(control)
        if kind != SURVIVED:
            raise RunFailure(f"CONTROL FAILED on an unmutated extract ({kind}: {why}). Every mutant "
                             f"would read KILLED for a reason that has nothing to do with the "
                             f"mutation. Trap 1. Output:\n{control.stdout[-3000:]}{control.stderr[-3000:]}")
        print(f"control: OK on unmutated extract ({time.time() - t0:.0f}s)\n")

        results = []
        for m in mutants:
            target = extract / m["file"]
            original = target.read_text()
            n = original.count(m["find"])
            if n != 1:
                raise RunFailure(f"[{m['id']}] anchor occurs {n} times in {m['file']} (need exactly 1). "
                                 f"Trap 3: an unapplied patch would have reported SURVIVED.")
            _applied[str(target)] = original
            target.write_text(original.replace(m["find"], m["replace"]))
            try:
                r = run_tests(extract, m["killers"])
                kind, why = classify(r)
                if kind == SURVIVED and args.full:
                    rf = run_tests(extract, ["discover", "-s", "tests"], timeout=3600)
                    k2, w2 = classify(rf)
                    kind, why = (k2, f"full suite: {w2}") if k2 != SURVIVED else (SURVIVED, f"full suite: {w2}")
                elif kind == SURVIVED:
                    kind, why = "SURVIVED_UNCONFIRMED", why + " (targeted only; --full to confirm)"
            finally:
                target.write_text(original)
                _applied.pop(str(target), None)
            results.append((m["id"], kind, why))
            print(f"{m['id']:<28} {kind:<20} {why[:110]}")

        print()
        bad = [r for r in results if r[1] != KILLED]
        for mid, kind, why in bad:
            print(f"NOT KILLED: {mid} -- {kind}: {why}")
        print(f"\n{len(results) - len(bad)}/{len(results)} KILLED")
        return 1 if bad else 0
    finally:
        after = tree_fingerprint(subject)
        print(f"working tree: {'UNCHANGED' if after == before else '*** CHANGED ***'}")
        if args.keep:
            print(f"extract kept: {tmp}")
        else:
            shutil.rmtree(tmp, ignore_errors=True)
        if after != before:
            raise RunFailure("the working tree changed during a mutation run; it must not. Trap 4.")


if __name__ == "__main__":
    try:
        sys.exit(main())
    except RunFailure as exc:
        print(f"\nRUN FAILURE: {exc}", file=sys.stderr)
        sys.exit(2)
