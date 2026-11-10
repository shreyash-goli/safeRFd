#!/usr/bin/env bash
# Deterministic, offline test runner for the TOY safety-audit kit (SR-15).
#
#   scripts/run_tests.sh [--expect none|torch|any] [--twice] [--no-network-guard]
#                        [--no-pytest] [--tests-dir D] [--baseline FILE|none] [--update-baseline]
#
#   --expect none   nothing third-party is installed: torch/numpy-dependent tests MUST report as skipped
#                   (with a reason naming the missing package); a silent pass is a failure.
#   --expect torch  torch+numpy installed: no test may be skipped for "not installed"; only device-specific
#                   skips (CUDA / MPS / the "torch present" wiring test) are allowed.
#   --expect any    (default) only consistency checks; counts are printed.
#   --twice         run the unittest suite a second time and require identical per-module counts and an
#                   identical skip list (determinism check).
#   --no-pytest     do not run pytest even if installed (used by the script's own tests for speed).
#   --tests-dir D   test directory (default: <repo>/tests, so the command works from any cwd; an explicit relative
#                   D is taken relative to the caller's cwd). Exists so the policy can be driven by synthetic suites. A run
#                   with --tests-dir clears bytecode ONLY under D; the default run clears the whole repo tree.
#   --baseline F    per-module baseline (default scripts/test_baseline.txt; "none" disables). One line per
#                   module: "<module> <tests> <bare-environment skips>". A module with FEWER tests than recorded
#                   fails, and with --expect none so does a module with FEWER skips than recorded: deleting tests,
#                   or turning a torch-guarded test into a silent early-return pass, is caught by module name
#                   rather than hidden under a loose global floor.
#   --update-baseline  rewrite the baseline from this run (requires --expect none and a baseline FILE, so
#                   `--baseline none --update-baseline` is a usage error rather than a file named `none` in the
#                   repo root; the diff is reviewable). The new file is STAGED by the Python stage and moved into
#                   place by the shell only if the WHOLE run ends RESULT: OK -- see "WHY the baseline is staged".
#
# Every policy failure line carries a stable token `POLICY:<NAME>`; tests match the token, not the prose.
# SKIP POLICY (case-insensitive; reasons are the only defence against a torch test passing silently):
#   none:  EVERY skip reason must name torch/numpy/pyyaml/pytest and say "not installed", "missing",
#          "unavailable" or "not available"; at least MIN_NONE_SKIPS (default 50) skips; at least one torch and
#          one numpy reason; no reason may say "torch present".
#   torch: EVERY skip reason must name cuda, mps or "torch present", and must not say "not installed",
#          "missing" or mention numpy; at most 12 skips.
#   Filesystem-case skips ("case-sensitive filesystem ...": Linux, case-sensitive APFS) are allowed in every mode, at
#   most 8, and are not counted toward the package-skip floor, the torch cap or the baseline (they were the first
#   observed failure of this script on a case-sensitive filesystem; see docs/CLEAN_CLONE.md).
#   Skips are recorded exactly (test id + reason) by a hook in the sitecustomize shim that runs inside the
#   unittest process only (the env var is popped, so child processes do not log), not by scraping output.
#
# WHY bytecode caching is disabled and __pycache__ is cleared first (STANDING RULE for this kit):
#   Three separate agents got contaminated mutation results from a stale .pyc (a source edit within the same
#   second as the cached compile reuses the old bytecode), and one spurious 10-failure spike was misattributed
#   to teammates because of it. Every run therefore starts from a tree with no bytecode and writes none.
#   (A child started with `python -I` ignores PYTHONDONTWRITEBYTECODE and may write .pyc; see docs/CLEAN_CLONE.md.)
#
# WHY PYTHONHASHSEED is fixed (default 0): str/bytes hashing is randomised per process, which changes set and
#   dict-of-set iteration order. Pinning it means a count difference between two runs is a real
#   non-determinism bug rather than hash-order noise. (The suite is also expected to pass under other seeds;
#   override with PYTHONHASHSEED=<n> to check.)
#
# WHY the baseline is staged rather than written where it is computed: the Python stage below can see only the
#   unittest log and its own skip-policy list. MIN_TESTS, SKIP_RECORD, PYTEST_FAILED, PYTEST_COLLECTED,
#   PYTEST_SKIPPED and NONDETERMINISTIC are all decided in the SHELL and were invisible to it, so
#   `MIN_TESTS=1000 ... --update-baseline` printed `baseline written:` and `RESULT: FAIL` in the same run and the
#   floor was recorded from a failing tree anyway. Python now writes a staging file and the shell moves it into
#   place only when FAIL is still 0, so "not written from a run that is not clean" covers EVERY policy failure.
#
# NETWORK (the .env.example flags are inert markers read by no code; this guard is the real mechanism, and it is
#   PYTHON-LEVEL ONLY): a sitecustomize shim replaces socket's connection and name-resolution entry points with a
#   function that raises, for the run and for children while they inherit PYTHONPATH. The patched names are the
#   `_BLOCK_MODULE`/`_BLOCK_SOCKET` tuples in the guard below and the deliberately unpatched ones are
#   `_NOT_BLOCKED`, each with its reason; read those tuples rather than any prose list, here or in the docs,
#   because the prose list went stale twice. It does NOT stop _socket.socket().connect, `python -I`/`-S`
#   children, or non-Python children (curl). See docs/CLEAN_CLONE.md for the full known-bypass list. The manual
#   `curl` commands in docs/DIFF_EVIDENCE.md are documentation for a human and are never executed here.
#
# NETWORK, the other direction: this script and its own tests must not emit a packet that leaves the host, so the
#   canary below and the negative controls in tests/toy_tests/test_scripts.py aim at a CLOSED LOOPBACK PORT
#   (127.0.0.1:1 -> ECONNREFUSED from the local stack). They used to aim at 192.0.2.1:9 (TEST-NET-1, which is
#   non-routable by convention only), and with the guard deliberately disabled -- which is how the negative
#   controls prove the guard is load-bearing -- that was a real outbound SYN on every run of the suite.
set -u -o pipefail

INVOKED_FROM="$PWD"   # saved before the cd to ROOT: a relative --tests-dir/--baseline means the CALLER's cwd
EXPECT=any
TWICE=0
GUARD=1
TESTS_DIR=""   # empty = not given; resolved to $ROOT/tests AFTER cd (it used to be resolved against $PWD BEFORE
               # the cd, so the documented default run failed with "tests dir not found" from any other cwd)
SCOPED=0     # --tests-dir given: a nested/driven run must NOT touch the rest of the repo
BASELINE=""
UPDATE=0
NOPYTEST=0
while [ $# -gt 0 ]; do
  case "$1" in
    --expect) EXPECT="${2:-}"; shift 2 ;;
    --twice) TWICE=1; shift ;;
    --no-network-guard) GUARD=0; shift ;;
    --no-pytest) NOPYTEST=1; shift ;;
    --tests-dir) TESTS_DIR="${2:-}"; SCOPED=1; shift 2 ;;
    --baseline) BASELINE="${2:-}"; shift 2 ;;
    --update-baseline) UPDATE=1; shift ;;
    # Print the WHOLE leading comment header (was `sed -n '2,42p'`, which silently truncated the NETWORK section
    # when the header grew past line 42; awk stops at the first non-comment line, so it cannot go stale again).
    -h|--help) awk 'NR == 1 { next } /^#/ { print; next } { exit }' "$0"; exit 0 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done
case "$EXPECT" in none|torch|any) ;; *) echo "--expect must be none|torch|any" >&2; exit 2 ;; esac
if [ "$UPDATE" = 1 ] && [ "$EXPECT" != none ]; then echo "--update-baseline requires --expect none" >&2; exit 2; fi
# `none` is the sentinel that DISABLES the baseline. It was honoured in the comparison branch and not in the
# update branch, which did an unconditional open(base, "w"): `--baseline none --update-baseline` wrote a real
# baseline into a file literally named `none` in the repo root (untracked, not in .gitignore) for a user who had
# just asked for no baseline at all. Erroring matches the --expect check immediately above.
if [ "$UPDATE" = 1 ] && [ "$BASELINE" = none ]; then
  echo "--update-baseline requires a baseline FILE: --baseline none disables the baseline, and updating it would" >&2
  echo "write a file literally named 'none' into the repository root. Pass --baseline <path>, or drop --update-baseline." >&2
  exit 2
fi

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# Paths are resolved HERE, after ROOT is known: the DEFAULT tests dir and baseline belong to the repo the script
# lives in (so the documented commands work from any cwd), while an explicit RELATIVE path is resolved against the
# caller's cwd, which is what the caller means by it.
if [ -z "$TESTS_DIR" ]; then TESTS_DIR="$ROOT/tests"
else case "$TESTS_DIR" in /*) ;; *) TESTS_DIR="$INVOKED_FROM/$TESTS_DIR" ;; esac
fi
if [ -z "$BASELINE" ]; then BASELINE="$ROOT/scripts/test_baseline.txt"
elif [ "$BASELINE" != none ]; then case "$BASELINE" in /*) ;; *) BASELINE="$INVOKED_FROM/$BASELINE" ;; esac
fi
[ -d "$TESTS_DIR" ] || { echo "tests dir not found: $TESTS_DIR" >&2; exit 2; }
cd "$ROOT" || exit 2

export PYTHONDONTWRITEBYTECODE=1
export PYTHONHASHSEED="${PYTHONHASHSEED:-0}"
export MIN_TESTS="${MIN_TESTS:-650}"             # global floor (-ge); the per-module baseline is the sharp check
export MIN_NONE_SKIPS="${MIN_NONE_SKIPS:-50}"

clear_bytecode() {
  # Default (top-level) run: clear the whole repo tree, as the standing rule requires. With --tests-dir (a run driven
  # by a test against a synthetic suite while an outer run may be using the real tree) clear ONLY that directory:
  # wiping the repo's bytecode mid-run corrupted the surrounding run (varying failure counts).
  if [ "$SCOPED" = 0 ]; then
    find . \( -name .git -o -name .venv -o -name venv -o -name node_modules \) -prune -o \
      \( -name __pycache__ -type d -print0 \) | xargs -0 rm -rf
    find . \( -name .git -o -name .venv -o -name venv \) -prune -o -name '*.pyc' -type f -print0 | xargs -0 rm -f
  fi
  find "$TESTS_DIR" \( -name __pycache__ -type d -print0 \) | xargs -0 rm -rf
  find "$TESTS_DIR" -name '*.pyc' -type f -print0 | xargs -0 rm -f
}
clear_bytecode

TMP="$(mktemp -d "${TMPDIR:-/tmp}/saferf_tests.XXXXXX")"
trap 'rm -rf "$TMP"' EXIT

mkdir -p "$TMP/guard"
cat > "$TMP/guard/sitecustomize.py" <<'PY'
import os as _os
_log = _os.environ.pop("SAFERF_SKIP_LOG", None)   # popped: child processes do not inherit and do not log
if _log:
    import json as _json
    import unittest as _ut
    _f = open(_log, "a", buffering=1, encoding="utf-8")
    _start, _skip = _ut.TestResult.startTest, _ut.TestResult.addSkip
    def _startTest(self, test):
        _f.write(_json.dumps({"e": "start", "id": test.id()}) + "\n")
        return _start(self, test)
    def _addSkip(self, test, reason):
        _f.write(_json.dumps({"e": "skip", "id": test.id(), "reason": str(reason)}) + "\n")
        return _skip(self, test, reason)
    _ut.TestResult.startTest, _ut.TestResult.addSkip = _startTest, _addSkip
PY
if [ "$GUARD" = 1 ]; then
  cat >> "$TMP/guard/sitecustomize.py" <<'PY'
import socket as _s
def _blocked(*a, **k):
    raise OSError("NETWORK BLOCKED by scripts/run_tests.sh: the offline suite must not touch the network")
# The patch list is DATA, not a sequence of assignments, because the assignment version grew one name per review
# round -- gethostbyname_ex, then getnameinfo, then gethostbyaddr/getfqdn -- each time patching the names that
# reviewer happened to test instead of the family, so the next name anyone tested reproduced the defect.
# tests/toy_tests/test_scripts.py parses these three tuples out of this file and asserts that
#   (1) EVERY member of socket's connection/name-resolution family, enumerated from the live `socket` module,
#       is named in exactly one of them -- so a name that is neither patched nor disclosed fails the suite; and
#   (2) every patched name has a test that drives it through this script with the guard on and off.
# docs/CLEAN_CLONE.md points at these tuples instead of restating them, so the disclosure cannot go stale.
_BLOCK_MODULE = ("create_connection", "create_server", "getaddrinfo", "getfqdn", "gethostbyaddr",
                 "gethostbyname", "gethostbyname_ex", "getnameinfo")
_BLOCK_SOCKET = ("connect", "connect_ex", "bind", "listen", "sendto", "sendmsg")
# KNOWN-UNPATCHED and therefore DISCLOSED, each with the reason it is left alone:
#   gethostname, getservbyname, getservbyport, getprotobyname -- purely local lookups (the host's own name,
#     /etc/services, /etc/protocols); they originate no traffic. gethostbyname/getfqdn, which DO resolve, are
#     patched, so gethostbyname(gethostname()) is still blocked.
#   send, sendall, sendfile, accept -- reachable only through a connect/bind/listen that IS patched.
# This is still a Python-level tripwire, not a sandbox: see the NETWORK note in the header.
_NOT_BLOCKED = ("gethostname", "getservbyname", "getservbyport", "getprotobyname",
                "send", "sendall", "sendfile", "accept")
for _n in _BLOCK_MODULE:
    setattr(_s, _n, _blocked)
for _n in _BLOCK_SOCKET:
    setattr(_s.socket, _n, _blocked)
PY
fi
export PYTHONPATH="$TMP/guard${PYTHONPATH:+:$PYTHONPATH}"
if [ "$GUARD" = 1 ]; then
  # 127.0.0.1:1 is a CLOSED LOOPBACK PORT: if the guard is missing this fails instantly with "connection
  # refused" from the local stack and nothing leaves the host. It used to be 192.0.2.1:9, which is unroutable
  # only by convention -- the kernel still sent the SYN, on every run where the guard was absent.
  CANARY="$(python3 -c "import socket; socket.create_connection(('127.0.0.1', 1), timeout=1)" 2>&1 || true)"
  case "$CANARY" in *"NETWORK BLOCKED"*) ;; *)
    echo "FAIL: POLICY:CANARY network guard canary did not trigger; refusing to run" >&2; exit 1 ;;
  esac
  echo "network guard: active, python-level only (canary connect attempt was blocked)"
fi

echo "python: $(python3 --version 2>&1)  PYTHONHASHSEED=$PYTHONHASHSEED  expect=$EXPECT"
for m in torch numpy; do
  if python3 -c "import $m" 2>/dev/null; then echo "optional $m: present"; else echo "optional $m: absent"; fi
done

run_unittest() {  # $1 = log path; skips/starts are recorded to $1.jsonl
  : > "$1.jsonl"
  SAFERF_SKIP_LOG="$1.jsonl" python3 -m unittest discover -s "$TESTS_DIR" -v >"$1" 2>&1
  return $?
}

# policy LOG CANON_OUT STAGE -> prints counts, applies skip/baseline policy, writes canonical summary; exit 1 on
# violation. STAGE is where an --update-baseline run leaves the NEW baseline for the shell to move into place.
policy() {
  # ARITY, checked rather than assumed. Under `set -u` a missing $3 is not a command failure but a FATAL SHELL
  # ERROR: bash prints `line 220: $3: unbound variable` and the whole script exits 1 on the spot -- before any
  # policy verdict, before the pytest block and before `RESULT:` is printed. (Reproduced deliberately: the run
  # had already printed `unittest: ran=1 ... rc=0`, so a scraper reading only that line could be misled, but the
  # exit status is 1 and `RESULT: OK` never appears, so no verdict can be silently dropped and no caller can
  # mistake it for a pass. `|| FAIL=1` does not even run.)
  # This was reported once under concurrent test execution. It is NOT a latent call path: there are exactly two
  # call sites and both pass three arguments. The cause is that this script's own tests COPY the live script
  # (see synth_root in tests/toy_tests/test_scripts.py) and run the copy, so a concurrent run read the file
  # inside the window in which `policy` had grown its third parameter and the two call sites had not yet been
  # updated. That is the same class as the stale-.pyc and read-mid-edit incidents in docs/CLEAN_CLONE.md.
  # The arity is therefore named: a wrong count now fails loudly as POLICY:INTERNAL (red run, stable token)
  # instead of as a bash diagnostic. Deliberately NOT a default (`${3:-...}`) -- defaulting would let a
  # genuinely miscalled policy() stage a baseline somewhere nobody asked for, which is the D2 defect again.
  [ "$#" -eq 3 ] || { echo "FAIL: POLICY:INTERNAL policy() takes 3 arguments (log, canon-out, baseline-stage), got $#"; return 2; }
  EXPECT="$EXPECT" LOG="$1" CANON="$2" STAGE="$3" BASELINE="$BASELINE" UPDATE="$UPDATE" python3 - <<'PY'
import json, os, re, sys
mode, base, update = os.environ["EXPECT"], os.environ["BASELINE"], os.environ["UPDATE"] == "1"
stage = os.environ["STAGE"]
min_none = int(os.environ["MIN_NONE_SKIPS"])
text = open(os.environ["LOG"], encoding="utf-8", errors="replace").read()
m = re.search(r"^Ran (\d+) tests?", text, re.M)
ran_log = int(m.group(1)) if m else 0
starts, skips = [], []
for line in open(os.environ["LOG"] + ".jsonl", encoding="utf-8"):
    e = json.loads(line)
    (starts if e["e"] == "start" else skips).append(e)
def mod(i):
    mm = re.match(r"^(.*)\.[A-Za-z_]\w*\.\w+$", i)
    return mm.group(1) if mm else i
ran_mod, skip_mod = {}, {}
for e in starts: ran_mod[mod(e["id"])] = ran_mod.get(mod(e["id"]), 0) + 1
for e in skips: skip_mod[mod(e["id"])] = skip_mod.get(mod(e["id"]), 0) + 1
bad = []
print(f"skip policy ({mode}): {len(skips)} skipped across {len(skip_mod)} modules; {len(starts)} tests started")
if len(starts) < ran_log: bad.append(f"POLICY:RECORDER recorder saw {len(starts)} tests but unittest ran {ran_log}")
reasons = [e["reason"] for e in skips]
for e in skips:
    if not e["reason"].strip(): bad.append("POLICY:EMPTY_REASON empty skip reason: " + e["id"])
# Environment skips unrelated to optional packages: the filesystem is case-sensitive (Linux, case-sensitive APFS), so
# tests of case-variant paths cannot run. Allowed in every mode, but capped and never counted toward the floors, so
# they cannot pad the bare-mode skip count or hide a torch test.
FS = re.compile(r"case[- ]sensitive", re.I)
fs = [e for e in skips if FS.search(e["reason"])]
pkg = [e for e in skips if not FS.search(e["reason"])]
if len(fs) > 8: bad.append(f"POLICY:FS_CAP {len(fs)} filesystem-case skips; at most 8 are expected (found on a case-sensitive filesystem)")
if fs: print(f"note: {len(fs)} skip(s) for a case-sensitive filesystem (expected on Linux); not counted toward package skips")
if mode == "none":
    NONE_OK = re.compile(r"(torch|numpy|pyyaml|pytest).*(not installed|missing|unavailable|not available)", re.I | re.S)
    for e in pkg:
        if not NONE_OK.search(e["reason"]): bad.append(f"POLICY:NONE_REASON skip reason does not say a package is missing: {e['id']} :: {e['reason']!r}")
    for e in skips:
        if re.search(r"torch present", e["reason"], re.I): bad.append("POLICY:TORCH_PRESENT a skip says torch is present although none is expected: " + e["id"])
    if len(pkg) < min_none: bad.append(f"POLICY:MIN_NONE_SKIPS expected >= {min_none} package skips with nothing installed, got {len(pkg)}: torch tests may be passing silently or were removed")
    if not any(re.search(r"torch", e["reason"], re.I) for e in pkg): bad.append("POLICY:NO_TORCH_REASON no skip mentions torch")
    if not any(re.search(r"numpy", e["reason"], re.I) for e in pkg): bad.append("POLICY:NO_NUMPY_REASON no skip mentions numpy")
elif mode == "torch":
    ALLOW = re.compile(r"\bcuda\b|\bmps\b|torch present", re.I)
    DENY = re.compile(r"not installed|missing|numpy", re.I)
    for e in skips:
        if DENY.search(e["reason"]): bad.append(f"POLICY:TORCH_MODE_MISSING torch expected but skipped as missing: {e['id']} :: {e['reason']!r}")
    for e in pkg:
        if not DENY.search(e["reason"]) and not ALLOW.search(e["reason"]): bad.append(f"POLICY:TORCH_MODE_UNEXPLAINED unexplained skip with torch present: {e['id']} :: {e['reason']!r}")
    if len(pkg) > 12: bad.append(f"POLICY:TORCH_CAP {len(pkg)} skips with torch present; at most 12 (CUDA/MPS/wiring) are allowed")
# per-module baseline
if update and mode == "none":
    # REFUSE to record a baseline from a run that is not clean. This used to write unconditionally,
    # and it did: a 14-minute bare run went red with three false failures (a module read mid-edit by
    # another process) and the baseline was rewritten from it anyway. A baseline captured from a red
    # or mid-refactor tree silently encodes whatever was broken at that moment as the floor, which is
    # the exact defect the per-module baseline exists to catch. The run's own failure is not enough
    # to stop it, because the write happens before the exit code is decided.
    # A refused update does NOT fall through to the comparison branch below: it is still an update
    # attempt, and comparing a red run against the old baseline would pile POLICY:BASELINE_* failures
    # on top of the real cause and bury it.
    # "A run that is not clean" means the run's whole RESULT, not just the part visible here. The two
    # predicates below (the unittest log ended in OK; `bad` is empty) are everything a process that sees
    # only the log and the skip recorder CAN check -- MIN_TESTS, SKIP_RECORD, the three PYTEST_* checks and
    # NONDETERMINISTIC are decided in the shell. So this branch does not write `base`; it STAGES the new
    # content and the shell moves it into place only if FAIL is still 0 at the end of the run. Before that
    # split, `MIN_TESTS=1000 ... --update-baseline` printed "baseline written:" and then "RESULT: FAIL".
    run_ok = re.search(r"^OK\b", text, re.M) is not None and re.search(r"^FAILED\b", text, re.M) is None
    if bad or not run_ok:
        why = []
        if not run_ok: why.append("the test run did not end in OK")
        if bad: why.append(f"{len(bad)} skip-policy failure(s)")
        bad.append("POLICY:BASELINE_REFUSED --update-baseline refused and the baseline is UNCHANGED: "
                   + "; ".join(why) + ". Regenerate only on a quiet, green tree.")
    else:
        rows = sorted((k, ran_mod[k], sum(1 for e in skips if mod(e["id"]) == k and not re.search("yaml|case[- ]sensitive", e["reason"], re.I))) for k in ran_mod)
        with open(stage, "w", encoding="utf-8") as f:
            f.write("# module  tests  bare-environment-skips   (generated: scripts/run_tests.sh --expect none --update-baseline)\n")
            f.write("# Fewer tests, or (bare mode) fewer skips, than recorded here fails the run. Raise only by regenerating.\n")
            for k, r, s_ in rows: f.write(f"{k} {r} {s_}\n")
        print(f"baseline staged for {base} ({len(rows)} modules); it is written only if this run ends RESULT: OK")
elif base != "none" and os.path.exists(base):
    for line in open(base, encoding="utf-8"):
        if not line.strip() or line.startswith("#"): continue
        k, r, s_ = line.split(); r, s_ = int(r), int(s_)
        if ran_mod.get(k, 0) < r: bad.append(f"POLICY:BASELINE_TESTS baseline: module {k} ran {ran_mod.get(k, 0)} tests, baseline {r} (tests deleted?)")
        elif mode == "none":
            got = sum(1 for e in skips if mod(e["id"]) == k and not re.search("yaml|case[- ]sensitive", e["reason"], re.I))
            if got < s_: bad.append(f"POLICY:BASELINE_SKIPS baseline: module {k} has {got} bare-environment skips, baseline {s_} (guarded tests now pass silently?)")
    known = {l.split()[0] for l in open(base, encoding="utf-8") if l.strip() and not l.startswith("#")}
    new = sorted(set(ran_mod) - known)
    if new: print("note: modules not in baseline (regenerate to track):", ", ".join(new))
elif base != "none":
    print(f"note: baseline file {base} not found; per-module check skipped")
with open(os.environ["CANON"], "w", encoding="utf-8") as f:
    for k in sorted(ran_mod): f.write(f"ran {k} {ran_mod[k]}\n")
    for e in sorted(skips, key=lambda e: (e["id"], e["reason"])): f.write(f"skip {e['id']} :: {e['reason']}\n")
for b in bad: print("FAIL:", b)
print(f"{ran_log} {len(skips)}", file=open(os.environ["CANON"] + ".counts", "w"))
sys.exit(1 if bad else 0)
PY
}

summarize() {  # $1 = log; "RAN SKIPPED FAILED" from the unittest summary lines
  python3 - "$1" <<'PY'
import re, sys
t = open(sys.argv[1], encoding="utf-8", errors="replace").read()
ran = re.search(r"^Ran (\d+) tests?", t, re.M)
last = t.strip().splitlines()[-1] if t.strip() else ""
skipped = re.search(r"skipped=(\d+)", last)
print(ran.group(1) if ran else "0", skipped.group(1) if skipped else "0", "1" if last.startswith("FAILED") else "0")
PY
}

FAIL=0
echo "== unittest discover =="
if run_unittest "$TMP/ut1.log"; then UT_RC=0; else UT_RC=$?; fi
tail -n 4 "$TMP/ut1.log"
read -r RAN SKIPPED BAD < <(summarize "$TMP/ut1.log")
echo "unittest: ran=$RAN skipped=$SKIPPED failed=$BAD rc=$UT_RC"
[ "$UT_RC" -eq 0 ] || { echo "FAIL: POLICY:UNITTEST_FAILED unittest suite failed"; grep -E "^(FAIL|ERROR):" "$TMP/ut1.log" | head -30; FAIL=1; }
[ "$RAN" -ge "$MIN_TESTS" ] || { echo "FAIL: POLICY:MIN_TESTS only $RAN tests ran (floor MIN_TESTS=$MIN_TESTS)"; FAIL=1; }
policy "$TMP/ut1.log" "$TMP/canon1.txt" "$TMP/base.staged" || FAIL=1
if [ -f "$TMP/canon1.txt.counts" ]; then
  read -r _ NSK < "$TMP/canon1.txt.counts"
  [ "$NSK" = "$SKIPPED" ] || { echo "FAIL: POLICY:SKIP_RECORD recorded skips ($NSK) != reported skips ($SKIPPED)"; FAIL=1; }
fi

if [ "$NOPYTEST" = 1 ]; then
  echo "== pytest == SKIPPED: --no-pytest"
elif python3 -c "import pytest" 2>/dev/null; then
  echo "== pytest =="
  # -p no:cacheprovider: do not create .pytest_cache in the repo.
  if python3 -m pytest -q -p no:cacheprovider "$TESTS_DIR" >"$TMP/pt.log" 2>&1; then PT_RC=0; else PT_RC=$?; fi
  tail -n 2 "$TMP/pt.log"
  PT_PASSED=$(grep -Eo '[0-9]+ passed' "$TMP/pt.log" | tail -1 | cut -d' ' -f1); PT_PASSED=${PT_PASSED:-0}
  PT_SKIPPED=$(grep -Eo '[0-9]+ skipped' "$TMP/pt.log" | tail -1 | cut -d' ' -f1); PT_SKIPPED=${PT_SKIPPED:-0}
  PT_FAILED=$(grep -Eo '[0-9]+ failed' "$TMP/pt.log" | tail -1 | cut -d' ' -f1); PT_FAILED=${PT_FAILED:-0}
  echo "pytest: passed=$PT_PASSED skipped=$PT_SKIPPED failed=$PT_FAILED rc=$PT_RC"
  [ "$PT_RC" -eq 0 ] || { echo "FAIL: POLICY:PYTEST_FAILED pytest failed"; FAIL=1; }
  [ "$((PT_PASSED + PT_SKIPPED + PT_FAILED))" -eq "$RAN" ] || { echo "FAIL: POLICY:PYTEST_COLLECTED pytest collected $((PT_PASSED + PT_SKIPPED + PT_FAILED)) tests, unittest ran $RAN"; FAIL=1; }
  [ "$PT_SKIPPED" -eq "$SKIPPED" ] || { echo "FAIL: POLICY:PYTEST_SKIPPED pytest skipped $PT_SKIPPED, unittest skipped $SKIPPED"; FAIL=1; }
else
  echo "== pytest == SKIPPED: pytest is not installed (optional; unittest results above are authoritative)"
fi

if [ "$TWICE" = 1 ]; then
  echo "== unittest, second run (determinism) =="
  clear_bytecode
  if run_unittest "$TMP/ut2.log"; then UT_RC2=0; else UT_RC2=$?; fi
  read -r RAN2 SKIPPED2 BAD2 < <(summarize "$TMP/ut2.log")
  # A separate staging path: only run 1's staged baseline is ever moved into place, so run 2 cannot overwrite it.
  policy "$TMP/ut2.log" "$TMP/canon2.txt" "$TMP/base2.staged" >/dev/null || true
  if [ "$RAN $SKIPPED $BAD $UT_RC" = "$RAN2 $SKIPPED2 $BAD2 $UT_RC2" ] && cmp -s "$TMP/canon1.txt" "$TMP/canon2.txt"; then
    echo "deterministic: run1 == run2 (ran=$RAN skipped=$SKIPPED failed=$BAD, identical per-module counts and skip list)"
  else
    echo "FAIL: POLICY:NONDETERMINISTIC non-deterministic: run1 ran=$RAN skipped=$SKIPPED failed=$BAD rc=$UT_RC ; run2 ran=$RAN2 skipped=$SKIPPED2 failed=$BAD2 rc=$UT_RC2"
    diff "$TMP/canon1.txt" "$TMP/canon2.txt" | head -20; FAIL=1
  fi
fi

# --update-baseline, second half: the Python stage STAGED the new baseline (it can see only the unittest log and
# its own skip policy); it is moved into place HERE, after every shell-side check has had its say, and only if the
# run is still clean. This is the point of the split -- POLICY:MIN_TESTS, SKIP_RECORD, PYTEST_FAILED,
# PYTEST_COLLECTED, PYTEST_SKIPPED and NONDETERMINISTIC are all set out here and were invisible to the refusal.
if [ "$UPDATE" = 1 ] && [ -f "$TMP/base.staged" ]; then
  if [ "$FAIL" -eq 0 ]; then
    if mv "$TMP/base.staged" "$BASELINE"; then
      echo "baseline written: $BASELINE ($(grep -cv '^#' "$BASELINE" || true) modules)"
    else
      echo "FAIL: POLICY:BASELINE_WRITE could not write the staged baseline to $BASELINE"; FAIL=1
    fi
  else
    echo "FAIL: POLICY:BASELINE_REFUSED --update-baseline refused and the baseline is UNCHANGED: this run's"\
         "RESULT is FAIL (see the failures above). Regenerate only on a quiet, green tree."
  fi
fi

# Leave the tree clean (no bytecode / caches).
clear_bytecode
if [ "$FAIL" -ne 0 ]; then echo "RESULT: FAIL"; exit 1; fi
echo "RESULT: OK (unittest ran=$RAN skipped=$SKIPPED)"
