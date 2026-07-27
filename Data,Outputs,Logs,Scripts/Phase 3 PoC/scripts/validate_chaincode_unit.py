#!/usr/bin/env python3
"""Run deterministic local validation for the frozen m4evidence chaincode."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import shutil
import subprocess
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
PACKAGE_DIR = SCRIPT_DIR.parent
DEFAULT_CHAINCODE = PACKAGE_DIR / "chaincode" / "m4evidence"
DEFAULT_SUBMISSION = PACKAGE_DIR / "evidence" / "urllib3_W03" / "ledger_submission_v1.json"
DEFAULT_RECORD_SCHEMA = PACKAGE_DIR / "spec" / "ledger_record_schema_v1.json"
DEFAULT_OUTPUT = PACKAGE_DIR / "out" / "chaincode_unit_validation_summary.csv"
DEFAULT_LOG = PACKAGE_DIR / "logs" / "chaincode_unit_validation.log"
SOURCE_FILES = ["index.js", "lib/m4-evidence-contract.js"]
SUMMARY_FIELDS = [
    "validation_id",
    "chaincode_name",
    "chaincode_version",
    "node_version",
    "npm_version",
    "fabric_contract_api_version",
    "fabric_shim_version",
    "tests_total",
    "tests_passed",
    "tests_failed",
    "tests_skipped",
    "npm_audit_info",
    "npm_audit_low",
    "npm_audit_moderate",
    "npm_audit_high",
    "npm_audit_critical",
    "npm_audit_total",
    "package_files",
    "package_unpacked_bytes",
    "record_schema_required_fields",
    "chaincode_source_sha256",
    "package_lock_sha256",
    "ledger_submission_sha256",
    "expected_record_id",
    "validation_status",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--chaincode-dir", type=Path, default=DEFAULT_CHAINCODE)
    parser.add_argument("--submission", type=Path, default=DEFAULT_SUBMISSION)
    parser.add_argument("--record-schema", type=Path, default=DEFAULT_RECORD_SCHEMA)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--log-file", type=Path, default=DEFAULT_LOG)
    return parser.parse_args()


def run(command: list[str], cwd: Path, *, allow_nonzero: bool = False) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment["NO_COLOR"] = "1"
    result = subprocess.run(
        command,
        cwd=cwd,
        text=True,
        capture_output=True,
        encoding="utf-8",
        errors="strict",
        env=environment,
        check=False,
    )
    if result.returncode != 0 and not allow_nonzero:
        raise RuntimeError(
            f"Command failed ({result.returncode}): {' '.join(command)}\n"
            f"STDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
        )
    return result


def read_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise RuntimeError(f"Expected JSON object: {path}")
    return value


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def chaincode_source_hash(chaincode_dir: Path) -> str:
    digest = hashlib.sha256()
    digest.update(b"m4evidence-source-v1\x00")
    for relative in SOURCE_FILES:
        digest.update(relative.encode("utf-8"))
        digest.update(b"\x00")
        digest.update((chaincode_dir / relative).read_bytes())
        digest.update(b"\x00")
    return digest.hexdigest()


def domain_hash(domain: str, values: list[str]) -> str:
    payload = domain.encode("utf-8") + b"\x00" + b"\x00".join(
        value.encode("utf-8") for value in values
    )
    return hashlib.sha256(payload).hexdigest()


def parse_tap_summary(output: str) -> dict[str, int]:
    values: dict[str, int] = {}
    for key in ["tests", "pass", "fail", "skipped"]:
        matches = re.findall(rf"^# {key} (\d+)$", output, flags=re.MULTILINE)
        if len(matches) != 1:
            raise RuntimeError(f"Could not parse TAP {key} count")
        values[key] = int(matches[0])
    return values


def write_csv(path: Path, row: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=SUMMARY_FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerow(row)


def main() -> int:
    args = parse_args()
    chaincode_dir = args.chaincode_dir.resolve()
    node = shutil.which("node")
    npm = shutil.which("npm")
    if not node or not npm:
        raise RuntimeError("Node and npm are required")

    package = read_json(chaincode_dir / "package.json")
    package_lock = read_json(chaincode_dir / "package-lock.json")
    submission = read_json(args.submission.resolve())
    record_schema = read_json(args.record_schema.resolve())

    test_result = run(
        [node, "--test", "--test-reporter=tap", "test/m4-evidence-contract.test.js"],
        chaincode_dir,
    )
    tests = parse_tap_summary(test_result.stdout)
    dependency_result = run([npm, "ls", "--depth=0", "--json"], chaincode_dir)
    dependencies = json.loads(dependency_result.stdout)["dependencies"]
    audit_result = run([npm, "audit", "--omit=dev", "--json"], chaincode_dir, allow_nonzero=True)
    audit = json.loads(audit_result.stdout)
    vulnerability_counts = audit["metadata"]["vulnerabilities"]
    pack_result = run([npm, "pack", "--dry-run", "--json"], chaincode_dir)
    pack = json.loads(pack_result.stdout)[0]

    expected_dependency_versions = {
        "fabric-contract-api": package["dependencies"]["fabric-contract-api"],
        "fabric-shim": package["dependencies"]["fabric-shim"],
    }
    installed_versions = {
        name: dependencies[name]["version"] for name in expected_dependency_versions
    }
    dependency_versions_match = installed_versions == expected_dependency_versions
    lock_root = package_lock["packages"][""]
    lock_versions_match = lock_root["dependencies"] == expected_dependency_versions

    expected_record_id = domain_hash(
        "m4-record-id-v1",
        [
            submission["projectId"],
            submission["windowId"],
            submission["developerIdHash"],
            submission["metricId"],
            submission["policyVersion"],
        ],
    )
    test_status = tests["tests"] == tests["pass"] and tests["fail"] == 0
    audit_status = vulnerability_counts["total"] == 0 and audit_result.returncode == 0
    validation_status = (
        "pass"
        if test_status and audit_status and dependency_versions_match and lock_versions_match
        else "fail"
    )
    row = {
        "validation_id": "M4_CHAINCODE_UNIT_VALIDATION_V1",
        "chaincode_name": "m4evidence",
        "chaincode_version": package["version"],
        "node_version": run([node, "--version"], chaincode_dir).stdout.strip(),
        "npm_version": run([npm, "--version"], chaincode_dir).stdout.strip(),
        "fabric_contract_api_version": installed_versions["fabric-contract-api"],
        "fabric_shim_version": installed_versions["fabric-shim"],
        "tests_total": tests["tests"],
        "tests_passed": tests["pass"],
        "tests_failed": tests["fail"],
        "tests_skipped": tests["skipped"],
        "npm_audit_info": vulnerability_counts["info"],
        "npm_audit_low": vulnerability_counts["low"],
        "npm_audit_moderate": vulnerability_counts["moderate"],
        "npm_audit_high": vulnerability_counts["high"],
        "npm_audit_critical": vulnerability_counts["critical"],
        "npm_audit_total": vulnerability_counts["total"],
        "package_files": pack["entryCount"],
        "package_unpacked_bytes": pack["unpackedSize"],
        "record_schema_required_fields": len(record_schema["required"]),
        "chaincode_source_sha256": chaincode_source_hash(chaincode_dir),
        "package_lock_sha256": sha256_file(chaincode_dir / "package-lock.json"),
        "ledger_submission_sha256": sha256_file(args.submission.resolve()),
        "expected_record_id": expected_record_id,
        "validation_status": validation_status,
    }
    write_csv(args.output.resolve(), row)
    args.log_file.resolve().parent.mkdir(parents=True, exist_ok=True)
    args.log_file.resolve().write_text(
        "\n".join(f"{field}={row[field]}" for field in SUMMARY_FIELDS) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    if validation_status != "pass":
        raise RuntimeError(f"Chaincode unit validation failed: {row}")
    print(
        f"Validated m4evidence: {tests['pass']}/{tests['tests']} tests passed; "
        f"npm audit findings: {vulnerability_counts['total']}."
    )
    print(f"Expected record ID: {expected_record_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
