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
#   --expect any    (default) only consistency checks; counts are printed. NO skip-REASON check runs in this mode:
#                   every reason rule sits inside `if mode == "none"` / `elif mode == "torch"` with no else, so a
#                   reason either of those would reject is accepted here, and the per-module BASELINE SKIP column
#                   is not compared either (that comparison is inside `elif mode == "none"`). What does apply in
#                   every mode: every environment-category check built from EXEMPT_CATEGORIES (FS_CAP,
#                   TOOL_CAP, TOOL_UNDECLARED, EXEMPT_AMBIGUOUS, INTERNAL), EMPTY_REASON, RECORDER, the
#                   per-module TEST-count baseline, and every shell-side check.
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
# SKIP POLICY (case-insensitive; reason checks are the FIRST defence against a torch test passing silently --
# the per-module baseline's skip column is the other, and it is the one that catches a RE-PARKED skip):
#   none:  EVERY skip reason must name torch/numpy/pyyaml/pytest and say "not installed", "missing",
#          "unavailable" or "not available"; at least MIN_NONE_SKIPS (default 50) skips; at least one torch and
#          one numpy reason; no reason may say "torch present".
#   torch: EVERY skip reason must name cuda, mps or "torch present", and must not say "not installed",
#          "missing" or mention numpy; at most 12 skips.
#   ENVIRONMENT-EXEMPTION CATEGORIES are declared in ONE tuple, `EXEMPT_CATEGORIES` in the policy below, and
#   every guard, cap and exclusion is applied by the loop that reads it. There are two:
#     FS    "case-sensitive filesystem ..."  (Linux, case-sensitive APFS)                        cap 8
#     TOOL  "optional developer tool `<name>` is not on PATH", `<name>` on the `TOOLS` allowlist  cap 4
#   Both are allowed in EVERY mode and are excluded from the package-skip floor, the torch cap and the per-module
#   baseline -- in baseline GENERATION as well as comparison, so a recorded skip column cannot differ between a
#   machine that has the thing and one that does not. FS was the first observed failure of this script on a
#   case-sensitive filesystem; TOOL exists for a test whose BEHAVIOURAL half needs a linter that nothing in this
#   kit installs (ruff). Naming no package is correct for both, because no package is missing. See
#   docs/CLEAN_CLONE.md.
#   WHY A TUPLE RATHER THAN TWO HAND-GUARDED SITES: round 5 gave TOOL an anchored phrase, a trailing `\b` and a
#   closed allowlist, and FS -- the same KIND of exemption -- got none of the three; `case-sensitive filesystem:
#   variants differ; libtorch is gone` was then EXEMPT in all three modes. The guards now come from the
#   declaration: anchored phrase (`\A` + `.match`), trailing `\b`, the package rule, a closed allowlist wherever
#   the phrase carries a name, every OCCURRENCE of a phrase checked and not only the anchored one, ONE claim per
#   reason, and a per-category cap. A row declared badly is POLICY:INTERNAL; a category claimed badly is
#   POLICY:<TOKEN>_UNDECLARED or POLICY:EXEMPT_AMBIGUOUS -- loud in EVERY mode, never a silent exemption.
#   EVERY RUN PRINTS THE REGISTRY IT JUDGED WITH, one `exemption registry row:` JSON line per row, rendered
#   from the value the policy really reads. tests/toy_tests/test_scripts.py requires that listing to EQUAL the
#   `EXEMPT_CATEGORIES` literal it parses out of this file, so a row that arrives by any other route -- a
#   rebind, `globals()[...]`, `setattr` -- is a red suite rather than a working category with no token. The
#   static "assigned exactly once" check cannot see those routes, and it used to claim the runtime half covered
#   them: it does not, because the runtime half rejects a MALFORMED row and such a row can be well formed.
#   THE RULES THAT BOUND THEM, and no one of them is a bound by itself:
#     (1) A REASON THAT NAMES ANY PACKAGE THIS KIT MEASURES GETS NO EXEMPTION -- OUTSIDE THE DECLARED NAME THE
#         PHRASE ITSELF CARRIES, which is (1a) below -- as a WORD (`PKG`: torch, pyyaml)
#         or ANYWHERE INSIDE a longer name (`PKG_EXEMPT`, a containment test: torchrun, numpy2, libtorch,
#         _torch) -- it is judged as a package skip in the mode that is running (`--expect any` applies no
#         reason check at all, so there it is judged by nothing; see the note on that mode above). The package
#         list is the `PKGS` tuple below and every rule built on it derives from it, because the previous
#         version of this rule was a list of missing-phrase SPELLINGS kept by hand in three places, and the
#         three disagreed: measured, before the rule existed, `optional developer tool `torch` is not on PATH`
#         passed `--expect torch` and spent one of the 50 skips `--expect none` requires; so did
#         `case-sensitive filesystem; torch unavailable`.
#     (1a) THE ONE EXCEPTION TO (1), and it closes round 7's F3, a LEGITIMATE DENY: the containment test was
#         applied to the WHOLE reason, AFTER the allowlist, and returned unconditionally -- so a declared name
#         that merely CONTAINS a package name could never be exempted and DECLARING IT CHANGED NOTHING. Measured
#         with `TOOLS = ("ruff", "yamllint", "shellcheck")` and nothing else changed, reason ``optional developer
#         tool `yamllint` is not on PATH`` (`yamllint` contains `yaml`): `--expect none` -> POLICY:NONE_REASON,
#         RESULT: FAIL -- the IDENTICAL red before and after declaring it, in the mode BOTH CI jobs run;
#         `--expect torch` -> POLICY:TORCH_MODE_UNEXPLAINED; `--expect any` -> OK but NOT exempt; control in the
#         same run, declared `shellcheck` -> exempt, note printed. The failure message says "declare the tool
#         there, with a test", which was advice that could not be followed: round 3's defect shape, latent only
#         because the one gated tool happens to be `ruff`. Plausible real names: `yamllint`/`yamlfmt` (for
#         ci.yml), `numpydoc`, `pytest-cov`, `torchfix`.
#         SO: the SPAN of a name the category's OWN CLOSED ALLOWLIST carries is blanked out of the reason before
#         the containment test runs; every other character of the reason is still tested, so every prose tail in
#         the laundering table is denied exactly as before. The open-set argument that motivated containment
#         does not apply to a closed set. The rail that keeps the exception narrow is a DECLARATION-TIME one: an
#         allowlist entry that IS a measured package spelling (`PKG.fullmatch`: torch, numpy, yaml, pyyaml,
#         pytest) is POLICY:INTERNAL, so round 4's actual defect (``optional developer tool `torch` is not on
#         PATH``) cannot be declared into existence. THE COST, as a measurement and not a hope: a DECLARED
#         `torchfix` would be exempt, bounded by the cap (4), by the baseline, and by the test-time equality
#         that requires a real skip site in tests/toy_tests/ for every name on the allowlist.
#     (2) A name the phrase carries must be DECLARED, on that category's own allowlist.
#   WHAT IS NOT TRUE, and was asserted here for a round: that rule (1) alone makes an exemption "sound ... only
#   while it cannot be spent on hiding a package skip". It cannot, on its own: it is a spelling test, so EVERY
#   reason that names no package collects the exemption, and before rule (2) existed that included `torchrun`
#   (PyTorch's own console script), `libtorch` (its C++ distribution), `torchvision`, `torchaudio`,
#   `torch_geometric`, `torch2`, `_torch`, `numpy2`, `pytestx`, `mypy`, `black` and `yamllint` -- all measured
#   EXEMPT in `--expect none` AND `--expect torch` on the live script. THE REAL BOUND IS THE CAPS AND THE
#   BASELINE, not the naming rule: at most TOOL_CAP (4, one in use) + FS_CAP (8) skips can be exempt at all, and
#   re-parking an EXISTING package skip into either category lowers that module's recorded bare-skip column and
#   fails POLICY:BASELINE_SKIPS. What an exemption buys is therefore bounded by those numbers; the naming rules
#   only keep an honest reason from being read as a dishonest one.
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
# (the directory check needs the RESOLVED path and so lives just after the resolution block below)

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
# A DIRECTORY is not a baseline, and both branches mishandled one. `--update-baseline` ended in
# `mv "$TMP/base.staged" "$BASELINE"`, which for a directory destination SUCCEEDS by dropping a file named
# `base.staged` INSIDE it -- so `--baseline scripts --update-baseline` printed `RESULT: OK` and left an untracked,
# un-gitignored `scripts/base.staged` in the repository, the D1 shape again (the only hint was an empty
# `( modules)`, because the count came from `$(grep -cv '^#' "$BASELINE" || true)` and the `|| true` swallowed
# grep's "Is a directory"). The comparison branch was no better: `os.path.exists(base)` is true for a directory,
# so `open(base)` raised IsADirectoryError and the run died with a traceback and no POLICY token at all.
# Checked HERE, before the suite runs, so neither branch is reached and the user is not made to wait for it.
# The write-time POLICY:BASELINE_WRITE guard further down is still needed: a directory can appear at that path
# DURING the run, which this check cannot see.
if [ "$BASELINE" != none ] && [ -d "$BASELINE" ]; then
  echo "--baseline must be a FILE: $BASELINE is a directory" >&2
  echo "With --update-baseline the staged file would be moved INSIDE it as base.staged (an untracked file in your" >&2
  echo "tree, reported as RESULT: OK); without it, the per-module comparison cannot read it. Pass a file path." >&2
  exit 2
fi
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
# docs/CLEAN_CLONE.md points at these tuples instead of restating the PATCHED lists, so the count there cannot go
# stale (it said "five patched" against seven). It DOES spell out the _NOT_BLOCKED names, deliberately -- a reader
# needs the known-bypass list -- and that copy is kept in step by
# test_the_documentation_names_every_disclosed_unpatched_entry_point rather than by not existing.
_BLOCK_MODULE = ("create_connection", "create_server", "getaddrinfo", "getfqdn", "gethostbyaddr",
                 "gethostbyname", "gethostbyname_ex", "getnameinfo")
_BLOCK_SOCKET = ("connect", "connect_ex", "bind", "listen", "sendto", "sendmsg")
# KNOWN-UNPATCHED and therefore DISCLOSED, each with the reason it is left alone:
#   gethostname, getservbyname, getservbyport, getprotobyname -- purely local lookups (the host's own name,
#     /etc/services, /etc/protocols); they originate no traffic. gethostbyname/getfqdn, which DO resolve, are
#     patched, so gethostbyname(gethostname()) is still blocked.
#   send, sendall, sendfile, accept -- reachable only through a connect/bind/listen that IS patched.
#   sendmsg_afalg -- LINUX ONLY (typeshed declares it under `if sys.platform == "linux"`, and it is absent from
#     socket.socket on macOS, so it is invisible to the family enumeration on this host and appears on Linux).
#     It is not an egress path: it is valid only on a socket in the AF_ALG family, the kernel CRYPTO API socket
#     family, whose addresses are algorithm names (e.g. ("hash", "sha256")) rather than host/port pairs. An AF_ALG
#     socket has no network peer, no route and no interface -- its only correspondent is the local kernel -- and
#     sendmsg_afalg's extra arguments (op, iv, assoclen, flags) are cipher parameters, not addressing. Calling it
#     on an AF_INET socket raises; the AF_INET path is socket.sendmsg, which IS patched. DISCLOSED rather than
#     patched because patching it would mean setattr-ing a name that does not exist on macOS, which would put a
#     member in _BLOCK_SOCKET that is outside the live family on this platform; and the enumeration is
#     deliberately NOT made platform-aware, because enumerating from the live module is the whole mechanism that
#     stopped this guard from being patched one reviewer-tested name at a time.
# This is still a Python-level tripwire, not a sandbox: see the NETWORK note in the header.
_NOT_BLOCKED = ("gethostname", "getservbyname", "getservbyport", "getprotobyname",
                "send", "sendall", "sendfile", "accept", "sendmsg_afalg")
for _n in _BLOCK_MODULE:
    setattr(_s, _n, _blocked)
for _n in _BLOCK_SOCKET:
    setattr(_s.socket, _n, _blocked)
PY
fi
export PYTHONPATH="$TMP/guard${PYTHONPATH:+:$PYTHONPATH}"
if [ "$GUARD" = 1 ]; then
  # 127.0.0.1:1 is a CLOSED LOOPBACK PORT: if the guard is missing this fails instantly with "connection
  # refused" from this host's own stack, over the loopback device.
  # THE RETRACTION, kept where the claim was made (round 8's F3): this comment used to end that sentence "and
  # nothing leaves the host", which is the phrase README.md retracted, and for the same reason -- aiming at
  # loopback is a property of the ADDRESS THIS SCRIPT ASKS FOR, which is tested, and not of the host's egress,
  # which has never been observed. Hermeticity is UNATTESTED; docs/CLEAN_CLONE.md's Known-limits bullet defines
  # the network-denied measurement that would attest it, and that measurement has not been run.
  # The TARGET used to be 192.0.2.1:9, which is unroutable only by convention -- the kernel still sent the SYN,
  # on every run where the guard was absent.
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
# ------------------------------------------------------------------------------------------------------------
# ENVIRONMENT-EXEMPTION CATEGORIES. ONE DECLARATION (`EXEMPT_CATEGORIES`, below); EVERY GUARD APPLIES TO EVERY
# ENTRY, BY THE LOOP THAT READS IT RATHER THAN BY HAND AT EACH SITE.
#
# WHY A REGISTRY, i.e. THE SIXTH SR-15 FAIL. Round 5 closed the optional-developer-tool category with three
# independent guards -- `\A` in the phrase, `.match` at the call site, a trailing `\b` -- PLUS a closed
# allowlist of names. The filesystem-case category is the same KIND of exemption and got NONE of the four: it
# was `re.compile(r"case[- ]sensitive", re.I)` used UNANCHORED via `.search`. Measured on the live script, all
# EXEMPT (RESULT: OK) in `--expect none` AND `--expect torch` AND `--expect any`:
#     case-sensitive filesystem: variants differ; libtorch is gone                 (also `_torch`, `mytorch`)
#     case-sensitive filesystem: ...; optional developer tool `black` is not on PATH
#     the optional developer tool `mypy` is not on PATH (case-sensitive filesystem)
#     case-sensitive: this test is disabled for now
# -- while the same laundering worded through the TOOL phrase was rejected in every mode. A guard installed at
# the sites someone thought of is a guard the next category does not get.
# WHAT THIS COMMENT USED TO ADD, and it was false: "or hide a torch test". An exempt reason CAN hide one -- that
# is what an exemption is -- and the bound is the category's CAP plus the per-module baseline, which catches a
# RE-PARKED existing skip because the module's recorded bare-skip column drops. Not the exclusion, and not the
# naming rule.
#
# THE GUARDS, applied to every declared category by the loop below:
#   (1) ANCHORED: `\A` in the pattern and `.match` at the ONE call site, and a POLICY:INTERNAL check that every
#       declared pattern carries `\A`. The two anchor terms are MUTUALLY REDUNDANT (`\A` can match only at
#       position 0, so `.search` on an `\A` pattern IS `.match`, and `.match` on a pattern without `\A` is
#       anchored by the method), so a mutant dropping ONE of them is an EQUIVALENT mutant and surviving proves
#       nothing; the mutant worth running drops BOTH, and it is killed by the prose-carrying cases
#       (`the suite reports: <phrase>`) that the per-category laundering table drives for EVERY category.
#   (2) \b-TERMINATED: the pattern must end on `\b`, also POLICY:INTERNAL -- it is what rejects
#       `...is not on PATHological systems`.
#   (3) THE PACKAGE RULE (`PKG_EXEMPT`, shared): a reason that CONTAINS a measured package name gets no
#       exemption at all -- OUTSIDE the span of a name the category's own closed allowlist carries, which
#       `claim()` blanks before applying the pattern. That exception is round 7's F3; it is stated in full at
#       (1a) in the header, with the measurement and the POLICY:INTERNAL rail that bounds it.
#   (4) A CLOSED ALLOWLIST where the phrase carries a NAME, and none where it does not: the mismatch is
#       POLICY:INTERNAL, so a new category cannot ship with the OPEN SET the tool category had in round 4.
#   (5) EVERY OCCURRENCE of a declared phrase in the reason, not only the anchored one, is checked against that
#       category's allowlist (`...; also optional developer tool `black` is not on PATH`).
#   (6) ONE CLAIM PER REASON: carrying a second category's phrase is POLICY:EXEMPT_AMBIGUOUS. This is what
#       makes a per-category cap a bound at all. Measured before it, in `--expect any` with 5 identical skips:
#       the live ruff reason x5 is POLICY:TOOL_CAP (x4 is OK, the documented 4/5 boundary), and the same reason
#       + ` (case-sensitive filesystem)` x5 was OK and reported as "5 skip(s) for a case-sensitive filesystem",
#       i.e. tool parks were counted AND PRINTED as the Linux figure docs/CLEAN_CLONE.md tells readers to
#       expect, up to FS_CAP.
#   (7) A CAP of its own (POLICY:<TOKEN>_CAP) and exclusion from the bare-mode skip floor, the torch cap and the
#       per-module baseline -- in GENERATION as well as comparison, so a recorded skip column cannot differ
#       between a machine that has the thing and one that does not.
# tests/toy_tests/test_scripts.py PARSES `EXEMPT_CATEGORIES` and derives from it: the structural requirements
# above, a laundering table driven per category in all three modes, the cap boundary, the cross-category case,
# the equality between a category's allowlist and the skip sites in tests/toy_tests/ that claim it, and the
# POLICY tokens a category must have tests for. A category is therefore covered the moment it is declared, and
# a category declared badly is a RED SUITE -- which is the one thing two hand-guarded sites could not give.
#
# WHAT NONE OF THE SEVEN DOES. None of them tells a true claim from a false one: a DECLARED phrase with a prose
# tail that names no measured package (``optional developer tool `ruff` is not on PATH; mypy is gone``) is still
# exempt, and no regex can change that. What an exemption BUYS is bounded by the caps and the baseline --
# measured: re-parking an EXISTING baseline-counted skip is POLICY:BASELINE_SKIPS, and ADDING laundered
# filesystem-case skips is OK up to 8 and POLICY:FS_CAP at 9, so the reach was <= 8 newly parked tests, <= 4 on
# a Linux runner where the real case-sensitivity skips occupy the bucket.
# THE packages this kit measures -- ONE tuple, from which FOUR things are built and no longer merely described as
# built: NONE_OK (bare-mode reason check), PKG (the exemption's name test), PKG_EXEMPT (its prefix test) and
# PYYAML (the baseline exclusion, which was an independently typed `\b(?:py)?yaml\b` while this comment already
# claimed it came from here). They used to be three hand-written lists of spellings in three places and they
# disagreed: see PKG below and the SKIP POLICY note in the header. tests/toy_tests/test_scripts.py parses this
# tuple and derives its laundering cases from it.
PKGS = ("torch", "numpy", "yaml", "pytest")
PKG = re.compile(r"\b(?:py)?(?:" + "|".join(PKGS) + r")\b", re.I)
# ...and the same tuple as a CONTAINMENT test, used ONLY to deny an environment exemption. `PKG` ends on a
# word boundary and the word boundary is EVADABLE IN BOTH DIRECTIONS. A PREFIX test closed one direction only,
# and that was the shape of this round's defect: `torchrun` (PyTorch's own console script), `numpy2` and
# `pytestx` were denied, while `libtorch` (its C++ distribution), `_torch` and `mytorch` have no `\b` before
# `torch` and so were EXEMPT as a tail on either category (measured, in `--expect none`, `--expect torch` and
# `--expect any`). There is no boundary left to evade: a reason CONTAINING a measured package name, in any case,
# with any affix, gets no exemption -- OUTSIDE the span of a DECLARED name, which `claim()` blanks before
# applying this pattern (round 7's F3; see (1a) in the header). That clause is new: the sentence above used to
# end at "gets no exemption", with no exception at all, and it was TRUE of the code and FALSE as a policy,
# because it made the `TOOLS` allowlist INERT for every name containing a package substring -- `yamllint`
# contains `yaml`, and declaring it changed no verdict in any mode. The two patterns are deliberately NOT merged:
#   * NONE_OK (what counts as an honest "a package is missing" reason in bare mode) must stay the WORD test.
#     With this one, `optional developer tool `torchrun` is not on PATH; it is missing` would be ACCEPTED as an
#     honest package skip and would count toward the 50 -- the wrong direction.
#   * the baseline's PyYAML exclusion must stay the WORD test too, or a reason merely mentioning `yamllint`
#     would drop out of a module's recorded bare-skip column, which is the floor that catches re-parked skips.
# Denying an exemption is the safe direction for a loose match: the reason is then judged by the mode it runs in
# and counted in the baseline, never silently excused. The cost of the loose direction, measured: a legitimate
# environment reason that happens to contain those letters (``case-sensitive filesystem; see
# test_pytest_roundtrip``) loses its exemption and goes red in `--expect none` -- loudly, and with the reason
# printed, which is the trade this direction is chosen for.
PKG_EXEMPT = re.compile("|".join(PKGS), re.I)
# GUARD (3), THE PACKAGE RULE (the others are listed above; no one of them is sufficient alone, and the real
# bound on what an exemption buys is the caps plus the baseline -- see the header):
# a reason that CONTAINS a measured package name, outside the span of a name its own allowlist declares, gets no
# exemption. Stated as what it measures, because the
# sentence that stood here -- "whatever else it says and HOWEVER IT SPELLS IT" -- was FALSE while this was a
# prefix test: `libtorch is gone` and `_torch is gone` were exempt tails on both categories, measured in all
# three modes, and `libtorch` is PyTorch's own C++ distribution. It is now a CONTAINMENT test over the `PKGS`
# tuple, case-insensitive: any affix on either side is caught (`libtorch`, `_torch`, `mytorch`, `torchrun`,
# `torch2`, `numpy2`, `pytestx`, `yamllint`). It is a SUBSTRING RULE AND NOTHING MORE, and two residues are
# measured rather than argued: a name spelled with a character the name does not contain (`t0rch`) is NOT
# caught, and neither is a reason that describes a package without naming it ("the deep-learning framework is
# gone"). Both stay exempt, bounded by the caps and the baseline like every other honest-looking reason.
# It is a NAME test rather than a phrase test on purpose. The previous
# rule tried to catch the laundering by its wording -- torch mode denied "not installed|missing|numpy" on every
# skip, tool skips included -- and `unavailable`, which `--expect none` itself accepts as a package-missing
# phrase, was not among the three; so `optional developer tool `torch` is not on PATH` (no phrase at all) and
# ``optional developer tool `ruff` is not on PATH` (torch unavailable)`` both passed `--expect torch`, and
# `case-sensitive filesystem; torch unavailable` passed it too. A category that admits "a test cannot run here"
# has no business naming a package whose absence is the thing being measured, so it may not.
# THE TOOLS THE TOOL CATEGORY EXISTS FOR -- a CLOSED ALLOWLIST of names, which is the ROUND-5 fix. `PKG` above
# is a word-boundary test for four package SPELLINGS, and as the only gate on the tool category it was an OPEN
# set: every name that is not one of those four words collected the exemption in `--expect none` AND
# `--expect torch`. Measured on the live script before this tuple existed, all EXEMPT in both modes:
#   torchrun (PyTorch's own console script), libtorch (its C++ distribution), torchvision, torchaudio,
#   torch_geometric, torch2, _torch, numpy2, pytestx, mypy, black, yamllint
# -- and round 4's actual defect was ``optional developer tool `torch` is not on PATH``, one suffix away from the
# first two. A negative rule ("does it look like a package?") cannot close that; a positive one can, because the
# tools this suite really gates a test on are a CLOSED set of size 1.
# DERIVED, not hand-maintained: tests/toy_tests/test_scripts.py parses this tuple out of this file AND parses
# every tool-gated skip site out of tests/toy_tests/*.py (the `@unittest.skipUnless(...)` / `skipTest(...)`
# reasons that claim the TOOL category below) and requires the two sets to be EQUAL. So a NEW tool-gated test is
# a RED SUITE with a message naming the tool and this tuple, never a silent exemption -- and so is a name left
# here after the test that needed it is gone. A reason shaped like the category whose name is not here is
# POLICY:TOOL_UNDECLARED in EVERY mode, including `--expect any`, where no reason check runs at all.
# THE SAME IS NOW TRUE OF THE FILESYSTEM-CASE CATEGORY, which had no such derivation: its phrase is a declared,
# anchored phrase, and the same test requires every skip site in tests/toy_tests/ whose reason carries that
# phrase to CLAIM the category properly. The site that made this necessary was real --
# tests/toy_tests/test_scripts.py skipped with "filesystem is case-sensitive; ..." (the phrase mid-sentence), so
# the category's own scan could not see it and an anchored phrase would have left it judged as a package skip on
# every Linux runner.
TOOLS = ("ruff",)
# ONE ROW PER CATEGORY. Adding a row is all it takes to get every guard, every exclusion and (via the tests that
# parse this tuple) every driven case; getting a row wrong is POLICY:INTERNAL rather than a quiet hole.
#   token      the stable POLICY-token prefix (<token>_CAP, <token>_UNDECLARED); UPPERCASE, non-blank and UNIQUE
#   phrase     the reason's phrase: MUST start with \A and end with \b; at most ONE capture group, which is the
#              name the reason carries and which must then be on the allowlist. A capture group must be
#              MANDATORY -- top-level, unquantified, no alternation anywhere in the phrase -- because the
#              allowlist check reads group(1) and an OPTIONAL group makes that None (round 7's N2: AttributeError
#              before `bad` was printed, RESULT: FAIL with NO POLICY token).
#   cap        at most this many skips may claim the category in one run; a positive int
#   declared   where the allowlist lives in this file, for the failure message; "" when the phrase names nothing
#   allowlist  the closed set of names the phrase may carry; () when it carries none. No entry may BE a package
#              the kit measures (`PKG.fullmatch`), which is the rail on (1a) in the header.
#   note       how the run reports the category, printed and used in its failure messages; UNIQUE, because it is
#              the ONLY thing a reader of the output sees -- round 7's F2 variant m7b declared a category whose
#              note was the filesystem-case note verbatim and printed its parked skips as "4 skip(s) for a
#              case-sensitive filesystem (expected on Linux)", the figure docs/CLEAN_CLONE.md tells readers to
#              expect on Linux.
# A ROW THAT IS WRONG IS POLICY:INTERNAL **AND THE RUN STOPS THERE**, before a single skip is judged: the loop
# below prints `bad` and exits if any INTERNAL is in it. That is round 7's N1/N2 -- a non-int cap and an optional
# capture group each computed POLICY:INTERNAL into `bad` and then died (TypeError at `len(_got) > _cap`,
# AttributeError at `m.group(1).lower()`) BEFORE `bad` was printed, so the run was RESULT: FAIL, rc=1, with NO
# POLICY token at all. A registry that fails its own contract cannot be used to judge skips, so it is not.
EXEMPT_CATEGORIES = (
    ("FS", r"\Acase[- ]sensitive filesystem\b", 8, "", (),
     "for a case-sensitive filesystem (expected on Linux)"),
    ("TOOL", r"\Aoptional developer tool `([\w.+-]+)` is not on PATH\b", 4, "TOOLS", TOOLS,
     "for an absent optional developer tool"),
)
def mandatory_group(pat):
    """True when every match of `pat` MUST have entered its one capturing group, so group(1) is never None.

    ROUND 7's N2: a phrase with an OPTIONAL capture group (`\\Aonly on( `[\\w]+`)? zed\\b`) passed all seven
    declaration guards and then died at `m.group(1).lower()` with AttributeError -- RESULT: FAIL, rc=1, NO POLICY
    token. The condition asserted here is deliberately syntactic and narrow: the capturing group must sit at the
    TOP LEVEL of the pattern, carry no `?`/`*`/`{` quantifier, and the pattern must hold no alternation. Under
    those three, a successful match always enters the group. A phrase that needs more than that is refused not
    because it is wrong but because this check cannot prove it right, which is the fail-closed direction for a
    declaration -- and the runtime treats a None group as an UNDECLARED name rather than as a crash anyway.
    """
    i, n, depth, opened, closed = 0, len(pat), 0, -1, -1
    while i < n:
        ch = pat[i]
        if ch == "\\":
            i += 2
            continue
        if ch == "[":                                  # a character class: `|` and `(` inside it are literals
            i += 1
            if i < n and pat[i] == "^": i += 1
            if i < n and pat[i] == "]": i += 1
            while i < n and pat[i] != "]":
                i += 2 if pat[i] == "\\" else 1
            i += 1
            continue
        if ch == "|":
            return False                               # a branch that skips the group may match
        if ch == "(":
            if pat[i + 1:i + 2] != "?":                # a CAPTURING group
                if depth or opened != -1:
                    return False                       # nested in another group, or a second capturing group
                opened = i
            depth += 1
        elif ch == ")":
            depth -= 1
            if opened != -1 and closed == -1 and depth == 0:
                closed = i
        i += 1
    if opened == -1 or closed == -1:
        return False
    return pat[closed + 1:closed + 2] not in ("?", "*", "{")
def fold_note(s):
    """A note as a reader sees it: lowercase words, punctuation and case discarded. Used ONLY to decide whether
    two declared notes are distinguishable -- see the near-duplicate test in the declaration loop below."""
    return " ".join(re.sub(r"[^0-9a-z]+", " ", str(s).lower()).split())
CATS = []
for _tok, _pat, _cap, _where, _allow, _note in EXEMPT_CATEGORIES:
    _why = []
    if not isinstance(_tok, str) or re.fullmatch(r"[A-Z][A-Z0-9_]*", _tok) is None:
        _why.append(f"its token {_tok!r} is not a non-blank UPPERCASE identifier, and POLICY:<TOKEN>_CAP and "
                    "POLICY:<TOKEN>_UNDECLARED are built from it")
    elif _tok in {c[0] for c in CATS}:
        _why.append(f"its token {_tok!r} is already declared by an earlier row, so two categories share one cap "
                    "token and one failure message")
    # NEAR-DUPLICATE, not merely duplicate -- ROUND 8's F1, second half. This test was EXACT-STRING equality,
    # so round 7's m7b variant worded ONE WORD longer was ACCEPTED: note "for a case-sensitive filesystem
    # (expected on Linux runners)" against the real "(expected on Linux)" printed its parked skips as
    # "4 skip(s) for a case-sensitive filesystem (expected on Linux runners)" -- the figure docs/CLEAN_CLONE.md
    # tells a LINUX reader to expect, under a token nobody declared. The note is the ONLY thing a reader of the
    # output sees, so "distinct" has to mean distinct TO A READER, and these three are what that can be made to
    # mean mechanically: after folding to lowercase words, no note may EQUAL another, CONTAIN another (which is
    # exactly what the one-word tail did, in both directions), or OPEN ON THE SAME FOUR WORDS. Measured on the
    # live declaration: the two real notes fold to "for a case sensitive filesystem expected on linux" and "for
    # an absent optional developer tool", which share one opening word, so none of the three fires.
    # RESIDUE, measured rather than argued: a genuine paraphrase that contains nothing and shares no opening
    # ("because this filesystem distinguishes case") is still accepted. What bounds it is that a row can now
    # only reach the judging through the literal -- the listing printed below is compared, row for row, against
    # the parsed `EXEMPT_CATEGORIES` literal by tests/toy_tests/test_scripts.py.
    _nf = fold_note(_note)
    for _prev in [c[6] for c in CATS]:
        _pf = fold_note(_prev)
        if _nf == _pf:
            _how = "is already declared by an earlier row"
        elif _nf and _pf and (_nf in _pf or _pf in _nf):
            _how = "differs from an earlier row's note only by a longer tail"
        elif len(_nf.split()) >= 4 and _nf.split()[:4] == _pf.split()[:4]:
            _how = "opens on the same four words as an earlier row's note"
        else:
            _how = None
        if _how:
            _why.append(f"its note {_note!r} {_how} ({_prev!r}): the note is the ONLY thing a reader of the "
                        "output sees, and a note a reader cannot tell from another prints one category's "
                        "parked skips under another category's name")
    if not str(_note).strip():
        _why.append("its note is blank, so the run would report its skips as nothing at all")
    if not _pat.startswith("\\A"):
        _why.append("its phrase is not ANCHORED (no leading \\A), so prose can carry the claim")
    if not _pat.endswith("\\b"):
        _why.append("its phrase does not end on a WORD BOUNDARY (no trailing \\b), so a longer word can carry it")
    _c = re.compile(_pat, re.I)
    if _c.groups > 1:
        _why.append(f"its phrase captures {_c.groups} names; a category names at most one")
    if bool(_c.groups) != bool(_allow) or bool(_c.groups) != bool(_where):
        _why.append("a phrase that captures a NAME must declare a non-empty allowlist AND where it lives, and a "
                    "phrase that captures none must declare neither -- a name class with no allowlist is the "
                    "OPEN SET of round 4")
    if _c.groups and not mandatory_group(_pat):
        _why.append("its name group is OPTIONAL, quantified, nested or behind an alternation, so the phrase can "
                    "match with NO name captured and the allowlist check has nothing to read")
    for _a in _allow:
        if PKG.fullmatch(str(_a)):
            _why.append(f"its allowlist entry {_a!r} IS a package this kit MEASURES, and a declared name is "
                        "exempted from the package rule (header (1a)); round 4's defect was exactly "
                        "``optional developer tool `torch` is not on PATH`` and it may not be declared into "
                        "existence")
    if not isinstance(_cap, int) or _cap < 1:
        _why.append(f"its cap {_cap!r} is not a positive integer")
    if _why:
        bad.append(f"POLICY:INTERNAL exemption category {_tok} is not declared as the policy requires: "
                   + "; ".join(_why))
    CATS.append((_tok, _c, re.compile(_pat[2:] if _pat.startswith("\\A") else _pat, re.I),
                 _cap, _where, {str(a).lower() for a in _allow}, _note))
if not CATS:
    bad.append("POLICY:INTERNAL EXEMPT_CATEGORIES is empty, so every exclusion built on it below is dead code; "
               "remove the machinery deliberately or declare a category")
# FAIL-CLOSED, AND IT MUST BE HERE RATHER THAN AT THE END: a registry that fails its own contract cannot be used
# to judge skips, and trying anyway is how round 7's N1 and N2 produced a TOKENLESS red run -- a non-int cap died
# at `len(_got) > _cap` (TypeError) and an optional capture group at `m.group(1).lower()` (AttributeError), both
# BEFORE the `for b in bad: print("FAIL:", b)` loop at the bottom of this block ever ran. rc=1 and RESULT: FAIL
# either way, so nothing was ever silently exempt; what was lost was the stable token that says WHICH defect it
# was, which is the whole point of a POLICY token.
if any(b.startswith("POLICY:INTERNAL") for b in bad):
    for b in bad: print("FAIL:", b)
    print("the exemption registry is not usable, so NO skip was judged in this run: fix the declaration above")
    sys.exit(1)
def claim(reason):
    """(the category token this reason CLAIMS, [(POLICY token, message), ...]); (None, []) means no claim.

    No claim is the SAFE direction and is where every DENIAL lands too: the skip is then judged by the mode that
    is running and counted in the per-module baseline, never silently excused. A non-empty failure list means
    the reason is SHAPED like a claim and is rejected LOUDLY in every mode, `--expect any` included, where no
    reason check runs at all.
    """
    r = reason.strip()
    for tok, anchored, _loose, _cap, _where, _allow, _note in CATS:
        if anchored.match(r) is None:
            continue                          # guards (1) and (2): anchored, and \b-terminated
        fails = []
        declared_spans = []                   # (1a): the spans the package rule below does NOT get to see
        for tok2, _a2, loose2, _c2, where2, allow2, note2 in CATS:
            for m in loose2.finditer(r):      # guard (5): EVERY occurrence, not only the anchored one
                if tok2 == tok and loose2.groups and (m.group(1) or "").lower() in allow2:
                    declared_spans.append((m.start(1), m.end(1)))
                if tok2 != tok:               # guard (6): one claim per reason
                    fails.append(("POLICY:EXEMPT_AMBIGUOUS",
                                  f"skip claims the {tok} environment exemption and carries the {tok2} phrase "
                                  f"as well, so it claims two categories at once. One skip has one cause, and a "
                                  f"per-category cap bounds that category only while a reason cannot be counted "
                                  f"in another's bucket; word the reason for the ONE category the test is "
                                  f"really gated on"))
                elif loose2.groups and (m.group(1) or "").lower() not in allow2:
                    fails.append((f"POLICY:{tok2}_UNDECLARED",
                                  f"skip claims an exemption {note2} but {m.group(1)} is not in the {where2} "
                                  f"allowlist in scripts/run_tests.sh (declare the tool there, with a test; do "
                                  f"not widen the phrase)"))
        # GUARD (3), the package rule, is applied LAST and is ADDITIVE rather than ordered against the rest:
        # ``optional developer tool `torch` is not on PATH`` is BOTH an undeclared name AND a reason that names
        # a measured package, and it is reported as both. Ordering the package rule first silently dropped
        # POLICY:TOOL_UNDECLARED for every undeclared name that happens to contain a package name -- `torchrun`,
        # the exact reason round 5 pinned -- which in `--expect any` (no reason check at all) left the run GREEN.
        # Measured: that is what the first draft of this registry did, and three subtests caught it.
        # (1a), round 7's F3: the package rule is applied to the reason with the span of every DECLARED name
        # blanked out, so declaring a name on the closed allowlist is no longer INERT for a name that happens to
        # contain a package substring (`yamllint` contains `yaml`; `torchfix` contains `torch`). Blanking rather
        # than deleting keeps every other offset and every other character intact, so a prose tail is judged
        # exactly as before -- ``optional developer tool `ruff` is not on PATH; libtorch is gone`` is still
        # denied, and an UNDECLARED name is not blanked at all, so ``... `torchrun` ...`` is still denied AND
        # reported as POLICY:TOOL_UNDECLARED.
        probe = r
        for _s, _e in declared_spans:
            probe = probe[:_s] + " " * (_e - _s) + probe[_e:]
        if PKG_EXEMPT.search(probe):
            return None, fails
        return (None if fails else tok), fails
    return None, []
def exempt_category(reason):
    """The category a reason is exempt under, or None. A reason whose claim FAILED is not exempt."""
    tok, fails = claim(reason)
    return None if fails else tok
# Skips excluded from the per-module baseline. ONE predicate, used by the generation branch AND the comparison
# branch below, because two copies of this list are exactly how `test_scripts <n> 4` would become
# machine-dependent -- 4 on a machine with ruff, 5 without it -- and a machine-dependent baseline is worse than
# none. PyYAML is excluded because it is the one optional package a developer may have without the others;
# matched as a WORD ((py)yaml) rather than as the bare substring "yaml", which also excluded any reason that
# merely contained those four letters.
# The spelling is taken FROM PKGS rather than retyped. It used to be an independent `\b(?:py)?yaml\b` while the
# comment on PKGS claimed PKGS was the tuple "from which NONE_OK, the baseline exclusion and the exemption rule
# are all built" -- a third of that sentence was false, which is the exact shape of the defect PKGS was created
# to end. A `yaml` dropped from PKGS now fails loudly as POLICY:INTERNAL instead of leaving this pattern
# silently naming a package the policy no longer measures.
_YAML = [p for p in PKGS if "yaml" in p]
if not _YAML:
    bad.append("POLICY:INTERNAL the PKGS tuple no longer names a yaml spelling, and the baseline's PyYAML "
               "exclusion is built from it; add it back or rewrite the exclusion deliberately")
PYYAML = re.compile(r"\b(?:py)?(?:" + "|".join(_YAML or ["yaml"]) + r")\b", re.I)
def base_excl(reason):
    return bool(PYYAML.search(reason)) or exempt_category(reason) is not None
# EVERY bucket, cap, note and failure token below comes from the ONE registry, so a category cannot be declared
# without a cap or be left out of the exclusions, and two categories cannot diverge by omission. `pkg` is every
# skip that claims no exemption -- INCLUDING every skip whose claim was rejected, which is what keeps a denial
# additive: it is reported here AND judged by the mode below (POLICY:NONE_REASON in bare mode,
# POLICY:TORCH_MODE_MISSING or POLICY:TORCH_MODE_UNEXPLAINED in torch mode).
# THE REGISTRY THIS RUN REALLY USED, printed AS DATA so that it can be COMPARED instead of trusted. ROUND 8's
# F1. test_the_category_registry_is_assigned_exactly_once_and_never_rebound asserts the registry contract on
# SOURCE TEXT, conceded that a binding made through `globals()[...]` or `setattr` is not a Name in Store context
# and so is invisible to it, and then claimed "the runtime half below is what covers a bad row however it
# arrives". THAT WAS FALSE, and it was the one sentence holding the door shut: the runtime half rejects a
# MALFORMED row (POLICY:INTERNAL), and the mutant that door admits is WELL FORMED. Measured, one line inserted
# after the literal:
#     globals()["EXEMPT_CATEGORIES"] = EXEMPT_CATEGORIES + (("ZED", r"\Aonly on this platform\b", 8, "", (),
#         "for a case-sensitive filesystem (expected on Linux runners)"),)
# -> `RESULT: OK`, NO POLICY token in any mode, a working cap, and its parked skips printed as "4 skip(s) for a
# case-sensitive filesystem (expected on Linux runners)" -- the figure docs/CLEAN_CLONE.md tells a Linux reader
# to expect -- while the whole script suite stayed green, because every check in that file is built from the
# LITERAL and none of them can see past it.
# So the run ATTESTS its registry: one JSON line per row, rendered from `CATS`, which is the value `claim()`
# reads two lines below. test_the_registry_the_run_really_uses_equals_the_declared_literal drives this script
# and requires the listing to equal the parsed literal row for row and column for column, so a row that arrives
# by ANY route -- the literal, a rebind, globals(), setattr, an import -- is a RED SUITE instead of a silent
# category. `_REGISTRY_USED` closes the one gap this placement leaves (a rebind made BETWEEN this listing and
# the cap loop) as POLICY:INTERNAL.
print(f"exemption registry: {len(CATS)} row(s), as this run judged them")
for _tok, _a, _l, _cap, _w, _al, _note in CATS:
    print("exemption registry row: " + json.dumps({"token": _tok, "phrase": _a.pattern, "cap": _cap,
                                                   "where": _w, "allow": sorted(_al), "note": _note},
                                                  sort_keys=True))
_REGISTRY_USED = list(CATS)
claimed = {}
for e in skips:
    _tok, _fails = claim(e["reason"])
    claimed[id(e)] = _tok
    for _token, _msg in _fails:
        bad.append(f"{_token} {_msg}: {e['id']} :: {e['reason']!r}")
pkg = [e for e in skips if claimed[id(e)] is None]
for _tok, _a, _l, _cap, _w, _al, _note in CATS:
    _got = [e for e in skips if claimed[id(e)] == _tok]
    if len(_got) > _cap:
        bad.append(f"POLICY:{_tok}_CAP {len(_got)} skip(s) claim the {_tok} exemption ({_note}); at most {_cap} "
                   f"are expected -- a growing count means tests are being parked in an environment category")
    if _got:
        print(f"note: {len(_got)} skip(s) {_note}; not counted toward package skips")
if list(CATS) != _REGISTRY_USED:
    bad.append("POLICY:INTERNAL the exemption registry changed between the listing printed above and the "
               "judging of this run's skips, so the listing a test compares against the declaration is not "
               "the registry these skips were judged by")
if mode == "none":
    # Built from PKG (the one package list) rather than retyping the four names a third time.
    NONE_OK = re.compile(PKG.pattern + r".*(not installed|missing|unavailable|not available)", re.I | re.S)
    for e in pkg:
        if not NONE_OK.search(e["reason"]): bad.append(f"POLICY:NONE_REASON skip reason does not say a package is missing: {e['id']} :: {e['reason']!r}")
    for e in skips:
        if re.search(r"torch present", e["reason"], re.I): bad.append("POLICY:TORCH_PRESENT a skip says torch is present although none is expected: " + e["id"])
    if len(pkg) < min_none: bad.append(f"POLICY:MIN_NONE_SKIPS expected >= {min_none} package skips with nothing installed, got {len(pkg)}: torch tests may be passing silently or were removed")
    if not any(re.search(r"torch", e["reason"], re.I) for e in pkg): bad.append("POLICY:NO_TORCH_REASON no skip mentions torch")
    if not any(re.search(r"numpy", e["reason"], re.I) for e in pkg): bad.append("POLICY:NO_NUMPY_REASON no skip mentions numpy")
elif mode == "torch":
    ALLOW = re.compile(r"\bcuda\b|\bmps\b|torch present", re.I)
    # DENY is deliberately NOT widened to the other spellings of "is missing" that `--expect none` accepts
    # ("unavailable", "not available"), and the reason is a measurement, not taste: it is applied to EVERY skip,
    # and two reasons the suite really emits in this mode contain those words --
    #   "torch present; unavailable path is exercised in the subprocess test"   (test_failure_modes.py)
    #   "CUDA not available: CPU-vs-CUDA comparison (ER-09) is UNKNOWN, not passed"  (test_tensor_ops.py)
    # -- so widening it turns documented step (d) red on every machine. (Measured; both reasons are driven
    # through this mode by test_live_torch_mode_skip_reasons_stay_accepted.) The laundering that widening was
    # proposed for is closed at the exemption instead: an exempt reason may not NAME a package at all, so it
    # cannot reach this check pretending to be an environment skip. Leaving a package-missing reason that avoids
    # these three spellings to POLICY:TORCH_MODE_UNEXPLAINED, which is where it lands, is the trade.
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
        rows = sorted((k, ran_mod[k], sum(1 for e in skips if mod(e["id"]) == k and not base_excl(e["reason"]))) for k in ran_mod)
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
            got = sum(1 for e in skips if mod(e["id"]) == k and not base_excl(e["reason"]))
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
    # Counted from the STAGED file, BEFORE the move, and with an explicit fallback instead of `|| true`. It used
    # to be `$(grep -cv '^#' "$BASELINE" || true)` -- read AFTER the move, from a path that might not be a file at
    # all -- so when the destination was a directory grep failed, printed nothing, and the line read
    # "baseline written: <dir> ( modules)": an empty count was the only hint that anything was wrong. `|| true`
    # discarded both grep's exit status and its "Is a directory" message. (The file exists here, so a non-zero
    # status now means only "no non-comment lines", i.e. zero modules, which prints as 0 rather than as nothing.)
    STAGED_MODULES="$(grep -cv '^#' "$TMP/base.staged")" || STAGED_MODULES=0
    if [ -d "$BASELINE" ]; then
      # `mv file dir/` SUCCEEDS: it drops the file inside as $BASELINE/base.staged. That is how
      # `--baseline scripts --update-baseline` printed RESULT: OK while leaving an untracked, un-gitignored
      # scripts/base.staged in the repository -- the D1 shape, in a kit whose demo.py carries an inode-identity
      # guard so that nothing can write there. The start-up check rejects a directory given on the command line;
      # this one catches a directory that appeared at that path DURING the run, which is all that is left.
      echo "FAIL: POLICY:BASELINE_WRITE the baseline path is a DIRECTORY, not a file: $BASELINE"
      echo "      the staged baseline was NOT moved (mv would have left base.staged inside it); baseline UNCHANGED"
      FAIL=1
    elif mv "$TMP/base.staged" "$BASELINE"; then
      echo "baseline written: $BASELINE ($STAGED_MODULES modules)"
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
