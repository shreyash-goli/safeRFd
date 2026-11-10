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
#   --tests-dir D   test directory (default: tests). Exists so the policy can be driven by synthetic suites.
#   --baseline F    per-module baseline (default scripts/test_baseline.txt; "none" disables). One line per
#                   module: "<module> <tests> <bare-environment skips>". A module with FEWER tests than recorded
#                   fails, and with --expect none so does a module with FEWER skips than recorded: deleting tests,
#                   or turning a torch-guarded test into a silent early-return pass, is caught by module name
#                   rather than hidden under a loose global floor.
#   --update-baseline  rewrite the baseline from this run (requires --expect none; the diff is reviewable).
#
# SKIP POLICY (case-insensitive; reasons are the only defence against a torch test passing silently):
#   none:  EVERY skip reason must name torch/numpy/pyyaml/pytest and say "not installed", "missing",
#          "unavailable" or "not available"; at least MIN_NONE_SKIPS (default 50) skips; at least one torch and
#          one numpy reason; no reason may say "torch present".
#   torch: EVERY skip reason must name cuda, mps or "torch present", and must not say "not installed",
#          "missing" or mention numpy; at most 12 skips.
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
# NETWORK (the .env.example flags are inert markers read by no code; this guard is the real mechanism, and it is
#   PYTHON-LEVEL ONLY): a sitecustomize shim makes socket.socket.connect / connect_ex, socket.create_connection,
#   getaddrinfo and gethostbyname raise for the run, children included while they inherit PYTHONPATH. It does NOT
#   stop _socket.socket().connect, UDP sendto, gethostbyname_ex, `python -I` children, or non-Python children
#   (curl). See docs/CLEAN_CLONE.md. The manual `curl` commands in docs/DIFF_EVIDENCE.md are documentation for a
#   human and are never executed here.
set -u -o pipefail

EXPECT=any
TWICE=0
GUARD=1
TESTS_DIR=tests
BASELINE=""
UPDATE=0
NOPYTEST=0
while [ $# -gt 0 ]; do
  case "$1" in
    --expect) EXPECT="${2:-}"; shift 2 ;;
    --twice) TWICE=1; shift ;;
    --no-network-guard) GUARD=0; shift ;;
    --no-pytest) NOPYTEST=1; shift ;;
    --tests-dir) TESTS_DIR="${2:-}"; shift 2 ;;
    --baseline) BASELINE="${2:-}"; shift 2 ;;
    --update-baseline) UPDATE=1; shift ;;
    -h|--help) sed -n '2,38p' "$0"; exit 0 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done
case "$EXPECT" in none|torch|any) ;; *) echo "--expect must be none|torch|any" >&2; exit 2 ;; esac
if [ "$UPDATE" = 1 ] && [ "$EXPECT" != none ]; then echo "--update-baseline requires --expect none" >&2; exit 2; fi
case "$TESTS_DIR" in /*) ;; *) TESTS_DIR="$PWD/$TESTS_DIR" ;; esac
[ -d "$TESTS_DIR" ] || { echo "tests dir not found: $TESTS_DIR" >&2; exit 2; }

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
[ -n "$BASELINE" ] || BASELINE="$ROOT/scripts/test_baseline.txt"
cd "$ROOT" || exit 2

export PYTHONDONTWRITEBYTECODE=1
export PYTHONHASHSEED="${PYTHONHASHSEED:-0}"
export MIN_TESTS="${MIN_TESTS:-650}"             # global floor (-ge); the per-module baseline is the sharp check
export MIN_NONE_SKIPS="${MIN_NONE_SKIPS:-50}"

clear_bytecode() {
  find . \( -name .git -o -name .venv -o -name venv -o -name node_modules \) -prune -o \
    \( -name __pycache__ -type d -print0 \) | xargs -0 rm -rf
  find . \( -name .git -o -name .venv -o -name venv \) -prune -o -name '*.pyc' -type f -print0 | xargs -0 rm -f
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
_s.socket.connect = _blocked
_s.socket.connect_ex = _blocked
_s.create_connection = _blocked
_s.getaddrinfo = _blocked
_s.gethostbyname = _blocked
PY
fi
export PYTHONPATH="$TMP/guard${PYTHONPATH:+:$PYTHONPATH}"
if [ "$GUARD" = 1 ]; then
  CANARY="$(python3 -c "import socket; socket.create_connection(('192.0.2.1', 9), timeout=1)" 2>&1 || true)"
  case "$CANARY" in *"NETWORK BLOCKED"*) ;; *)
    echo "FAIL: network guard canary did not trigger; refusing to run" >&2; exit 1 ;;
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

# policy LOG CANON_OUT -> prints counts, applies skip/baseline policy, writes canonical summary; exit 1 on violation
policy() {
  EXPECT="$EXPECT" LOG="$1" CANON="$2" BASELINE="$BASELINE" UPDATE="$UPDATE" python3 - <<'PY'
import json, os, re, sys
mode, base, update = os.environ["EXPECT"], os.environ["BASELINE"], os.environ["UPDATE"] == "1"
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
if len(starts) < ran_log: bad.append(f"recorder saw {len(starts)} tests but unittest ran {ran_log}")
reasons = [e["reason"] for e in skips]
for e in skips:
    if not e["reason"].strip(): bad.append("empty skip reason: " + e["id"])
if mode == "none":
    NONE_OK = re.compile(r"(torch|numpy|pyyaml|pytest).*(not installed|missing|unavailable|not available)", re.I | re.S)
    for e in skips:
        if not NONE_OK.search(e["reason"]): bad.append(f"skip reason does not say a package is missing: {e['id']} :: {e['reason']!r}")
        if re.search(r"torch present", e["reason"], re.I): bad.append("a skip says torch is present although none is expected: " + e["id"])
    if len(skips) < min_none: bad.append(f"expected >= {min_none} skips with nothing installed, got {len(skips)}: torch tests may be passing silently or were removed")
    if not any(re.search(r"torch", r, re.I) for r in reasons): bad.append("no skip mentions torch")
    if not any(re.search(r"numpy", r, re.I) for r in reasons): bad.append("no skip mentions numpy")
elif mode == "torch":
    ALLOW = re.compile(r"\bcuda\b|\bmps\b|torch present", re.I)
    DENY = re.compile(r"not installed|missing|numpy", re.I)
    for e in skips:
        if DENY.search(e["reason"]): bad.append(f"torch expected but skipped as missing: {e['id']} :: {e['reason']!r}")
        elif not ALLOW.search(e["reason"]): bad.append(f"unexplained skip with torch present: {e['id']} :: {e['reason']!r}")
    if len(skips) > 12: bad.append(f"{len(skips)} skips with torch present; at most 12 (CUDA/MPS/wiring) are allowed")
# per-module baseline
if update and mode == "none":
    rows = sorted((k, ran_mod[k], sum(1 for e in skips if mod(e["id"]) == k and not re.search("yaml", e["reason"], re.I))) for k in ran_mod)
    with open(base, "w", encoding="utf-8") as f:
        f.write("# module  tests  bare-environment-skips   (generated: scripts/run_tests.sh --expect none --update-baseline)\n")
        f.write("# Fewer tests, or (bare mode) fewer skips, than recorded here fails the run. Raise only by regenerating.\n")
        for k, r, s_ in rows: f.write(f"{k} {r} {s_}\n")
    print(f"baseline written: {base} ({len(rows)} modules)")
elif base != "none" and os.path.exists(base):
    for line in open(base, encoding="utf-8"):
        if not line.strip() or line.startswith("#"): continue
        k, r, s_ = line.split(); r, s_ = int(r), int(s_)
        if ran_mod.get(k, 0) < r: bad.append(f"baseline: module {k} ran {ran_mod.get(k, 0)} tests, baseline {r} (tests deleted?)")
        elif mode == "none":
            got = sum(1 for e in skips if mod(e["id"]) == k and not re.search("yaml", e["reason"], re.I))
            if got < s_: bad.append(f"baseline: module {k} has {got} bare-environment skips, baseline {s_} (guarded tests now pass silently?)")
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
[ "$UT_RC" -eq 0 ] || { echo "FAIL: unittest suite failed"; grep -E "^(FAIL|ERROR):" "$TMP/ut1.log" | head -30; FAIL=1; }
[ "$RAN" -ge "$MIN_TESTS" ] || { echo "FAIL: only $RAN tests ran (floor MIN_TESTS=$MIN_TESTS)"; FAIL=1; }
policy "$TMP/ut1.log" "$TMP/canon1.txt" || FAIL=1
if [ -f "$TMP/canon1.txt.counts" ]; then
  read -r _ NSK < "$TMP/canon1.txt.counts"
  [ "$NSK" = "$SKIPPED" ] || { echo "FAIL: recorded skips ($NSK) != reported skips ($SKIPPED)"; FAIL=1; }
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
  [ "$PT_RC" -eq 0 ] || { echo "FAIL: pytest failed"; FAIL=1; }
  [ "$((PT_PASSED + PT_SKIPPED + PT_FAILED))" -eq "$RAN" ] || { echo "FAIL: pytest collected $((PT_PASSED + PT_SKIPPED + PT_FAILED)) tests, unittest ran $RAN"; FAIL=1; }
  [ "$PT_SKIPPED" -eq "$SKIPPED" ] || { echo "FAIL: pytest skipped $PT_SKIPPED, unittest skipped $SKIPPED"; FAIL=1; }
else
  echo "== pytest == SKIPPED: pytest is not installed (optional; unittest results above are authoritative)"
fi

if [ "$TWICE" = 1 ]; then
  echo "== unittest, second run (determinism) =="
  clear_bytecode
  run_unittest "$TMP/ut2.log"; read -r RAN2 SKIPPED2 BAD2 < <(summarize "$TMP/ut2.log")
  policy "$TMP/ut2.log" "$TMP/canon2.txt" >/dev/null || true
  if [ "$RAN$SKIPPED$BAD" = "$RAN2$SKIPPED2$BAD2" ] && cmp -s "$TMP/canon1.txt" "$TMP/canon2.txt"; then
    echo "deterministic: run1 == run2 (ran=$RAN skipped=$SKIPPED failed=$BAD, identical per-module counts and skip list)"
  else
    echo "FAIL: non-deterministic: run1 ran=$RAN skipped=$SKIPPED failed=$BAD ; run2 ran=$RAN2 skipped=$SKIPPED2 failed=$BAD2"
    diff "$TMP/canon1.txt" "$TMP/canon2.txt" | head -20; FAIL=1
  fi
fi

# Leave the tree clean (no bytecode / caches).
clear_bytecode
if [ "$FAIL" -ne 0 ]; then echo "RESULT: FAIL"; exit 1; fi
echo "RESULT: OK (unittest ran=$RAN skipped=$SKIPPED)"
