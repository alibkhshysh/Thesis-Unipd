#!/usr/bin/env python3
"""Create and verify a deterministic standalone Git bundle for the PoC fixture."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import tempfile
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
PACKAGE_DIR = SCRIPT_DIR.parent
DEFAULT_FIXTURE = PACKAGE_DIR / "spec" / "baseline_demo_case_v1.json"
DEFAULT_JOB = PACKAGE_DIR / "spec" / "baseline_evidence_job_v1.json"
DEFAULT_REPO = PACKAGE_DIR.parent / "Phase 1" / "repos" / "urllib3"
DEFAULT_OUTPUT = PACKAGE_DIR / "artifacts" / "urllib3_W03.git.bundle"
DEFAULT_LOG = PACKAGE_DIR / "logs" / "git_evidence_bundle.log"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=DEFAULT_REPO)
    parser.add_argument("--fixture", type=Path, default=DEFAULT_FIXTURE)
    parser.add_argument("--job", type=Path, default=DEFAULT_JOB)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--log-file", type=Path, default=DEFAULT_LOG)
    parser.add_argument("--determinism-runs", type=int, default=2)
    return parser.parse_args()


def read_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise RuntimeError(f"Expected JSON object: {path}")
    return value


def git_environment() -> dict[str, str]:
    environment = os.environ.copy()
    environment.update(
        {
            "GIT_OPTIONAL_LOCKS": "0",
            "LC_ALL": "C",
            "LANG": "C",
        }
    )
    return environment


def run_git(repo: Path, arguments: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
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


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def bundle_prerequisites(path: Path) -> list[str]:
    prerequisites: list[str] = []
    with path.open("rb") as handle:
        first_line = handle.readline().decode("ascii").rstrip("\n")
        if first_line != "# v2 git bundle":
            raise RuntimeError(f"Unexpected Git bundle header: {first_line!r}")
        while True:
            line = handle.readline()
            if line in {b"", b"\n"}:
                break
            decoded = line.decode("utf-8").rstrip("\n")
            if decoded.startswith("-"):
                prerequisites.append(decoded)
    return prerequisites


def resolve_tag_commit(repo: Path, tag: str) -> str:
    return run_git(repo, ["rev-parse", "--verify", f"refs/tags/{tag}^{{commit}}"] ).stdout.strip()


def validate_inputs(repo: Path, fixture: dict, job: dict) -> list[str]:
    failures: list[str] = []
    if run_git(repo, ["rev-parse", "--is-inside-work-tree"]).stdout.strip() != "true":
        failures.append("source path is not a Git working tree")
    if fixture["project_id"] != job["projectId"]:
        failures.append("fixture/job project mismatch")
    if fixture["window_id"] != job["windowId"]:
        failures.append("fixture/job window mismatch")

    from_commit = resolve_tag_commit(repo, fixture["from_tag"])
    to_commit = resolve_tag_commit(repo, fixture["to_tag"])
    if from_commit != fixture["from_commit_hash"]:
        failures.append("from-tag commit does not match fixture")
    if to_commit != fixture["to_commit_hash"]:
        failures.append("to-tag commit does not match fixture")
    ancestry = run_git(
        repo,
        ["merge-base", "--is-ancestor", from_commit, to_commit],
        check=False,
    )
    if ancestry.returncode != 0:
        failures.append("fixture range is not ancestral")

    expected_refs = [f"refs/tags/{fixture['from_tag']}", f"refs/tags/{fixture['to_tag']}"]
    if job["artifact"]["includedRefs"] != expected_refs:
        failures.append("job includedRefs do not match fixture tags")
    if job["artifact"]["bundleVersion"] != 2:
        failures.append("baseline requires Git bundle version 2")
    return failures


def create_bundle(repo: Path, output: Path, refs: list[str], version: int) -> None:
    run_git(
        repo,
        [
            "-c",
            "pack.threads=1",
            "bundle",
            "create",
            f"--version={version}",
            str(output),
            *refs,
        ],
    )


def main() -> int:
    args = parse_args()
    if args.determinism_runs < 2:
        raise ValueError("--determinism-runs must be at least 2")

    repo = args.repo.resolve()
    fixture = read_json(args.fixture.resolve())
    job = read_json(args.job.resolve())
    failures = validate_inputs(repo, fixture, job)
    if failures:
        raise RuntimeError("Bundle input validation failed: " + "; ".join(failures))

    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    refs = list(job["artifact"]["includedRefs"])
    version = int(job["artifact"]["bundleVersion"])

    created: list[Path] = []
    hashes: list[str] = []
    try:
        for run_number in range(args.determinism_runs):
            handle = tempfile.NamedTemporaryFile(
                prefix=f".{output.name}.run{run_number + 1}.",
                suffix=".tmp",
                dir=output.parent,
                delete=False,
            )
            temp_path = Path(handle.name)
            handle.close()
            temp_path.unlink()
            created.append(temp_path)
            create_bundle(repo, temp_path, refs, version)
            run_git(repo, ["bundle", "verify", str(temp_path)])
            prerequisites = bundle_prerequisites(temp_path)
            if prerequisites:
                raise RuntimeError(
                    f"Bundle run {run_number + 1} is not standalone: {prerequisites}"
                )
            hashes.append(sha256_file(temp_path))

        if len(set(hashes)) != 1:
            raise RuntimeError(f"Bundle generation was not deterministic: {hashes}")
        os.replace(created[0], output)
        created = created[1:]
    finally:
        for temp_path in created:
            if temp_path.exists():
                temp_path.unlink()

    heads = run_git(repo, ["bundle", "list-heads", str(output)]).stdout.strip().splitlines()
    head_refs = {line.split(maxsplit=1)[1] for line in heads if len(line.split(maxsplit=1)) == 2}
    missing_refs = set(refs).difference(head_refs)
    if missing_refs:
        raise RuntimeError(f"Bundle is missing required refs: {sorted(missing_refs)}")

    artifact_hash = sha256_file(output)
    log_lines = [
        "status=pass",
        f"fixture_id={fixture['fixture_id']}",
        f"bundle_version={version}",
        f"included_refs={','.join(refs)}",
        "standalone_history=true",
        f"determinism_runs={args.determinism_runs}",
        "determinism_status=pass",
        f"artifact_bytes={output.stat().st_size}",
        f"artifact_sha256={artifact_hash}",
    ]
    args.log_file.resolve().parent.mkdir(parents=True, exist_ok=True)
    args.log_file.resolve().write_text(
        "\n".join(log_lines) + "\n", encoding="utf-8", newline="\n"
    )
    print(
        f"Created deterministic Git bundle ({output.stat().st_size} bytes); SHA-256 {artifact_hash}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
