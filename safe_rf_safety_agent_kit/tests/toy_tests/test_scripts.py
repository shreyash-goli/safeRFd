"""SR-15 tests for the dev/CI scripts. TOY ONLY. Standard library only (PyYAML is used if present, never required)."""
import ast
import json
import os
import re
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"
CI = ROOT / ".github" / "workflows" / "ci.yml"


def _deferred_gates():
    """Read `DEFERRED_GATES` out of src/toy/benchmark.py by parsing it, not by importing it.

    This module is deliberately free of imports from the `toy` package: everything it tests, it tests through
    a subprocess, which is what lets it run unchanged in the bare `venv --without-pip` interpreter. Parsing
    keeps that property and follows `_lint_blocklists` above, which exists because two hand-maintained copies
    of a list diverged.
    """
    src = (ROOT / "src" / "toy" / "benchmark.py").read_text(encoding="utf-8")
    for node in ast.parse(src).body:
        if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == "DEFERRED_GATES" for t in node.targets):
            return tuple(ast.literal_eval(node.value))
    raise AssertionError("src/toy/benchmark.py no longer assigns DEFERRED_GATES at module level as a literal; "
                         "this file parses it (see _deferred_gates) and must be updated together with it")


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


def _policy_tools():
    """The `TOOLS` allowlist in `scripts/run_tests.sh`: the CLOSED set of developer-tool names whose absence may
    claim the optional-developer-tool exemption. Parsed, like `PKGS`."""
    text = (SCRIPTS / "run_tests.sh").read_text(encoding="utf-8")
    m = re.search(r"(?m)^TOOLS = (\(.*?\))\n", text, re.S)
    if m is None:
        raise AssertionError("scripts/run_tests.sh no longer defines TOOLS as a plain tuple literal; this file "
                             "parses it (see _policy_tools) and must be updated together with it")
    return tuple(ast.literal_eval(m.group(1)))


POLICY_TOOLS = _policy_tools()


class _Cat:
    """One row of the runner's `EXEMPT_CATEGORIES`: an environment-exemption CATEGORY as the policy declares it."""

    def __init__(self, token, phrase, cap, where, allow, note):
        self.token, self.phrase, self.cap = token, phrase, cap
        self.where, self.allow, self.note = where, tuple(allow), note

    @property
    def anchored(self):
        """The phrase as the policy applies it: `.match`ed, i.e. only at position 0."""
        return re.compile(self.phrase, re.I)

    @property
    def loose(self):
        """The same phrase with the leading `\\A` stripped -- what the policy uses to find a SECOND occurrence,
        and what this file uses to find a skip site that CARRIES the phrase without claiming the category."""
        return re.compile(self.phrase[2:] if self.phrase.startswith(r"\A") else self.phrase, re.I)

    def __repr__(self):
        return f"_Cat({self.token}, cap={self.cap}, allow={self.allow})"


def _policy_block():
    """The skip-policy Python the runner executes -- the one `<<'PY'` heredoc in `scripts/run_tests.sh` that
    declares `EXEMPT_CATEGORIES` -- as SOURCE, so it can be parsed as a program rather than grepped.

    `_policy_exempt_categories` below reads the registry with a REGEX over the file and then `ast.literal_eval`s
    the rows; that sees the literal and nothing else, which is round 7's F2. Parsing the whole block is what lets
    a test ask the question the regex cannot: is this name assigned anywhere ELSE?
    """
    text = (SCRIPTS / "run_tests.sh").read_text(encoding="utf-8")
    blocks = [b for b in re.findall(r"<<'PY'\n(.*?)\nPY\n", text, re.S) if "EXEMPT_CATEGORIES" in b]
    if len(blocks) != 1:
        raise AssertionError(f"scripts/run_tests.sh holds {len(blocks)} `<<'PY'` heredocs that mention "
                             f"EXEMPT_CATEGORIES; this file parses exactly one (see _policy_block)")
    return blocks[0]


def _policy_exempt_categories():
    """The runner's `EXEMPT_CATEGORIES` tuple -- ONE row per environment-exemption category -- parsed out of
    `scripts/run_tests.sh`.

    THE ROUND-6 FAIL IS WHY THIS IS PARSED. The tool category had three anchoring guards and a closed allowlist;
    the filesystem-case category -- the same KIND of exemption -- had an unanchored `re.search` for
    `case[- ]sensitive` and no allowlist at all, so `case-sensitive filesystem: variants differ; libtorch is
    gone` was exempt in all three modes. Two hand-guarded sites cannot be kept in step by review, so the policy
    declares its categories in one tuple and the checks in this file are generated FROM it: every guard, the cap
    boundary, the laundering table, the cross-category case, the allowlist equality and the POLICY tokens a
    category must have tests for. A category added to the script without a declaration this parse accepts is an
    AssertionError here; a category declared badly is POLICY:INTERNAL at runtime.
    """
    text = (SCRIPTS / "run_tests.sh").read_text(encoding="utf-8")
    m = re.search(r"(?ms)^EXEMPT_CATEGORIES = \((.*?)^\)\n", text)
    if m is None:
        raise AssertionError("scripts/run_tests.sh no longer defines EXEMPT_CATEGORIES as a parenthesised tuple "
                             "of rows; this file parses it (see _policy_exempt_categories) and must be updated "
                             "together with it")
    tree = ast.parse("(" + m.group(1) + ")", mode="eval").body
    if not isinstance(tree, ast.Tuple) or not tree.elts:
        raise AssertionError("EXEMPT_CATEGORIES is no longer a non-empty tuple of rows")
    # the allowlist column may be a NAME (`TOOLS`) rather than a literal; resolve only the names the script
    # really declares, so an unknown name fails here instead of being skipped
    resolvable = {"TOOLS": POLICY_TOOLS}
    cats = []
    for row in tree.elts:
        if not isinstance(row, ast.Tuple) or len(row.elts) != 6:
            raise AssertionError("a row of EXEMPT_CATEGORIES is not a 6-tuple "
                                 "(token, phrase, cap, where, allowlist, note); this file parses every column "
                                 "(see _policy_exempt_categories) and a new column must be given a check here")
        vals = []
        for el in row.elts:
            if isinstance(el, ast.Name):
                if el.id not in resolvable:
                    raise AssertionError(f"a row of EXEMPT_CATEGORIES refers to the name {el.id!r}, which this "
                                         f"file cannot resolve; declare it as a literal or teach "
                                         f"_policy_exempt_categories to read it")
                vals.append(resolvable[el.id])
            else:
                vals.append(ast.literal_eval(el))
        cats.append(_Cat(*vals))
    return tuple(cats)


EXEMPT_CATS = _policy_exempt_categories()


def _cat(token):
    """The one declared category with this token, or an AssertionError naming what is declared instead."""
    hit = [c for c in EXEMPT_CATS if c.token == token]
    if len(hit) != 1:
        raise AssertionError(f"scripts/run_tests.sh declares {[c.token for c in EXEMPT_CATS]} as its "
                             f"environment-exemption categories and this file needs exactly one {token!r}")
    return hit[0]


def _tool_phrase_re():
    """The runner's TOOL-category phrase, taken from the parsed `EXEMPT_CATEGORIES` row, with its name group.

    Parsed rather than retyped for the same reason `_live_ruff_skip_reason` parses the decorator: the phrase and
    the thing that judges the phrase were written in two places by two people once already."""
    pat = _cat("TOOL").anchored
    if pat.groups != 1:
        raise AssertionError("the runner's TOOL phrase no longer captures the tool name in exactly one group; "
                             "_suite_tool_gates reads group(1)")
    return pat


def _skip_reason_exprs(source, label):
    """[(label:line, expression)] for every skip-reason ARGUMENT in a module's source -- the expression a
    `skip`/`skipIf`/`skipUnless`/`skipTest` call takes its reason from, whether or not it is a literal."""
    out = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        name = fn.attr if isinstance(fn, ast.Attribute) else getattr(fn, "id", "")
        if name not in ("skip", "skipIf", "skipUnless", "skipTest"):
            continue
        i = 0 if name in ("skip", "skipTest") else 1
        if len(node.args) <= i:
            continue
        out.append((f"{label}:{node.lineno}", node.args[i]))
    return out


def _static_strings(node):
    """Every string a STATIC reader can see in a reason expression that is not one literal: the constant pieces
    of an f-string, of a `+` concatenation, of a conditional, of a `join`/`%`/`.format` operand. A `{...}`
    field contributes NOTHING, which is exactly the point of the check built on this."""
    if isinstance(node, ast.Constant):
        return [node.value] if isinstance(node.value, str) else []
    out = []
    if isinstance(node, ast.JoinedStr):
        for v in node.values:
            out += _static_strings(v)
    elif isinstance(node, ast.BinOp):
        out += _static_strings(node.left) + _static_strings(node.right)
    elif isinstance(node, ast.IfExp):
        out += _static_strings(node.body) + _static_strings(node.orelse)
    elif isinstance(node, (ast.Tuple, ast.List)):
        for e in node.elts:
            out += _static_strings(e)
    elif isinstance(node, ast.Call):
        for arg in [getattr(node.func, "value", None), *node.args]:
            if isinstance(arg, ast.AST):
                out += _static_strings(arg)
    return out


def _suite_modules():
    """Every module the runner DISCOVERS -- `discover -s tests`, so tests/ and not only tests/toy_tests/.

    `tests/test_toy.py` is in the discovered suite and was outside this file's scan, so a skip reason there
    would have been judged by the runner and by nothing at test time. It carries no skip at all today
    (measured), which is why widening the scan costs nothing -- and why it is worth doing before it does.
    """
    return sorted((ROOT / "tests").rglob("*.py"))


def _suite_skip_sites():
    """[(file:line, reason)] for every LITERAL skip reason in the DISCOVERED suite (tests/, recursively).

    LITERAL is the limit of this scan, and `_suite_computed_skip_sites` is the other half: a reason built with
    an f-string or a concatenation is not an `ast.Constant` and cannot be judged by `.match`ing a phrase
    against it, so it is collected separately and held to a narrower rule.

    Synthetic reasons built inside this file's laundering tables are NOT skip sites (they are strings handed to
    helpers, or source text for a generated module), so they are invisible here -- which is the point: the scan
    sees what the SUITE will emit.
    """
    out = []
    for p in _suite_modules():
        label = str(p.relative_to(ROOT / "tests"))
        for where, expr in _skip_reason_exprs(p.read_text(encoding="utf-8"), label):
            if isinstance(expr, ast.Constant) and isinstance(expr.value, str):
                out.append((where, expr.value.strip()))
    return out


def _suite_computed_skip_sites():
    """[(file:line, [fragment, ...])] for every skip reason in the discovered suite that is NOT one literal --
    an f-string, a concatenation, a conditional -- with the strings a static reader can still see in it.

    These are invisible to `_suite_skip_sites`, and therefore to the allowlist equality and to the carrier
    scan. Two are real (`toy_tests/test_tensor_ops.py:29` and `:31`). What may be done with them is
    test_no_computed_skip_reason_carries_a_declared_exemption_phrase.
    """
    out = []
    for p in _suite_modules():
        label = str(p.relative_to(ROOT / "tests"))
        for where, expr in _skip_reason_exprs(p.read_text(encoding="utf-8"), label):
            if not (isinstance(expr, ast.Constant) and isinstance(expr.value, str)):
                out.append((where, _static_strings(expr)))
    return out


def _suite_category_gates(cat):
    """name -> [file:line, ...] for every skip site in tests/toy_tests/ whose reason BEGINS with this category's
    declared phrase and carries a name in it.

    ROUND 7's F1 IS WHY THIS TAKES A CATEGORY. The round-5 derivation was written for the tool category alone and
    compared the gate set against `POLICY_TOOLS` -- the `TOOLS = (...)` line -- rather than against the allowlist
    column of the REGISTRY ROW that the policy actually reads. So a ONE-TOKEN change at the row
    (`..., 4, "TOOLS", TOOLS,` -> `..., 4, "TOOLS", ("ruff", "shellcheck"),`) left `TOOLS = ("ruff",)` literally
    true, the `.github/workflows/ci.yml` comment true and the equality at
    test_the_TOOLS_allowlist_is_exactly_the_tools_this_suite_gates_on GREEN, while `shellcheck` was exempt in all
    three modes with no POLICY token at all. The guards were generalised in round 6 and the DERIVATION was not.
    """
    pat = cat.anchored
    if pat.groups != 1:
        raise AssertionError(f"{cat.token}'s phrase does not capture exactly one name; _suite_category_gates "
                             f"reads group(1) and is only meaningful for a category that carries a name")
    gates = {}
    for where, reason in _suite_skip_sites():
        m = pat.match(reason)
        if m and m.group(1):
            gates.setdefault(m.group(1).lower(), []).append(where)
    return gates


def _suite_tool_gates():
    """(tool name -> [file:line, ...], number of literal skip reasons scanned) for every skip site in
    tests/toy_tests/ whose reason is SHAPED like the runner's optional-developer-tool category.

    This is the derivation the round-5 fix rests on: the allowlist in the script must be exactly the set of tools
    this suite really gates a test on, and that set is read out of the live `@unittest.skipUnless(...)` /
    `skipTest(...)` reasons rather than maintained beside them. It is kept as the TOOL-specific wrapper because
    the test built on it pins the `TOOLS` TUPLE; the per-ROW equality is
    test_every_named_categorys_allowlist_is_exactly_the_names_this_suite_gates_on, and both are needed -- the
    tuple can be true while the row that reads it is not.
    """
    _tool_phrase_re()                                      # the arity check, with its own message
    return _suite_category_gates(_cat("TOOL")), len(_suite_skip_sites())


def _suite_exempt_carriers():
    """[(file:line, category, reason)] for every literal skip reason in tests/toy_tests/ that CARRIES a declared
    environment-exemption phrase ANYWHERE in it -- claiming the category or not.

    Looking for the phrase LOOSELY is the whole value of this scan, and it is the round-6 defect stated as a
    check. `_suite_tool_gates` looks for the TOOL phrase with `.match`, so a reason that does not BEGIN with it
    is invisible to the derivation the allowlist rests on: measured on a byte-identical copy, a probe site
    reading ``case-sensitive filesystem: optional developer tool `mypy` is not on PATH`` left
    test_the_TOOLS_allowlist_is_exactly_the_tools_this_suite_gates_on GREEN while the skip was exempt at runtime
    in all three modes -- a test gated on an undeclared tool, green at test time and at run time. (The same
    reason WITHOUT the leading filesystem-case phrase fails that test, which is how the derivation is known to
    work at all.) A carrier that does not properly claim its category is reported by
    test_every_declared_exemption_category_is_claimed_properly_by_the_sites_that_use_it.
    """
    out = []
    for where, reason in _suite_skip_sites():
        for c in EXEMPT_CATS:
            if c.loose.search(reason):
                out.append((where, c, reason))
    return out

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


def _comment_units(path, comments_only):
    """[(first line number, text)] for each maximal run of COMMENT lines (or, in a document, of non-blank
    lines), with the comment markers stripped and the run joined into one string.

    Every file this discipline scans is HARD-WRAPPED, so a sentence is not a line: joining the run is what lets
    a check ask which SENTENCE a retraction marker belongs to. See
    test_no_withdrawn_guarantee_is_restated_in_a_comment for the measurement that made that necessary.
    """
    out, run, start = [], [], None
    for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        s = line.strip()
        if (s.startswith("#") if comments_only else bool(s)):
            if start is None:
                start = i
            run.append(re.sub(r"^#+\s?", "", s) if comments_only else s)
        else:
            if run:
                out.append((start, " ".join(run)))
            run, start = [], None
    if run:
        out.append((start, " ".join(run)))
    return out


_SENTENCE_END = re.compile(r"(?<=[.!?;])\s+")


def _sentence_lead(text, pos):
    """The text from the start of the sentence containing `pos` up to `pos` -- i.e. what a reader has already
    been told when they reach the claim at `pos`.

    A retraction marker counts only if it is HERE. A line window cannot do that: round 8's F3 was a line that
    carried a withdrawn claim AND a correct history note about a different fact, so the marker the window found
    belonged to the other claim and the needle passed at every half-width from 0 to 7 (measured).
    """
    head = text[:pos]
    cuts = [m.end() for m in _SENTENCE_END.finditer(head)]
    return head[cuts[-1]:] if cuts else head


_CODE_SUFFIXES = (".py", ".sh", ".yml", ".yaml")


def _tracked():
    """Every path `git ls-files` reports for this repository, relative to ROOT."""
    r = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT, capture_output=True, text=True, timeout=60)
    if r.returncode != 0:
        raise AssertionError(f"`git ls-files` failed in {ROOT}: {r.stderr.strip()!r}. The withdrawn-guarantee "
                             f"scope is DERIVED from it rather than enumerated, so it cannot run without it.")
    return [p for p in r.stdout.split("\0") if p]


def _journal_files():
    """The files this project's own operating rules designate as the durable JOURNAL -- a dated record of
    findings rather than normative prose about the kit -- read out of `CLAUDE.md` instead of typed here.

    The journal quotes withdrawn claims verbatim, as findings, which is what a journal is for: measured on the
    tree this derivation was written on, `docs/PROGRESS.md` held 15 needle occurrences and 12 of them fail the
    sentence rule. Adjudicating that with a prose rule is a category error, so it is excluded -- but excluded by
    the project's own sentence about it, so that renaming the journal moves the exclusion with it and deleting
    that sentence turns this red instead of silently widening the scope.
    """
    text = (ROOT / "CLAUDE.md").read_text(encoding="utf-8")
    hits = {m.group(1) for m in re.finditer(r"`([\w./-]+)` is the durable journal", text)}
    if not hits:
        raise AssertionError("CLAUDE.md no longer names a file as `… is the durable journal`. "
                             "test_no_withdrawn_guarantee_is_restated_in_a_comment derives the ONE exclusion "
                             "from that sentence; without it the journal's quoted findings enter the scan and "
                             "this fails loudly, which is the intended direction. Restore the sentence or "
                             "change the derivation deliberately.")
    return hits


def _normative_prose_files():
    """([(path relative to ROOT, read COMMENTS ONLY?)], [tracked paths that are not UTF-8 text]).

    THE SCOPE OF THE WITHDRAWN-GUARANTEE SCAN, DERIVED RATHER THAN ENUMERATED -- round 10's F3. The enumerated
    list went short three times in a row: widened to `docs/CLEAN_CLONE.md` in round 7, to
    `.github/workflows/ci.yml` in round 9, and found short again by `scripts/lint.sh`'s 43-line normative header
    AND by `README.md` -- the file that retracted "nothing leaves the host" in the first place. An enumeration is
    short by exactly the files nobody thought of, so there is nothing to think of here: the scope is every
    tracked file except the designated journal, and the per-file reading rule comes from the suffix (a code file
    is read for its FULL-LINE comments, a document for all of its prose, because in a Markdown file the prose IS
    the claim). A new file carrying normative prose lands in the scope with no edit to this file.
    """
    journal = _journal_files()
    out, binary = [], []
    for rel in _tracked():
        if rel in journal:
            continue
        p = ROOT / rel
        try:
            p.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            binary.append(rel)
            continue
        out.append((rel, p.suffix in _CODE_SUFFIXES))
    return out, binary


def _fold_note(s):
    """A note as the runner's `fold_note` folds it: lowercase words, punctuation and case discarded. Mirrored
    rather than parsed because it is three lines; the near-duplicate rows this file drives are what pin the
    runner's copy, and this one only decides whether a test case is still the case it claims to be."""
    return " ".join(re.sub(r"[^0-9a-z]+", " ", str(s).lower()).split())


def _registry_cols():
    """The columns `scripts/run_tests.sh` attests for each registry row, read out of the script.

    Parsed rather than retyped so that a column added to the script's attestation forces the comparison in
    test_the_registry_the_run_really_uses_equals_the_declared_literal to be updated with it -- which is the
    other half of the script's own runtime check that a `CATS` row has exactly these columns. The pair is what
    closes the gap the listing had while it omitted column 3, the loose pattern.
    """
    text = (SCRIPTS / "run_tests.sh").read_text(encoding="utf-8")
    m = re.search(r"(?m)^_REGISTRY_COLS = (\(.*\))\n", text)
    if m is None:
        raise AssertionError("scripts/run_tests.sh no longer declares _REGISTRY_COLS on one line; this file "
                             "reads it to require that the registry attestation carries EVERY column of a row")
    return tuple(ast.literal_eval(m.group(1)))


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

    def test_demo_verdict_line_carries_its_scorer_qualifier_on_that_same_line(self):
        """F23 (SR-16's M7). The demo's step-[3] line is its most quotable output -- it prints a
        `JOINT_SUPPORTED` verdict -- and the bracketed qualifier is the DEMO'S ONLY safety qualifier on it.
        Deleting `[tests the scorer; says nothing about any method]` from demo.py:138 survived all 1493 tests.

        Pinned ON THE VERDICT LINE, not merely somewhere in stdout, because that is the qualifier's job: no
        crop of the verdict line may omit it. A mutant that moves the qualifier to its own `print`, into the
        banner, or into step [4] therefore dies here even though stdout still contains every word of it --
        which is exactly the hostile-quoting case `docs/SR12_INDEPENDENT_REVIEW.md` Q2 and
        `docs/SR16_AUDIT_REPORT.md` §2.2 raise, and which an `assertIn(..., r.stdout)` would not catch.

        The verdict line is LOCATED rather than assumed: the lines matching `verdict <TOKEN>` are collected
        and the count is asserted to be exactly 1, so deleting the print (or the verdict from it) fails on the
        count instead of leaving a sweep with nothing to sweep. The denial is then pinned verbatim, so
        `[tests the scorer]`, `[tests the scorer; says little about any method]` and `[tests the scorer; says
        nothing about THIS method]` all fail, and so does an empty qualifier.
        """
        qual = "[tests the scorer; says nothing about any method]"
        r = subprocess.run([sys.executable, str(SCRIPTS / "demo.py")], capture_output=True, text=True,
                           env=_env(), cwd=ROOT, timeout=120)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        verdict_lines = [ln for ln in r.stdout.splitlines() if re.search(r"\bverdict [A-Z][A-Z_]+", ln)]
        self.assertEqual(len(verdict_lines), 1,
                         f"expected exactly one `verdict <TOKEN>` line in demo stdout, got {verdict_lines!r}")
        line = verdict_lines[0]
        _before, bracket, rest = line.partition("[tests the scorer;")
        self.assertTrue(bracket, f"the verdict line carries no scorer qualifier at all: {line!r}")
        self.assertTrue(rest.startswith(" says nothing about any method]"),
                        f"the qualifier's denial is weakened, truncated or reworded: {line!r}")
        self.assertIn(qual, line, f"the qualifier is not intact on the verdict line: {line!r}")

    def test_demo_claim_state_line_carries_its_not_supported_qualifier_on_that_same_line(self):
        """The F23/F24 sibling class, item `Z-demo5` -- F23 for the step-[5] line instead of the step-[3]
        one. (No new F-number is coined here: `F25` is already SR-16's checkpoint-digest advisory.)
        `scripts/demo.py:159` prints `claim state REVIEWED (not SUPPORTED)`, and deleting the parenthetical
        left `Ran 157 ... OK`. Without it the line reads `claim state REVIEWED`, which a reader -- or a
        quote of the demo's output -- takes for a positive finding about the claim, when `REVIEWED` in this
        kit means only that a human looked at it and issued NO verdict (`claim_ledger.py`:
        `REVIEWED (inspected by a human; no verdict yet)`).

        Pinned ON THE CLAIM-STATE LINE, not merely somewhere in stdout, for the reason F23 established: an
        `assertIn("(not SUPPORTED)", r.stdout)` passes when the qualifier is relocated to its own `print`,
        and relocation is the exact failure the qualifier exists to prevent -- no crop of this line may omit
        it. The line is LOCATED rather than assumed: the lines matching `claim state <TOKEN>` are collected
        and the count asserted to be exactly 1, so deleting the print (or the state from it) fails on the
        count instead of leaving a sweep with nothing to sweep. The qualifier is then required to follow the
        state ON THAT LINE, so `(SUPPORTED)`, `(reviewed)`, `(not SUPPORTED yet)` and an empty parenthetical
        all fail, and so does a second `print` carrying it.
        """
        r = subprocess.run([sys.executable, str(SCRIPTS / "demo.py")], capture_output=True, text=True,
                           env=_env(), cwd=ROOT, timeout=120)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        state_lines = [ln for ln in r.stdout.splitlines() if re.search(r"\bclaim state [A-Z][A-Z_]+", ln)]
        self.assertEqual(len(state_lines), 1,
                         f"expected exactly one `claim state <TOKEN>` line in demo stdout, got {state_lines!r}")
        line = state_lines[0]
        state = re.search(r"\bclaim state ([A-Z][A-Z_]+)", line).group(1)
        before_qual, qual, _rest = line.partition("(not SUPPORTED)")
        self.assertTrue(qual, f"the claim-state line carries no `(not SUPPORTED)` qualifier -- it has been "
                              f"deleted, weakened, re-polarised, or moved off this line: {line!r}")
        self.assertIn(f"claim state {state}", before_qual,
                      f"the qualifier no longer follows the claim state on its own line: {line!r}")

    def test_demo_status_line_carries_its_not_refuted_qualifier_on_that_same_line(self):
        """The F23/F24 sibling class, item `Z-demo4` -- SR-16's operator decision 1, now closed.
        `scripts/demo.py` step [4] printed `status INVARIANCE_HOLDS` BARE while steps [3] and [5] both
        carried a qualifier, and SR-16 flagged it as the kit's most quotable remaining overclaim: a reader
        who crops that line reads `INVARIANCE_HOLDS` as a proof of invariance, when the probe's actual
        finding is that it FAILED TO REFUTE invariance on twelve fixtures. `robustness.py` says so in its
        own vocabulary; the demo's stdout did not.

        Pinned ON THE STATUS LINE for the reason F23 established: an `assertIn("(not refuted", r.stdout)`
        passes when the qualifier is relocated to its own `print` or folded into the banner, and relocation
        is the exact failure a qualifier exists to prevent. The line is LOCATED rather than assumed -- the
        lines matching `status <TOKEN>` are collected and the count asserted to be exactly 1 -- so deleting
        the print, or the status from it, fails on the count instead of leaving a sweep with nothing to
        sweep.

        The seed count inside the qualifier is read off the line's OWN prose rather than hard-coded here, so
        a mutant that drops the probe to three seeds while leaving the words `these 12 fixtures` standing
        dies on the mismatch. That is the one thing a verbatim-string pin cannot catch, and the reason this
        test parses two numbers instead of asserting one sentence.
        """
        r = subprocess.run([sys.executable, str(SCRIPTS / "demo.py")], capture_output=True, text=True,
                           env=_env(), cwd=ROOT, timeout=120)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        status_lines = [ln for ln in r.stdout.splitlines() if re.search(r"\bstatus [A-Z][A-Z_]+", ln)]
        self.assertEqual(len(status_lines), 1,
                         f"expected exactly one `status <TOKEN>` line in demo stdout, got {status_lines!r}")
        line = status_lines[0]
        status = re.search(r"\bstatus ([A-Z][A-Z_]+)", line).group(1)
        before_qual, qual, _rest = line.partition("(not refuted on these ")
        self.assertTrue(qual, f"the status line carries no `(not refuted ...)` qualifier -- it has been "
                              f"deleted, weakened, re-polarised, or moved off this line: {line!r}")
        self.assertIn(f"status {status}", before_qual,
                      f"the qualifier no longer follows the status on its own line: {line!r}")
        m = re.search(r"\(not refuted on these (\d+) fixtures\)", line)
        self.assertIsNotNone(m, f"the qualifier's wording has drifted from `(not refuted on these N "
                               f"fixtures)`: {line!r}")
        declared = re.search(r"(\d+) seeds", line)
        self.assertIsNotNone(declared, f"the status line no longer declares its seed count: {line!r}")
        self.assertEqual(m.group(1), declared.group(1),
                         f"the qualifier's fixture count and the line's own seed count disagree -- one of "
                         f"the two is now false: {line!r}")

    def test_demo_verdict_line_reports_joint_supported_in_the_mandated_conditional_form(self):
        """F16 (SR-12), now closed. `docs/EVALUATION_PROTOCOL.md:126` is explicit: *"While any check in
        section 8.2 is unimplemented or unrun, JOINT_SUPPORTED is a **conditional** verdict and must be
        reported as `JOINT_SUPPORTED (conditional on deferred checks: <list>)`"*. The demo printed the bare
        token for 28 rounds. The document and the code are required by that same sentence to tell the same
        story, and they did not.

        THE VACUITY TRAP, and why this test asserts three things instead of one. `cond` is empty when
        `JointResult.complete_gate_coverage` is True, and that property is just `not self.deferred_gates`.
        So a mutant that sets `DEFERRED_GATES = ()` -- one token -- makes the parenthetical vanish
        LEGITIMATELY, and a test that compared the line against the live tuple would sweep an empty table
        and pass. That is the vacuity shape this project has now hit six times, once inside a subject. The
        guard is to assert the table is non-empty FIRST, as its own assertion with its own message, before
        any sweep over it.

        `complete_gate_coverage is False` is therefore asserted as a SHIPPED FACT, not as a derivation. If
        some future change legitimately implements, runs and passes all six deferred checks, this test is
        SUPPOSED to fail: the protocol's next sentence says an unconditional label "requires every deferred
        check to be implemented, run, passed and independently attested by QA", and a test that silently
        accommodated the unconditional form would be the mechanism by which that attestation got skipped.
        """
        r = subprocess.run([sys.executable, str(SCRIPTS / "demo.py")], capture_output=True, text=True,
                           env=_env(), cwd=ROOT, timeout=120)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        gates = _deferred_gates()
        self.assertTrue(gates, "src/toy/benchmark.py DEFERRED_GATES is empty, so `complete_gate_coverage` is "
                               "True, so the demo's conditional parenthetical disappears LEGITIMATELY and "
                               "every assertion below would be vacuously satisfied. Either every section-8.2 "
                               "check is now implemented, run, passed and QA-attested -- in which case update "
                               "docs/EVALUATION_PROTOCOL.md:126 and this test together -- or one token has "
                               "just deleted the demo's only conditionality signal")
        verdict_lines = [ln for ln in r.stdout.splitlines() if re.search(r"\bverdict [A-Z][A-Z_]+", ln)]
        self.assertEqual(len(verdict_lines), 1,
                         f"expected exactly one `verdict <TOKEN>` line in demo stdout, got {verdict_lines!r}")
        line = verdict_lines[0]
        verdict = re.search(r"\bverdict ([A-Z][A-Z_]+)", line).group(1)
        self.assertEqual(verdict, "JOINT_SUPPORTED",
                         f"this pin is written for the fixture's JOINT_SUPPORTED verdict; it now reads "
                         f"{verdict!r}, so the conditionality rule it guards may no longer apply: {line!r}")
        before_qual, qual, rest = line.partition("(conditional on deferred checks: ")
        self.assertTrue(qual, f"a JOINT_SUPPORTED verdict is printed WITHOUT the conditional form that "
                              f"docs/EVALUATION_PROTOCOL.md:126 mandates: {line!r}")
        self.assertIn(f"verdict {verdict}", before_qual,
                      f"the conditional no longer follows the verdict on its own line: {line!r}")
        named = rest.partition(")")[0]
        for gate in gates:
            self.assertIn(gate, named, f"deferred check {gate!r} is unimplemented but is not named in the "
                                       f"demo's conditional list: {line!r}")

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

    def test_the_header_discloses_every_remote_fetch_its_own_steps_make(self):
        """ROUND 8's F2, and the direction the needle test cannot cover.

        The header opened *"Nothing in this workflow reaches a remote host except the pip-install step of the
        optional-deps job"* while BOTH jobs run `actions/checkout@v4` and `actions/setup-python@v5`: the actions
        themselves, and this repository, are fetched from github.com before a test runs. The sentence was false
        for `core-no-deps` INDEPENDENTLY of hermeticity, and it is the same claim README.md retracted in the
        same round.
        test_no_withdrawn_guarantee_is_restated_in_a_comment now scans this file and catches the sentence being
        RESTATED (that is what adding the file to its scope bought). It cannot catch the disclosure being
        DELETED, which is how a presence check goes vacuous -- the defect this project has now hit four times.
        So this is derived from the workflow rather than from prose: every third-party action the steps `uses:`
        must be named in the header, and the header must say where it comes from. Add `actions/cache@v4` and
        this test asks for a sentence about it.
        """
        header = [l.lstrip("# ").rstrip() for l in self.text.splitlines() if l.startswith("#")]
        flat = re.sub(r"\s+", " ", " ".join(header))
        self.assertGreaterEqual(len(header), 10, "the normative header is gone; this test reads it")
        uses = sorted({u.split("@")[0] for u in re.findall(r"(?m)^\s*-\s*uses:\s*(\S+)", self.text)})
        self.assertGreaterEqual(len(uses), 2, f"this workflow uses {uses}: the parse has gone stale and this "
                                              f"check is vacuous")
        for action in uses:
            self.assertIn(action, flat, f"the header does not name {action!r}, which the steps fetch and run. "
                                        f"Every action a job uses is a remote fetch before any test runs, and "
                                        f"the header is where this workflow states its network behaviour.")
        self.assertIn("github.com", flat, "the header must say where the actions and the repository come "
                                          "from: both jobs fetch them from github.com before a test runs")
        # ...and the per-job claim: a job that uses an action may not be described as reaching nothing
        jobs = re.findall(r"(?m)^  ([\w-]+):$", self.text.split("\njobs:\n", 1)[1])
        self.assertEqual(sorted(jobs), ["core-no-deps", "optional-deps"], jobs)
        self.assertRegex(flat, r"BOTH JOBS[^.]*github\.com",
                         "the header states this workflow's egress and both jobs fetch from github.com; say "
                         "so about BOTH of them, not about the pip-install step alone")

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
        own_needle = 'self.skipTest("case-' + 'sensitive filesystem: a case-varied'
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

    def test_no_withdrawn_guarantee_is_restated_in_a_comment(self):
        """THE CLASS THAT HAS NOW COST FOUR ROUNDS: a guarantee this project withdrew, still asserted as current
        prose. A docstring assertion cannot reach a comment and neither can a doc grep, so the only thing that
        can keep prose honest is a source-text test over the prose itself.

        The occasion was `tests/toy_tests/test_scripts.py`, which carried *"It says 'not on PATH' rather than
        'not installed' on purpose: torch mode denies the latter on EVERY skip, tool skips included, so the
        category cannot launder a missing package"* while `docs/CLEAN_CLONE.md` had explicitly retracted exactly
        that reasoning (*"that is a courtesy to the reader and **not** the anti-laundering defence"*). The same
        round found `scripts/run_tests.sh` defining soundness as *"an exemption is sound only while it cannot be
        spent on hiding a package skip. One rule makes it sound"* -- false: any reason naming no package collects
        the exemption, up to TOOL_CAP (4) and FS_CAP (8), so the caps and the baseline are the real bound.

        Each needle below is a withdrawn claim. It may appear ONLY where a marker stands before it IN ITS OWN
        SENTENCE, and it must still appear somewhere -- deleting the record is how the same sentence comes back.

        TWO THINGS WERE SHORT ABOUT THIS CHECK FOR THREE ROUNDS RUNNING, AND BOTH WERE ENUMERATIONS. The scope
        was a list of FILES, and the marker rule was a per-needle LINE WINDOW. Round 10 closed both.

        (1) THE FILE LIST IS NOW DERIVED (`_normative_prose_files`). It was widened to `docs/CLEAN_CLONE.md` in
        round 7 -- *"the project invented this discipline and left the hole exactly where its normative document
        lives"* -- and to `.github/workflows/ci.yml` in round 9, and it was still short: MEASURED on the round-9
        tree, the unmarked sentence ``...cannot launder a missing package, and nothing leaves the host.`` added
        to `scripts/lint.sh`'s 43-line normative header, or to `README.md`, or to both, left this test GREEN in
        every case -- and `README.md` is the file that retracted "nothing leaves the host" in the first place,
        while being checked for exactly one unrelated needle by another test. An enumeration is short by exactly
        the files nobody thought of, so there is nothing left here to think of: the scope is every tracked file
        except the journal `CLAUDE.md` designates, and the assertion below that NOTHING tracked is outside the
        scope but that journal is what keeps the derivation from quietly shrinking.

        (2) THE WIDTHS ARE GONE; EVERY NEEDLE IS HELD TO THE SENTENCE RULE. A line window cannot adjudicate a
        claim whose own line carries an unrelated marker -- round 8's F3: `scripts/run_tests.sh` read
        ``"connection refused" from the local stack and nothing leaves the host. It used to be 192.0.2.1:9``,
        the phrase README.md retracted beside a CORRECT history note about a different fact, on ONE line, and it
        passed at every half-width from 0 to 7 (measured on that line). Widening MARK is not the answer, and
        nor is a width: a marker's distance is a property of PROSE and moves whenever a paragraph is rewritten,
        which was measured three times in a single round (one needle failed at 0-4 and passed from 5; one had a
        minimum width of 2 where the note here claimed 6; one moved to another file twice). The `ci.yml` ceiling
        had already promoted a whole file to the sentence rule for a fourth reason -- that header is itself dense
        with CORRECT retraction markers, so an unmarked ``cannot launder`` added to it PASSES at +-6 and FAILS
        under the sentence rule -- and the general form of that lesson is that a line window is only as good as
        the sparsity of markers around it. So the rule is now one rule: the marker must appear BEFORE the needle
        and INSIDE ITS OWN SENTENCE, in the prose block joined across the hard wrap (`_comment_units`,
        `_sentence_lead`). MEASURED COST, and it is the whole cost: four live sentences in this kit had to be
        reworded to satisfy it (one in `scripts/run_tests.sh`, one in `.github/workflows/ci.yml`, two in
        `docs/CLEAN_CLONE.md`), each because a `.` or an ellipsis inside a quotation split the sentence and left
        the marker in the previous one.

        TWO RESIDUES, STATED RATHER THAN HIDDEN, AND BOTH ARE OPEN. One sentence that both asserts a withdrawn
        claim and marks it as history satisfies this rule, as it satisfies any window -- measured GREEN in
        `ci.yml` with *"This header used to say nothing leaves the host, and nothing leaves the host."*; reading
        prose is not on offer. And a `.py` file is read for FULL-LINE comments only: widening it to docstrings
        and trailing comments immediately flags `src/toy/robustness.py:62` (*"`dataclasses.replace` cannot
        launder a summary that was tampered with"*) and `tests/toy_tests/test_benchmark.py:498`
        (*"# cannot launder a primary id either"*) -- two innocent uses of the same two words in a different
        domain, in files this discipline does not own -- so closing that boundary needs needles specific to the
        skip policy, which `cannot launder` is not.
        """
        MARK = re.compile(r"used to|was false|WHAT IS NOT TRUE|withdrawn|no longer|retract|NOT the anti|"
                          r"it was false|FALSE for", re.I)
        # needle -> why it is withdrawn. THERE IS NO WIDTH COLUMN ANY MORE: see the docstring.
        NEEDLES = {
            "cannot launder": "the category's anti-laundering guarantee (withdrawn in docs/CLEAN_CLONE.md: "
                              "the wording is a courtesy to the reader, not the defence)",
            "hide a torch test": "the filesystem-case exclusion's claim that it cannot hide a torch test (an "
                                 "exemption can; the bound is FS_CAP and the baseline)",
            "cannot be spent on hiding a package skip": "the definition of a SOUND exemption as one no reason "
                                                        "can spend (the caps are the bound, not the rule)",
            'contains "case-sensitive"': "the filesystem-case category as a reason CONTAINING `case-sensitive` "
                                         "-- round 6's F1 defect, deleted. The live rule is the anchored "
                                         "phrase in EXEMPT_CATEGORIES",
            "as a word and as a prefix": "the package rule as a word-plus-prefix test -- `PKG_EXEMPT` is a "
                                         "CONTAINMENT test, which is what catches `libtorch`",
            "nothing leaves the host": "egress as a property of the host rather than of the ADDRESS the script "
                                       "asks for -- retracted in README.md; hermeticity is unattested and no "
                                       "network-denied run exists",
            # ROUND 10: the SHORTER needle, because the rephrasing that mattered was not covered. `ci.yml`
            # used to assert that no step which runs the scripts "reaches a remote host" -- arrival, which is
            # the retracted property, not the address asked for -- rescued only by the sentence after it, so a
            # reader who stopped at the colon got the claim README.md withdrew. The longer needle below stays
            # as well: it is the exact wording of round 8's F2 and its record has to survive.
            "reaches a remote host": "egress stated as ARRIVAL at a remote host rather than as the address a "
                                     "step asks for -- the property README.md retracted; the suite tests the "
                                     "address, and no job has ever run network-denied",
            "reaches a remote host except the pip-install step":
                "the workflow's egress claim -- BOTH jobs fetch actions/checkout@v4, actions/setup-python@v5 "
                "and the repository from github.com before any test runs",
            "no packet reaches an interface":
                "loopback traffic DOES traverse `lo`; the careful claim in docs/CLEAN_CLONE.md is that no "
                "packet reaches a NETWORK interface",
        }
        scope, binary = _normative_prose_files()
        self.assertEqual(binary, [], f"tracked file(s) {binary} are not UTF-8 text, so the derived scope of "
                                     f"this scan silently skips them. Decide deliberately: either they cannot "
                                     f"carry prose, in which case teach _normative_prose_files to say so, or "
                                     f"they can, in which case give them a reading rule.")
        rels = [rel for rel, _ in scope]
        # THE DERIVATION IS THE CLAIM, so it is asserted in both directions. Forward: the two files round 10
        # found missing must be in the scope, and so must every file an earlier round had to widen it to --
        # DERIVED, not listed, which is why these are assertions about the derivation rather than its content.
        for must in ("README.md", "scripts/lint.sh", "scripts/run_tests.sh", "docs/CLEAN_CLONE.md",
                     ".github/workflows/ci.yml", "tests/toy_tests/test_scripts.py"):
            self.assertIn(must, rels, f"{must} is not in the derived scope of the withdrawn-guarantee scan. "
                                      f"The scope is every tracked file minus the journal; if {must} is no "
                                      f"longer tracked, say so deliberately here.")
        # Backward: nothing tracked is outside the scope EXCEPT the designated journal. This is what the
        # enumeration could never have: a file cannot be left out by being forgotten, only by being named in
        # CLAUDE.md as the journal.
        self.assertEqual(sorted(set(_tracked()) - set(rels)), sorted(_journal_files()),
                         "the derived scope no longer covers every tracked file but the journal. The scan has "
                         "gone short three times by enumeration; the only permitted exclusion is the file "
                         "CLAUDE.md designates as the durable journal.")
        self.assertGreater(len(rels), 20, f"the derived scope holds only {len(rels)} files; `git ls-files` or "
                                          f"the derivation has gone wrong and this scan is near-vacuous")
        hits = dict.fromkeys(NEEDLES, 0)
        for rel, comments_only in scope:
            for start, text in _comment_units(ROOT / rel, comments_only):
                for needle, why in NEEDLES.items():
                    for m in re.finditer(re.escape(needle), text):
                        hits[needle] += 1
                        self.assertRegex(
                            _sentence_lead(text, m.start()), MARK,
                            f"{rel}, in the block beginning at line {start}, asserts a WITHDRAWN guarantee as "
                            f"if it were current -- {why}. The marker must stand BEFORE the claim IN THE SAME "
                            f"SENTENCE: a marker in the next sentence belongs to a different claim, which is "
                            f"how round 8's F3 passed a line window of any width, and a line window of any "
                            f"width is only as good as the sparsity of markers around it. Mark it as history "
                            f"or delete it. (Watch for a `.` or an ellipsis INSIDE a quotation: it splits the "
                            f"sentence and leaves the marker in the previous one -- that is what four live "
                            f"sentences in this kit had to be reworded for.)")
        # ...and the record of each must survive SOMEWHERE in the scope: the first needle was only ever
        # asserted in this file and the second only in the runner, so the presence check is over the whole
        # derived scope. Deleting a record is how the same sentence comes back a round later, and how this
        # check goes vacuous.
        for needle, n in hits.items():
            self.assertGreaterEqual(n, 1, f"no file in the derived scope records the withdrawn guarantee "
                                          f"{needle!r} any more: {NEEDLES[needle]}. It was deleted rather than "
                                          f"marked as history, and this check now proves nothing.")

    def test_the_normative_skip_policy_section_states_the_rules_the_script_really_applies(self):
        """ROUND 7's F4: the needle tests over docs/CLEAN_CLONE.md check PRESENCE, never CURRENCY.

        Every disclosure test in this class asks "is this string in the document?", which a deleted rule
        satisfies as happily as a live one -- and the normative skip-policy section stated two deleted rules as
        current for a round. So this one DERIVES what the section must say from the script:

          * each declared category's PHRASE, spelled as the policy spells it (the name group shown as `<name>`),
            must appear in that section, so changing the phrase in `EXEMPT_CATEGORIES` without changing the
            document is a red suite rather than a silently stale sentence;
          * the section must describe each category as a reason that BEGINS with its phrase -- the anchor is
            precisely what both withdrawn rules got wrong, in both directions ("contains" for FS, "a word and a
            prefix" for the package rule);
          * `PKG_EXEMPT` is read out of the script and required to be a bare containment pattern (no `\\b`), and
            only then is the section required to call it a containment rule. If the script ever goes back to a
            word or prefix test, this fails HERE with the script named, instead of leaving the document to be
            re-checked by hand.

        It cannot prove the section is true -- no test can -- only that the three load-bearing nouns in it are
        the ones the script is built from. test_no_withdrawn_guarantee_is_restated_in_a_comment covers the
        opposite direction: the deleted wordings may appear only as history.
        """
        doc = (ROOT / "docs" / "CLEAN_CLONE.md").read_text(encoding="utf-8")
        head = "Skip-reason policy"
        self.assertIn(head, doc, "docs/CLEAN_CLONE.md no longer has a 'Skip-reason policy' section; this test "
                                 "reads it and must be updated with the document")
        sec = re.split(r"\n#{2,4} ", doc.split(head, 1)[1], maxsplit=1)[0]
        flat = re.sub(r"\s+", " ", sec)                      # the document is hard-wrapped and list-indented
        self.assertGreaterEqual(len(flat), 500, "the parsed section is almost empty; the split has gone stale")
        for c in EXEMPT_CATS:
            display = re.sub(r"\s+", " ", re.sub(r"\([^)]*\)", "<name>", c.phrase[2:-2]))
            with self.subTest(category=c.token):
                self.assertIn(display, flat,
                              f"the {c.token} category's phrase is {c.phrase!r} in scripts/run_tests.sh and the "
                              f"skip-reason policy section of docs/CLEAN_CLONE.md does not state it "
                              f"({display!r}). The document is what a clean clone is sent to; a phrase that "
                              f"lives in one place and is described in another is how this project's last three "
                              f"documentation defects happened.")
        self.assertGreaterEqual(flat.count("begins with"), len(EXEMPT_CATS),
                                "the skip-reason policy section does not describe every exemption category as a "
                                "reason that BEGINS with its phrase; the anchor is the guard both withdrawn "
                                "descriptions of these rules got wrong")
        script = (SCRIPTS / "run_tests.sh").read_text(encoding="utf-8")
        m = re.search(r"(?m)^PKG_EXEMPT = re\.compile\((.*)\)\n", script)
        self.assertIsNotNone(m, "scripts/run_tests.sh no longer defines PKG_EXEMPT on one line; this test reads "
                                "it to decide what the documentation must say about it")
        self.assertNotIn(r"\b", m.group(1),
                         "PKG_EXEMPT is no longer a bare containment pattern. docs/CLEAN_CLONE.md is required "
                         "below to call it a containment rule; change the document deliberately with it.")
        self.assertIn("containment", flat,
                      "PKG_EXEMPT is a containment test in scripts/run_tests.sh and the skip-reason policy "
                      "section of docs/CLEAN_CLONE.md does not say so")

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
        else:
            # F20, HALF (ii). A test ABOUT the pytest stage must CONTROL the plugin environment rather than
            # inherit it. Four tests here drive that stage (`POLICY:PYTEST_FAILED`, `PYTEST_COLLECTED`,
            # `PYTEST_SKIPPED` x2) and all four read the host's `pytest11` entry points, because pytest
            # autoloads every installed plugin. Measured on this project's conda CPython 3.13.5: all four
            # FAIL, with the sub-run's log carrying `OSError: Could not find/load shared object file
            # 'libllvmlite.dylib'` from a broken numba/llvmlite install OUTSIDE this repository; the same
            # crash reproduces from `python3 -m pytest -q .` in an empty directory holding one trivial
            # passing test, so it is a property of the host and not of this kit. The fixtures below inject
            # their OWN pytest outcome; a third-party plugin dying at collection replaces that fixture with
            # noise and the assertion then measures the laptop. `e.pop` above deliberately strips the
            # variables the SCRIPT must set -- this one is not among them, it is a property of the
            # EXPERIMENT, so it is set here unconditionally and does not depend on the caller's shell.
            e["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
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

    def test_a_captured_ran_line_does_not_understate_the_total_f22(self):
        """F22, SITE 2, BEHAVIOURALLY. `summarize()` and `policy()` both matched `^Ran (\\d+) tests?` with
        `re.search`, which takes the FIRST match. A log can hold more than one such line: a test that
        captures a sub-run's transcript and prints it embeds that sub-run's `Ran N tests`, and unittest's
        own summary comes last, after every test has finished. So first-match reads the WRONG total.

        `docs/CLEAN_CLONE.md` declared this fix and wrote that it "must therefore touch BOTH sites". Both
        sites were unchanged -- the declaration shipped inside the very commit that marked the task. That is
        F22, and an unpinned fix would repeat it, so this exists.

        Driven by a test module that prints a plausible captured `Ran 3 tests` line while the real total is
        4. This test FAILED against the first version of the fix and is the reason the rule changed.

        THE RULE `docs/CLEAN_CLONE.md` PRESCRIBED -- "take the last match rather than the first" -- IS ALSO
        WRONG, and this fixture is what showed it. Position in the log is not information: unittest writes
        its summary to stderr unbuffered, while this module's `print` goes to block-buffered stdout and is
        flushed at exit, so in the redirected log the REAL total appears at line 3 and the printed decoy at
        line 6. First-match happened to be right here; last-match was wrong. For a test whose SUBPROCESS
        writes to the inherited fd, the order is genuinely chronological and the opposite holds. Neither
        position is reliable.

        What is reliable is unittest's summary BLOCK: `separator2`, 70 dashes, written immediately before
        `Ran N tests` on the same stream. See `_ran_totals` in the script.
        """
        body = ("import unittest\n"
                "class T(unittest.TestCase):\n"
                "    def test_prints_a_captured_transcript(self):\n"
                "        print('Ran 3 tests in 0.001s')\n"
                "        print('OK')\n"
                "    def test_b(self): pass\n"
                "    def test_c(self): pass\n"
                "    def test_d(self): pass\n")
        r = self.rt({"test_a.py": body})
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        m = re.search(r"^unittest: ran=(\d+) ", r.stdout, re.M)
        self.assertIsNotNone(m, f"no `unittest: ran=` line in stdout:\n{r.stdout}")
        self.assertEqual(m.group(1), "4",
                         f"the script read a captured `Ran 3 tests` line as this run's total -- the "
                         f"first-match regex of F22 is back:\n{r.stdout}")

    def test_both_f22_sites_take_the_last_ran_match_not_the_first(self):
        """F22, BOTH SITES, STRUCTURALLY -- and an admission about why this one is structural.

        Site 2 (`summarize()`) is pinned behaviourally by the test above, through `unittest: ran=`. SITE 1
        (`policy()`, feeding `ran_log` and the `POLICY:RECORDER` check `if len(starts) < ran_log`) HAS NO
        REACHABLE OBSERVABLE: understating `ran_log` only ever SILENCES that check, and making it speak
        requires the recorder to have seen fewer tests than unittest ran, which is a state this suite
        cannot arrange without introducing the very defect RECORDER exists to catch. `CLEAN_CLONE.md`
        measured the asymmetry by driving `policy()` with two crafted logs and found it "does mask a real
        check -- just never one that could change a verdict", because the captured transcript only exists
        when a test already failed, so POLICY:UNITTEST_FAILED fires and the run is red either way. What
        degrades is the diagnosis.

        So this test asserts the SHAPE at both sites, and that is a weaker thing than a measurement -- a
        count of a construct is not a measurement of its behaviour, which this project has learned the hard
        way. It is recorded as the honest best available for site 1, not as equivalent to the pin above.
        """
        text = (SCRIPTS / "run_tests.sh").read_text(encoding="utf-8")
        self.assertEqual(re.findall(r're\.search\(r"\^Ran ', text), [],
                         "a `^Ran` site is back to re.search, which takes the FIRST match in a log whose "
                         "ordering is not chronological")
        self.assertEqual(len(re.findall(r"_ran(?:_all)?\s*=\s*_ran_totals\(", text)), 2,
                         "expected exactly 2 call sites of _ran_totals in run_tests.sh -- policy(), which "
                         "feeds ran_log and POLICY:RECORDER, and summarize(), which feeds RAN. If a site "
                         "was added or removed, this pin and docs/CLEAN_CLONE.md must move together: F22 "
                         "was precisely a declared two-site fix that touched neither.")
        self.assertEqual(len(re.findall(r"_ran(?:_all)?\[-1\]", text)), 2,
                         "both `^Ran` sites must index [-1]; one of them stopped taking the last match")
        self.assertEqual(text.count("def _ran_totals(text):"), 2,
                         "_ran_totals must be defined in BOTH heredocs -- they are separate python "
                         "processes and cannot share a definition, which is exactly how F22's two sites "
                         "drifted apart in the first place")
        self.assertEqual(len(re.findall(r'\^-\{10,\}\\nRan \(\\d\+\) tests\?', text)), 2,
                         "the dash-anchored pattern is gone from a site: position in the log is not "
                         "information (stdout is block-buffered, stderr is not), so only unittest's "
                         "separator2 + `Ran N` block identifies the real total")

    def _fake_pytest_root(self, pytest_body, n=3):
        """A throwaway repo root whose own `pytest.py` SHADOWS the installed pytest.

        `python3 -m pytest` puts the cwd first on `sys.path`, so a `pytest.py` beside the copied script is
        what `-m pytest` executes -- while `python3 -c "import pytest"`, which the script uses to decide
        whether the stage runs at all, imports the SAME file as a module. So the body must import cleanly
        and misbehave only under `__main__`. That is the only way to drive the pytest stage's failure
        branches without installing a broken plugin on the machine running these tests, which is the whole
        point: F20 is about a host this kit does not control.
        """
        # Own uniquely-named root rather than `synth_root`, which hardcodes one directory name and so can
        # only be called once per test -- and this test needs TWO roots, because its negative control is
        # not optional.
        root = self.dir / f"fakepytest{len(list(self.dir.glob('fakepytest*')))}"
        (root / "scripts").mkdir(parents=True)
        (root / "tests").mkdir()
        shutil.copy2(RUN_TESTS, root / "scripts" / "run_tests.sh")      # copy2 keeps the executable bit
        (root / "tests" / "test_a.py").write_text(_pass_module(n), encoding="utf-8")
        (root / "pytest.py").write_text(pytest_body, encoding="utf-8")
        e = _env(PATH=f"{self.shim}:{os.environ.get('PATH', '')}", MIN_TESTS="1")
        for k in ("PYTHONHASHSEED", "PYTHONPATH", "PYTHONDONTWRITEBYTECODE"):
            e.pop(k, None)
        e["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"      # the REAL pytest is not what runs here; be explicit
        return subprocess.run([str(root / "scripts" / "run_tests.sh"), "--baseline", "none"],
                              capture_output=True, text=True, env=e, cwd=str(root), timeout=180)

    def test_pytest_dying_before_collection_is_UNUSABLE_and_not_a_suite_failure(self):
        """F20, half (i), and the token `POLICY:PYTEST_UNUSABLE`.

        AN OPTIONAL TOOL THAT IS PRESENT BUT BROKEN MUST CHANGE WHICH CHECKS RUN, NEVER WHETHER THE SUITE
        PASSES. `README.md` records this kit getting the ABSENT case wrong once -- "for one round the
        commands below failed on any machine without `ruff`" -- and present-but-broken was the uncovered
        half of that same sentence. Measured on this project's conda CPython 3.13.5 before the fix:
        `./scripts/run_tests.sh --expect any` ended `RESULT: FAIL` with `POLICY:PYTEST_FAILED` and
        `POLICY:PYTEST_COLLECTED pytest collected 0 tests`, because a numba/llvmlite plugin OUTSIDE this
        repository died at collection with `OSError: Could not find/load shared object file
        'libllvmlite.dylib'`. The same crash reproduced from `python3 -m pytest -q .` in an empty directory
        holding one trivial passing test, so it was a property of the host, not of this kit.

        THE NEGATIVE CONTROL IS THE POINT OF THIS TEST, not the positive case. A branch that forgives a
        crashing pytest is one sloppy condition away from forgiving a REAL red pytest, which is the
        opposite error and the worse one. So the second half drives a pytest that genuinely collects and
        genuinely fails, and requires it to STILL be fatal.
        """
        crash = ('import sys\n'
                 'if __name__ == "__main__":\n'
                 '    sys.stderr.write(\'ImportError while loading entry point "numba"\\n\'\n'
                 '                     \'  File "/opt/miniconda3/lib/python3.13/site-packages/llvmlite/'
                 'binding/ffi.py", line 170\\n\'\n'
                 '                     "OSError: Could not find/load shared object file "\n'
                 '                     "\'libllvmlite.dylib\'\\n")\n'
                 '    sys.exit(4)\n')
        r = self._fake_pytest_root(crash)
        self.assertIn("POLICY:PYTEST_UNUSABLE", r.stdout,
                      "a pytest that died before collection was not classified UNUSABLE:\n" + r.stdout)
        self.assertIn("RESULT: OK", r.stdout,
                      "a broken third-party plugin turned the suite RED, which is F20 itself:\n" + r.stdout)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertNotIn("POLICY:PYTEST_FAILED", r.stdout)
        self.assertNotIn("POLICY:PYTEST_COLLECTED", r.stdout)
        self.assertIn("authoritative", r.stdout)            # the note says the unittest leg still stands
        self.assertIn("OSError", r.stdout)                  # and it SHOWS the offending output, loudly

        # NEGATIVE CONTROL: pytest collected and failed FOR REAL. Still fatal, by every token.
        #
        # THIS CONTROL WAS TOO WEAK AT FIRST AND A MUTANT PROVED IT. The earlier version printed only
        # `collected 1 item` / `1 failed`, with no package path anywhere -- so a mutant that DELETED the
        # `PT_TOTAL -eq 0` and `no collected line` conditions SURVIVED: its remaining condition (a
        # traceback naming an installed package) was never satisfied by this fixture, so the branch did
        # not fire either way and the assertions below passed for the wrong reason.
        #
        # The realistic shape is the one that matters: a genuine test failure whose traceback passes
        # THROUGH an installed library shows site-packages paths, which is common and is exactly what the
        # widened discriminator would forgive. The fixture now carries one, so every condition the branch
        # tests is exercised and dropping any of them is fatal to this test.
        real_red = ('import sys\n'
                    'if __name__ == "__main__":\n'
                    '    print("collected 1 item")\n'
                    '    print("")\n'
                    '    print("=================================== FAILURES ===================================")\n'
                    '    print("_______________________________ test_division ________________________________")\n'
                    '    print("  File \'/opt/miniconda3/lib/python3.13/site-packages/numpy/_core/'
                    'fromnumeric.py\', line 3504, in mean")\n'
                    '    print("ZeroDivisionError: division by zero")\n'
                    '    print("1 failed in 0.01s")\n'
                    '    sys.exit(1)\n')
        r2 = self._fake_pytest_root(real_red)
        self.assertNotIn("POLICY:PYTEST_UNUSABLE", r2.stdout,
                         "a REAL pytest failure was forgiven as UNUSABLE -- the discriminator is too "
                         "broad, which is a worse defect than F20:\n" + r2.stdout)
        self.assertIn("POLICY:PYTEST_FAILED", r2.stdout)
        self.assertNotIn("RESULT: OK", r2.stdout)
        self.assertNotEqual(r2.returncode, 0)

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
        # An EMISSION is `POLICY:<NAME>` followed by whitespace (the message) or by a closing quote (a token
        # carried in a tuple and printed by the caller). The lookahead is what keeps the script's own prose out:
        # the header writes the placeholder `POLICY:<NAME>`, a comment writes the wildcard `POLICY:BASELINE_*`,
        # and neither is a token. (Without it the wildcard read as `BASELINE`.)
        tokens = set(re.findall(r'POLICY:([A-Z_]+)(?=["\s])', script))
        # ...PLUS the tokens the policy builds from `EXEMPT_CATEGORIES`, which no regex over the script can see
        # because the script spells them `f"POLICY:{_tok}_CAP ..."`. THIS IS THE FAIL-CLOSED PART, and the
        # round-6 reason for it: a category added to that tuple brings a cap token (and, if its phrase carries a
        # name, an undeclared-name token) that some test in this file must assert, or this check goes red with
        # the token named. A category cannot arrive with tests nobody wrote.
        for c in EXEMPT_CATS:
            tokens.add(f"{c.token}_CAP")
            if c.anchored.groups:
                tokens.add(f"{c.token}_UNDECLARED")
        tokens = sorted(tokens)
        # ANTI-VACUITY, in two parts, because the one part it had was off by one: `>= 24` against a script that
        # emits 25, so a token could be deleted and the floor still passed. The floor is now the real count
        # (raise it when a token is added; it must never be lowered). 25 -> 26 with POLICY:TOOL_UNDECLARED,
        # 26 -> 27 with POLICY:EXEMPT_AMBIGUOUS.
        self.assertGreaterEqual(len(tokens), 27, tokens)
        # ...and, derived rather than typed, EVERY `POLICY:` occurrence in the script is accounted for: each is
        # either an emission the strict regex above found, or one of the two documented non-emissions -- the
        # header's `POLICY:<NAME>` placeholder and a comment's `POLICY:BASELINE_*` wildcard. This is the half the
        # floor was standing in for: if the strict regex stops matching (the real hazard -- a token count is not
        # a bug, a broken regex is), the occurrences it no longer explains fail here whatever the count.
        # The placeholders and TEMPLATES that are not tokens: the header's `POLICY:<NAME>`, a comment's
        # `POLICY:BASELINE_*` wildcard, the two `POLICY:<TOKEN>_*` forms the header uses to describe a category's
        # tokens generically, and the two f-string templates the policy really emits them through -- whose
        # EXPANSIONS are required above, derived from EXEMPT_CATEGORIES rather than read out of the text.
        NON_EMISSIONS = {"<NAME>", "BASELINE_*", "<TOKEN>_CAP", "<TOKEN>_UNDECLARED",
                         "{_tok}_CAP", "{tok2}_UNDECLARED"}
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
        #
        # THE LAST TWO CASES ARE THE ANCHOR, and they are here because the six candidates above DO NOT TEST IT.
        # Every one of those is rejected by something else: four never contain the phrase at all, and the two
        # `PATHological` ones are rejected by the trailing `\b`, with or without an anchor. The table had no case
        # with LEADING PROSE and a clean `is not on PATH` ending, so nothing exercised the anchor. These two do,
        # and they name a DECLARED tool (`ruff`) so that the TOOLS allowlist cannot be what rejects them either.
        #
        # MEASURED, and it corrects the mutant the defect report named. The anchor is written twice (`\A` in the
        # runner's `TOOL` pattern and `.match` at the call site) and the two terms are MUTUALLY REDUNDANT: `\A`
        # matches only at position 0, so `.search` on an `\A` pattern IS `.match`, and `.match` on a pattern
        # without `\A` is anchored by the method. So
        #   S3   drop `\A`, keep `.match`                 -> EQUIVALENT mutant, SURVIVED (proves nothing)
        #   S3b  keep `\A`, `.match` -> `.search`         -> EQUIVALENT mutant, SURVIVED (proves nothing)
        #   S3c  BOTH, i.e. the round-4 hole verbatim     -> KILLED by the two cases below
        #   S3c with these two cases deleted              -> SURVIVED
        # The last line is the masking that was reported, and it was real; the single-term mutants were not
        # evidence of it, because neither changes any verdict. A control run (the two cases deleted, the script
        # unmutated) passes, so the SURVIVED verdict belongs to the mutant and not to the edit.
        r = self.rejects_each(["optional developer tool is not on PATH", "ruff is not installed (optional linter)",
                               "optional linter absent", "developer tool `ruff` missing",
                               "an optional developer tool `ruff` is not on PATHological systems",
                               "optional developer tool `ruff` is not on PATHological systems",
                               "note: optional developer tool `ruff` is not on PATH",
                               "the suite reports: " + self.TOOL_REASON], expect="none")
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
        # ...and (3) the WORD BOUNDARY in `PKG` is evadable, so the tail check is a PREFIX test (`PKG_EXEMPT`):
        # `\btorch\b` does not match `torchrun`, which is PyTorch's own console script, nor `torchvision`,
        # `numpy2` or `pytestx`. Measured: `the live ruff reason + "; torchrun is gone"` and
        # `case-sensitive filesystem ...; torch2 is gone` BOTH collected the exemption in `--expect none` and
        # `--expect torch` before `PKG_EXEMPT` existed. Derived from the same tuple, so a package added to the
        # script is laundered past the suffixes too, not just past the bare word.
        # ROUND 6: THIS TABLE ENUMERATED ONLY SUFFIXES, and that is exactly the half a PREFIX test closes.
        # `\btorch\b` does not match `torchrun` and the prefix rule caught it; but there is no `\b` before
        # `torch` in `libtorch` either, so the prefix rule could not catch THAT -- and `libtorch` and `_torch`
        # appear ninety lines below as tool NAMES, where the allowlist rejects them, which is how the gap stayed
        # invisible: the names were in the file, in the wrong table. Measured EXEMPT on the live script in all
        # three modes, as a tail on BOTH categories: `; libtorch is gone`, `; _torch is gone`, `; mytorch is
        # gone`. The rule is a CONTAINMENT test now and the table carries the prefix and infix forms with the
        # suffix ones.
        for pkg in POLICY_PKGS:
            for affixed in (f"{pkg}run", f"{pkg}2", f"{pkg}vision", f"py{pkg}x", f"{pkg}_geometric",
                            f"lib{pkg}", f"_{pkg}", f"my{pkg}", f"x{pkg}x"):
                tails += [self.TOOL_REASON + f"; {affixed} is gone", self.FS_REASON + f"; {affixed} is gone"]
        self.rejects_each(tails, expect="torch")
        # THE RESIDUE, measured rather than argued: containment is a SUBSTRING rule, so a name spelled with a
        # character the name does not contain keeps the exemption. `t0rch` is exempt on both categories, in
        # every mode, and so is any reason that describes a package without naming it. Asserted as ACCEPTED so
        # that the sentence in scripts/run_tests.sh which says so cannot drift: the bound on it is the caps and
        # the baseline, not the spelling rule. (docs/CLEAN_CLONE.md, "What is still exempt, stated plainly".)
        for reason in (self.TOOL_REASON + "; t0rch is gone", self.FS_REASON + "; t0rch is gone",
                       self.FS_REASON + "; the deep-learning framework is gone"):
            with self.subTest(residue=reason):
                self.ok(self.rt({"test_a.py": _pass_module(1),
                                 "test_r.py": _skip_module(1, reason, cls="R", prefix="test_r")}, expect="any"))

    def test_the_TOOLS_allowlist_is_exactly_the_tools_this_suite_gates_on(self):
        """THE FIFTH SR-15 FAIL: `PKG` is a spelling rule, and its word boundaries are evadable.

        As the only gate on the tool exemption, `\\b(?:py)?(?:torch|numpy|yaml|pytest)\\b` is an OPEN set --
        every name that is not one of those four words collected the exemption. Measured on the LIVE script,
        EXEMPT in `--expect none` AND `--expect torch`:

            optional developer tool `torchrun` is not on PATH     <- PyTorch's own console script
            optional developer tool `libtorch` is not on PATH     <- its C++ distribution
            ... and torchvision, torchaudio, torch_geometric, torch2, _torch, numpy2, pytestx, mypy, black,
                yamllint, ruff.exe, ruff-0.4

        Round 4's defect was ``optional developer tool `torch` is not on PATH`` -- ONE SUFFIX from the first two.
        A negative rule ("does this name look like a package?") cannot close an open set; a positive one can,
        because the tools this suite really gates a test on are a closed set of size one.

        THIS TEST IS THE DERIVATION. The allowlist is declared in exactly one place (`TOOLS` in
        scripts/run_tests.sh, which the policy reads) and is required here to EQUAL the set of tool-gated skip
        sites parsed out of the live decorators and `skipTest` calls in tests/toy_tests/. So:
          * a NEW tool-gated test fails here, naming the tool and the tuple to declare it in -- and fails at
            runtime as POLICY:TOOL_UNDECLARED in every mode, never a silent exemption;
          * a name left in the tuple after its test is deleted fails here too, so the allowlist cannot grow
            stale permissions.
        """
        gates, sites = _suite_tool_gates()
        self.assertGreaterEqual(sites, 10, "the skip-site scan found almost no literal skip reasons: "
                                           "_suite_tool_gates has stopped looking (a renamed skip helper, or "
                                           "reasons that are no longer literals) and this check is vacuous")
        self.assertIn("ruff", gates, "the suite's one real tool gate -- the behavioural half of the fatal-ruff "
                                     "guarantee -- is no longer found by the scan")
        self.assertEqual(sorted(gates), sorted({t.lower() for t in POLICY_TOOLS}),
                         f"the TOOLS allowlist in scripts/run_tests.sh is {sorted(POLICY_TOOLS)} while this "
                         f"suite gates tests on {dict(gates)}. DECLARE the tool in that tuple (with a test that "
                         f"drives it), or delete a name whose test is gone. Do NOT widen the phrase: an "
                         f"undeclared name is POLICY:TOOL_UNDECLARED at runtime, which is the loud failure this "
                         f"equality exists to produce.")
        # the allowlist is a set of NAMES, not of patterns: a regex-looking entry would reopen the open set
        for t in POLICY_TOOLS:
            self.assertRegex(t, r"\A[\w.+-]+\Z", f"TOOLS entry {t!r} is not a plain tool name")

    def test_every_named_categorys_allowlist_is_exactly_the_names_this_suite_gates_on(self):
        """ROUND 7's F1: the allowlist/gating-site equality was bound to the `TOOLS` TUPLE, not to the REGISTRY
        ROW the policy reads.

        test_the_TOOLS_allowlist_is_exactly_the_tools_this_suite_gates_on compares the gate set against
        `POLICY_TOOLS`, parsed from the `TOOLS = (...)` line, and `_policy_exempt_categories` resolves a Name in
        the allowlist column through `resolvable = {"TOOLS": POLICY_TOOLS}` with an error message that explicitly
        blesses "declare it as a literal". So a ONE-TOKEN change at the TOOL row --

            ("TOOL", r"...", 4, "TOOLS", TOOLS, ...)  ->  ("TOOL", r"...", 4, "TOOLS", ("ruff", "shellcheck"), ...)

        -- left `TOOLS = ("ruff",)` literally true, the comment in .github/workflows/ci.yml true, and that
        equality GREEN, while `shellcheck` was exempt in all three modes, in the TOOL bucket, excluded from the
        package-skip floor, the torch cap and the baseline, with NO POLICY token. (Control on the unmodified
        copy: `POLICY:TOOL_UNDECLARED` in all three modes.) Round 6 generalised the GUARDS to a registry and left
        the DERIVATION bound to one hand-named tuple.
        The property asserted here is the generalised one, and it is the eighth guard a future named category
        gets for free: for EVERY declared category whose phrase carries a name, the allowlist in its own row
        equals the set of names the suite's own skip sites gate on. The opposite direction -- a site that carries
        a phrase must claim the category -- is
        test_every_declared_exemption_category_is_claimed_properly_by_the_sites_that_use_it.
        """
        sites = _suite_skip_sites()
        self.assertGreaterEqual(len(sites), 10, "the skip-site scan found almost no literal skip reasons: "
                                                "_suite_skip_sites has stopped looking and this check is vacuous")
        named = [c for c in EXEMPT_CATS if c.anchored.groups == 1]
        self.assertTrue(named, "no declared category carries a name, so this derivation covers nothing and the "
                               "allowlist machinery in scripts/run_tests.sh is dead code")
        for c in named:
            with self.subTest(category=c.token):
                gates = _suite_category_gates(c)
                self.assertEqual(sorted(gates), sorted({str(n).lower() for n in c.allow}),
                                 f"the {c.token} row of EXEMPT_CATEGORIES in scripts/run_tests.sh declares the "
                                 f"allowlist {sorted(c.allow)} while this suite gates tests on {dict(gates)}. "
                                 f"The ROW is what the policy reads: declaring the name somewhere else (or "
                                 f"inlining a wider literal here) exempts it with no test behind it. Declare it "
                                 f"in {c.where or 'the row'} with a test that drives it, or delete a name whose "
                                 f"test is gone.")
                for n in c.allow:                  # names, never patterns, in the row as well as in the tuple
                    self.assertRegex(str(n), r"\A[\w.+-]+\Z",
                                     f"{c.token} allowlist entry {n!r} is not a plain tool name")

    def test_every_name_on_a_category_allowlist_is_really_exemptable_in_every_mode(self):
        """ROUND 7's F3, and it is a LEGITIMATE DENY: the `TOOLS` allowlist was INERT for any name containing a
        `PKGS` substring, so DECLARING a name changed nothing.

        In `claim()` the containment rule `if PKG_EXEMPT.search(r): return None, fails` was applied AFTER the
        allowlist and returned unconditionally. `yamllint` contains `yaml`. Measured with
        `TOOLS = ("ruff", "yamllint", "shellcheck")` and nothing else changed, reason ``optional developer tool
        `yamllint` is not on PATH``:

            --expect none  -> POLICY:NONE_REASON, RESULT: FAIL   (identical red before and after declaring it,
                                                                  in the mode BOTH CI jobs run)
            --expect torch -> POLICY:TORCH_MODE_UNEXPLAINED, FAIL
            --expect any   -> OK but NOT exempt; control in the same run: declared `shellcheck` -> exempt

        -- while the failure message instructs "declare the tool there, with a test". Round 3's defect shape:
        honest reason, red suite, unfollowable advice; latent only because the one gated tool happens to be
        `ruff`. NO TEST ASSERTED THAT EVERY NAME ON `TOOLS` IS EXEMPTABLE -- the positive direction was driven
        for `ruff` alone, by test_the_live_ruff_skip_reason_is_accepted_in_every_documented_mode.

        This is that assertion, generated from the registry. The live allowlist is a closed set of size one, so
        the second half drives a COPY of the script whose `TOOLS` carries `yamllint` (contains `yaml`) with
        `shellcheck` (contains none) as the control in the same run: without the fix the two names get DIFFERENT
        verdicts, which is the defect; with it they get the same one.
        """
        named = [c for c in EXEMPT_CATS if c.anchored.groups == 1]
        self.assertTrue(named, "no declared category carries a name; this check is vacuous")
        for c in named:
            canon = self._canonical(c)
            m = c.anchored.match(canon)
            self.assertIsNotNone(m, canon)
            for name in c.allow:
                probe = canon[:m.start(1)] + str(name) + canon[m.end(1):]
                for mode, extra in (("none", _mixed_none(50)),
                                    ("torch", _skip_module(1, "CUDA not available: x")),
                                    ("any", _pass_module(1))):
                    with self.subTest(category=c.token, name=name, mode=mode):
                        r = self.rt({"test_a.py": extra,
                                     "test_d.py": _skip_module(1, probe, cls="D", prefix="test_d")}, expect=mode)
                        self.ok(r)
                        self.assertIn(f"1 skip(s) {c.note}", r.stdout,
                                      f"{name!r} is on the {c.token} allowlist and its reason is not exempt in "
                                      f"--expect {mode}: declaring a name has no effect, which is the defect "
                                      f"this test exists for.\n" + r.stdout)
        # ...and the name class the live tuple cannot exercise: one that CONTAINS a measured package name.
        # `yamllint` contains `yaml`; `shellcheck` contains nothing and is the control IN THE SAME RUN, which is
        # what makes the two verdicts comparable.
        parked = "".join(_skip_module(1, f"optional developer tool `{n}` is not on PATH",
                                      cls=f"T{i}", prefix=f"test_t{i}_").replace("import unittest\n", "")
                         for i, n in enumerate(("yamllint", "shellcheck")))
        root = self.synth_root(_pass_module(1))
        script = root / "scripts" / "run_tests.sh"
        text = script.read_text(encoding="utf-8")
        old = 'TOOLS = ("ruff",)'
        self.assertEqual(text.count(old), 1, "scripts/run_tests.sh no longer spells TOOLS as this test expects; "
                                             "update the declaration below with it")
        script.write_text(text.replace(old, 'TOOLS = ("ruff", "yamllint", "shellcheck")'), encoding="utf-8")
        # one body per mode, for the same reason the `rt` loop above has one: the 50 package-missing reasons
        # `--expect none` requires are POLICY:TORCH_MODE_MISSING in `--expect torch`
        for mode, extra in (("none", _mixed_none(50)),
                            ("torch", _skip_module(1, "CUDA not available: x")),
                            ("any", _pass_module(1))):
            with self.subTest(declared_name_containing_a_package=mode):
                (root / "tests" / "test_a.py").write_text(extra + parked, encoding="utf-8")
                r = self.run_default(root, "--expect", mode)
                self.ok(r)
                self.assertIn("2 skip(s) for an absent optional developer tool", r.stdout,
                              "a DECLARED tool name that contains a measured package name is not exempt: the "
                              "allowlist is inert for it and the advice in POLICY:TOOL_UNDECLARED cannot be "
                              "followed.\n" + r.stdout)
        # the rail that keeps the exception narrow: a name that IS a measured package may not be declared at all
        script.write_text(text.replace(old, f'TOOLS = ("ruff", "{POLICY_PKGS[0]}")'), encoding="utf-8")
        (root / "tests" / "test_a.py").write_text(_pass_module(1), encoding="utf-8")
        r = self.run_default(root, "--expect", "any")
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("POLICY:INTERNAL", r.stdout)
        self.assertIn(POLICY_PKGS[0], r.stdout)

    def test_an_undeclared_tool_name_gets_no_exemption_and_fails_loudly_in_every_mode(self):
        """The runtime half of the allowlist, driven in all three documented modes.

        `--expect any` matters most here and is the reason this is a cap-style check rather than a reason check:
        `any` applies NO skip-reason check at all (every one of them sits inside `if mode == "none"` /
        `elif mode == "torch"`), so before POLICY:TOOL_UNDECLARED an undeclared tool name was accepted there in
        silence. The declared name in the same shape still passes in every mode --
        test_the_live_ruff_skip_reason_is_accepted_in_every_documented_mode -- so this is not a blanket refusal
        of the category.
        """
        und = "optional developer tool `torchrun` is not on PATH"
        for mode, extra in (("none", _mixed_none(50)), ("torch", _skip_module(1, "CUDA not available: x")),
                            ("any", _pass_module(1))):
            with self.subTest(mode=mode):
                r = self.rt({"test_a.py": extra,
                             "test_t.py": _skip_module(1, und, cls="T", prefix="test_t")}, expect=mode)
                self.bad(r, "POLICY:TOOL_UNDECLARED")
                self.assertIn("TOOLS allowlist", r.stdout)       # the message says what to do about it
                self.assertIn("torchrun", r.stdout)              # ...and which name is undeclared
                self.assertNotIn("skip(s) for an absent optional developer tool", r.stdout)   # no exemption

    def test_every_name_that_laundered_past_the_word_boundary_is_rejected_now(self):
        """The measured laundering table of the fifth FAIL, as a test, plus names nobody had listed.

        All of these were EXEMPT in `--expect none` and `--expect torch` before the allowlist. `pytest-cov`,
        `numpy-stubs`, `py-torch`, `torch-cpu`, `TORCH` and `pytorch` were NOT -- the hyphen and the case folding
        put them inside `PKG`'s word boundaries -- which is exactly how narrow the old rule's reach was.
        """
        names = ["torchrun", "libtorch", "torch2", "_torch", "pytestx", "torchvision", "torchaudio", "numpy2",
                 "yamllint", "mypy", "black", "torch_geometric", "ruff.exe", "ruff-0.4", "RUFFIAN"]
        shaped = [f"optional developer tool `{n}` is not on PATH" for n in names]
        r = self.rejects_each(shaped, expect="torch")
        self.assertIn("POLICY:TOOL_UNDECLARED", r.stdout)
        r = self.rejects_each(shaped, expect="none")
        self.assertIn("POLICY:TOOL_UNDECLARED", r.stdout)
        # a tail may not introduce a second, undeclared CLAIM either: the check is over every OCCURRENCE of a
        # declared category phrase in the reason, not only the anchored one.
        # WHAT THIS USED TO BE, and it was withdrawn in round 6 because it was a LEGITIMATE DENY: the rule was
        # "every BACKTICKED name in a tool-shaped reason must be a declared tool", so the live ruff reason plus
        # `` (see `scripts/lint.sh`) `` -- or a backticked rule code such as `` `F821` `` -- was
        # POLICY:TOOL_UNDECLARED in all three modes, RESULT: FAIL, with advice that cannot be followed
        # ("declare the tool there" about a path). That is round 3's defect shape exactly: honest reason, red
        # suite, unfollowable guidance. It was latent only because the live reason happens to backtick just
        # `ruff`. The narrowing costs the one case below the line: a bare `` `mypy` `` in a tail is exempt now
        # -- as `; mypy is gone` already was, so what the rule really did was make the verdict depend on
        # TYPOGRAPHY. See test_a_backticked_name_is_judged_only_as_a_second_category_claim.
        self.rejects_each([self.TOOL_REASON + "; `torchrun` is gone",
                           self.TOOL_REASON + "; also optional developer tool `black` is not on PATH",
                           self.TOOL_REASON + "; also optional developer tool `mypy` is not on PATH"],
                          expect="none")
        # and a name the PHRASE cannot hold is rejected by the shape before the allowlist is reached: the name
        # class is [\w.+-]+, so a backtick inside the name means it is not tool-shaped at all
        self.rejects_each(["optional developer tool `ru`ff` is not on PATH"], expect="none")
        # The same for a name carrying a NEWLINE or a ZERO-WIDTH SPACE -- a name that looks like `ruff` in a
        # terminal. Driven one at a time rather than through `rejects_each`, because the runner prints the
        # reason with repr(): `\n` and `​` come out ESCAPED, so a candidate holding the raw character can
        # never be found inside a line of output by a substring match. (Measured: that is a limitation of the
        # table's attribution, not of the policy -- both are rejected.)
        for label, name in (("newline", "ru\nff"), ("zero-width", "ruff​")):
            with self.subTest(name=label):
                r = self.rt({"test_a.py": _mixed_none(50),
                             "test_b.py": _skip_module(1, f"optional developer tool `{name}` is not on PATH",
                                                       cls="N", prefix="test_n")}, expect="none")
                self.bad(r, "POLICY:NONE_REASON")
                self.assertNotIn("skip(s) for an absent optional developer tool", r.stdout)

    # --- THE SIXTH SR-15 FAIL: the category REGISTRY, and every check below generated from it ---------------
    def _canonical(self, cat):
        """A reason the SUITE really emits for this category, read out of its own skip sites.

        The generated cases below are built from this rather than from a string typed here, for the reason
        `_live_ruff_skip_reason` exists: a reason typed in one place and judged in another is how round 3's FAIL
        happened. It is also what makes the generated tables non-vacuous -- a category with no site fails here
        rather than producing an empty table.
        """
        live = sorted(r for _w, c, r in _suite_exempt_carriers() if c.token == cat.token)
        self.assertTrue(live, f"no skip site in tests/toy_tests/ carries the {cat.token} phrase, so the category "
                              f"is declared in scripts/run_tests.sh for nothing: delete the row, or the test it "
                              f"existed for was deleted and its exemption has outlived it")
        return live[0]

    def test_every_exemption_category_is_declared_with_the_same_guards(self):
        """THE ROOT OF THE SIXTH FAIL, as the property that replaced it.

        Round 5 closed the TOOL category with three anchoring guards (`\\A` in the phrase, `.match` at the call,
        a trailing `\\b`) PLUS a closed allowlist of names. The filesystem-case category is the same KIND of
        exemption and got NONE of the four: `re.compile(r"case[- ]sensitive", re.I)`, applied with `.search`.
        Reviewing two hand-guarded sites for symmetry is what failed, so the guards are now properties of a
        DECLARATION and this test is the declaration's contract:

          * the phrase is anchored and `\\b`-terminated, so prose can neither carry the claim nor extend it;
          * it captures at most ONE name, and it carries a name IF AND ONLY IF it declares a closed allowlist
            for it and says where that allowlist lives -- a name class with no allowlist is the OPEN SET that
            was round 4's defect;
          * it has a positive cap.

        The script checks the same five properties at run time and refuses the run as POLICY:INTERNAL
        (driven by test_a_category_declared_without_the_guards_is_refused_as_POLICY_INTERNAL), so this is the
        static half of a check that exists on both sides.
        """
        self.assertGreaterEqual(len(EXEMPT_CATS), 2, EXEMPT_CATS)          # not vacuous if the parse degrades
        self.assertEqual(sorted(c.token for c in EXEMPT_CATS), ["FS", "TOOL"],
                         f"scripts/run_tests.sh declares {[c.token for c in EXEMPT_CATS]} as its "
                         f"environment-exemption categories. A NEW category must be named HERE deliberately: "
                         f"every generated table in this file then drives it, and POLICY:<TOKEN>_CAP and (if "
                         f"its phrase carries a name) POLICY:<TOKEN>_UNDECLARED must be asserted by a test "
                         f"(test_every_policy_token_is_asserted_by_some_test enforces that).")
        for c in EXEMPT_CATS:
            with self.subTest(category=c.token):
                self.assertTrue(c.phrase.startswith(r"\A"), f"{c.token}'s phrase {c.phrase!r} is not anchored")
                self.assertTrue(c.phrase.endswith(r"\b"), f"{c.token}'s phrase {c.phrase!r} does not end on \\b")
                self.assertLessEqual(c.anchored.groups, 1, f"{c.token}'s phrase captures more than one name")
                self.assertEqual(bool(c.anchored.groups), bool(c.allow),
                                 f"{c.token} carries a name iff it declares an allowlist: {c.phrase!r} {c.allow}")
                self.assertEqual(bool(c.anchored.groups), bool(c.where),
                                 f"{c.token} must say where its allowlist lives iff it has one: {c.where!r}")
                self.assertIsInstance(c.cap, int)
                self.assertGreaterEqual(c.cap, 1, f"{c.token}'s cap is not positive")
                for n in c.allow:                      # names, never patterns: a pattern reopens the open set
                    self.assertRegex(n, r"\A[\w.+-]+\Z", f"{c.token} allowlist entry {n!r} is not a plain name")
        # the SECOND anchor term: the policy applies a category phrase with `.match`, at ONE call site. The two
        # terms are mutually redundant (see the runner's comment), so this pins the pair rather than either.
        script = (SCRIPTS / "run_tests.sh").read_text(encoding="utf-8")
        self.assertEqual(len(re.findall(r"anchored\.match\(", script)), 1,
                         "the policy no longer applies a category phrase with exactly one `anchored.match(` "
                         "call; the anchor is written twice on purpose and this is the second term")
        self.assertNotIn("anchored.search(", script)

    def test_the_category_registry_is_assigned_exactly_once_and_never_rebound(self):
        """ROUND 7's F2: the registry contract is asserted on SOURCE TEXT, and the loop reads a VALUE.

        `_policy_exempt_categories` parses `^EXEMPT_CATEGORIES = \\((.*?)^\\)\\n` out of the script and
        `literal_eval`s the rows, so every generated check in this file -- the structural contract, the
        laundering table, the cap boundary, the cross-category pairs, the allowlist equality, the POLICY-token
        accounting -- is made of what that LITERAL says. ONE line inserted immediately after the literal's `)`:

            EXEMPT_CATEGORIES = EXEMPT_CATEGORIES + (("ZED", r"\\Aonly on zed\\b", 2, "", (), "for zed"),)

        gives a fully functional category with a working cap (measured on the live script: n=2 -> `RESULT: OK`
        with `note: 2 skip(s) for zed`, n=3 -> `POLICY:ZED_CAP`), no token, in all three modes, and it is
        invisible to every one of those six checks because none of them can see past the literal.
        Variant m7b sets the note column to the filesystem-case note VERBATIM and prints parked skips as
        *"note: 4 skip(s) for a case-sensitive filesystem (expected on Linux)"* -- round 6's F3 effect through a
        different door, and the figure docs/CLEAN_CLONE.md tells a reader to expect on Linux.

        So the name is required to be bound EXACTLY ONCE, by a module-level assignment whose value is a
        literal tuple of literal tuples. Parsed as a PROGRAM (`_policy_block` + `ast`), not grepped: any Store
        or Del of the name anywhere -- a rebind, an augmented assignment, a loop target, a walrus -- is a
        second binding and fails here.
        THE RESIDUE, AND THE SENTENCE THAT USED TO STAND HERE WAS FALSE. The first half was right: a binding
        made through `globals()[...]` or `setattr` is not a Name in Store context, so this check cannot see it.
        What followed -- "the runtime half below is what covers a bad row however it arrives" -- was NOT. The
        runtime half rejects a row that VIOLATES the declaration contract, and round 7's F2 mutant is WELL
        FORMED, so the acknowledged door admitted exactly the mutant class this test was written for. MEASURED
        (round 8's F1), with the `globals()` one-liner in place: this test passed in 0.004 s, the module was
        151 OK rc=0, and at run time the extra category had a working cap and printed its parked skips under a
        note of its own choosing with NO POLICY token in any mode.
        WHAT COVERS IT NOW IS A COMPARISON RATHER THAN A HOPE:
        test_the_registry_the_run_really_uses_equals_the_declared_literal requires the registry listing
        `scripts/run_tests.sh` prints AT THE POINT OF USE to equal this literal, row for row and column for
        column, so a row arriving by any route is a red suite. The runtime half,
        test_a_category_declared_without_the_guards_is_refused_as_POLICY_INTERNAL, is what it always was -- a
        MALFORMED row: a duplicate token, and a duplicate or NEAR-duplicate note -- and this static half is
        kept because it localises the defect to a line of source instead of to a listing.
        THE CONTROL THAT PROVES THE HOLE WAS THE DOOR AND NOT THE ROW, measured rather than hedged (the
        sentence below this one used to say "at least six" checks, with the count unre-enumerated): on the
        pre-fix tree, the IDENTICAL row placed INSIDE the literal fails 7 test methods and 8 failure records --
        test_every_exemption_category_is_declared_with_the_same_guards, ..._has_its_own_cap_and_its_boundary_
        is_driven, ..._is_claimed_properly_by_the_sites_that_use_it, ..._rejects_the_same_laundering,
        test_no_reason_may_claim_two_exemption_categories_at_once,
        test_every_policy_token_is_asserted_by_some_test and
        test_the_normative_skip_policy_section_states_the_rules_the_script_really_applies. On the CURRENT tree
        the same row is POLICY:INTERNAL at the declaration (its note is a near-duplicate), so the registry is
        refused and 112 failure records follow; a row with an unconfusable note is caught by the listing
        comparison instead.
        """
        src = _policy_block()
        self.assertIn("def claim(", src, "the parsed block is not the skip-policy program; _policy_block has "
                                         "found the wrong heredoc and this check is vacuous")
        tree = ast.parse(src)
        stores = [n for n in ast.walk(tree) if isinstance(n, ast.Name) and n.id == "EXEMPT_CATEGORIES"
                  and isinstance(n.ctx, (ast.Store, ast.Del))]
        self.assertEqual([n.lineno for n in stores][1:], [],
                         f"EXEMPT_CATEGORIES is bound {len(stores)} times in the skip-policy block of "
                         f"scripts/run_tests.sh (lines {[n.lineno for n in stores]} of that block). The registry "
                         f"is parsed as a LITERAL by _policy_exempt_categories and every generated check in this "
                         f"file is built from what that literal says, so a second binding adds a category no "
                         f"test in this file can see. Declare the row inside the one literal.")
        assigns = [s for s in tree.body if isinstance(s, ast.Assign)
                   and any(isinstance(t, ast.Name) and t.id == "EXEMPT_CATEGORIES" for t in s.targets)]
        self.assertEqual(len(assigns), 1, "EXEMPT_CATEGORIES is not assigned exactly once at the top level of "
                                          "the skip-policy block")
        val = assigns[0].value
        self.assertIsInstance(val, ast.Tuple, "EXEMPT_CATEGORIES is no longer assigned a literal tuple (a call, "
                                              "a concatenation or a comprehension would make the registry this "
                                              "file parses a lie about what the loop reads)")
        self.assertTrue(val.elts, "EXEMPT_CATEGORIES is an empty literal")
        for row in val.elts:
            self.assertIsInstance(row, ast.Tuple, "a row of EXEMPT_CATEGORIES is not a literal tuple")
        self.assertEqual(len(val.elts), len(EXEMPT_CATS),
                         "the literal the policy executes and the one _policy_exempt_categories parses disagree "
                         "about how many rows there are")

    def test_the_registry_the_run_really_uses_equals_the_declared_literal(self):
        """ROUND 8's F1: the static half above conceded a door and the sentence that said the runtime half
        covered it was false, so the door admitted the one mutant class that mattered.

        The static check reads SOURCE TEXT; the runtime check rejects a MALFORMED row. A row that arrives
        through `globals()[...]` or `setattr` is invisible to the first and acceptable to the second. MEASURED
        before this test existed, ONE line inserted after the literal's `)`:

            globals()["EXEMPT_CATEGORIES"] = EXEMPT_CATEGORIES + (("ZED", r"\\Aonly on this platform\\b", 8,
                "", (), "for a case-sensitive filesystem (expected on Linux runners)"),)

        -> `tests.toy_tests.test_scripts` 151 OK, rc=0, UNKILLED: the exactly-once test passes (it sees the
        literal), and the token accounting derives its tokens from the literal too, so no `ZED_CAP` is ever
        required. At run time: `RESULT: OK`, no POLICY token in any mode, a working cap at 8, and parked skips
        printed as "note: 4 skip(s) for a case-sensitive filesystem (expected on Linux runners)" -- the figure
        docs/CLEAN_CLONE.md tells a LINUX reader to expect, under a token nobody declared.

        So the script ATTESTS the registry it judged with -- one `exemption registry row:` JSON line per row,
        rendered from a snapshot of the `CATS` value `claim()` reads -- and this test COMPARES that listing
        against the parsed literal, row for row and column for column.

        EVERY COLUMN, AND THAT IS ROUND 10's HALF OF THIS TEST. The listing used to omit `CATS` column 3, the
        LOOSE pattern -- the value guards (5) and (6) are built from, which find a SECOND occurrence of any
        declared phrase anywhere in a reason. So an attested listing could equal the literal while that column
        was neutered. MEASURED on the round-9 script, column 3 replaced by a never-matching pattern: the listing
        stayed BYTE-IDENTICAL while a reason carrying a second category's phrase in its tail went from
        POLICY:EXEMPT_AMBIGUOUS to `RESULT: OK` AND EXEMPT (round 6's F3 at run time), and one carrying an
        UNDECLARED tool name in its tail went from POLICY:TOOL_UNDECLARED to `RESULT: OK` AND EXEMPT (round 5's
        shape); a reason naming a package in its tail stayed denied, because `PKG_EXEMPT` reads the whole
        reason. Two behavioural tests do kill that mutant -- but not the attestation, and the attestation is the
        thing that claims to cover routes, so it now carries the column. The column NAMES are read out of the
        script (`_registry_cols`) rather than retyped, and the script refuses a `CATS` row that is not exactly
        that wide, so a new column cannot be added at either end without the other end going red.

        WHERE THE BOUNDARY OF THIS ATTESTATION IS, AND WHO SAYS SO: not this docstring.
        test_every_insertion_position_around_the_registry_attestation_is_driven drives every insertion position
        around the attestation and asserts the outcome at each.
        """
        r = self.rt({"test_a.py": _pass_module(1)}, expect="any")
        self.ok(r)
        want = [{"token": c.token, "phrase": c.phrase, "loose": c.loose.pattern, "cap": c.cap, "where": c.where,
                 "allow": sorted(str(a).lower() for a in c.allow), "note": c.note} for c in EXEMPT_CATS]
        self.assertIn("exemption registry: ", r.stdout,
                      "scripts/run_tests.sh no longer attests the registry it judged with, and this test is "
                      "vacuous without that listing.\n" + r.stdout)
        self.assertEqual(sorted(_registry_cols()), sorted(want[0]),
                         "scripts/run_tests.sh attests a different set of row columns than this test compares. "
                         "The script refuses a CATS row that is not exactly as wide as _REGISTRY_COLS, so a new "
                         "column lands here: add it to `want` above, derived from the parsed literal, or the "
                         "attestation stops covering it -- which is exactly how the loose pattern went "
                         "unattested for a round.")
        self.assertEqual(self._listed_registry(r.stdout), want,
                         "the exemption registry scripts/run_tests.sh REALLY USED is not the "
                         "EXEMPT_CATEGORIES literal this file parses. A row reaching the policy by any other "
                         "route -- a rebind, globals()[...], setattr, exec -- is a fully working environment "
                         "exemption with a cap, a bucket and a printed note that NO check built from the "
                         "literal can see. Declare the row inside the one literal.\n" + r.stdout)
        self.assertIn(f"exemption registry: {len(want)} row(s)", r.stdout,
                      "the count the run prints disagrees with the rows it listed.\n" + r.stdout)
        # THE SHAPE OF THE ROUND-10 FIX, pinned on the source so that the behavioural drives below cannot be
        # satisfied by accident: the snapshot is taken BEFORE the listing is rendered (that order is what the
        # F1 window was), and the registry is re-compared at TWO places, both at the TOP LEVEL of the policy
        # program -- not inside an `if mode == ...` branch, so the compares apply in every mode including
        # `--expect any`, where no reason check runs at all.
        blk = _policy_block()
        self.assertLess(blk.index("_REGISTRY_USED = list(CATS)"), blk.index('print(f"exemption registry: '),
                        "scripts/run_tests.sh renders the registry listing BEFORE it snapshots the registry. "
                        "That order is round 10's F1: a rebind between the two is invisible to both halves, "
                        "because the listing comes from the pre-mutation value and the snapshot from the "
                        "post-mutation one, so the end-of-block compare passes.")
        drift = [s for s in ast.parse(blk).body
                 if isinstance(s, ast.If) and isinstance(s.test, ast.Call)
                 and isinstance(s.test.func, ast.Name) and s.test.func.id == "registry_drifted"]
        self.assertEqual(len(drift), 2,
                         f"the policy program compares the registry against its snapshot at "
                         f"{len(drift)} top-level places; there must be TWO -- one after the caps and one after "
                         f"the registry's LAST consumer (the baseline branches, which reach it through "
                         f"base_excl), so that no position in the program sits after the last compare.")

    def test_every_insertion_position_around_the_registry_attestation_is_driven(self):
        """ROUND 10's F1, AND THE SHAPE OF THE PROJECT'S RECURRING DEFECT: the mechanism was real and the
        sentence describing its REACH was stronger than the mechanism, for the third round running.

        | round | mechanism            | the prose about its reach                     | the actual gap        |
        | 8     | runtime row checks   | "covers a bad row HOWEVER IT ARRIVES"         | a class: only MALFORMED
        | 9     | registry attestation | "a row that arrives by ANY ROUTE ... RED SUITE" | one line

        Round 9's listing was printed from `CATS` and the snapshot taken one line later, so a
        `globals()["CATS"] = CATS + [...]` line BETWEEN them was invisible to both halves: the listing came
        from the pre-mutation value, the snapshot from the post-mutation one, and the compare at the end of the
        block was therefore satisfied. MEASURED on the round-9 script, one such line with an unanchored phrase,
        no allowlist and the filesystem-case note verbatim, in `--expect none` (the mode BOTH CI jobs run):
        `exemption registry: 2 row(s)` with the listing BYTE-IDENTICAL to the declared literal, then
        "note: 4 skip(s) for a case-sensitive filesystem (expected on Linux)", `RESULT: OK`, rc=0, NO POLICY
        token -- against a base control of four POLICY:NONE_REASON and rc=1 on the same suite. Round 7's m7b
        and round 8's F1 were both fully restored by it, because a rebind bypasses the declaration loop
        entirely so no declaration guard applies.

        D4 pins a WITHDRAWN claim; nothing in this project pins a REACH claim. So this test does not state a
        reach, and neither does the code: IT ENUMERATES THE POSITIONS AND ASSERTS THE OUTCOME AT EACH, and the
        enumeration IS the claim. One working, well-formed row, carrying the documented filesystem-case note and
        really parking four skips, is inserted at each position around the attestation:

          * BEFORE the snapshot -> the run stays GREEN and silent (rc=0, no POLICY token, and the four skips
            are parked under the figure docs/CLEAN_CLONE.md tells a Linux reader to expect), and the LISTING is
            what kills it: three rows where the literal declares two. That the run is green here is the point;
            it is why the listing has to exist at all.
          * BETWEEN the snapshot and the listing -- THE ROUND-9 WINDOW -- and at every later position: inside
            the listing loop, after the listing, after the cap loop, after the first compare, and after the
            registry's LAST consumer. Each is POLICY:INTERNAL, rc=1, WITH THE LISTING STILL EQUAL TO THE
            DECLARATION. That last assertion is what makes this non-vacuous: at these positions the listing
            cannot see the row, so the script-side compare is the load-bearing half, and if the compare were
            removed the listing assertion would pass while the row judged skips.

        What this does NOT claim: that a line cannot be inserted anywhere else in the program to some other
        effect, that the positions below are the only ones a reviewer could invent, or anything at all about
        routes other than a rebind of the name the policy reads. The rows below are the measurement; there is
        no sentence here that reaches past them.
        """
        FS = _cat("FS")                                  # derived: the note a Linux reader is told to expect
        root = self.synth_root(_pass_module(1),
                               files={"tests/test_z.py": _skip_module(4, "only on this platform", cls="Z",
                                                                      prefix="test_z")})
        script = root / "scripts" / "run_tests.sh"
        orig = script.read_text(encoding="utf-8")
        row = ('globals()["CATS"] = CATS + [("ZED", re.compile(r"\\Aonly on this platform\\b", re.I), '
               're.compile(r"only on this platform\\b", re.I), 8, "", set(), %r)]\n' % FS.note)
        # (label, anchor, indent, insert AFTER the anchor?, which half is expected to kill it)
        POSITIONS = (
            ("before the snapshot", "_REGISTRY_USED = list(CATS)", "", False, "listing"),
            ("between the snapshot and the listing", "_LISTED = registry_rows(_REGISTRY_USED)\n", "", True,
             "script"),
            ("inside the listing loop", '    print("exemption registry row: " + _row)\n', "    ", True,
             "script"),
            ("after the listing", "def registry_drifted():", "", False, "script"),
            ("after the cap loop", 'if registry_drifted():\n    bad.append("POLICY:INTERNAL the exemption '
                                   'registry changed between', "", False, "script"),
            ("after the first compare", 'if mode == "none":\n    # Built from PKG', "", False, "script"),
            ("after the registry's last consumer", "# THE SECOND COMPARE,", "", False, "script"),
        )
        for label, anchor, _i, _a, _k in POSITIONS:
            self.assertEqual(orig.count(anchor), 1,
                             f"scripts/run_tests.sh no longer holds the anchor for the position {label!r} "
                             f"exactly once ({anchor!r}); this enumeration IS the claim about where the "
                             f"attestation's boundary is, so a moved anchor must be re-measured, not deleted")
        control = self.run_default(root)
        self.ok(control)                                             # the copy is green as copied
        declared = self._listed_registry(control.stdout)
        self.assertEqual(len(declared), len(EXEMPT_CATS), control.stdout)
        try:
            for label, anchor, indent, after, kill in POSITIONS:
                with self.subTest(position=label):
                    line = indent + row
                    script.write_text(orig.replace(anchor, (anchor + line) if after else (line + anchor)),
                                      encoding="utf-8")
                    r = self.run_default(root)
                    listed = self._listed_registry(r.stdout)
                    self.assertNotIn("Traceback (most recent call last)", r.stdout + r.stderr,
                                     f"the row inserted {label} killed the policy process instead of being "
                                     f"reported.\n" + r.stdout + r.stderr)
                    if kill == "listing":
                        # a WELL FORMED, WORKING row: the run is green and silent, and only the listing differs
                        self.ok(r)
                        self.assertNotIn("POLICY:", r.stdout)
                        self.assertIn(f"4 skip(s) {FS.note}", r.stdout, r.stdout)
                        self.assertEqual(len(listed), len(declared) + 1, r.stdout)
                        self.assertEqual([x["token"] for x in listed][-1], "ZED", r.stdout)
                        self.assertNotEqual(listed, declared,
                                            f"a row inserted {label} is in the listing, so "
                                            f"test_the_registry_the_run_really_uses_equals_the_declared_literal "
                                            f"is what kills it -- and here the listing matches the declaration "
                                            f"anyway, which means neither half sees it.\n" + r.stdout)
                    else:
                        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
                        self.assertIn("POLICY:INTERNAL", r.stdout, r.stdout)
                        self.assertRegex(r.stdout, r"registry changed (between|after) the listing", r.stdout)
                        # ...and the LISTING cannot see it, which is why the script-side compare is the half
                        # that has to fire. This is the assertion round 9 had no equivalent of.
                        self.assertEqual(listed, declared,
                                         f"a row inserted {label} IS visible in the listing, so this position "
                                         f"is covered by the row-equality test as well and the script-side "
                                         f"compare is not being measured here. Re-measure the boundary.\n"
                                         + r.stdout)
        finally:
            script.write_text(orig, encoding="utf-8")

    @staticmethod
    def _listed_registry(stdout):
        """The registry a run of scripts/run_tests.sh attested, parsed back out of its output."""
        return [json.loads(l.split(": ", 1)[1]) for l in stdout.splitlines()
                if l.startswith("exemption registry row: ")]

    def test_every_declared_exemption_category_is_claimed_properly_by_the_sites_that_use_it(self):
        """THE DERIVATION, generalised from the TOOLS allowlist to every category -- and it is what a real site
        in this very file failed.

        `_suite_tool_gates` finds a tool gate with `.match`, so a skip reason that does not BEGIN with the
        phrase is invisible to it. Measured on a byte-identical copy of the repo: a probe site reading
        ``case-sensitive filesystem: optional developer tool `mypy` is not on PATH`` left
        test_the_TOOLS_allowlist_is_exactly_the_tools_this_suite_gates_on GREEN, while the skip was exempt at
        run time in all three modes -- a test gated on an undeclared tool, green at test time and at run time.
        The same reason without the leading filesystem-case phrase fails that test, which is how the derivation
        is known to work.
        And the loose scan found a REAL one: this file skipped with "filesystem is case-sensitive; case-varied
        path does not alias the repo" -- the phrase mid-sentence, claiming nothing. Under the anchored phrase
        that skip is judged as a package skip, so the documented `--expect none` run would have gone red with
        POLICY:NONE_REASON on every case-sensitive filesystem, i.e. on both CI runners.

        So every reason in tests/toy_tests/ that CARRIES a declared phrase is driven through the live script and
        must be reported as exempt under the category it carries. Not a text check: the script decides.
        """
        carriers = _suite_exempt_carriers()
        self.assertGreaterEqual(len(carriers), 3, f"the carrier scan found almost nothing ({carriers}): it has "
                                                  f"stopped looking and this check is vacuous")
        for where, c, reason in carriers:
            with self.subTest(site=where, category=c.token):
                r = self.rt({"test_a.py": _pass_module(1),
                             "test_c.py": _skip_module(1, reason, cls="E", prefix="test_e")}, expect="any")
                self.ok(r)
                self.assertIn(f"1 skip(s) {c.note}", r.stdout,
                              f"the skip site at {where} carries the {c.token} phrase but does not CLAIM the "
                              f"category: word it as the declared phrase (anchored, nothing before it), or it "
                              f"will be judged as a package skip wherever it fires.\n" + r.stdout)
        self.assertEqual(sorted({c.token for _w, c, _r in carriers}), sorted(c.token for c in EXEMPT_CATS),
                         "a declared category has no skip site in tests/toy_tests/ at all: an exemption with "
                         "no test behind it is a permission nobody needs")

    def test_no_computed_skip_reason_carries_a_declared_exemption_phrase(self):
        """THE SECOND-ORDER HOLE IN THE DERIVATIONS ABOVE, closed fail-closed instead of argued away.

        `_suite_skip_sites` collected `ast.Constant` reasons only, and only from tests/toy_tests/. Two real
        skip sites build their reason with an f-string --

            toy_tests/test_tensor_ops.py:29, :31   (f"{_WHY}; " if _WHY else "") + "CUDA not available: ..."

        -- so they were outside BOTH derivations (the per-row allowlist equality and the carrier scan), and
        `tests/test_toy.py` is in the discovered suite (`discover -s tests`) and was outside the scan
        altogether. Measured today: 17 literal sites, 2 computed ones (the two above), and `tests/test_toy.py`
        carries no skip at all, so widening the scan changed no derivation.
        WHY IT STILL MATTERS: those two reasons are benign because they name no declared phrase and run through
        torch mode, and because an undeclared NAME is POLICY:TOOL_UNDECLARED at runtime whatever built the
        string. The UNNAMED category has no such backstop -- the filesystem-case phrase carries no name for the
        runtime to check -- so a computed reason claiming it would be bounded by FS_CAP (8) and the per-module
        baseline and by nothing else, with no test-time derivation able to see it.
        THE RULE, therefore: a reason the static derivations cannot read may not CARRY a declared phrase in any
        fragment a static reader CAN see. Write it as a literal, or gate the test on something readable. This
        is fail-closed about a thing no regex can decide -- what the `{...}` fields will hold at run time -- and
        the cost is one line of rewording at a site that wants both.
        The extractor is checked against a positive control, because a scan that silently stops finding things
        is how the round-6 defect hid for a round.
        """
        exprs = sum((_skip_reason_exprs(p.read_text(encoding="utf-8"), p.name) for p in _suite_modules()), [])
        self.assertGreaterEqual(len(exprs), 10, f"the skip-reason scan found {len(exprs)} call sites in the "
                                                f"discovered suite: it has stopped looking and every "
                                                f"derivation built on it is vacuous")
        for where, frags in _suite_computed_skip_sites():
            for frag in frags:
                for c in EXEMPT_CATS:
                    with self.subTest(site=where, category=c.token):
                        self.assertIsNone(c.loose.search(frag),
                                          f"the skip reason at {where} is COMPUTED (an f-string, a "
                                          f"concatenation or a conditional), so neither _suite_category_gates "
                                          f"(which .match-es a literal) nor _suite_exempt_carriers can judge "
                                          f"it -- and this fragment carries the {c.token} phrase "
                                          f"{c.phrase!r}: {frag!r}. The {c.token} category "
                                          + ("carries a name, so an undeclared one is still "
                                             f"POLICY:{c.token}_UNDECLARED at run time, but the DERIVATION "
                                             "that keeps its allowlist honest cannot see this site"
                                             if c.anchored.groups else
                                             "carries NO name, so the runtime has nothing to check and the "
                                             "only bound left is the cap and the baseline")
                                          + ". Write the reason as one literal, or gate the test on something "
                                            "the derivation can read.")
        # POSITIVE CONTROL for the extractor, independent of the tree: an f-string reason carrying the FS
        # phrase must be SEEN as computed and its constant fragments must be read out of it.
        control = ("import unittest\n"
                   "W = 'x'\n"
                   "class T(unittest.TestCase):\n"
                   "    @unittest.skipUnless(False, (f'{W}; ' if W else '') + 'case-sensitive filesystem: c')\n"
                   "    def test_a(self): pass\n")
        found = [(w, _static_strings(e)) for w, e in _skip_reason_exprs(control, "control.py")
                 if not (isinstance(e, ast.Constant) and isinstance(e.value, str))]
        self.assertEqual(len(found), 1, f"the computed-reason scan no longer sees an f-string skip reason at "
                                        f"all, so the check above is vacuous: {found}")
        self.assertTrue(any(_cat("FS").loose.search(f) for _w, frags in found for f in frags),
                        f"the fragment extractor no longer reads the constant pieces of a computed reason, so "
                        f"the check above is vacuous: {found}")
        # ...and the scan really covers what the runner discovers, which is tests/ and not tests/toy_tests/
        mods = {str(m.relative_to(ROOT / "tests")) for m in _suite_modules()}
        for needed in ("test_toy.py", "toy_tests/test_tensor_ops.py", "toy_tests/test_scripts.py"):
            self.assertIn(needed, mods, f"the scan no longer covers {needed}, which `discover -s tests` runs")

    def test_every_declared_exemption_category_rejects_the_same_laundering(self):
        """ONE TABLE, GENERATED FOR EVERY DECLARED CATEGORY. The fourth FAIL's laundering was re-measured
        against the tool category alone, and the filesystem-case category was never driven with most of it; this
        generates both halves from `PKGS` and the registry, so a category declared tomorrow is laundered against
        the same way with no table to remember to extend.
        """
        tails, prose = [], []
        for c in EXEMPT_CATS:
            canon = self._canonical(c)
            prose += ["the suite reports: " + canon, "note: " + canon]
            for pkg in POLICY_PKGS:
                for affixed in (pkg, f"lib{pkg}", f"_{pkg}", f"my{pkg}", f"{pkg}run", f"{pkg}2", f"py{pkg}x"):
                    tails.append(canon + f"; {affixed} is gone")
        self.assertGreaterEqual(len(tails), 2 * 4 * 7, len(tails))        # not vacuous if a parse degrades
        r = self.rejects_each(tails, expect="torch")
        self.assertIn("POLICY:TORCH_MODE_UNEXPLAINED", r.stdout)
        r = self.rejects_each(tails, expect="none")
        self.assertIn("POLICY:NONE_REASON", r.stdout)
        r = self.rejects_each(prose, expect="none")                       # the anchor, for every category
        self.assertIn("POLICY:NONE_REASON", r.stdout)

    def test_no_reason_may_claim_two_exemption_categories_at_once(self):
        """F3 OF ROUND 6: a per-category cap is a bound only while a reason cannot be counted in the other
        category's bucket.

        Measured on the live script in `--expect any` with 5 identical skips: the live ruff reason x5 is
        POLICY:TOOL_CAP (x4 is OK -- the documented 4/5 boundary), and the SAME reason plus
        ` (case-sensitive filesystem)` x5 was **OK**, reported as "note: 5 skip(s) for a case-sensitive
        filesystem", x8 OK, and POLICY:FS_CAP only at 9. The combined 12-skip ceiling was not breached; what
        broke was the per-category bound the documents name as the thing that bounds tool parking -- and the run
        then printed tool parks as the Linux filesystem figure docs/CLEAN_CLONE.md tells readers to expect.
        Generated over ordered pairs, so a third category is covered against both of the others at once.
        """
        mixed = []
        for a in EXEMPT_CATS:
            for b in EXEMPT_CATS:
                if a.token != b.token:
                    mixed.append(self._canonical(a) + " (" + self._canonical(b) + ")")
        self.assertGreaterEqual(len(mixed), 2, mixed)
        for mode in ("none", "torch", "any"):
            with self.subTest(mode=mode):
                r = self.rejects_each(mixed, expect=mode)
                self.assertIn("POLICY:EXEMPT_AMBIGUOUS", r.stdout)
                for c in EXEMPT_CATS:                      # and neither bucket counted them
                    self.assertNotIn(f"skip(s) {c.note}", r.stdout)

    def test_every_declared_exemption_category_has_its_own_cap_and_its_boundary_is_driven(self):
        """A cap per category, from the declaration, with the boundary measured for each: a category cannot be
        declared without one, and a cap raised in the tuple is a cap this test re-measures at its new value."""
        for c in EXEMPT_CATS:
            canon = self._canonical(c)
            with self.subTest(category=c.token, n=c.cap):
                r = self.rt({"test_a.py": _pass_module(1),
                             "test_c.py": _skip_module(c.cap, canon, cls="E", prefix="test_e")}, expect="any")
                self.ok(r)
                self.assertIn(f"{c.cap} skip(s) {c.note}", r.stdout)
            with self.subTest(category=c.token, n=c.cap + 1):
                self.bad(self.rt({"test_a.py": _pass_module(1),
                                  "test_c.py": _skip_module(c.cap + 1, canon, cls="E", prefix="test_e")},
                                 expect="any"), f"POLICY:{c.token}_CAP")

    def test_an_undeclared_name_in_any_category_is_loud_in_every_mode(self):
        """Generated from the registry for every category whose phrase carries a NAME, by substituting an
        undeclared name into the live reason -- so the round-5 runtime guarantee is re-derived rather than
        re-typed, for whatever categories exist."""
        named = [c for c in EXEMPT_CATS if c.anchored.groups == 1]
        self.assertTrue(named, "no declared category carries a name; this check is vacuous and the TOOLS "
                               "allowlist has no runtime half")
        probes = []
        for c in named:
            canon = self._canonical(c)
            m = c.anchored.match(canon)
            self.assertIsNotNone(m, canon)
            self.assertNotIn("undeclared-probe-tool", canon)
            probes.append((c, canon[:m.start(1)] + "undeclared-probe-tool" + canon[m.end(1):]))
        for mode in ("none", "torch", "any"):
            with self.subTest(mode=mode):
                r = self.rejects_each([p for _c, p in probes], expect=mode)
                for c, _p in probes:
                    self.assertIn(f"POLICY:{c.token}_UNDECLARED", r.stdout)
                    self.assertNotIn(f"skip(s) {c.note}", r.stdout)
                self.assertIn("allowlist in scripts/run_tests.sh", r.stdout)     # the message says what to do

    def test_a_category_declared_without_the_guards_is_refused_as_POLICY_INTERNAL(self):
        """THE FAIL-CLOSED HALF, and the whole reason this is a registry and not two guarded sites: a category
        declared with fewer guards than the others cannot exempt anything, because the run refuses to start
        judging skips at all. Each row below is one a reviewer could plausibly have written -- the third is
        round 4's open set, declared in one line -- and each is POLICY:INTERNAL, in every mode, naming the
        category. The control run of the unmodified copy is what keeps this from passing for the wrong reason.
        """
        first = EXEMPT_CATS[0]                       # derived, so a renamed category does not make a row stale
        _tail_note = first.note + " runners"                                   # round 7's m7b, one word longer
        _loud_note = first.note.upper().replace("(", "[").replace(")", "]")     # the same note, shouted
        # ONE WORD SUBSTITUTED, which is what the third clause tests now. It used to be a four-word PREFIX
        # test, and a row sharing four opening words is exactly what an honest second category looks like under
        # this project's naming convention -- round 10's F2, driven as an ACCEPT by
        # test_an_honest_second_category_note_is_accepted_and_a_confusable_one_names_both_rows.
        _edit_note = " ".join(first.note.split()[:-1] + ["Zedland)"])
        MUT = {
            "no anchor": ('("TUE", r"only on tuesdays\\b", 2, "", (), "for tuesdays"),', "TUE"),
            "no trailing boundary": ('("TUE", r"\\Aonly on tuesdays", 2, "", (), "for tuesdays"),', "TUE"),
            "a name with no allowlist": ('("TUE", r"\\Aonly on `([\\w.+-]+)` days\\b", 2, "", (), "for tuesdays"),', "TUE"),
            "an allowlist with no name": ('("TUE", r"\\Aonly on tuesdays\\b", 2, "TUE_OK", ("tue",), "for tuesdays"),', "TUE"),
            "a cap of zero": ('("TUE", r"\\Aonly on tuesdays\\b", 0, "", (), "for tuesdays"),', "TUE"),
            # ROUND 7's N1 and N2, the two TOKENLESS failures. Each computed POLICY:INTERNAL into `bad` and then
            # died before `bad` was printed -- a non-int cap at `len(_got) > _cap` with TypeError, an OPTIONAL
            # capture group at `m.group(1).lower()` with AttributeError -- so the run was RESULT: FAIL, rc=1, no
            # POLICY token at all. The existing cap row drives a cap of ZERO, which is an int and reaches no
            # comparison. The `assertNotIn("Traceback")` below is the half that pins the difference.
            "a non-int cap": ('("TUE", r"\\Aonly on tuesdays\\b", "2", "", (), "for tuesdays"),', "TUE"),
            "an optional name group": ('("TUE", r"\\Aonly on( `[\\w.+-]+`)? tuesdays\\b", 2, "TUE_OK", ("tue",), "for tuesdays"),', "TUE"),
            # ROUND 7's F2 at run time: the static half (one binding, one literal) is
            # test_the_category_registry_is_assigned_exactly_once_and_never_rebound; these two are what makes a
            # BAD ROW loud however it arrives. The duplicate note is variant m7b, which printed its parked skips
            # as "note: N skip(s) for a case-sensitive filesystem (expected on Linux)" -- another category's
            # name, and the figure docs/CLEAN_CLONE.md tells a reader to expect on Linux.
            "a duplicate token": (f'("{first.token}", r"\\Aonly on tuesdays\\b", 2, "", (), "for tuesdays"),',
                                  first.token),
            # the inserted row comes FIRST, so the "already declared" complaint lands on the REAL row that
            # shares the note -- the needle is therefore the note itself, which is in the message either way
            "a duplicate note": (f'("TUE", r"\\Aonly on tuesdays\\b", 2, "", (), {first.note!r}),', first.note),
            # ...and the NEAR-duplicates, which the exact-string test ACCEPTED (round 8's F1, second half).
            # Measured on the pre-fix script, each of these was RESULT: OK, rc=0, and printed its parked skips
            # under a note a reader cannot tell from the real one; the "for tuesdays" rows above are the control
            # that this is not blanket-firing on any added note, and the ACCEPTED honest pair in
            # test_an_honest_second_category_note_is_accepted_and_a_confusable_one_names_both_rows is the
            # control that it is not blanket-firing on any note that resembles another.
            "a note one word longer than another":
                (f'("TUE", r"\\Aonly on tuesdays\\b", 2, "", (), {_tail_note!r}),', first.note),
            "a note differing only in case and punctuation":
                (f'("TUE", r"\\Aonly on tuesdays\\b", 2, "", (), {_loud_note!r}),', first.note),
            "a note one word edit from another":
                (f'("TUE", r"\\Aonly on tuesdays\\b", 2, "", (), {_edit_note!r}),', first.note),
            "a blank token": ('("", r"\\Aonly on tuesdays\\b", 2, "", (), "for tuesdays"),',
                              "is not a non-blank UPPERCASE identifier"),
            "a blank note": ('("TUE", r"\\Aonly on tuesdays\\b", 2, "", (), "  "),', "TUE"),
            # ...and the rail on the ROUND-8 exception: a DECLARED name is exempted from the package rule, so a
            # name that IS a measured package may not be declared at all (round 4's defect in one line).
            "an allowlist entry that is a measured package":
                (f'("TUE", r"\\Aonly on `([\\w.+-]+)` days\\b", 2, "TUE_OK", ("{POLICY_PKGS[0]}",), "for tuesdays"),',
                 "TUE"),
        }
        anchor = "EXEMPT_CATEGORIES = (\n"
        # a skip whose reason matches the optional-group row's phrase WITH NO NAME: without one, N2's
        # AttributeError is never reached and that row would pin the declaration guard alone.
        body = (_pass_module(1)
                + _skip_module(1, "only on tuesdays", cls="U", prefix="test_u").replace("import unittest\n", ""))
        root = self.synth_root(body)
        script = root / "scripts" / "run_tests.sh"
        orig = script.read_text(encoding="utf-8")
        self.assertEqual(orig.count(anchor), 1, "scripts/run_tests.sh no longer opens EXEMPT_CATEGORIES as this "
                                                "test expects; update the mutations below with it")
        self.ok(self.run_default(root))                                  # control: the copy is green as copied
        try:
            for label, (row, needle) in MUT.items():
                with self.subTest(declaration=label):
                    script.write_text(orig.replace(anchor, anchor + "    " + row + "\n"), encoding="utf-8")
                    r = self.run_default(root)
                    self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
                    self.assertIn("POLICY:INTERNAL", r.stdout)
                    self.assertIn(needle, r.stdout)                      # ...and it says which category
                    # a POLICY token, not a stack trace: the run must REPORT the bad declaration, not die on it
                    self.assertNotIn("Traceback (most recent call last)", r.stdout + r.stderr,
                                     f"the {label} row killed the policy process before it printed its "
                                     f"failures: rc=1 and RESULT: FAIL with NO POLICY token is a red run nobody "
                                     f"can act on.\n" + r.stdout + r.stderr)
                    # ...and nothing was judged on a registry that fails its own contract
                    self.assertNotIn("skip(s) for", r.stdout)
        finally:
            script.write_text(orig, encoding="utf-8")

    def test_an_honest_second_category_note_is_accepted_and_a_confusable_one_names_both_rows(self):
        """ROUND 10's F2, AND IT IS ROUND 3's SHAPE IN THE NOTE RULE: an honest declaration, a red run, and
        advice pointing at the wrong line.

        The near-duplicate note test's third clause was a FOUR-WORD PREFIX test. MEASURED on the round-9
        script, a row noted "for an absent optional runtime library" declared beside the live "for an absent
        optional developer tool" was POLICY:INTERNAL in all three modes, with the run stopping before a single
        skip was judged -- and the failure read *"exemption category TOOL is not declared as the policy
        requires: its note 'for an absent optional developer tool' opens on the same four words as an earlier
        row's note"*, blaming the LIVE, CORRECT row, because the inserted row is scanned first and the complaint
        was attached to the row being declared. No reader confuses "runtime library" with "developer tool"; the
        two notes differ exactly where English notes differ, in the last two words, and this project's own
        naming convention (`for an absent optional ...`) makes a four-word collision the LIKELY case rather than
        the pathological one.

        BOTH HALVES ARE DRIVEN HERE, and the notes are DERIVED from the live one so that renaming a category
        cannot make either row stale:

          * the honest row -- the live note with its last TWO words replaced -- is ACCEPTED, in all three modes,
            and the run is green with the row in its listing. The subtest first asserts that this note really
            does share the live note's first four folded words, so that it is still the exact pair the old rule
            refused: without that, this test could pass by accident on a note the old rule would also have
            accepted.
          * the confusable row -- the live note with its last ONE word replaced -- is still POLICY:INTERNAL, and
            the message now names BOTH rows with their positions and blames neither, because by the time the
            check runs both are in the literal and it cannot know which is new. The old single-row wording is
            asserted ABSENT.

        The threshold is one word edit and not two because two would re-refuse the honest pair; see
        `one_word_apart` in scripts/run_tests.sh for the other three variants the clause still catches.
        """
        tool = _cat("TOOL")
        honest_note = " ".join(tool.note.split()[:-2] + ["runtime", "library"])
        clash_note = " ".join(tool.note.split()[:-1] + ["library"])
        self.assertEqual(_fold_note(honest_note).split()[:4], _fold_note(tool.note).split()[:4],
                         f"the honest note this test drives ({honest_note!r}) no longer opens on the same four "
                         f"folded words as the live {tool.token} note ({tool.note!r}), so it is not the pair "
                         f"the withdrawn four-word rule refused and this regression pin is vacuous")
        self.assertNotEqual(_fold_note(honest_note), _fold_note(clash_note))
        row = ('    ("RLIB", r"\\Aoptional runtime library `([\\w.+-]+)` is not importable\\b", 4, "RLIB_OK",\n'
               '     ("zedlib",), %r),\n')
        anchor = "EXEMPT_CATEGORIES = (\n"
        # the honest/confusable row is declared FIRST, which is the configuration that made the old message
        # blame the live row, and is what a diff adding a row at the top of the literal produces
        MODES = (("none", _mixed_none(50)), ("torch", _skip_module(1, "CUDA not available: x")),
                 ("any", _pass_module(1)))
        root = self.synth_root(_pass_module(1))
        script = root / "scripts" / "run_tests.sh"
        orig = script.read_text(encoding="utf-8")
        self.assertEqual(orig.count(anchor), 1)
        try:
            for mode, body in MODES:
                (root / "tests" / "test_a.py").write_text(body, encoding="utf-8")
                with self.subTest(mode=mode, note="honest, two words apart -> ACCEPTED"):
                    script.write_text(orig.replace(anchor, anchor + row % honest_note), encoding="utf-8")
                    r = self.run_default(root, "--expect", mode)
                    self.ok(r)
                    self.assertNotIn("POLICY:", r.stdout, r.stdout)
                    listed = [x["note"] for x in self._listed_registry(r.stdout)]
                    self.assertIn(honest_note, listed, r.stdout)
                    self.assertIn(tool.note, listed, r.stdout)
                with self.subTest(mode=mode, note="one word apart -> POLICY:INTERNAL, naming both rows"):
                    script.write_text(orig.replace(anchor, anchor + row % clash_note), encoding="utf-8")
                    r = self.run_default(root, "--expect", mode)
                    self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
                    self.assertIn("POLICY:INTERNAL", r.stdout)
                    self.assertNotIn("skip(s) for", r.stdout)      # nothing judged on an unusable registry
                    self.assertNotIn("Traceback (most recent call last)", r.stdout + r.stderr)
                    line = [l for l in r.stdout.splitlines() if "declare notes a reader cannot tell apart" in l]
                    self.assertEqual(len(line), 1, r.stdout)
                    for needle in ("RLIB", tool.token, clash_note, tool.note, "within ONE word edit",
                                   "REWORD THE NOTE OF WHICHEVER OF THESE TWO ROWS YOU ARE ADDING"):
                        self.assertIn(needle, line[0], f"the note-collision failure must name {needle!r}; a "
                                                       f"message that names one row sends the author to the "
                                                       f"wrong line whenever the new row is declared first\n"
                                                       + line[0])
                    self.assertNotIn("is not declared as the policy requires: its note", r.stdout,
                                     "the note collision is still reported against ONE row's declaration, "
                                     "which blames the live row whenever the new row is scanned first\n"
                                     + r.stdout)
        finally:
            script.write_text(orig, encoding="utf-8")

    def test_a_backticked_name_is_judged_only_as_a_second_category_claim(self):
        """F2 OF ROUND 6, and it is a LEGITIMATE DENY rather than a hole.

        The rule was "every BACKTICKED name in a tool-shaped reason must be a declared tool". Measured on the
        live script, the live ruff reason plus `` (see `scripts/lint.sh`) `` was POLICY:TOOL_UNDECLARED in ALL
        THREE modes, RESULT: FAIL, with advice that cannot be followed -- "`scripts/lint.sh` is not in the TOOLS
        allowlist ... declare the tool there" -- and the same for a backticked rule code such as `` `F821` ``.
        That is round 3's defect shape exactly (honest reason, red suite, unfollowable guidance), and round 3's
        SR-15 FAIL was caused by exactly that kind of over-eager guard; it was latent only because the live
        reason happens to backtick just `ruff`. docs/CLEAN_CLONE.md presented the rule as a feature and did not
        disclose the cost.

        What replaced it is NARROWER and derived from the registry: every OCCURRENCE of a declared category
        PHRASE is checked, not every pair of backticks. The cost, stated plainly: a bare `` `mypy` `` in a prose
        tail is exempt now. It is the same verdict `; mypy is gone` already got, so what the old rule really did
        was make the verdict depend on TYPOGRAPHY; the bound on either is the caps and the baseline.
        """
        tool = self._canonical(_cat("TOOL"))
        honest = [" (see `scripts/lint.sh`)", " (rule `F821`)", "; `mypy` would have run it"]
        for mode, extra in (("none", _mixed_none(50)), ("torch", _skip_module(1, "CUDA not available: x")),
                            ("any", _pass_module(1))):
            with self.subTest(mode=mode):
                files = {"test_a.py": extra}
                for i, tail in enumerate(honest):
                    files[f"test_h{i}.py"] = _skip_module(1, tool + tail, cls=f"H{i}", prefix=f"test_h{i}_")
                r = self.rt(files, expect=mode)
                self.ok(r)
                self.assertIn(f"{len(honest)} skip(s) for an absent optional developer tool", r.stdout)
        # ...and a tail that really does claim the category again, with an undeclared name, is still rejected
        r = self.rejects_each([tool + "; also optional developer tool `black` is not on PATH"], expect="any")
        self.assertIn("POLICY:TOOL_UNDECLARED", r.stdout)

    def test_the_baseline_pyyaml_exclusion_is_built_from_PKGS_and_says_so_loudly(self):
        """D4: `PKGS`'s comment claimed it was the tuple "from which `NONE_OK`, the baseline exclusion and the
        exemption rule are all built", and the baseline exclusion was an INDEPENDENTLY typed
        `PYYAML = re.compile(r"\\b(?:py)?yaml\\b")` thirty lines below it. A third of the sentence was false --
        the same shape as the defect `PKGS` was created to end.

        It is built from the tuple now, and the degenerate case is loud rather than silent: this drives a COPY of
        the live script whose `PKGS` has lost `yaml`, and requires `POLICY:INTERNAL` instead of a pattern that
        goes on excluding a package the policy no longer measures. The control run of the unmodified copy is
        what keeps this from passing for the wrong reason.
        """
        body = _pass_module(1)
        root = self.synth_root(body)
        self.ok(self.run_default(root))                                  # control: the copy is green as copied
        script = root / "scripts" / "run_tests.sh"
        text = script.read_text(encoding="utf-8")
        old = 'PKGS = ("torch", "numpy", "yaml", "pytest")'
        self.assertEqual(text.count(old), 1, "scripts/run_tests.sh no longer spells PKGS as this test expects; "
                                             "update the mutation below with it")
        script.write_text(text.replace(old, 'PKGS = ("torch", "numpy", "pytest")'), encoding="utf-8")
        r = self.run_default(root)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("POLICY:INTERNAL", r.stdout)
        self.assertIn("yaml", r.stdout)

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
        """THE SIXTH SR-15 FAIL IS THAT THIS TEST HAD EXACTLY TWO CASES, and both of them contained `\btorch\b`
        -- the SAME SHAPE docs/CLEAN_CLONE.md records as what "used to pass throughout the fourth SR-15 FAIL"
        for the tool category. Everything the filesystem-case category could really be laundered with avoided
        the bare word, and all of it was EXEMPT (RESULT: OK) in all three modes on the live script:

            case-sensitive filesystem: variants differ; libtorch is gone        (also `_torch`, `mytorch`)
            case-sensitive filesystem: ...; optional developer tool `black` is not on PATH
            the optional developer tool `mypy` is not on PATH (case-sensitive filesystem)
            case-sensitive: this test is disabled for now

        The first row is why `PKG_EXEMPT` is a CONTAINMENT test rather than a prefix test: there is no `\b`
        before `torch` in `libtorch`, so the prefix rule that caught `torchrun` could never catch `libtorch`,
        PyTorch's own C++ distribution. The rest are why the phrase is anchored, `\b`-terminated, and may not be
        carried alongside another category's phrase.

        The generated tables do the same thing for EVERY declared category
        (test_every_declared_exemption_category_rejects_the_same_laundering); these are the measured strings
        from the round, kept as the record of what passed.
        """
        self.bad(self.rt({"test_a.py": _skip_module(1, "torch not installed; case-sensitive filesystem")}, expect="torch"), "POLICY:TORCH_MODE_MISSING")
        self.bad(self.rt({"test_a.py": _mixed_none(50), "test_b.py": _skip_module(1, "torch present; case-sensitive", cls="Q", prefix="test_q")},
                         expect="none"), "POLICY:TORCH_PRESENT")
        # (1) the affixed package names -- the prefix side is what the prefix rule could not reach
        r = self.rejects_each([self.FS_REASON + "; libtorch is gone", self.FS_REASON + "; _torch is gone",
                               self.FS_REASON + "; mytorch is gone", self.FS_REASON + "; torchrun is gone",
                               self.FS_REASON + "; numpy2 is gone", self.FS_REASON + "; yamllint is gone",
                               self.TOOL_REASON + "; libtorch is gone", self.TOOL_REASON + "; _torch is gone"],
                              expect="torch")
        self.assertIn("POLICY:TORCH_MODE_UNEXPLAINED", r.stdout)
        # (2) the phrase may not be CARRIED by prose, and `case-sensitive` alone is not the phrase
        r = self.rejects_each(["the suite reports: " + self.FS_REASON,
                               "note: " + self.FS_REASON,
                               "case-sensitive: this test is disabled for now",
                               "filesystem is case-sensitive; variants differ",
                               "case-sensitive filesystems are different directories"], expect="none")
        self.assertIn("POLICY:NONE_REASON", r.stdout)
        # (3) ...and in `--expect any`, where NO reason check runs at all and the hole was therefore completely
        #     silent, the change is visible as the exemption itself: the laundered reason no longer collects it,
        #     so it no longer spends FS_CAP budget and no longer drops out of the per-module skip column that
        #     catches a re-parked skip. (It is counted as a package skip there, which `any` mode does not judge
        #     -- that is the documented property of the mode, not of this category.)
        r = self.rt({"test_a.py": _pass_module(1),
                     "test_y.py": _skip_module(1, self.FS_REASON + "; libtorch is gone", cls="Y", prefix="test_y")},
                    expect="any")
        self.ok(r)
        self.assertNotIn("skip(s) for a case-sensitive filesystem", r.stdout)

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
    `/Library/Frameworks/.../3.12/bin` has neither, but a conda `bin` -- also a python3 on this PATH -- holds
    both `ruff` and `pyflakes`, so under that interpreter every "no optional tool" lint test ran WITH both tools
    present and measured the opposite branch from the one it names.

    WHAT THIS DOCSTRING USED TO END WITH, and it was FALSE: "A directory we construct cannot drift that way." It
    can, and it did. A constructed directory removes a tool from PATH; it does not remove it from the
    INTERPRETER, and the `python3` symlinked in here brings its own site-packages with it. `scripts/lint.sh`
    probed pyflakes as `python3 -m pyflakes --version`, so on an interpreter with pyflakes importable (CPython
    3.13.5, pyflakes 3.4.0) `RAN_ANY=1` and `test_missing_optional_tools_never_fail` FAILED -- a real live
    failure, and the test was measuring the opposite branch from the one it names on every such interpreter.
    What makes the claim true is that BOTH optional linters are now gated on PATH (`command -v`), which is why
    test_every_optional_linter_is_gated_on_PATH_not_on_the_interpreter exists: this directory is only as
    tool-free as the script's probes are PATH-based, and that is a property of the script, not of the directory.
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
    # machine has ruff. `ruff` must be on the `TOOLS` allowlist in that script, and it is: the equality is
    # DERIVED FROM THIS DECORATOR by test_the_TOOLS_allowlist_is_exactly_the_tools_this_suite_gates_on, so
    # renaming the tool here without declaring it there is a red suite, not a silent exemption.
    #
    # WHAT THIS COMMENT USED TO END WITH, and it was a guarantee this project had already WITHDRAWN in
    # docs/CLEAN_CLONE.md ("that is a courtesy to the reader and **not** the anti-laundering defence"):
    #     "It says 'not on PATH' rather than 'not installed' on purpose: torch mode denies the latter on EVERY
    #      skip, tool skips included, so the category cannot launder a missing package."
    # The retraction never reached the comment -- the third time in this project that a withdrawn guarantee
    # outlived its withdrawal in a comment, which is why there is now a source-text test for it
    # (test_no_withdrawn_guarantee_is_restated_in_a_comment): a docstring assertion cannot reach a comment.
    # The wording IS a courtesy to the reader, and nothing more. What bounds the category: the TOOLS allowlist,
    # the package rules (PKG / PKG_EXEMPT), POLICY:TOOL_CAP of 4 -- and, for a RE-PARKED existing skip, the
    # per-module baseline column. Those caps are the real bound, not any rule about wording.
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

    def test_every_optional_linter_is_gated_on_PATH_not_on_the_interpreter(self):
        """F4 OF ROUND 6, AND A REAL LIVE FAILURE: `test_missing_optional_tools_never_fail` measured the
        opposite branch from the one it names, on any interpreter with pyflakes importable.

        `ruff` was gated on `command -v ruff` (PATH) and `pyflakes` on `python3 -m pyflakes --version`
        (THROUGH THE INTERPRETER). `_toolfree_bin` removes tools from PATH only -- the symlinked interpreter
        brings its own site-packages -- so with pyflakes importable `RAN_ANY=1`, the
        "no optional linter (ruff/pyflakes) installed; skipped" branch never fired, and the test asserting that
        branch failed:

            PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python3 -m unittest
            tests.toy_tests.test_scripts    ->  Ran 137 tests, FAILED (failures=1)
            (CPython 3.13.5 with pyflakes 3.4.0; the same command on CPython 3.12.4, which has neither linter,
             was OK -- which is why it was invisible, and CI installs no linter in either job either)

        THE ASYMMETRY IS THE DEFECT, not the probe: two gates on the same kind of thing, written differently,
        and the one nobody looked at was the one that drifted -- the same shape as this round's exemption
        categories. So this is a STRUCTURAL check that every optional-linter gate in the section is a `command
        -v` gate, and that the section invokes no linter through the interpreter. A mutant that puts the `-m`
        probe back fails here on every interpreter, including those where the behavioural test cannot see it.
        """
        text = LINT.read_text(encoding="utf-8")
        m = re.search(r'(?ms)^echo "== optional linters =="\n(.*?)^\[ "\$RAN_ANY" = 1 \]', text)
        self.assertIsNotNone(m, "scripts/lint.sh no longer has an `== optional linters ==` section ending in "
                                "the RAN_ANY report; this test reads that section by text and must be updated "
                                "together with it")
        # COMMENT LINES STRIPPED FIRST: the record of the defect below names the `python3 -m` probe it
        # replaced, and a check that cannot tell the record from the code is a check that forbids the record.
        # (Same convention as `_code_string_literals` for a .sh file: scan what the script EXECUTES.)
        section = "\n".join(l for l in m.group(1).splitlines() if not l.lstrip().startswith("#"))
        gates = re.findall(r"(?m)^if (.+?); then$", section)
        self.assertEqual(sorted(gates), ["command -v pyflakes >/dev/null 2>&1", "command -v ruff >/dev/null 2>&1"],
                         f"every optional linter must be gated on PATH with `command -v`, so that a PATH "
                         f"without it really is a PATH without it (see _toolfree_bin). Found: {gates}")
        self.assertNotIn("python3 -m", section,
                         "an optional linter is invoked through the interpreter in this section: it then sees "
                         "the interpreter's own site-packages and the tool-free-PATH tests measure the "
                         "tools-PRESENT branch:\n" + section)

    def test_a_pyflakes_on_PATH_runs_and_stays_advisory_unless_LINT_STRICT(self):
        """The other half of the PATH gate: gating on PATH must not have quietly DISABLED pyflakes.

        Driven with a stub `pyflakes` on PATH rather than with the real one, so it never skips and adds no
        optional-developer-tool skip category member (`ruff` is the one name on the `TOOLS` allowlist in
        scripts/run_tests.sh, and a second gated test would have to be declared there). The stub reports a
        finding and exits non-zero, which is what the advisory branch is for.
        """
        d = Path(tempfile.mkdtemp(prefix="saferf_pyflakes_stub_"))
        self.addCleanup(shutil.rmtree, str(d), True)
        stub = d / "pyflakes"
        stub.write_text("#!/bin/sh\necho \"x.py:1:1: 'os' imported but unused\"\nexit 1\n", encoding="utf-8")
        stub.chmod(0o755)
        env = {"PATH": _toolfree_bin() + ":" + str(d) + ":/usr/bin:/bin"}
        r = _lint(self.tree({}), env)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)            # advisory: a finding is not fatal
        self.assertIn("pyflakes: 1 finding(s) (advisory)", r.stdout)
        self.assertIn("imported but unused", r.stdout)
        self.assertIn("LINT: OK", r.stdout)
        self.assertNotIn("no optional linter", r.stdout)                  # RAN_ANY really was set
        strict = dict(env, LINT_STRICT="1")
        r = _lint(self.tree({}), strict)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)            # ...and LINT_STRICT makes it fatal
        self.assertIn("LINT: FAIL", r.stdout)

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
            # WORDED AS THE DECLARED PHRASE, which is the round-6 fix reaching a real site: this reason used
            # to read "filesystem is case-sensitive; ..." -- the phrase MID-SENTENCE. The runner's
            # filesystem-case phrase is now anchored (`\A`, like the tool phrase since round 5), so this skip
            # would have been judged as a package skip and the documented `--expect none` run would have gone
            # red with POLICY:NONE_REASON on every case-sensitive filesystem, i.e. on both CI runners. The
            # mid-sentence wording was also invisible to the category's own site scan
            # (test_every_declared_exemption_category_is_claimed_properly_by_the_sites_that_use_it), which is
            # how a reason that claims nothing can sit in the tree looking like a claim.
            self.skipTest("case-sensitive filesystem: a case-varied path does not alias the repo here, so the "
                          "aliasing this test refuses cannot be constructed")
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
