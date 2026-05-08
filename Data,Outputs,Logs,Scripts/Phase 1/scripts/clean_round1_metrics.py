#!/usr/bin/env python3
"""Clean Round-1 metrics by consolidating duplicate author identities per window."""

from __future__ import annotations

import argparse
import csv
import datetime as dt
from collections import Counter
from pathlib import Path


DEV_REQUIRED_FIELDS = {
    "project_id",
    "window_id",
    "author_email",
    "author_name",
    "commits",
    "added",
    "deleted",
    "churn",
    "binary_file_count",
    "active_days",
    "first_commit",
    "last_commit",
}

WINDOWS_REQUIRED_FIELDS = {"project_id", "window_id", "from_tag", "to_tag"}

DEV_OUT_FIELDS = [
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

TOTALS_OUT_FIELDS = [
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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--in-dev", default="out/metrics_window_dev_all.csv", type=Path)
    parser.add_argument("--windows", default="data/windows_all.csv", type=Path)
    parser.add_argument(
        "--out-dev-clean", default="out/metrics_window_dev_clean_all.csv", type=Path
    )
    parser.add_argument(
        "--out-totals-clean", default="out/metrics_window_totals_clean_all.csv", type=Path
    )
    parser.add_argument("--log", default="logs/clean_all_metrics.log", type=Path)
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


def is_unknown_name(name: str) -> bool:
    return name.strip().lower() in UNKNOWN_NAMES


def parse_dt(value: str) -> dt.datetime | None:
    s = (value or "").strip()
    if not s:
        return None

    for parser in (
        lambda x: dt.datetime.fromisoformat(x.replace("Z", "+00:00")),
        lambda x: dt.datetime.strptime(x, "%Y-%m-%d %H:%M:%S %z"),
        lambda x: dt.datetime.strptime(x, "%Y-%m-%d %H:%M:%S"),
    ):
        try:
            return parser(s)
        except ValueError:
            continue
    return None


def dt_to_str(value: dt.datetime | None, fallback: str = "") -> str:
    if value is None:
        return fallback
    return value.strftime("%Y-%m-%d %H:%M:%S %z").strip()


def read_csv(path: Path, required_fields: set[str]) -> list[dict]:
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        if not reader.fieldnames:
            raise ValueError(f"{path} is empty or missing a header")
        missing = required_fields.difference(set(reader.fieldnames))
        if missing:
            missing_list = ", ".join(sorted(missing))
            raise ValueError(f"{path} missing required columns: {missing_list}")
        return [row for row in reader]


def write_csv(path: Path, fieldnames: list[str], rows: list[dict]) -> None:
    ensure_parent(path)
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def choose_author_name(rows: list[dict]) -> str:
    # Rule: most frequent non-"unknown" name; else keep first.
    freq: Counter[str] = Counter()
    first_idx: dict[str, int] = {}

    for i, row in enumerate(rows):
        raw = (row.get("author_name") or "").strip()
        if raw and not is_unknown_name(raw):
            freq[raw] += 1
            first_idx.setdefault(raw, i)

    if freq:
        # Stable tie-breaker by earliest appearance then lexical.
        ranked = sorted(freq.items(), key=lambda kv: (-kv[1], first_idx[kv[0]], kv[0]))
        return ranked[0][0]

    # Else keep first available author_name.
    for row in rows:
        raw = (row.get("author_name") or "").strip()
        if raw:
            return raw
    return "unknown"


def resolve_windows_path(candidate: Path, base: Path) -> Path:
    if candidate.exists():
        return candidate
    fallback = base / "data" / "windows.csv"
    if fallback.exists():
        return fallback
    raise FileNotFoundError(
        f"Windows file not found at {candidate} and fallback {fallback} is missing."
    )


def main() -> int:
    args = parse_args()
    base = Path.cwd()

    in_dev = normalize(args.in_dev, base)
    windows_path = resolve_windows_path(normalize(args.windows, base), base)
    out_dev_clean = normalize(args.out_dev_clean, base)
    out_totals_clean = normalize(args.out_totals_clean, base)
    log_path = normalize(args.log, base)

    dev_rows = read_csv(in_dev, DEV_REQUIRED_FIELDS)
    windows_rows = read_csv(windows_path, WINDOWS_REQUIRED_FIELDS)

    windows_map: dict[tuple[str, str], dict] = {}
    for w in windows_rows:
        key = (w["project_id"].strip(), w["window_id"].strip())
        windows_map[key] = {
            "from_tag": (w.get("from_tag") or "").strip(),
            "to_tag": (w.get("to_tag") or "").strip(),
        }

    grouped: dict[tuple[str, str, str], list[dict]] = {}
    for row in dev_rows:
        key = (
            (row.get("project_id") or "").strip(),
            (row.get("window_id") or "").strip(),
            (row.get("author_email") or "").strip().lower(),
        )
        grouped.setdefault(key, []).append(row)

    clean_dev: list[dict] = []
    duplicate_groups = 0
    merged_rows = 0

    for key in sorted(grouped):
        project_id, window_id, author_email = key
        rows = grouped[key]

        if len(rows) > 1:
            duplicate_groups += 1
            merged_rows += len(rows) - 1

        from_to = windows_map.get((project_id, window_id), {})
        from_tag = from_to.get("from_tag", "")
        to_tag = from_to.get("to_tag", "")

        if not from_tag:
            from_tag = (rows[0].get("from_tag") or "").strip()
        if not to_tag:
            to_tag = (rows[0].get("to_tag") or "").strip()

        commits = sum(to_int(r.get("commits")) for r in rows)
        added = sum(to_int(r.get("added")) for r in rows)
        deleted = sum(to_int(r.get("deleted")) for r in rows)
        churn = sum(to_int(r.get("churn")) for r in rows)
        binary_file_count = sum(to_int(r.get("binary_file_count")) for r in rows)

        # We cannot reconstruct exact distinct commit-day sets from aggregated rows.
        active_days = max((to_int(r.get("active_days")) for r in rows), default=0)

        first_dt_candidates = [parse_dt(r.get("first_commit", "")) for r in rows]
        first_dt_candidates = [x for x in first_dt_candidates if x is not None]
        last_dt_candidates = [parse_dt(r.get("last_commit", "")) for r in rows]
        last_dt_candidates = [x for x in last_dt_candidates if x is not None]

        first_dt = min(first_dt_candidates) if first_dt_candidates else None
        last_dt = max(last_dt_candidates) if last_dt_candidates else None
        first_raw = (rows[0].get("first_commit") or "").strip()
        last_raw = (rows[0].get("last_commit") or "").strip()

        author_name = choose_author_name(rows)
        is_bot = any(to_bool(r.get("is_bot")) for r in rows)

        clean_dev.append(
            {
                "project_id": project_id,
                "window_id": window_id,
                "from_tag": from_tag,
                "to_tag": to_tag,
                "author_email": author_email,
                "author_name": author_name,
                "is_bot": is_bot,
                "commits": commits,
                "added": added,
                "deleted": deleted,
                "churn": churn,
                "binary_file_count": binary_file_count,
                "active_days": active_days,
                "first_commit": dt_to_str(first_dt, fallback=first_raw),
                "last_commit": dt_to_str(last_dt, fallback=last_raw),
            }
        )

    clean_dev.sort(
        key=lambda r: (
            r["project_id"],
            r["window_id"],
            -to_int(r["churn"]),
            r["author_email"],
        )
    )

    # Build clean totals for every declared window.
    totals_acc: dict[tuple[str, str], dict] = {}
    for row in clean_dev:
        key = (row["project_id"], row["window_id"])
        acc = totals_acc.setdefault(
            key,
            {
                "project_id": row["project_id"],
                "window_id": row["window_id"],
                "from_tag": row.get("from_tag", ""),
                "to_tag": row.get("to_tag", ""),
                "total_commits": 0,
                "total_added": 0,
                "total_deleted": 0,
                "total_churn": 0,
                "author_emails": set(),
            },
        )
        acc["total_commits"] += to_int(row.get("commits"))
        acc["total_added"] += to_int(row.get("added"))
        acc["total_deleted"] += to_int(row.get("deleted"))
        acc["total_churn"] += to_int(row.get("churn"))
        acc["author_emails"].add(row["author_email"])

    clean_totals: list[dict] = []
    window_keys = sorted(windows_map.keys())
    for key in window_keys:
        project_id, window_id = key
        from_tag = windows_map[key].get("from_tag", "")
        to_tag = windows_map[key].get("to_tag", "")

        if key in totals_acc:
            acc = totals_acc[key]
            clean_totals.append(
                {
                    "project_id": project_id,
                    "window_id": window_id,
                    "from_tag": from_tag or acc.get("from_tag", ""),
                    "to_tag": to_tag or acc.get("to_tag", ""),
                    "total_commits": acc["total_commits"],
                    "total_added": acc["total_added"],
                    "total_deleted": acc["total_deleted"],
                    "total_churn": acc["total_churn"],
                    "unique_authors": len(acc["author_emails"]),
                }
            )
        else:
            clean_totals.append(
                {
                    "project_id": project_id,
                    "window_id": window_id,
                    "from_tag": from_tag,
                    "to_tag": to_tag,
                    "total_commits": 0,
                    "total_added": 0,
                    "total_deleted": 0,
                    "total_churn": 0,
                    "unique_authors": 0,
                }
            )

    clean_totals.sort(key=lambda r: (r["project_id"], r["window_id"]))

    write_csv(out_dev_clean, DEV_OUT_FIELDS, clean_dev)
    write_csv(out_totals_clean, TOTALS_OUT_FIELDS, clean_totals)

    ensure_parent(log_path)
    now = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    log_lines = [
        f"[{now}] input_rows={len(dev_rows)}",
        f"[{now}] unique_keys_after_clean={len(clean_dev)}",
        f"[{now}] duplicate_key_groups_merged={duplicate_groups}",
        f"[{now}] merged_rows_count={merged_rows}",
        f"[{now}] windows_source={windows_path}",
        f"[{now}] output_dev_clean={out_dev_clean}",
        f"[{now}] output_totals_clean={out_totals_clean}",
    ]
    log_path.write_text("\n".join(log_lines) + "\n", encoding="utf-8")

    print(f"Wrote {len(clean_dev)} rows to {out_dev_clean}")
    print(f"Wrote {len(clean_totals)} rows to {out_totals_clean}")
    print(f"Duplicate key groups merged: {duplicate_groups}")
    print(f"Merged duplicate rows: {merged_rows}")
    print(f"Log written to {log_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
