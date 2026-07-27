#!/usr/bin/env python3
"""Unit and generated-artifact tests for the M4 off-chain verifier."""

from __future__ import annotations

import copy
import importlib.util
import json
import re
import sys
import unittest
from pathlib import Path


sys.dont_write_bytecode = True
TEST_DIR = Path(__file__).resolve().parent
PACKAGE_DIR = TEST_DIR.parent
VERIFIER_PATH = PACKAGE_DIR / "scripts" / "m4_offchain_verifier.py"

SPEC = importlib.util.spec_from_file_location("m4_offchain_verifier_under_test", VERIFIER_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"Cannot load verifier: {VERIFIER_PATH}")
VERIFIER = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = VERIFIER
SPEC.loader.exec_module(VERIFIER)


class OffchainVerifierTests(unittest.TestCase):
    def setUp(self) -> None:
        self.evidence_dir = PACKAGE_DIR / "evidence" / "urllib3_W03"
        self.manifest = VERIFIER.read_json(self.evidence_dir / "evidence_manifest_v1.json")
        self.submission = VERIFIER.read_json(self.evidence_dir / "ledger_submission_v1.json")

    def test_canonical_json_is_sorted_compact_and_has_no_newline(self) -> None:
        encoded = VERIFIER.canonical_json_bytes({"z": 1, "a": {"y": 2, "b": 3}})
        self.assertEqual(encoded, b'{"a":{"b":3,"y":2},"z":1}')
        self.assertFalse(encoded.endswith(b"\n"))

    def test_synthetic_aggregation_applies_identity_bot_and_binary_policy(self) -> None:
        commits = [
            {
                "hash": "a" * 40,
                "email": " Human@Example.COM ",
                "name": "Alice",
                "date": "2026-01-01T00:00:00+00:00",
                "added": 4,
                "deleted": 2,
                "binary_file_changes": 1,
            },
            {
                "hash": "b" * 40,
                "email": "human@example.com",
                "name": "Alice",
                "date": "2026-01-02T00:00:00+00:00",
                "added": 1,
                "deleted": 3,
                "binary_file_changes": 0,
            },
            {
                "hash": "c" * 40,
                "email": "49699333+dependabot[bot]@users.noreply.github.com",
                "name": "dependabot[bot]",
                "date": "2026-01-03T00:00:00+00:00",
                "added": 9,
                "deleted": 9,
                "binary_file_changes": 0,
            },
        ]
        rows = VERIFIER.aggregate_developers(commits, re.compile(r"(\[bot\]|dependabot)", re.I))
        self.assertEqual(len(rows), 2)
        human = next(row for row in rows if not row["is_bot"])
        bot = next(row for row in rows if row["is_bot"])
        self.assertEqual(human["canonical_email"], "human@example.com")
        self.assertEqual((human["commits"], human["added"], human["deleted"], human["churn"]), (2, 5, 5, 10))
        self.assertEqual(human["binary_file_changes"], 1)
        self.assertEqual(bot["churn"], 18)

    def test_generated_instances_match_the_frozen_schemas(self) -> None:
        manifest_schema = VERIFIER.read_json(PACKAGE_DIR / "spec" / "evidence_manifest_schema_v1.json")
        submission_schema = VERIFIER.read_json(PACKAGE_DIR / "spec" / "ledger_submission_schema_v1.json")
        self.assertEqual(
            VERIFIER.validate_schema_instance(self.manifest, manifest_schema, manifest_schema), []
        )
        self.assertEqual(
            VERIFIER.validate_schema_instance(self.submission, submission_schema, submission_schema), []
        )

    def test_generated_hash_chain_and_integer_calculation(self) -> None:
        manifest_path = self.evidence_dir / "evidence_manifest_v1.json"
        bundle_path = PACKAGE_DIR / "artifacts" / "urllib3_W03.git.bundle"
        manifest_hash = VERIFIER.sha256_file(manifest_path)
        self.assertEqual(manifest_hash, self.submission["evidenceManifestHash"])
        self.assertEqual(VERIFIER.sha256_file(bundle_path), self.submission["evidenceArtifactHash"])
        self.assertEqual(
            VERIFIER.ppm_round_half_up(
                int(self.submission["numeratorChurn"]),
                int(self.submission["denominatorChurn"]),
            ),
            self.submission["metricValuePpm"],
        )
        self.assertEqual(VERIFIER.validate_cross_contracts(self.manifest, self.submission, manifest_hash), [])

    def test_additional_submission_field_is_rejected(self) -> None:
        schema = VERIFIER.read_json(PACKAGE_DIR / "spec" / "ledger_submission_schema_v1.json")
        mutated = dict(self.submission)
        mutated["unexpected"] = "not allowed"
        errors = VERIFIER.validate_schema_instance(mutated, schema, schema)
        self.assertTrue(any("additional property unexpected" in error for error in errors))

    def test_arithmetic_mutation_is_rejected(self) -> None:
        mutated_manifest = copy.deepcopy(self.manifest)
        mutated_submission = dict(self.submission)
        mutated_manifest["calculation"]["metricValuePpm"] += 1
        mutated_submission["metricValuePpm"] += 1
        mutated_hash = VERIFIER.sha256_bytes(VERIFIER.canonical_json_bytes(mutated_manifest))
        mutated_submission["evidenceManifestHash"] = mutated_hash
        errors = VERIFIER.validate_cross_contracts(mutated_manifest, mutated_submission, mutated_hash)
        self.assertIn("manifest ppm arithmetic mismatch", errors)

    def test_generated_summary_has_zero_failures(self) -> None:
        summary = VERIFIER.read_json(self.evidence_dir / "verification_summary_v1.json")
        self.assertEqual(summary["status"], "pass")
        self.assertEqual(summary["nonMergeCommits"], 16)
        self.assertEqual(summary["humanCommits"], 14)
        self.assertEqual(summary["excludedBotCommits"], 2)
        self.assertEqual(summary["binaryFileChanges"], 0)
        self.assertEqual(summary["schemaValidationFailures"], 0)
        self.assertEqual(summary["fixtureValidationFailures"], 0)
        self.assertEqual(summary["crossContractFailures"], 0)


if __name__ == "__main__":
    unittest.main()
