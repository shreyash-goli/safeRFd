#!/usr/bin/env bash
# Lint for the TOY safety-audit kit (SR-15). Works with NOTHING installed: python3 -m compileall plus an
# AST-based check written inline below. Optional linters are used only if present. ruff's correctness
# rules (E9,F63,F7,F82 -- syntax, undefined names, bad comparisons) are FATAL when ruff is present;
# pyflakes findings stay advisory (set LINT_STRICT=1 to make them fatal too). A MISSING tool never
# fails this script, so the bare-interpreter path is unaffected. BOTH optional linters are gated on PATH
# (`command -v`), which is asserted structurally by
# test_every_optional_linter_is_gated_on_PATH_not_on_the_interpreter: an interpreter-gated probe
# (`python3 -m <tool>`) sees the interpreter's own site-packages and made a test measure the opposite branch
# from the one it names -- see the note on the pyflakes gate below.
#
# WHAT THIS IS: a module-name BLOCKLIST plus an attribute-name blocklist, plus (in src/ only) a positive
# standard-library-only check. A blocklist is a TRIPWIRE and is inherently INCOMPLETE: the Python standard library
# contains many more ways to execute code or open a socket than any list will name. Do not read a passing run as
# proof that src/ cannot execute code or reach the network.
#
# THIS HEADER IS NORMATIVE PROSE, AND IT IS INSIDE THE WITHDRAWN-GUARANTEE DISCIPLINE. It was outside it until
# SR-15's tenth round, which is how an unmarked sentence restating a guarantee this project had retracted was
# measured GREEN here; the scope of test_no_withdrawn_guarantee_is_restated_in_a_comment is now DERIVED from
# `git ls-files` rather than enumerated, so this file and every other tracked file is in it. A withdrawn claim
# may appear in the comments below only where a marker ("used to", "no longer", "retracted", ...) stands before
# it IN THE SAME SENTENCE. See docs/CLEAN_CLONE.md.
#
# KNOWN GAPS (this is hygiene, not a sandbox):
#   * runtime-name tricks: getattr(os, "sys" + "tem"), a module aliased through importlib's internals, `exec` of a
#     string built at runtime;
#   * a literal os.system("curl ...") OUTSIDE src/ (the process rules are src/-only by design);
#   * anything in a third-party package;
#   * reflection through a MAPPING rather than an attribute: vars(os)["system"], os.__dict__["system"],
#     dict(inspect.getmembers(os))["system"]. A different shape from the attribute blocklist, and deliberately
#     left uncovered (see docs/CLEAN_CLONE.md "Still not covered");
#   * STRING ANNOTATIONS and other places a name is spelled as data rather than as code. `typing.get_type_hints`
#     is now named, so the demonstrated form is caught, but the class is not closed: any other stdlib function
#     that evaluates a string it is handed is a fresh instance of it;
#   * and, most importantly, every stdlib code-execution or server entry point NOT named in the lists below. The
#     lists were extended after review found many that passed: see docs/CLEAN_CLONE.md "Lint scope" for the
#     enumeration of what is and is not named, and for the ones still known to pass.
# One whole class IS closed structurally rather than by name: src/ may import no underscore-prefixed top-level
# module (`__future__` excepted). The private C-extension counterparts of banned modules -- _pickle (arbitrary
# code via __reduce__), _imp (create_dynamic/exec_dynamic load a native extension), _posixsubprocess.fork_exec,
# _multiprocessing, _asyncio, _sqlite3, _tkinter, _curses -- were a systematic evasion of the blocklist, and
# only _socket and _ctypes had been thought of. A rule beats eight more names.
# In src/ the rules below (including aliasing like `import os as o`, `f = os.system`, `e = eval`, `builtins.exec`,
# `from os import system`, and the exec*/spawn*/posix_spawn* family) ban network/process modules, __import__, importlib, os.system/popen and any eval/exec
# except the two literal strings allow-listed by (file, exact text). The runtime socket guard in run_tests.sh is
# the second layer, and it is Python-level only (see docs/CLEAN_CLONE.md).
#
# Bytecode: PYTHONDONTWRITEBYTECODE is set and compileall's output is redirected to a temp
# PYTHONPYCACHEPREFIX that is deleted afterwards, so the repo never receives .pyc files (standing rule: stale
# .pyc contaminated earlier mutation results; see scripts/run_tests.sh).
set -u -o pipefail
ROOT="${LINT_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"   # LINT_ROOT: lets tests lint a synthetic tree
cd "$ROOT" || exit 2
export PYTHONDONTWRITEBYTECODE=1
TMP="$(mktemp -d "${TMPDIR:-/tmp}/saferf_lint.XXXXXX")"
trap 'rm -rf "$TMP"' EXIT
export PYTHONPYCACHEPREFIX="$TMP/pyc"
FAIL=0

echo "== compileall =="
if python3 -m compileall -q src tests scripts; then echo "compileall: OK"; else echo "FAIL: compileall"; FAIL=1; fi

echo "== AST checks =="
python3 - <<'PY' || FAIL=1
import ast, pathlib, sys
ROOT = pathlib.Path(".")
# Network/browser-capable module names, banned in src/, tests/ AND scripts/. `pydoc` starts an HTTP server
# (pydoc.browse); `antigravity` opens a web browser on import.
BANNED = {"socket", "urllib", "urllib2", "urllib3", "http", "httplib", "requests", "httpx", "aiohttp",
          "ftplib", "smtplib", "poplib", "imaplib", "telnetlib", "xmlrpc", "ssl", "websocket", "websockets",
          "_socket", "socketserver", "asyncio", "selectors", "webbrowser", "nntplib", "smtpd", "wsgiref", "cgi",
          "pydoc", "antigravity", "_ssl", "_asyncio"}
# Dotted names whose PARENT module is legitimate, so BANNED (which matches the top-level name) cannot hold them.
# logging.config.listen() runs a socket server that exec()s the configuration it receives; logging.handlers has
# SocketHandler/HTTPHandler/SMTPHandler.
BANNED_FULL = {"logging.config", "logging.handlers"}
# Process start / dynamic code loading, banned in src/ only. The second group is stdlib code EXECUTION: every one of
# these was found by review to pass this lint as a plain static import with a literal attribute call.
PROC = {"subprocess", "ctypes", "_ctypes", "importlib", "multiprocessing", "pty", "posix", "nt", "builtins"} | \
       {"runpy", "code", "codeop", "pdb", "bdb", "cProfile", "profile", "trace", "timeit", "doctest",
        "marshal", "pickle", "shelve", "zipimport", "pkgutil", "site", "venv", "py_compile", "compileall",
        "modulefinder"} | \
       {"ensurepip", "sqlite3", "tkinter", "turtle"}   # pip (network); sqlite3 loads native extensions; Tcl exec
PROC_FULL = {"concurrent.futures"}        # ProcessPoolExecutor is the same capability as multiprocessing
# src/ is standard-library only. This is the POSITIVE check (the blocklists above are negative and incomplete):
# any top-level import that is not a stdlib module, not the kit's own `toy` package and not the one documented
# optional dependency is an error.
SRC_IMPORT_OK = set(sys.stdlib_module_names) | {"toy", "torch"}
# Attribute names that start processes or execute/load code. Banned in src/ on ANY base object (this catches
# `import os as o; o.system(..)`, `f = os.system`, `builtins.exec(..)`) and as `from os import <name>`.
# `resolve_name` is listed first because pkgutil.resolve_name("os:system") defeats every other entry in this set
# in a single line: it returns the function without ever naming it as an attribute.
# `loadTestsFromName` is listed with `resolve_name` because it is the same shape and the same power:
# unittest.TestLoader().loadTestsFromName("os.system") is a plain static call with a literal string.
# `_getframe` reaches the caller's builtins (sys._getframe().f_builtins["exec"]).
#
# The last three were each DEMONSTRATED to execute a shell command and to pass this lint with `0 error(s)`, with no
# eval/exec/compile/getattr/__dict__/vars/getmembers token anywhere, and were reported as NOT part of any failing
# criterion (the doc already concedes "any stdlib code-execution or server entry point nobody has thought of yet").
# They are closed because they cost one name each, not because the list is now complete:
#   get_type_hints  -- typing.get_type_hints(f) EVALUATES a string annotation, so a return annotation that is the
#                      string "__import__('os').system('echo pwned')" runs as code with no eval in sight.
#   getattr_static  -- inspect.getattr_static(os, "system") returns the function without an attribute access the
#                      blocklist can see; same shape and same power as pkgutil.resolve_name.
#   breakpointhook  -- sys.breakpointhook("...") honours $PYTHONBREAKPOINT (e.g. os.system). The bare builtin
#                      `breakpoint()` reaches pdb -- a module named in PROC -- through no import at all, so it is
#                      in DANGEROUS_NAMES below rather than here.
DANGEROUS_ATTR = {"resolve_name", "loadTestsFromName", "_getframe",
                  "get_type_hints", "getattr_static", "breakpointhook",
                  "system", "popen", "fork", "forkpty", "startfile", "import_module", "exec",
                  "eval", "__import__", "posix_spawn", "posix_spawnp", "Popen", "check_output", "check_call",
                  "runsource", "runcode", "interact", "run_module", "run_path", "runctx",
                  "load_module", "exec_module", "create_module", "find_module",
                  "FunctionType", "CodeType", "addsitedir", "getnode", "uuid1", "browse", "listen",
                  "testmod", "testfile", "ProcessPoolExecutor", "EnvBuilder", "bootstrap",
                  "load_extension", "enable_load_extension", "attrgetter", "methodcaller"} | \
                 {f"{p}{s}" for p in ("exec", "spawn") for s in ("l", "le", "lp", "lpe", "v", "ve", "vp", "vpe")}
# banned in src/ only. `breakpoint` is a BUILTIN that reaches pdb (named in PROC) with no import, and honours
# $PYTHONBREAKPOINT, so it is the one entry here that needs no module reference at all.
DANGEROUS_NAMES = {"eval", "exec", "__import__", "compile", "__builtins__", "breakpoint"}
# eval/exec allowed in src/ ONLY for these exact (file, literal text) pairs: the demonstration of a bare-exception
# statement. Anything else, including other string literals, is an error.
EXEC_ALLOW = {("src/toy/failure_modes.py", "evaluated += 1; RuntimeError"),
              ("src/toy/failure_modes.py", "evaluated += 1; RuntimeError('never raised')")}
errors, warnings = [], []
files = sorted(p for d in ("src", "tests", "scripts") for p in (ROOT / d).rglob("*.py"))
for path in files:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except SyntaxError as e:
        errors.append(f"{path}:{e.lineno}: syntax error: {e.msg}"); continue
    except ValueError as e:
        errors.append(f"{path}: cannot parse: {e}"); continue
    in_src = path.parts[0] == "src"
    in_tests = path.parts[0] == "tests"
    imported = {}
    allowed_names = set()
    for node in ast.walk(tree):
        loc = f"{path}:{getattr(node, 'lineno', 0)}"
        if isinstance(node, ast.ExceptHandler) and node.type is None:
            errors.append(f"{loc}: bare 'except:' (swallows KeyboardInterrupt/SystemExit)")
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for d in node.args.defaults + [k for k in node.args.kw_defaults if k is not None]:
                if isinstance(d, (ast.List, ast.Dict, ast.Set)):
                    errors.append(f"{loc}: mutable default argument in {node.name}()")
        if isinstance(node, ast.Assert) and isinstance(node.test, ast.Tuple) and node.test.elts:
            errors.append(f"{loc}: assert on a non-empty tuple is always true")
        if isinstance(node, ast.Compare) and any(isinstance(o, (ast.Is, ast.IsNot)) for o in node.ops):
            for c in [node.left, *node.comparators]:
                if isinstance(c, ast.Constant) and isinstance(c.value, (str, bytes, int, float)) \
                        and not isinstance(c.value, bool):
                    errors.append(f"{loc}: 'is' comparison with a literal")
        if in_src and isinstance(node, ast.Call):
            fn = node.func
            if isinstance(fn, ast.Name) and fn.id in ("eval", "exec"):
                lit = node.args[0].value if node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str) else None
                if (path.as_posix(), lit) in EXEC_ALLOW:
                    allowed_names.add(id(fn))
        if in_src and isinstance(node, ast.Attribute) and node.attr in DANGEROUS_ATTR:
            errors.append(f"{loc}: attribute '.{node.attr}' (process start / dynamic code) in src/")
        # `from <anything> import <dangerous name>` in src/. No longer limited to os/posix/nt/builtins/importlib:
        # `from pkgutil import resolve_name`, `from runpy import run_module` and `from types import FunctionType`
        # all have to be caught, and a star-import hides any of them.
        if in_src and isinstance(node, ast.ImportFrom) and node.level == 0 \
                and any(a.name in DANGEROUS_ATTR or a.name in DANGEROUS_NAMES or a.name == "*" for a in node.names):
            errors.append(f"{loc}: 'from {node.module} import ...' of a process/dynamic-code function in src/")
        mods, submods = [], []
        if isinstance(node, ast.Import):
            mods = [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            mods = [node.module]
            submods = [f"{node.module}.{a.name}" for a in node.names]   # catches `from logging import config`
        for m in mods:
            top = m.split(".")[0]
            if top in BANNED or m in BANNED_FULL:
                errors.append(f"{loc}: network-capable import '{m}' (offline-only kit)")
            if in_src and (top in PROC or m in PROC_FULL):
                errors.append(f"{loc}: process/dynamic-loading import '{m}' in src/")
            # STRUCTURAL rule, not another name: the private C-extension counterparts of the banned modules
            # (_pickle, _imp, _posixsubprocess, _multiprocessing, _asyncio, _sqlite3, _tkinter, _curses, ...)
            # are one greppable class, and only _socket/_ctypes had been named. src/ imports none of them.
            if in_src and top.startswith("_") and top != "__future__":
                errors.append(f"{loc}: private implementation module import '{m}' in src/ (underscore-prefixed "
                              f"C-extension/internal modules are the counterparts of the banned ones)")
            if in_src and top not in SRC_IMPORT_OK:
                errors.append(f"{loc}: non-stdlib import '{m}' in src/ (src/ is standard-library only; the only "
                              f"allowed non-stdlib name is the documented optional 'torch')")
        for m in submods:   # dotted submodule of a legitimate parent; the loop above cannot see these
            if m in BANNED_FULL:
                errors.append(f"{loc}: network-capable import '{m}' (offline-only kit)")
            if in_src and m in PROC_FULL:
                errors.append(f"{loc}: process/dynamic-loading import '{m}' in src/")
        if isinstance(node, (ast.Import, ast.ImportFrom)) and node.col_offset == 0:
            for a in node.names:
                imported.setdefault((a.asname or a.name).split(".")[0], node.lineno)
    if in_src:   # bare references: `e = eval`, `f = exec`, `__builtins__`, and non-allow-listed calls
        for node in ast.walk(tree):
            if isinstance(node, ast.Name) and node.id in DANGEROUS_NAMES and id(node) not in allowed_names:
                errors.append(f"{path}:{node.lineno}: {node.id} used in src/ (only the allow-listed exec literals in EXEC_ALLOW pass)")
    # Shadowed definitions: a duplicate test method is silently never run.
    for scope in ast.walk(tree):
        if isinstance(scope, (ast.ClassDef, ast.Module)):
            seen = {}
            for n in scope.body:
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    if n.name in seen and not n.decorator_list:
                        (errors if (in_tests and n.name.startswith("test")) else warnings).append(
                            f"{path}:{n.lineno}: '{n.name}' redefines line {seen[n.name]} (earlier one never runs)")
                    seen[n.name] = n.lineno
    # Unused module-level imports (advisory).
    names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)} | \
            {n.value.id for n in ast.walk(tree) if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name)}
    text = path.read_text(encoding="utf-8")
    if path.name != "__init__.py" and "__all__" not in text:
        for nm, ln in imported.items():
            if nm not in names and nm != "annotations" and f"noqa" not in text.splitlines()[ln - 1]:
                warnings.append(f"{path}:{ln}: import '{nm}' appears unused")
print(f"checked {len(files)} files; {len(errors)} error(s), {len(warnings)} warning(s)")
for w in warnings[:25]: print("warn:", w)
if len(warnings) > 25: print(f"warn: ... {len(warnings) - 25} more")
for e in errors: print("ERROR:", e)
sys.exit(1 if errors else 0)
PY

echo "== optional linters =="
RAN_ANY=0
if command -v ruff >/dev/null 2>&1; then
  RAN_ANY=1
  # E9/F63/F7/F82 are CORRECTNESS, not style: syntax errors, invalid comparisons, undefined names.
  # These are FATAL when ruff is present, not advisory. Reason, from a real miss: an undefined `Any`
  # in a committed annotation in src/toy/benchmark.py went unnoticed because ruff reported it and
  # this script printed "LINT: OK" anyway -- `from __future__ import annotations` keeps such a name
  # from raising at runtime, so nothing else caught it either. A linter finding that nobody has to
  # act on is a linter finding nobody reads.
  # A MISSING ruff still never fails the script: the bare-interpreter guarantee is unchanged, and
  # that is why this is gated on `command -v` rather than being required.
  if ruff check --no-cache --select E9,F63,F7,F82 src tests scripts; then echo "ruff: OK"
  else echo "ruff: correctness findings above (FATAL: undefined names and syntax errors are not style)"
       FAIL=1; fi
fi
# GATED ON PATH, LIKE ruff ABOVE, AND THAT SYMMETRY IS THE POINT. This used to probe
# `python3 -m pyflakes --version` -- THROUGH THE INTERPRETER -- while ruff was gated on `command -v`, and the
# asymmetry made a test measure the opposite branch from the one it names: tests/toy_tests/test_scripts.py
# builds a PATH directory holding only a `python3` symlink so that a lint run genuinely has no optional linter
# on PATH, and its docstring claimed "a directory we construct cannot drift that way". It can: the symlinked
# interpreter brings its OWN site-packages, so on an interpreter with pyflakes importable (measured on a
# conda python3 on the development host, CPython 3.13.5, pyflakes 3.4.0) `RAN_ANY=1` and the
# "no optional linter ... skipped" branch below NEVER FIRED -- a real live failure of
# test_missing_optional_tools_never_fail, invisible under an interpreter without pyflakes and invisible in CI,
# where neither job installs it.
# THE BEHAVIOUR THIS CHANGES, measured rather than argued: `python3 -m pyflakes` works wherever pyflakes is
# IMPORTABLE, and `command -v pyflakes` needs its console script on PATH. On this host both are present and
# both print the same three advisory findings, so nothing is lost here; what is lost in general is the advisory
# run (and, with LINT_STRICT=1, its fatality) in an environment where pyflakes is importable but its console
# script is not on PATH. The trade is taken because the `-m` form also coupled the linter to whichever
# `python3` the PATH resolves, while the console script carries its own interpreter -- so the probe and the run
# could disagree about what is installed, which is the defect above in one sentence.
if command -v pyflakes >/dev/null 2>&1; then
  RAN_ANY=1
  if pyflakes src scripts >"$TMP/pyflakes.txt" 2>&1; then echo "pyflakes: OK"
  else echo "pyflakes: $(wc -l <"$TMP/pyflakes.txt" | tr -d ' ') finding(s) (advisory)"; head -10 "$TMP/pyflakes.txt"
       [ "${LINT_STRICT:-0}" = 1 ] && FAIL=1; fi
fi
[ "$RAN_ANY" = 1 ] || echo "no optional linter (ruff/pyflakes) installed; skipped"

if [ "$FAIL" -ne 0 ]; then echo "LINT: FAIL"; exit 1; fi
echo "LINT: OK"
