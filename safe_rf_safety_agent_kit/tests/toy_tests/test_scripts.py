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
BANNED = {"socket", "urllib", "urllib2", "urllib3", "http", "httplib", "requests", "httpx", "aiohttp", "ftplib",
          "smtplib", "poplib", "imaplib", "telnetlib", "xmlrpc", "ssl", "websocket", "websockets"}


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
    def test_src_toy_has_no_network_imports(self):
        found = []
        for p in sorted((ROOT / "src" / "toy").rglob("*.py")):
            for node in ast.walk(ast.parse(p.read_text(encoding="utf-8"))):
                mods = []
                if isinstance(node, ast.Import):
                    mods = [a.name for a in node.names]
                elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                    mods = [node.module]
                found += [f"{p.name}:{node.lineno}: {m}" for m in mods if m.split(".")[0] in BANNED]
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "__import__":
                    found.append(f"{p.name}:{node.lineno}: __import__")
        self.assertEqual(found, [])

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
        for needle in ("has never been executed", "untested as a combination", "tag, not commit SHA", "estimate"):
            self.assertIn(needle, doc)

    def test_socket_guard_blocks_connections(self):
        """The guard run_tests.sh installs must make connection attempts fail (checked in a child process)."""
        t = (SCRIPTS / "run_tests.sh").read_text(encoding="utf-8")
        guard = re.search(r"<<'PY'\n(import socket as _s.*?)\nPY\n", t, re.S)
        self.assertIsNotNone(guard)
        code = guard.group(1) + "\ntry:\n    _s.create_connection(('192.0.2.1', 9), timeout=1)\nexcept OSError as e:\n    print('BLOCKED', e)\n"
        r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=30)
        self.assertIn("BLOCKED", r.stdout, r.stderr)


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
        self.bad(self.rt({"test_a.py": _mixed_none(49)}, expect="none"), "expected >= 50 skips")

    def test_floor_is_configurable_and_not_off_by_one(self):
        self.ok(self.rt({"test_a.py": _mixed_none(5)}, expect="none", env={"MIN_NONE_SKIPS": "5"}))
        self.bad(self.rt({"test_a.py": _mixed_none(4)}, expect="none", env={"MIN_NONE_SKIPS": "5"}))

    def test_every_skip_must_have_a_valid_reason_not_just_two(self):
        files = {"test_a.py": _mixed_none(48), "test_b.py": _skip_module(2, "meh installed", cls="M", prefix="test_m")}
        self.bad(self.rt(files, expect="none"), "does not say a package is missing")

    def test_reason_case_is_ignored(self):
        files = {"test_a.py": _mixed_none(49), "test_b.py": _skip_module(1, "Torch Not Installed", cls="U", prefix="test_u")}
        self.ok(self.rt(files, expect="none"))

    def test_empty_reason_fails(self):
        files = {"test_a.py": _mixed_none(50), "test_b.py": _skip_module(1, "", cls="E", prefix="test_e")}
        self.bad(self.rt(files, expect="none"), "empty skip reason")

    def test_torch_present_reason_fails_in_none_mode(self):
        files = {"test_a.py": _mixed_none(50), "test_b.py": _skip_module(1, "torch present; torch not installed", cls="T", prefix="test_t")}
        self.bad(self.rt(files, expect="none"), "torch is present")

    def test_all_torch_no_numpy_reason_fails(self):
        self.bad(self.rt({"test_a.py": _skip_module(50, NONE_REASONS[0])}, expect="none"), "no skip mentions numpy")

    def test_all_numpy_no_torch_reason_fails(self):
        self.bad(self.rt({"test_a.py": _skip_module(50, NONE_REASONS[1])}, expect="none"), "no skip mentions torch")

    def test_silent_passes_instead_of_skips_fail(self):
        self.bad(self.rt({"test_a.py": _pass_module(60)}, expect="none"), "expected >= 50 skips")


class TestRunTestsSkipPolicyTorch(_SyntheticBase):
    def test_12_device_skips_pass_and_13_fail(self):
        self.ok(self.rt({"test_a.py": _skip_module(12, "CUDA not available: comparison is UNKNOWN")}, expect="torch"))
        self.bad(self.rt({"test_a.py": _skip_module(13, "CUDA not available: comparison is UNKNOWN")}, expect="torch"), "at most 12")

    def test_allowed_reasons_pass(self):
        files = {"test_a.py": _skip_module(1, "MPS not available (or probe op failed)", cls="A", prefix="test_a"),
                 "test_b.py": _skip_module(1, "torch present; unavailable path is exercised in the subprocess test", cls="B", prefix="test_b")}
        self.ok(self.rt(files, expect="torch"))

    def test_missing_wording_variants_all_fail(self):
        for reason in ("torch is missing", "Torch Not Installed", "numpy not installed (optional)", "CUDA missing",
                       "torch not installed; CUDA not available"):
            with self.subTest(reason=reason):
                self.bad(self.rt({"test_a.py": _skip_module(1, reason)}, expect="torch"), "skipped as missing")

    def test_unexplained_reason_fails(self):
        for reason in ("meh", "torch unavailable", ""):
            with self.subTest(reason=reason):
                self.bad(self.rt({"test_a.py": _skip_module(1, reason)}, expect="torch"))

    def test_zero_skips_pass_in_torch_mode(self):
        self.ok(self.rt({"test_a.py": _pass_module(3)}, expect="torch"))


class TestRunTestsFloorsAndBaseline(_SyntheticBase):
    def test_min_tests_boundary(self):
        self.ok(self.rt({"test_a.py": _pass_module(5)}, env={"MIN_TESTS": "5"}))
        self.bad(self.rt({"test_a.py": _pass_module(4)}, env={"MIN_TESTS": "5"}), "MIN_TESTS=5")

    def test_default_floor_is_650_inclusive(self):
        self.ok(self._default_floor(650))
        self.bad(self._default_floor(649), "MIN_TESTS=650")

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
        self.bad(r, "module test_a ran 4 tests, baseline 5")

    def test_deleted_module_fails(self):
        b = self._baseline("test_a 5 3\ntest_gone 2 0\n")
        r = self.rt({"test_a.py": self._suite3(3)}, expect="none", baseline=b, env={"MIN_NONE_SKIPS": "1"})
        self.bad(r, "module test_gone ran 0")

    def test_guarded_tests_turned_into_silent_passes_fail(self):
        b = self._baseline("test_a 5 3\n")
        r = self.rt({"test_a.py": self._suite3(2)}, expect="none", baseline=b, env={"MIN_NONE_SKIPS": "1"})
        self.bad(r, "module test_a has 2 bare-environment skips, baseline 3")

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
        self.bad(self.rt({"test_a.py": body}), "unittest suite failed")

    def test_erroring_test_fails_run(self):
        body = "import unittest\nclass T(unittest.TestCase):\n    def test_x(self):\n        raise RuntimeError('boom')\n"
        self.bad(self.rt({"test_a.py": body}), "unittest suite failed")

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

    def test_network_guard_blocks_each_entry_point(self):
        body = textwrap.dedent("""
            import socket, unittest
            def _sock():
                s = socket.socket()
                s.settimeout(1)          # without the guard these must fail fast, not hang for ~75 s
                return s
            def blocked(fn):
                def t(self):
                    with self.assertRaises(OSError) as cm:
                        fn()
                    self.assertIn("NETWORK BLOCKED", str(cm.exception))
                return t
            class T(unittest.TestCase):
                test_create_connection = blocked(lambda: socket.create_connection(("192.0.2.1", 9), timeout=1))
                test_connect = blocked(lambda: _sock().connect(("192.0.2.1", 9)))
                test_connect_ex = blocked(lambda: _sock().connect_ex(("192.0.2.1", 9)))
                test_getaddrinfo = blocked(lambda: socket.getaddrinfo("localhost", 80))
                test_gethostbyname = blocked(lambda: socket.gethostbyname("localhost"))
        """)
        self.ok(self.rt({"test_a.py": body}))
        r = self.rt({"test_a.py": body}, "--no-network-guard")
        self.bad(r)   # without the guard the same suite fails: the test above really depends on the guard

    def test_missing_guard_is_detected_by_canary(self):
        (self.shim / "python3").unlink()
        (self.shim / "python3").write_text(f'#!/bin/sh\nexec "{sys.executable}" -S "$@"\n', encoding="utf-8")   # -S: no site, no sitecustomize
        os.chmod(self.shim / "python3", 0o755)
        r = self.rt({"test_a.py": _pass_module(1)})
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("canary did not trigger", r.stdout + r.stderr)

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
        self.bad(self.rt({"test_a.py": body}, "--twice", env={"STATE": str(state)}), "non-deterministic")
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
        self.bad(r, "pytest collected")
        self.ok(self.rt({"test_a.py": _pass_module(3)}, pytest=True))

    @unittest.skipUnless(__import__("importlib.util").util.find_spec("pytest"), "pytest not installed (optional)")
    def test_pytest_skip_count_mismatch_is_compared(self):
        self.assertIn("pytest: passed=3 skipped=0", self.rt({"test_a.py": _pass_module(3)}, pytest=True).stdout)


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
                 ("import os\nos.system('curl x')\n", "os.system"), ("import os\nos.popen('x')\n", "os.popen"),
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
