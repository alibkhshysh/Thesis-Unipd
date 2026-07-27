#!/usr/bin/env python3
"""Replay the frozen M4 evidence solely from its Git bundle and compare bytes."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from collections import Counter
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
PACKAGE_DIR = SCRIPT_DIR.parent
DEFAULT_BUNDLE = PACKAGE_DIR / "artifacts" / "urllib3_W03.git.bundle"
DEFAULT_EXPECTED = PACKAGE_DIR / "evidence" / "urllib3_W03"
DEFAULT_FIXTURE = PACKAGE_DIR / "spec" / "baseline_demo_case_v1.json"
DEFAULT_JOB = PACKAGE_DIR / "spec" / "baseline_evidence_job_v1.json"
DEFAULT_POLICY = PACKAGE_DIR / "spec" / "m4_metric_policy_v1.json"
DEFAULT_OUTPUT = PACKAGE_DIR / "out" / "urllib3_W03_replay_validation.csv"
DEFAULT_LOG = PACKAGE_DIR / "logs" / "urllib3_W03_replay_validation.log"
VERIFIER = SCRIPT_DIR / "m4_offchain_verifier.py"
COMPARE_FILES = [
    "evidence_manifest_v1.json",
    "ledger_submission_v1.json",
    "developer_evidence_v1.csv",
    "verification_summary_v1.json",
]
OUTPUT_FIELDS = [
    "fixture_id",
    "bundle_clone_status",
    "bundle_refs_match",
    "artifact_hash_matches_manifest",
    "manifest_hash_matches_submission",
    "integer_calculation_matches",
    "independent_extraction_matches",
    "independent_extraction_mismatches",
    "independent_non_merge_commits",
    "replayed_files_compared",
    "byte_identical_files",
    "byte_mismatch_files",
    "evidence_artifact_hash",
    "evidence_manifest_hash",
    "ledger_submission_hash",
    "validation_status",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, default=DEFAULT_BUNDLE)
    parser.add_argument("--expected-dir", type=Path, default=DEFAULT_EXPECTED)
    parser.add_argument("--fixture", type=Path, default=DEFAULT_FIXTURE)
    parser.add_argument("--job", type=Path, default=DEFAULT_JOB)
    parser.add_argument("--policy", type=Path, default=DEFAULT_POLICY)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--log-file", type=Path, default=DEFAULT_LOG)
    return parser.parse_args()


def read_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def run(command: list[str]) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment.update({"GIT_OPTIONAL_LOCKS": "0", "LC_ALL": "C", "LANG": "C"})
    result = subprocess.run(
        command,
        text=True,
        capture_output=True,
        encoding="utf-8",
        errors="strict",
        env=environment,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"Command failed ({result.returncode}): {' '.join(command)}\n{result.stderr.strip()}"
        )
    return result


def write_csv(path: Path, row: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=OUTPUT_FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerow(row)


def independent_extract(
    repo: Path, from_commit: str, to_commit: str, bot_regex: str, selected_email: str
) -> dict[str, int]:
    commits = (
        run(["git", "-C", str(repo), "rev-list", "--no-merges", f"{from_commit}..{to_commit}"])
        .stdout.strip()
        .splitlines()
    )
    by_email: dict[str, dict[str, object]] = {}
    binary_file_changes = 0
    for commit in commits:
        metadata = run(
            ["git", "-C", str(repo), "show", "-s", "--format=%ae%x00%an", commit]
        ).stdout.rstrip("\n")
        metadata_parts = metadata.split("\x00", 1)
        if len(metadata_parts) != 2:
            raise RuntimeError(f"Independent metadata parse failed for {commit}")
        email = metadata_parts[0].strip().lower()
        name = metadata_parts[1].strip()
        record = by_email.setdefault(
            email,
            {"names": Counter(), "commits": 0, "added": 0, "deleted": 0, "binary": 0},
        )
        record["names"][name] += 1
        record["commits"] += 1
        numstat = run(
            ["git", "-C", str(repo), "diff-tree", "--no-commit-id", "--numstat", "-r", f"{commit}^!"]
        ).stdout
        for line in numstat.splitlines():
            parts = line.split("\t", 2)
            if len(parts) != 3:
                raise RuntimeError(f"Independent numstat parse failed: {line!r}")
            added_raw, deleted_raw = parts[0].strip(), parts[1].strip()
            binary = added_raw == "-" or deleted_raw == "-"
            if not binary and (not added_raw.isdigit() or not deleted_raw.isdigit()):
                raise RuntimeError(f"Independent numstat count failed: {line!r}")
            record["added"] += int(added_raw) if added_raw.isdigit() else 0
            record["deleted"] += int(deleted_raw) if deleted_raw.isdigit() else 0
            record["binary"] += int(binary)
            binary_file_changes += int(binary)

    pattern = re.compile(bot_regex, re.IGNORECASE)
    humans: list[tuple[str, dict[str, object]]] = []
    bots: list[tuple[str, dict[str, object]]] = []
    for email, record in sorted(by_email.items()):
        names = record["names"]
        selected_name = sorted(names.items(), key=lambda item: (-item[1], item[0].lower(), item[0]))[0][0]
        target = bots if pattern.search(email) or pattern.search(selected_name) else humans
        target.append((email, record))

    human_added = sum(int(record["added"]) for _, record in humans)
    human_deleted = sum(int(record["deleted"]) for _, record in humans)
    bot_added = sum(int(record["added"]) for _, record in bots)
    bot_deleted = sum(int(record["deleted"]) for _, record in bots)
    selected_records = [record for email, record in humans if email == selected_email]
    if len(selected_records) != 1:
        raise RuntimeError("Independent extraction did not find the selected developer exactly once")
    selected_record = selected_records[0]
    denominator = human_added + human_deleted
    numerator = int(selected_record["added"]) + int(selected_record["deleted"])
    return {
        "nonMergeCommits": len(commits),
        "humanDevelopers": len(humans),
        "humanCommits": sum(int(record["commits"]) for _, record in humans),
        "humanAdded": human_added,
        "humanDeleted": human_deleted,
        "humanChurn": denominator,
        "excludedBotIdentities": len(bots),
        "excludedBotCommits": sum(int(record["commits"]) for _, record in bots),
        "excludedBotChurn": bot_added + bot_deleted,
        "binaryFileChanges": binary_file_changes,
        "numeratorChurn": numerator,
        "denominatorChurn": denominator,
        "metricValuePpm": (numerator * 1_000_000 + denominator // 2) // denominator,
    }


def main() -> int:
    args = parse_args()
    bundle = args.bundle.resolve()
    expected_dir = args.expected_dir.resolve()
    fixture = read_json(args.fixture.resolve())
    job = read_json(args.job.resolve())
    policy = read_json(args.policy.resolve())

    with tempfile.TemporaryDirectory(prefix="m4-evidence-replay-") as temp_name:
        temp_root = Path(temp_name)
        replay_repo = temp_root / "repo.git"
        replay_output = temp_root / "evidence"
        replay_log = temp_root / "verifier.log"
        run(["git", "init", "--bare", "--quiet", str(replay_repo)])
        fetch_specs = [f"{ref}:{ref}" for ref in job["artifact"]["includedRefs"]]
        run(["git", "-C", str(replay_repo), "fetch", "--quiet", str(bundle), *fetch_specs])
        run(
            [
                sys.executable,
                str(VERIFIER),
                "--repo",
                str(replay_repo),
                "--policy",
                str(args.policy.resolve()),
                "--fixture",
                str(args.fixture.resolve()),
                "--job",
                str(args.job.resolve()),
                "--artifact",
                str(bundle),
                "--output-dir",
                str(replay_output),
                "--log-file",
                str(replay_log),
            ]
        )

        expected_refs = set(job["artifact"]["includedRefs"])
        actual_refs = set(
            run(["git", "-C", str(replay_repo), "for-each-ref", "--format=%(refname)", "refs/tags/"])
            .stdout.strip()
            .splitlines()
        )
        bundle_refs_match = actual_refs == expected_refs

        mismatches: list[str] = []
        for name in COMPARE_FILES:
            expected = expected_dir / name
            replayed = replay_output / name
            if not expected.is_file() or expected.read_bytes() != replayed.read_bytes():
                mismatches.append(name)

        manifest_path = expected_dir / "evidence_manifest_v1.json"
        submission_path = expected_dir / "ledger_submission_v1.json"
        manifest = read_json(manifest_path)
        submission = read_json(submission_path)
        artifact_hash = sha256_file(bundle)
        manifest_hash = sha256_file(manifest_path)
        submission_hash = sha256_file(submission_path)
        artifact_hash_matches = artifact_hash == manifest["evidenceArtifact"]["sha256"]
        manifest_hash_matches = manifest_hash == submission["evidenceManifestHash"]
        numerator = int(submission["numeratorChurn"])
        denominator = int(submission["denominatorChurn"])
        expected_ppm = (numerator * 1_000_000 + denominator // 2) // denominator
        integer_matches = expected_ppm == submission["metricValuePpm"]
        independent = independent_extract(
            replay_repo,
            manifest["window"]["fromCommitHash"],
            manifest["window"]["toCommitHash"],
            policy["population_policy"]["bot_regex"],
            fixture["selected_developer"]["canonical_email_off_chain_only"],
        )
        independent_expected = {
            "nonMergeCommits": manifest["extraction"]["humanCommits"]
            + manifest["extraction"]["excludedBotCommits"],
            "humanDevelopers": manifest["extraction"]["humanDevelopers"],
            "humanCommits": manifest["extraction"]["humanCommits"],
            "humanAdded": manifest["extraction"]["humanAdded"],
            "humanDeleted": manifest["extraction"]["humanDeleted"],
            "humanChurn": manifest["extraction"]["humanChurn"],
            "excludedBotIdentities": manifest["extraction"]["excludedBotIdentities"],
            "excludedBotCommits": manifest["extraction"]["excludedBotCommits"],
            "excludedBotChurn": manifest["extraction"]["excludedBotChurn"],
            "binaryFileChanges": manifest["extraction"]["binaryFileChanges"],
            "numeratorChurn": manifest["calculation"]["numeratorChurn"],
            "denominatorChurn": manifest["calculation"]["denominatorChurn"],
            "metricValuePpm": manifest["calculation"]["metricValuePpm"],
        }
        independent_mismatches = [
            field for field in independent_expected if independent[field] != independent_expected[field]
        ]
        independent_matches = not independent_mismatches
        status = (
            "pass"
            if bundle_refs_match
            and not mismatches
            and artifact_hash_matches
            and manifest_hash_matches
            and integer_matches
            and independent_matches
            else "fail"
        )

    row = {
        "fixture_id": fixture["fixture_id"],
        "bundle_clone_status": "pass",
        "bundle_refs_match": str(bundle_refs_match).lower(),
        "artifact_hash_matches_manifest": str(artifact_hash_matches).lower(),
        "manifest_hash_matches_submission": str(manifest_hash_matches).lower(),
        "integer_calculation_matches": str(integer_matches).lower(),
        "independent_extraction_matches": str(independent_matches).lower(),
        "independent_extraction_mismatches": ";".join(independent_mismatches),
        "independent_non_merge_commits": independent["nonMergeCommits"],
        "replayed_files_compared": len(COMPARE_FILES),
        "byte_identical_files": len(COMPARE_FILES) - len(mismatches),
        "byte_mismatch_files": ";".join(mismatches),
        "evidence_artifact_hash": artifact_hash,
        "evidence_manifest_hash": manifest_hash,
        "ledger_submission_hash": submission_hash,
        "validation_status": status,
    }
    write_csv(args.output.resolve(), row)
    log_lines = [f"{key}={value}" for key, value in row.items()]
    args.log_file.resolve().parent.mkdir(parents=True, exist_ok=True)
    args.log_file.resolve().write_text(
        "\n".join(log_lines) + "\n", encoding="utf-8", newline="\n"
    )
    if status != "pass":
        raise RuntimeError(f"Evidence replay failed: {row}")
    print(f"Replayed {len(COMPARE_FILES)} evidence files from the Git bundle; all bytes match.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
