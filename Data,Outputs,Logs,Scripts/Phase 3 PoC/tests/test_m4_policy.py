#!/usr/bin/env python3
"""Deterministic arithmetic and frozen-fixture tests for M4 policy v1."""

from __future__ import annotations

import importlib.util
import json
import sys
import unittest
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path


sys.dont_write_bytecode = True
TEST_DIR = Path(__file__).resolve().parent
PACKAGE_DIR = TEST_DIR.parent
VALIDATOR_PATH = PACKAGE_DIR / "scripts" / "validate_m4_calculation.py"

SPEC = importlib.util.spec_from_file_location("m4_validator_under_test", VALIDATOR_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"Cannot load validator: {VALIDATOR_PATH}")
VALIDATOR = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = VALIDATOR
SPEC.loader.exec_module(VALIDATOR)


class M4PolicyTests(unittest.TestCase):
    def test_fixed_rounding_vectors(self) -> None:
        vectors = [
            (0, 1, 0),
            (1, 1, 1_000_000),
            (1, 2, 500_000),
            (1, 3, 333_333),
            (2, 3, 666_667),
            (1, 128, 7_813),
            (325, 1058, 307_183),
        ]
        for numerator, denominator, expected in vectors:
            with self.subTest(numerator=numerator, denominator=denominator):
                self.assertEqual(
                    VALIDATOR.ppm_round_half_up(numerator, denominator), expected
                )

    def test_integer_formula_matches_decimal_half_up(self) -> None:
        unit = Decimal("1")
        for denominator in range(1, 501):
            for numerator in range(denominator + 1):
                decimal_value = (
                    Decimal(numerator)
                    * Decimal(VALIDATOR.SCALE)
                    / Decimal(denominator)
                )
                expected = int(decimal_value.quantize(unit, rounding=ROUND_HALF_UP))
                actual = VALIDATOR.ppm_round_half_up(numerator, denominator)
                self.assertEqual(actual, expected)

    def test_invalid_inputs_are_rejected(self) -> None:
        for numerator, denominator in [(0, 0), (1, 0), (-1, 10), (11, 10)]:
            with self.subTest(numerator=numerator, denominator=denominator):
                with self.assertRaises(ValueError):
                    VALIDATOR.ppm_round_half_up(numerator, denominator)

    def test_developer_hash_fixture(self) -> None:
        self.assertEqual(
            VALIDATOR.developer_id_hash("illia.volochii@gmail.com"),
            "eaed488dac37a20eeadce46717abb4d78655633b3ffd07af79d532c4ce47185a",
        )

    def test_policy_hash_and_demo_fixture_agree(self) -> None:
        policy_path = PACKAGE_DIR / "spec" / "m4_metric_policy_v1.json"
        fixture_path = PACKAGE_DIR / "spec" / "baseline_demo_case_v1.json"
        with policy_path.open("r", encoding="utf-8") as handle:
            policy = json.load(handle)
        with fixture_path.open("r", encoding="utf-8") as handle:
            fixture = json.load(handle)
        self.assertEqual(
            VALIDATOR.policy_hash(policy), fixture["analysis_policy_hash_sha256"]
        )
        selected = fixture["selected_developer"]
        self.assertEqual(
            VALIDATOR.ppm_round_half_up(
                selected["numerator_churn"], selected["denominator_churn"]
            ),
            selected["metric_value_ppm"],
        )
        self.assertEqual(
            VALIDATOR.developer_id_hash(selected["canonical_email_off_chain_only"]),
            selected["developer_id_hash"],
        )

    def test_full_calculation_audit_passed(self) -> None:
        summary_path = PACKAGE_DIR / "out" / "m4_calculation_audit_summary_all.csv"
        rows = VALIDATOR.read_csv(summary_path)
        self.assertEqual(len(rows), 1)
        summary = rows[0]
        self.assertEqual(summary["validation_status"], "pass")
        self.assertEqual(summary["calculation_conclusion_supported"], "true")
        self.assertEqual(summary["developer_validation_failures"], "0")
        self.assertEqual(summary["window_validation_failures"], "0")
        self.assertEqual(summary["eligible_poc_windows"], "58")


if __name__ == "__main__":
    unittest.main()

