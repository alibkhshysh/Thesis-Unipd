#!/usr/bin/env python3
"""Compute ownership/concentration metrics from developer window metrics."""

from __future__ import annotations

import argparse
import csv
from pathlib import Path


REQUIRED_FIELDS = {
    "project_id",
    "window_id",
    "author_email",
    "commits",
    "churn",
}

SUMMARY_FIELDS = [
    "project_id",
    "window_id",
    "from_tag",
    "to_tag",
    "total_churn",
    "total_commits",
    "unique_authors",
    "top1_share_churn",
    "top3_share_churn",
    "top1_share_commits",
    "top3_share_commits",
]

DEV_SHARE_FIELDS = [
    "project_id",
    "window_id",
    "author_email",
    "churn",
    "commits",
    "share_churn",
    "share_commits",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--in-dev", default="out/metrics_window_dev.csv", type=Path)
    parser.add_argument(
        "--out-summary", default="out/ownership_summary.csv", type=Path
    )
    parser.add_argument(
        "--out-dev-shares", default="out/ownership_dev_shares.csv", type=Path
    )
    return parser.parse_args()


def normalize(path: Path, base: Path) -> Path:
    return path if path.is_absolute() else base / path


def ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def read_csv_rows(path: Path) -> list[dict]:
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        if not reader.fieldnames:
            raise ValueError(f"{path} is empty or missing a header")

        missing = REQUIRED_FIELDS.difference(set(reader.fieldnames))
        if missing:
            missing_list = ", ".join(sorted(missing))
            raise ValueError(f"{path} missing required columns: {missing_list}")

        return [row for row in reader]


def to_int(value: str) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def write_csv(path: Path, fieldnames: list[str], rows: list[dict]) -> None:
    ensure_parent(path)
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def safe_share(num: int, den: int) -> float:
    if den <= 0:
        return 0.0
    return num / den


def main() -> int:
    args = parse_args()
    base = Path.cwd()
    in_dev = normalize(args.in_dev, base)
    out_summary = normalize(args.out_summary, base)
    out_dev_shares = normalize(args.out_dev_shares, base)

    rows = read_csv_rows(in_dev)
    # Stable order first by project/window then contributor.
    rows.sort(
        key=lambda r: (
            r.get("project_id", ""),
            r.get("window_id", ""),
            r.get("author_email", "").lower(),
        )
    )

    groups: dict[tuple[str, str], list[dict]] = {}
    for r in rows:
        key = (r["project_id"], r["window_id"])
        groups.setdefault(key, []).append(r)

    summary_rows: list[dict] = []
    dev_share_rows: list[dict] = []

    for key in sorted(groups):
        project_id, window_id = key
        group = groups[key]

        total_churn = sum(to_int(r.get("churn", "0")) for r in group)
        total_commits = sum(to_int(r.get("commits", "0")) for r in group)

        calc = []
        for r in group:
            churn = to_int(r.get("churn", "0"))
            commits = to_int(r.get("commits", "0"))
            share_churn = safe_share(churn, total_churn)
            share_commits = safe_share(commits, total_commits)

            calc.append(
                {
                    "project_id": project_id,
                    "window_id": window_id,
                    "author_email": r.get("author_email", "").strip().lower(),
                    "churn": churn,
                    "commits": commits,
                    "share_churn": f"{share_churn:.6f}",
                    "share_commits": f"{share_commits:.6f}",
                }
            )

        # Rank for concentration metrics.
        churn_rank = sorted(calc, key=lambda x: float(x["share_churn"]), reverse=True)
        commits_rank = sorted(
            calc, key=lambda x: float(x["share_commits"]), reverse=True
        )

        top1_share_churn = float(churn_rank[0]["share_churn"]) if churn_rank else 0.0
        top3_share_churn = sum(
            float(r["share_churn"]) for r in churn_rank[:3]
        ) if churn_rank else 0.0
        top1_share_commits = (
            float(commits_rank[0]["share_commits"]) if commits_rank else 0.0
        )
        top3_share_commits = sum(
            float(r["share_commits"]) for r in commits_rank[:3]
        ) if commits_rank else 0.0

        first = group[0]
        summary_rows.append(
            {
                "project_id": project_id,
                "window_id": window_id,
                "from_tag": first.get("from_tag", ""),
                "to_tag": first.get("to_tag", ""),
                "total_churn": total_churn,
                "total_commits": total_commits,
                "unique_authors": len(group),
                "top1_share_churn": f"{top1_share_churn:.6f}",
                "top3_share_churn": f"{top3_share_churn:.6f}",
                "top1_share_commits": f"{top1_share_commits:.6f}",
                "top3_share_commits": f"{top3_share_commits:.6f}",
            }
        )

        calc.sort(
            key=lambda x: (
                x["project_id"],
                x["window_id"],
                -float(x["share_churn"]),
                x["author_email"],
            )
        )
        dev_share_rows.extend(calc)

    write_csv(out_summary, SUMMARY_FIELDS, summary_rows)
    write_csv(out_dev_shares, DEV_SHARE_FIELDS, dev_share_rows)

    print(f"Wrote {len(summary_rows)} rows to {out_summary}")
    print(f"Wrote {len(dev_share_rows)} rows to {out_dev_shares}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
