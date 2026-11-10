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
    """Every file under the repo (excluding .git and bytecode caches) with size and mtime. Files git already
    reports as modified are tracked by path only, so a concurrent edit by someone else cannot flake the test,
    while any created/deleted path and any change to a clean file is still detected."""
    dirty = _dirty()
    out = {}
    for dp, dns, fns in os.walk(ROOT):
        dns[:] = [d for d in dns if d not in (".git", "__pycache__")]
        for fn in fns:
            p = Path(dp) / fn
            st = p.lstat()
            rel = str(p.relative_to(ROOT))
            out[rel] = None if any(rel == d or rel.startswith(d) for d in dirty) else (st.st_size, st.st_mtime_ns)
    return out


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
        for needle in ("PYTHONDONTWRITEBYTECODE=1", "PYTHONHASHSEED", "__pycache__", "-m unittest discover -s tests",
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
        self.assertEqual(_listing(), before, "demo changed files inside the repository")
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
        self.assertEqual(_listing(), before)


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


if __name__ == "__main__":
    unittest.main()
