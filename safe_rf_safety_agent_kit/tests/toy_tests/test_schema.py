"""SR-04 schema tests. TOY data only: abstract numbers, no biological content."""
import ast
import dataclasses
import json
import math
import random
import sys
import unittest
from collections.abc import Mapping
from enum import Enum
from pathlib import Path
from types import MappingProxyType

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from toy import schema
from toy.schema import (SCHEMA_VERSION, TOY_LABEL, EvidenceClass, ExperimentRecord, MetricValue, RunProvenance,
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


class AMetricStoresTheNumberItChecked(unittest.TestCase):
    """F1, THE ROOT DEFECT OF THIS ROUND, pinned where it lives.

    `MetricValue.__post_init__` validated `self.value` with `isinstance` and `math.isfinite` -- neither
    of which a `float` SUBCLASS can lie to -- and then ended with a -0.0 normalisation written as
    `self.value == 0.0`, which is `type(self.value).__eq__` and IS overridable. So the last act of the
    schema's own validator was to decide, by asking the value itself, whether to REPLACE the value:

        class EqZero(float):
            def __eq__(self, o):  return True
            def __hash__(self):   return 0
        MetricValue.measured(EqZero(7.0)).value   ->   0.0

    No `object.__setattr__`, no tampering primitive, one public classmethod. Every module in this kit
    stores measurements as `MetricValue`s, so this was upstream of `toy.benchmark._metric_read`,
    `_plain_number` and `toy.robustness._plain_summary_fields` -- all three of which exist for this
    exact pattern and none of which could help, because the substitution had already happened at
    construction. The fix is `float.__float__`, which reads the double the object STORES: the number
    checked, the number stored, the number serialized and the number compared are then one number.
    NOT reachable by deserialisation -- `from_dict` yields plain floats out of JSON -- so the route is
    an in-process `float` subclass, which is exactly what a producer module hands to
    `MetricValue.measured(...)`."""

    class EqZero(float):
        def __eq__(self, o):
            return True

        def __ne__(self, o):
            return False

        def __hash__(self):
            return 0

    class Lying(float):
        """Lies about everything a conversion or a comparison could consult."""
        def __eq__(self, o):
            return True

        def __ne__(self, o):
            return False

        def __float__(self):
            return 1e308

        def __abs__(self):
            return 0.0

        def __gt__(self, o):
            return True

        def __lt__(self, o):
            return False

        def __repr__(self):
            return "0.0"

        def __hash__(self):
            return 0

    def test_a_float_subclass_cannot_replace_the_stored_value(self):
        for cls in (self.EqZero, self.Lying):
            for stored in (7.0, -7.0, 0.25, 1e-300, 1e300, 5e-324):
                with self.subTest(sneak=cls.__name__, stored=stored):
                    mv = MetricValue.measured(cls(stored))
                    self.assertIs(type(mv.value), float, "the subclass instance is still stored")
                    self.assertEqual(mv.value, stored)
                    # and the stored number is what every consumer sees, however it reads it
                    self.assertEqual(mv.to_dict()["value"], stored)
                    self.assertEqual(json.loads(json.dumps(mv.to_dict()))["value"], stored)
                    self.assertEqual(mv.render(), repr(stored))
                    self.assertTrue(mv.is_measured)

    def test_the_minus_zero_normalisation_this_line_is_for_still_works(self):
        """The fix must not cost the property the line exists for: -0.0 -> 0.0 so equal values hash
        equally. Asserted on the plain floats AND through a subclass holding -0.0."""
        for z in (-0.0, self.EqZero(-0.0), self.Lying(-0.0)):
            mv = MetricValue.measured(z)
            self.assertEqual(math.copysign(1.0, mv.value), 1.0, repr(type(z)))
            self.assertIs(type(mv.value), float)
            self.assertNotIn("-0.0", record(metrics={"m": mv}).to_json())
        self.assertEqual(record(metrics={"m": MetricValue.measured(0.0)}).content_hash(),
                         record(metrics={"m": MetricValue.measured(-0.0)}).content_hash())

    def test_the_serialisation_contract_is_unchanged_for_honest_values(self):
        """SCHEMA_VERSION and every stored `content_hash` are a contract: the fix must be invisible to
        an honest record. The baseline hash below was computed from `HEAD:src/toy/schema.py` -- the
        version BEFORE the fix -- on this same `record()` fixture, and it is pinned BY VALUE so that a
        future change to `MetricValue.to_dict`, `TOY_LABEL` or the canonical JSON cannot pass
        unnoticed. SCHEMA_VERSION did NOT move: nothing an honest record serialises changed."""
        self.assertEqual(SCHEMA_VERSION, "2")
        self.assertEqual(record().content_hash(),
                         "09aa84a200ffc456a472aa4cbadf5dec1396b21bbe2867afda4b898ac230f283")
        self.assertEqual(MetricValue.measured(0.25).to_dict(), {"value": 0.25, "reason": None})
        r = record()
        self.assertEqual(ExperimentRecord.from_json(r.to_json()).content_hash(), r.content_hash())
        # identity, not merely equality: an honest float is stored unchanged, so nothing is copied
        v = 0.3 + 0.4
        self.assertIs(MetricValue.measured(v).value, v)

    def test_the_type_rules_are_not_weakened_by_the_normalisation(self):
        """`float.__float__` must not become a coercion: an int, a bool and a non-finite are still
        refused, and a subclass whose STORED double is non-finite is refused for its stored value."""
        for bad in (1, True, False, "0.0", None, [0.0]):
            with self.assertRaises(ValueError, msg=repr(bad)):
                MetricValue.measured(bad)
        for bad in (float("nan"), float("inf"), float("-inf")):
            with self.assertRaises(ValueError, msg=repr(bad)):
                MetricValue.measured(self.EqZero(bad))
            with self.assertRaises(ValueError, msg=repr(bad)):
                MetricValue.measured(self.Lying(bad))
        with self.assertRaises(ValueError):
            MetricValue(self.EqZero(1.0), "reason")      # measured + reason still refused


class TheKeySetCheckComparesPlainKeys(unittest.TestCase):
    """One site's behaviour, pinned. NOT the last instance of anything -- see below.

    THE SENTENCE THAT USED TO OPEN THIS DOCSTRING was "The last instance the operator sweep turned up,
    reported as the minor thing it is." It is deleted rather than softened, because it was FALSE BY FOUR
    COUNTEREXAMPLES, every one of them live in the unmodified tree one round later, reproduced through
    public entry points with no `object.__setattr__`: `RunProvenance.input_hashes` was format-checked and
    then stored un-normalised, so a 64-lowercase-hex `str` subclass decided
    `toy.benchmark.verdict_from_records`' own config binding (JOINT_INCONCLUSIVE -> JOINT_SUPPORTED);
    `ExperimentRecord.from_dict`'s version and label gates were `!=` on the caller's object, which
    laundered a version-1 record and silently relabelled a record reading "VERIFIED SAFETY FINDING";
    `toy.robustness.arm_difference` ran its membership test on un-normalised arm NAMES, turning an absent
    arm into a measured 0.0; and `toy.robustness.shift_reorder_rows`'s `rel_tol` was the un-swept sibling
    of a `tol` the previous round had just fixed.
    STANDING RULE, which is why no sentence replacing it quotes a number: a claim that a sweep found the
    LAST instance is a claim about ABSENCE, and sweeping cannot establish absence. A sweep can only ever
    report what it found. What makes a NEW site covered is therefore not a better sweep but a boundary
    whose field list is read from the class -- `_normalise_fields`, pinned by
    `EveryDataclassFieldIsNormalisedOrExplicitlyExempt` below, which fails closed on a new field and on a
    new dataclass. This class pins what it always pinned: the behaviour of `_check_keys`.

    `_check_keys` compares key SETS, so it runs on `__hash__` and `__eq__`. A `str` subclass whose hash
    equals a real key's and whose `__eq__` always returns True is accepted as that key. MEASURED on both
    routes, because they differ and only one is a defect:
      * top level: it was HARMLESS, and that is stated as a measurement rather than assumed.
        `ExperimentRecord.from_dict` reads its fields by explicit `data["name"]` lookups, which the same
        lying `__eq__` resolves to the same values, so the record built was BYTE-IDENTICAL to the honest
        one (measured before the fix). A provenance argument would have said "a caller who can build the
        dict could just use the right key"; the validity argument is the byte-identical record.
      * nested: a real, if small, defect. `RunProvenance.from_dict` uses `cls(**data)`, so a mislabelled
        key reached the constructor as a keyword and escaped as `TypeError: got multiple values for
        argument ...`, outside this module's stated `ValueError` contract.
    Normalising the key set closes the nested escape and, as a side effect, gives the top-level case a
    diagnostic instead of a silent resolution. The gain is the DIAGNOSTIC and the error contract, not
    secrecy: a caller who builds the dict always controlled its contents."""

    @staticmethod
    def liar(target):
        class K(str):
            def __hash__(self):
                return hash(target)

            def __eq__(self, o):
                return True
        return K

    def test_a_mislabelled_nested_key_is_a_valueerror_not_a_typeerror(self):
        d = record().to_dict()
        p = dict(d["provenance"])
        p[self.liar("run_id")("bogus")] = p.pop("run_id")
        d["provenance"] = p
        with self.assertRaises(ValueError) as cm:
            ExperimentRecord.from_dict(d)
        self.assertIn("bogus", str(cm.exception))      # the key is NAMED, not swallowed
        try:
            ExperimentRecord.from_dict(d)
        except TypeError:                              # pragma: no cover - the defect, if it returns
            self.fail("TypeError escaped from_dict, outside the stated ValueError contract")
        except ValueError:
            pass

    def test_a_top_level_mislabelled_key_is_named_too(self):
        d = record().to_dict()
        d[self.liar("name")("nonsense")] = d.pop("name")
        with self.assertRaisesRegex(ValueError, r"unknown keys \['nonsense'\]"):
            ExperimentRecord.from_dict(d)

    def test_honest_key_sets_are_unaffected(self):
        for path in ([], ["provenance"], ["metrics", "loss"]):
            d = json.loads(record().to_json())
            t = d
            for k in path:
                t = t[k]
            t["extra"] = 1
            with self.assertRaisesRegex(ValueError, "unknown keys", msg=str(path)):
                ExperimentRecord.from_json(json.dumps(d))
        d = json.loads(record().to_json())
        del d["provenance"]["seed"]
        with self.assertRaisesRegex(ValueError, "missing keys"):
            ExperimentRecord.from_json(json.dumps(d))
        self.assertEqual(ExperimentRecord.from_json(record().to_json()).content_hash(),
                         record().content_hash())


class ASeedIsNormalisedBeforeItIsCompared(unittest.TestCase):
    """F2b: `_check_seed` inspected the caller's object and discarded the result.

    `seed < 0` and `seed > MAX_SEED` are overridable comparisons, and `derive_seed` FORMATS the seed
    into the string it hashes (`__format__` / `__str__`, also overridable). The sharp consequence is
    not the range check: it is that two seeds a duplicate check sees as DISTINCT could derive the SAME
    sub-run seed, and therefore the same fixture, so `toy.robustness`'s "n distinct seeds" could be one
    example n times with no repeated value anywhere in the card."""

    class LtSeed(int):
        def __lt__(self, o):
            return False

        def __gt__(self, o):
            return False

        def __le__(self, o):
            return False

        def __ge__(self, o):
            return False

    class StrSeed(int):
        def __str__(self):
            return "7"

        def __format__(self, spec):
            return "7"

    def test_an_out_of_range_seed_subclass_is_refused_for_its_stored_value(self):
        for bad in (-1, -5, 2 ** 64, 2 ** 200):
            with self.subTest(stored=bad):
                with self.assertRaises(ValueError):
                    make_rng(self.LtSeed(bad))
                with self.assertRaises(ValueError):
                    derive_seed(self.LtSeed(bad), "a")
                with self.assertRaises(ValueError):
                    prov(seed=self.LtSeed(bad))
        for good in (0, 7, 2 ** 64 - 1):
            self.assertEqual(derive_seed(self.LtSeed(good), "a"), derive_seed(good, "a"))

    def test_two_distinct_seeds_cannot_derive_one_fixture(self):
        self.assertNotEqual(derive_seed(self.StrSeed(9), "a"), derive_seed(7, "a"))
        self.assertEqual(derive_seed(self.StrSeed(9), "a"), derive_seed(9, "a"))
        # and the generator is seeded with the stored value, not with whatever __str__ says
        self.assertEqual([make_rng(self.StrSeed(9)).random() for _ in range(3)],
                         [make_rng(9).random() for _ in range(3)])
        self.assertNotEqual(make_rng(self.StrSeed(9)).random(), make_rng(7).random())

    def test_a_provenance_record_stores_the_plain_seed(self):
        p = prov(seed=self.StrSeed(9))
        self.assertIs(type(p.seed), int)
        self.assertEqual(p.seed, 9)
        self.assertEqual(p.to_dict()["seed"], 9)
        self.assertEqual(json.loads(json.dumps(p.to_dict()))["seed"], 9)
        # ... so two records differing only in the seed's TYPE are byte-identical
        self.assertEqual(record(provenance=prov(seed=self.StrSeed(9))).content_hash(),
                         record(provenance=prov(seed=9)).content_hash())
        self.assertEqual(len({p.seed} & {9}), 1)       # a set built from it behaves


# =================================================== the round-6 findings, pinned by consequence
class TwoKeyMapping(Mapping):
    """A real `Mapping` that really yields TWO distinct key objects.

    Needed because a dict LITERAL cannot carry the collapse: `{"seed_list": a, Collapse("scorecard"): b}`
    collapses inside the CALLER's own dict, before any constructor sees two entries, so the schema is
    handed an honest one-entry mapping and has nothing to detect. The realisable shape of the defect is a
    non-dict `Mapping` whose `.items()` yields both, which `RunProvenance.__post_init__` iterates."""

    def __init__(self, pairs):
        self._pairs = list(pairs)

    def __iter__(self):
        return iter(k for k, _ in self._pairs)

    def __len__(self):
        return len(self._pairs)

    def __getitem__(self, key):
        for k, v in self._pairs:
            if k is key or str.__str__(k) == str.__str__(key):
                return v
        raise KeyError(key)

    def items(self):
        return list(self._pairs)


class LyingText(str):
    """64-lowercase-hex-compatible `str` subclass: equal to everything, unequal to nothing.

    It does NOT lie to `str.__str__`, to `str.strip()` or to a regex -- it does not have to. The guards
    it defeats are written in `==` / `!=` / `in`, and those are what it overrides."""

    def __eq__(self, other):
        return True

    def __ne__(self, other):
        return False

    def __hash__(self):
        return hash(str.__str__(self))


_STUDY = {}


def study_records():
    """A real SR-10 study run at `width_tol=0.10`, with its records. Cached: ~2.5s per run.

    This file imports `toy.benchmark` for ONE reason, stated so it does not read as creep: finding 1's
    fix is in `RunProvenance.__post_init__`, in this module, but its CONSEQUENCE is in
    `benchmark.verdict_from_records`, which this owner may not edit. A pin on the stored TYPE would not be
    a pin on the consequence, and the brief for this round is explicit that the consequence is what must
    be pinned. `width_tol` 0.10 vs the module default 0.25 is the pair the honest refusal exists for."""
    if "recs" not in _STUDY:
        from toy import benchmark as bm
        fz = bm.freeze_seed_list(7, 30)
        res = bm.run_study(fz, bm.fixture_oracle_gated, subject="oracle_gated",
                           registered_digest=fz.digest, cfg=bm.BenchmarkConfig(n_boot=2000, width_tol=0.10))
        _STUDY["bm"] = bm
        _STUDY["recs"] = bm.to_experiment_records(res, study_id="f", base_seed=7,
                                                  timestamp_utc="2025-01-02T03:04:05Z")
    return _STUDY["bm"], _STUDY["recs"]


class AStoredHashIsNormalisedBeforeAnythingComparesIt(unittest.TestCase):
    """ROUND-6 FINDING 1, pinned by the verdict it buys.

    `RunProvenance.__post_init__` ran `_SHA256_RE.fullmatch(v)` on each `input_hashes` value -- which
    reads the real characters, so a 64-lowercase-hex `str` SUBCLASS passes it -- and then stored THE
    CALLER'S OBJECT. `benchmark.verdict_from_records` binds a recompute to the configuration the study
    ran under with `bound != want_hash` over `input_hashes["config"]`, so the value under audit decided
    whether it matched. MEASURED on a study run at `width_tol=0.10` recomputed with the module default
    0.25, through the public constructor, no `object.__setattr__`:
        honest -> JOINT_INCONCLUSIVE, h1/h2/h3 INCONCLUSIVE, one reason naming the mismatch
        forged -> JOINT_SUPPORTED,    h1/h2/h3 SUPPORTED,    reasons = (), config_hash "000000000000"
    STRICTLY STRONGER than the residual `verdict_from_records`' own docstring discloses, which says the
    attack needs the records rewritten AND a matching `cfg`: neither is needed, and the study's real hash
    need not be known. The three sibling guards in that function cannot help, because `stored` is a `set`
    built from the same object: "records disagree on the stored config hash" and `None in stored` are
    defeated by it too.
    THE FIX IS HERE, NOT THERE. `benchmark.py` belongs to another owner this round, and the defect is not
    in its comparison -- a recompute SHOULD compare the stored hash with `==` -- but in a schema that
    validated one object and stored another."""

    def forged(self, recs, value):
        out = []
        for r in recs:
            p = r.provenance
            ih = dict(p.input_hashes)
            ih["config"] = value
            out.append(dataclasses.replace(r, provenance=RunProvenance(
                run_id=p.run_id, timestamp_utc=p.timestamp_utc, seed=p.seed, code_version=p.code_version,
                python_version=p.python_version, toy_only=True, input_hashes=ih)))
        return out

    def test_a_lying_config_hash_cannot_bind_a_recompute_to_a_configuration_it_does_not_match(self):
        bm, recs = study_records()
        wrong_cfg = bm.BenchmarkConfig(n_boot=2000)              # default width_tol 0.25, not the study's
        honest = bm.verdict_from_records(recs, wrong_cfg)
        self.assertEqual(honest.joint, bm.JointVerdict.JOINT_INCONCLUSIVE)   # the control: it refuses
        self.assertEqual(len(honest.reasons), 1)
        self.assertIn("does not match the stored study configuration", honest.reasons[0])
        for forged in (LyingText("0" * 64), LyingText("a" * 64)):
            with self.subTest(forged=str.__str__(forged)[:4]):
                got = bm.verdict_from_records(self.forged(recs, forged), wrong_cfg)
                self.assertEqual(got.joint, bm.JointVerdict.JOINT_INCONCLUSIVE)
                for v in (got.h1, got.h2, got.h3):
                    self.assertEqual(v, bm.Verdict.INCONCLUSIVE)
                self.assertEqual(len(got.reasons), 1)
                self.assertIn("does not match the stored study configuration", got.reasons[0])
                self.assertIs(type(got.config_hash), str)
        # THE HONEST DIRECTION, and the sharpest statement of what the forgery bought. The study's OWN
        # cfg binds (`reasons == ()`) and recomputes H2 and H3 as INCONCLUSIVE: at `width_tol=0.10` the
        # two interval methods disagree on width. So the forged hash did not merely defeat a binding
        # check -- it produced JOINT_SUPPORTED with h1/h2/h3 all SUPPORTED, a verdict the configuration
        # the study actually ran under REFUSES, out of the same records.
        right = bm.verdict_from_records(recs, bm.BenchmarkConfig(n_boot=2000, width_tol=0.10))
        self.assertEqual(right.reasons, ())
        self.assertEqual((right.joint, right.h1, right.h2, right.h3),
                         (bm.JointVerdict.JOINT_INCONCLUSIVE, bm.Verdict.SUPPORTED,
                          bm.Verdict.INCONCLUSIVE, bm.Verdict.INCONCLUSIVE))

    def test_the_stored_hash_is_the_plain_text_and_the_record_is_byte_identical(self):
        p = prov(input_hashes={"config": LyingText("b" * 64)})
        self.assertIs(type(p.input_hashes["config"]), str)
        self.assertEqual(p.to_dict()["input_hashes"], {"config": "b" * 64})
        self.assertEqual(record(provenance=p).content_hash(),
                         record(provenance=prov(input_hashes={"config": "b" * 64})).content_hash())
        # the key side too, and the honest format gate is untouched
        q = prov(input_hashes={LyingText("config"): "b" * 64})
        self.assertEqual([type(k) for k in q.input_hashes], [str])
        for bad in ("A" * 64, "a" * 63, "g" * 64, "", 64 * "a" + "a"):
            with self.assertRaises(ValueError, msg=repr(bad)):
                prov(input_hashes={"config": bad})
        with self.assertRaises(ValueError):
            prov(input_hashes={"config": LyingText("NOT A HASH")})

    def test_two_input_hash_entries_cannot_collapse_into_one(self):
        """The second consequence of the same root, on the field `toy.robustness` calls "the provenance
        anchor a reader would check the seeds against" -- and `robustness.scorecard_to_record` writes
        exactly the two keys used here. Before the fix `dict(sorted(self.input_hashes.items()))` was
        built from the caller's key objects, so a key holding "scorecard" that HASHES as "seed_list"
        landed on the existing entry and the stored mapping held ONE: measured as
        `{'seed_list': 'bbb...'}`, n = 1, a record carrying one anchor where its producer wrote two.
        Normalising the keys first makes both survive with their real names, because the collapse was
        never about the characters. The loud refusal is kept for the case where it IS about the
        characters -- two keys that are the same text once plain -- inside the `ValueError` contract."""
        class Collapse(str):
            def __hash__(self):
                return hash("seed_list")

            def __eq__(self, other):
                return True

            def __ne__(self, other):
                return False
        m = TwoKeyMapping([("seed_list", "a" * 64), (Collapse("scorecard"), "b" * 64)])
        self.assertEqual(len(m), 2)                              # the caller really wrote two anchors
        p = prov(input_hashes=m)
        self.assertEqual(dict(p.input_hashes), {"seed_list": "a" * 64, "scorecard": "b" * 64})
        self.assertEqual([type(k) for k in p.input_hashes], [str, str])
        self.assertEqual(sorted(json.loads(record(provenance=p).to_json())["provenance"]["input_hashes"]),
                         ["scorecard", "seed_list"])
        # ... and a genuine duplicate, two keys that are one text once plain, is refused rather than
        # resolved silently to whichever happened to be iterated last
        dupe = TwoKeyMapping([("seed_list", "a" * 64), (Collapse("seed_list"), "b" * 64)])
        with self.assertRaisesRegex(ValueError, "collapse to 'seed_list'"):
            prov(input_hashes=dupe)
        # two honestly distinct keys are unaffected
        ok = prov(input_hashes=TwoKeyMapping([("seed_list", "a" * 64), ("scorecard", "b" * 64)]))
        self.assertEqual(dict(ok.input_hashes), {"seed_list": "a" * 64, "scorecard": "b" * 64})

    def test_a_metric_name_cannot_be_absent_from_the_content_hash(self):
        """The note of the same shape: metric NAMES were `_nonblank`-checked and never normalised, so a
        metric a recompute reads could be stored under a subclass key, and a second name could collapse
        into it -- absent from the canonical JSON and therefore from `content_hash()`."""
        r = record(metrics={LyingText("loss"): MetricValue.measured(0.25)})
        self.assertEqual([type(k) for k in r.metrics], [str])
        self.assertEqual(sorted(json.loads(r.to_json())["metrics"]), ["loss"])
        self.assertEqual(r.content_hash(), record(metrics={"loss": MetricValue.measured(0.25)}).content_hash())

        class Collapse(str):
            def __hash__(self):
                return hash("loss")

            def __eq__(self, other):
                return True

            def __ne__(self, other):
                return False
        mm = TwoKeyMapping([("loss", MetricValue.measured(1.0)),
                            (Collapse("recall"), MetricValue.measured(2.0))])
        r2 = record(metrics=mm)
        self.assertEqual(sorted(json.loads(r2.to_json())["metrics"]), ["loss", "recall"])
        self.assertEqual(r2.content_hash(),
                         record(metrics={"loss": MetricValue.measured(1.0),
                                         "recall": MetricValue.measured(2.0)}).content_hash())
        with self.assertRaisesRegex(ValueError, "collapse to 'loss'"):
            record(metrics=TwoKeyMapping([("loss", MetricValue.measured(1.0)),
                                          (Collapse("loss"), MetricValue.measured(2.0))]))


class AVersionAndLabelGateCompareThePlainText(unittest.TestCase):
    """ROUND-6 FINDING 3, pinned by what the accepted record SAYS.

    `ExperimentRecord.from_dict`'s two value gates were `data["schema_version"] != SCHEMA_VERSION` and
    `data["label"] != TOY_LABEL`, i.e. `__ne__` on the caller's object. MEASURED through `from_dict` on a
    hand-built dict, no `object.__setattr__`:
      * a VERSION-1 record was laundered into a valid version-2 one and RE-SERIALIZED with
        `schema_version="2"` and the canonical `TOY_LABEL` -- the version gate exists precisely because
        TOY_LABEL's text changed when SCHEMA_VERSION went 1 -> 2, so the one record the gate is for is
        the one it passed;
      * a record whose stored label read "VERIFIED SAFETY FINDING" was accepted and silently RELABELLED,
        which inverts the direction the label is for: the reader of the re-serialized record is told this
        kit vouched for text it never saw.
    HONEST BOUND, measured and unchanged by the fix: only `from_dict` with a hand-built dict reaches it.
    `from_json` is immune because the JSON decoder emits plain `str` -- which is exactly why this escaped
    five rounds: BOTH label-tampering tests at `test_label_tampering_rejected` /
    `test_label_near_misses_rejected` go through `from_json`, the one route that cannot show it.
    `_check_keys` normalises the dict's KEYS and its docstring calls that route "HARMLESS"; that
    measurement is about keys and never extended to these two values."""

    def test_a_lying_schema_version_cannot_be_laundered_into_the_current_one(self):
        d = record().to_dict()
        self.assertEqual(ExperimentRecord.from_dict(d).content_hash(), record().content_hash())  # control
        for bad in ("1", "0", "3", "2.0", ""):
            with self.subTest(bad=bad):
                with self.assertRaisesRegex(ValueError, "unsupported schema_version"):
                    ExperimentRecord.from_dict(dict(d, schema_version=LyingText(bad)))

    def test_a_lying_label_cannot_be_relabelled_as_a_toy_result(self):
        d = record().to_dict()
        for bad in ("VERIFIED SAFETY FINDING", "", "TOY RESULT", TOY_LABEL + " "):
            with self.subTest(bad=bad):
                with self.assertRaisesRegex(ValueError, "label must equal"):
                    ExperimentRecord.from_dict(dict(d, label=LyingText(bad)))
        # and the record that WOULD have been built is the one whose text is the giveaway: the forged
        # label never appears in anything the schema produces, because nothing is produced at all.
        self.assertNotIn("VERIFIED", record().to_json())

    def test_the_whole_document_is_normalised_not_just_these_two_gates(self):
        """The fix is `data = _plain_value(data)` at the boundary, not two more `_plain_text` calls, so a
        gate a future reader ADDS to this method is covered without being remembered. Asserted on the
        fields that are not gates at all: an honest record whose every string, number and key is a
        subclass instance deserialises BYTE-IDENTICALLY to the plain one."""
        d = record().to_dict()
        lied = _subclassed(d)
        self.assertNotEqual({type(k) for k in lied}, {str})      # the input really is subclassed
        got = ExperimentRecord.from_dict(lied)
        self.assertEqual(got.content_hash(), record().content_hash())
        self.assertEqual(_impure(got, "record"), [])
        # a non-dict input still gets the stated diagnostic rather than an AttributeError
        for bad in ([1, 2], "x", None, 7):
            with self.assertRaises(ValueError, msg=repr(bad)):
                ExperimentRecord.from_dict(bad)


# ----------------------------------------------- machine-derived field-coverage probe (shared shape)
def _subclassed(v):
    """Rebuild `v` with every plain `str` / `int` / `float` replaced by a SUBCLASS instance holding the
    same value, recursing through mapping keys AND values, sequences, and nested dataclasses.

    The subclasses do not lie about anything. That is deliberate: the property under test is that the
    object STORES the plain value, which is what makes every `==` / `!=` / `in` / `<` / `>` / `__float__`
    guard written anywhere downstream unfoolable. A probe built from one particular lie would pin one
    particular lie."""
    if v is None or isinstance(v, (Enum, bool)):
        return v
    if isinstance(v, str):
        return type("StrSub", (str,), {})(v)
    if isinstance(v, float):
        return type("FloatSub", (float,), {})(v)
    if isinstance(v, int):
        return type("IntSub", (int,), {})(v)
    if isinstance(v, Mapping):
        return {_subclassed(k): _subclassed(v[k]) for k in v}
    if isinstance(v, (list, tuple)):
        return (list if isinstance(v, list) else tuple)(_subclassed(x) for x in v)
    if dataclasses.is_dataclass(v) and not isinstance(v, type):
        return type(v)(**{f.name: _subclassed(getattr(v, f.name)) for f in dataclasses.fields(v)})
    return v


def _impure(v, path):
    """Every path inside `v` at which a `str` / `int` / `float` / container SUBCLASS instance is stored.

    An empty list is the assertion "nothing here can answer a comparison with anything but its own
    value". `Enum` members and `bool`s are skipped: `EvidenceClass` is a `str` subclass BY DESIGN and
    `bool` cannot be subclassed (see `toy.schema._plain_value`)."""
    out = []
    if v is None or isinstance(v, (Enum, bool)):
        return out
    if isinstance(v, (str, float, int)):
        if type(v) not in (str, float, int):
            out.append(f"{path} is a {type(v).__name__}")
        return out
    if isinstance(v, Mapping):
        if type(v) not in (dict, type(MappingProxyType({}))):
            out.append(f"{path} is a {type(v).__name__}")
        for k in v:
            out += _impure(k, f"{path}/key") + _impure(v[k], f"{path}[{k!r}]")
        return out
    if isinstance(v, (list, tuple)):
        if type(v) not in (list, tuple):
            out.append(f"{path} is a {type(v).__name__}")
        for i, x in enumerate(v):
            out += _impure(x, f"{path}[{i}]")
        return out
    if dataclasses.is_dataclass(v) and not isinstance(v, type):
        for f in dataclasses.fields(v):
            out += _impure(getattr(v, f.name), f"{path}.{f.name}")
    return out


def assert_fields_are_covered_or_exempt(case, module, fixtures, expected_counts):
    """The shared body of the two coverage tests (this module's and `test_robustness`'s twin).

    THE POINT, which is the whole round-6 fix: the field list is read from `dataclasses.fields()` and the
    class list from the MODULE, so a new field and a new dataclass FAIL CLOSED instead of being noticed
    by a reviewer. Three things are asserted per class:
      1. it is in the registry at all (a new dataclass fails);
      2. every `__post_init__` has `_normalise_fields(self)` as its FIRST statement -- the ordering rule
         ("normalise, THEN compare") is what the previous rounds' half-fixes kept getting wrong, and a
         call placed after a gate is as useless as no call;
      3. every field is either stored PLAIN when handed a subclass instance, or refused outright with a
         `ValueError` (also fail-closed), or named in the class's `_NORMALISE_EXEMPT` with a nonblank
         reason.
    What this does NOT cover, said plainly so it is not mistaken for more than it is: function
    PARAMETERS and closure variables are not fields. `toy.robustness.arm_difference`'s arm names,
    `shift_reorder_rows`'s `rel_tol`, `probe_precision`'s `tol` / `param` and `probe_shift`'s three
    callable returns are normalised where they are bound or consumed, each with its own consequence
    test."""
    found = {v for v in vars(module).values()
             if isinstance(v, type) and dataclasses.is_dataclass(v) and v.__module__ == module.__name__}
    case.assertEqual(sorted(c.__name__ for c in found), sorted(c.__name__ for c in fixtures),
                     f"a dataclass in {module.__name__} is not in this registry: add it, with a fixture, "
                     "and state for each of its fields whether it is normalised or exempt")
    tree = ast.parse(Path(module.__file__).read_text())
    posts = {f"{cls.name}.{fn.name}": fn for cls in ast.walk(tree) if isinstance(cls, ast.ClassDef)
             for fn in cls.body if isinstance(fn, ast.FunctionDef) and fn.name == "__post_init__"}
    n_fields = n_exempt = 0
    for cls, make in fixtures.items():
        key = f"{cls.__name__}.__post_init__"
        case.assertIn(key, posts, f"{cls.__name__} has no __post_init__, so nothing normalises it")
        first = posts[key].body[0]
        case.assertEqual(
            isinstance(first, ast.Expr) and isinstance(first.value, ast.Call)
            and getattr(first.value.func, "id", None) == "_normalise_fields", True,
            f"{key} must call _normalise_fields(self) as its FIRST statement, before any gate; "
            f"got {ast.dump(first)[:120]}")
        inst = make()
        exempt = dict(getattr(cls, "_NORMALISE_EXEMPT", {}))
        names = [f.name for f in dataclasses.fields(cls)]
        case.assertLessEqual(set(exempt), set(names), f"{cls.__name__}: _NORMALISE_EXEMPT names a "
                                                      "field that does not exist")
        for name in names:
            n_fields += 1
            if name in exempt:
                n_exempt += 1
                case.assertTrue(str(exempt[name]).strip(),
                                f"{cls.__name__}.{name} is exempt with no reason recorded")
                continue
            kwargs = {f.name: getattr(inst, f.name) for f in dataclasses.fields(cls)}
            kwargs[name] = _subclassed(kwargs[name])
            try:
                built = cls(**kwargs)
            except ValueError:
                continue                      # refused outright: also fail-closed
            case.assertEqual(_impure(getattr(built, name), f"{cls.__name__}.{name}"), [],
                             f"{cls.__name__}.{name} stored a subclass instance: either normalise it "
                             "(it should be covered by default) or exempt it with a reason")
    case.assertEqual((n_fields, n_exempt), expected_counts,
                     "the field/exemption counts moved. This is not a rubber stamp: confirm the new "
                     "field is covered (it is, by default) or exempt it with a reason, then update the "
                     "count -- a count that is remembered rather than measured is how five numbers got "
                     "into circulation for SEED_FLOOR.")


class EveryDataclassFieldIsNormalisedOrExplicitlyExempt(unittest.TestCase):
    """THE ROUND-6 FIX ITSELF, pinned. See `assert_fields_are_covered_or_exempt` for what it asserts.

    Why a boundary and not four more fixes: `_plain_summary_fields`, `_plain_text`, `_plain_measure`,
    `toy.benchmark._plain_number` and `_plain_parameter` are all CORRECT, and were applied at twelve
    hand-chosen call sites. Five consecutive review rounds each found the sites nobody remembered. That
    procedure cannot terminate, because its audit is a person hunting for omissions; this one terminates
    because the list of places is computed."""

    def test_schema_fields_are_covered_or_exempt_with_a_reason(self):
        from toy import schema
        assert_fields_are_covered_or_exempt(
            self, schema,
            {RunProvenance: prov, MetricValue: lambda: MetricValue.measured(0.25), ExperimentRecord: record},
            expected_counts=(14, 0))

    def test_the_normaliser_leaves_an_honest_record_byte_identical(self):
        """A normalisation that moved an honest byte would be a breaking change for every stored
        `content_hash`. The baseline is pinned by value in
        `AMetricStoresTheNumberItChecked.test_the_serialisation_contract_is_unchanged_for_honest_values`;
        here the assertion is that identity, not merely equality, survives for plain values."""
        for v in ("abc", 0.25, 7, True, None, (1, 2), ["a"], {"k": "v"}):
            self.assertIs(schema._plain_value(v), v, repr(v))
        self.assertEqual(SCHEMA_VERSION, "2")
        r = record()
        self.assertIs(r.name, "toy-exp")
        self.assertEqual(r.content_hash(), ExperimentRecord.from_json(r.to_json()).content_hash())

    def test_an_enum_member_is_not_collapsed_and_a_forged_one_is_refused(self):
        """The one TYPE-level skip in `_plain_value`, and the reason it launders nothing: `EvidenceClass`
        is a `str` subclass by construction, so collapsing it would destroy the `isinstance` checks the
        module relies on -- and a bare `str` subclass offered where an enum is required is refused."""
        r = record()
        self.assertIs(r.evidence_class, EvidenceClass.TOY_RESULT)
        self.assertIs(type(r.evidence_class), EvidenceClass)
        self.assertIs(schema._plain_value(EvidenceClass.TOY_RESULT), EvidenceClass.TOY_RESULT)
        with self.assertRaises(ValueError):
            record(evidence_class=LyingText("TOY_RESULT"))
        self.assertEqual(json.loads(r.to_json())["evidence_class"], "TOY_RESULT")


if __name__ == "__main__":
    unittest.main()
