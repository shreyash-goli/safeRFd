"""Run the tracked mutation harness on Modal, one container per mutant.

WHY THIS IS WORTH DOING, beyond wall-clock. The 15 kills measured so far were all measured on ONE
laptop, with one Python build, one filesystem and one git. A second platform is the only way to find out
whether a kill is a property of the pin or a property of this machine -- which matters here, because
F20 was ITSELF a finding about results that were hostage to one host's installed packages.

PRIVACY. Only `git archive HEAD` is uploaded: an exported tree with NO `.git`, because commit objects
carry author identity. The launcher refuses to upload if it finds an email address in the tree.
"""
import json
import os
import pathlib
import re
import tempfile
import subprocess
import sys

import modal

ROOT = pathlib.Path(__file__).resolve().parents[1]
# The tarball is written beside the repo, never inside it: a stray 4.8 MB artefact in the tree would
# make `git status --porcelain` dirty, which this launcher itself refuses to upload on.
TAR_LOCAL = pathlib.Path(os.environ.get("SAFERF_TAR", tempfile.gettempdir() + "/saferf_kit_head.tar"))
TAR_REMOTE = "/opt/kit.tar"

EMAIL = re.compile(rb"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
# Allowed: the two upstream GitHub URLs the audit cites. Nothing else may carry an @.
ALLOWED = (b"noreply@github.com",)


def export_and_screen() -> list[str]:
    """`git archive HEAD` to a tarball, then REFUSE to go further if it carries an email address."""
    with TAR_LOCAL.open("wb") as fh:
        subprocess.run(["git", "archive", "HEAD"], cwd=ROOT, stdout=fh, check=True)
    blob = TAR_LOCAL.read_bytes()
    # MEMBER PATHS, not a byte search. Checking `b".git/" in blob` says YES on this very tree, because
    # docs/SR12_INDEPENDENT_REVIEW.md discusses `.git/` in prose -- a lexical match reported as a
    # structural fact, which is the error this project keeps catching in other people's work.
    import tarfile, io
    with tarfile.open(fileobj=io.BytesIO(blob)) as tf:
        members = tf.getnames()
    leaked = [m for m in members if m == ".git" or m.startswith(".git/")]
    if leaked:
        raise SystemExit(f"REFUSING TO UPLOAD: {len(leaked)} member(s) under .git/ -- commit objects "
                         f"carry author identity: {leaked[:5]}")
    print(f"tar members: {len(members)}, none under .git/")
    hits = {m for m in EMAIL.findall(blob) if m not in ALLOWED}
    if hits:
        raise SystemExit(f"REFUSING TO UPLOAD: the exported tree contains {len(hits)} email "
                         f"address(es): {sorted(h.decode() for h in hits)[:5]}")
    head = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT,
                          capture_output=True, text=True, check=True).stdout.strip()
    dirty = subprocess.run(["git", "status", "--porcelain"], cwd=ROOT,
                           capture_output=True, text=True, check=True).stdout
    if dirty:
        raise SystemExit(f"REFUSING TO UPLOAD: the tree is dirty, so `git archive HEAD` is not what is "
                         f"being tested:\n{dirty}")
    ids = [m["id"] for m in json.loads((ROOT / "scripts" / "mutants.json").read_text())["mutants"]]
    print(f"exported HEAD {head}: {len(blob)} bytes, no email addresses, {len(ids)} mutants")
    return ids


app = modal.App("saferf-mutants")
image = (modal.Image.debian_slim(python_version="3.12")
         .apt_install("git")
         .add_local_file(TAR_LOCAL, TAR_REMOTE, copy=True))


@app.function(image=image, timeout=1800, max_containers=16)
def run_one(mid: str) -> dict:
    import os
    import pathlib as pl
    import subprocess as sp
    work = pl.Path("/work")
    work.mkdir(exist_ok=True)
    sp.run(["tar", "-xf", TAR_REMOTE, "-C", str(work)], check=True)
    env = {**os.environ,
           "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",     # the precondition this kit documents
           "PYTHONDONTWRITEBYTECODE": "1",
           "GIT_CONFIG_GLOBAL": "/dev/null",          # no identity, no user config, anywhere
           "GIT_CONFIG_SYSTEM": "/dev/null",
           "HOME": "/root"}
    r = sp.run([sys.executable, "scripts/mutate.py", "--tree", str(work), "--id", mid],
               cwd=str(work), capture_output=True, text=True, env=env)
    plat = sp.run([sys.executable, "-c",
                   "import platform,sys;print(platform.platform(), sys.version.split()[0])"],
                  capture_output=True, text=True).stdout.strip()
    return {"id": mid, "rc": r.returncode, "platform": plat,
            "out": r.stdout[-6000:], "err": r.stderr[-3000:]}


@app.local_entrypoint()
def main():
    ids = export_and_screen()
    results = list(run_one.map(ids))
    print()
    killed, other = [], []
    for res in sorted(results, key=lambda d: d["id"]):
        line = [ln for ln in res["out"].splitlines()
                if ln.startswith(res["id"]) or " KILLED " in ln or "SURVIVED" in ln or "ERROR" in ln]
        # THREE OUTCOMES, NOT TWO. This read `rc == 0 and ... else "NOT KILLED"`, which reports an
        # INTERRUPTED OR PREEMPTED container as a finding -- and a preempted container is routine on a
        # pool. Independent QA found this paired with the harness's SIGTERM path exiting 1 instead of
        # 130. A worker that never reached a verdict has not measured a survival; saying it did is the
        # direction this project says gets written down as a finding.
        tail = res["out"] + res["err"]
        if res["rc"] == 0 and "1/1 KILLED" in tail:
            verdict = "KILLED"
        elif "SURVIVED" in tail or "NOT KILLED" in tail or "RUN FAILURE" in tail:
            verdict = "NOT KILLED"
        else:
            verdict = "NO VERDICT"      # interrupted, preempted, or died before reporting
        (killed if verdict == "KILLED" else other).append(f"{res['id']} ({verdict})")
        print(f"{res['id']:<30} {verdict:<11} rc={res['rc']}  {(line[-1][:90] if line else '')}")
        if verdict != "KILLED":
            print("   stdout tail:", res["out"][-700:].replace("\n", "\n   "))
            print("   stderr tail:", res["err"][-500:].replace("\n", "\n   "))
    print(f"\n{len(killed)}/{len(results)} KILLED on Modal")
    if results:
        print("worker platform:", results[0]["platform"])
    if other:
        print("NOT KILLED:", other)
        raise SystemExit(1)
