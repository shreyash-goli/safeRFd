#!/usr/bin/env bash
# Lint for the TOY safety-audit kit (SR-15). Works with NOTHING installed: python3 -m compileall plus an
# AST-based check written inline below. Optional linters (ruff, pyflakes) are used only if present and their
# findings are advisory (set LINT_STRICT=1 to make them fatal). A missing tool never fails this script.
#
# KNOWN GAPS (this is hygiene, not a sandbox): network use via getattr/string tricks, ctypes loaded under another
# name, `exec` of a string built at runtime, and a literal `os.system("curl ...")` OUTSIDE src/ are not caught.
# In src/ the rules below ban network/process modules, __import__, importlib, os.system/popen and any eval/exec
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
BANNED = {"socket", "urllib", "urllib2", "urllib3", "http", "httplib", "requests", "httpx", "aiohttp",
          "ftplib", "smtplib", "poplib", "imaplib", "telnetlib", "xmlrpc", "ssl", "websocket", "websockets",
          "_socket", "socketserver", "asyncio", "selectors", "webbrowser", "nntplib", "smtpd", "wsgiref", "cgi"}
PROC = {"subprocess", "ctypes", "importlib", "multiprocessing", "pty"}   # banned in src/ only
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
            if isinstance(fn, ast.Name) and fn.id in ("eval", "exec", "__import__", "compile"):
                lit = node.args[0].value if node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str) else None
                if fn.id in ("eval", "exec") and (path.as_posix(), lit) in EXEC_ALLOW:
                    pass
                else:
                    errors.append(f"{loc}: {fn.id}() in src/ (only the allow-listed literals in EXEC_ALLOW pass)")
            if isinstance(fn, ast.Attribute) and fn.attr in ("system", "popen", "import_module", "spawn", "execv", "execl", "run", "Popen", "call", "check_output") \
                    and isinstance(fn.value, ast.Name) and fn.value.id in ("os", "importlib", "subprocess"):
                errors.append(f"{loc}: {fn.value.id}.{fn.attr}() in src/")
        mods = []
        if isinstance(node, ast.Import):
            mods = [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            mods = [node.module]
        for m in mods:
            if m.split(".")[0] in BANNED:
                errors.append(f"{loc}: network-capable import '{m}' (offline-only kit)")
            if in_src and m.split(".")[0] in PROC:
                errors.append(f"{loc}: process/dynamic-loading import '{m}' in src/")
        if isinstance(node, (ast.Import, ast.ImportFrom)) and node.col_offset == 0:
            for a in node.names:
                imported.setdefault((a.asname or a.name).split(".")[0], node.lineno)
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

echo "== optional linters (advisory) =="
RAN_ANY=0
if command -v ruff >/dev/null 2>&1; then
  RAN_ANY=1
  # Real-error rules only (syntax, undefined names, invalid comparisons); no cache dir written into the repo.
  if ruff check --no-cache --select E9,F63,F7,F82 src tests scripts; then echo "ruff: OK"
  else echo "ruff: findings above"; [ "${LINT_STRICT:-0}" = 1 ] && FAIL=1; fi
fi
if python3 -m pyflakes --version >/dev/null 2>&1; then
  RAN_ANY=1
  if python3 -m pyflakes src scripts >"$TMP/pyflakes.txt" 2>&1; then echo "pyflakes: OK"
  else echo "pyflakes: $(wc -l <"$TMP/pyflakes.txt" | tr -d ' ') finding(s) (advisory)"; head -10 "$TMP/pyflakes.txt"
       [ "${LINT_STRICT:-0}" = 1 ] && FAIL=1; fi
fi
[ "$RAN_ANY" = 1 ] || echo "no optional linter (ruff/pyflakes) installed; skipped"

if [ "$FAIL" -ne 0 ]; then echo "LINT: FAIL"; exit 1; fi
echo "LINT: OK"
