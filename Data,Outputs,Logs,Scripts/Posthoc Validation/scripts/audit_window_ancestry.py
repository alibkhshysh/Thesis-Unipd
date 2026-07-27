#!/usr/bin/env python3
"""Audit whether each frozen release window follows a linear Git ancestry path.

This is an additive post-hoc validation. It reads the frozen Phase I inputs and
writes separate outputs under ``Posthoc Validation``. It never edits Phase I or
Phase II artifacts and it never checks out or otherwise changes a repository.
"""

from __future__ import annotations

import argparse
import csv
import subprocess
import sys
from collections import defaultdict
from pathlib import Path
from typing import Iterable


SCRIPT_DIR = Path(__file__).resolve().parent
PACKAGE_DIR = SCRIPT_DIR.parent
DEFAULT_PHASE1_DIR = PACKAGE_DIR.parent / "Phase 1"

AUDIT_FIELDS = [
    "project_id",
    "window_id",
    "from_tag",
    "to_tag",
    "from_hash",
    "to_hash",
    "from_date",
    "to_date",
    "ancestry_status",
    "include_in_ancestral_sensitivity",
    "from_only_commits",
    "to_only_commits",
    "human_commits",
    "human_churn",
    "interpretation",
]

PROJECT_SUMMARY_FIELDS = [
    "project_id",
    "total_windows",
    "ancestral_windows",
    "non_ancestral_windows",
    "human_commits_all_windows",
    "human_commits_non_ancestral_windows",
    "human_commits_non_ancestral_pct",
    "human_churn_all_windows",
    "human_churn_non_ancestral_windows",
    "human_churn_non_ancestral_pct",
]

IMPACT_SUMMARY_FIELDS = [
    "total_projects",
    "projects_with_non_ancestral_windows",
    "total_windows",
    "ancestral_windows",
    "non_ancestral_windows",
    "human_commits_all_windows",
    "human_commits_non_ancestral_windows",
    "human_commits_non_ancestral_pct",
    "human_churn_all_windows",
    "human_churn_non_ancestral_windows",
    "human_churn_non_ancestral_pct",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--phase1-dir",
        type=Path,
        default=DEFAULT_PHASE1_DIR,
        help="Frozen Phase I directory (default: %(default)s)",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=PACKAGE_DIR / "out",
        help="Separate audit output directory (default: %(default)s)",
    )
    parser.add_argument(
        "--log-file",
        type=Path,
        default=PACKAGE_DIR / "logs" / "window_ancestry_audit.log",
        help="Audit log path (default: %(default)s)",
    )
    return parser.parse_args()


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, fields: list[str], rows: Iterable[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def run_git(repo: Path, *args: str, allowed_codes: tuple[int, ...] = (0,)) -> subprocess.CompletedProcess[str]:
    command = ["git", "-C", str(repo), *args]
    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if result.returncode not in allowed_codes:
        detail = result.stderr.strip() or result.stdout.strip() or "no Git diagnostic"
        raise RuntimeError(f"Git command failed ({result.returncode}): {' '.join(command)}\n{detail}")
    return result


def validate_commit(repo: Path, commit_hash: str) -> None:
    run_git(repo, "cat-file", "-e", f"{commit_hash}^{{commit}}")


def ancestry_status(repo: Path, from_hash: str, to_hash: str) -> str:
    result = run_git(
        repo,
        "merge-base",
        "--is-ancestor",
        from_hash,
        to_hash,
        allowed_codes=(0, 1),
    )
    return "ancestral" if result.returncode == 0 else "non_ancestral"


def symmetric_difference_counts(repo: Path, from_hash: str, to_hash: str) -> tuple[int, int]:
    result = run_git(repo, "rev-list", "--left-right", "--count", f"{from_hash}...{to_hash}")
    values = result.stdout.strip().split()
    if len(values) != 2:
        raise RuntimeError(
            f"Unexpected rev-list count for {repo.name} {from_hash}...{to_hash}: {result.stdout!r}"
        )
    return int(values[0]), int(values[1])


def pct(part: int, whole: int) -> str:
    if whole == 0:
        return "0.000000"
    return f"{100.0 * part / whole:.6f}"


def build_audit_rows(
    phase1_dir: Path,
    windows: list[dict[str, str]],
    totals_by_key: dict[tuple[str, str], dict[str, str]],
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    expected_keys = {(row["project_id"], row["window_id"]) for row in windows}
    missing_totals = expected_keys - set(totals_by_key)
    if missing_totals:
        formatted = ", ".join(f"{project}/{window}" for project, window in sorted(missing_totals))
        raise RuntimeError(f"Missing human totals for frozen windows: {formatted}")

    for window in sorted(windows, key=lambda row: (row["project_id"], row["window_id"])):
        project_id = window["project_id"]
        window_id = window["window_id"]
        repo = phase1_dir / "repos" / project_id
        if not repo.is_dir():
            raise RuntimeError(f"Repository directory does not exist: {repo}")

        from_hash = window["from_hash"]
        to_hash = window["to_hash"]
        validate_commit(repo, from_hash)
        validate_commit(repo, to_hash)
        status = ancestry_status(repo, from_hash, to_hash)
        from_only, to_only = symmetric_difference_counts(repo, from_hash, to_hash)
        totals = totals_by_key[(project_id, window_id)]

        if status == "ancestral":
            interpretation = (
                "from commit is an ancestor of to commit; from..to is a linear Git release interval"
            )
            include = "true"
        else:
            interpretation = (
                "tags are on divergent history paths; from..to is not a sequential release interval"
            )
            include = "false"

        rows.append(
            {
                **{field: window[field] for field in (
                    "project_id",
                    "window_id",
                    "from_tag",
                    "to_tag",
                    "from_hash",
                    "to_hash",
                    "from_date",
                    "to_date",
                )},
                "ancestry_status": status,
                "include_in_ancestral_sensitivity": include,
                "from_only_commits": from_only,
                "to_only_commits": to_only,
                "human_commits": int(totals["total_commits"]),
                "human_churn": int(totals["total_churn"]),
                "interpretation": interpretation,
            }
        )
    return rows


def build_project_summaries(audit_rows: list[dict[str, object]]) -> list[dict[str, object]]:
    grouped: dict[str, list[dict[str, object]]] = defaultdict(list)
    for row in audit_rows:
        grouped[str(row["project_id"])].append(row)

    summaries: list[dict[str, object]] = []
    for project_id in sorted(grouped):
        rows = grouped[project_id]
        invalid = [row for row in rows if row["ancestry_status"] == "non_ancestral"]
        commits_all = sum(int(row["human_commits"]) for row in rows)
        commits_invalid = sum(int(row["human_commits"]) for row in invalid)
        churn_all = sum(int(row["human_churn"]) for row in rows)
        churn_invalid = sum(int(row["human_churn"]) for row in invalid)
        summaries.append(
            {
                "project_id": project_id,
                "total_windows": len(rows),
                "ancestral_windows": len(rows) - len(invalid),
                "non_ancestral_windows": len(invalid),
                "human_commits_all_windows": commits_all,
                "human_commits_non_ancestral_windows": commits_invalid,
                "human_commits_non_ancestral_pct": pct(commits_invalid, commits_all),
                "human_churn_all_windows": churn_all,
                "human_churn_non_ancestral_windows": churn_invalid,
                "human_churn_non_ancestral_pct": pct(churn_invalid, churn_all),
            }
        )
    return summaries


def build_impact_summary(
    audit_rows: list[dict[str, object]], project_summaries: list[dict[str, object]]
) -> dict[str, object]:
    invalid = [row for row in audit_rows if row["ancestry_status"] == "non_ancestral"]
    commits_all = sum(int(row["human_commits"]) for row in audit_rows)
    commits_invalid = sum(int(row["human_commits"]) for row in invalid)
    churn_all = sum(int(row["human_churn"]) for row in audit_rows)
    churn_invalid = sum(int(row["human_churn"]) for row in invalid)
    return {
        "total_projects": len(project_summaries),
        "projects_with_non_ancestral_windows": sum(
            int(row["non_ancestral_windows"]) > 0 for row in project_summaries
        ),
        "total_windows": len(audit_rows),
        "ancestral_windows": len(audit_rows) - len(invalid),
        "non_ancestral_windows": len(invalid),
        "human_commits_all_windows": commits_all,
        "human_commits_non_ancestral_windows": commits_invalid,
        "human_commits_non_ancestral_pct": pct(commits_invalid, commits_all),
        "human_churn_all_windows": churn_all,
        "human_churn_non_ancestral_windows": churn_invalid,
        "human_churn_non_ancestral_pct": pct(churn_invalid, churn_all),
    }


def write_log(
    path: Path,
    phase1_dir: Path,
    audit_rows: list[dict[str, object]],
    impact: dict[str, object],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    git_version = subprocess.run(
        ["git", "--version"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=True,
    ).stdout.strip()
    non_ancestral = [
        f"{row['project_id']}/{row['window_id']} ({row['from_tag']} -> {row['to_tag']})"
        for row in audit_rows
        if row["ancestry_status"] == "non_ancestral"
    ]
    lines = [
        "Post-hoc release-window ancestry audit",
        f"Git version: {git_version}",
        f"Phase I directory: {phase1_dir.resolve()}",
        f"Total windows: {impact['total_windows']}",
        f"Ancestral windows: {impact['ancestral_windows']}",
        f"Non-ancestral windows: {impact['non_ancestral_windows']}",
        f"Human commits in non-ancestral windows: {impact['human_commits_non_ancestral_windows']} "
        f"of {impact['human_commits_all_windows']} "
        f"({impact['human_commits_non_ancestral_pct']}%)",
        f"Human churn in non-ancestral windows: {impact['human_churn_non_ancestral_windows']} "
        f"of {impact['human_churn_all_windows']} "
        f"({impact['human_churn_non_ancestral_pct']}%)",
        "Non-ancestral windows:",
        *[f"- {value}" for value in non_ancestral],
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    args = parse_args()
    phase1_dir = args.phase1_dir.resolve()
    windows_path = phase1_dir / "data" / "windows_all.csv"
    totals_path = phase1_dir / "out" / "metrics_window_totals_human_all.csv"

    windows = read_csv(windows_path)
    totals = read_csv(totals_path)
    if len(windows) != 70:
        raise RuntimeError(f"Expected 70 frozen windows, found {len(windows)} in {windows_path}")
    totals_by_key = {(row["project_id"], row["window_id"]): row for row in totals}

    audit_rows = build_audit_rows(phase1_dir, windows, totals_by_key)
    project_summaries = build_project_summaries(audit_rows)
    impact = build_impact_summary(audit_rows, project_summaries)

    write_csv(args.output_dir / "window_ancestry_audit_all.csv", AUDIT_FIELDS, audit_rows)
    write_csv(
        args.output_dir / "window_ancestry_summary_by_project_all.csv",
        PROJECT_SUMMARY_FIELDS,
        project_summaries,
    )
    write_csv(
        args.output_dir / "window_ancestry_impact_summary_all.csv",
        IMPACT_SUMMARY_FIELDS,
        [impact],
    )
    write_log(args.log_file, phase1_dir, audit_rows, impact)

    print(
        f"Validated {impact['total_windows']} windows: "
        f"{impact['ancestral_windows']} ancestral, "
        f"{impact['non_ancestral_windows']} non-ancestral."
    )
    print(
        "Non-ancestral impact: "
        f"{impact['human_commits_non_ancestral_pct']}% of human commits, "
        f"{impact['human_churn_non_ancestral_pct']}% of human churn."
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc

