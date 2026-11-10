"""SR-08 tests. TOY RESULT only: synthetic numbers, no biological content, no safety claims.
All files are written to a tempfile directory, never into the repo."""
import ast
import copy
import json
import math
import os
import struct
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from toy import checkpoint as ck
from toy.checkpoint import (Checkpoint, CheckpointError, CheckpointFormatError, CheckpointIntegrityError,
                            CheckpointKeyError, CheckpointNonFiniteError, CheckpointProvenanceError,
                            CheckpointTypeError, CheckpointVersionError, compute_digest, load_checkpoint,
                            save_checkpoint)
from toy.schema import RunProvenance, _canonical
from toy.stability import NonFiniteError, StabilityError
from toy.teacher_student import train

TS = "2025-01-02T03:04:05Z"
BANNED = ("pickle", "cPickle", "_pickle", "torch", "dill", "marshal", "shelve")


def banned_imports(source: str) -> list:
    """AST scan: banned module imports, plus dynamic-import escape hatches."""
    hits = []
    for node in ast.walk(ast.parse(source)):
        names = []
        if isinstance(node, ast.Import):
            names = [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            names = [node.module or ""]
        elif isinstance(node, ast.Name) and node.id in ("__import__", "importlib"):
            hits.append(node.id)
        elif isinstance(node, ast.Attribute) and node.attr in ("import_module", "__import__"):
            hits.append(node.attr)
        for n in names:
            if n.split(".")[0] in BANNED or n.split(".")[0] == "importlib":
                hits.append(n)
    return hits


class Base(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.dir = Path(self._td.name)
        self.path = self.dir / "c.json"
        self.result = train(seed=3, steps=10, timestamp_utc=TS)
        self.prov = self.result.record.provenance
        self.digest = save_checkpoint(self.path, self.result.final_params, self.prov, created_utc=TS)

    def doc(self):
        return json.loads(self.path.read_text())

    def write_doc(self, d, recompute=False):
        if recompute:
            d = {k: v for k, v in d.items() if k != "digest"}
            d["digest"] = compute_digest(d)
        self.path.write_bytes(_canonical(d).encode())

    def write_raw(self, b):
        self.path.write_bytes(b)


class RoundTrip(Base):
    def test_train_result_roundtrip_exact(self):
        cp = load_checkpoint(self.path)
        self.assertIsInstance(cp, Checkpoint)
        self.assertEqual(cp.params, self.result.final_params)
        self.assertEqual(cp.provenance, self.prov)
        self.assertEqual(cp.provenance.to_dict(), self.prov.to_dict())
        self.assertEqual(cp.created_utc, TS)
        self.assertEqual(cp.digest, self.digest)
        self.assertEqual(cp.format_version, 1)

    def test_stable_digest_and_bytes(self):
        p2 = self.dir / "d.json"
        d2 = save_checkpoint(p2, self.result.final_params, self.prov, created_utc=TS)
        self.assertEqual(d2, self.digest)
        self.assertEqual(p2.read_bytes(), self.path.read_bytes())
        r2 = train(seed=3, steps=10, timestamp_utc=TS)
        self.assertEqual(save_checkpoint(self.dir / "e.json", r2.final_params, r2.record.provenance,
                                         created_utc=TS), self.digest)

    def test_pinned_vs_default_timestamp(self):
        d = save_checkpoint(self.dir / "n.json", self.result.final_params, self.prov)
        cp = load_checkpoint(self.dir / "n.json")
        self.assertRegex(cp.created_utc, r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")
        self.assertEqual(cp.digest, d)
        self.assertNotEqual(cp.created_utc, "")

    def test_toy_label_and_no_trailing_newline(self):
        d = self.doc()
        self.assertIn("TOY RESULT", d["label"])
        self.assertFalse(self.path.read_bytes().endswith(b"\n"))
        self.assertEqual(set(d), set(ck.EXPECTED_KEYS))

    def test_digest_is_sha256_of_canonical_without_digest(self):
        import hashlib
        d = self.doc()
        d.pop("digest")
        self.assertEqual(hashlib.sha256(_canonical(d).encode()).hexdigest(), self.digest)

    def test_checkpoint_payload_dict_matches_file(self):
        cp = load_checkpoint(self.path)
        self.assertEqual(compute_digest(cp.payload_dict()), cp.digest)


class FloatFidelity(Base):
    def test_special_floats_exact(self):
        vals = [-0.0, 0.0, 5e-324, -5e-324, 1e308, -1.7976931348623157e308, 2.2250738585072014e-308,
                0.1, 1 / 3, 0.30000000000000004, 123456789.12345678, 1.0000000000000002, 1e22, 1e-7]
        save_checkpoint(self.path, vals, self.prov, created_utc=TS)
        out = load_checkpoint(self.path).params
        self.assertEqual(len(out), len(vals))
        for a, b in zip(vals, out):
            self.assertEqual(struct.pack(">d", a), struct.pack(">d", b), (a, b))
        self.assertTrue(math.copysign(1.0, out[0]) < 0)
        self.assertTrue(math.copysign(1.0, out[1]) > 0)

    def test_seventeen_digit_values(self):
        vals = [float.fromhex("0x1.123456789abcdp+3"), 0.1 + 0.2, 1.7976931348623155e308]
        self.assertTrue(all(len(repr(v).replace(".", "").replace("-", "").split("e")[0]) >= 16 for v in vals[:2]))
        save_checkpoint(self.path, vals, self.prov, created_utc=TS)
        self.assertEqual(load_checkpoint(self.path).params, tuple(vals))

    def test_negative_zero_changes_digest(self):
        a = save_checkpoint(self.dir / "a.json", [0.0, 1.0], self.prov, created_utc=TS)
        b = save_checkpoint(self.dir / "b.json", [-0.0, 1.0], self.prov, created_utc=TS)
        self.assertNotEqual(a, b)

    def test_int_and_bool_params_rejected_on_save(self):
        for bad in ([1, 2.0], [True], [float("nan")], [float("inf")], [], "abc", None, [None], ["1.0"]):
            with self.subTest(bad=bad), self.assertRaises(CheckpointError):
                save_checkpoint(self.dir / "x.json", bad, self.prov, created_utc=TS)
        self.assertFalse((self.dir / "x.json").exists())


class CorruptionMatrix(Base):
    def assertLoadRaises(self, exc):
        with self.assertRaises(exc) as cm:
            load_checkpoint(self.path)
        self.assertIsInstance(cm.exception, CheckpointError)
        self.assertIsInstance(cm.exception, ValueError)
        self.assertTrue(str(cm.exception))
        return cm.exception

    def test_every_single_byte_flip_detected(self):
        raw = self.path.read_bytes()
        self.assertGreater(len(raw), 200)
        for mask in (0x01, 0x20, 0xFF):
            for i in range(len(raw)):
                bad = bytearray(raw)
                bad[i] ^= mask
                self.write_raw(bytes(bad))
                with self.assertRaises(CheckpointError, msg=f"byte {i} mask {mask:#x} not detected"):
                    load_checkpoint(self.path)

    def test_every_single_byte_deletion_and_insertion_detected(self):
        raw = self.path.read_bytes()
        for i in range(len(raw)):
            for bad in (raw[:i] + raw[i + 1:], raw[:i] + b" " + raw[i:]):
                self.write_raw(bad)
                with self.assertRaises(CheckpointError):
                    load_checkpoint(self.path)

    def test_flip_in_params_is_integrity_error(self):
        raw = self.path.read_bytes()
        start = raw.index(b'"params":[') + len(b'"params":[')
        i = raw.index(b",", start) - 1  # last digit of the first parameter
        bad = bytearray(raw)
        self.assertIn(bad[i], b"0123456789")
        bad[i] = ord("7") if bad[i] != ord("7") else ord("6")
        self.write_raw(bytes(bad))
        self.assertLoadRaises(CheckpointIntegrityError)

    def test_truncation_points(self):
        raw = self.path.read_bytes()
        for cut in (1, 2, 10, len(raw) // 4, len(raw) // 2, len(raw) - 10, len(raw) - 2, len(raw) - 1):
            self.write_raw(raw[:cut])
            self.assertLoadRaises(CheckpointFormatError)

    def test_trailing_garbage(self):
        raw = self.path.read_bytes()
        for extra in (b"\n", b" ", b"x", b"{}"):
            self.write_raw(raw + extra)
            self.assertLoadRaises(CheckpointFormatError)

    def test_empty_file(self):
        self.write_raw(b"")
        e = self.assertLoadRaises(CheckpointFormatError)
        self.assertIn("empty", str(e))

    def test_non_json_bytes(self):
        for blob in (b"\x00\x01\x02\xff\xfe", b"not json at all", bytes(range(256)), b"\x80abc"):
            self.write_raw(blob)
            self.assertLoadRaises(CheckpointFormatError)

    def test_top_level_array_and_scalars(self):
        for blob in (b"[]", b"[1,2,3]", b'["a"]', b"null", b"3", b'"str"', b"true"):
            self.write_raw(blob)
            e = self.assertLoadRaises(CheckpointFormatError)
            self.assertIn("top level", str(e))

    def test_duplicate_key(self):
        raw = self.path.read_text()
        self.write_raw(raw.replace('"format_version":1', '"format_version":1,"format_version":1').encode())
        self.assertLoadRaises(CheckpointFormatError)

    def test_unknown_key_added(self):
        d = self.doc()
        d["student_model_state_dict"] = [0.0]
        self.write_doc(d)  # digest now stale too; key guard fires first
        e = self.assertLoadRaises(CheckpointKeyError)
        self.assertIn("student_model_state_dict", str(e))
        self.write_doc(d, recompute=True)  # even with attacker-recomputed digest
        self.assertLoadRaises(CheckpointKeyError)

    def test_key_removed(self):
        for k in ("params", "provenance", "created_utc", "label", "format_version"):
            d = self.doc()
            del d[k]
            self.write_doc(d)
            e = self.assertLoadRaises(CheckpointKeyError)
            self.assertIn(k, str(e))

    def test_renamed_key_mismatch(self):
        d = self.doc()
        d["model_state_dict"] = d.pop("params")
        self.write_doc(d, recompute=True)
        e = self.assertLoadRaises(CheckpointKeyError)
        self.assertIn("model_state_dict", str(e))
        self.assertIn("params", str(e))

    def test_digest_removed(self):
        d = self.doc()
        del d["digest"]
        self.write_doc(d)
        self.assertLoadRaises(CheckpointIntegrityError)

    def test_digest_altered(self):
        d = self.doc()
        d["digest"] = ("0" if d["digest"][0] != "0" else "1") + d["digest"][1:]
        self.write_doc(d)
        e = self.assertLoadRaises(CheckpointIntegrityError)
        self.assertIn("mismatch", str(e))
        for bad in ("", "abc", d["digest"].upper(), "z" * 64):
            d["digest"] = bad
            self.write_doc(d)
            self.assertLoadRaises(CheckpointIntegrityError)
        d["digest"] = 123
        self.write_doc(d)
        self.assertLoadRaises(CheckpointTypeError)

    def test_content_tampered_digest_unchanged(self):
        d = self.doc()
        d["params"][0] = d["params"][0] + 1.0
        self.write_doc(d)
        self.assertLoadRaises(CheckpointIntegrityError)

    def test_attacker_recomputed_digest_is_accepted_documented_limit(self):
        """HONEST LIMIT: a plain digest is not a signature. An attacker who rewrites the
        whole file and recomputes the digest produces a file that loads."""
        d = self.doc()
        d["params"][0] = 999.0
        self.write_doc(d, recompute=True)
        cp = load_checkpoint(self.path)
        self.assertEqual(cp.params[0], 999.0)
        self.assertNotEqual(cp.digest, self.digest)  # only an out-of-band digest comparison catches it

    def test_version_bumped(self):
        for v in (2, 0, -1, 10**9):
            d = self.doc()
            d["format_version"] = v
            self.write_doc(d, recompute=True)
            e = self.assertLoadRaises(CheckpointVersionError)
            self.assertIn("unsupported", str(e))
        for v in ("1", 1.0, True, None, [1]):
            d = self.doc()
            d["format_version"] = v
            self.write_doc(d, recompute=True)
            self.assertLoadRaises(CheckpointVersionError)

    def test_non_finite_param_injected(self):
        raw = self.path.read_text()
        i = raw.index('"params":[') + len('"params":[')
        j = raw.index(",", i)
        for tok in ("NaN", "Infinity", "-Infinity", "1e999", "-1e999"):
            self.write_raw((raw[:i] + tok + raw[j:]).encode())
            e = self.assertLoadRaises(CheckpointNonFiniteError)
            self.assertIsInstance(e, NonFiniteError)
            self.assertIsInstance(e, StabilityError)

    def test_wrong_types(self):
        cases = {
            "params": ["abc", {"a": 1.0}, 5.0, None, [1, 2], [True, 1.0], ["1.0"], [None], [[1.0]], []],
            "created_utc": [20250102, None, ["x"]],
            "label": ["other", 3, None],
            "digest": [None, 5, [], {}],
        }
        for key, bads in cases.items():
            for bad in bads:
                d = self.doc()
                d[key] = bad
                self.write_doc(d, recompute=(key != "digest"))
                with self.subTest(key=key, bad=bad), self.assertRaises(CheckpointError):
                    load_checkpoint(self.path)
        save_checkpoint(self.path, self.result.final_params, self.prov, created_utc=TS)
        d = self.doc()
        d["params"] = [1, 2]
        self.write_doc(d, recompute=True)
        self.assertLoadRaises(CheckpointTypeError)

    def test_bad_timestamp_values(self):
        for bad in ("2025-13-45T00:00:00Z", "2025-01-02 03:04:05", "yesterday", ""):
            d = self.doc()
            d["created_utc"] = bad
            self.write_doc(d, recompute=True)
            self.assertLoadRaises(CheckpointFormatError)

    def test_malformed_provenance(self):
        def mut(f):
            d = self.doc()
            f(d["provenance"] if isinstance(d["provenance"], dict) else d)
            return d
        muts = [
            lambda p: p.__setitem__("toy_only", False),
            lambda p: p.__setitem__("seed", -1),
            lambda p: p.__setitem__("seed", "3"),
            lambda p: p.__setitem__("timestamp_utc", "nope"),
            lambda p: p.__setitem__("input_hashes", {"x": "short"}),
            lambda p: p.__setitem__("input_hashes", [1]),
            lambda p: p.__setitem__("extra", 1),
            lambda p: p.pop("run_id"),
            lambda p: p.__setitem__("run_id", "  "),
        ]
        for m in muts:
            self.write_doc(mut(m), recompute=True)
            self.assertLoadRaises(CheckpointProvenanceError)
        d = self.doc()
        for bad in (None, [], "x", 5):
            d["provenance"] = bad
            self.write_doc(d, recompute=True)
            self.assertLoadRaises(CheckpointProvenanceError)

    def test_oversize_refused(self):
        with mock.patch.object(ck, "MAX_CHECKPOINT_BYTES", 50):
            with self.assertRaises(CheckpointFormatError):
                load_checkpoint(self.path)

    def test_missing_file_is_oserror_not_checkpoint_error(self):
        with self.assertRaises(FileNotFoundError):
            load_checkpoint(self.dir / "nope.json")

    def test_deep_nesting_rejected(self):
        self.write_raw(b"[" * 100000 + b"]" * 100000)
        self.assertLoadRaises(CheckpointFormatError)


class DigestCoverage(Base):
    def test_each_field_mutation_changes_digest(self):
        base = self.doc()
        base.pop("digest")
        h0 = compute_digest(base)
        self.assertEqual(h0, self.digest)
        muts = {
            "format_version": 2,
            "label": base["label"] + "!",
            "created_utc": "2030-01-01T00:00:00Z",
            "params": [base["params"][0] + 1e-9] + base["params"][1:],
        }
        for k, v in muts.items():
            m = copy.deepcopy(base)
            m[k] = v
            self.assertNotEqual(compute_digest(m), h0, k)
        for k in base["provenance"]:
            m = copy.deepcopy(base)
            p = m["provenance"]
            if k == "seed":
                p[k] += 1
            elif k == "toy_only":
                p[k] = False
            elif k == "input_hashes":
                p[k]["x"] = "0" * 64
            else:
                p[k] = p[k] + "x"
            self.assertNotEqual(compute_digest(m), h0, f"provenance.{k}")
        for hk in base["provenance"]["input_hashes"]:
            m = copy.deepcopy(base)
            m["provenance"]["input_hashes"][hk] = "f" * 64
            self.assertNotEqual(compute_digest(m), h0, f"input_hashes.{hk}")
        m = copy.deepcopy(base)
        m["params"] = list(reversed(m["params"]))
        self.assertNotEqual(compute_digest(m), h0, "param order")
        m = copy.deepcopy(base)
        m["extra"] = 1
        self.assertNotEqual(compute_digest(m), h0, "added key")
        m = copy.deepcopy(base)
        m["params"] = m["params"] + [0.0]
        self.assertNotEqual(compute_digest(m), h0, "param length")

    def test_digest_does_not_cover_itself(self):
        with self.assertRaises(CheckpointError):
            compute_digest({**self.doc()})  # contains digest
        self.assertEqual(set(ck._PAYLOAD_KEYS) | {"digest"}, set(ck.EXPECTED_KEYS))

    def test_covers_every_top_level_key_but_digest(self):
        self.assertEqual(set(self.doc()) - {"digest"}, set(ck._PAYLOAD_KEYS))

    def test_key_order_does_not_matter_for_digest_but_file_must_be_canonical(self):
        d = self.doc()
        reordered = dict(reversed(list(d.items())))
        self.path.write_text(json.dumps(reordered))  # valid content, non-canonical bytes
        with self.assertRaises(CheckpointFormatError):
            load_checkpoint(self.path)


class AtomicWrite(Base):
    def test_interrupted_replace_leaves_no_file(self):
        target = self.dir / "new.json"
        with mock.patch("os.replace", side_effect=OSError("simulated interruption")):
            with self.assertRaises(OSError):
                save_checkpoint(target, self.result.final_params, self.prov, created_utc=TS)
        self.assertFalse(target.exists())
        self.assertEqual(sorted(p.name for p in self.dir.iterdir()), ["c.json"])  # no temp leftovers

    def test_interrupted_write_keeps_previous_valid_checkpoint(self):
        before = self.path.read_bytes()
        with mock.patch("os.fsync", side_effect=OSError("simulated crash mid-save")):
            with self.assertRaises(OSError):
                save_checkpoint(self.path, [9.0, 9.0], self.prov, created_utc=TS)
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(load_checkpoint(self.path).digest, self.digest)
        self.assertEqual([p.name for p in self.dir.iterdir()], ["c.json"])

    def test_partial_temp_never_under_target_name(self):
        target = self.dir / "t.json"
        seen = []
        real_replace = os.replace

        def spy(src, dst):
            seen.append(target.exists())  # target must not exist before the rename
            return real_replace(src, dst)
        with mock.patch("os.replace", side_effect=spy):
            save_checkpoint(target, self.result.final_params, self.prov, created_utc=TS)
        self.assertEqual(seen, [False])
        load_checkpoint(target)

    def test_invalid_input_writes_nothing(self):
        before = sorted(p.name for p in self.dir.iterdir())
        with self.assertRaises(CheckpointError):
            save_checkpoint(self.dir / "z.json", [float("nan")], self.prov, created_utc=TS)
        with self.assertRaises(CheckpointError):
            save_checkpoint(self.dir / "z.json", [1.0], self.prov, created_utc="bad")
        with self.assertRaises(CheckpointProvenanceError):
            save_checkpoint(self.dir / "z.json", [1.0], {"run_id": "x"}, created_utc=TS)
        self.assertEqual(sorted(p.name for p in self.dir.iterdir()), before)


class NoPickle(unittest.TestCase):
    SRC = Path(ck.__file__).read_text()

    def test_module_imports_no_banned_modules(self):
        self.assertEqual(banned_imports(self.SRC), [])

    def test_scanner_is_not_vacuous(self):
        # The scanner must flag each banned import form, or the assertion above proves nothing.
        for snippet in ("import pickle", "import torch", "import dill", "import marshal", "import shelve",
                        "from pickle import loads", "import os, pickle", "import torch.nn as nn",
                        "from torch import load", "import pickle as p", "__import__('pickle')",
                        "import importlib", "x.import_module('a')"):
            with self.subTest(snippet=snippet):
                self.assertTrue(banned_imports(snippet), snippet)
        for ok in ("import json", "from hashlib import sha256", "'pickle in a string'",
                   '"""docstring mentions pickle and torch"""'):
            self.assertEqual(banned_imports(ok), [], ok)

    def test_scanner_would_catch_a_tampered_copy_of_the_real_source(self):
        self.assertTrue(banned_imports(self.SRC + "\nimport pickle\n"))
        self.assertTrue(banned_imports("from torch import load\n" + self.SRC))

    def test_source_is_nonempty_and_scanned_file_is_the_checkpoint_module(self):
        self.assertTrue(ck.__file__.endswith(os.path.join("toy", "checkpoint.py")))
        self.assertIn("def load_checkpoint", self.SRC)
        self.assertGreater(len(ast.parse(self.SRC).body), 10)

    def test_checkpoint_file_is_plain_json_data(self):
        with tempfile.TemporaryDirectory() as td:
            r = train(seed=1, steps=2, timestamp_utc=TS)
            p = Path(td) / "c.json"
            save_checkpoint(p, r.final_params, r.record.provenance, created_utc=TS)
            self.assertIsInstance(json.loads(p.read_text()), dict)


if __name__ == "__main__":
    unittest.main()
