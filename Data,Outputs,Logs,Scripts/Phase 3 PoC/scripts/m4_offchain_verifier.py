#!/usr/bin/env python3
"""Generate deterministic M4 evidence from a pinned Git range and artifact."""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
import re
import subprocess
from collections import Counter
from datetime import datetime
from decimal import Decimal, ROUND_HALF_EVEN, getcontext
from fractions import Fraction
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


getcontext().prec = 50

SCRIPT_DIR = Path(__file__).resolve().parent
PACKAGE_DIR = SCRIPT_DIR.parent
DEFAULT_REPO = PACKAGE_DIR.parent / "Phase 1" / "repos" / "urllib3"
DEFAULT_POLICY = PACKAGE_DIR / "spec" / "m4_metric_policy_v1.json"
DEFAULT_FIXTURE = PACKAGE_DIR / "spec" / "baseline_demo_case_v1.json"
DEFAULT_JOB = PACKAGE_DIR / "spec" / "baseline_evidence_job_v1.json"
DEFAULT_ARTIFACT = PACKAGE_DIR / "artifacts" / "urllib3_W03.git.bundle"
DEFAULT_OUTPUT_DIR = PACKAGE_DIR / "evidence" / "urllib3_W03"
DEFAULT_LOG = PACKAGE_DIR / "logs" / "m4_offchain_verifier.log"

SCALE = 1_000_000
DEVELOPER_HASH_DOMAIN = b"m4-developer-id-v1\x00"
UNKNOWN_NAMES = {
    "",
    "unknown",
    "unknown author",
    "n/a",
    "na",
    "none",
    "null",
    "(no author)",
    "no author",
}
AUDIT_FIELDS = [
    "canonical_email",
    "developer_id_hash",
    "selected_author_name",
    "is_bot",
    "commits",
    "added",
    "deleted",
    "churn",
    "binary_file_changes",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=DEFAULT_REPO)
    parser.add_argument("--policy", type=Path, default=DEFAULT_POLICY)
    parser.add_argument("--fixture", type=Path, default=DEFAULT_FIXTURE)
    parser.add_argument("--job", type=Path, default=DEFAULT_JOB)
    parser.add_argument("--artifact", type=Path, default=DEFAULT_ARTIFACT)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--log-file", type=Path, default=DEFAULT_LOG)
    return parser.parse_args()


def read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise RuntimeError(f"Expected JSON object: {path}")
    return value


def canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def developer_id_hash(canonical_email: str) -> str:
    return sha256_bytes(DEVELOPER_HASH_DOMAIN + canonical_email.encode("utf-8"))


def ppm_round_half_up(numerator: int, denominator: int) -> int:
    if denominator <= 0:
        raise ValueError("M4 denominator must be greater than zero")
    if numerator < 0 or numerator > denominator:
        raise ValueError("M4 numerator must satisfy 0 <= numerator <= denominator")
    return (numerator * SCALE + denominator // 2) // denominator


def decimal_12(value: Fraction) -> str:
    decimal_value = Decimal(value.numerator) / Decimal(value.denominator)
    return f"{decimal_value.quantize(Decimal('0.000000000001'), rounding=ROUND_HALF_EVEN):.12f}"


def gini_fraction(values: list[int]) -> Fraction:
    clean = sorted(value for value in values if value >= 0)
    count = len(clean)
    total = sum(clean)
    if count == 0 or total == 0:
        return Fraction(0, 1)
    weighted = sum((index + 1) * value for index, value in enumerate(clean))
    return Fraction(2 * weighted, count * total) - Fraction(count + 1, count)


def git_environment() -> dict[str, str]:
    environment = os.environ.copy()
    environment.update({"GIT_OPTIONAL_LOCKS": "0", "LC_ALL": "C", "LANG": "C"})
    return environment


def run_git(
    repo: Path, arguments: list[str], *, check: bool = True
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        ["git", "-c", "color.ui=false", "-C", str(repo), *arguments],
        text=True,
        capture_output=True,
        encoding="utf-8",
        errors="strict",
        env=git_environment(),
        check=False,
    )
    if check and result.returncode != 0:
        raise RuntimeError(
            f"Git command failed ({result.returncode}): {' '.join(arguments)}\n{result.stderr.strip()}"
        )
    return result


def resolve_tag_commit(repo: Path, tag: str) -> str:
    return run_git(repo, ["rev-parse", "--verify", f"refs/tags/{tag}^{{commit}}"] ).stdout.strip()


def tag_time(repo: Path, tag: str, commit_hash: str) -> datetime:
    value = run_git(
        repo,
        ["for-each-ref", "--format=%(taggerdate:iso-strict)", f"refs/tags/{tag}"],
    ).stdout.strip()
    if not value:
        value = run_git(repo, ["show", "-s", "--format=%cI", commit_hash]).stdout.strip()
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def parse_commit_date(value: str) -> datetime:
    return datetime.fromisoformat(value.strip().replace("Z", "+00:00"))


def extract_commits(repo: Path, from_commit: str, to_commit: str) -> list[dict[str, Any]]:
    revision = f"{from_commit}..{to_commit}"
    output = run_git(
        repo,
        [
            "log",
            "--no-merges",
            "--numstat",
            "--pretty=format:COMMIT|%H|%ae|%an|%cI",
            revision,
        ],
    ).stdout
    commits: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None

    for raw_line in output.splitlines():
        line = raw_line.strip("\n")
        if line.startswith("COMMIT|"):
            if current is not None:
                commits.append(current)
            parts = line.split("|", 4)
            if len(parts) != 5:
                raise RuntimeError(f"Malformed Git commit header: {line!r}")
            parse_commit_date(parts[4])
            current = {
                "hash": parts[1].strip(),
                "email": parts[2].strip().lower(),
                "name": parts[3].strip(),
                "date": parts[4].strip(),
                "added": 0,
                "deleted": 0,
                "binary_file_changes": 0,
            }
            continue
        if not line:
            continue
        if current is None:
            raise RuntimeError(f"Numstat row appeared before a commit header: {line!r}")
        parts = line.split("\t", 2)
        if len(parts) != 3:
            raise RuntimeError(f"Malformed Git numstat row: {line!r}")
        added_raw, deleted_raw = parts[0].strip(), parts[1].strip()
        binary = added_raw == "-" or deleted_raw == "-"
        if not binary and (not added_raw.isdigit() or not deleted_raw.isdigit()):
            raise RuntimeError(f"Non-numeric Git numstat counts: {line!r}")
        current["added"] += int(added_raw) if added_raw.isdigit() else 0
        current["deleted"] += int(deleted_raw) if deleted_raw.isdigit() else 0
        current["binary_file_changes"] += int(binary)

    if current is not None:
        commits.append(current)
    if len({commit["hash"] for commit in commits}) != len(commits):
        raise RuntimeError("Duplicate commits returned by Git log")
    return commits


def is_unknown_name(name: str) -> bool:
    return name.strip().lower() in UNKNOWN_NAMES


def select_author_name(name_counts: Counter[str], email: str) -> str:
    if not name_counts:
        return email.split("@", 1)[0] or "unknown"
    non_unknown = {name: count for name, count in name_counts.items() if not is_unknown_name(name)}
    pool = non_unknown if non_unknown else dict(name_counts)
    return sorted(pool.items(), key=lambda item: (-item[1], item[0].lower(), item[0]))[0][0].strip()


def aggregate_developers(
    commits: list[dict[str, Any]], bot_pattern: re.Pattern[str]
) -> list[dict[str, Any]]:
    aggregate: dict[str, dict[str, Any]] = {}
    for commit in commits:
        email = commit["email"].strip().lower()
        record = aggregate.setdefault(
            email,
            {
                "canonical_email": email,
                "name_counts": Counter(),
                "commits": 0,
                "added": 0,
                "deleted": 0,
                "binary_file_changes": 0,
            },
        )
        record["name_counts"][commit["name"].strip()] += 1
        record["commits"] += 1
        record["added"] += commit["added"]
        record["deleted"] += commit["deleted"]
        record["binary_file_changes"] += commit["binary_file_changes"]

    rows: list[dict[str, Any]] = []
    for email in sorted(aggregate):
        record = aggregate[email]
        selected_name = select_author_name(record["name_counts"], email)
        is_bot = bool(bot_pattern.search(email) or bot_pattern.search(selected_name))
        rows.append(
            {
                "canonical_email": email,
                "developer_id_hash": developer_id_hash(email),
                "selected_author_name": selected_name,
                "is_bot": is_bot,
                "commits": record["commits"],
                "added": record["added"],
                "deleted": record["deleted"],
                "churn": record["added"] + record["deleted"],
                "binary_file_changes": record["binary_file_changes"],
            }
        )
    return rows


def resolve_local_ref(schema: dict[str, Any], reference: str) -> Any:
    if not reference.startswith("#/"):
        raise RuntimeError(f"Only local schema references are supported: {reference}")
    value: Any = schema
    for component in reference[2:].split("/"):
        value = value[component.replace("~1", "/").replace("~0", "~")]
    return value


def type_matches(value: Any, expected: str) -> bool:
    if expected == "object":
        return isinstance(value, dict)
    if expected == "array":
        return isinstance(value, list)
    if expected == "string":
        return isinstance(value, str)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "null":
        return value is None
    raise RuntimeError(f"Unsupported schema type: {expected}")


def validate_schema_instance(
    value: Any,
    node: dict[str, Any],
    root_schema: dict[str, Any],
    path: str = "$",
) -> list[str]:
    if "$ref" in node:
        return validate_schema_instance(value, resolve_local_ref(root_schema, node["$ref"]), root_schema, path)
    errors: list[str] = []
    if "type" in node and not type_matches(value, node["type"]):
        return [f"{path}: expected {node['type']}"]
    if "const" in node and value != node["const"]:
        errors.append(f"{path}: expected constant {node['const']!r}")
    if "enum" in node and value not in node["enum"]:
        errors.append(f"{path}: value is not in enum")

    if isinstance(value, dict):
        required = set(node.get("required", []))
        errors.extend(f"{path}: missing required property {name}" for name in sorted(required - value.keys()))
        properties = node.get("properties", {})
        if node.get("additionalProperties") is False:
            errors.extend(
                f"{path}: additional property {name}"
                for name in sorted(value.keys() - properties.keys())
            )
        for name, child in properties.items():
            if name in value:
                errors.extend(validate_schema_instance(value[name], child, root_schema, f"{path}.{name}"))
    if isinstance(value, list) and "items" in node:
        for index, item in enumerate(value):
            errors.extend(validate_schema_instance(item, node["items"], root_schema, f"{path}[{index}]"))
    if isinstance(value, str):
        if len(value) < node.get("minLength", 0):
            errors.append(f"{path}: shorter than minLength")
        if "maxLength" in node and len(value) > node["maxLength"]:
            errors.append(f"{path}: longer than maxLength")
        if "pattern" in node and re.search(node["pattern"], value) is None:
            errors.append(f"{path}: does not match pattern")
        if node.get("format") == "uri":
            parsed = urlparse(value)
            if not parsed.scheme:
                errors.append(f"{path}: invalid URI")
        if node.get("format") == "date-time":
            try:
                datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError:
                errors.append(f"{path}: invalid date-time")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in node and value < node["minimum"]:
            errors.append(f"{path}: below minimum")
        if "maximum" in node and value > node["maximum"]:
            errors.append(f"{path}: above maximum")
    return errors


def csv_bytes(rows: list[dict[str, Any]]) -> bytes:
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=AUDIT_FIELDS, lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow({**row, "is_bot": str(row["is_bot"]).lower()})
    return stream.getvalue().encode("utf-8")


def write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(path.name + ".tmp")
    temp_path.write_bytes(data)
    os.replace(temp_path, path)


def fixture_failures(
    fixture: dict[str, Any],
    job: dict[str, Any],
    rows: list[dict[str, Any]],
    duration_seconds: int,
    policy_hash: str,
) -> list[str]:
    failures: list[str] = []
    humans = [row for row in rows if not row["is_bot"]]
    bots = [row for row in rows if row["is_bot"]]
    human_expected = fixture["human_population"]
    bot_expected = fixture["excluded_bot_context"]
    totals = {
        "developers": len(humans),
        "commits": sum(row["commits"] for row in humans),
        "added": sum(row["added"] for row in humans),
        "deleted": sum(row["deleted"] for row in humans),
        "churn": sum(row["churn"] for row in humans),
    }
    for field, actual in totals.items():
        if actual != human_expected[field]:
            failures.append(f"human {field}: expected {human_expected[field]}, got {actual}")
    bot_totals = {
        "identities": len(bots),
        "commits": sum(row["commits"] for row in bots),
        "churn": sum(row["churn"] for row in bots),
    }
    for field, actual in bot_totals.items():
        if actual != bot_expected[field]:
            failures.append(f"bot {field}: expected {bot_expected[field]}, got {actual}")
    if len(bots) == 1 and bots[0]["selected_author_name"] != bot_expected["label"]:
        failures.append("bot label does not match fixture")

    selected = fixture["selected_developer"]
    matching = [row for row in humans if row["canonical_email"] == selected["canonical_email_off_chain_only"]]
    if len(matching) != 1:
        failures.append("selected developer was not found exactly once")
    else:
        record = matching[0]
        denominator = totals["churn"]
        if record["developer_id_hash"] != selected["developer_id_hash"]:
            failures.append("selected developer hash mismatch")
        if record["churn"] != selected["numerator_churn"]:
            failures.append("selected numerator mismatch")
        if denominator != selected["denominator_churn"]:
            failures.append("selected denominator mismatch")
        if decimal_12(Fraction(record["churn"], denominator)) != selected["exact_share_12dp"]:
            failures.append("selected exact share mismatch")
        if ppm_round_half_up(record["churn"], denominator) != selected["metric_value_ppm"]:
            failures.append("selected ppm mismatch")

    churn_values = [row["churn"] for row in humans]
    support = fixture["supporting_window_values"]
    if decimal_12(Fraction(max(churn_values), sum(churn_values))) != support["top1_share_churn_12dp"]:
        failures.append("top-one share mismatch")
    if decimal_12(gini_fraction(churn_values)) != support["gini_churn_12dp"]:
        failures.append("Gini mismatch")
    ppm_sum = sum(ppm_round_half_up(value, sum(churn_values)) for value in churn_values)
    if ppm_sum != support["sum_individually_rounded_ppm"]:
        failures.append("sum of rounded ppm values mismatch")
    if ppm_sum - SCALE != support["ppm_sum_deviation_from_scale"]:
        failures.append("ppm sum deviation mismatch")
    if f"{Decimal(duration_seconds) / Decimal(86400):.6f}" != fixture["duration_days"]:
        failures.append("duration-days mismatch")
    if duration_seconds != job["expectedDurationSeconds"]:
        failures.append("duration-seconds mismatch")
    if policy_hash != fixture["analysis_policy_hash_sha256"]:
        failures.append("analysis policy hash mismatch")
    return failures


def validate_cross_contracts(
    manifest: dict[str, Any], submission: dict[str, Any], manifest_hash: str
) -> list[str]:
    failures: list[str] = []
    calculation = manifest["calculation"]
    extraction = manifest["extraction"]
    expected_ppm = ppm_round_half_up(calculation["numeratorChurn"], calculation["denominatorChurn"])
    if calculation["metricValuePpm"] != expected_ppm:
        failures.append("manifest ppm arithmetic mismatch")
    if extraction["humanAdded"] + extraction["humanDeleted"] != extraction["humanChurn"]:
        failures.append("manifest human churn sum mismatch")
    if extraction["humanChurn"] != calculation["denominatorChurn"]:
        failures.append("manifest extraction/calculation denominator mismatch")
    mappings = {
        "projectId": manifest["project"]["projectId"],
        "windowId": manifest["window"]["windowId"],
        "developerIdHash": manifest["subject"]["developerIdHash"],
        "metricId": calculation["metricId"],
        "metricVersion": calculation["metricVersion"],
        "metricValuePpm": calculation["metricValuePpm"],
        "numeratorChurn": str(calculation["numeratorChurn"]),
        "denominatorChurn": str(calculation["denominatorChurn"]),
        "fromCommitHash": manifest["window"]["fromCommitHash"],
        "toCommitHash": manifest["window"]["toCommitHash"],
        "policyId": manifest["policy"]["policyId"],
        "policyVersion": manifest["policy"]["policyVersion"],
        "analysisPolicyHash": manifest["policy"]["analysisPolicyHash"],
        "evidenceManifestHash": manifest_hash,
        "evidenceArtifactHash": manifest["evidenceArtifact"]["sha256"],
        "storageReference": manifest["evidenceArtifact"]["storageReference"],
        "storagePersistence": manifest["evidenceArtifact"]["storagePersistence"],
    }
    for field, expected in mappings.items():
        if submission.get(field) != expected:
            failures.append(f"submission field mismatch: {field}")
    return failures


def main() -> int:
    args = parse_args()
    repo = args.repo.resolve()
    artifact = args.artifact.resolve()
    policy = read_json(args.policy.resolve())
    fixture = read_json(args.fixture.resolve())
    job = read_json(args.job.resolve())

    if not artifact.is_file():
        raise FileNotFoundError(artifact)
    policy_hash = sha256_bytes(canonical_json_bytes(policy))
    if policy["policy_id"] != fixture["policy_id"] or policy["policy_version"] != fixture["policy_version"]:
        raise RuntimeError("Policy and fixture identifiers differ")

    from_commit = resolve_tag_commit(repo, fixture["from_tag"])
    to_commit = resolve_tag_commit(repo, fixture["to_tag"])
    if from_commit != fixture["from_commit_hash"] or to_commit != fixture["to_commit_hash"]:
        raise RuntimeError("Resolved tag commits differ from the frozen fixture")
    ancestry = run_git(repo, ["merge-base", "--is-ancestor", from_commit, to_commit], check=False)
    if ancestry.returncode != 0:
        raise RuntimeError("FROM_COMMIT is not an ancestor of TO_COMMIT")

    start_time = tag_time(repo, fixture["from_tag"], from_commit)
    end_time = tag_time(repo, fixture["to_tag"], to_commit)
    duration_seconds = int((end_time - start_time).total_seconds())
    if duration_seconds <= 0:
        raise RuntimeError("Release-window duration is not positive")

    bot_pattern = re.compile(policy["population_policy"]["bot_regex"], re.IGNORECASE)
    commits = extract_commits(repo, from_commit, to_commit)
    rows = aggregate_developers(commits, bot_pattern)
    failures = fixture_failures(fixture, job, rows, duration_seconds, policy_hash)
    if failures:
        raise RuntimeError("Fixture validation failed: " + "; ".join(failures))

    humans = [row for row in rows if not row["is_bot"]]
    bots = [row for row in rows if row["is_bot"]]
    selected_email = fixture["selected_developer"]["canonical_email_off_chain_only"]
    selected = next(row for row in humans if row["canonical_email"] == selected_email)
    denominator = sum(row["churn"] for row in humans)
    numerator = selected["churn"]
    artifact_hash = sha256_file(artifact)
    source_hash = sha256_file(Path(__file__).resolve())

    manifest = {
        "schemaId": "M4_EVIDENCE_MANIFEST",
        "schemaVersion": "1.0.0",
        "policy": {
            "policyId": policy["policy_id"],
            "policyVersion": policy["policy_version"],
            "analysisPolicyHash": policy_hash,
        },
        "project": {
            "projectId": fixture["project_id"],
            "repositoryUrl": job["repositoryUrl"],
        },
        "window": {
            "windowId": fixture["window_id"],
            "fromTag": fixture["from_tag"],
            "toTag": fixture["to_tag"],
            "fromCommitHash": from_commit,
            "toCommitHash": to_commit,
            "revisionExpression": f"{from_commit}..{to_commit}",
            "ancestryVerified": True,
            "analysisSet": fixture["analysis_set"],
            "durationSeconds": duration_seconds,
        },
        "subject": {"developerIdHash": selected["developer_id_hash"]},
        "extraction": {
            "vcs": "git",
            "mergeCommitsIncluded": False,
            "identitySource": "%ae",
            "humanDevelopers": len(humans),
            "humanCommits": sum(row["commits"] for row in humans),
            "humanAdded": sum(row["added"] for row in humans),
            "humanDeleted": sum(row["deleted"] for row in humans),
            "humanChurn": denominator,
            "excludedBotIdentities": len(bots),
            "excludedBotCommits": sum(row["commits"] for row in bots),
            "excludedBotChurn": sum(row["churn"] for row in bots),
            "binaryFileChanges": sum(row["binary_file_changes"] for row in rows),
        },
        "calculation": {
            "metricId": policy["metric"]["metric_id"],
            "metricVersion": policy["policy_version"],
            "numeratorChurn": numerator,
            "denominatorChurn": denominator,
            "scale": SCALE,
            "metricValuePpm": ppm_round_half_up(numerator, denominator),
        },
        "evidenceArtifact": {
            "mediaType": job["artifact"]["mediaType"],
            "sha256": artifact_hash,
            "storageReference": job["artifact"]["storageReference"],
            "storagePersistence": job["artifact"]["storagePersistence"],
        },
        "verifier": {
            "name": job["verifier"]["name"],
            "version": job["verifier"]["version"],
            "sourceSha256": source_hash,
        },
    }
    manifest_bytes = canonical_json_bytes(manifest)
    manifest_hash = sha256_bytes(manifest_bytes)
    submission = {
        "schemaId": "M4_LEDGER_SUBMISSION",
        "schemaVersion": "1.0.0",
        "projectId": fixture["project_id"],
        "windowId": fixture["window_id"],
        "developerIdHash": selected["developer_id_hash"],
        "metricId": policy["metric"]["metric_id"],
        "metricVersion": policy["policy_version"],
        "metricValuePpm": ppm_round_half_up(numerator, denominator),
        "numeratorChurn": str(numerator),
        "denominatorChurn": str(denominator),
        "fromCommitHash": from_commit,
        "toCommitHash": to_commit,
        "policyId": policy["policy_id"],
        "policyVersion": policy["policy_version"],
        "analysisPolicyHash": policy_hash,
        "evidenceManifestHash": manifest_hash,
        "evidenceArtifactHash": artifact_hash,
        "storageReference": job["artifact"]["storageReference"],
        "storagePersistence": job["artifact"]["storagePersistence"],
    }

    manifest_schema = read_json(PACKAGE_DIR / "spec" / "evidence_manifest_schema_v1.json")
    submission_schema = read_json(PACKAGE_DIR / "spec" / "ledger_submission_schema_v1.json")
    schema_errors = validate_schema_instance(manifest, manifest_schema, manifest_schema)
    schema_errors.extend(validate_schema_instance(submission, submission_schema, submission_schema))
    cross_errors = validate_cross_contracts(manifest, submission, manifest_hash)
    if schema_errors or cross_errors:
        raise RuntimeError("Generated contract validation failed: " + "; ".join(schema_errors + cross_errors))

    audit_data = csv_bytes(rows)
    submission_bytes = canonical_json_bytes(submission)
    summary = {
        "schemaId": "M4_OFFCHAIN_VERIFICATION_SUMMARY",
        "schemaVersion": "1.0.0",
        "fixtureId": fixture["fixture_id"],
        "status": "pass",
        "ancestryVerified": True,
        "nonMergeCommits": len(commits),
        "humanDevelopers": len(humans),
        "humanCommits": sum(row["commits"] for row in humans),
        "excludedBotIdentities": len(bots),
        "excludedBotCommits": sum(row["commits"] for row in bots),
        "binaryFileChanges": sum(row["binary_file_changes"] for row in rows),
        "numeratorChurn": numerator,
        "denominatorChurn": denominator,
        "metricValuePpm": ppm_round_half_up(numerator, denominator),
        "durationSeconds": duration_seconds,
        "artifactBytes": artifact.stat().st_size,
        "analysisPolicyHash": policy_hash,
        "verifierSourceHash": source_hash,
        "evidenceArtifactHash": artifact_hash,
        "evidenceManifestHash": manifest_hash,
        "ledgerSubmissionHash": sha256_bytes(submission_bytes),
        "developerAuditHash": sha256_bytes(audit_data),
        "schemaValidationFailures": 0,
        "fixtureValidationFailures": 0,
        "crossContractFailures": 0,
    }
    summary_bytes = canonical_json_bytes(summary)

    output_dir = args.output_dir.resolve()
    write_bytes(output_dir / "evidence_manifest_v1.json", manifest_bytes)
    write_bytes(output_dir / "ledger_submission_v1.json", submission_bytes)
    write_bytes(output_dir / "developer_evidence_v1.csv", audit_data)
    write_bytes(output_dir / "verification_summary_v1.json", summary_bytes)

    log_lines = [
        "status=pass",
        f"fixture_id={fixture['fixture_id']}",
        f"ancestry_verified=true",
        f"non_merge_commits={len(commits)}",
        f"human_developers={len(humans)}",
        f"human_commits={sum(row['commits'] for row in humans)}",
        f"human_added={sum(row['added'] for row in humans)}",
        f"human_deleted={sum(row['deleted'] for row in humans)}",
        f"human_churn={denominator}",
        f"excluded_bot_identities={len(bots)}",
        f"excluded_bot_commits={sum(row['commits'] for row in bots)}",
        f"excluded_bot_churn={sum(row['churn'] for row in bots)}",
        f"binary_file_changes={sum(row['binary_file_changes'] for row in rows)}",
        f"metric_value_ppm={summary['metricValuePpm']}",
        f"analysis_policy_hash={policy_hash}",
        f"verifier_source_hash={source_hash}",
        f"evidence_artifact_hash={artifact_hash}",
        f"evidence_manifest_hash={manifest_hash}",
        f"ledger_submission_hash={summary['ledgerSubmissionHash']}",
        "schema_validation_failures=0",
        "fixture_validation_failures=0",
        "cross_contract_failures=0",
    ]
    write_bytes(args.log_file.resolve(), ("\n".join(log_lines) + "\n").encode("utf-8"))
    print(
        f"Verified {len(commits)} commits and generated M4 evidence: {numerator}/{denominator} = {summary['metricValuePpm']} ppm"
    )
    print(f"Evidence manifest SHA-256: {manifest_hash}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
