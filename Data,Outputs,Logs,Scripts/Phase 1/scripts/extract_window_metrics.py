#!/usr/bin/env python3
"""Extract per-window developer metrics from Git history."""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import re
import subprocess
from pathlib import Path


WINDOW_REQUIRED_FIELDS = {
    "project_id",
    "window_id",
    "from_tag",
    "to_tag",
    "from_hash",
    "to_hash",
    "from_date",
    "to_date",
}

DEV_FIELDS = [
    "project_id",
    "window_id",
    "from_tag",
    "to_tag",
    "author_email",
    "author_name",
    "is_bot",
    "commits",
    "added",
    "deleted",
    "churn",
    "binary_file_count",
    "active_days",
    "first_commit",
    "last_commit",
]

TOTAL_FIELDS = [
    "project_id",
    "window_id",
    "from_tag",
    "to_tag",
    "total_commits",
    "total_added",
    "total_deleted",
    "total_churn",
    "unique_authors",
]

UNKNOWN_NAME_VALUES = {
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

BOT_PATTERN = re.compile(
    r"(\[bot\]|brewtestbot|dependabot|github-actions|pre-commit-ci|renovate|codecov|snyk|readthedocs)",
    re.IGNORECASE,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--windows", default="data/windows_all.csv", type=Path)
    parser.add_argument("--repos-dir", default="repos", type=Path)
    parser.add_argument("--out-dev", default="out/metrics_window_dev_all.csv", type=Path)
    parser.add_argument(
        "--out-totals", default="out/metrics_window_totals_all.csv", type=Path
    )
    parser.add_argument("--error-log", default="logs/errors_all_metrics.log", type=Path)
    return parser.parse_args()


def ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def append_error(log_path: Path, message: str) -> None:
    ensure_parent(log_path)
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    with log_path.open("a", encoding="utf-8") as fh:
        fh.write(f"[{stamp}] {message}\n")


def normalize_path(path: Path, base_dir: Path) -> Path:
    return path if path.is_absolute() else base_dir / path


def run_git_log(repo_dir: Path, from_hash: str, to_hash: str) -> subprocess.CompletedProcess:
    cmd = [
        "git",
        "-C",
        str(repo_dir),
        "log",
        "--no-merges",
        "--numstat",
        "--pretty=format:COMMIT|%H|%ae|%an|%cI",
        f"{from_hash}..{to_hash}",
    ]
    return subprocess.run(
        cmd,
        text=True,
        capture_output=True,
        check=False,
        encoding="utf-8",
        errors="replace",
    )


def parse_git_date(value: str) -> dt.datetime | None:
    value = value.strip()
    if not value:
        return None

    try:
        return dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        try:
            return dt.datetime.strptime(value, "%Y-%m-%d %H:%M:%S %z")
        except ValueError:
            return None


def is_unknown_name(name: str) -> bool:
    return name.strip().lower() in UNKNOWN_NAME_VALUES


def pick_author_name(name_counts: dict[str, int], author_email: str) -> str:
    if not name_counts:
        return "unknown"

    non_unknown = {k: v for k, v in name_counts.items() if not is_unknown_name(k)}
    pool = non_unknown if non_unknown else name_counts
    ordered = sorted(pool.items(), key=lambda x: (-x[1], x[0].lower(), x[0]))
    chosen = ordered[0][0].strip()
    if chosen:
        return chosen

    local_part = author_email.split("@", 1)[0].strip()
    return local_part if local_part else "unknown"


def is_bot_identity(author_email: str, author_name: str) -> bool:
    return bool(BOT_PATTERN.search(author_email) or BOT_PATTERN.search(author_name))


def parse_git_log_output(text: str) -> list[dict]:
    commits: list[dict] = []
    current: dict | None = None

    for raw_line in text.splitlines():
        line = raw_line.strip("\n")

        if line.startswith("COMMIT|"):
            if current is not None:
                commits.append(current)

            parts = line.split("|", 4)
            if len(parts) < 5:
                current = None
                continue

            commit_date = parse_git_date(parts[4])
            if commit_date is None:
                current = None
                continue

            current = {
                "hash": parts[1].strip(),
                "email": parts[2].strip().lower(),
                "name": parts[3].strip(),
                "date": commit_date,
                "added": 0,
                "deleted": 0,
                "binary_file_count": 0,
            }
            continue

        if current is None or not line:
            continue

        parts = line.split("\t", 2)
        if len(parts) < 3:
            continue

        added_raw = parts[0].strip()
        deleted_raw = parts[1].strip()

        binary_file = added_raw == "-" or deleted_raw == "-"
        added = int(added_raw) if added_raw.isdigit() else 0
        deleted = int(deleted_raw) if deleted_raw.isdigit() else 0

        current["added"] += added
        current["deleted"] += deleted
        if binary_file:
            current["binary_file_count"] += 1

    if current is not None:
        commits.append(current)

    return commits


def aggregate_by_developer(
    window: dict, commits: list[dict]
) -> tuple[list[dict], dict]:
    dev_map: dict[str, dict] = {}
    total_added = 0
    total_deleted = 0

    for commit in commits:
        email = commit["email"]
        if email not in dev_map:
            dev_map[email] = {
                "project_id": window["project_id"],
                "window_id": window["window_id"],
                "from_tag": window["from_tag"],
                "to_tag": window["to_tag"],
                "author_email": email,
                "commits": 0,
                "added": 0,
                "deleted": 0,
                "binary_file_count": 0,
                "active_days_set": set(),
                "first_commit_dt": None,
                "last_commit_dt": None,
                "name_counts": {},
            }

        rec = dev_map[email]
        rec["commits"] += 1
        rec["added"] += commit["added"]
        rec["deleted"] += commit["deleted"]
        rec["binary_file_count"] += commit["binary_file_count"]
        rec["active_days_set"].add(commit["date"].date().isoformat())
        name = commit["name"].strip()
        rec["name_counts"][name] = rec["name_counts"].get(name, 0) + 1

        first_dt = rec["first_commit_dt"]
        last_dt = rec["last_commit_dt"]
        if first_dt is None or commit["date"] < first_dt:
            rec["first_commit_dt"] = commit["date"]
        if last_dt is None or commit["date"] > last_dt:
            rec["last_commit_dt"] = commit["date"]

        total_added += commit["added"]
        total_deleted += commit["deleted"]

    dev_rows: list[dict] = []
    for rec in dev_map.values():
        first_dt = rec["first_commit_dt"]
        last_dt = rec["last_commit_dt"]
        author_name = pick_author_name(rec["name_counts"], rec["author_email"])
        rec_out = {
            "project_id": rec["project_id"],
            "window_id": rec["window_id"],
            "from_tag": rec["from_tag"],
            "to_tag": rec["to_tag"],
            "author_email": rec["author_email"],
            "author_name": author_name,
            "is_bot": is_bot_identity(rec["author_email"], author_name),
            "commits": rec["commits"],
            "added": rec["added"],
            "deleted": rec["deleted"],
            "churn": rec["added"] + rec["deleted"],
            "binary_file_count": rec["binary_file_count"],
            "active_days": len(rec["active_days_set"]),
            "first_commit": (
                first_dt.strftime("%Y-%m-%d %H:%M:%S %z") if first_dt else ""
            ),
            "last_commit": (
                last_dt.strftime("%Y-%m-%d %H:%M:%S %z") if last_dt else ""
            ),
        }
        dev_rows.append(rec_out)

    dev_rows.sort(key=lambda x: (x["project_id"], x["window_id"], x["author_email"]))

    totals = {
        "project_id": window["project_id"],
        "window_id": window["window_id"],
        "from_tag": window["from_tag"],
        "to_tag": window["to_tag"],
        "total_commits": len(commits),
        "total_added": total_added,
        "total_deleted": total_deleted,
        "total_churn": total_added + total_deleted,
        "unique_authors": len({row["author_email"] for row in dev_rows}),
    }

    return dev_rows, totals


def read_windows(path: Path) -> list[dict]:
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        if not reader.fieldnames:
            raise ValueError(f"{path} is empty or missing a header")

        missing = WINDOW_REQUIRED_FIELDS.difference(set(reader.fieldnames))
        if missing:
            missing_list = ", ".join(sorted(missing))
            raise ValueError(f"{path} is missing required columns: {missing_list}")

        return [row for row in reader]


def write_csv(path: Path, fieldnames: list[str], rows: list[dict]) -> None:
    ensure_parent(path)
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def main() -> int:
    args = parse_args()
    base_dir = Path.cwd()

    windows_path = normalize_path(args.windows, base_dir)
    repos_dir = normalize_path(args.repos_dir, base_dir)
    out_dev = normalize_path(args.out_dev, base_dir)
    out_totals = normalize_path(args.out_totals, base_dir)
    error_log = normalize_path(args.error_log, base_dir)

    ensure_parent(error_log)
    error_log.write_text("", encoding="utf-8")

    try:
        windows = read_windows(windows_path)
    except Exception as exc:  # noqa: BLE001
        append_error(error_log, f"Fatal: cannot read windows file: {exc}")
        print(f"Failed to read windows: {exc}")
        return 1

    dev_rows_all: list[dict] = []
    totals_rows_all: list[dict] = []

    for window in windows:
        project_id = window["project_id"].strip()
        window_id = window["window_id"].strip()
        from_hash = window["from_hash"].strip()
        to_hash = window["to_hash"].strip()
        repo_dir = repos_dir / project_id

        if not repo_dir.exists():
            append_error(
                error_log,
                f"{project_id}/{window_id}: repo path not found: {repo_dir}",
            )
            totals_rows_all.append(
                {
                    "project_id": project_id,
                    "window_id": window["window_id"],
                    "from_tag": window["from_tag"],
                    "to_tag": window["to_tag"],
                    "total_commits": 0,
                    "total_added": 0,
                    "total_deleted": 0,
                    "total_churn": 0,
                    "unique_authors": 0,
                }
            )
            continue

        proc = run_git_log(repo_dir, from_hash, to_hash)
        if proc.returncode != 0:
            stderr = (proc.stderr or "").strip().replace("\n", " | ")
            append_error(
                error_log,
                (
                    f"{project_id}/{window_id}: git log failed (exit={proc.returncode}) "
                    f"for range {from_hash}..{to_hash}; stderr={stderr}"
                ),
            )
            totals_rows_all.append(
                {
                    "project_id": project_id,
                    "window_id": window["window_id"],
                    "from_tag": window["from_tag"],
                    "to_tag": window["to_tag"],
                    "total_commits": 0,
                    "total_added": 0,
                    "total_deleted": 0,
                    "total_churn": 0,
                    "unique_authors": 0,
                }
            )
            continue

        commits = parse_git_log_output(proc.stdout or "")
        dev_rows, totals = aggregate_by_developer(window, commits)
        dev_rows_all.extend(dev_rows)
        totals_rows_all.append(totals)

    dev_rows_all.sort(
        key=lambda x: (
            x["project_id"],
            x["window_id"],
            -int(x["churn"]),
            x["author_email"],
        )
    )
    totals_rows_all.sort(key=lambda x: (x["project_id"], x["window_id"]))

    write_csv(out_dev, DEV_FIELDS, dev_rows_all)
    write_csv(out_totals, TOTAL_FIELDS, totals_rows_all)

    print(f"Wrote {len(dev_rows_all)} developer rows to {out_dev}")
    print(f"Wrote {len(totals_rows_all)} total rows to {out_totals}")
    print(f"Errors logged to {error_log}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
