"""SR-04 schema tests. TOY data only: abstract numbers, no biological content."""
import dataclasses
import json
import math
import random
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from toy.schema import (EvidenceClass, ExperimentRecord, MetricValue, RunProvenance,
                        current_python_version, derive_seed, make_rng)

H = "a" * 64


def prov(**kw):
    base = dict(run_id="run-001", timestamp_utc="2025-01-02T03:04:05Z", seed=7,
                code_version="deadbeef", python_version="3.12.0", toy_only=True,
                input_hashes={"matrix_a": H})
    base.update(kw)
    return RunProvenance(**base)


def record(**kw):
    base = dict(name="toy-exp", provenance=prov(),
                metrics={"loss": MetricValue.measured(0.25), "zero": MetricValue.measured(0.0),
                         "missing": MetricValue.unmeasured("not run")},
                evidence_class=EvidenceClass.TOY_RESULT, notes="abstract numbers")
    base.update(kw)
    return ExperimentRecord(**base)


class HappyPath(unittest.TestCase):
    def test_roundtrip_exact_and_hash_stable(self):
        r = record()
        text = r.to_json()
        r2 = ExperimentRecord.from_json(text)
        self.assertEqual(r, r2)
        self.assertEqual(text, r2.to_json())
        self.assertEqual(r.content_hash(), r2.content_hash())
        self.assertEqual(r.content_hash(), record().content_hash())
        self.assertEqual(len(r.content_hash()), 64)

    def test_sorted_keys_and_toy_label(self):
        d = json.loads(record().to_json())
        self.assertIn("TOY RESULT", d["label"])
        self.assertEqual(list(d), sorted(d))

    def test_hash_changes_with_content(self):
        self.assertNotEqual(record().content_hash(), record(name="other").content_hash())

    def test_current_python_version_valid(self):
        prov(python_version=current_python_version())


class InvalidInputs(unittest.TestCase):
    def test_nonfinite_metrics(self):
        for bad in (float("nan"), float("inf"), float("-inf")):
            with self.assertRaises(ValueError):
                MetricValue.measured(bad)

    def test_nonfinite_json_rejected(self):
        text = record().to_json().replace('"value":0.25', '"value":NaN')
        with self.assertRaises(ValueError):
            ExperimentRecord.from_json(text)

    def test_bad_seeds(self):
        for bad in (-1, 1.5, "7", None, True):
            with self.assertRaises(ValueError, msg=repr(bad)):
                prov(seed=bad)

    def test_blank_run_id(self):
        for bad in ("", "   ", None, 5):
            with self.assertRaises(ValueError):
                prov(run_id=bad)

    def test_malformed_timestamp(self):
        for bad in ("2025-01-02", "2025-01-02T03:04:05", "2025-13-02T03:04:05Z",
                    "2025-02-30T03:04:05Z", "yesterday", "2025-01-02T03:04:05+00:00"):
            with self.assertRaises(ValueError, msg=bad):
                prov(timestamp_utc=bad)

    def test_unknown_evidence_class(self):
        with self.assertRaises(ValueError):
            EvidenceClass.parse("PROVEN_SAFE")
        with self.assertRaises(ValueError):
            EvidenceClass.parse(3)
        d = json.loads(record().to_json())
        d["evidence_class"] = "PROVEN_SAFE"
        with self.assertRaises(ValueError):
            ExperimentRecord.from_json(json.dumps(d))
        with self.assertRaises(ValueError):
            record(evidence_class="TOY_RESULT")  # no silent coercion

    def test_toy_only_false_rejected(self):
        for bad in (False, 0, 1, None, "true"):
            with self.assertRaises(ValueError):
                prov(toy_only=bad)
        d = json.loads(record().to_json())
        d["provenance"]["toy_only"] = False
        with self.assertRaises(ValueError):
            ExperimentRecord.from_json(json.dumps(d))

    def test_unknown_and_missing_keys(self):
        for path in ([], ["provenance"], ["metrics", "loss"]):
            d = json.loads(record().to_json())
            t = d
            for p in path:
                t = t[p]
            t["extra"] = 1
            with self.assertRaises(ValueError, msg=str(path)):
                ExperimentRecord.from_json(json.dumps(d))
        d = json.loads(record().to_json())
        del d["evidence_class"]
        with self.assertRaises(ValueError):
            ExperimentRecord.from_json(json.dumps(d))

    def test_wrong_types(self):
        with self.assertRaises(ValueError):
            MetricValue.measured(1)  # int not coerced
        with self.assertRaises(ValueError):
            MetricValue.measured(True)
        with self.assertRaises(ValueError):
            record(metrics={"loss": 0.5})
        with self.assertRaises(ValueError):
            record(metrics=[("loss", MetricValue.measured(0.5))])
        with self.assertRaises(ValueError):
            record(provenance={"run_id": "x"})
        with self.assertRaises(ValueError):
            record(notes=5)
        with self.assertRaises(ValueError):
            prov(input_hashes={"a": "not-a-hash"})
        with self.assertRaises(ValueError):
            prov(input_hashes={"a": "A" * 64})
        with self.assertRaises(ValueError):
            ExperimentRecord.from_json("[1,2]")
        with self.assertRaises(ValueError):
            ExperimentRecord.from_json("{not json")
        with self.assertRaises(ValueError):
            ExperimentRecord.from_json(None)

    def test_duplicate_json_keys_top_level(self):
        text = record().to_json()
        ExperimentRecord.from_json(text)  # baseline is valid
        dup = text.replace('"name":"toy-exp"', '"name":"toy-exp","name":"toy-exp"', 1)
        self.assertNotEqual(dup, text)
        with self.assertRaisesRegex(ValueError, "duplicate JSON key"):
            ExperimentRecord.from_json(dup)

    def test_duplicate_json_keys_nested(self):
        text = record().to_json()
        dup = text.replace('"seed":7', '"seed":7,"seed":8', 1)
        self.assertNotEqual(dup, text)
        with self.assertRaisesRegex(ValueError, "duplicate JSON key"):
            ExperimentRecord.from_json(dup)

    def test_bad_schema_version(self):
        d = json.loads(record().to_json())
        d["schema_version"] = "99"
        with self.assertRaisesRegex(ValueError, "schema_version"):
            ExperimentRecord.from_json(json.dumps(d))

    def test_parse_constant_hook_isolated(self):
        # Call the strict loader directly: only its parse_constant hook can reject these.
        from toy.schema import _strict_loads
        for const in ("NaN", "Infinity", "-Infinity"):
            with self.assertRaisesRegex(ValueError, "non-finite JSON constant"):
                _strict_loads('{"x": %s}' % const)
        self.assertEqual(_strict_loads('{"x": 1.5}'), {"x": 1.5})

    def test_sha256_strict(self):
        for bad in ("a" * 64 + "\n", "a" * 63, "a" * 65, "\n" + "a" * 64):
            with self.assertRaises(ValueError, msg=repr(bad)):
                prov(input_hashes={"a": bad})

    def test_timestamp_ascii_digits_only(self):
        for bad in ("\uff12\uff10\uff12\uff15-01-02T03:04:05Z", "2025-01-02T03:04:05Z\n"):
            with self.assertRaises(ValueError, msg=repr(bad)):
                prov(timestamp_utc=bad)

    def test_label_tampering_rejected(self):
        text = record().to_json()
        d = json.loads(text)
        for bad in ("VALIDATED SAFE", None, "", 5):
            d["label"] = bad
            with self.assertRaisesRegex(ValueError, "label"):
                ExperimentRecord.from_json(json.dumps(d))

    def test_label_near_misses_rejected(self):
        good = "TOY RESULT (synthetic, non-biological; not a safety finding)"
        near = [good + " ", " " + good, good + "\n", good.lower(), "TOY RESULT",
                good[:10] + "\u200b" + good[10:], good.replace("not a safety finding", "a safety finding"),
                good.replace("finding", "claim"),   # the pre-F15 wording is now a near miss
                good + " validated safe"]
        d = json.loads(record().to_json())
        for bad in near:
            self.assertNotEqual(bad, good)
            d["label"] = bad
            with self.assertRaisesRegex(ValueError, "label", msg=repr(bad)):
                ExperimentRecord.from_json(json.dumps(d))

    def test_deep_nesting_is_valueerror(self):
        for text in ("[" * 100000, '{"a":' * 100000):
            with self.assertRaisesRegex(ValueError, "nesting too deep"):
                ExperimentRecord.from_json(text)

    def test_roundtrip_identity_on_text(self):
        for r in (record(), record(metrics={}, notes=None)):
            t = r.to_json()
            self.assertEqual(ExperimentRecord.from_json(t).to_json(), t)

    def test_seed_bounds(self):
        prov(seed=0)
        prov(seed=2**64 - 1)
        with self.assertRaises(ValueError):
            prov(seed=2**64)
        with self.assertRaises(ValueError):
            prov(seed=2**200)
        with self.assertRaises(ValueError):
            make_rng(2**64)
        with self.assertRaises(ValueError):
            derive_seed(2**64, "a")

    def test_negative_zero_normalised(self):
        a, b = MetricValue.measured(0.0), MetricValue.measured(-0.0)
        self.assertEqual(a, b)
        self.assertEqual(math.copysign(1.0, b.value), 1.0)
        ra = record(metrics={"m": a})
        rb = record(metrics={"m": b})
        self.assertEqual(ra.content_hash(), rb.content_hash())
        self.assertEqual(ra.to_json(), rb.to_json())
        self.assertNotIn("-0.0", rb.to_json())

    def test_source_observed_rejected_for_run_records(self):
        with self.assertRaisesRegex(ValueError, "audit/claim records"):
            record(evidence_class=EvidenceClass.SOURCE_OBSERVED)
        d = json.loads(record().to_json())
        d["evidence_class"] = "SOURCE_OBSERVED"
        with self.assertRaisesRegex(ValueError, "audit/claim records"):
            ExperimentRecord.from_json(json.dumps(d))
        self.assertIn("SOURCE_OBSERVED", EvidenceClass.__members__)
        for ec in EvidenceClass:
            if ec is not EvidenceClass.SOURCE_OBSERVED:
                record(evidence_class=ec)

    def test_unmeasured_needs_reason_and_measured_forbids_one(self):
        with self.assertRaises(ValueError):
            MetricValue(None)
        with self.assertRaises(ValueError):
            MetricValue.unmeasured("  ")
        with self.assertRaises(ValueError):
            MetricValue(1.0, "reason")

    def test_frozen(self):
        r = record()
        for obj, attr in ((r, "name"), (r.provenance, "seed"), (r.metrics["loss"], "value")):
            with self.assertRaises(dataclasses.FrozenInstanceError, msg=type(obj).__name__):
                setattr(obj, attr, obj.__class__ and getattr(obj, attr))
        with self.assertRaises(TypeError):
            r.metrics["new"] = MetricValue.measured(1.0)
        with self.assertRaises(TypeError):
            r.provenance.input_hashes["x"] = H


class MissingEvidence(unittest.TestCase):
    def test_unmeasured_is_not_zero(self):
        missing = MetricValue.unmeasured("not run")
        zero = MetricValue.measured(0.0)
        self.assertIsNone(missing.value)
        self.assertNotEqual(missing, zero)
        self.assertNotEqual(missing.value, 0.0)
        self.assertFalse(missing.is_measured)
        self.assertTrue(zero.is_measured)
        self.assertEqual(missing.render(), "UNKNOWN")
        self.assertEqual(zero.render(), "0.0")

    def test_distinct_after_roundtrip_and_hash(self):
        r = record()
        r2 = ExperimentRecord.from_json(r.to_json())
        self.assertIsNone(r2.metrics["missing"].value)
        self.assertEqual(r2.metrics["zero"].value, 0.0)
        self.assertIsNot(r2.metrics["missing"].value, 0.0)
        d = json.loads(r.to_json())
        self.assertIsNone(d["metrics"]["missing"]["value"])
        self.assertEqual(d["metrics"]["zero"]["value"], 0.0)
        swapped = record(metrics={"missing": MetricValue.measured(0.0)})
        other = record(metrics={"missing": MetricValue.unmeasured("not run")})
        self.assertNotEqual(swapped.content_hash(), other.content_hash())

    def test_absent_metric_not_defaulted(self):
        r = record(metrics={})
        self.assertNotIn("loss", r.metrics)
        self.assertEqual(ExperimentRecord.from_json(r.to_json()).metrics, {})


class Determinism(unittest.TestCase):
    def test_same_seed_same_sequence(self):
        a = [make_rng(5).random() for _ in range(1)]
        r1, r2 = make_rng(5), make_rng(5)
        self.assertEqual([r1.random() for _ in range(20)], [r2.random() for _ in range(20)])
        self.assertEqual(a[0], make_rng(5).random())

    def test_different_seed_differs(self):
        self.assertNotEqual([make_rng(1).random() for _ in range(5)], [make_rng(2).random() for _ in range(5)])

    def test_global_state_untouched(self):
        random.seed(123)
        before = random.getstate()
        make_rng(9).random()
        derive_seed(9, "sub")
        prov(); record()
        self.assertEqual(random.getstate(), before)

    def test_derive_seed(self):
        self.assertEqual(derive_seed(1, "a"), derive_seed(1, "a"))
        self.assertNotEqual(derive_seed(1, "a"), derive_seed(1, "b"))
        self.assertNotEqual(derive_seed(1, "a"), derive_seed(2, "a"))
        for bad in (-1, 1.0):
            with self.assertRaises(ValueError):
                derive_seed(bad, "a")
        with self.assertRaises(ValueError):
            derive_seed(1, " ")


if __name__ == "__main__":
    unittest.main()
