#!/usr/bin/env python3
"""Validate internal consistency of the frozen M4 PoC design and schemas."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from pathlib import Path
from typing import Iterable


SCRIPT_DIR = Path(__file__).resolve().parent
PACKAGE_DIR = SCRIPT_DIR.parent
SPEC_DIR = PACKAGE_DIR / "spec"

SUMMARY_FIELDS = [
    "design_id",
    "design_version",
    "fabric_version",
    "chaincode_language",
    "metric_id",
    "policy_id",
    "policy_version",
    "analysis_policy_hash_sha256",
    "design_hash_sha256",
    "schemas_checked",
    "schema_reference_failures",
    "schema_required_property_failures",
    "cross_schema_constraint_failures",
    "policy_design_failures",
    "fixture_failures",
    "validation_status",
]

HASH_FIELDS = [
    "artifact",
    "canonical_sha256",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec-dir", type=Path, default=SPEC_DIR)
    parser.add_argument("--output-dir", type=Path, default=PACKAGE_DIR / "out")
    parser.add_argument(
        "--log-file",
        type=Path,
        default=PACKAGE_DIR / "logs" / "poc_design_validation.log",
    )
    return parser.parse_args()


def read_json(path: Path) -> dict:
    if not path.exists():
        raise FileNotFoundError(path)
    with path.open("r", encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise RuntimeError(f"Expected a JSON object: {path}")
    return value


def canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def canonical_hash(value: object) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def write_csv(path: Path, fields: list[str], rows: Iterable[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def collect_refs(value: object) -> list[str]:
    refs: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            if key == "$ref" and isinstance(item, str):
                refs.append(item)
            else:
                refs.extend(collect_refs(item))
    elif isinstance(value, list):
        for item in value:
            refs.extend(collect_refs(item))
    return refs


def validate_schema_structure(schema: dict) -> tuple[int, int]:
    reference_failures = 0
    required_failures = 0
    definitions = schema.get("$defs", {})
    for ref in collect_refs(schema):
        prefix = "#/$defs/"
        if not ref.startswith(prefix) or ref[len(prefix) :] not in definitions:
            reference_failures += 1

    def walk(value: object) -> None:
        nonlocal required_failures
        if isinstance(value, dict):
            required = value.get("required")
            properties = value.get("properties")
            if required is not None:
                if not isinstance(required, list) or not isinstance(properties, dict):
                    required_failures += 1
                else:
                    required_failures += len(set(required) - set(properties))
                    if len(required) != len(set(required)):
                        required_failures += 1
            for item in value.values():
                walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)

    walk(schema)
    return reference_failures, required_failures


def cross_schema_failures(submission: dict, record: dict, manifest: dict) -> int:
    failures = 0
    shared_submission_record = [
        "projectId",
        "windowId",
        "developerIdHash",
        "metricId",
        "metricVersion",
        "metricValuePpm",
        "numeratorChurn",
        "denominatorChurn",
        "fromCommitHash",
        "toCommitHash",
        "policyId",
        "policyVersion",
        "analysisPolicyHash",
        "evidenceManifestHash",
        "evidenceArtifactHash",
        "storageReference",
        "storagePersistence",
    ]
    submission_properties = submission["properties"]
    record_properties = record["properties"]
    for field in shared_submission_record:
        if submission_properties.get(field) != record_properties.get(field):
            failures += 1

    calculation = manifest["properties"]["calculation"]["properties"]
    if calculation["metricId"].get("const") != submission_properties["metricId"].get("const"):
        failures += 1
    if calculation["metricVersion"].get("const") != submission_properties["metricVersion"].get("const"):
        failures += 1
    if calculation["scale"].get("const") != 1_000_000:
        failures += 1
    if submission_properties["metricValuePpm"].get("maximum") != 1_000_000:
        failures += 1
    if submission_properties["numeratorChurn"].get("$ref") != "#/$defs/uintDecimal":
        failures += 1
    if submission_properties["denominatorChurn"].get("$ref") != "#/$defs/positiveUintDecimal":
        failures += 1
    return failures


def main() -> int:
    args = parse_args()
    spec_dir = args.spec_dir.resolve()
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    policy = read_json(spec_dir / "m4_metric_policy_v1.json")
    design = read_json(spec_dir / "poc_design_v1.json")
    fixture = read_json(spec_dir / "baseline_demo_case_v1.json")
    schema_paths = [
        spec_dir / "evidence_manifest_schema_v1.json",
        spec_dir / "ledger_submission_schema_v1.json",
        spec_dir / "ledger_record_schema_v1.json",
    ]
    schemas = {path.name: read_json(path) for path in schema_paths}
    manifest = schemas["evidence_manifest_schema_v1.json"]
    submission = schemas["ledger_submission_schema_v1.json"]
    record = schemas["ledger_record_schema_v1.json"]

    reference_failures = 0
    required_failures = 0
    for schema in schemas.values():
        ref_count, required_count = validate_schema_structure(schema)
        reference_failures += ref_count
        required_failures += required_count

    constraint_failures = cross_schema_failures(submission, record, manifest)

    current_policy_hash = canonical_hash(policy)
    policy_design_failures = 0
    if design["design_id"] != "M4_HYBRID_FABRIC_POC":
        policy_design_failures += 1
    if design["platform"]["fabric_version"] != "2.5.15":
        policy_design_failures += 1
    if design["chaincode"]["language"] != "javascript":
        policy_design_failures += 1
    if design["chaincode"]["fabric_contract_api_version"] != "2.5.8":
        policy_design_failures += 1
    if design["chaincode"]["fabric_shim_version"] != "2.5.8":
        policy_design_failures += 1
    if policy["metric"]["metric_id"] != submission["properties"]["metricId"]["const"]:
        policy_design_failures += 1
    if policy["policy_id"] != submission["properties"]["policyId"]["const"]:
        policy_design_failures += 1
    if policy["policy_version"] != submission["properties"]["policyVersion"]["const"]:
        policy_design_failures += 1
    if policy["calculation_policy"]["fixed_point_scale"] != 1_000_000:
        policy_design_failures += 1
    if design["platform"]["production_claim"] is not False:
        policy_design_failures += 1

    fixture_failures = 0
    if fixture["analysis_policy_hash_sha256"] != current_policy_hash:
        fixture_failures += 1
    if fixture["policy_id"] != policy["policy_id"]:
        fixture_failures += 1
    if fixture["policy_version"] != policy["policy_version"]:
        fixture_failures += 1
    selected = fixture["selected_developer"]
    numerator = selected["numerator_churn"]
    denominator = selected["denominator_churn"]
    expected_ppm = (numerator * 1_000_000 + denominator // 2) // denominator
    if expected_ppm != selected["metric_value_ppm"]:
        fixture_failures += 1
    if not fixture["ancestry_status"] == "ancestral":
        fixture_failures += 1

    status = (
        "pass"
        if not any(
            [
                reference_failures,
                required_failures,
                constraint_failures,
                policy_design_failures,
                fixture_failures,
            ]
        )
        else "fail"
    )

    summary = {
        "design_id": design["design_id"],
        "design_version": design["design_version"],
        "fabric_version": design["platform"]["fabric_version"],
        "chaincode_language": design["chaincode"]["language"],
        "metric_id": policy["metric"]["metric_id"],
        "policy_id": policy["policy_id"],
        "policy_version": policy["policy_version"],
        "analysis_policy_hash_sha256": current_policy_hash,
        "design_hash_sha256": canonical_hash(design),
        "schemas_checked": len(schemas),
        "schema_reference_failures": reference_failures,
        "schema_required_property_failures": required_failures,
        "cross_schema_constraint_failures": constraint_failures,
        "policy_design_failures": policy_design_failures,
        "fixture_failures": fixture_failures,
        "validation_status": status,
    }

    artifact_hashes = [
        {"artifact": "m4_metric_policy_v1.json", "canonical_sha256": current_policy_hash},
        {"artifact": "poc_design_v1.json", "canonical_sha256": canonical_hash(design)},
        *[
            {"artifact": name, "canonical_sha256": canonical_hash(schema)}
            for name, schema in sorted(schemas.items())
        ],
    ]

    write_csv(output_dir / "poc_design_validation_summary.csv", SUMMARY_FIELDS, [summary])
    write_csv(output_dir / "poc_design_artifact_hashes.csv", HASH_FIELDS, artifact_hashes)

    args.log_file.resolve().parent.mkdir(parents=True, exist_ok=True)
    args.log_file.resolve().write_text(
        "\n".join(
            [
                "M4 PoC design consistency validation",
                f"Design: {design['design_id']} {design['design_version']}",
                f"Fabric target: {design['platform']['fabric_version']}",
                f"Schemas checked: {len(schemas)}",
                f"Schema reference failures: {reference_failures}",
                f"Schema required-property failures: {required_failures}",
                f"Cross-schema constraint failures: {constraint_failures}",
                f"Policy/design failures: {policy_design_failures}",
                f"Fixture failures: {fixture_failures}",
                f"Validation status: {status}",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    print(
        f"Validated {len(schemas)} schemas for {design['design_id']} "
        f"against policy {policy['policy_version']}: {status}."
    )
    return 0 if status == "pass" else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc

