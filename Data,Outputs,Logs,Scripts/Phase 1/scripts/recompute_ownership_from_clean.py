#!/usr/bin/env python3
"""Recompute ownership metrics strictly from the cleaned Round-1 dataset."""

from __future__ import annotations

import argparse
import csv
import datetime as dt
from pathlib import Path


REQUIRED_FIELDS = {
    "project_id",
    "window_id",
    "author_email",
    "author_name",
    "commits",
    "churn",
}

DEV_OUT_FIELDS = [
    "project_id",
    "window_id",
    "from_tag",
    "to_tag",
    "author_email",
    "author_name",
    "is_bot",
    "commits",
    "churn",
    "share_commits",
    "share_churn",
]

SUMMARY_OUT_FIELDS = [
    "project_id",
    "window_id",
    "from_tag",
    "to_tag",
    "total_commits",
    "total_churn",
    "unique_authors",
    "top1_share_commits",
    "top3_share_commits",
    "top1_share_churn",
    "top3_share_churn",
    "gini_commits",
    "gini_churn",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--in",
        dest="in_clean",
        default="out/metrics_window_dev_clean.csv",
        type=Path,
        help="Path to cleaned developer-window metrics CSV.",
    )
    parser.add_argument(
        "--outdir",
        default="out",
        type=Path,
        help="Directory where clean ownership outputs are written.",
    )
    parser.add_argument(
        "--windows",
        default="data/windows.csv",
        type=Path,
        help="Optional windows CSV for from_tag/to_tag lookup when missing in input.",
    )
    parser.add_argument(
        "--log",
        default="logs/ownership_recompute.log",
        type=Path,
        help="Path to recompute log file.",
    )
    parser.add_argument(
        "--tol",
        default=1e-6,
        type=float,
        help="Validation tolerance for share sums.",
    )
    return parser.parse_args()


def normalize(path: Path, base: Path) -> Path:
    return path if path.is_absolute() else base / path


def ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def to_int(value: str | int | None) -> int:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0


def to_bool(value: str | bool | None) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return value.strip().lower() in {"1", "true", "t", "yes", "y"}


def read_csv(path: Path) -> tuple[list[str], list[dict]]:
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        if not reader.fieldnames:
            raise ValueError(f"{path} is empty or missing a header")
        rows = [row for row in reader]
        return list(reader.fieldnames), rows


def write_csv(path: Path, fieldnames: list[str], rows: list[dict]) -> None:
    ensure_parent(path)
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def resolve_clean_input(path_arg: Path, base: Path) -> Path:
    candidates: list[Path] = []
    candidates.append(path_arg if path_arg.is_absolute() else base / path_arg)
    # Support "--in metrics_window_dev_clean.csv" as requested.
    if path_arg.name == path_arg.as_posix():
        candidates.append(base / "out" / path_arg.name)
    if path_arg.name != "metrics_window_dev_clean.csv":
        candidates.append(base / "out" / "metrics_window_dev_clean.csv")

    seen: set[Path] = set()
    for c in candidates:
        if c in seen:
            continue
        seen.add(c)
        if c.exists():
            return c
    raise FileNotFoundError(
        f"Clean input file not found. Checked: {', '.join(str(c) for c in candidates)}"
    )


def resolve_windows(path_arg: Path, base: Path) -> Path | None:
    candidates: list[Path] = []
    candidates.append(path_arg if path_arg.is_absolute() else base / path_arg)
    if path_arg.name == "windows.csv":
        candidates.extend(
            [
                base / "data" / "windows.csv",
                base / "out" / "windows.csv",
                base / "windows.csv",
            ]
        )

    seen: set[Path] = set()
    for c in candidates:
        if c in seen:
            continue
        seen.add(c)
        if c.exists():
            return c
    return None


def safe_div(num: int, den: int) -> float:
    if den == 0:
        return 0.0
    return num / den


def top_k_sum(values: list[float], k: int) -> float:
    if not values:
        return 0.0
    return sum(sorted(values, reverse=True)[:k])


def gini(values: list[int]) -> float:
    # Stable definition for non-negative values.
    n = len(values)
    if n <= 1:
        return 0.0
    sorted_vals = sorted(max(v, 0) for v in values)
    total = sum(sorted_vals)
    if total <= 0:
        return 0.0
    weighted_sum = 0
    for i, x in enumerate(sorted_vals, start=1):
        weighted_sum += i * x
    g = (2.0 * weighted_sum) / (n * total) - (n + 1) / n
    if g < 0:
        return 0.0
    if g > 1:
        return 1.0
    return g


def main() -> int:
    args = parse_args()
    base = Path.cwd()

    in_clean = resolve_clean_input(args.in_clean, base)
    outdir = normalize(args.outdir, base)
    out_dev = outdir / "ownership_dev_shares_clean.csv"
    out_summary = outdir / "ownership_summary_clean.csv"
    log_path = normalize(args.log, base)
    windows_path = resolve_windows(args.windows, base)

    in_fields, rows = read_csv(in_clean)
    missing = REQUIRED_FIELDS.difference(set(in_fields))
    if missing:
        missing_list = ", ".join(sorted(missing))
        raise ValueError(f"{in_clean} missing required columns: {missing_list}")

    # Optional tag lookup when from_tag/to_tag are absent or empty.
    windows_map: dict[tuple[str, str], tuple[str, str]] = {}
    if windows_path is not None:
        _, win_rows = read_csv(windows_path)
        for w in win_rows:
            key = ((w.get("project_id") or "").strip(), (w.get("window_id") or "").strip())
            windows_map[key] = (
                (w.get("from_tag") or "").strip(),
                (w.get("to_tag") or "").strip(),
            )

    has_from_tag = "from_tag" in in_fields
    has_to_tag = "to_tag" in in_fields
    has_is_bot = "is_bot" in in_fields

    grouped: dict[tuple[str, str], list[dict]] = {}
    for row in rows:
        project_id = (row.get("project_id") or "").strip()
        window_id = (row.get("window_id") or "").strip()
        author_email = (row.get("author_email") or "").strip().lower()
        row["project_id"] = project_id
        row["window_id"] = window_id
        row["author_email"] = author_email
        grouped.setdefault((project_id, window_id), []).append(row)

    dev_out_rows: list[dict] = []
    summary_rows: list[dict] = []

    windows_total_churn_zero = 0
    windows_total_commits_zero = 0
    bot_counts_per_project: dict[str, int] = {}
    no_bot_window_stats: list[dict] = []

    # Validation counters
    share_churn_bad = 0
    share_commits_bad = 0
    unique_authors_bad = 0

    for key in sorted(grouped):
        project_id, window_id = key
        group = grouped[key]

        from_tag = ""
        to_tag = ""
        if has_from_tag:
            from_tag = next(
                ((r.get("from_tag") or "").strip() for r in group if (r.get("from_tag") or "").strip()),
                "",
            )
        if has_to_tag:
            to_tag = next(
                ((r.get("to_tag") or "").strip() for r in group if (r.get("to_tag") or "").strip()),
                "",
            )
        if (not from_tag or not to_tag) and key in windows_map:
            wf, wt = windows_map[key]
            if not from_tag:
                from_tag = wf
            if not to_tag:
                to_tag = wt

        total_commits = sum(to_int(r.get("commits")) for r in group)
        total_churn = sum(to_int(r.get("churn")) for r in group)
        unique_authors = len({(r.get("author_email") or "").strip().lower() for r in group})

        if total_churn == 0:
            windows_total_churn_zero += 1
        if total_commits == 0:
            windows_total_commits_zero += 1

        commits_values: list[int] = []
        churn_values: list[int] = []
        share_commits_values: list[float] = []
        share_churn_values: list[float] = []

        # No-bot stats logged (minimal summary output mode).
        no_bot_commits = 0
        no_bot_churn = 0
        no_bot_emails: set[str] = set()
        no_bot_share_churn_values: list[float] = []

        for r in group:
            commits = to_int(r.get("commits"))
            churn = to_int(r.get("churn"))
            author_email = (r.get("author_email") or "").strip().lower()
            author_name = (r.get("author_name") or "").strip()
            is_bot = to_bool(r.get("is_bot")) if has_is_bot else False

            share_commits = safe_div(commits, total_commits)
            share_churn = safe_div(churn, total_churn)

            dev_out_rows.append(
                {
                    "project_id": project_id,
                    "window_id": window_id,
                    "from_tag": from_tag,
                    "to_tag": to_tag,
                    "author_email": author_email,
                    "author_name": author_name,
                    "is_bot": is_bot,
                    "commits": commits,
                    "churn": churn,
                    "share_commits": f"{share_commits:.6f}",
                    "share_churn": f"{share_churn:.6f}",
                }
            )

            commits_values.append(commits)
            churn_values.append(churn)
            share_commits_values.append(share_commits)
            share_churn_values.append(share_churn)

            if is_bot:
                bot_counts_per_project[project_id] = bot_counts_per_project.get(project_id, 0) + 1
            else:
                no_bot_commits += commits
                no_bot_churn += churn
                no_bot_emails.add(author_email)

        # Compute no-bot churn shares for logs.
        if no_bot_churn > 0:
            for r in group:
                if to_bool(r.get("is_bot")) if has_is_bot else False:
                    continue
                no_bot_share_churn_values.append(
                    to_int(r.get("churn")) / no_bot_churn
                )

        no_bot_window_stats.append(
            {
                "project_id": project_id,
                "window_id": window_id,
                "total_commits_no_bots": no_bot_commits,
                "total_churn_no_bots": no_bot_churn,
                "unique_authors_no_bots": len(no_bot_emails),
                "top1_share_churn_no_bots": (
                    max(no_bot_share_churn_values) if no_bot_share_churn_values else 0.0
                ),
                "top3_share_churn_no_bots": top_k_sum(no_bot_share_churn_values, 3),
            }
        )

        top1_share_commits = max(share_commits_values) if share_commits_values else 0.0
        top3_share_commits = top_k_sum(share_commits_values, 3)
        top1_share_churn = max(share_churn_values) if share_churn_values else 0.0
        top3_share_churn = top_k_sum(share_churn_values, 3)

        summary_rows.append(
            {
                "project_id": project_id,
                "window_id": window_id,
                "from_tag": from_tag,
                "to_tag": to_tag,
                "total_commits": total_commits,
                "total_churn": total_churn,
                "unique_authors": unique_authors,
                "top1_share_commits": f"{top1_share_commits:.6f}",
                "top3_share_commits": f"{top3_share_commits:.6f}",
                "top1_share_churn": f"{top1_share_churn:.6f}",
                "top3_share_churn": f"{top3_share_churn:.6f}",
                "gini_commits": f"{gini(commits_values):.6f}",
                "gini_churn": f"{gini(churn_values):.6f}",
            }
        )

        # Validation checks required by spec.
        sum_share_churn = sum(share_churn_values)
        sum_share_commits = sum(share_commits_values)
        expected_churn_sum = 0.0 if total_churn == 0 else 1.0
        expected_commits_sum = 0.0 if total_commits == 0 else 1.0

        if abs(sum_share_churn - expected_churn_sum) > args.tol:
            share_churn_bad += 1
        if abs(sum_share_commits - expected_commits_sum) > args.tol:
            share_commits_bad += 1
        if unique_authors != len({r["author_email"] for r in group}):
            unique_authors_bad += 1

    dev_out_rows.sort(
        key=lambda r: (
            r["project_id"],
            r["window_id"],
            -float(r["share_churn"]),
            r["author_email"],
        )
    )
    summary_rows.sort(key=lambda r: (r["project_id"], r["window_id"]))

    write_csv(out_dev, DEV_OUT_FIELDS, dev_out_rows)
    write_csv(out_summary, SUMMARY_OUT_FIELDS, summary_rows)

    unique_windows = len(grouped)
    summary_row_count_bad = 0 if len(summary_rows) == unique_windows else 1

    # Log outputs and validations.
    ensure_parent(log_path)
    now = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    lines: list[str] = [
        f"[{now}] input_file={in_clean}",
        f"[{now}] windows_file={windows_path if windows_path is not None else 'MISSING (used input tags only)'}",
        f"[{now}] input_row_count={len(rows)}",
        f"[{now}] output_dev_row_count={len(dev_out_rows)}",
        f"[{now}] output_summary_row_count={len(summary_rows)}",
        f"[{now}] unique_windows={unique_windows}",
        f"[{now}] windows_total_churn_zero={windows_total_churn_zero}",
        f"[{now}] windows_total_commits_zero={windows_total_commits_zero}",
        f"[{now}] validation_share_churn_bad_windows={share_churn_bad}",
        f"[{now}] validation_share_commits_bad_windows={share_commits_bad}",
        f"[{now}] validation_unique_authors_bad_windows={unique_authors_bad}",
        f"[{now}] validation_summary_rowcount_bad={summary_row_count_bad}",
    ]

    lines.append(f"[{now}] bot_counts_per_project_start")
    for project_id in sorted({r['project_id'] for r in rows}):
        bot_count = bot_counts_per_project.get(project_id, 0)
        lines.append(f"[{now}] bot_rows[{project_id}]={bot_count}")
    lines.append(f"[{now}] bot_counts_per_project_end")

    lines.append(f"[{now}] no_bot_window_stats_start")
    for rec in sorted(no_bot_window_stats, key=lambda x: (x["project_id"], x["window_id"])):
        lines.append(
            (
                f"[{now}] no_bots[{rec['project_id']}/{rec['window_id']}] "
                f"total_commits_no_bots={rec['total_commits_no_bots']} "
                f"total_churn_no_bots={rec['total_churn_no_bots']} "
                f"unique_authors_no_bots={rec['unique_authors_no_bots']} "
                f"top1_share_churn_no_bots={rec['top1_share_churn_no_bots']:.6f} "
                f"top3_share_churn_no_bots={rec['top3_share_churn_no_bots']:.6f}"
            )
        )
    lines.append(f"[{now}] no_bot_window_stats_end")

    log_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(f"Wrote {len(dev_out_rows)} rows to {out_dev}")
    print(f"Wrote {len(summary_rows)} rows to {out_summary}")
    print(f"Log written to {log_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
