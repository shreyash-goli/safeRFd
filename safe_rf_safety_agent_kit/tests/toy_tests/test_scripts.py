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
        self.assertLessEqual(PATCHED_MODULE, fam_mod, "a patched name is outside the enumerated family")
        self.assertLessEqual(PATCHED_SOCKET, fam_sock, "a patched method is outside the enumerated family")
        unaccounted = sorted((fam_mod | fam_sock) - PATCHED_MODULE - PATCHED_SOCKET - GUARD_DISCLOSED)
        self.assertEqual(unaccounted, [], "socket entry point neither patched by scripts/run_tests.sh nor named "
                                          "in its _NOT_BLOCKED disclosure list: patch it or disclose it")
        # and the disclosure is not a dumping ground: nothing may be in both lists
        self.assertEqual(sorted(GUARD_DISCLOSED & (PATCHED_MODULE | PATCHED_SOCKET)), [])
        for n in ("gethostbyaddr", "getfqdn"):          # the two D3 names, now really in the patch set
            self.assertIn(n, PATCHED_MODULE, n)

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


class TestRunTestsPolicyDetails(_SyntheticBase):
    FS_REASON = "case-sensitive filesystem: case variants are different directories here"

    def _fs(self, n, cls="F", prefix="test_f"):
        return _skip_module(n, self.FS_REASON, cls=cls, prefix=prefix)

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
            files = {"test_a.py": _mixed_none(2) + _skip_module(1, extra, cls="Y", prefix="test_y").replace("import unittest\\n", "")
                     + _pass_module(2, cls="H", prefix="test_h").replace("import unittest\\n", "")}
            with self.subTest(extra=extra):
                self.bad(self.rt(files, expect="none", baseline=str(b), env={"MIN_NONE_SKIPS": "1"}), "POLICY:BASELINE_SKIPS")

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


def _lint(root, extra_env=None):
    # PATH without ruff/pyflakes keeps each synthetic lint run fast; the optional-tools test overrides nothing else.
    e = _env(LINT_ROOT=str(root), PATH=str(Path(sys.executable).parent) + ":/usr/bin:/bin")
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

    @unittest.skipUnless(shutil.which("ruff"), "ruff is not installed (optional linter)")
    def test_ruff_correctness_findings_are_fatal_not_advisory(self):
        """An undefined name is correctness, not style. This was found the hard way: an undefined
        `Any` in a committed annotation in `src/toy/benchmark.py` survived because ruff reported it
        and `lint.sh` printed `LINT: OK` anyway -- `from __future__ import annotations` stops such a
        name from raising at runtime, so nothing else caught it either. A linter finding nobody has
        to act on is a finding nobody reads.
        The companion guarantee, pinned in `test_lint_passes_with_nothing_installed`, is that a
        MISSING ruff still never fails the script -- so the bare-interpreter path is unchanged."""
        # `_lint` strips ruff from PATH deliberately (synthetic runs stay fast), so this test must
        # put it back -- otherwise it would assert the fatal path while measuring the skipped one,
        # which is the masked-test shape this project has hit twelve times.
        ruff_dir = str(Path(shutil.which("ruff")).parent)
        with_ruff = {"PATH": ruff_dir + ":" + str(Path(sys.executable).parent) + ":/usr/bin:/bin"}
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
        r = _lint(self.tree({}), {"PATH": str(Path(sys.executable).parent) + ":/usr/bin:/bin"})
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
