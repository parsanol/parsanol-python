"""The declared per-target binding artifact (parsanol-ruby#432): the
Python loader replays the Ruby-emitted fixture byte-for-byte and
enforces the same verification matrix as the Ruby/rs loaders."""

import json
import os
import unittest

from parsanol import BINDING_TARGETS, BindingsArtifact, bindings_envelope

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "parg_binding_artifacts.json")


class BindingsArtifactTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(FIXTURE, encoding="utf-8") as handle:
            cls.fixture = json.load(handle)

    def test_ruby_emitted_artifacts_verify_and_replay(self):
        envelope = self.fixture["envelope"]
        artifact_envelope = json.loads(json.dumps(envelope))
        for target in BINDING_TARGETS:
            declared = BindingsArtifact(self.fixture["artifacts"][target], target)
            self.assertEqual(declared.target, target)
            self.assertEqual(
                declared.grammar_source_hash,
                envelope.get("source_hash"),
                f"{target}: source hash must pin the envelope",
            )
            for case in self.fixture["cases"]:
                bound = declared.apply(artifact_envelope, "identifier", case["shape"])
                self.assertEqual(bound, case["bound"], f"{target} {case['input']}")

    def test_python_emission_matches_the_ruby_reference(self):
        envelope = self.fixture["envelope"]
        for target in BINDING_TARGETS:
            emitted = bindings_envelope(envelope, target)
            self.assertEqual(
                emitted,
                self.fixture["artifacts"][target],
                f"python-emitted {target} artifact diverges from the Ruby reference",
            )

    def test_tampered_records_fail_the_checksum(self):
        payload = json.loads(json.dumps(self.fixture["artifacts"]["rs"]))
        entries = payload["entries"]
        for slot in entries.values():
            records = slot["bindings"]
            if records:
                records[0]["path"] = "smuggled"
                break
        with self.assertRaises(ValueError) as caught:
            BindingsArtifact(payload)
        self.assertIn("checksum mismatch", str(caught.exception))

    def test_target_pin_rejects_a_foreign_artifact(self):
        with self.assertRaises(ValueError) as caught:
            BindingsArtifact(self.fixture["artifacts"]["ts"], "rs")
        self.assertIn("targets 'ts', not 'rs'", str(caught.exception))

    def test_pairing_rejects_a_foreign_grammar_hash(self):
        from parsanol import checksum_hex

        payload = json.loads(json.dumps(self.fixture["artifacts"]["python"]))
        payload["grammar_source_hash"] = "0" * 64
        payload["checksum"] = checksum_hex(
            {k: v for k, v in payload.items() if k != "checksum"}
        )
        declared = BindingsArtifact(payload)
        envelope = json.loads(json.dumps(self.fixture["envelope"]))
        with self.assertRaises(ValueError) as caught:
            declared.apply(envelope, "identifier", self.fixture["cases"][0]["shape"])
        self.assertIn("source_hash", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
