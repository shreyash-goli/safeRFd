#!/usr/bin/env python3
"""Offline end-to-end demo of the TOY safety-audit kit (SR-15).

Standard library only. No network, no weights, no credentials. Deterministic: every seed and every timestamp is
pinned, and all output goes to a fresh temporary directory (never into the repository). Exits non-zero on ANY
failure, including a missing/broken module, an in-repo output path, or a failed self-check.

    python3 scripts/demo.py [--src DIR] [--keep]

--src DIR  directory that must contain the `toy` package (default: <repo>/src). Exists so the "dependency
           missing" path can be tested.
--keep     do not delete the temp directory afterwards (its path is printed).

NOTHING THIS SCRIPT PRODUCES IS EVIDENCE ABOUT RFDIFFUSION, THE SAFERFDIFFUSION FORK, OR ANY REAL BIOLOGICAL
CAPABILITY. It exercises synthetic, non-biological toy matrices to show the tooling works.
"""
from __future__ import annotations

import argparse
import importlib.util
import shutil
import sys
import tempfile
import time
from pathlib import Path

sys.dont_write_bytecode = True   # never leave __pycache__ in the repo (see run_tests.sh for why)

REPO = Path(__file__).resolve().parents[1]
TS = "2026-01-01T00:00:00Z"      # pinned: demo outputs must not depend on the wall clock
REQUIRED = ("schema", "teacher_student", "checkpoint", "benchmark", "robustness", "claim_ledger", "dashboard")

DISCLAIMER = """\
==============================================================================
 TOY DEMO. NOT EVIDENCE.
 Nothing printed or written by this demo is evidence about RFdiffusion, the
 safeRFdiffusion fork, or any real biological capability. All data are
 synthetic non-biological toy matrices; no model weights are used.
==============================================================================
"""


class DemoFailure(Exception):
    pass


def check(cond, msg):
    if not cond:
        raise DemoFailure(msg)


def preflight(src: Path) -> None:
    """Detect a missing/unimportable toy package BEFORE doing any work."""
    missing = []
    for name in REQUIRED:
        if not (src / "toy" / f"{name}.py").is_file():
            missing.append(name)
    if missing:
        raise DemoFailure(f"required module(s) not found under {src / 'toy'}: {', '.join(missing)}")
    sys.path.insert(0, str(src))
    for name in REQUIRED:
        if importlib.util.find_spec(f"toy.{name}") is None:
            raise DemoFailure(f"cannot import toy.{name} from {src}")


def run(src: Path, keep: bool) -> int:
    t0 = time.monotonic()
    print(DISCLAIMER)
    preflight(src)
    from toy import benchmark as bm
    from toy import checkpoint as ck
    from toy import claim_ledger as cl
    from toy import dashboard as db
    from toy import robustness as rb
    from toy.schema import EvidenceClass
    from toy.teacher_student import train

    work = Path(tempfile.mkdtemp(prefix="saferf_demo_")).resolve()
    try:
        # Output must never land in the repo (e.g. via a TMPDIR pointing inside it).
        try:
            work.relative_to(REPO)
        except ValueError:
            pass
        else:
            raise DemoFailure(f"temp dir {work} is inside the repository; set TMPDIR elsewhere")
        print(f"[0] temp dir (all outputs go here): {work}")

        # 1. toy teacher/student run
        tr = train(seed=3, steps=60, timestamp_utc=TS)
        loss0, loss1 = tr.history[0][1], tr.history[-1][1]
        check(loss1 < loss0, "toy student loss did not decrease")
        print(f"[1] toy teacher/student: loss {loss0:.4f} -> {loss1:.4f} over {len(tr.history) - 1} steps "
              f"(evidence class {tr.record.evidence_class.value})")

        # 2. checkpoint save + verify (tamper must be detected)
        cp_path = work / "toy.ckpt.json"
        digest = ck.save_checkpoint(cp_path, tr.final_params, tr.record.provenance, created_utc=TS)
        loaded = ck.load_checkpoint(cp_path)
        check(loaded.digest == digest and tuple(loaded.params) == tuple(tr.final_params), "checkpoint round-trip mismatch")
        tampered = work / "tampered.ckpt.json"
        tampered.write_text(cp_path.read_text(encoding="utf-8").replace("[", "[0.0,", 1), encoding="utf-8")
        try:
            ck.load_checkpoint(tampered)
        except ck.CheckpointError:
            tamper = "rejected"
        else:
            raise DemoFailure("tampered checkpoint was accepted")
        print(f"[2] checkpoint saved + verified, digest {digest[:16]}...; tampered copy {tamper}")

        # 3. scorer-validation fixture (a test of the scorer, not of any method)
        cfg = bm.BenchmarkConfig(n_boot=500)
        fz = bm.freeze_seed_list(7, 30)
        joint = bm.run_study(fz, bm.fixture_oracle_gated, subject="demo scorer-validation fixture",
                             registered_digest=fz.digest, cfg=cfg)
        print(f"[3] scorer-validation fixture (ORACLE_GATED) scored on {len(fz.seeds)} seeds: "
              f"verdict {joint.verdict.value}  [tests the scorer; says nothing about any method]")
        check(isinstance(joint.verdict, bm.JointVerdict), "scorer returned no JointVerdict")

        # 4. robustness probe
        card = rb.probe_shift(rb.mse_fsum, rb.shift_reorder_rows(), seeds=tuple(range(12)))
        check(card.summary is not None, "robustness probe produced no summary")
        print(f"[4] robustness probe (row reorder on mse_fsum, 12 seeds): status {card.status.value}")
        rb_rec = rb.scorecard_to_record(card, run_id="demo-robustness", timestamp_utc=TS)

        # 5. claim ledger: open + review (a reviewer's act; it does not validate anything)
        led = cl.ClaimLedger()
        cid = "demo-claim-1"
        led.open_claim(event_id="e1", claim_id=cid, reviewer="demo-script", statement="The toy student loss decreases.",
                       justification="Demonstration of the ledger workflow only.", evidence_class=EvidenceClass.TOY_RESULT,
                       timestamp_utc=TS, evidence_refs=(cl.evidence_from_record(tr.record),))
        led.review(event_id="e2", claim_id=cid, reviewer="demo-script",
                   justification="Reviewed for the demo; no support verdict is issued.",
                   timestamp_utc="2026-01-01T00:00:01Z")
        check(led.verify_chain().ok, "claim ledger chain failed verification")
        check(led.claim_state(cid) is cl.ClaimState.REVIEWED, "claim is not in REVIEWED state")
        print(f"[5] claim ledger: {len(led)} events, chain verified, claim state {led.claim_state(cid).value} "
              f"(not SUPPORTED)")

        # 6. dashboard, rendered twice: must be byte-identical
        data = {"snapshot": db.load_snapshot(), "train": tr, "joint": joint, "records": [tr.record, rb_rec]}
        out = db.write_dashboard(work / "dashboard.html", data)
        first = out.read_bytes()
        check(first == db.render_dashboard(data).encode("utf-8"), "dashboard file differs from a fresh render")
        out2 = db.write_dashboard(work / "dashboard2.html", data)
        check(out2.read_bytes() == first, "dashboard is not byte-identical across renders")
        check(b"<script" not in first and b"http://" not in first and b"https://" not in first,
              "dashboard contains script or external URL")
        print(f"[6] dashboard rendered ({len(first)} bytes, byte-identical on re-render): {out}")

        elapsed = time.monotonic() - t0
        print(f"\nDEMO OK in {elapsed:.1f}s. All checks passed.")
        print(DISCLAIMER)
        if keep:
            print(f"--keep: outputs left in {work}")
        return 0
    finally:
        if not keep:
            shutil.rmtree(work, ignore_errors=True)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--src", default=str(REPO / "src"), help="directory containing the `toy` package")
    ap.add_argument("--keep", action="store_true", help="keep the temp output directory")
    args = ap.parse_args(argv)
    try:
        return run(Path(args.src).resolve(), args.keep)
    except DemoFailure as e:
        print(f"\nDEMO FAILED: {e}", file=sys.stderr)
        return 1
    except Exception as e:   # any other error is also a failure; never exit 0
        print(f"\nDEMO FAILED: unexpected {type(e).__name__}: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
