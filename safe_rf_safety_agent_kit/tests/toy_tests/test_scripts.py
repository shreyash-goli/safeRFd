"""SR-15 tests for the dev/CI scripts. TOY ONLY. Standard library only (PyYAML is used if present, never required)."""
import ast
import os
import re
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"
CI = ROOT / ".github" / "workflows" / "ci.yml"


def _lint_blocklists():
    """Read the network blocklists OUT OF scripts/lint.sh instead of restating them.

    They used to be two hand-maintained copies and they diverged: lint.sh named 27 modules, this file named 18, so
    `import asyncio` in src/toy/ was rejected by the script and missed by the test that docs/CLEAN_CLONE.md cites
    as co-enforcing the rule. Parsing makes divergence impossible rather than merely noticed.
    """
    text = (SCRIPTS / "lint.sh").read_text(encoding="utf-8")
    out = []
    for name in ("BANNED", "BANNED_FULL"):
        m = re.search(rf"(?m)^{name} = (\{{.*?\}})\n", text, re.S)
        if m is None:
            raise AssertionError(f"scripts/lint.sh no longer defines {name} as a plain set literal; this file "
                                 f"parses it (see _lint_blocklists) and must be updated together with it")
        out.append(frozenset(ast.literal_eval(m.group(1))))
    return out


BANNED, BANNED_FULL = _lint_blocklists()


def _guard_source():
    """The socket-guard block exactly as scripts/run_tests.sh appends it to the sitecustomize shim."""
    text = (SCRIPTS / "run_tests.sh").read_text(encoding="utf-8")
    m = re.search(r"<<'PY'\n(import socket as _s\n.*?)\nPY\n", text, re.S)
    if m is None:
        raise AssertionError("scripts/run_tests.sh no longer appends a socket-guard heredoc beginning with "
                             "`import socket as _s`; this file parses it (see _guard_source) and must be "
                             "updated together with it")
    return m.group(1)


def _guard_lists():
    """(patched socket-module names, patched socket-method names, disclosed-unpatched names) -- parsed OUT of the
    guard in scripts/run_tests.sh rather than restated here.

    The guard used to be a run of assignments that grew one name per review round (gethostbyname_ex, then
    getnameinfo, then gethostbyaddr/getfqdn), and the disclosure was hand-written prose that went stale twice
    (docs/CLEAN_CLONE.md said "five patched socket-module functions" while the script patched seven). Parsing
    makes the test, the drive table and the documentation derive from the script.
    """
    src = _guard_source()
    out = []
    for name in ("_BLOCK_MODULE", "_BLOCK_SOCKET", "_NOT_BLOCKED"):
        m = re.search(rf"(?m)^{name} = (\(.*?\))\n", src, re.S)
        if m is None:
            raise AssertionError(f"the socket guard in scripts/run_tests.sh no longer defines {name} as a plain "
                                 f"tuple literal; this file parses it (see _guard_lists)")
        out.append(frozenset(ast.literal_eval(m.group(1))))
    return out


PATCHED_MODULE, PATCHED_SOCKET, GUARD_DISCLOSED = _guard_lists()


def _policy_pkgs():
    """The packages whose absence `scripts/run_tests.sh` measures -- its `PKGS` tuple, parsed out of the script.

    Three rules in the script are built from it (the none-mode reason check, the baseline exclusion, and the rule
    that an environment-skip exemption may not name a measured package), and the fourth SR-15 FAIL was those
    three being hand-written lists that disagreed. The tests that drive the rule derive their cases from this, so
    a package added to the script is a package the suite immediately tries to launder.
    """
    text = (SCRIPTS / "run_tests.sh").read_text(encoding="utf-8")
    m = re.search(r"(?m)^PKGS = (\(.*?\))\n", text, re.S)
    if m is None:
        raise AssertionError("scripts/run_tests.sh no longer defines PKGS as a plain tuple literal; this file "
                             "parses it (see _policy_pkgs) and must be updated together with it")
    return tuple(ast.literal_eval(m.group(1)))


POLICY_PKGS = _policy_pkgs()

# One driving expression per patched entry point, keyed exactly as the guard names it ("socket." prefix = a
# method on socket.socket). test_network_guard_blocks_every_patched_entry_point builds a synthetic suite out of
# this table and asserts the keys are EXACTLY the parsed patch set, so a name cannot be added to the guard
# without a test that drives it through the real script, and the table cannot claim coverage of a name the guard
# no longer patches.
#
# EVERY TARGET IS LOOPBACK, and that is not cosmetic: the negative control runs these with the guard DISABLED
# (--no-network-guard), because that is what makes it a control. They used to aim at 192.0.2.1:9, so a bare run
# of this suite made three real outbound connection attempts (plus a fourth from the runner's canary) while the
# docs said no network was touched at test time. 127.0.0.1:1 is a closed port -- ECONNREFUSED comes back from
# the local stack, nothing is transmitted, and it is instant instead of waiting out SYN retransmission.
# socket.listen is driven on an AF_UNIX socket because listen() on an unbound INET socket auto-binds to the
# wildcard address; AF_UNIX gives the same "did the guard fire?" answer without any listener at all.
GUARD_CALLS = {
    "create_connection": 'socket.create_connection(("127.0.0.1", 1), timeout=1)',
    "create_server": 'socket.create_server(("127.0.0.1", 0)).close()',
    "getaddrinfo": 'socket.getaddrinfo("127.0.0.1", 80)',
    "getfqdn": 'socket.getfqdn("127.0.0.1")',
    "gethostbyaddr": 'socket.gethostbyaddr("127.0.0.1")',
    "gethostbyname": 'socket.gethostbyname("127.0.0.1")',
    "gethostbyname_ex": 'socket.gethostbyname_ex("127.0.0.1")',
    "getnameinfo": 'socket.getnameinfo(("127.0.0.1", 80), socket.NI_NUMERICHOST | socket.NI_NUMERICSERV)',
    "socket.bind": '_tcp().bind(("127.0.0.1", 0))',
    "socket.connect": '_tcp().connect(("127.0.0.1", 1))',
    "socket.connect_ex": '_tcp().connect_ex(("127.0.0.1", 1))',
    "socket.listen": '_unix().listen(1)',
    "socket.sendmsg": '_udp().sendmsg([b""], [], 0, ("127.0.0.1", 9))',
    "socket.sendto": '_udp().sendto(b"", ("127.0.0.1", 9))',
}


def _guard_suite_body():
    """A synthetic suite with one test per patched entry point, generated from GUARD_CALLS.

    With the guard on, each must raise OSError("NETWORK BLOCKED ..."). With --no-network-guard each must NOT:
    the calls then either return normally (bind, sendto, every resolver) or raise a local OSError whose message
    is "Connection refused" / "Invalid argument", so every single test fails. That difference is the control.
    """
    lines = ["import socket, unittest",
             "def _tcp():",
             "    s = socket.socket(); s.settimeout(1); return s",
             "def _udp():",
             "    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); s.settimeout(1); return s",
             "def _unix():",
             "    return socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)",
             "def blocked(fn):",
             "    def t(self):",
             "        with self.assertRaises(OSError) as cm:",
             "            fn()",
             "        self.assertIn('NETWORK BLOCKED', str(cm.exception))",
             "    return t",
             "class T(unittest.TestCase):"]
    for name, call in sorted(GUARD_CALLS.items()):
        lines.append(f"    test_{name.replace('.', '_')} = blocked(lambda: {call})")
    return "\n".join(lines) + "\n"


def _code_string_literals(path):
    """(lineno, text) for every string literal in a .py file that is NOT a docstring, or every non-comment line
    of a .sh file. The historical record of the 192.0.2.1 defect lives in comments and docstrings on purpose;
    this is for scanning what the files actually EXECUTE."""
    text = path.read_text(encoding="utf-8")
    if path.suffix != ".py":
        return [(i, l) for i, l in enumerate(text.splitlines(), 1) if not l.lstrip().startswith("#")]
    tree = ast.parse(text)
    docs = set()
    for node in ast.walk(tree):
        body = getattr(node, "body", None)
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and body:
            first = body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) \
                    and isinstance(first.value.value, str):
                docs.add(id(first.value))
    return [(n.lineno, n.value) for n in ast.walk(tree)
            if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in docs]


def _env(**extra):
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", PYTHONHASHSEED="0")
    env.update(extra)
    return env


def _dirty():
    """Paths git already reports as modified (another agent/human may be editing them concurrently)."""
    try:
        r = subprocess.run(["git", "status", "--porcelain"], cwd=ROOT, capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return set()
    return {line[3:].strip().strip('"') for line in r.stdout.splitlines() if line[3:]}


def _listing():
    """Every file under the repo (excluding .git and bytecode caches): path -> (size, mtime), plus the set of paths
    git reports as modified at that moment (someone else may be editing them concurrently)."""
    out = {}
    for dp, dns, fns in os.walk(ROOT):
        dns[:] = [d for d in dns if d not in (".git", "__pycache__")]
        for fn in fns:
            p = Path(dp) / fn
            st = p.lstat()
            out[str(p.relative_to(ROOT))] = (st.st_size, st.st_mtime_ns)
    return out, _dirty()


def _same(before, after):
    """Equal path sets, and equal size/mtime for every file not git-dirty at either snapshot. A concurrent edit by
    another agent cannot flake this, but any created/deleted path or change to a clean file is detected."""
    (b, bd), (a, ad) = before, after
    if set(b) != set(a):
        return False
    skip = bd | ad
    return all(b[k] == a[k] for k in b if not any(k == d or k.startswith(d) for d in skip))


class TestScriptsExist(unittest.TestCase):
    def test_scripts_exist_and_are_executable(self):
        for name in ("run_tests.sh", "lint.sh", "demo.py"):
            p = SCRIPTS / name
            self.assertTrue(p.is_file(), name)
            self.assertTrue(os.access(p, os.X_OK), f"{name} is not executable")

    def test_shell_scripts_parse(self):
        for name in ("run_tests.sh", "lint.sh"):
            r = subprocess.run(["bash", "-n", str(SCRIPTS / name)], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)

    def test_run_tests_encodes_the_standing_rules(self):
        t = (SCRIPTS / "run_tests.sh").read_text(encoding="utf-8")
        for needle in ("PYTHONDONTWRITEBYTECODE=1", "PYTHONHASHSEED", "__pycache__", '-m unittest discover -s "$TESTS_DIR"',
                       "-m pytest", "no:cacheprovider", "stale .pyc"):
            self.assertIn(needle, t)
        self.assertIn("pytest is not installed", t)   # graceful skip

    def test_support_files_exist(self):
        for rel in ("requirements-dev.txt", "constraints.txt", "docs/CLEAN_CLONE.md"):
            self.assertTrue((ROOT / rel).is_file(), rel)
        self.assertRegex((ROOT / "constraints.txt").read_text(encoding="utf-8"), r"(?m)^numpy==1\.26\.\d+")

    def test_lint_script_passes(self):
        r = subprocess.run([str(SCRIPTS / "lint.sh")], capture_output=True, text=True, env=_env(), cwd=ROOT, timeout=120)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("LINT: OK", r.stdout)


class TestDemo(unittest.TestCase):
    def test_demo_succeeds_prints_disclaimer_and_writes_nothing_into_repo(self):
        before = _listing()
        r = subprocess.run([sys.executable, str(SCRIPTS / "demo.py")], capture_output=True, text=True,
                           env=_env(), cwd=ROOT, timeout=120)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("DEMO OK", r.stdout)
        self.assertIn("NOT EVIDENCE", r.stdout)
        self.assertIn("RFdiffusion", r.stdout)
        self.assertIn("real biological capability", r.stdout)
        self.assertTrue(_same(before, _listing()), "demo changed files inside the repository")
        # temp dir was cleaned up
        m = re.search(r"temp dir \(all outputs go here\): (\S+)", r.stdout)
        self.assertIsNotNone(m)
        self.assertFalse(Path(m.group(1)).exists())

    def test_demo_fails_nonzero_when_toy_package_missing(self):
        r = subprocess.run([sys.executable, str(SCRIPTS / "demo.py"), "--src", str(ROOT / "docs")],
                           capture_output=True, text=True, env=_env(), cwd=ROOT, timeout=60)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("DEMO FAILED", r.stderr)
        self.assertNotIn("DEMO OK", r.stdout)

    def test_demo_fails_nonzero_when_one_module_missing(self):
        import shutil
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            shutil.copytree(ROOT / "src" / "toy", Path(td) / "toy", ignore=shutil.ignore_patterns("__pycache__"))
            (Path(td) / "toy" / "dashboard.py").unlink()
            r = subprocess.run([sys.executable, str(SCRIPTS / "demo.py"), "--src", td], capture_output=True,
                               text=True, env=_env(), cwd=ROOT, timeout=60)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("dashboard", r.stderr)

    def test_demo_refuses_tmpdir_inside_repo(self):
        before = _listing()
        with __import__("tempfile").TemporaryDirectory(dir=ROOT) as td:
            r = subprocess.run([sys.executable, str(SCRIPTS / "demo.py")], capture_output=True, text=True,
                               env=_env(TMPDIR=td), cwd=ROOT, timeout=60)
            leftovers = list(Path(td).iterdir())
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("inside the repository", r.stderr)
        self.assertEqual(leftovers, [], "demo left output inside the repo-local TMPDIR")
        self.assertTrue(_same(before, _listing()))


class TestCiWorkflow(unittest.TestCase):
    def setUp(self):
        self.text = CI.read_text(encoding="utf-8")

    def test_structure_by_text(self):
        t = self.text
        self.assertRegex(t, r"(?m)^jobs:\s*$")
        self.assertRegex(t, r"(?m)^permissions:\s*\n\s+contents: read\s*$")
        for needle in ("run_tests.sh --expect none --twice", "run_tests.sh --expect torch --twice", "scripts/demo.py",
                       "scripts/lint.sh", 'PYTHONHASHSEED: "0"', "PYTHONDONTWRITEBYTECODE", "constraints.txt",
                       '"3.12"', "numpy must stay <2"):
            self.assertIn(needle, t)
        self.assertNotIn("\t", t)

    def test_read_only_no_secrets_no_publish(self):
        body = "\n".join(l for l in self.text.splitlines() if not l.lstrip().startswith("#"))  # prose may say "no deploy"
        for bad in ("secrets.", "git push", "git commit", "docker push", "twine", "gh release", "deploy",
                    "upload-artifact", "curl ", "wget ", "id-token", "contents: write"):
            self.assertNotIn(bad, body, bad)

    def test_core_job_installs_nothing(self):
        core = self.text.split("optional-deps:")[0]
        self.assertNotIn("pip install", core)

    def test_parses_with_yaml_if_available(self):
        try:
            import yaml
        except ImportError:
            self.skipTest("PyYAML not installed (optional); structural text checks above still ran")
        d = yaml.safe_load(self.text)
        self.assertEqual(set(d["jobs"]), {"core-no-deps", "optional-deps"})
        self.assertEqual(d["permissions"], {"contents": "read"})
        self.assertIn("3.12", d["jobs"]["core-no-deps"]["strategy"]["matrix"]["python"])
        for job in d["jobs"].values():
            self.assertTrue(all("steps" in job and isinstance(job["steps"], list) for _ in [0]))


class TestNoNetworkImports(unittest.TestCase):
    def test_blocklist_is_parsed_from_lint_sh_and_holds_the_known_names(self):
        """Pins the single-source-of-truth parse in _lint_blocklists(). A silently empty or short set would make
        every network-import assertion in this module vacuous, which is exactly how the 27-vs-18 divergence hid."""
        self.assertGreaterEqual(len(BANNED), 27)
        for m in ("socket", "urllib", "http", "requests", "ssl", "_socket", "socketserver", "asyncio", "selectors",
                  "webbrowser", "nntplib", "smtpd", "wsgiref", "cgi", "pydoc", "antigravity"):
            self.assertIn(m, BANNED, m)
        self.assertIn("logging.config", BANNED_FULL)

    def test_src_toy_has_no_network_imports(self):
        found = []
        for p in sorted((ROOT / "src" / "toy").rglob("*.py")):
            for node in ast.walk(ast.parse(p.read_text(encoding="utf-8"))):
                mods = []
                if isinstance(node, ast.Import):
                    mods = [a.name for a in node.names]
                elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                    mods = [node.module] + [f"{node.module}.{a.name}" for a in node.names]
                found += [f"{p.name}:{node.lineno}: {m}" for m in mods
                          if m.split(".")[0] in BANNED or m in BANNED_FULL]
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "__import__":
                    found.append(f"{p.name}:{node.lineno}: __import__")
        self.assertEqual(found, [])

    def test_src_toy_imports_only_the_standard_library(self):
        """docs/CLEAN_CLONE.md claims src/ is standard-library only. Nothing used to check it: `import numpy`,
        `pandas`, `scipy` and `yaml` in src/toy/ all passed lint with rc=0 and 0 errors. The only non-stdlib names
        allowed are the kit's own `toy` package and the documented, guarded, optional `torch`."""
        allowed = set(sys.stdlib_module_names) | {"toy", "torch"}
        found = []
        for p in sorted((ROOT / "src").rglob("*.py")):
            for node in ast.walk(ast.parse(p.read_text(encoding="utf-8"))):
                mods = []
                if isinstance(node, ast.Import):
                    mods = [a.name for a in node.names]
                elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                    mods = [node.module]
                found += [f"{p.name}:{node.lineno}: {m}" for m in mods if m.split(".")[0] not in allowed]
        self.assertEqual(found, [], "non-stdlib import in src/")

    def test_demo_script_has_no_network_imports(self):
        tree = ast.parse((SCRIPTS / "demo.py").read_text(encoding="utf-8"))
        mods = {a.name.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
        mods |= {n.module.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}
        self.assertFalse(mods & BANNED)

    def test_curl_audit_commands_are_not_executed_by_scripts_or_ci(self):
        for p in (SCRIPTS / "run_tests.sh", SCRIPTS / "lint.sh", CI):
            self.assertNotRegex(p.read_text(encoding="utf-8"), r"(?m)^\s*(curl|wget|gh api)\b", p.name)

    def test_env_flags_are_documented_as_inert_and_really_are_unread(self):
        flags = ("RUN_MODE", "ALLOW_EXTERNAL_NETWORK", "MODEL_WEIGHTS_ENABLED", "BIOLOGICAL_TRAINING_ENABLED", "TOY_SEED")
        files = list((ROOT / "src").rglob("*.py")) + list(SCRIPTS.iterdir()) + [CI]
        for p in files:
            if p.is_file():
                body = "\n".join(l for l in p.read_text(encoding="utf-8").splitlines() if not l.lstrip().startswith("#"))
                for f in flags:
                    self.assertNotIn(f, body, f"{p.name} references {f}; if a flag becomes real, enforce and test it")
        doc = (ROOT / "docs" / "CLEAN_CLONE.md").read_text(encoding="utf-8")
        self.assertIn("declarative markers only", doc)
        self.assertIn("No code reads any of them", doc.replace("**No code reads any of them**", "No code reads any of them"))
        self.assertNotRegex(doc, r"flags govern the \*\*toy application")

    def test_docs_carry_the_honest_ci_caveats(self):
        doc = (ROOT / "docs" / "CLEAN_CLONE.md").read_text(encoding="utf-8")
        for needle in ("has never been executed", "untested as a combination", "tag, not commit SHA", "stand-in", "case-sensitive", "has never been observed"):
            self.assertIn(needle, doc)

    def test_filesystem_case_skip_count_in_the_docs_matches_the_actually_gated_tests(self):
        """F1 was a NUMBER that disagreed with reality in the same document (it said both "1 filesystem-case" and
        "four tests skip this way") and a FALSE cause for the disagreement ("the dashboard tests were since
        changed" -- the three `need_ci()` call sites were never touched; the stand-in measured 1 because its
        `TMPDIR` sat on the case-insensitive system volume while only the repo was case-sensitive).

        So this is not a doc grep: it counts the tests that really gate on a case-sensitivity probe and requires
        the documented figure to equal it."""
        dash = (ROOT / "tests" / "toy_tests" / "test_dashboard.py").read_text(encoding="utf-8")
        # split so this expression does not match itself when it reads this very file
        own_needle = 'self.skipTest("filesystem is ' + 'case-sensitive'
        gated = dash.count("self.need_ci()") + Path(__file__).read_text(encoding="utf-8").count(own_needle)
        self.assertEqual(gated, 4, "the number of case-sensitivity-gated tests changed: update the '4' in "
                                   "docs/CLEAN_CLONE.md (and the FS_CAP of 8 if it grew)")
        doc = (ROOT / "docs" / "CLEAN_CLONE.md").read_text(encoding="utf-8")
        self.assertIn("**4** filesystem-case skips on Linux", doc)
        self.assertIn("TMPDIR", doc)                                   # the real cause is recorded
        self.assertNotIn("dashboard tests were since changed", doc)     # the false cause is gone
        self.assertNotIn("only 1 remains", doc)

    def test_docs_disclose_the_optional_developer_tool_skip_category_and_the_steps_it_broke(self):
        """The third SR-15 FAIL. The documented steps failed on a machine with no `ruff` and the documents said
        nothing about it, because the defect was invisible on every machine that had it. A reader of
        CLEAN_CLONE.md must be able to find: that the category exists, what its cap and token are, that it is
        excluded from the baseline in GENERATION (which is what keeps the committed skip column
        machine-independent), that nothing in the kit installs `ruff`, and what a skip there costs."""
        # the doc is hard-wrapped AND list-indented, so a needle must survive both: collapse all runs of
        # whitespace rather than only newlines (matching on "\n" -> " " alone leaves the list indent behind)
        doc = re.sub(r"\s+", " ", (ROOT / "docs" / "CLEAN_CLONE.md").read_text(encoding="utf-8"))
        for needle in ("optional developer tool", "is not on PATH", "POLICY:TOOL_CAP", "at most 4",
                       "nothing in this kit installs it", "generation as well as comparison",
                       "cannot launder", "is not measured"):
            self.assertIn(needle, doc, f"docs/CLEAN_CLONE.md must disclose: {needle}")
        # The old, wrong reason may appear only as history. Checked over a three-line window because the document
        # is hard-wrapped and because one occurrence is a quoted runner transcript whose own line is just the
        # `:: '<reason>'` continuation -- the marker ("FAIL:") is two lines above it.
        lines = (ROOT / "docs" / "CLEAN_CLONE.md").read_text(encoding="utf-8").splitlines()
        hits = 0
        for i, line in enumerate(lines):
            if "ruff is not installed (optional linter)" in line:
                hits += 1
                window = " ".join(lines[max(0, i - 2):i + 1])
                self.assertRegex(window, r"used to|before|FAIL|carried",
                                 f"docs/CLEAN_CLONE.md:{i + 1} restates the reason that caused the FAIL as if it "
                                 f"were current")
        self.assertGreaterEqual(hits, 2, "the record of the reason that failed has been deleted rather than "
                                         "marked as history")
        # README carries the one-line precondition and must not promise what the kit does not install
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertNotIn("ruff is not installed (optional linter)", readme)

    def test_docs_disclose_the_lint_names_closed_without_being_scored(self):
        """Closed cheaply, and the document must not read as if that made the blocklist complete: the three names
        are listed as what they are (one demonstrated form each), and the CLASS behind the first of them is
        listed as still open."""
        doc = re.sub(r"\s+", " ", (ROOT / "docs" / "CLEAN_CLONE.md").read_text(encoding="utf-8"))
        for needle in ("get_type_hints", "getattr_static", "breakpointhook", "breakpoint()",
                       "String annotations", "is not an enumeration of everything that still passes"):
            self.assertIn(needle, doc, f"docs/CLEAN_CLONE.md must disclose: {needle}")
        lint = LINT.read_text(encoding="utf-8")
        for name in ("get_type_hints", "getattr_static", "breakpointhook"):
            self.assertIn(f'"{name}"', lint, f"scripts/lint.sh no longer names {name}")
        self.assertIn('"breakpoint"', lint)

    def test_docs_describe_the_lint_check_as_an_incomplete_blocklist(self):
        """F5: the "Not covered" list named only getattr-style tricks, runtime-built names, things outside src/ and
        third-party packages -- and none of the nineteen plain static attribute calls that passed fell into any of
        those four buckets, so the enumeration implied they were covered."""
        doc = (ROOT / "docs" / "CLEAN_CLONE.md").read_text(encoding="utf-8")
        for needle in ("blocklist", "are tripwires", "pkgutil.resolve_name", "Still not covered",
                       "positive standard-library-only check", "not evidence that `src/` cannot execute code"):
            self.assertIn(needle, doc.replace("\n", " "), needle)   # doc is hard-wrapped; match across wraps

    def test_docs_state_the_baseline_slack_policy(self):
        """F4: the baseline was presented as "the sharp check" with no mention that it is a floor, that it goes
        stale the moment a test is added, or that the stale gap is exactly the deletable surface."""
        doc = (ROOT / "docs" / "CLEAN_CLONE.md").read_text(encoding="utf-8")
        for needle in ("is a FLOOR", "goes stale", "deletable surface", "sharp only immediately after"):
            self.assertIn(needle, doc, needle)

    def test_docs_steps_state_the_bare_environment_precondition(self):
        """F6: the documented sequence `./scripts/run_tests.sh --expect none --twice` fails with 8 policy failures
        on any machine where torch/numpy/pytest/PyYAML are importable, and the bare-environment requirement
        appeared only parenthetically inside a table cell, never in the Steps."""
        doc = (ROOT / "docs" / "CLEAN_CLONE.md").read_text(encoding="utf-8")
        steps = doc.split("## Steps", 1)[1].split("\n## ", 1)[0]
        for needle in ("--without-pip", "--expect any", "asserts", "--expect none", "--expect torch"):
            self.assertIn(needle, steps, f"Steps section does not mention {needle}")

    def test_every_directory_pruned_from_the_bytecode_sweep_is_git_ignored(self):
        """D2 of the fourth SR-15 FAIL. The Steps told the reader that "only `.venv`/`venv` are pruned from the
        bytecode sweep and **ignored by git**" -- and `.gitignore` carried `.venv/` alone, while
        `scripts/run_tests.sh` prunes `.venv`, `venv` and `node_modules`. Measured with `git check-ignore`
        before the fix:

            IGNORED  .venv/pyvenv.cfg      NOT IGNORED  venv/pyvenv.cfg      NOT IGNORED  venv/bin/python3

        Half of the stated protection was absent, in the direction the sentence exists to warn about: the Steps
        tell the reader to create a venv, name `venv` as one of the two safe names, and a reader who used it got
        an untracked-but-not-ignored interpreter tree in `git status`.

        STRUCTURAL, and says so: it compares `.gitignore`'s patterns against the prune list PARSED OUT OF the
        script, so the two cannot drift apart again (a directory the sweep learns to skip is a directory git must
        ignore -- that equivalence is the whole content of the sentence). It does not run git, deliberately:
        gating it on `shutil.which("git")` would add a second optional-developer-tool skip category member and
        another machine-dependent figure to the documented counts, to re-measure what `<dir>/` in a `.gitignore`
        means.
        """
        script = (SCRIPTS / "run_tests.sh").read_text(encoding="utf-8")
        body = re.search(r"(?ms)^clear_bytecode\(\) \{(.*?)^\}", script)
        self.assertIsNotNone(body, "scripts/run_tests.sh no longer defines clear_bytecode() as a plain function; "
                                   "this test parses its prune list")
        groups = re.findall(r"\\\((.*?)\\\) -prune", body.group(1), re.S)
        pruned = {t for g in groups for t in re.findall(r"-name ([\w.*-]+)", g)} - {".git"}
        self.assertLessEqual({".venv", "venv"}, pruned, sorted(pruned))      # not vacuous if the parse degrades
        patterns = {l.strip().rstrip("/") for l in (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
                    if l.strip() and not l.lstrip().startswith("#")}
        self.assertEqual(sorted(d for d in pruned if d.rstrip("/") not in patterns), [],
                         f"scripts/run_tests.sh prunes these directories from the bytecode sweep and .gitignore "
                         f"does not ignore them, while docs/CLEAN_CLONE.md tells the reader both are true: "
                         f"{sorted(pruned)} vs {sorted(patterns)}")
        # ...and the sentence in the Steps that made the claim must still name both, or it has stopped being the
        # thing this test keeps true
        steps = (ROOT / "docs" / "CLEAN_CLONE.md").read_text(encoding="utf-8").split("## Steps", 1)[1].split("\n## ", 1)[0]
        self.assertIn("ignored by git", re.sub(r"\s+", " ", steps))

    def test_socket_guard_blocks_connections(self):
        """The guard run_tests.sh installs must make connection attempts fail (checked in a child process).
        The target is a closed LOOPBACK port: if a future edit broke the patch, this snippet would really
        connect, and it must not be able to leave the host when it does."""
        code = _guard_source() + "\ntry:\n    _s.create_connection(('127.0.0.1', 1), timeout=1)\nexcept OSError as e:\n    print('BLOCKED', e)\n"
        r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=30)
        self.assertIn("BLOCKED", r.stdout, r.stderr)


class TestNetworkGuardSurfaceAndDisclosure(unittest.TestCase):
    """D3/D4/D5. Three separate defects with one cause: the guard's patch list, the list of connection targets
    and the prose describing both were maintained by hand in four places.

    D3: `socket.gethostbyaddr` and `socket.getfqdn` were neither patched nor disclosed, and `gethostbyaddr` of a
    non-local address issues a reverse-DNS query that leaves the host. That was the third round of patching the
    names a reviewer happened to test instead of the family, so the patch list is now data in the script and
    this class enumerates the family from the live `socket` module against it.

    D4: docs/CLEAN_CLONE.md said "the five patched socket-module functions" while its own list, and the script,
    had seven. The documentation now points at the tuples instead of counting them.

    D5: every connection target in the runner and in this file was 192.0.2.1 (TEST-NET-1), which is unroutable
    by convention and not by the kernel -- `route -n get 192.0.2.1` on this host returns a real gateway and
    interface. The negative controls run with the guard deliberately off, so those were real outbound SYNs on
    every run of the suite, while the docs said "no network access at test time".
    """

    DOC = ROOT / "docs" / "CLEAN_CLONE.md"
    # socket's connection + name-resolution surface, enumerated from the LIVE module so that a name added by a
    # future Python (gethostbyname2, say) is caught rather than quietly joining the gap.
    MODULE_FAMILY = re.compile(r"^(get(?:addrinfo|fqdn|host\w*|name\w*|serv\w*|proto\w*)"
                               r"|create_connection|create_server)$")
    SOCKET_FAMILY = re.compile(r"^(connect\w*|bind|listen|accept\w*|send\w*)$")

    def test_every_family_member_is_either_patched_or_disclosed(self):
        # `import socket` would be rejected by scripts/lint.sh in tests/ as well as src/ (it is in BANNED);
        # the file's established idiom for a module it must reach anyway is __import__, as with importlib.util.
        socket = __import__("socket")
        fam_mod = {n for n in dir(socket) if self.MODULE_FAMILY.match(n) and callable(getattr(socket, n, None))}
        fam_sock = {n for n in dir(socket.socket)
                    if self.SOCKET_FAMILY.match(n) and callable(getattr(socket.socket, n, None))}
        # not vacuous: if the regexes stopped matching, the whole check would pass by matching nothing
        self.assertGreaterEqual(len(fam_mod), 12, sorted(fam_mod))
        self.assertGreaterEqual(len(fam_sock), 10, sorted(fam_sock))
        # ...and the floors are backed BY NAME, because BOTH are met EXACTLY on macOS (12 and 10): a family that
        # shrank by one would slip under them silently, and the floor is the only thing standing between a broken
        # regex and a vacuous pass. `PATCHED_MODULE <= fam_mod` / `PATCHED_SOCKET <= fam_sock` already pin the 8
        # patched functions and 6 patched methods; these are the other 4 and 4, which are disclosed rather than
        # patched and so were pinned by the count alone. (The METHOD side was given this treatment one round
        # before the MODULE side, which is the asymmetry this line removes: `getservbyname|getprotobyname` are
        # matched by `serv\w*|proto\w*` in MODULE_FAMILY, and deleting either alternative dropped fam_mod to 10
        # or 11 while every other assertion here still passed.)
        self.assertLessEqual({"accept", "send", "sendall", "sendfile"}, fam_sock, sorted(fam_sock))
        self.assertLessEqual({"gethostname", "getservbyname", "getservbyport", "getprotobyname"}, fam_mod,
                             sorted(fam_mod))
        self.assertLessEqual(PATCHED_MODULE, fam_mod, "a patched name is outside the enumerated family")
        self.assertLessEqual(PATCHED_SOCKET, fam_sock, "a patched method is outside the enumerated family")
        unaccounted = sorted((fam_mod | fam_sock) - PATCHED_MODULE - PATCHED_SOCKET - GUARD_DISCLOSED)
        self.assertEqual(unaccounted, [], "socket entry point neither patched by scripts/run_tests.sh nor named "
                                          "in its _NOT_BLOCKED disclosure list: patch it or disclose it")
        # and the disclosure is not a dumping ground: nothing may be in both lists
        self.assertEqual(sorted(GUARD_DISCLOSED & (PATCHED_MODULE | PATCHED_SOCKET)), [])
        for n in ("gethostbyaddr", "getfqdn"):          # the two D3 names, now really in the patch set
            self.assertIn(n, PATCHED_MODULE, n)
        # LINUX-ONLY member, disclosed rather than patched. `socket.socket.sendmsg_afalg` exists only on Linux
        # (typeshed declares it under `if sys.platform == "linux"`), `socket.socket.__mro__` includes
        # `_socket.socket` so `dir()` sees it there, and `send\\w*` matches it -- so on Linux, and ONLY on Linux,
        # it joined `fam_sock` in neither patch tuple nor the disclosure and `unaccounted` was
        # `['sendmsg_afalg']`. That is why this assertion is unconditional while the name is platform-specific:
        # the enumeration is deliberately NOT platform-aware (enumerating from the live module is the mechanism
        # that stopped this guard being patched one reviewer-tested name at a time), so the DISCLOSURE has to
        # cover names this host cannot see. It is disclosed because AF_ALG is the kernel crypto socket family --
        # addresses are algorithm names, not host/port pairs, and the only correspondent is the local kernel --
        # and patching it would mean setattr-ing onto socket.socket a name that does not exist on macOS, which
        # would then be a _BLOCK_SOCKET member outside the live family and fail the assertion above.
        self.assertIn("sendmsg_afalg", GUARD_DISCLOSED,
                      "socket.socket.sendmsg_afalg (Linux only) must stay disclosed in _NOT_BLOCKED: on Linux it "
                      "is matched by SOCKET_FAMILY and would otherwise be unaccounted for")
        if hasattr(socket.socket, "sendmsg_afalg"):      # true on Linux, false on this host
            self.assertIn("sendmsg_afalg", fam_sock, "SOCKET_FAMILY no longer matches a live family member")

    def test_the_documentation_names_every_disclosed_unpatched_entry_point(self):
        """D4's remaining half. The document is told not to restate the PATCHED list and does not -- but it does
        spell out the `_NOT_BLOCKED` names in its known-bypass section, and nothing checked that copy, so it could
        go stale exactly the way the patched list did (it said "five" for seven). Adding `sendmsg_afalg` to the
        tuple without documenting it would now fail here."""
        doc = self.DOC.read_text(encoding="utf-8").replace("\n", " ")
        for n in sorted(GUARD_DISCLOSED):
            self.assertIn(n, doc, f"docs/CLEAN_CLONE.md does not name the disclosed-unpatched entry point {n}; "
                                  f"the known-bypass list it gives readers is incomplete")

    def test_every_patched_entry_point_has_a_driving_call(self):
        """The guard and the drive table cannot diverge: this is what "do not just add two more names" means."""
        self.assertEqual(set(GUARD_CALLS), set(PATCHED_MODULE) | {f"socket.{n}" for n in PATCHED_SOCKET})

    def test_the_documentation_derives_the_list_instead_of_restating_it(self):
        """D4: "five patched socket-module functions" against the same document's list of seven, three lines
        apart. A number that has to be kept in step by hand is the defect, so there is no number any more."""
        doc = self.DOC.read_text(encoding="utf-8")
        script = (SCRIPTS / "run_tests.sh").read_text(encoding="utf-8")
        for ident in ("_BLOCK_MODULE", "_BLOCK_SOCKET", "_NOT_BLOCKED"):
            self.assertIn(ident, script, ident)
            self.assertIn(ident, doc, f"docs/CLEAN_CLONE.md must point at {ident} rather than restate it")
        self.assertNotRegex(doc.replace("\n", " "),
                            r"(?i)\b(two|three|four|five|six|seven|eight|nine|ten|\d+)\s+patched\b")

    def test_no_executed_connection_target_in_the_suite_is_non_loopback(self):
        """D5(a). Scans what the runner and the tests EXECUTE (code lines / non-docstring string literals), so
        the record of the 192.0.2.1 defect can stay in the comments where it belongs. A mutant that puts the old
        address back into GUARD_CALLS or into the runner's canary fails here."""
        quad = re.compile(r"\b(\d{1,3}(?:\.\d{1,3}){3})\b")
        # the (host, port) tuple form, which is what every socket call takes -- so sqlite3.connect(':memory:')
        # and other same-named calls on non-sockets are not swept up
        addr = re.compile(r"""(?:create_connection|create_server|\.connect|\.connect_ex)\(\s*\(\s*['"]([^'"]+)['"]""")
        targets, bad = 0, set()
        for p in [SCRIPTS / "run_tests.sh", SCRIPTS / "lint.sh", Path(__file__)] + \
                 sorted((ROOT / "tests").rglob("test_*.py")):
            for lineno, s in _code_string_literals(p):
                for ip in quad.findall(s):
                    targets += 1
                    if not ip.startswith("127."):
                        bad.add(f"{p.name}:{lineno}: {ip}")
                for host in addr.findall(s):
                    targets += 1
                    if host not in ("127.0.0.1", "localhost"):
                        bad.add(f"{p.name}:{lineno}: host {host!r}")
        self.assertEqual(sorted(bad), [], "non-loopback connection target in the offline suite: the negative "
                                          "controls run with the guard DISABLED, so such a target really "
                                          "leaves the host")
        self.assertGreaterEqual(targets, 10, "the scan found almost nothing: it has stopped looking")

    def test_docs_and_ci_do_not_claim_the_suite_attempts_no_connection(self):
        """D5(b). Both documents made an unqualified claim that the measured behaviour contradicted:
        "no network access at test time" and "EVERY test step runs under a socket guard ... that makes ANY
        connection attempt fail". Understating this is worse than the defect, so the claim is now the narrower
        true one: the attempts exist, they are loopback-only, and the documents say which tests make them."""
        doc = self.DOC.read_text(encoding="utf-8")
        ci = CI.read_text(encoding="utf-8")
        # The claim must be gone from the summary a reader takes it from, and anywhere it still appears it must
        # be marked as retracted rather than restated as current.
        self.assertNotIn("no network access at test time", doc.split("## Steps", 1)[0])
        for line in doc.splitlines():
            if "no network access at test" in line:
                self.assertRegex(line, r"used to say|this document said",
                                 "the retracted claim is restated as if it were current")
        self.assertNotIn("makes any connection attempt fail", ci.lower())
        self.assertNotIn("any connection attempt", ci.lower())
        for needle in ("loopback", "--no-network-guard", "no packet reaches a network interface"):
            self.assertIn(needle, doc.replace("\n", " "), f"docs/CLEAN_CLONE.md must disclose: {needle}")
        for needle in ("loopback", "--no-network-guard"):
            self.assertIn(needle, ci, f".github/workflows/ci.yml must disclose: {needle}")

    def test_docs_disclose_the_transitive_dependency_pins_and_the_determinism_redundancy(self):
        """Two corrections to the record that were not overclaims but were undisclosed: nothing pinned the
        transitive dependencies (no --require-hashes), and the determinism comparison has FOUR individually
        unpinned terms (RAN, SKIPPED, BAD, UT_RC), not one."""
        doc = self.DOC.read_text(encoding="utf-8").replace("\n", " ")
        for needle in ("--require-hashes", "transitive"):
            self.assertIn(needle, doc, needle)
        if "individually unpinned" in doc:
            self.assertRegex(doc, r"four\s+(?:of\s+)?(?:its\s+)?(?:terms|redundan)")


# ======================================================================================================
# Behavioural tests of the scripts' POLICY, driven with synthetic suites / synthetic source trees.
# These exist because a happy-path-only test lets every threshold, check and exit code be mutated unnoticed.
# ======================================================================================================
import shutil
import tempfile
import textwrap

RUN_TESTS = SCRIPTS / "run_tests.sh"
LINT = SCRIPTS / "lint.sh"
NONE_REASONS = ("torch not installed; torch tensor tests skipped", "numpy not installed (optional)")


def _skip_module(n, reason, cls="S", prefix="test_s"):
    return (f"import unittest\nclass {cls}(unittest.TestCase):\n    pass\n"
            f"for _i in range({n}):\n"
            f"    setattr({cls}, '{prefix}%d' % _i, unittest.skip({reason!r})(lambda self: None))\n")


def _pass_module(n, cls="P", prefix="test_p"):
    return (f"import unittest\nclass {cls}(unittest.TestCase):\n    pass\n"
            f"for _i in range({n}):\n    setattr({cls}, '{prefix}%d' % _i, lambda self: None)\n")


def _mixed_none(n):
    """n skips, alternating torch / numpy reasons (all valid for --expect none)."""
    return "\n".join(_skip_module(1, NONE_REASONS[i % 2], cls=f"C{i}", prefix="test_k").replace("import unittest\n", "")
                     for i in range(n)).join(["import unittest\n", ""]) if n else "import unittest\n"


class _SyntheticBase(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory(prefix="saferf_synth_")
        self.addCleanup(self._td.cleanup)
        self.dir = Path(self._td.name)
        self.shim = self.dir / "bin"
        self.shim.mkdir()
        (self.shim / "python3").symlink_to(sys.executable)   # script must use THIS interpreter

    def suite(self, files):
        d = self.dir / "suite"
        d.mkdir(exist_ok=True)
        for name, body in files.items():
            (d / name).write_text(body, encoding="utf-8")
        return d

    def rt(self, files, *args, expect="any", env=None, baseline="none", pytest=False, suite_dir=None):
        d = suite_dir or self.suite(files)
        e = _env(PATH=f"{self.shim}:{os.environ.get('PATH', '')}", MIN_TESTS="1", MIN_NONE_SKIPS="50")
        for k in ("PYTHONHASHSEED", "PYTHONPATH", "PYTHONDONTWRITEBYTECODE"):   # the SCRIPT must set these
            e.pop(k, None)
        e.update(env or {})
        cmd = [str(RUN_TESTS), "--expect", expect, "--tests-dir", str(d), "--baseline", baseline, *args]
        if not pytest:
            cmd.append("--no-pytest")
        return subprocess.run(cmd, capture_output=True, text=True, env=e, cwd=ROOT, timeout=180)

    def synth_root(self, test_body, files=None):
        """A throwaway repo root holding a COPY of the LIVE run_tests.sh, so the DEFAULT (no --tests-dir) code path
        can be driven without running the real ~900-test suite. The script derives ROOT from its own location, so
        the copy treats this directory as "the repo": its whole-tree bytecode clearing happens in here only."""
        root = self.dir / "synthroot"
        (root / "scripts").mkdir(parents=True)
        (root / "tests").mkdir()
        shutil.copy2(RUN_TESTS, root / "scripts" / "run_tests.sh")      # copy2 keeps the executable bit
        (root / "tests" / "test_a.py").write_text(test_body, encoding="utf-8")
        for rel, body in (files or {}).items():
            p = root / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(body) if isinstance(body, bytes) else p.write_text(body, encoding="utf-8")
        return root

    def run_default(self, root, *args, cwd=None, env=None):
        """Run the copied script with NO --tests-dir: that is the DEFAULT, unscoped code path (SCOPED=0)."""
        e = _env(PATH=f"{self.shim}:{os.environ.get('PATH', '')}", MIN_TESTS="1")
        for k in ("PYTHONHASHSEED", "PYTHONPATH", "PYTHONDONTWRITEBYTECODE"):   # the SCRIPT must set these
            e.pop(k, None)
        e.update(env or {})
        return subprocess.run([str(root / "scripts" / "run_tests.sh"), "--baseline", "none", "--no-pytest", *args],
                              capture_output=True, text=True, env=e, cwd=str(cwd or root), timeout=180)

    def ok(self, r):
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("RESULT: OK", r.stdout)

    def bad(self, r, needle=None):
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("RESULT: FAIL", r.stdout + r.stderr)
        if needle:
            self.assertIn(needle, r.stdout + r.stderr)


class TestRunTestsSkipPolicyNone(_SyntheticBase):
    def test_exactly_50_valid_skips_pass(self):
        self.ok(self.rt({"test_a.py": _mixed_none(50)}, expect="none"))

    def test_49_skips_fail_at_the_floor(self):
        self.bad(self.rt({"test_a.py": _mixed_none(49)}, expect="none"), "POLICY:MIN_NONE_SKIPS")

    def test_floor_is_configurable_and_not_off_by_one(self):
        self.ok(self.rt({"test_a.py": _mixed_none(5)}, expect="none", env={"MIN_NONE_SKIPS": "5"}))
        self.bad(self.rt({"test_a.py": _mixed_none(4)}, expect="none", env={"MIN_NONE_SKIPS": "5"}))

    def test_every_skip_must_have_a_valid_reason_not_just_two(self):
        files = {"test_a.py": _mixed_none(48), "test_b.py": _skip_module(2, "meh installed", cls="M", prefix="test_m")}
        self.bad(self.rt(files, expect="none"), "POLICY:NONE_REASON")

    def test_reason_case_is_ignored(self):
        files = {"test_a.py": _mixed_none(49), "test_b.py": _skip_module(1, "Torch Not Installed", cls="U", prefix="test_u")}
        self.ok(self.rt(files, expect="none"))

    def test_empty_reason_fails(self):
        files = {"test_a.py": _mixed_none(50), "test_b.py": _skip_module(1, "", cls="E", prefix="test_e")}
        self.bad(self.rt(files, expect="none"), "POLICY:EMPTY_REASON")

    def test_torch_present_reason_fails_in_none_mode(self):
        files = {"test_a.py": _mixed_none(50), "test_b.py": _skip_module(1, "torch present; torch not installed", cls="T", prefix="test_t")}
        self.bad(self.rt(files, expect="none"), "POLICY:TORCH_PRESENT")

    def test_all_torch_no_numpy_reason_fails(self):
        self.bad(self.rt({"test_a.py": _skip_module(50, NONE_REASONS[0])}, expect="none"), "POLICY:NO_NUMPY_REASON")

    def test_all_numpy_no_torch_reason_fails(self):
        self.bad(self.rt({"test_a.py": _skip_module(50, NONE_REASONS[1])}, expect="none"), "POLICY:NO_TORCH_REASON")

    def test_silent_passes_instead_of_skips_fail(self):
        self.bad(self.rt({"test_a.py": _pass_module(60)}, expect="none"), "POLICY:MIN_NONE_SKIPS")


class TestRunTestsSkipPolicyTorch(_SyntheticBase):
    def test_12_device_skips_pass_and_13_fail(self):
        self.ok(self.rt({"test_a.py": _skip_module(12, "CUDA not available: comparison is UNKNOWN")}, expect="torch"))
        self.bad(self.rt({"test_a.py": _skip_module(13, "CUDA not available: comparison is UNKNOWN")}, expect="torch"), "POLICY:TORCH_CAP")

    def test_allowed_reasons_pass(self):
        files = {"test_a.py": _skip_module(1, "MPS not available (or probe op failed)", cls="A", prefix="test_a"),
                 "test_b.py": _skip_module(1, "torch present; unavailable path is exercised in the subprocess test", cls="B", prefix="test_b")}
        self.ok(self.rt(files, expect="torch"))

    def test_missing_wording_variants_all_fail(self):
        for reason in ("torch is missing", "Torch Not Installed", "numpy not installed (optional)", "CUDA missing",
                       "torch not installed; CUDA not available"):
            with self.subTest(reason=reason):
                self.bad(self.rt({"test_a.py": _skip_module(1, reason)}, expect="torch"), "POLICY:TORCH_MODE_MISSING")

    def test_unexplained_reason_fails(self):
        for reason in ("meh", "torch unavailable", ""):
            with self.subTest(reason=reason):
                self.bad(self.rt({"test_a.py": _skip_module(1, reason)}, expect="torch"))

    def test_zero_skips_pass_in_torch_mode(self):
        self.ok(self.rt({"test_a.py": _pass_module(3)}, expect="torch"))


class TestRunTestsFloorsAndBaseline(_SyntheticBase):
    def test_min_tests_boundary(self):
        self.ok(self.rt({"test_a.py": _pass_module(5)}, env={"MIN_TESTS": "5"}))
        self.bad(self.rt({"test_a.py": _pass_module(4)}, env={"MIN_TESTS": "5"}), "POLICY:MIN_TESTS")

    def test_default_floor_is_650_inclusive(self):
        self.ok(self._default_floor(650))
        self.bad(self._default_floor(649), "POLICY:MIN_TESTS")

    def _default_floor(self, n):
        d = self.suite({"test_a.py": _pass_module(n)})
        e = _env(PATH=f"{self.shim}:{os.environ.get('PATH', '')}")
        for k in ("PYTHONHASHSEED", "PYTHONPATH", "MIN_TESTS"):
            e.pop(k, None)
        return subprocess.run([str(RUN_TESTS), "--tests-dir", str(d), "--baseline", "none", "--no-pytest"],
                              capture_output=True, text=True, env=e, cwd=ROOT, timeout=180)

    def _baseline(self, text):
        p = self.dir / "baseline.txt"
        p.write_text(text, encoding="utf-8")
        return str(p)

    def _suite3(self, skipped, total=5):
        body = _mixed_none(skipped)
        if total > skipped:
            body += _pass_module(total - skipped, cls="H", prefix="test_h").replace("import unittest\n", "")
        return body

    def test_baseline_matching_passes(self):
        b = self._baseline("test_a 5 3\n")
        self.ok(self.rt({"test_a.py": self._suite3(3)}, expect="none", baseline=b, env={"MIN_NONE_SKIPS": "1"}))

    def test_deleted_tests_fail_by_module_name(self):
        b = self._baseline("test_a 5 3\n")
        r = self.rt({"test_a.py": self._suite3(3, total=4)}, expect="none", baseline=b, env={"MIN_NONE_SKIPS": "1"})
        self.bad(r, "POLICY:BASELINE_TESTS baseline: module test_a ran 4 tests, baseline 5")

    def test_deleted_module_fails(self):
        b = self._baseline("test_a 5 3\ntest_gone 2 0\n")
        r = self.rt({"test_a.py": self._suite3(3)}, expect="none", baseline=b, env={"MIN_NONE_SKIPS": "1"})
        self.bad(r, "POLICY:BASELINE_TESTS baseline: module test_gone ran 0")

    def test_guarded_tests_turned_into_silent_passes_fail(self):
        b = self._baseline("test_a 5 3\n")
        r = self.rt({"test_a.py": self._suite3(2)}, expect="none", baseline=b, env={"MIN_NONE_SKIPS": "1"})
        self.bad(r, "POLICY:BASELINE_SKIPS baseline: module test_a has 2 bare-environment skips, baseline 3")

    def test_baseline_skip_floor_not_applied_with_torch(self):
        b = self._baseline("test_a 5 3\n")
        self.ok(self.rt({"test_a.py": self._suite3(0)}, expect="torch", baseline=b))

    def test_more_tests_than_baseline_is_fine(self):
        b = self._baseline("test_a 5 3\n")
        self.ok(self.rt({"test_a.py": self._suite3(3, total=9)}, expect="none", baseline=b, env={"MIN_NONE_SKIPS": "1"}))

    def test_update_baseline_writes_counts_and_requires_none_mode(self):
        b = self.dir / "new_baseline.txt"
        r = self.rt({"test_a.py": self._suite3(3)}, "--update-baseline", expect="none", baseline=str(b), env={"MIN_NONE_SKIPS": "1"})
        self.ok(r)
        self.assertIn("test_a 5 3", b.read_text(encoding="utf-8").splitlines())
        r2 = self.rt({"test_a.py": self._suite3(3)}, "--update-baseline", expect="torch", baseline=str(b))
        self.assertEqual(r2.returncode, 2)

    def test_update_baseline_refuses_a_failing_run_and_leaves_the_file_untouched(self):
        """`--update-baseline` used to write unconditionally. It did: a real 14-minute bare run went
        red with three false failures (a module read mid-edit by another process) and the baseline
        was rewritten from that red run anyway. A baseline recorded from a red or mid-refactor tree
        encodes whatever was broken at that moment as the permanent floor -- the exact defect the
        per-module baseline exists to catch. The run's own non-zero exit is no protection, because
        the write happened before the exit code was decided."""
        b = self.dir / "refuse_baseline.txt"
        b.write_text("test_a 5 3\n", encoding="utf-8")   # pre-existing content that must SURVIVE
        before = b.read_text(encoding="utf-8")
        failing = ("import unittest\nclass F(unittest.TestCase):\n"
                   "    def test_boom(self):\n        self.fail('deliberate')\n")
        r = self.rt({"test_a.py": self._suite3(3) + "\n" + failing}, "--update-baseline",
                    expect="none", baseline=str(b), env={"MIN_NONE_SKIPS": "1"})
        self.bad(r, "POLICY:BASELINE_REFUSED")
        self.assertIn("baseline is UNCHANGED", r.stdout)
        self.assertIn("did not end in OK", r.stdout)
        # the file is byte-identical: not rewritten, not truncated, not deleted
        self.assertEqual(b.read_text(encoding="utf-8"), before)
        self.assertNotIn("baseline written", r.stdout)
        # and the refusal does not ALSO emit comparison failures, which would bury the real cause
        self.assertNotIn("POLICY:BASELINE_TESTS", r.stdout)
        self.assertNotIn("POLICY:BASELINE_SKIPS", r.stdout)

    def test_update_baseline_refuses_when_only_the_skip_policy_fails(self):
        """The other half: the tests can all pass while the skip policy fails. That is still not a
        tree to record a floor from, because a policy failure means the skip accounting itself is
        not trustworthy -- and the skip counts are half of what the baseline records."""
        b = self.dir / "refuse_baseline2.txt"
        b.write_text("test_a 5 3\n", encoding="utf-8")
        before = b.read_text(encoding="utf-8")
        # all green, but an unexplained skip reason trips POLICY:NONE_REASON
        bad_reason = ("import unittest\nclass U(unittest.TestCase):\n"
                      "    @unittest.skip('just because')\n    def test_u(self):\n        pass\n")
        r = self.rt({"test_a.py": self._suite3(3) + "\n" + bad_reason}, "--update-baseline",
                    expect="none", baseline=str(b), env={"MIN_NONE_SKIPS": "1"})
        self.bad(r, "POLICY:BASELINE_REFUSED")
        self.assertIn("skip-policy failure(s)", r.stdout)
        self.assertEqual(b.read_text(encoding="utf-8"), before)

    def test_update_baseline_with_baseline_none_is_a_usage_error(self):
        """D1. `none` is the sentinel that DISABLES the baseline. It was honoured in the comparison branch
        (`elif base != "none"`) and not in the update branch, which did an unconditional open(base, "w"), so

            ./scripts/run_tests.sh --expect none --tests-dir <synth> --baseline none --update-baseline
            baseline written: none (1 modules)
            $ ls -la none     ->  -rw-r--r--  224 bytes of real baseline content

        dropped a file literally named `none` into the repository root -- untracked, not in .gitignore -- for a
        user who had just asked for no baseline at all. In a kit whose demo.py carries an inode-identity guard
        specifically so it cannot write there.

        Part (a) drives a COPY of the live script in a throwaway root, so if the sentinel is not honoured the
        junk file lands there, where it is visible and harmless, instead of in the real repo. The suite is green
        in `none` mode, which is what the old code needed in order to reach the write at all.
        """
        root = self.synth_root(self._suite3(3))
        r = self.run_default(root, "--expect", "none", "--update-baseline", env={"MIN_NONE_SKIPS": "1"})
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertIn("--update-baseline requires a baseline FILE", r.stderr)
        self.assertFalse((root / "none").exists(), "a file named 'none' was written into the repo root")
        self.assertEqual(sorted(p.name for p in root.iterdir()), ["scripts", "tests"])
        self.assertNotIn("baseline written", r.stdout)
        # (b) the real script, in the real repository: same usage error, and the repo is untouched
        before = _listing()
        r2 = self.rt({"test_a.py": self._suite3(3)}, "--update-baseline", expect="none", baseline="none",
                     env={"MIN_NONE_SKIPS": "1"})
        self.assertEqual(r2.returncode, 2, r2.stdout + r2.stderr)
        self.assertFalse((ROOT / "none").exists())
        self.assertTrue(_same(before, _listing()), "the run changed files inside the repository")

    def test_update_baseline_is_refused_by_every_shell_side_policy_failure_too(self):
        """D2. The refusal consulted only the unittest log's ^OK/^FAILED lines and the Python stage's own `bad`
        list. POLICY:MIN_TESTS, SKIP_RECORD, PYTEST_FAILED, PYTEST_COLLECTED, PYTEST_SKIPPED and
        NONDETERMINISTIC are all decided in the SHELL and were invisible to it, so the in-code comment --
        "REFUSE to record a baseline from a run that is not clean ... a baseline captured from a red or
        mid-refactor tree silently encodes whatever was broken at that moment as the floor" -- was an overclaim.
        Measured before the fix:

            $ MIN_TESTS=1000 ./scripts/run_tests.sh --expect none --tests-dir <synth> \\
                             --baseline <file> --update-baseline
            FAIL: POLICY:MIN_TESTS only 5 tests ran (floor MIN_TESTS=1000)
            baseline written: /tmp/.../base.txt (1 modules)
            RESULT: FAIL

        The Python stage now STAGES the file and the shell moves it into place only once FAIL is still 0, so the
        predicate is the run's whole RESULT. Both arms below are shell-side and leave the unittest run green, so
        nothing but the staging split can stop them.
        """
        b = self.dir / "shell_side_baseline.txt"
        b.write_text("test_a 5 3\n", encoding="utf-8")        # must SURVIVE byte-identically
        before = b.read_text(encoding="utf-8")
        # (a) a global-floor failure: the tests pass, the skip policy passes, MIN_TESTS does not
        r = self.rt({"test_a.py": self._suite3(3)}, "--update-baseline", expect="none", baseline=str(b),
                    env={"MIN_NONE_SKIPS": "1", "MIN_TESTS": "1000"})
        self.bad(r, "POLICY:MIN_TESTS")
        self.assertIn("POLICY:BASELINE_REFUSED", r.stdout)
        self.assertIn("baseline is UNCHANGED", r.stdout)
        self.assertNotIn("baseline written", r.stdout)
        self.assertEqual(b.read_text(encoding="utf-8"), before)
        # (b) a determinism failure, which is decided after BOTH runs and after the pytest block
        state = self.dir / "flaky_flag"
        flaky = textwrap.dedent("""
            import os, unittest
            class V(unittest.TestCase):
                def test_flaky_reason(self):
                    p = os.environ["STATE"]
                    first = not os.path.exists(p)
                    open(p, "w").close()
                    self.skipTest("torch not installed; run A" if first else "torch not installed; run B")
        """)
        r2 = self.rt({"test_a.py": self._suite3(3), "test_v.py": flaky}, "--update-baseline", "--twice",
                     expect="none", baseline=str(b), env={"MIN_NONE_SKIPS": "1", "STATE": str(state)})
        self.bad(r2, "POLICY:NONDETERMINISTIC")
        self.assertIn("POLICY:BASELINE_REFUSED", r2.stdout)
        self.assertNotIn("baseline written", r2.stdout)
        self.assertEqual(b.read_text(encoding="utf-8"), before)
        # ...and the same shape of run, made clean, DOES write it: the refusal is not just always-on.
        # (test_v.py is overwritten rather than left behind: self.rt reuses one synthetic suite directory.)
        r3 = self.rt({"test_a.py": self._suite3(3), "test_v.py": _pass_module(1, cls="V", prefix="test_v")},
                     "--update-baseline", "--twice", expect="none", baseline=str(b),
                     env={"MIN_NONE_SKIPS": "1"})
        self.ok(r3)
        self.assertIn(f"baseline written: {b}", r3.stdout)
        self.assertIn("test_a 5 3", b.read_text(encoding="utf-8").splitlines())

    def test_baseline_path_that_is_a_directory_is_a_usage_error_and_drops_no_junk_in_the_repo(self):
        """D1, re-opened by the staging write. `run_tests.sh` ended `--update-baseline` with
        `mv "$TMP/base.staged" "$BASELINE"` and never checked that `$BASELINE` was a FILE. `mv file dir`
        SUCCEEDS -- it drops the file inside -- so:

            $ MIN_TESTS=1 MIN_NONE_SKIPS=1 ./scripts/run_tests.sh --expect none \\
                  --tests-dir <synth> --baseline scripts --update-baseline
            baseline staged for .../scripts (1 modules); it is written only if this run ends RESULT: OK
            baseline written: .../scripts ( modules)
            RESULT: OK      exit=0
            $ git status --porcelain  ->  ?? scripts/base.staged      (untracked, not gitignored)

        Exactly the D1 shape: a user who asked for a baseline somewhere gets an untracked junk file INSIDE the
        repository, reported as RESULT: OK, in a kit whose demo.py carries an inode-identity guard precisely so
        that nothing can write there. The only hint was the empty `( modules)` -- `$(grep -cv '^#' "$BASELINE"
        || true)` run against a directory, with `|| true` swallowing grep's "Is a directory".

        The comparison branch was broken by the same input in a different way: `os.path.exists(base)` is true for
        a directory, so `open(base)` raised IsADirectoryError and the run died with a traceback and no POLICY
        token. Both are now one start-up usage error, checked before the suite runs so nobody waits for it.
        """
        before = _listing()
        r = self.rt({"test_a.py": self._suite3(3)}, "--update-baseline", expect="none", baseline="scripts",
                    env={"MIN_NONE_SKIPS": "1"})
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertIn("--baseline must be a FILE", r.stderr)
        self.assertNotIn("baseline written", r.stdout)
        self.assertNotIn("RESULT: OK", r.stdout)
        self.assertFalse((SCRIPTS / "base.staged").exists(), "the staged baseline was moved into scripts/")
        self.assertTrue(_same(before, _listing()), "the run changed files inside the repository")
        # the plain comparison run is rejected by the same check, instead of dying with IsADirectoryError
        r2 = self.rt({"test_a.py": _pass_module(2)}, baseline="scripts")
        self.assertEqual(r2.returncode, 2, r2.stdout + r2.stderr)
        self.assertIn("--baseline must be a FILE", r2.stderr)
        self.assertNotIn("IsADirectoryError", r2.stdout + r2.stderr)
        # ...and the same path as a FILE is of course still fine, so this is not a blanket refusal
        ok = self.dir / "dir_check_baseline.txt"
        self.ok(self.rt({"test_a.py": self._suite3(3)}, "--update-baseline", expect="none", baseline=str(ok),
                        env={"MIN_NONE_SKIPS": "1"}))

    def test_baseline_that_becomes_a_directory_during_the_run_is_POLICY_BASELINE_WRITE(self):
        """POLICY:BASELINE_WRITE was emitted by the script and asserted by NO test, and it is the branch the
        directory case slipped past. It is driven here by the one input the start-up check cannot see: a test in
        the suite creates the directory WHILE the run is in progress, which is the race the write-time guard
        exists for. Nothing may be written inside it, and the empty `( modules)` must be gone."""
        b = self.dir / "becomes_a_directory"
        sabotage = textwrap.dedent("""
            import os, unittest
            class W(unittest.TestCase):
                def test_make_the_baseline_path_a_directory_mid_run(self):
                    os.mkdir(os.environ["LATE_BASELINE"])   # the start-up check could not have seen this
                    self.assertTrue(os.path.isdir(os.environ["LATE_BASELINE"]))
        """)
        r = self.rt({"test_a.py": self._suite3(3), "test_w.py": sabotage}, "--update-baseline", expect="none",
                    baseline=str(b), env={"MIN_NONE_SKIPS": "1", "LATE_BASELINE": str(b)})
        self.bad(r, "POLICY:BASELINE_WRITE")
        self.assertIn("is a DIRECTORY", r.stdout)
        self.assertIn("baseline UNCHANGED", r.stdout)
        self.assertNotIn("baseline written", r.stdout)
        self.assertNotIn("( modules)", r.stdout)            # the empty count that hid this
        self.assertTrue(b.is_dir())
        self.assertEqual(sorted(p.name for p in b.iterdir()), [], "the staged baseline was moved INTO the directory")

    def test_the_written_baseline_line_carries_a_real_module_count(self):
        """The `( modules)` half. The count came from `$(grep -cv '^#' "$BASELINE" || true)` AFTER the move, so a
        failing grep printed nothing and `|| true` hid why; it is now counted from the staged file BEFORE the
        move, with an explicit 0 fallback. An empty or non-numeric count fails this."""
        b = self.dir / "count_baseline.txt"
        r = self.rt({"test_a.py": self._suite3(3)}, "--update-baseline", expect="none", baseline=str(b),
                    env={"MIN_NONE_SKIPS": "1"})
        self.ok(r)
        self.assertRegex(r.stdout, r"(?m)^baseline written: " + re.escape(str(b)) + r" \(1 modules\)$")

    def test_a_recorder_that_misses_a_started_test_is_POLICY_RECORDER(self):
        """POLICY:RECORDER was emitted and asserted by no test. The skip recorder is the whole evidential basis of
        the skip policy -- reasons are recorded by a hook inside the unittest process rather than scraped from
        output -- so "the recorder saw fewer tests than unittest ran" means every skip-reason verdict in the run
        was computed from an incomplete record. It must be a red run, not a quieter one.

        Driven by restoring a plain `TestResult.startTest` from inside the suite: unittest keeps counting the
        tests that follow, the hook no longer logs them, and `len(starts) < ran_log`. `test_a` sorts before
        `test_b`, so the unhook happens first.
        """
        unhook = textwrap.dedent("""
            import unittest
            class A(unittest.TestCase):
                def test_a_unhook_the_recorder(self):
                    def plain(self, test):      # counts, but does not log
                        self.testsRun += 1
                    unittest.TestResult.startTest = plain
        """)
        more = _pass_module(3, cls="B", prefix="test_b")
        r = self.rt({"test_a.py": unhook, "test_b.py": more})
        self.bad(r, "POLICY:RECORDER")
        self.assertIn("recorder saw 1 tests but unittest ran 4", r.stdout)
        self.assertNotIn("POLICY:SKIP_RECORD", r.stdout)        # this run drives RECORDER and nothing else
        # not blanket: the same two modules without the sabotage pass
        self.ok(self.rt({"test_a.py": _pass_module(1, cls="A", prefix="test_a"), "test_b.py": more}))

    def test_a_skip_the_recorder_did_not_see_is_POLICY_SKIP_RECORD(self):
        """POLICY:SKIP_RECORD was emitted and asserted by no test. It is the cross-check between the two
        independent counts of the same thing -- unittest's own `skipped=N` and the hook's log -- and it is what
        stops the skip policy from being judged on a short list. Driven the same way as RECORDER, by restoring a
        plain `TestResult.addSkip`: unittest still reports the skip, the hook no longer records it."""
        unhook = textwrap.dedent("""
            import unittest
            class A(unittest.TestCase):
                def test_a_unhook_the_skip_recorder(self):
                    def plain(self, test, reason):      # reported by unittest, not logged
                        self.skipped.append((test, reason))
                    unittest.TestResult.addSkip = plain
        """)
        skipper = _skip_module(2, "torch not installed", cls="B", prefix="test_b")
        r = self.rt({"test_a.py": unhook, "test_b.py": skipper})
        self.bad(r, "POLICY:SKIP_RECORD")
        self.assertIn("recorded skips (0) != reported skips (2)", r.stdout)
        self.assertNotIn("POLICY:RECORDER", r.stdout)           # this run drives SKIP_RECORD and nothing else
        self.ok(self.rt({"test_a.py": _pass_module(1, cls="A", prefix="test_a"), "test_b.py": skipper}))

    def test_repo_baseline_exists_and_covers_every_test_module(self):
        lines = [l.split() for l in (SCRIPTS / "test_baseline.txt").read_text(encoding="utf-8").splitlines()
                 if l.strip() and not l.startswith("#")]
        recorded = {l[0] for l in lines}
        on_disk = {"toy_tests." + p.stem for p in (ROOT / "tests" / "toy_tests").glob("test_*.py")} | \
                  {p.stem for p in (ROOT / "tests").glob("test_*.py")}
        self.assertTrue(on_disk <= recorded, f"modules missing from scripts/test_baseline.txt: {sorted(on_disk - recorded)}")
        self.assertTrue(all(int(l[1]) > 0 for l in lines))


class TestRunTestsMechanics(_SyntheticBase):
    def test_failing_test_fails_run(self):
        body = "import unittest\nclass T(unittest.TestCase):\n    def test_x(self):\n        self.assertEqual(1, 2)\n"
        self.bad(self.rt({"test_a.py": body}), "POLICY:UNITTEST_FAILED")

    def test_erroring_test_fails_run(self):
        body = "import unittest\nclass T(unittest.TestCase):\n    def test_x(self):\n        raise RuntimeError('boom')\n"
        self.bad(self.rt({"test_a.py": body}), "POLICY:UNITTEST_FAILED")

    def test_unimportable_module_fails_run(self):
        self.bad(self.rt({"test_a.py": "import definitely_not_a_module_xyz\n"}))

    def test_unknown_argument_and_bad_expect_are_usage_errors(self):
        self.assertEqual(self.rt({"test_a.py": _pass_module(1)}, "--bogus").returncode, 2)
        self.assertEqual(self.rt({"test_a.py": _pass_module(1)}, expect="sometimes").returncode, 2)

    def test_environment_is_pinned_inside_the_tests(self):
        body = textwrap.dedent("""
            import os, sys, unittest
            class T(unittest.TestCase):
                def test_env(self):
                    self.assertEqual(os.environ.get("PYTHONHASHSEED"), os.environ["WANT_SEED"])
                    self.assertEqual(os.environ.get("PYTHONDONTWRITEBYTECODE"), "1")
                    self.assertTrue(sys.dont_write_bytecode)
                    self.assertNotIn("SAFERF_SKIP_LOG", os.environ)
        """)
        self.ok(self.rt({"test_a.py": body}, env={"WANT_SEED": "0"}))
        self.ok(self.rt({"test_a.py": body}, env={"WANT_SEED": "7", "PYTHONHASHSEED": "7"}))
        self.bad(self.rt({"test_a.py": body}, env={"WANT_SEED": "99"}))   # proves the assertion can fail

    def test_stale_bytecode_is_cleared_and_none_is_left_behind(self):
        d = self.suite({"test_a.py": "import os, unittest\nclass T(unittest.TestCase):\n    def test_x(self):\n"
                                       "        self.assertFalse(os.path.exists(os.path.join(os.path.dirname(__file__), '__pycache__')))\n"})
        (d / "__pycache__").mkdir()
        (d / "__pycache__" / "stale.cpython-312.pyc").write_bytes(b"\0")
        self.ok(self.rt({}, suite_dir=d))
        self.assertFalse((d / "__pycache__").exists())

    def test_scoped_run_does_not_touch_bytecode_outside_its_tests_dir(self):
        """Regression: a nested run once wiped the REAL repo's __pycache__ mid-way through the outer run."""
        sentinel = ROOT / "tests" / "toy_tests" / "__pycache__" / "sr15_sentinel.cpython-312.pyc"
        sentinel.parent.mkdir(exist_ok=True)
        sentinel.write_bytes(b"\0")
        def _cleanup():
            if sentinel.exists():
                sentinel.unlink()
            try:
                sentinel.parent.rmdir()      # only if empty
            except OSError:
                pass
        self.addCleanup(_cleanup)
        outside = self.dir / "elsewhere" / "__pycache__"
        outside.mkdir(parents=True)
        (outside / "keep.pyc").write_bytes(b"\0")
        self.ok(self.rt({"test_a.py": _pass_module(1)}))
        self.assertTrue(sentinel.exists(), "scoped run deleted bytecode in the real repo")
        self.assertTrue((outside / "keep.pyc").exists(), "scoped run deleted bytecode outside its tests dir")

    def test_default_run_clears_bytecode_in_the_whole_tree_not_only_under_tests(self):
        """BEHAVIOURAL. This replaced a grep for `if [ "$SCOPED" = 0 ]; then` and `SCOPED=1`, which was vacuous:
        a mutant that inserts `SCOPED=1` immediately above the top-level clear_bytecode call keeps both literals,
        so the grep passed while the default run stopped clearing anything outside tests/ (canary survived:
        unmutated=False, mutant=True) -- and the two other bytecode tests passed too, because one drives the
        SCOPED path via --tests-dir and the other asserts only that the scoped path does NOT delete.

        Canaries are planted OUTSIDE tests/. They must be gone BEFORE the suite starts (the in-suite assertion,
        which also kills a mutant that only clears at the end) and still gone afterwards.
        """
        body = textwrap.dedent("""
            import os, unittest
            class T(unittest.TestCase):
                def test_canaries_were_cleared_before_the_suite_started(self):
                    for p in os.environ["SR15_CANARIES"].split(os.pathsep):
                        self.assertFalse(os.path.exists(p), "bytecode outside tests/ survived into the run: " + p)
        """)
        root = self.synth_root(body, files={"pkg/__pycache__/canary.cpython-312.pyc": b"\0",
                                            "pkg/sub/loose_canary.pyc": b"\0"})
        canaries = [root / "pkg" / "__pycache__", root / "pkg" / "sub" / "loose_canary.pyc"]
        self.assertTrue(all(p.exists() for p in canaries), "canaries were not planted")
        r = self.run_default(root, env={"SR15_CANARIES": os.pathsep.join(str(p) for p in canaries)})
        self.ok(r)
        for p in canaries:
            self.assertFalse(p.exists(), f"default run left bytecode outside tests/: {p}")

    def test_default_tests_dir_is_the_scripts_own_repo_from_any_cwd(self):
        """TESTS_DIR used to be resolved against $PWD *before* the cd to ROOT, so the documented
        `./scripts/run_tests.sh ...` died with `tests dir not found: <cwd>/tests` from any other directory. An
        explicit RELATIVE --tests-dir still means "relative to the caller's cwd"."""
        root = self.synth_root("import unittest\nclass T(unittest.TestCase):\n    def test_x(self): pass\n")
        r = self.run_default(root, cwd=self.dir)                       # deliberately NOT the synthetic repo root
        self.assertNotIn("tests dir not found", r.stdout + r.stderr)
        self.ok(r)
        self.assertIn("ran=1", r.stdout)
        r2 = self.run_default(root, "--tests-dir", "tests", cwd=root)  # explicit + relative -> caller's cwd
        self.ok(r2)
        r3 = self.run_default(root, "--tests-dir", "tests", cwd=self.dir)
        self.assertEqual(r3.returncode, 2, r3.stdout + r3.stderr)      # no ./tests under self.dir
        self.assertIn("tests dir not found", r3.stderr)

    def test_help_prints_the_whole_comment_header_including_the_network_section(self):
        """--help was `sed -n '2,42p'` while the header had grown to 53 lines, so the entire NETWORK paragraph --
        the one that says the guard is Python-level only and lists what it does not stop -- was silently cut off."""
        r = subprocess.run([str(RUN_TESTS), "--help"], capture_output=True, text=True, env=_env(), cwd=ROOT,
                           timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        for needle in ("--expect none", "--tests-dir", "PYTHONHASHSEED", "WHY bytecode caching is disabled",
                       "NETWORK", "PYTHON-LEVEL ONLY", "children (curl)", "docs/DIFF_EVIDENCE.md"):
            self.assertIn(needle, r.stdout, needle)
        header = []
        for line in RUN_TESTS.read_text(encoding="utf-8").splitlines()[1:]:   # skip the shebang
            if not line.startswith("#"):
                break
            header.append(line)
        self.assertEqual(r.stdout.splitlines(), header, "--help is not exactly the leading comment header")
        self.assertNotIn("set -u", r.stdout)                                  # and stops before the code

    def test_network_guard_blocks_every_patched_entry_point(self):
        """The suite is GENERATED from GUARD_CALLS, which is pinned to the guard's own patch tuples by
        TestNetworkGuardSurfaceAndDisclosure. Before that, this test named the entry points by hand and the
        guard named them by hand in a different place: `gethostbyaddr`/`getfqdn` were in neither, and the
        reviewer who tested them found the same defect for the third time.

        The negative control asserts EVERY generated test fails without the guard, not merely that the run
        fails: a single surviving assertion would hide a name the guard had stopped patching. The targets are
        loopback-only -- see GUARD_CALLS for why that matters here specifically.
        """
        body = _guard_suite_body()
        r = self.rt({"test_a.py": body})
        self.ok(r)
        self.assertIn(f"ran={len(GUARD_CALLS)}", r.stdout)            # all of them really ran
        r2 = self.rt({"test_a.py": body}, "--no-network-guard")
        self.bad(r2)
        self.assertIn(f"failures={len(GUARD_CALLS)}", r2.stdout)      # and all of them depend on the guard

    def test_missing_guard_is_detected_by_canary(self):
        """`python -S` loads no sitecustomize, so the runner's own canary connect runs unguarded. That canary
        now aims at a closed loopback port; with 192.0.2.1 this very test put a SYN on the wire every run."""
        (self.shim / "python3").unlink()
        (self.shim / "python3").write_text(f'#!/bin/sh\nexec "{sys.executable}" -S "$@"\n', encoding="utf-8")   # -S: no site, no sitecustomize
        os.chmod(self.shim / "python3", 0o755)
        r = self.rt({"test_a.py": _pass_module(1)})
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("POLICY:CANARY", r.stdout + r.stderr)

    def test_policy_helper_names_its_own_arity_instead_of_aborting_the_shell(self):
        """Reported by another owner: `run_tests.sh: line 220: $3: unbound variable`, once, under concurrent
        test execution, not reproducible serially.

        It is NOT a latent call path -- there are exactly two `policy` call sites and both pass three arguments.
        The cause is reproducible on demand: this script's own tests COPY the live script (synth_root) and run
        the copy, so a concurrent run read the file inside the window in which `policy` had grown its third
        parameter (the baseline staging path, D2) and the call sites had not yet been updated. Reconstructing
        that intermediate file reproduces the message at line 220 exactly.

        Which way it fails matters more than the cause, so: under `set -u` an unset positional is a FATAL SHELL
        ERROR, not a failed command. The shell exits 1 at that line, `|| FAIL=1` never runs, and neither the
        policy verdicts nor `RESULT:` are ever printed -- so the abort cannot silently drop a verdict and
        cannot be mistaken for a pass (though `unittest: ran=N ... rc=0` may already have been printed above
        it, which is why a scraper must read the exit status and `RESULT:`, as self.ok() does).

        The fix names the arity so a miscall is a red run with a stable token instead of a bash diagnostic. It
        is deliberately not a default value: a default would let a wrongly-called policy() stage a baseline
        nowhere anyone asked for, which is D2 over again.
        """
        src = (SCRIPTS / "run_tests.sh").read_text(encoding="utf-8")
        m = re.search(r"(?ms)^policy\(\) \{\n.*?^\}\n", src)
        self.assertIsNotNone(m, "scripts/run_tests.sh no longer defines policy() as a top-level function; this "
                                "test extracts it by text and must be updated with it")
        prelude = "EXPECT=any BASELINE=none UPDATE=0\nexport MIN_NONE_SKIPS=50\n"
        two = subprocess.run(["bash", "-u", "-o", "pipefail", "-c",
                              prelude + m.group(0) + '\npolicy a b\necho "returned: $?"'],
                             capture_output=True, text=True, timeout=60)
        self.assertIn("POLICY:INTERNAL", two.stdout + two.stderr)
        self.assertIn("returned: 2", two.stdout)                 # a return, so the caller's || FAIL=1 still runs
        self.assertNotIn("unbound variable", two.stderr)         # not a fatal shell abort any more
        three = subprocess.run(["bash", "-u", "-o", "pipefail", "-c", prelude + m.group(0) + "\npolicy a b c\n"],
                               capture_output=True, text=True, timeout=60)
        self.assertNotIn("POLICY:INTERNAL", three.stdout + three.stderr)   # the gate is not blanket-firing
        # and the real call sites are all three-argument ones
        calls = re.findall(r"(?m)^\s*policy (.+)$", src)
        self.assertEqual(len(calls), 2, calls)
        for c in calls:
            self.assertEqual(len(re.findall(r'"[^"]*"', c.split("|")[0].split(">")[0])), 3, c)

    def test_twice_detects_nondeterminism_and_accepts_determinism(self):
        state = self.dir / "state_flag"
        body = textwrap.dedent("""
            import os, unittest
            class T(unittest.TestCase):
                def test_flaky(self):
                    p = os.environ["STATE"]
                    first = not os.path.exists(p)
                    open(p, "w").close()
                    # same NUMBER of skips both times, different reason: only the skip-list comparison can see it
                    self.skipTest("torch not installed; run A" if first else "torch not installed; run B")
        """)
        self.bad(self.rt({"test_a.py": body}, "--twice", env={"STATE": str(state)}), "POLICY:NONDETERMINISTIC")
        self.ok(self.rt({"test_a.py": _pass_module(3)}, "--twice"))
        self.assertIn("deterministic: run1 == run2", self.rt({"test_a.py": _pass_module(3)}, "--twice").stdout)

    @unittest.skipUnless(__import__("importlib.util").util.find_spec("pytest"), "pytest not installed (optional)")
    def test_pytest_unittest_count_mismatch_fails(self):
        body = textwrap.dedent("""
            import unittest
            class T(unittest.TestCase):
                def test_a(self): pass
            class Extra(unittest.TestCase):
                def test_only_unittest_sees_me(self): pass
            def load_tests(loader, tests, pattern):          # honoured by unittest discovery, ignored by pytest
                s = unittest.TestSuite(); s.addTests(loader.loadTestsFromTestCase(T)); s.addTests(loader.loadTestsFromTestCase(Extra))
                s.addTests(loader.loadTestsFromTestCase(Extra)); return s
        """)
        r = self.rt({"test_a.py": body}, pytest=True)
        self.bad(r, "POLICY:PYTEST_COLLECTED")
        self.ok(self.rt({"test_a.py": _pass_module(3)}, pytest=True))

    @unittest.skipUnless(__import__("importlib.util").util.find_spec("pytest"), "pytest not installed (optional)")
    def test_pytest_skip_count_mismatch_is_compared(self):
        self.assertIn("pytest: passed=3 skipped=0", self.rt({"test_a.py": _pass_module(3)}, pytest=True).stdout)

    @unittest.skipUnless(__import__("importlib.util").util.find_spec("pytest"), "pytest not installed (optional)")
    def test_pytest_failing_while_unittest_passes_is_POLICY_PYTEST_FAILED(self):
        """A FOURTH token that was emitted and asserted by no test (the review named three). Its two siblings
        `PYTEST_COLLECTED` and `PYTEST_SKIPPED` were pinned and this one was not, which is the sharper gap of the
        three: a run in which pytest goes red while unittest stays green is exactly the case where the unittest
        result alone would have been read as a pass.

        Driven by a test that can only fail under pytest (pytest imports itself into `sys.modules`; `python -m
        unittest` does not), so `PT_RC != 0` while the unittest leg is clean, and the collected and skipped counts
        still agree -- so ONLY the pytest exit-status check can fail.
        """
        body = textwrap.dedent("""
            import sys, unittest
            class T(unittest.TestCase):
                def test_fails_under_pytest_only(self):
                    self.assertNotIn("pytest", sys.modules, "deliberate: fails under pytest, passes under unittest")
        """)
        r = self.rt({"test_a.py": body}, pytest=True)
        self.bad(r, "POLICY:PYTEST_FAILED")
        self.assertIn("unittest: ran=1 skipped=0 failed=0 rc=0", r.stdout)   # the unittest leg really was green
        self.assertNotIn("POLICY:UNITTEST_FAILED", r.stdout)
        self.assertNotIn("POLICY:PYTEST_COLLECTED", r.stdout)                # counts agree; only the status fails
        self.assertNotIn("POLICY:PYTEST_SKIPPED", r.stdout)
        self.ok(self.rt({"test_a.py": _pass_module(3)}, pytest=True))

    def test_every_policy_token_is_asserted_by_some_test(self):
        """A STALENESS TRIPWIRE, not a measurement: `POLICY:BASELINE_WRITE`, `POLICY:RECORDER` and
        `POLICY:SKIP_RECORD` were emitted by `scripts/run_tests.sh` and asserted by no test at all, and
        `BASELINE_WRITE` is the branch the directory-destination write slipped past -- an unasserted branch is
        where a defect goes to hide. `POLICY:PYTEST_FAILED` was a fourth, found by this check.

        It requires each token to appear in a NON-DOCSTRING string literal of this file, i.e. as data an
        assertion is made of, so quoting a token in prose does not satisfy it. It cannot prove the assertion
        drives the branch -- only that nobody added a token without reaching for one.
        """
        script = (SCRIPTS / "run_tests.sh").read_text(encoding="utf-8")
        # An EMISSION is `POLICY:<NAME>` followed by whitespace and then the message. The `(?=\s)` is what keeps
        # the script's own prose out: the header writes the placeholder `POLICY:<NAME>` and a comment writes the
        # wildcard `POLICY:BASELINE_*`, and neither is a token. (Without it the wildcard read as `BASELINE`.)
        tokens = sorted(set(re.findall(r"POLICY:([A-Z_]+)(?=\s)", script)))
        # ANTI-VACUITY, in two parts, because the one part it had was off by one: `>= 24` against a script that
        # emits 25, so a token could be deleted and the floor still passed. The floor is now the real count
        # (raise it when a token is added; it must never be lowered)...
        self.assertGreaterEqual(len(tokens), 25, tokens)
        # ...and, derived rather than typed, EVERY `POLICY:` occurrence in the script is accounted for: each is
        # either an emission the strict regex above found, or one of the two documented non-emissions -- the
        # header's `POLICY:<NAME>` placeholder and a comment's `POLICY:BASELINE_*` wildcard. This is the half the
        # floor was standing in for: if the strict regex stops matching (the real hazard -- a token count is not
        # a bug, a broken regex is), the occurrences it no longer explains fail here whatever the count.
        NON_EMISSIONS = {"<NAME>", "BASELINE_*"}
        occurrences = set(re.findall(r"POLICY:([^\s`'\"),.;:]*)", script))
        self.assertEqual(sorted(occurrences - NON_EMISSIONS - set(tokens)), [],
                         "these POLICY: strings in scripts/run_tests.sh are matched by neither the token regex "
                         "nor the two known non-emissions: the regex has gone stale, and a token it no longer "
                         "sees is a token no test is required to assert")
        self.assertLessEqual(NON_EMISSIONS, occurrences, "the two documented non-emissions are gone from "
                                                         "scripts/run_tests.sh; this accounting is now vacuous")
        for t in ("BASELINE_WRITE", "RECORDER", "SKIP_RECORD", "PYTEST_FAILED"):   # the four that were unasserted
            self.assertIn(t, tokens, t)
        asserted = set()
        for _lineno, s in _code_string_literals(Path(__file__)):
            asserted |= set(re.findall(r"POLICY:([A-Z_]+)", s))
        self.assertEqual([t for t in tokens if t not in asserted], [],
                         "scripts/run_tests.sh can print these POLICY: tokens and no test in this file asserts "
                         "any of them; drive the branch, or say in docs/CLEAN_CLONE.md why it cannot be driven")


def _live_ruff_skip_reason():
    """The skip reason the LIVE decorator on test_ruff_correctness_findings_are_fatal_not_advisory uses, read out
    of this file's own source rather than retyped.

    Retyping it is what the defect was made of: the reason and the policy that judges it were written in two
    places by two people, and the mismatch (`ruff is not installed (optional linter)` against a policy that
    requires a package name) was invisible on every machine that had ruff. Parsing means the tests below judge the
    string the suite will really emit on a machine without ruff.
    """
    tree = ast.parse(Path(__file__).read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) \
                and node.name == "test_ruff_correctness_findings_are_fatal_not_advisory":
            for d in node.decorator_list:
                if isinstance(d, ast.Call) and getattr(d.func, "attr", None) == "skipUnless":
                    return ast.literal_eval(d.args[1])
    raise AssertionError("test_ruff_correctness_findings_are_fatal_not_advisory no longer carries a "
                         "@unittest.skipUnless(..., <reason>) decorator; _live_ruff_skip_reason parses it")


class TestRunTestsPolicyDetails(_SyntheticBase):
    FS_REASON = "case-sensitive filesystem: case variants are different directories here"
    TOOL_REASON = _live_ruff_skip_reason()

    def _fs(self, n, cls="F", prefix="test_f"):
        return _skip_module(n, self.FS_REASON, cls=cls, prefix=prefix)

    def _tool(self, n, cls="T", prefix="test_t"):
        return _skip_module(n, self.TOOL_REASON, cls=cls, prefix=prefix)

    def rejects_each(self, reasons, expect):
        """ONE run, many candidate reasons, per-reason attribution: every rejected skip prints its own
        `FAIL: POLICY:<TOKEN> ... <id> :: '<reason>'` line, so a single run shows which reasons were rejected and
        which slipped through. Written this way because each run of the script costs about a second and these
        tables are long: 48 separate runs of the laundering table added 57 s to this module for no more
        information than three runs give. (Each skip is judged independently of the others, so batching changes
        no verdict; the floor is lowered to 1 so that it cannot be what fails the run.)"""
        body = "import unittest\n"
        for i, reason in enumerate(reasons):
            body += _skip_module(1, reason, cls=f"L{i}", prefix=f"test_l{i}_").replace("import unittest\n", "")
        r = self.rt({"test_a.py": body}, expect=expect, env={"MIN_NONE_SKIPS": "1"})
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        fails = [l for l in r.stdout.splitlines() if l.startswith("FAIL: POLICY:")]
        for i, reason in enumerate(reasons):
            # Matched on the skip's own TEST ID and not on the reason text alone, which was a masked assertion
            # of exactly the kind this file keeps finding: one of the laundering candidates is a SUBSTRING of
            # another ("an optional developer tool ..." contains "optional developer tool ..."), so the rejected
            # one's FAIL line satisfied the unrejected one's check, and the mutant that re-opened the
            # prose-carrying hole SURVIVED this test. Measured, before the id was added.
            where = f"test_l{i}_0"
            self.assertTrue(any(where in l and reason in l for l in fails),
                            f"--expect {expect} did NOT reject {reason!r} (as {where}): it still claims an "
                            f"environment-skip exemption, or is read as an honest package skip.\n"
                            + "\n".join(fails))
        return r

    # --- optional-developer-tool skips (THE SR-15 THIRD FAIL) ---
    def test_the_live_ruff_skip_reason_is_accepted_in_every_documented_mode(self):
        """THE FAIL. `@unittest.skipUnless(shutil.which("ruff"), "ruff is not installed (optional linter)")` named
        no package, so on any machine without ruff the DOCUMENTED steps failed:

            $ ./scripts/run_tests.sh --expect none --twice      # docs/CLEAN_CLONE.md steps (a) and (c)
            FAIL: POLICY:NONE_REASON skip reason does not say a package is missing:
              toy_tests.test_scripts.TestLintPolicy.test_ruff_correctness_findings_are_fatal_not_advisory
              :: 'ruff is not installed (optional linter)'
            RESULT: FAIL

            $ ./scripts/run_tests.sh --expect torch --twice     # step (d)
            FAIL: POLICY:TORCH_MODE_MISSING torch expected but skipped as missing: ... :: 'ruff is not installed ...'

        `ruff` appears in no requirements file, no constraints file, no CI step and no documented command, and the
        doc's own bareness probe (`for m in torch numpy pytest yaml`) cannot see it -- so the failure was
        reachable only on a machine that did NOT have it, which is precisely the clean clone and the CI runner
        that CLEAN_CLONE.md and README.md are about. It read `OK (skipped=89)` for everyone who had ruff.

        The reason is parsed from the live decorator (see `_live_ruff_skip_reason`), so this drives the exact
        string the suite emits, in each of the three modes the documented steps use.
        """
        for mode, extra in (("none", _mixed_none(50)), ("torch", _skip_module(1, "CUDA not available: x")),
                            ("any", _pass_module(1))):
            with self.subTest(mode=mode):
                self.ok(self.rt({"test_a.py": extra, "test_t.py": self._tool(1)}, "--twice", expect=mode))
        # ...and the runner says so, rather than silently folding it into the package skips
        r = self.rt({"test_a.py": _mixed_none(50), "test_t.py": self._tool(1)}, expect="none")
        self.assertIn("1 skip(s) for an absent optional developer tool", r.stdout)

    def test_tool_skips_do_not_count_toward_the_bare_mode_floor_or_the_torch_cap(self):
        """Same treatment as the filesystem-case category, and for the same reason: a category that could pad the
        bare-mode skip count would let a torch test be parked behind a missing linter and disappear from the
        floor that exists to catch exactly that."""
        self.ok(self.rt({"test_a.py": _mixed_none(50), "test_t.py": self._tool(4)}, expect="none"))
        self.bad(self.rt({"test_a.py": _mixed_none(49), "test_t.py": self._tool(4)}, expect="none"),
                 "POLICY:MIN_NONE_SKIPS")
        self.ok(self.rt({"test_a.py": _skip_module(12, "CUDA not available: x"), "test_t.py": self._tool(4)},
                        expect="torch"))

    def test_tool_skips_are_capped_at_4(self):
        """A cap, like FS_CAP: the category is an admission that a test cannot run here, so a growing count is a
        growing hole and must be noticed rather than accumulated."""
        self.ok(self.rt({"test_a.py": _pass_module(1), "test_t.py": self._tool(4)}, expect="any"))
        self.bad(self.rt({"test_a.py": _pass_module(1), "test_t.py": self._tool(5)}, expect="any"),
                 "POLICY:TOOL_CAP")
        self.bad(self.rt({"test_a.py": _mixed_none(50), "test_t.py": self._tool(5)}, expect="none"),
                 "POLICY:TOOL_CAP")

    def test_tool_reason_cannot_launder_a_missing_package_or_torch_present(self):
        """The anti-laundering rule, identical to the filesystem-case one.

        THIS TEST USED TO PASS THROUGHOUT THE FOURTH SR-15 FAIL, and that is the lesson in it: it tried exactly
        two laundered reasons, both of which happened to contain one of the three spellings torch mode's DENY
        check knows (`not installed`, `missing`, `numpy`) or the phrase `torch present`. Every laundering that
        avoided those three words worked. The rule is no longer about wording at all -- a reason that NAMES a
        measured package gets no exemption -- and the cases below are the ones that were passing.
        """
        laundered = self.TOOL_REASON + "; torch not installed"
        self.bad(self.rt({"test_a.py": _skip_module(1, laundered)}, expect="torch"), "POLICY:TORCH_MODE_MISSING")
        self.bad(self.rt({"test_a.py": _mixed_none(50),
                          "test_b.py": _skip_module(1, self.TOOL_REASON + "; torch present", cls="Q", prefix="test_q")},
                         expect="none"), "POLICY:TORCH_PRESENT")
        # MEASURED PASSING before the fix, in torch mode, i.e. a torch-guarded test could be skipped as "a tool is
        # missing" on a machine that HAS torch and the run stayed green:
        self.rejects_each([self.TOOL_REASON + " (torch unavailable)",
                           self.TOOL_REASON + "; torch is not available here",
                           self.TOOL_REASON + "; torch absent",
                           self.TOOL_REASON + "; torch could not be imported",
                           "optional developer tool `torch` is not on PATH"], expect="torch")
        # and the phrase is structured, not a password: prose that merely sounds like it gets no exemption, and
        # prose that CARRIES it gets none either -- `TOOL` was an unanchored `.search()`, so a reason that merely
        # CONTAINED the phrase collected the exemption (the last two were measured passing with `--expect none`).
        r = self.rejects_each(["optional developer tool is not on PATH", "ruff is not installed (optional linter)",
                               "optional linter absent", "developer tool `ruff` missing",
                               "an optional developer tool `ruff` is not on PATHological systems",
                               "optional developer tool `ruff` is not on PATHological systems"], expect="none")
        self.assertIn("POLICY:NONE_REASON", r.stdout)

    def test_no_environment_exemption_may_name_a_package_the_kit_MEASURES(self):
        """THE FOURTH SR-15 FAIL, stated as the rule that replaced it, and DERIVED: the package list is parsed out
        of `scripts/run_tests.sh` (`PKGS`), so adding a package there without re-measuring this is not possible.

        Both exempt categories are driven, because the defect was in the shape of the exemption and not in the
        tool category: `case-sensitive filesystem; torch unavailable` passed `--expect torch` as well.
        """
        self.assertGreaterEqual(len(POLICY_PKGS), 4, POLICY_PKGS)      # not vacuous if the parse degrades
        self.assertIn("torch", POLICY_PKGS)
        # (1) neither category may be claimed BY a measured package (the tool name is the only place a package
        #     name can sit while the reason still makes no missing-claim at all, which is why it was the one
        #     laundering no wording rule could ever have caught)
        named = [f"optional developer tool `{pkg}` is not on PATH" for pkg in POLICY_PKGS]
        self.rejects_each(named, expect="torch")
        r = self.rejects_each(named, expect="none")
        self.assertIn("POLICY:NONE_REASON", r.stdout)
        # (2) nor may either category carry a package claim as a tail, in ANY spelling. Driven in torch mode:
        #     with nothing installed these reasons are honest package skips and `--expect none` is right to
        #     accept them -- what must not happen is their keeping the exemption, which is what (1) and
        #     test_tool_skips_do_not_count_toward_the_bare_mode_floor_or_the_torch_cap measure.
        tails = []
        for pkg in POLICY_PKGS:
            for tail in (f"; {pkg} unavailable", f"; {pkg} is not available", f"; {pkg} absent",
                         f" ({pkg} could not be imported)", f"; no {pkg} here"):
                tails += [self.TOOL_REASON + tail, self.FS_REASON + tail]
        self.rejects_each(tails, expect="torch")

    def test_live_torch_mode_skip_reasons_stay_accepted(self):
        """WHY the torch-mode DENY list is NOT widened to the other spellings of "is missing" that `--expect none`
        accepts, which is what the obvious fix for the laundering above would have been.

        DENY is applied to EVERY skip, and these are the reasons the real suite emits in torch mode. Two of them
        contain "unavailable" / "not available", so `DENY |= unavailable|not available` turns documented step (d)
        red on every machine -- measured, and the reason the laundering is closed at the exemption instead.

        The reasons are asserted to be present verbatim in the modules that emit them, so rewording one fails
        here (with the file named) instead of silently making this test prove nothing.
        """
        TESTS = ROOT / "tests" / "toy_tests"
        live = [(TESTS / "test_failure_modes.py", "torch present; unavailable path is exercised in the subprocess test"),
                (TESTS / "test_tensor_ops.py", "CUDA not available: CPU-vs-CUDA comparison (ER-09) is UNKNOWN, not passed"),
                (TESTS / "test_tensor_ops.py", "MPS not available (or probe op failed): CPU-vs-MPS comparison is UNKNOWN, not passed"),
                (TESTS / "test_tensor_ops.py", "CUDA present")]
        for path, reason in live:
            self.assertIn(reason, path.read_text(encoding="utf-8"),
                          f"{path.name} no longer emits the skip reason {reason!r}; this test drives it through "
                          f"`--expect torch` and must be updated with it")
            with self.subTest(reason=reason):
                self.ok(self.rt({"test_a.py": _skip_module(1, reason)}, expect="torch"))
        # the same two device reasons as the suite really spells them with nothing installed (test_tensor_ops
        # prefixes `torch not installed; `), which must stay a legal BARE-mode package skip
        for _path, reason in live[1:3]:
            with self.subTest(none_mode=reason):
                self.ok(self.rt({"test_a.py": _mixed_none(49),
                                 "test_b.py": _skip_module(1, "torch not installed; " + reason, cls="W", prefix="test_w")},
                                expect="none"))

    def test_the_baseline_skip_column_is_the_same_with_and_without_the_tool(self):
        """THE WRINKLE, and the reason the exclusion has to be in GENERATION as well as comparison.
        `scripts/test_baseline.txt` records `toy_tests.test_scripts <n> 4` (it said 3 here while the committed
        file said 4 -- prose only, but the figure is the subject of the test). Without the exclusion a no-ruff
        machine would generate 5 there and a ruff machine 4, so the committed file would depend on whose laptop
        ran `--update-baseline`, and a regeneration on the other kind of machine would look like a real change.
        Both halves of the file are generated here from suites that differ ONLY in the tool skip."""
        with_tool = {"test_a.py": _mixed_none(2) + self._tool(1, cls="T", prefix="test_t").replace("import unittest\n", "")
                     + _pass_module(2, cls="H", prefix="test_h").replace("import unittest\n", "")}
        without = {"test_a.py": _mixed_none(2)
                   + _pass_module(3, cls="H", prefix="test_h").replace("import unittest\n", "")}
        gen = []
        for i, files in enumerate((with_tool, without)):
            b = self.dir / f"tool_baseline{i}.txt"
            self.ok(self.rt(files, "--update-baseline", expect="none", baseline=str(b), env={"MIN_NONE_SKIPS": "1"}))
            gen.append(b.read_text(encoding="utf-8"))
        self.assertEqual(gen[0], gen[1], "the baseline depends on whether the optional tool is present")
        self.assertIn("test_a 5 2", gen[0].splitlines())
        # ...and the comparison side agrees: the tool skip cannot be spent as a bare-environment skip
        b = self.dir / "tool_cmp_baseline.txt"
        b.write_text("test_a 5 3\n", encoding="utf-8")
        self.bad(self.rt(with_tool, expect="none", baseline=str(b), env={"MIN_NONE_SKIPS": "1"}),
                 "POLICY:BASELINE_SKIPS")

    # --- filesystem-case skips (first observed failure on a case-sensitive FS) ---
    def test_fs_case_skips_are_accepted_in_none_mode_but_do_not_count_toward_the_floor(self):
        self.ok(self.rt({"test_a.py": _mixed_none(50), "test_f.py": self._fs(4)}, expect="none"))
        self.bad(self.rt({"test_a.py": _mixed_none(49), "test_f.py": self._fs(4)}, expect="none"), "POLICY:MIN_NONE_SKIPS")

    def test_fs_case_skips_are_accepted_in_torch_mode_and_capped_at_8(self):
        self.ok(self.rt({"test_a.py": _skip_module(12, "CUDA not available: x"), "test_f.py": self._fs(8)}, expect="torch"))
        self.bad(self.rt({"test_a.py": _pass_module(1), "test_f.py": self._fs(9)}, expect="torch"), "POLICY:FS_CAP")
        self.bad(self.rt({"test_a.py": _mixed_none(50), "test_f.py": self._fs(9)}, expect="none"), "POLICY:FS_CAP")

    def test_fs_reason_cannot_launder_a_missing_package_or_torch_present(self):
        self.bad(self.rt({"test_a.py": _skip_module(1, "torch not installed; case-sensitive filesystem")}, expect="torch"), "POLICY:TORCH_MODE_MISSING")
        self.bad(self.rt({"test_a.py": _mixed_none(50), "test_b.py": _skip_module(1, "torch present; case-sensitive", cls="Q", prefix="test_q")},
                         expect="none"), "POLICY:TORCH_PRESENT")

    # --- reason wording (none mode) ---
    def test_none_mode_accepts_each_listed_phrase_and_package(self):
        for reason in ("torch missing", "numpy unavailable", "PyYAML not installed", "pytest not installed (optional)",
                       "TORCH NOT AVAILABLE", "pyyaml missing"):
            with self.subTest(reason=reason):
                self.ok(self.rt({"test_a.py": _mixed_none(49), "test_b.py": _skip_module(1, reason, cls="W", prefix="test_w")}, expect="none"))

    def test_none_mode_requires_a_package_name_and_a_phrase(self):
        for reason in ("not installed", "something is missing", "meh installed", "\t \n", "torch", "optional dependency absent"):
            with self.subTest(reason=reason):
                self.bad(self.rt({"test_a.py": _mixed_none(49), "test_b.py": _skip_module(1, reason, cls="W", prefix="test_w")}, expect="none"))

    def test_default_none_floor_is_50(self):
        self.ok(self.rt({"test_a.py": _mixed_none(50)}, expect="none", env={"MIN_NONE_SKIPS": ""}))
        self.bad(self.rt({"test_a.py": _mixed_none(49)}, expect="none", env={"MIN_NONE_SKIPS": ""}), "POLICY:MIN_NONE_SKIPS")

    # --- reason wording (torch mode) ---
    def test_torch_mode_numpy_mention_is_denied_even_with_an_allowed_word(self):
        self.bad(self.rt({"test_a.py": _skip_module(1, "CUDA not available; numpy absent")}, expect="torch"), "POLICY:TORCH_MODE_MISSING")

    def test_torch_mode_device_words_are_whole_words_and_case_insensitive(self):
        for reason in ("CUDAx", "xcuda", "mpsx", "ampsy"):
            with self.subTest(reason=reason):
                self.bad(self.rt({"test_a.py": _skip_module(1, reason)}, expect="torch"), "POLICY:TORCH_MODE_UNEXPLAINED")
        for reason in ("cuda", "MPS", "Torch Present", "no CUDA here"):
            with self.subTest(reason=reason):
                self.ok(self.rt({"test_a.py": _skip_module(1, reason)}, expect="torch"))

    # --- baseline exclusions ---
    def test_baseline_generation_excludes_pyyaml_and_fs_skips(self):
        b = self.dir / "gen_baseline.txt"
        files = {"test_a.py": _mixed_none(2) + _skip_module(1, "PyYAML not installed", cls="Y", prefix="test_y").replace("import unittest\n", "")
                 + _skip_module(1, self.FS_REASON, cls="Z", prefix="test_z").replace("import unittest\n", "")
                 + _pass_module(2, cls="H", prefix="test_h").replace("import unittest\n", "")}
        self.ok(self.rt(files, "--update-baseline", expect="none", baseline=str(b), env={"MIN_NONE_SKIPS": "1"}))
        self.assertIn("test_a 6 2", b.read_text(encoding="utf-8").splitlines())

    def test_pyyaml_or_fs_skip_cannot_mask_a_missing_package_skip_in_the_baseline_check(self):
        b = self.dir / "cmp_baseline.txt"
        b.write_text("test_a 5 3\n", encoding="utf-8")
        for extra in ("PyYAML not installed", self.FS_REASON):
            # (the two `.replace(...)` calls used to be written with a LITERAL backslash-n, `"import unittest\\n"`,
            # unlike their siblings above, so the de-duplication silently did nothing -- harmless, because a
            # repeated `import unittest` changes no count, which is exactly why nothing noticed)
            files = {"test_a.py": _mixed_none(2) + _skip_module(1, extra, cls="Y", prefix="test_y").replace("import unittest\n", "")
                     + _pass_module(2, cls="H", prefix="test_h").replace("import unittest\n", "")}
            with self.subTest(extra=extra):
                self.bad(self.rt(files, expect="none", baseline=str(b), env={"MIN_NONE_SKIPS": "1"}), "POLICY:BASELINE_SKIPS")

    def test_baseline_excludes_pyyaml_as_a_WORD_not_as_a_bare_substring(self):
        """The exclusion was the bare substring `yaml`, so ANY reason containing those four letters anywhere left
        the baseline skip column -- including a reason that names another test (`test_yaml_roundtrip`) while
        honestly reporting that torch is missing. It affects a floor only, which is why it is cheap to pin: the
        skip below must be COUNTED (column 3, not 2), and under the substring rule it was not."""
        b = self.dir / "word_baseline.txt"
        reason = "torch not installed; see test_yaml_roundtrip for the stdlib path"
        files = {"test_a.py": _mixed_none(2) + _skip_module(1, reason, cls="Y", prefix="test_y").replace("import unittest\n", "")
                 + _pass_module(2, cls="H", prefix="test_h").replace("import unittest\n", "")}
        self.ok(self.rt(files, "--update-baseline", expect="none", baseline=str(b), env={"MIN_NONE_SKIPS": "1"}))
        self.assertIn("test_a 5 3", b.read_text(encoding="utf-8").splitlines())
        # ...and a real PyYAML skip is still excluded, so the committed column stays machine-independent
        b2 = self.dir / "word_baseline2.txt"
        files2 = {"test_a.py": _mixed_none(2) + _skip_module(1, "PyYAML not installed", cls="Y", prefix="test_y").replace("import unittest\n", "")
                  + _pass_module(2, cls="H", prefix="test_h").replace("import unittest\n", "")}
        self.ok(self.rt(files2, "--update-baseline", expect="none", baseline=str(b2), env={"MIN_NONE_SKIPS": "1"}))
        self.assertIn("test_a 5 2", b2.read_text(encoding="utf-8").splitlines())

    # --- pytest vs unittest skip counts (M13) ---
    @unittest.skipUnless(__import__("importlib.util").util.find_spec("pytest"), "pytest not installed (optional)")
    def test_pytest_unittest_skip_count_mismatch_fails(self):
        body = textwrap.dedent("""
            import sys, unittest
            class T(unittest.TestCase):
                def test_differs(self):
                    if "pytest" not in sys.modules:       # true under `python -m unittest`, false under pytest
                        self.skipTest("torch not installed; skipped by unittest only")
        """)
        r = self.rt({"test_a.py": body}, pytest=True)
        self.bad(r, "POLICY:PYTEST_SKIPPED")
        self.assertNotIn("POLICY:PYTEST_COLLECTED", r.stdout)          # same collected count: ONLY the skip comparison can fail

    # --- determinism incl. run-2 exit status (U3b) ---
    def test_failure_only_in_second_run_is_nondeterminism(self):
        state = self.dir / "run2_flag"
        body = textwrap.dedent("""
            import os, unittest
            class T(unittest.TestCase):
                def test_fails_second_time(self):
                    p = os.environ["STATE"]
                    second = os.path.exists(p)
                    open(p, "w").close()
                    self.assertFalse(second, "fails only on the second run")
        """)
        r = self.rt({"test_a.py": body}, "--twice", env={"STATE": str(state)})
        self.bad(r, "POLICY:NONDETERMINISTIC")
        self.assertIn("rc=1", r.stdout)


_TOOLFREE = []


def _toolfree_bin():
    """A PATH directory holding ONLY `python3` (a symlink to this interpreter), so a lint run under it genuinely
    has no optional linter on PATH.

    This used to be `str(Path(sys.executable).parent)`, whose comment claimed "PATH without ruff/pyflakes". That
    was true only by ACCIDENT, and the accident depended on which interpreter ran the suite: the interpreter's own
    `bin` directory is exactly where a linter installed into the same environment lives. On this host
    `/Library/Frameworks/.../3.12/bin` has neither, but `/Users/shrey/miniconda3/bin` -- also a python3 on this
    PATH -- holds both `ruff` and `pyflakes`, so under that interpreter every "no optional tool" lint test ran
    WITH both tools present and measured the opposite branch from the one it names. A directory we construct
    cannot drift that way.
    """
    if not _TOOLFREE:
        d = Path(tempfile.mkdtemp(prefix="saferf_toolfree_"))
        __import__("atexit").register(shutil.rmtree, str(d), True)
        (d / "python3").symlink_to(sys.executable)
        _TOOLFREE.append(str(d))
    return _TOOLFREE[0]


def _lint(root, extra_env=None):
    # A genuinely tool-free PATH (see _toolfree_bin): no optional linter, so each synthetic lint run stays fast AND
    # the "a missing tool never fails lint" tests really measure the missing-tool branch. The ruff test puts ruff
    # back explicitly, AFTER this directory, so python3 still resolves to THIS interpreter.
    e = _env(LINT_ROOT=str(root), PATH=_toolfree_bin() + ":/usr/bin:/bin")
    e.pop("PYTHONPATH", None)
    e.update(extra_env or {})
    return subprocess.run([str(LINT)], capture_output=True, text=True, env=e, cwd=ROOT, timeout=120)


class TestLintPolicy(unittest.TestCase):
    CLEAN = {"src/toy/ok.py": "def f(x):\n    return x + 1\n", "tests/test_ok.py": "import unittest\nclass T(unittest.TestCase):\n    def test_a(self): pass\n",
             "scripts/ok.py": "print('hi')\n"}
    FM = "src/toy/failure_modes.py"
    FM_OK = ("def f():\n    ns = {'evaluated': 0}\n    exec('evaluated += 1; RuntimeError', ns)\n"
             "    exec(\"evaluated += 1; RuntimeError('never raised')\", ns)\n")

    def tree(self, extra, drop=()):
        td = tempfile.TemporaryDirectory(prefix="saferf_lint_")
        self.addCleanup(td.cleanup)
        files = {k: v for k, v in self.CLEAN.items() if k not in drop}
        files.update(extra)
        for rel, body in files.items():
            p = Path(td.name) / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(body, encoding="utf-8")
        return Path(td.name)

    def fails(self, extra, needle=None, drop=()):
        r = _lint(self.tree(extra, drop))
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("LINT: FAIL", r.stdout)
        if needle:
            self.assertIn(needle, r.stdout)

    # SKIP REASON, deliberately worded: the `none`-mode policy requires every skip reason to name a missing
    # PACKAGE, and `ruff is not installed (optional linter)` -- the previous reason -- named none, so the
    # DOCUMENTED run `./scripts/run_tests.sh --expect none --twice` failed with POLICY:NONE_REASON on any machine
    # without ruff, and `--expect torch --twice` failed with POLICY:TORCH_MODE_MISSING because the reason said
    # "not installed". Both were invisible on a machine that HAS ruff, which is why two measurements read OK.
    # `optional developer tool `<name>` is not on PATH` is the phrase scripts/run_tests.sh recognises as its
    # second environment-skip category (the first is the filesystem-case one), and it is handled exactly like it:
    # accepted in every mode, capped at 4 (POLICY:TOOL_CAP), and excluded from the bare-mode skip floor, the torch
    # cap and the baseline -- generation included, so the recorded skip column does not depend on whether the
    # machine has ruff. It says "not on PATH" rather than "not installed" on purpose: torch mode denies the latter
    # on EVERY skip, tool skips included, so the category cannot launder a missing package.
    @unittest.skipUnless(shutil.which("ruff"),
                         "optional developer tool `ruff` is not on PATH; nothing in this kit installs it, so only "
                         "the behavioural half of the fatal-ruff guarantee is skipped (the structural half runs "
                         "unconditionally in test_lint_script_makes_ruff_correctness_fatal_structurally)")
    def test_ruff_correctness_findings_are_fatal_not_advisory(self):
        """An undefined name is correctness, not style. This was found the hard way: an undefined
        `Any` in a committed annotation in `src/toy/benchmark.py` survived because ruff reported it
        and `lint.sh` printed `LINT: OK` anyway -- `from __future__ import annotations` stops such a
        name from raising at runtime, so nothing else caught it either. A linter finding nobody has
        to act on is a finding nobody reads.
        The companion guarantee, pinned in `test_missing_optional_tools_never_fail`, is that a
        MISSING ruff still never fails the script -- so the bare-interpreter path is unchanged."""
        # `_lint` strips ruff from PATH deliberately (synthetic runs stay fast, and the missing-tool
        # tests then really measure the missing-tool branch), so this test must put it back --
        # otherwise it would assert the fatal path while measuring the skipped one, which is the
        # masked-test shape this project has hit twelve times. The tool-free dir goes FIRST so that
        # `python3` still resolves to this interpreter and not to whichever one ships beside ruff.
        ruff_dir = str(Path(shutil.which("ruff")).parent)
        with_ruff = {"PATH": _toolfree_bin() + ":" + ruff_dir + ":/usr/bin:/bin"}
        r = _lint(self.tree({"src/toy/undef.py": "def f() -> Any:\n    return 1\n"}), with_ruff)
        self.assertIn("ruff:", r.stdout, "ruff did not run; this test would prove nothing")
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("LINT: FAIL", r.stdout)
        self.assertIn("FATAL: undefined names and syntax errors are not style", r.stdout)
        self.assertIn("F821", r.stdout)
        # and a clean tree still passes with ruff present, so this is not a blanket refusal
        ok = _lint(self.tree({}), with_ruff)
        self.assertEqual(ok.returncode, 0, ok.stdout + ok.stderr)
        self.assertIn("ruff: OK", ok.stdout)
        # the header must not still describe these findings as advisory
        head = (SCRIPTS / "lint.sh").read_text(encoding="utf-8")
        self.assertIn("are FATAL when ruff is present", head)

    def test_lint_script_makes_ruff_correctness_fatal_structurally(self):
        """The always-on half of the fatal-ruff guarantee: it NEVER skips, so a machine without ruff -- a clean
        clone, `core-no-deps` in CI -- is not left with zero coverage of it.

        BE CLEAR ABOUT WHAT THIS IS: a STRUCTURAL assertion over the text of `scripts/lint.sh`, not a
        measurement. It cannot prove that ruff runs, that `E9,F63,F7,F82` are the right rules, or that ruff's
        exit status is read correctly; only the behavioural test above does that, and on a machine without ruff
        that test honestly declares itself skipped instead of silently doing less work.
        What it DOES prove, and the reason it is here rather than being folded into a skipped test: if anyone
        makes ruff advisory again by deleting `FAIL=1` from the failure arm -- the exact regression that let an
        undefined `Any` ship -- this goes red everywhere, with or without ruff installed. That mutant is what the
        single assertRegex below is aimed at, and it kills it.
        """
        text = LINT.read_text(encoding="utf-8")
        m = re.search(r"(?ms)^if command -v ruff >/dev/null 2>&1; then\n(.*?)^fi$", text)
        self.assertIsNotNone(m, "scripts/lint.sh no longer gates ruff on `command -v ruff`; this test reads that "
                                "branch by text and must be updated together with it")
        branch = m.group(1)
        # success -> "ruff: OK"; failure -> a FATAL message AND FAIL=1. Written as one regex over the whole
        # if/else so that FAIL=1 cannot be satisfied by an occurrence somewhere else in the branch.
        self.assertRegex(branch,
                         r"if ruff check --no-cache --select E9,F63,F7,F82 src tests scripts; then echo \"ruff: OK\"\n"
                         r"\s*else echo \"[^\"]*FATAL[^\"]*\"\n"
                         r"\s*FAIL=1; fi",
                         "the ruff branch of scripts/lint.sh no longer makes a correctness finding fatal:\n" + branch)
        # ...and FAIL is what decides the exit status, so FAIL=1 is not decorative
        self.assertIn('if [ "$FAIL" -ne 0 ]; then echo "LINT: FAIL"; exit 1; fi', text)
        # the gate is `command -v`, i.e. a MISSING ruff cannot fail the script (pinned behaviourally in
        # test_missing_optional_tools_never_fail)
        self.assertNotIn("command -v ruff || exit", text)

    def test_clean_tree_passes(self):
        r = _lint(self.tree({}))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("LINT: OK", r.stdout)

    def batch(self, cases, extra=None):
        """One lint run over many bad files; every file must be reported by name with its expected message."""
        files = {rel: code for rel, (code, _) in cases.items()}
        files.update(extra or {})
        r = _lint(self.tree(files))
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("LINT: FAIL", r.stdout)
        errs = [l for l in r.stdout.splitlines() if l.startswith("ERROR:")]
        for rel, (_, needle) in cases.items():
            self.assertTrue(any(rel in l and needle in l for l in errs), f"{rel}: expected {needle!r} in\n" + "\n".join(errs))
        return errs

    def test_network_imports_banned_in_src_tests_and_scripts(self):
        cases = {}
        for d, ext in (("src/toy", "n"), ("tests", "test_n"), ("scripts", "n")):
            for i, code in enumerate(("import socket\n", "from urllib import request\n", "import http.client\n",
                                      "import requests\n", "import ssl\n", "import asyncio\n")):
                cases[f"{d}/{ext}{i}.py"] = (code, "network-capable import")
        self.batch(cases)

    def test_process_and_dynamic_imports_banned_in_src(self):
        codes = (("import subprocess\n", "process/dynamic"), ("import importlib\n", "process/dynamic"),
                 ("import ctypes\n", "process/dynamic"), ("__import__('socket')\n", "__import__"),
                 ("import os\nos.system('curl x')\n", ".system"), ("import os\nos.popen('x')\n", ".popen"),
                 ("import importlib\nimportlib.import_module('socket')\n", "import_module"))
        self.batch({f"src/toy/p{i}.py": c for i, c in enumerate(codes)})

    def test_exec_eval_allowlist_is_exact_per_file_and_string(self):
        r = _lint(self.tree({self.FM: self.FM_OK}))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        bodies = ("exec('import socket; socket.socket()')\n", "eval('__import__(\"os\").system(\"id\")')\n", "eval('1')\n",
                  "exec(code)\n", "compile('x', 'f', 'exec')\n")
        cases = {f"src/toy/e{i}.py": (b, "in src/") for i, b in enumerate(bodies)}
        cases["src/toy/allowed_text_wrong_file.py"] = (self.FM_OK, "in src/")
        errs = self.batch(cases, extra={self.FM: self.FM_OK.replace("RuntimeError', ns", "RuntimeError; import os', ns")})
        self.assertTrue(any("failure_modes.py" in l for l in errs), "right file, altered text must fail")
        r = _lint(self.tree({self.FM: self.FM_OK + "exec('import socket')\n"}))
        self.assertEqual(r.returncode, 1, r.stdout)       # allowed file, extra exec
        self.assertEqual(len([l for l in r.stdout.splitlines() if l.startswith("ERROR:")]), 1)


    def test_aliased_and_family_process_evasions_are_caught(self):
        cases = {
            "alias_as": ("import os as o\no.system('curl x')\n", ".system"),
            "from_import": ("from os import system\nsystem('x')\n", "from os import"),
            "assign_attr": ("import os\nf = os.system\n", ".system"),
            "assign_eval": ("e = eval\ne('1')\n", "eval used"),
            "assign_exec": ("f = exec\n", "exec used"),
            "builtins_exec": ("import builtins\nbuiltins.exec('1')\n", "process/dynamic"),
            "execvp": ("import os\nos.execvp('x', ['x'])\n", ".execvp"),
            "spawnl": ("import os\nos.spawnl(0, 'x', 'x')\n", ".spawnl"),
            "posix_spawn": ("import os\nos.posix_spawn('x', ['x'], {})\n", ".posix_spawn"),
            "from_posix": ("from posix import system\n", "process/dynamic"),
            "fork": ("import os\nos.fork()\n", ".fork"),
            "dunder_builtins": ("__builtins__['exec']('1')\n", "__builtins__"),
        }
        errs = self.batch({f"src/toy/ev_{k}.py": v for k, v in cases.items()})
        self.assertGreaterEqual(len(errs), len(cases))

    def test_stdlib_code_execution_and_server_modules_are_blocked_in_src(self):
        """Every case here PASSED lint with rc=0 and 0 errors before SR-15 closed it, and none of them is a
        runtime-name trick: they are plain static imports with literal attribute calls. `pkgutil.resolve_name`
        is first because it defeats the entire DANGEROUS_ATTR check in one line."""
        cases = {
            "pkgutil_resolve_name": ("import pkgutil\npkgutil.resolve_name('os:system')('echo pwned')\n", "resolve_name"),
            "pkgutil_from": ("from pkgutil import resolve_name\nprint(resolve_name)\n", "from pkgutil import"),
            "code_runsource": ("import code\ncode.InteractiveInterpreter().runsource('x=1')\n", "process/dynamic"),
            "runpy": ("import runpy\nrunpy.run_module('json')\n", "process/dynamic"),
            "runpy_from": ("from runpy import run_module\nrun_module('json')\n", "from runpy import"),
            "pdb": ("import pdb\npdb.run('x=1')\n", "process/dynamic"),
            "cprofile": ("import cProfile\ncProfile.run('x=1')\n", "process/dynamic"),
            "trace": ("import trace\ntrace.Trace().run('x=1')\n", "process/dynamic"),
            "timeit": ("import timeit\ntimeit.timeit('x=1')\n", "process/dynamic"),
            "marshal": ("import marshal\nprint(marshal.loads(b''))\n", "process/dynamic"),
            "types_functiontype": ("import types\nprint(types.FunctionType)\n", ".FunctionType"),
            "zipimport": ("import zipimport\nzipimport.zipimporter('p').load_module('m')\n", "process/dynamic"),
            "doctest": ("import doctest\ndoctest.testmod()\n", "process/dynamic"),
            "pickle": ("import pickle\npickle.loads(b'')\n", "process/dynamic"),
            "shelve": ("import shelve\nshelve.open('db')\n", "process/dynamic"),
            "venv": ("import venv\nvenv.EnvBuilder(with_pip=True).create('/tmp/d')\n", "process/dynamic"),
            "site_addsitedir": ("import site\nsite.addsitedir('/tmp')\n", "process/dynamic"),
            "ensurepip": ("import ensurepip\nensurepip.bootstrap()\n", "process/dynamic"),
            "sqlite3_extension": ("import sqlite3\nsqlite3.connect(':memory:').load_extension('x.so')\n", "process/dynamic"),
            "ctypes_private": ("import _ctypes\nprint(_ctypes)\n", "process/dynamic"),
            "tkinter_tcl_exec": ("import tkinter\ntkinter.Tk().tk.call('exec', 'id')\n", "process/dynamic"),
            "operator_attrgetter": ("import operator, os\noperator.attrgetter('system')(os)('id')\n", ".attrgetter"),
            "operator_methodcaller": ("import operator, os\noperator.methodcaller('system', 'id')(os)\n", ".methodcaller"),
            "procpool": ("import concurrent.futures\nconcurrent.futures.ProcessPoolExecutor()\n", "ProcessPoolExecutor"),
            "procpool_from": ("from concurrent.futures import ProcessPoolExecutor\nProcessPoolExecutor()\n", "process/dynamic"),
            "uuid_getnode": ("import uuid\nprint(uuid.getnode())\n", ".getnode"),
            "uuid1": ("import uuid\nprint(uuid.uuid1())\n", ".uuid1"),
            # network / server capability
            "logging_config": ("import logging.config\nlogging.config.listen(9999)\n", "network-capable"),
            "logging_config_from": ("from logging import config\nprint(config)\n", "network-capable"),
            "logging_handlers": ("import logging.handlers\nprint(logging.handlers)\n", "network-capable"),
            "pydoc_browse": ("import pydoc\npydoc.browse(port=8080)\n", "network-capable"),
            "antigravity": ("import antigravity\nprint(antigravity)\n", "network-capable"),
        }
        errs = self.batch({f"src/toy/x_{k}.py": v for k, v in cases.items()})
        self.assertGreaterEqual(len(errs), len(cases))

    def test_private_c_extension_counterparts_of_banned_modules_are_blocked_in_src(self):
        """Reported but NOT the FAIL ground, and closed anyway because it is one greppable class: the private
        C-extension counterparts of the banned modules. `_socket` and `_ctypes` were named -- which shows two
        members had been thought of -- while `_pickle` (arbitrary code via `__reduce__`), `_imp`
        (`create_dynamic`/`exec_dynamic` load a native extension), `_posixsubprocess.fork_exec`,
        `_multiprocessing`, `_asyncio`, `_sqlite3`, `_tkinter` and `_curses` were not. The lint now rejects ANY
        underscore-prefixed top-level import in src/ (a rule, not eight more names), so the next member of the
        family is closed before anyone tests it. `__future__` is the one exception and src/ relies on it.
        """
        cases = {f"src/toy/priv_{m}.py": (f"import {m}\nprint({m})\n", "private implementation module")
                 for m in ("_pickle", "_imp", "_posixsubprocess", "_multiprocessing", "_asyncio", "_sqlite3",
                           "_tkinter", "_curses", "_socket", "_ctypes", "_ssl", "_random")}
        cases["src/toy/priv_from.py"] = ("from _imp import create_dynamic\nprint(create_dynamic)\n",
                                         "private implementation module")
        self.batch(cases)
        # the exception, and the rule's scope: `from __future__` passes, and tests/ and scripts/ are not covered
        r = _lint(self.tree({"src/toy/fut.py": "from __future__ import annotations\nx: int = 1\n",
                             "tests/test_priv.py": "import _pickle\nprint(_pickle)\n",
                             "scripts/priv.py": "import _pickle\nprint(_pickle)\n"}))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_static_literal_name_resolution_calls_are_blocked_in_src(self):
        """`unittest.TestLoader().loadTestsFromName("os.system")` is a plain static call with a literal string --
        the same shape as `pkgutil.resolve_name`, which defeated the whole attribute blocklist in one line and
        was rated the most important of that round. `sys._getframe()` reaches the caller's builtins."""
        self.batch({
            "src/toy/lt.py": ("import unittest\nunittest.TestLoader().loadTestsFromName('os.system')\n",
                              "loadTestsFromName"),
            "src/toy/gf.py": ("import sys\nprint(sys._getframe().f_builtins['exec'])\n", "_getframe"),
        })

    def test_non_stdlib_imports_in_src_are_rejected(self):
        """The positive check behind the "src/ is standard-library only" claim. `import numpy` / `pandas` /
        `scipy` / `yaml` in src/toy/ used to lint with rc=0 and 0 errors, so the claim was true only by
        inspection. The blocklists above cannot establish it: they are a tripwire and name a finite set."""
        self.batch({f"src/toy/t_{m}.py": (f"import {m}\nprint({m})\n", "non-stdlib import")
                    for m in ("numpy", "pandas", "scipy", "yaml", "sklearn", "biopython")})
        self.fails({"src/toy/t_from.py": "from numpy import array\nprint(array)\n"}, "non-stdlib import")
        # the two allowed non-stdlib names still pass: the kit's own package and the documented optional torch
        r = _lint(self.tree({"src/toy/t_ok.py": "import torch\nfrom toy.schema import X\nprint(torch, X)\n"}))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        # ...and the check is src/-only: tests/ and scripts/ legitimately use numpy, pytest and yaml
        r2 = _lint(self.tree({"tests/test_np.py": "import numpy, yaml\nprint(numpy, yaml)\n",
                              "scripts/s.py": "import numpy\nprint(numpy)\n"}))
        self.assertEqual(r2.returncode, 0, r2.stdout + r2.stderr)

    def test_exec_outside_src_is_not_flagged(self):
        r = _lint(self.tree({"tests/test_x.py": "exec('1')\n", "scripts/x.py": "eval('1')\n"}))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_code_hygiene_rules(self):
        cases = {"bare": ("try:\n    pass\nexcept:\n    pass\n", "bare 'except:'"),
                 "mut": ("def f(x=[]):\n    return x\n", "mutable default"),
                 "mutkw": ("def f(*, x={}):\n    return x\n", "mutable default"),
                 "atup": ("assert (1, 'msg')\n", "always true"),
                 "islit": ("x = 1\nif x is 'a':\n    pass\n", "'is' comparison"),
                 "syn": ("def f(:\n", "syntax error"),
                 "nul": ("x = 1\0\n", "syntax error")}
        self.batch({f"src/toy/h_{k}.py": v for k, v in cases.items()})

    def test_duplicate_test_method_is_an_error_in_tests_only(self):
        dup = "import unittest\nclass T(unittest.TestCase):\n    def test_a(self): pass\n    def test_a(self): pass\n"
        self.fails({"tests/test_dup.py": dup}, "earlier one never runs")
        r = _lint(self.tree({"src/toy/dup.py": "def helper(): pass\ndef helper(): pass\n"}))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)   # advisory outside tests
        self.assertIn("warn:", r.stdout)

    def test_compileall_failure_that_ast_accepts_still_fails(self):
        self.fails({"src/toy/ret.py": "return 1\n"})          # ast.parse accepts; compileall rejects
        r = _lint(self.tree({"src/toy/ret.py": "return 1\n"}))
        self.assertIn("FAIL: compileall", r.stdout)

    def test_unused_import_is_only_a_warning(self):
        r = _lint(self.tree({"src/toy/u.py": "import json\n"}))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("appears unused", r.stdout)

    def test_real_repo_has_no_lint_errors_and_documents_gaps(self):
        self.assertIn("KNOWN GAPS", LINT.read_text(encoding="utf-8"))
        r = _lint(ROOT)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_missing_optional_tools_never_fail(self):
        """The bare-interpreter guarantee from the header of `scripts/lint.sh`: "A MISSING tool never fails this
        script, so the bare-interpreter path is unaffected."

        This test MEASURED NOTHING before. It passed `extra_env={"PATH": str(Path(sys.executable).parent) +
        ":/usr/bin:/bin"}`, which is byte-for-byte what `_lint` already set, and then asserted only `rc == 0` --
        so it was an exact duplicate of `test_clean_tree_passes` and added no coverage at all. Worse, the PATH it
        named was only accidentally tool-free (see `_toolfree_bin`): under an interpreter that ships beside ruff
        and pyflakes it asserted the missing-tool guarantee while measuring the tools-present run.

        It now asserts the branch it names: the script must report that it found no optional linter, and neither
        linter may have run. A mutant that makes an absent tool fatal, or that drops the `RAN_ANY` report, fails
        here; `rc == 0` alone would survive the second.
        """
        r = _lint(self.tree({}))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("LINT: OK", r.stdout)
        self.assertIn("no optional linter (ruff/pyflakes) installed; skipped", r.stdout)
        # ...and the run really was tool-free, so the assertion above is about the branch it claims
        self.assertNotIn("ruff:", r.stdout)
        self.assertNotIn("pyflakes:", r.stdout)

    def test_string_annotation_static_getattr_and_breakpoint_executions_are_blocked_in_src(self):
        """Reported, agreed to be outside the failing criterion (the documentation already concedes "any stdlib
        code-execution or server entry point nobody has thought of yet"), and closed anyway because it cost three
        names. Each of these DID execute a shell command and DID lint with `0 error(s)`, and none of them uses
        eval/exec/compile/getattr/__dict__/vars/getmembers:

        * `typing.get_type_hints(f)` where `f`'s return annotation is the STRING
          `"__import__('os').system('echo pwned')"` -- the string is evaluated, with no `eval` token in the file;
        * `inspect.getattr_static(os, "system")("...")` -- returns the function without an attribute access the
          blocklist can see, the same shape as `pkgutil.resolve_name`;
        * `sys.breakpointhook("...")` with `PYTHONBREAKPOINT=os.system`, and the bare builtin `breakpoint()`,
          which reaches `pdb` -- a module named in PROC -- through no import at all.

        This does NOT make the blocklist complete and is not claimed to: see docs/CLEAN_CLONE.md "Still not
        covered", which keeps the mapping-reflection forms and the string-annotation CLASS listed as open.
        """
        self.batch({
            "src/toy/gth.py": ("import typing\n"
                               "def f() -> \"__import__('os').system('echo pwned')\":\n    return 1\n"
                               "typing.get_type_hints(f)\n", ".get_type_hints"),
            "src/toy/gth_from.py": ("from typing import get_type_hints\nprint(get_type_hints)\n",
                                    "from typing import"),
            "src/toy/gas.py": ("import inspect, os\ninspect.getattr_static(os, 'system')('echo pwned')\n",
                               ".getattr_static"),
            "src/toy/bph.py": ("import sys\nsys.breakpointhook('echo pwned')\n", ".breakpointhook"),
            "src/toy/bp.py": ("breakpoint()\n", "breakpoint used in src/"),
        })
        # and the rule stays src/-only: tests/ and scripts/ legitimately introspect and debug
        r = _lint(self.tree({"tests/test_bp.py": "import typing\nprint(typing.get_type_hints)\nbreakpoint\n",
                             "scripts/bp.py": "import inspect\nprint(inspect.getattr_static)\n"}))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)


class TestDemoGenericFailure(unittest.TestCase):
    def test_non_demofailure_exception_exits_nonzero(self):
        with tempfile.TemporaryDirectory() as td:
            shutil.copytree(ROOT / "src" / "toy", Path(td) / "toy", ignore=shutil.ignore_patterns("__pycache__"))
            with open(Path(td) / "toy" / "benchmark.py", "a", encoding="utf-8") as f:
                f.write("\nraise RuntimeError('injected import-time failure')\n")
            r = subprocess.run([sys.executable, str(SCRIPTS / "demo.py"), "--src", td], capture_output=True, text=True,
                               env=_env(), cwd=ROOT, timeout=60)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("unexpected RuntimeError", r.stderr)
        self.assertNotIn("DEMO OK", r.stdout)


class TestDemoRepoInodeGuard(unittest.TestCase):
    """The demo must refuse a repo-aliasing TMPDIR BEFORE creating anything. It is run with --keep, so a transient
    in-repo write (normally cleaned up) would be left behind and make the emptiness assertions fail."""

    def _run(self, tmpdir):
        return subprocess.run([sys.executable, str(SCRIPTS / "demo.py"), "--keep"], capture_output=True, text=True,
                              env=_env(TMPDIR=tmpdir), cwd=ROOT, timeout=60)

    def _repo_dir(self):
        td = tempfile.mkdtemp(dir=ROOT)
        self.addCleanup(shutil.rmtree, td, ignore_errors=True)
        return td

    def test_case_varied_tmpdir_into_repo_is_refused_before_anything_is_written(self):
        td = self._repo_dir()
        variant = td.swapcase()
        if variant == td or not os.path.exists(variant) or not os.path.samefile(variant, td):
            self.skipTest("filesystem is case-sensitive; case-varied path does not alias the repo")
        r = self._run(variant)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("temp dir root", r.stderr)          # the PRE-creation check fired, not a later one
        self.assertEqual(os.listdir(td), [])

    def test_symlinked_tmpdir_into_repo_is_refused(self):
        inside = self._repo_dir()
        with tempfile.TemporaryDirectory() as outside:
            link = Path(outside) / "link"
            link.symlink_to(inside)
            r = self._run(str(link))
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("temp dir root", r.stderr)
        self.assertEqual(os.listdir(inside), [])

    def test_plain_tmpdir_in_repo_is_refused(self):
        inside = self._repo_dir()
        r = self._run(inside)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("temp dir root", r.stderr)

    def test_tmpdir_outside_repo_still_works(self):
        with tempfile.TemporaryDirectory() as outside:
            r = self._run(outside)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_demo_helper_uses_inode_identity(self):
        self.assertIn("st_ino", (SCRIPTS / "demo.py").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
