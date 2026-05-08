#!/usr/bin/env python3
"""Create duration-normalized Phase I metric outputs and short-window flags."""

from __future__ import annotations

import argparse
import csv
import datetime as dt
from pathlib import Path


TOTAL_OUT_FIELDS = [
    "project_id",
    "window_id",
    "from_tag",
    "to_tag",
    "duration_days",
    "is_short_lt_1d",
    "is_short_lt_7d",
    "is_short_lt_14d",
    "analysis_set",
    "total_commits",
    "total_added",
    "total_deleted",
    "total_churn",
    "unique_authors",
    "mean_endpoint_code_lines",
    "mean_endpoint_kloc",
    "commits_per_day",
    "added_per_day",
    "deleted_per_day",
    "churn_per_day",
    "churn_per_kloc_day",
]


DEV_OUT_FIELDS = [
    "project_id",
    "window_id",
    "from_tag",
    "to_tag",
    "duration_days",
    "is_short_lt_1d",
    "is_short_lt_7d",
    "is_short_lt_14d",
    "analysis_set",
    "author_email",
    "author_name",
    "is_bot",
    "commits",
    "added",
    "deleted",
    "churn",
    "active_days",
    "commits_per_day",
    "added_per_day",
    "deleted_per_day",
    "churn_per_day",
    "active_days_per_window_day",
]


WINDOW_OUT_FIELDS = [
    "project_id",
    "window_id",
    "from_tag",
    "to_tag",
    "duration_days",
    "is_short_lt_1d",
    "is_short_lt_7d",
    "is_short_lt_14d",
    "analysis_set",
]


SUMMARY_OUT_FIELDS = [
    "threshold",
    "window_count",
    "windows",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--windows", default="data/windows_all.csv", type=Path)
    parser.add_argument(
        "--totals-clean",
        default="out/metrics_window_totals_clean_all.csv",
        type=Path,
    )
    parser.add_argument(
        "--dev-clean",
        default="out/metrics_window_dev_clean_all.csv",
        type=Path,
    )
    parser.add_argument("--loc", default="out/loc_per_tag_all.csv", type=Path)
    parser.add_argument("--outdir", default="out", type=Path)
    parser.add_argument(
        "--log",
        default="logs/duration_normalization_all.log",
        type=Path,
    )
    parser.add_argument(
        "--output-suffix",
        default="_all",
        help="Suffix inserted before .csv for generated output files.",
    )
    parser.add_argument(
        "--analysis-scope",
        choices=("all", "human"),
        default="all",
        help="Controls centralized output names for all-account or human-only normalized files.",
    )
    return parser.parse_args()


def resolve(path: Path, base: Path) -> Path:
    return path if path.is_absolute() else base / path


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        if not reader.fieldnames:
            raise ValueError(f"{path} is empty or has no header")
        return [dict(row) for row in reader]


def write_csv(path: Path, fieldnames: list[str], rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def output_name(stem: str, suffix: str, analysis_scope: str) -> str:
    if analysis_scope == "human":
        if stem == "metrics_window_dev_normalized":
            return f"metrics_window_dev_human_normalized{suffix}.csv"
        if stem == "metrics_window_totals_normalized":
            return f"metrics_window_totals_human_normalized{suffix}.csv"
        if stem == "window_duration_flags":
            return f"window_duration_flags_human{suffix}.csv"
        if stem == "window_duration_sensitivity_summary":
            return f"window_duration_sensitivity_summary_human{suffix}.csv"
    return f"{stem}{suffix}.csv"


def to_float(value: str | int | float | None) -> float:
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0.0


def fmt(value: float) -> str:
    return f"{value:.6f}"


def parse_git_datetime(value: str) -> dt.datetime:
    normalized = value.strip().replace("Z", "+00:00")
    return dt.datetime.fromisoformat(normalized)


def build_window_rows(windows: list[dict[str, str]]) -> tuple[list[dict], dict[str, dict]]:
    rows: list[dict] = []
    by_id: dict[str, dict] = {}
    for row in windows:
        from_dt = parse_git_datetime(row["from_date"])
        to_dt = parse_git_datetime(row["to_date"])
        duration_days = (to_dt - from_dt).total_seconds() / 86400.0
        out = {
            "project_id": row["project_id"],
            "window_id": row["window_id"],
            "from_tag": row["from_tag"],
            "to_tag": row["to_tag"],
            "duration_days": fmt(duration_days),
            "is_short_lt_1d": str(duration_days < 1.0),
            "is_short_lt_7d": str(duration_days < 7.0),
            "is_short_lt_14d": str(duration_days < 14.0),
            "analysis_set": "sensitivity_only" if duration_days < 7.0 else "primary",
            "_duration_days_float": duration_days,
        }
        rows.append(out)
        by_id[row["window_id"]] = out
    return rows, by_id


def build_loc_map(loc_rows: list[dict[str, str]]) -> dict[tuple[str, str], float]:
    loc_map: dict[tuple[str, str], float] = {}
    for row in loc_rows:
        loc_map[(row["project_id"], row["tag_name"])] = to_float(row["code_lines"])
    return loc_map


def mean_endpoint_code_lines(
    loc_map: dict[tuple[str, str], float],
    project_id: str,
    from_tag: str,
    to_tag: str,
) -> float:
    values = [
        loc_map.get((project_id, from_tag), 0.0),
        loc_map.get((project_id, to_tag), 0.0),
    ]
    values = [value for value in values if value > 0.0]
    return sum(values) / len(values) if values else 0.0


def normalize_total_rows(
    totals: list[dict[str, str]],
    windows_by_id: dict[str, dict],
    loc_map: dict[tuple[str, str], float],
) -> list[dict]:
    out_rows: list[dict] = []
    for row in totals:
        window = windows_by_id[row["window_id"]]
        duration = window["_duration_days_float"]
        commits = to_float(row["total_commits"])
        added = to_float(row["total_added"])
        deleted = to_float(row["total_deleted"])
        churn = to_float(row["total_churn"])
        code_lines = mean_endpoint_code_lines(
            loc_map,
            row["project_id"],
            row["from_tag"],
            row["to_tag"],
        )
        kloc = code_lines / 1000.0
        out = {
            **{k: window[k] for k in WINDOW_OUT_FIELDS},
            "total_commits": row["total_commits"],
            "total_added": row["total_added"],
            "total_deleted": row["total_deleted"],
            "total_churn": row["total_churn"],
            "unique_authors": row["unique_authors"],
            "mean_endpoint_code_lines": fmt(code_lines),
            "mean_endpoint_kloc": fmt(kloc),
            "commits_per_day": fmt(commits / duration),
            "added_per_day": fmt(added / duration),
            "deleted_per_day": fmt(deleted / duration),
            "churn_per_day": fmt(churn / duration),
            "churn_per_kloc_day": fmt(churn / (duration * kloc)) if kloc else "",
        }
        out_rows.append(out)
    return out_rows


def normalize_dev_rows(dev_rows: list[dict[str, str]], windows_by_id: dict[str, dict]) -> list[dict]:
    out_rows: list[dict] = []
    for row in dev_rows:
        window = windows_by_id[row["window_id"]]
        duration = window["_duration_days_float"]
        commits = to_float(row["commits"])
        added = to_float(row["added"])
        deleted = to_float(row["deleted"])
        churn = to_float(row["churn"])
        active_days = to_float(row["active_days"])
        out = {
            **{k: window[k] for k in WINDOW_OUT_FIELDS},
            "author_email": row["author_email"],
            "author_name": row["author_name"],
            "is_bot": row.get("is_bot", "False"),
            "commits": row["commits"],
            "added": row["added"],
            "deleted": row["deleted"],
            "churn": row["churn"],
            "active_days": row["active_days"],
            "commits_per_day": fmt(commits / duration),
            "added_per_day": fmt(added / duration),
            "deleted_per_day": fmt(deleted / duration),
            "churn_per_day": fmt(churn / duration),
            "active_days_per_window_day": fmt(active_days / duration),
        }
        out_rows.append(out)
    return out_rows


def build_threshold_summary(window_rows: list[dict]) -> list[dict]:
    thresholds = [
        ("<1 day", "is_short_lt_1d"),
        ("<7 days", "is_short_lt_7d"),
        ("<14 days", "is_short_lt_14d"),
    ]
    rows: list[dict] = []
    for label, field in thresholds:
        matching = [row["window_id"] for row in window_rows if row[field] == "True"]
        rows.append(
            {
                "threshold": label,
                "window_count": len(matching),
                "windows": ";".join(matching),
            }
        )
    return rows


def strip_internal(rows: list[dict]) -> list[dict]:
    return [{k: v for k, v in row.items() if not k.startswith("_")} for row in rows]


def main() -> int:
    args = parse_args()
    base = Path.cwd()
    windows_path = resolve(args.windows, base)
    totals_path = resolve(args.totals_clean, base)
    dev_path = resolve(args.dev_clean, base)
    loc_path = resolve(args.loc, base)
    outdir = resolve(args.outdir, base)
    log_path = resolve(args.log, base)

    window_rows, windows_by_id = build_window_rows(read_csv(windows_path))
    loc_map = build_loc_map(read_csv(loc_path))
    totals_normalized = normalize_total_rows(read_csv(totals_path), windows_by_id, loc_map)
    dev_normalized = normalize_dev_rows(read_csv(dev_path), windows_by_id)
    summary_rows = build_threshold_summary(window_rows)

    window_out = outdir / output_name("window_duration_flags", args.output_suffix, args.analysis_scope)
    totals_out = outdir / output_name(
        "metrics_window_totals_normalized",
        args.output_suffix,
        args.analysis_scope,
    )
    dev_out = outdir / output_name(
        "metrics_window_dev_normalized",
        args.output_suffix,
        args.analysis_scope,
    )
    summary_out = outdir / output_name(
        "window_duration_sensitivity_summary",
        args.output_suffix,
        args.analysis_scope,
    )

    write_csv(window_out, WINDOW_OUT_FIELDS, strip_internal(window_rows))
    write_csv(
        totals_out,
        TOTAL_OUT_FIELDS,
        totals_normalized,
    )
    write_csv(
        dev_out,
        DEV_OUT_FIELDS,
        dev_normalized,
    )
    write_csv(
        summary_out,
        SUMMARY_OUT_FIELDS,
        summary_rows,
    )

    log_path.parent.mkdir(parents=True, exist_ok=True)
    now = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    with log_path.open("w", encoding="utf-8") as fh:
        fh.write(f"[{now}] windows={len(window_rows)}\n")
        fh.write(f"[{now}] totals_rows={len(totals_normalized)}\n")
        fh.write(f"[{now}] dev_rows={len(dev_normalized)}\n")
        for row in summary_rows:
            fh.write(
                f"[{now}] {row['threshold']} count={row['window_count']} windows={row['windows']}\n"
            )
        fh.write(f"[{now}] robust_primary_rule=exclude windows with duration_days < 7\n")

    print(f"Wrote {len(window_rows)} rows to {window_out}")
    print(f"Wrote {len(totals_normalized)} rows to {totals_out}")
    print(f"Wrote {len(dev_normalized)} rows to {dev_out}")
    print(f"Wrote {len(summary_rows)} rows to {summary_out}")
    print(f"Log written to {log_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
