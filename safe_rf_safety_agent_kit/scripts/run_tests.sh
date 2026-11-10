#!/usr/bin/env bash
# Deterministic, offline test runner for the TOY safety-audit kit (SR-15).
#
#   scripts/run_tests.sh [--expect none|torch|any] [--twice] [--no-network-guard]
#
#   --expect none   nothing third-party is installed: torch/numpy-dependent tests MUST report as skipped
#                   (with a reason mentioning "not installed"); a silent pass is a failure.
#   --expect torch  torch+numpy installed: no test may be skipped for "not installed"; only device-specific
#                   skips (CUDA / MPS / the "torch present" wiring test) are allowed.
#   --expect any    (default) only consistency checks; counts are printed.
#   --twice         run the unittest suite a second time and require identical run/skip/failure counts and an
#                   identical skip list (determinism check).
#
# WHY bytecode caching is disabled and __pycache__ is cleared first (STANDING RULE for this kit):
#   Three separate agents got contaminated mutation results from a stale .pyc (a source edit within the same
#   second as the cached compile reuses the old bytecode), and one spurious 10-failure spike was misattributed
#   to teammates because of it. Every run therefore starts from a tree with no bytecode and writes none.
#
# WHY PYTHONHASHSEED is fixed (default 0): str/bytes hashing is randomised per process, which changes set and
#   dict-of-set iteration order. Pinning it means a count difference between two runs is a real
#   non-determinism bug rather than hash-order noise. (The suite is also expected to pass under other seeds;
#   override with PYTHONHASHSEED=<n> to check.)
#
# NETWORK (the .env.example flags are inert markers read by no code; this guard is the real mechanism):
#   a sitecustomize guard makes socket connect / DNS lookups raise for the whole run (children
#   included), so any test that reached the network fails loudly. No credentials are read. The manual `curl`
#   commands in docs/DIFF_EVIDENCE.md are documentation for a human and are never executed here.
set -u -o pipefail

EXPECT=any
TWICE=0
GUARD=1
while [ $# -gt 0 ]; do
  case "$1" in
    --expect) EXPECT="${2:-}"; shift 2 ;;
    --twice) TWICE=1; shift ;;
    --no-network-guard) GUARD=0; shift ;;
    -h|--help) sed -n '2,29p' "$0"; exit 0 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done
case "$EXPECT" in none|torch|any) ;; *) echo "--expect must be none|torch|any" >&2; exit 2 ;; esac

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT" || exit 2

export PYTHONDONTWRITEBYTECODE=1
export PYTHONHASHSEED="${PYTHONHASHSEED:-0}"
export MIN_TESTS="${MIN_TESTS:-650}"   # floor: catches wholesale test deletion; raise as the suite grows

# Clear stale bytecode (outside .git / virtualenvs).
find . \( -name .git -o -name .venv -o -name venv -o -name node_modules \) -prune -o \
  \( -name __pycache__ -type d -print0 \) | xargs -0 rm -rf
find . \( -name .git -o -name .venv -o -name venv \) -prune -o -name '*.pyc' -type f -print0 | xargs -0 rm -f

TMP="$(mktemp -d "${TMPDIR:-/tmp}/saferf_tests.XXXXXX")"
trap 'rm -rf "$TMP"' EXIT

if [ "$GUARD" = 1 ]; then
  mkdir -p "$TMP/guard"
  cat > "$TMP/guard/sitecustomize.py" <<'PY'
import socket as _s
def _blocked(*a, **k):
    raise OSError("NETWORK BLOCKED by scripts/run_tests.sh: the offline suite must not touch the network")
_s.socket.connect = _blocked
_s.socket.connect_ex = _blocked
_s.create_connection = _blocked
_s.getaddrinfo = _blocked
_s.gethostbyname = _blocked
PY
  export PYTHONPATH="$TMP/guard${PYTHONPATH:+:$PYTHONPATH}"
  CANARY="$(python3 -c "import socket; socket.create_connection(('192.0.2.1', 9), timeout=1)" 2>&1 || true)"
  case "$CANARY" in *"NETWORK BLOCKED"*) ;; *)
    echo "FAIL: network guard canary did not trigger; refusing to run" >&2; exit 1 ;;
  esac
  echo "network guard: active (canary connect attempt was blocked)"
fi

echo "python: $(python3 --version 2>&1)  PYTHONHASHSEED=$PYTHONHASHSEED  expect=$EXPECT"
for m in torch numpy; do
  if python3 -c "import $m" 2>/dev/null; then echo "optional $m: present"; else echo "optional $m: absent"; fi
done

run_unittest() {  # $1 = log path
  python3 -m unittest discover -s tests -v >"$1" 2>&1
  return $?
}

summarize() {  # $1 = log; prints "RAN SKIPPED FAILS" parsed from the unittest log
  python3 - "$1" <<'PY'
import re, sys
t = open(sys.argv[1], encoding="utf-8", errors="replace").read()
ran = re.search(r"^Ran (\d+) tests?", t, re.M)
skipped = re.search(r"skipped=(\d+)", t.splitlines()[-1] if t.strip() else "")
bad = re.search(r"^FAILED \((.*)\)", t, re.M)
print(ran.group(1) if ran else "0", skipped.group(1) if skipped else "0", "1" if bad else "0")
PY
}

skip_list() {  # sorted, normalised "test :: reason" lines
  grep -E " \.\.\. skipped '" "$1" | sed -E "s/ \(.*\) \.\.\. skipped / :: /" | LC_ALL=C sort
}

FAIL=0
echo "== unittest discover =="
if run_unittest "$TMP/ut1.log"; then UT_RC=0; else UT_RC=$?; fi
tail -n 4 "$TMP/ut1.log"
read -r RAN SKIPPED BAD < <(summarize "$TMP/ut1.log")
echo "unittest: ran=$RAN skipped=$SKIPPED failed=$BAD rc=$UT_RC"
[ "$UT_RC" -eq 0 ] || { echo "FAIL: unittest suite failed"; grep -E "^(FAIL|ERROR):" "$TMP/ut1.log" | head -30; FAIL=1; }
[ "$RAN" -ge "$MIN_TESTS" ] || { echo "FAIL: only $RAN tests ran (floor MIN_TESTS=$MIN_TESTS)"; FAIL=1; }
skip_list "$TMP/ut1.log" > "$TMP/skips1.txt"
[ "$(wc -l < "$TMP/skips1.txt" | tr -d ' ')" = "$SKIPPED" ] || { echo "FAIL: skip list ($(wc -l < "$TMP/skips1.txt")) != reported skips ($SKIPPED); a skip lacks a reason"; FAIL=1; }

if python3 -c "import pytest" 2>/dev/null; then
  echo "== pytest =="
  # -p no:cacheprovider: do not create .pytest_cache in the repo.
  if python3 -m pytest -q -p no:cacheprovider tests >"$TMP/pt.log" 2>&1; then PT_RC=0; else PT_RC=$?; fi
  tail -n 2 "$TMP/pt.log"
  PT_PASSED=$(grep -Eo '[0-9]+ passed' "$TMP/pt.log" | tail -1 | cut -d' ' -f1); PT_PASSED=${PT_PASSED:-0}
  PT_SKIPPED=$(grep -Eo '[0-9]+ skipped' "$TMP/pt.log" | tail -1 | cut -d' ' -f1); PT_SKIPPED=${PT_SKIPPED:-0}
  echo "pytest: passed=$PT_PASSED skipped=$PT_SKIPPED rc=$PT_RC"
  [ "$PT_RC" -eq 0 ] || { echo "FAIL: pytest failed"; FAIL=1; }
  [ "$((PT_PASSED + PT_SKIPPED))" -eq "$RAN" ] || { echo "FAIL: pytest collected $((PT_PASSED + PT_SKIPPED)) tests, unittest ran $RAN"; FAIL=1; }
  [ "$PT_SKIPPED" -eq "$SKIPPED" ] || { echo "FAIL: pytest skipped $PT_SKIPPED, unittest skipped $SKIPPED"; FAIL=1; }
else
  echo "== pytest == SKIPPED: pytest is not installed (optional; unittest results above are authoritative)"
fi

# Skip-reason policy. Reasons are the only defence against a torch test passing (or vanishing) silently.
EXPECT="$EXPECT" SKIPFILE="$TMP/skips1.txt" python3 - <<'PY' || FAIL=1
import os, sys
mode = os.environ["EXPECT"]
lines = [l for l in open(os.environ["SKIPFILE"], encoding="utf-8").read().splitlines() if l]
n = len(lines)
ni = [l for l in lines if "not installed" in l]
print(f"skip policy ({mode}): {n} skipped, {len(ni)} for 'not installed'")
bad = []
if mode == "none":
    if n < 50: bad.append(f"expected many torch/numpy skips (>=50) with nothing installed, got {n}: a torch test may be passing silently or was removed")
    if not any("torch not installed" in l for l in lines): bad.append("no skip mentions 'torch not installed'")
    if not any("numpy not installed" in l for l in lines): bad.append("no skip mentions 'numpy not installed'")
    if any("torch present" in l for l in lines): bad.append("a skip says torch is present although none is expected")
elif mode == "torch":
    if ni: bad.append("tests were skipped for 'not installed' although torch+numpy should be installed: " + "; ".join(ni[:3]))
    if n > 12: bad.append(f"{n} skips with torch present; only CUDA/MPS/wiring skips (~2-6) are expected")
for l in lines:
    if not (l.split(" :: ", 1) + [""])[1].strip("' "):
        bad.append("empty skip reason: " + l)
for b in bad: print("FAIL:", b)
sys.exit(1 if bad else 0)
PY

if [ "$TWICE" = 1 ]; then
  echo "== unittest, second run (determinism) =="
  find . \( -name .git -o -name .venv \) -prune -o \( -name __pycache__ -type d -print0 \) | xargs -0 rm -rf
  run_unittest "$TMP/ut2.log"; read -r RAN2 SKIPPED2 BAD2 < <(summarize "$TMP/ut2.log")
  skip_list "$TMP/ut2.log" > "$TMP/skips2.txt"
  if [ "$RAN$SKIPPED$BAD" = "$RAN2$SKIPPED2$BAD2" ] && cmp -s "$TMP/skips1.txt" "$TMP/skips2.txt"; then
    echo "deterministic: run1 == run2 (ran=$RAN skipped=$SKIPPED failed=$BAD, identical skip list)"
  else
    echo "FAIL: non-deterministic: run1 ran=$RAN skipped=$SKIPPED failed=$BAD ; run2 ran=$RAN2 skipped=$SKIPPED2 failed=$BAD2"
    diff "$TMP/skips1.txt" "$TMP/skips2.txt" | head -20; FAIL=1
  fi
fi

# Leave the tree clean (no bytecode / caches).
find . \( -name .git -o -name .venv \) -prune -o \( -name __pycache__ -type d -print0 \) | xargs -0 rm -rf
if [ "$FAIL" -ne 0 ]; then echo "RESULT: FAIL"; exit 1; fi
echo "RESULT: OK (unittest ran=$RAN skipped=$SKIPPED)"
