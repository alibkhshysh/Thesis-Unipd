#!/usr/bin/env python3
"""Export human-only metric tables and bot-sensitivity summaries."""

from __future__ import annotations

import argparse
import csv
import datetime as dt
from pathlib import Path


DEV_HUMAN_FIELDS = [
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

TOTAL_HUMAN_FIELDS = [
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

NORMALIZED_HUMAN_FIELDS = [
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

OWNERSHIP_DEV_FIELDS = [
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

OWNERSHIP_SUMMARY_FIELDS = [
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

BOT_PROJECT_FIELDS = [
    "project_id",
    "developer_rows_all",
    "developer_rows_human",
    "developer_rows_bot",
    "windows_with_bots",
    "windows_where_bot_top_committer",
    "total_commits_all",
    "total_commits_human",
    "total_commits_bot",
    "bot_commit_share",
    "total_churn_all",
    "total_churn_human",
    "total_churn_bot",
    "bot_churn_share",
    "bot_identities",
]

BOT_WINDOW_FIELDS = [
    "project_id",
    "window_id",
    "from_tag",
    "to_tag",
    "developer_rows_all",
    "developer_rows_human",
    "developer_rows_bot",
    "unique_authors_all",
    "unique_authors_human",
    "total_commits_all",
    "total_commits_human",
    "total_commits_bot",
    "bot_commit_share",
    "total_churn_all",
    "total_churn_human",
    "total_churn_bot",
    "bot_churn_share",
    "bot_has_max_commits",
    "bot_has_max_churn",
    "bot_identities",
]

BOT_IDENTITY_FIELDS = [
    "author_email",
    "author_name",
    "developer_window_rows",
    "project_count",
    "window_count",
    "total_commits",
    "total_churn",
    "projects",
    "windows",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dev-clean",
        default="out/metrics_window_dev_clean_all.csv",
        type=Path,
    )
    parser.add_argument(
        "--totals-clean",
        default="out/metrics_window_totals_clean_all.csv",
        type=Path,
    )
    parser.add_argument("--windows", default="data/windows_all.csv", type=Path)
    parser.add_argument("--loc", default="out/loc_per_tag_all.csv", type=Path)
    parser.add_argument("--outdir", default="out", type=Path)
    parser.add_argument("--log", default="logs/bot_sensitivity_all.log", type=Path)
    parser.add_argument(
        "--output-suffix",
        default="_all",
        help="Suffix inserted before .csv for generated output files.",
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


def output_name(stem: str, suffix: str) -> str:
    return f"{stem}{suffix}.csv"


def to_int(value: str | int | None) -> int:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0


def to_float(value: str | int | float | None) -> float:
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0.0


def to_bool(value: str | bool | None) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "y"}


def fmt(value: float) -> str:
    return f"{value:.6f}"


def safe_div(num: float, den: float) -> float:
    return num / den if den else 0.0


def parse_git_datetime(value: str) -> dt.datetime:
    normalized = value.strip().replace("Z", "+00:00")
    return dt.datetime.fromisoformat(normalized)


def gini(values: list[int]) -> float:
    clean = sorted(float(v) for v in values if v >= 0)
    n = len(clean)
    if n == 0:
        return 0.0
    total = sum(clean)
    if total == 0:
        return 0.0
    weighted = sum((idx + 1) * value for idx, value in enumerate(clean))
    return (2 * weighted) / (n * total) - (n + 1) / n


def top_k_sum(values: list[float], k: int) -> float:
    return sum(sorted(values, reverse=True)[:k])


def identity_label(row: dict[str, str]) -> str:
    name = (row.get("author_name") or "").strip()
    email = (row.get("author_email") or "").strip().lower()
    return name or email


def build_window_metadata(windows: list[dict[str, str]]) -> tuple[list[dict], dict[tuple[str, str], dict]]:
    ordered: list[dict] = []
    by_key: dict[tuple[str, str], dict] = {}
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
        key = (out["project_id"], out["window_id"])
        ordered.append(out)
        by_key[key] = out
    return ordered, by_key


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


def normalize_dev_rows(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    out_rows: list[dict[str, str]] = []
    for row in rows:
        out = {field: row.get(field, "") for field in DEV_HUMAN_FIELDS}
        out["is_bot"] = "False"
        out_rows.append(out)
    return out_rows


def build_totals_for_group(group: list[dict[str, str]], meta: dict) -> dict:
    return {
        "project_id": meta["project_id"],
        "window_id": meta["window_id"],
        "from_tag": meta["from_tag"],
        "to_tag": meta["to_tag"],
        "total_commits": sum(to_int(row.get("commits")) for row in group),
        "total_added": sum(to_int(row.get("added")) for row in group),
        "total_deleted": sum(to_int(row.get("deleted")) for row in group),
        "total_churn": sum(to_int(row.get("churn")) for row in group),
        "unique_authors": len({(row.get("author_email") or "").strip().lower() for row in group}),
    }


def normalize_total_row(
    totals: dict,
    meta: dict,
    loc_map: dict[tuple[str, str], float],
) -> dict:
    duration = meta["_duration_days_float"]
    commits = to_float(totals["total_commits"])
    added = to_float(totals["total_added"])
    deleted = to_float(totals["total_deleted"])
    churn = to_float(totals["total_churn"])
    code_lines = mean_endpoint_code_lines(
        loc_map,
        totals["project_id"],
        totals["from_tag"],
        totals["to_tag"],
    )
    kloc = code_lines / 1000.0
    return {
        "project_id": meta["project_id"],
        "window_id": meta["window_id"],
        "from_tag": meta["from_tag"],
        "to_tag": meta["to_tag"],
        "duration_days": meta["duration_days"],
        "is_short_lt_1d": meta["is_short_lt_1d"],
        "is_short_lt_7d": meta["is_short_lt_7d"],
        "is_short_lt_14d": meta["is_short_lt_14d"],
        "analysis_set": meta["analysis_set"],
        "total_commits": totals["total_commits"],
        "total_added": totals["total_added"],
        "total_deleted": totals["total_deleted"],
        "total_churn": totals["total_churn"],
        "unique_authors": totals["unique_authors"],
        "mean_endpoint_code_lines": fmt(code_lines),
        "mean_endpoint_kloc": fmt(kloc),
        "commits_per_day": fmt(safe_div(commits, duration)),
        "added_per_day": fmt(safe_div(added, duration)),
        "deleted_per_day": fmt(safe_div(deleted, duration)),
        "churn_per_day": fmt(safe_div(churn, duration)),
        "churn_per_kloc_day": fmt(safe_div(churn, duration * kloc)) if kloc else "",
    }


def build_ownership(group: list[dict[str, str]], totals: dict, meta: dict) -> tuple[list[dict], dict]:
    total_commits = to_float(totals["total_commits"])
    total_churn = to_float(totals["total_churn"])
    dev_rows: list[dict] = []
    commit_values: list[int] = []
    churn_values: list[int] = []
    share_commits_values: list[float] = []
    share_churn_values: list[float] = []

    for row in sorted(group, key=lambda r: ((r.get("author_email") or "").strip().lower())):
        commits = to_int(row.get("commits"))
        churn = to_int(row.get("churn"))
        share_commits = safe_div(commits, total_commits)
        share_churn = safe_div(churn, total_churn)
        commit_values.append(commits)
        churn_values.append(churn)
        share_commits_values.append(share_commits)
        share_churn_values.append(share_churn)
        dev_rows.append(
            {
                "project_id": meta["project_id"],
                "window_id": meta["window_id"],
                "from_tag": meta["from_tag"],
                "to_tag": meta["to_tag"],
                "author_email": (row.get("author_email") or "").strip().lower(),
                "author_name": (row.get("author_name") or "").strip(),
                "is_bot": "False",
                "commits": commits,
                "churn": churn,
                "share_commits": fmt(share_commits),
                "share_churn": fmt(share_churn),
            }
        )

    summary = {
        "project_id": meta["project_id"],
        "window_id": meta["window_id"],
        "from_tag": meta["from_tag"],
        "to_tag": meta["to_tag"],
        "total_commits": totals["total_commits"],
        "total_churn": totals["total_churn"],
        "unique_authors": totals["unique_authors"],
        "top1_share_commits": fmt(max(share_commits_values) if share_commits_values else 0.0),
        "top3_share_commits": fmt(top_k_sum(share_commits_values, 3)),
        "top1_share_churn": fmt(max(share_churn_values) if share_churn_values else 0.0),
        "top3_share_churn": fmt(top_k_sum(share_churn_values, 3)),
        "gini_commits": fmt(gini(commit_values)),
        "gini_churn": fmt(gini(churn_values)),
    }
    dev_rows.sort(
        key=lambda r: (
            r["project_id"],
            r["window_id"],
            -float(r["share_churn"]),
            r["author_email"],
        )
    )
    return dev_rows, summary


def build_bot_window_summary(group: list[dict[str, str]], meta: dict) -> dict:
    bots = [row for row in group if to_bool(row.get("is_bot"))]
    humans = [row for row in group if not to_bool(row.get("is_bot"))]
    all_commits = sum(to_int(row.get("commits")) for row in group)
    human_commits = sum(to_int(row.get("commits")) for row in humans)
    bot_commits = sum(to_int(row.get("commits")) for row in bots)
    all_churn = sum(to_int(row.get("churn")) for row in group)
    human_churn = sum(to_int(row.get("churn")) for row in humans)
    bot_churn = sum(to_int(row.get("churn")) for row in bots)
    max_commits = max((to_int(row.get("commits")) for row in group), default=0)
    max_churn = max((to_int(row.get("churn")) for row in group), default=0)
    identities = sorted({identity_label(row) for row in bots if identity_label(row)})
    return {
        "project_id": meta["project_id"],
        "window_id": meta["window_id"],
        "from_tag": meta["from_tag"],
        "to_tag": meta["to_tag"],
        "developer_rows_all": len(group),
        "developer_rows_human": len(humans),
        "developer_rows_bot": len(bots),
        "unique_authors_all": len({(row.get("author_email") or "").strip().lower() for row in group}),
        "unique_authors_human": len({(row.get("author_email") or "").strip().lower() for row in humans}),
        "total_commits_all": all_commits,
        "total_commits_human": human_commits,
        "total_commits_bot": bot_commits,
        "bot_commit_share": fmt(safe_div(bot_commits, all_commits)),
        "total_churn_all": all_churn,
        "total_churn_human": human_churn,
        "total_churn_bot": bot_churn,
        "bot_churn_share": fmt(safe_div(bot_churn, all_churn)),
        "bot_has_max_commits": str(any(to_int(row.get("commits")) == max_commits for row in bots) and bool(bots)),
        "bot_has_max_churn": str(any(to_int(row.get("churn")) == max_churn for row in bots) and bool(bots)),
        "bot_identities": ";".join(identities),
    }


def build_project_summaries(window_summaries: list[dict]) -> list[dict]:
    by_project: dict[str, list[dict]] = {}
    for row in window_summaries:
        by_project.setdefault(row["project_id"], []).append(row)

    out_rows: list[dict] = []
    for project_id in sorted(by_project):
        rows = by_project[project_id]
        all_commits = sum(to_int(row["total_commits_all"]) for row in rows)
        human_commits = sum(to_int(row["total_commits_human"]) for row in rows)
        bot_commits = sum(to_int(row["total_commits_bot"]) for row in rows)
        all_churn = sum(to_int(row["total_churn_all"]) for row in rows)
        human_churn = sum(to_int(row["total_churn_human"]) for row in rows)
        bot_churn = sum(to_int(row["total_churn_bot"]) for row in rows)
        identities = sorted(
            {
                identity
                for row in rows
                for identity in str(row.get("bot_identities", "")).split(";")
                if identity
            }
        )
        out_rows.append(
            {
                "project_id": project_id,
                "developer_rows_all": sum(to_int(row["developer_rows_all"]) for row in rows),
                "developer_rows_human": sum(to_int(row["developer_rows_human"]) for row in rows),
                "developer_rows_bot": sum(to_int(row["developer_rows_bot"]) for row in rows),
                "windows_with_bots": sum(1 for row in rows if to_int(row["developer_rows_bot"]) > 0),
                "windows_where_bot_top_committer": sum(
                    1 for row in rows if to_bool(row["bot_has_max_commits"])
                ),
                "total_commits_all": all_commits,
                "total_commits_human": human_commits,
                "total_commits_bot": bot_commits,
                "bot_commit_share": fmt(safe_div(bot_commits, all_commits)),
                "total_churn_all": all_churn,
                "total_churn_human": human_churn,
                "total_churn_bot": bot_churn,
                "bot_churn_share": fmt(safe_div(bot_churn, all_churn)),
                "bot_identities": ";".join(identities),
            }
        )
    return out_rows


def build_identity_summary(bot_rows: list[dict[str, str]]) -> list[dict]:
    by_identity: dict[tuple[str, str], list[dict[str, str]]] = {}
    for row in bot_rows:
        email = (row.get("author_email") or "").strip().lower()
        name = (row.get("author_name") or "").strip()
        by_identity.setdefault((email, name), []).append(row)

    out_rows: list[dict] = []
    for (email, name), rows in sorted(by_identity.items()):
        projects = sorted({row["project_id"] for row in rows})
        windows = sorted({row["window_id"] for row in rows})
        out_rows.append(
            {
                "author_email": email,
                "author_name": name,
                "developer_window_rows": len(rows),
                "project_count": len(projects),
                "window_count": len(windows),
                "total_commits": sum(to_int(row.get("commits")) for row in rows),
                "total_churn": sum(to_int(row.get("churn")) for row in rows),
                "projects": ";".join(projects),
                "windows": ";".join(windows),
            }
        )
    return out_rows


def validate_totals(
    dev_rows_by_key: dict[tuple[str, str], list[dict[str, str]]],
    totals_clean: list[dict[str, str]],
) -> int:
    mismatches = 0
    for row in totals_clean:
        key = (row["project_id"], row["window_id"])
        group = dev_rows_by_key.get(key, [])
        checks = {
            "total_commits": sum(to_int(r.get("commits")) for r in group),
            "total_added": sum(to_int(r.get("added")) for r in group),
            "total_deleted": sum(to_int(r.get("deleted")) for r in group),
            "total_churn": sum(to_int(r.get("churn")) for r in group),
            "unique_authors": len({(r.get("author_email") or "").strip().lower() for r in group}),
        }
        for field, expected in checks.items():
            if to_int(row.get(field)) != expected:
                mismatches += 1
                break
    return mismatches


def main() -> int:
    args = parse_args()
    base = Path.cwd()
    dev_path = resolve(args.dev_clean, base)
    totals_path = resolve(args.totals_clean, base)
    windows_path = resolve(args.windows, base)
    loc_path = resolve(args.loc, base)
    outdir = resolve(args.outdir, base)
    log_path = resolve(args.log, base)

    dev_rows = read_csv(dev_path)
    totals_clean = read_csv(totals_path)
    window_order, window_meta = build_window_metadata(read_csv(windows_path))
    loc_map = build_loc_map(read_csv(loc_path))

    grouped: dict[tuple[str, str], list[dict[str, str]]] = {}
    for row in dev_rows:
        key = (row["project_id"], row["window_id"])
        grouped.setdefault(key, []).append(row)

    human_dev_rows = [row for row in dev_rows if not to_bool(row.get("is_bot"))]
    bot_rows = [row for row in dev_rows if to_bool(row.get("is_bot"))]

    human_totals: list[dict] = []
    human_normalized: list[dict] = []
    ownership_dev: list[dict] = []
    ownership_summary: list[dict] = []
    bot_window_summary: list[dict] = []

    for meta in window_order:
        key = (meta["project_id"], meta["window_id"])
        group = grouped.get(key, [])
        human_group = [row for row in group if not to_bool(row.get("is_bot"))]
        totals = build_totals_for_group(human_group, meta)
        human_totals.append(totals)
        human_normalized.append(normalize_total_row(totals, meta, loc_map))
        dev_share_rows, summary = build_ownership(human_group, totals, meta)
        ownership_dev.extend(dev_share_rows)
        ownership_summary.append(summary)
        bot_window_summary.append(build_bot_window_summary(group, meta))

    human_dev_out = normalize_dev_rows(human_dev_rows)
    human_dev_out.sort(key=lambda r: (r["project_id"], r["window_id"], r["author_email"]))
    human_totals.sort(key=lambda r: (r["project_id"], r["window_id"]))
    human_normalized.sort(key=lambda r: (r["project_id"], r["window_id"]))
    ownership_summary.sort(key=lambda r: (r["project_id"], r["window_id"]))
    bot_window_summary.sort(key=lambda r: (r["project_id"], r["window_id"]))
    bot_project_summary = build_project_summaries(bot_window_summary)
    bot_identity_summary = build_identity_summary(bot_rows)

    dev_human_out = outdir / output_name("metrics_window_dev_human", args.output_suffix)
    totals_human_out = outdir / output_name("metrics_window_totals_human", args.output_suffix)
    normalized_human_out = outdir / output_name("metrics_window_totals_human_normalized", args.output_suffix)
    ownership_dev_out = outdir / output_name("ownership_dev_shares_human", args.output_suffix)
    ownership_summary_out = outdir / output_name("ownership_summary_human", args.output_suffix)
    bot_project_out = outdir / output_name("bot_summary_by_project", args.output_suffix)
    bot_window_out = outdir / output_name("bot_summary_by_window", args.output_suffix)
    bot_identity_out = outdir / output_name("bot_identity_summary", args.output_suffix)

    write_csv(dev_human_out, DEV_HUMAN_FIELDS, human_dev_out)
    write_csv(totals_human_out, TOTAL_HUMAN_FIELDS, human_totals)
    write_csv(
        normalized_human_out,
        NORMALIZED_HUMAN_FIELDS,
        human_normalized,
    )
    write_csv(ownership_dev_out, OWNERSHIP_DEV_FIELDS, ownership_dev)
    write_csv(ownership_summary_out, OWNERSHIP_SUMMARY_FIELDS, ownership_summary)
    write_csv(bot_project_out, BOT_PROJECT_FIELDS, bot_project_summary)
    write_csv(bot_window_out, BOT_WINDOW_FIELDS, bot_window_summary)
    write_csv(bot_identity_out, BOT_IDENTITY_FIELDS, bot_identity_summary)

    validation_mismatches = validate_totals(grouped, totals_clean)
    total_commits_all = sum(to_int(row.get("commits")) for row in dev_rows)
    total_commits_bot = sum(to_int(row.get("commits")) for row in bot_rows)
    total_churn_all = sum(to_int(row.get("churn")) for row in dev_rows)
    total_churn_bot = sum(to_int(row.get("churn")) for row in bot_rows)
    bot_windows = sum(1 for row in bot_window_summary if to_int(row["developer_rows_bot"]) > 0)
    bot_top_windows = sum(1 for row in bot_window_summary if to_bool(row["bot_has_max_commits"]))

    log_path.parent.mkdir(parents=True, exist_ok=True)
    now = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    with log_path.open("w", encoding="utf-8") as fh:
        fh.write(f"[{now}] input_file={dev_path}\n")
        fh.write(f"[{now}] input_rows={len(dev_rows)}\n")
        fh.write(f"[{now}] human_rows={len(human_dev_out)}\n")
        fh.write(f"[{now}] bot_rows={len(bot_rows)}\n")
        fh.write(f"[{now}] windows={len(window_order)}\n")
        fh.write(f"[{now}] windows_with_bots={bot_windows}\n")
        fh.write(f"[{now}] windows_where_bot_top_committer={bot_top_windows}\n")
        fh.write(f"[{now}] total_commits_all={total_commits_all}\n")
        fh.write(f"[{now}] total_commits_bot={total_commits_bot}\n")
        fh.write(f"[{now}] bot_commit_share={fmt(safe_div(total_commits_bot, total_commits_all))}\n")
        fh.write(f"[{now}] total_churn_all={total_churn_all}\n")
        fh.write(f"[{now}] total_churn_bot={total_churn_bot}\n")
        fh.write(f"[{now}] bot_churn_share={fmt(safe_div(total_churn_bot, total_churn_all))}\n")
        fh.write(f"[{now}] validation_all_account_total_mismatches={validation_mismatches}\n")
        fh.write(f"[{now}] primary_population_for_m3_m4=human_only\n")
        fh.write(f"[{now}] all_account_outputs_retained_for_audit_and_sensitivity=True\n")

    print(f"Wrote {len(human_dev_out)} rows to {dev_human_out}")
    print(f"Wrote {len(human_totals)} rows to {totals_human_out}")
    print(
        f"Wrote {len(human_normalized)} rows to "
        f"{normalized_human_out}"
    )
    print(f"Wrote {len(ownership_dev)} rows to {ownership_dev_out}")
    print(f"Wrote {len(ownership_summary)} rows to {ownership_summary_out}")
    print(f"Wrote {len(bot_project_summary)} rows to {bot_project_out}")
    print(f"Wrote {len(bot_window_summary)} rows to {bot_window_out}")
    print(f"Wrote {len(bot_identity_summary)} rows to {bot_identity_out}")
    print(f"Log written to {log_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
