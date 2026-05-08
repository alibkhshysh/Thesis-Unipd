#!/usr/bin/env python3
"""Compute Month 3 / Phase II C1 stability evidence.

The script treats the centralized Phase I ``_all`` files as immutable inputs and
writes derived comparative-analysis artifacts for the first Month 3 criterion:
metric stability across release windows and projects.
"""

from __future__ import annotations

import argparse
import datetime as dt
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


WINDOW_METRICS = [
    {
        "metric_signal_id": "M1_endpoint_kloc",
        "metric_family": "M1",
        "metric_label": "M1 endpoint KLOC",
        "value_column": "endpoint_kloc",
        "unit": "KLOC",
    },
    {
        "metric_signal_id": "M2_churn_per_kloc_day",
        "metric_family": "M2",
        "metric_label": "M2 churn/KLOC/day",
        "value_column": "churn_per_kloc_day",
        "unit": "lines per KLOC-day",
    },
    {
        "metric_signal_id": "M3_commits_per_day",
        "metric_family": "M3",
        "metric_label": "M3 commits/day",
        "value_column": "commits_per_day",
        "unit": "commits per day",
    },
    {
        "metric_signal_id": "M4_gini_churn",
        "metric_family": "M4",
        "metric_label": "M4 churn Gini",
        "value_column": "gini_churn",
        "unit": "share inequality",
    },
    {
        "metric_signal_id": "M4_top1_share_churn",
        "metric_family": "M4",
        "metric_label": "M4 top-1 churn share",
        "value_column": "top1_share_churn",
        "unit": "share",
    },
]


RANK_METRICS = [
    {
        "metric_signal_id": "M2_developer_churn_per_day",
        "metric_family": "M2",
        "metric_label": "M2 developer churn/day",
        "source": "dev",
        "value_column": "churn_per_day",
    },
    {
        "metric_signal_id": "M3_developer_commits_per_day",
        "metric_family": "M3",
        "metric_label": "M3 developer commits/day",
        "source": "dev",
        "value_column": "commits_per_day",
    },
    {
        "metric_signal_id": "M4_developer_share_churn",
        "metric_family": "M4",
        "metric_label": "M4 developer churn share",
        "source": "ownership",
        "value_column": "share_churn",
    },
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase1-dir", default=Path("../Phase 1"), type=Path)
    parser.add_argument("--out-dir", default=Path("out"), type=Path)
    parser.add_argument("--fig-dir", default=Path("figures"), type=Path)
    parser.add_argument("--report-fig-dir", default=None, type=Path)
    parser.add_argument(
        "--log",
        default=Path("logs/c1_stability_20260508.log"),
        type=Path,
    )
    return parser.parse_args()


def normalize_path(path: Path, base_dir: Path) -> Path:
    return path if path.is_absolute() else base_dir / path


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def read_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(path)
    return pd.read_csv(path)


def window_index(window_id: str) -> int:
    try:
        return int(window_id.rsplit("_W", 1)[1])
    except (IndexError, ValueError):
        return -1


def coerce_numeric(df: pd.DataFrame, columns: list[str]) -> None:
    for column in columns:
        if column in df.columns:
            df[column] = pd.to_numeric(df[column], errors="coerce")


def build_window_metric_values(phase1_dir: Path) -> pd.DataFrame:
    out_dir = phase1_dir / "out"

    totals = read_csv(out_dir / "metrics_window_totals_human_normalized_all.csv")
    ownership = read_csv(out_dir / "ownership_summary_human_all.csv")
    loc = read_csv(out_dir / "loc_per_tag_all.csv")

    coerce_numeric(
        totals,
        [
            "duration_days",
            "total_commits",
            "total_churn",
            "unique_authors",
            "mean_endpoint_kloc",
            "commits_per_day",
            "churn_per_day",
            "churn_per_kloc_day",
        ],
    )
    coerce_numeric(
        ownership,
        [
            "top1_share_commits",
            "top3_share_commits",
            "top1_share_churn",
            "top3_share_churn",
            "gini_commits",
            "gini_churn",
        ],
    )
    coerce_numeric(loc, ["code_lines"])

    loc_to_tag = loc[["project_id", "tag_name", "code_lines"]].rename(
        columns={"tag_name": "to_tag", "code_lines": "to_code_lines"}
    )

    merged = totals.merge(
        loc_to_tag,
        on=["project_id", "to_tag"],
        how="left",
        validate="many_to_one",
    ).merge(
        ownership[
            [
                "project_id",
                "window_id",
                "top1_share_churn",
                "top3_share_churn",
                "gini_churn",
                "top1_share_commits",
                "gini_commits",
            ]
        ],
        on=["project_id", "window_id"],
        how="left",
        validate="one_to_one",
    )
    merged["window_index"] = merged["window_id"].map(window_index)
    merged["endpoint_kloc"] = merged["to_code_lines"] / 1000.0

    rows: list[dict] = []
    base_columns = [
        "project_id",
        "window_id",
        "window_index",
        "from_tag",
        "to_tag",
        "duration_days",
        "analysis_set",
    ]
    for metric in WINDOW_METRICS:
        value_column = metric["value_column"]
        for _, row in merged.iterrows():
            rows.append(
                {
                    **{column: row[column] for column in base_columns},
                    "metric_signal_id": metric["metric_signal_id"],
                    "metric_family": metric["metric_family"],
                    "metric_label": metric["metric_label"],
                    "unit": metric["unit"],
                    "value": row[value_column],
                }
            )

    result = pd.DataFrame(rows)
    result.sort_values(
        ["metric_signal_id", "project_id", "window_index"],
        inplace=True,
    )
    return result


def adjacent_relative_changes(values: pd.Series) -> list[float]:
    ordered = values.dropna().astype(float).to_numpy()
    changes: list[float] = []
    for previous, current in zip(ordered[:-1], ordered[1:]):
        if previous == 0:
            continue
        changes.append(abs(current - previous) / abs(previous))
    return changes


def classify_cv(cv: float | None) -> str:
    if cv is None or pd.isna(cv):
        return "insufficient"
    if cv <= 0.25:
        return "low"
    if cv <= 0.75:
        return "moderate"
    return "high"


def summarize_values(group: pd.DataFrame, scope: str) -> dict:
    values = group.sort_values("window_index")["value"].dropna().astype(float)
    n = int(values.shape[0])
    if n == 0:
        return {
            f"{scope}_n_windows": 0,
            f"{scope}_mean": np.nan,
            f"{scope}_median": np.nan,
            f"{scope}_std": np.nan,
            f"{scope}_iqr": np.nan,
            f"{scope}_cv": np.nan,
            f"{scope}_robust_iqr_over_median": np.nan,
            f"{scope}_median_adjacent_relative_change": np.nan,
            f"{scope}_max_adjacent_relative_change": np.nan,
            f"{scope}_volatility_class": "insufficient",
        }

    mean_value = float(values.mean())
    median_value = float(values.median())
    std_value = float(values.std(ddof=1)) if n >= 2 else 0.0
    q1 = float(values.quantile(0.25))
    q3 = float(values.quantile(0.75))
    iqr = q3 - q1
    cv = std_value / abs(mean_value) if mean_value != 0 else np.nan
    robust = iqr / abs(median_value) if median_value != 0 else np.nan
    changes = adjacent_relative_changes(group.sort_values("window_index")["value"])

    return {
        f"{scope}_n_windows": n,
        f"{scope}_mean": mean_value,
        f"{scope}_median": median_value,
        f"{scope}_std": std_value,
        f"{scope}_iqr": iqr,
        f"{scope}_cv": cv,
        f"{scope}_robust_iqr_over_median": robust,
        f"{scope}_median_adjacent_relative_change": (
            float(np.median(changes)) if changes else np.nan
        ),
        f"{scope}_max_adjacent_relative_change": (
            float(np.max(changes)) if changes else np.nan
        ),
        f"{scope}_volatility_class": classify_cv(cv),
    }


def build_project_stability(window_values: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict] = []
    for (metric_id, project_id), group in window_values.groupby(
        ["metric_signal_id", "project_id"],
        sort=True,
    ):
        first = group.iloc[0]
        full_stats = summarize_values(group, "full")
        primary_group = group[group["analysis_set"] == "primary"]
        primary_stats = summarize_values(primary_group, "primary")
        rows.append(
            {
                "metric_signal_id": metric_id,
                "metric_family": first["metric_family"],
                "metric_label": first["metric_label"],
                "unit": first["unit"],
                "project_id": project_id,
                **full_stats,
                **primary_stats,
            }
        )

    result = pd.DataFrame(rows)
    result.sort_values(["metric_signal_id", "project_id"], inplace=True)
    return result


def build_overall_stability(project_stability: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict] = []
    for metric_id, group in project_stability.groupby("metric_signal_id", sort=True):
        first = group.iloc[0]
        valid_primary = group[group["primary_n_windows"] >= 2]
        rows.append(
            {
                "metric_signal_id": metric_id,
                "metric_family": first["metric_family"],
                "metric_label": first["metric_label"],
                "unit": first["unit"],
                "projects": int(group["project_id"].nunique()),
                "projects_with_primary_n_ge_2": int(valid_primary["project_id"].nunique()),
                "median_full_cv": group["full_cv"].median(skipna=True),
                "median_primary_cv": valid_primary["primary_cv"].median(skipna=True),
                "median_full_adjacent_relative_change": group[
                    "full_median_adjacent_relative_change"
                ].median(skipna=True),
                "median_primary_adjacent_relative_change": valid_primary[
                    "primary_median_adjacent_relative_change"
                ].median(skipna=True),
                "full_low_volatility_projects": int(
                    (group["full_volatility_class"] == "low").sum()
                ),
                "full_moderate_volatility_projects": int(
                    (group["full_volatility_class"] == "moderate").sum()
                ),
                "full_high_volatility_projects": int(
                    (group["full_volatility_class"] == "high").sum()
                ),
                "primary_low_volatility_projects": int(
                    (valid_primary["primary_volatility_class"] == "low").sum()
                ),
                "primary_moderate_volatility_projects": int(
                    (valid_primary["primary_volatility_class"] == "moderate").sum()
                ),
                "primary_high_volatility_projects": int(
                    (valid_primary["primary_volatility_class"] == "high").sum()
                ),
            }
        )

    result = pd.DataFrame(rows)
    result.sort_values("metric_signal_id", inplace=True)
    return result


def prepare_rank_source(
    phase1_dir: Path,
    metric: dict,
    flags: pd.DataFrame,
) -> pd.DataFrame:
    out_dir = phase1_dir / "out"
    if metric["source"] == "dev":
        data = read_csv(out_dir / "metrics_window_dev_human_normalized_all.csv")
        identity_columns = ["author_email", "author_name"]
    else:
        data = read_csv(out_dir / "ownership_dev_shares_human_all.csv")
        identity_columns = ["author_email", "author_name"]

    value_column = metric["value_column"]
    coerce_numeric(data, [value_column])

    columns = ["project_id", "window_id", *identity_columns, value_column]
    result = data[columns].copy()
    result = result.merge(
        flags[["project_id", "window_id", "analysis_set"]],
        on=["project_id", "window_id"],
        how="left",
        validate="many_to_one",
    )
    result["metric_signal_id"] = metric["metric_signal_id"]
    result["metric_family"] = metric["metric_family"]
    result["metric_label"] = metric["metric_label"]
    result["value"] = result[value_column]
    result["window_index"] = result["window_id"].map(window_index)
    return result


def build_rank_stability(phase1_dir: Path) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    flags = read_csv(phase1_dir / "out" / "window_duration_flags_all.csv")
    rank_rows: list[pd.DataFrame] = []
    for metric in RANK_METRICS:
        rank_rows.append(prepare_rank_source(phase1_dir, metric, flags))
    ranks = pd.concat(rank_rows, ignore_index=True)

    pair_rows: list[dict] = []
    for (metric_id, project_id), group in ranks.groupby(
        ["metric_signal_id", "project_id"],
        sort=True,
    ):
        group = group.dropna(subset=["value"]).copy()
        if group.empty:
            continue

        metric_family = group["metric_family"].iloc[0]
        metric_label = group["metric_label"].iloc[0]
        windows = (
            group[["window_id", "window_index", "analysis_set"]]
            .drop_duplicates()
            .sort_values("window_index")
            .to_dict("records")
        )
        for previous, current in zip(windows[:-1], windows[1:]):
            left = group[group["window_id"] == previous["window_id"]][
                ["author_email", "value"]
            ].copy()
            right = group[group["window_id"] == current["window_id"]][
                ["author_email", "value"]
            ].copy()
            left["rank_left"] = left["value"].rank(
                ascending=False,
                method="average",
            )
            right["rank_right"] = right["value"].rank(
                ascending=False,
                method="average",
            )
            merged = left[["author_email", "rank_left"]].merge(
                right[["author_email", "rank_right"]],
                on="author_email",
                how="inner",
            )
            common_developers = int(merged.shape[0])
            union_developers = int(
                len(set(left["author_email"]).union(set(right["author_email"])))
            )
            if (
                common_developers >= 2
                and merged["rank_left"].nunique() >= 2
                and merged["rank_right"].nunique() >= 2
            ):
                corr = merged["rank_left"].corr(merged["rank_right"], method="spearman")
            else:
                corr = np.nan

            pair_rows.append(
                {
                    "metric_signal_id": metric_id,
                    "metric_family": metric_family,
                    "metric_label": metric_label,
                    "project_id": project_id,
                    "from_window_id": previous["window_id"],
                    "to_window_id": current["window_id"],
                    "from_window_index": previous["window_index"],
                    "to_window_index": current["window_index"],
                    "from_analysis_set": previous["analysis_set"],
                    "to_analysis_set": current["analysis_set"],
                    "both_primary": (
                        previous["analysis_set"] == "primary"
                        and current["analysis_set"] == "primary"
                    ),
                    "common_developers": common_developers,
                    "union_developers": union_developers,
                    "common_developer_share": (
                        common_developers / union_developers
                        if union_developers
                        else np.nan
                    ),
                    "spearman_rank_correlation": corr,
                }
            )

    pairs = pd.DataFrame(pair_rows)
    if pairs.empty:
        return ranks, pairs, pd.DataFrame()

    summary_rows: list[dict] = []
    for (metric_id, project_id), group in pairs.groupby(
        ["metric_signal_id", "project_id"],
        sort=True,
    ):
        first = group.iloc[0]
        corr_values = group["spearman_rank_correlation"].dropna()
        primary = group[group["both_primary"]]
        primary_corr = primary["spearman_rank_correlation"].dropna()
        summary_rows.append(
            {
                "metric_signal_id": metric_id,
                "metric_family": first["metric_family"],
                "metric_label": first["metric_label"],
                "project_id": project_id,
                "adjacent_pairs": int(group.shape[0]),
                "pairs_with_rank_correlation": int(corr_values.shape[0]),
                "mean_spearman_rank_correlation": corr_values.mean()
                if not corr_values.empty
                else np.nan,
                "median_spearman_rank_correlation": corr_values.median()
                if not corr_values.empty
                else np.nan,
                "mean_common_developer_share": group["common_developer_share"].mean(),
                "primary_adjacent_pairs": int(primary.shape[0]),
                "primary_pairs_with_rank_correlation": int(primary_corr.shape[0]),
                "primary_mean_spearman_rank_correlation": primary_corr.mean()
                if not primary_corr.empty
                else np.nan,
                "primary_median_spearman_rank_correlation": primary_corr.median()
                if not primary_corr.empty
                else np.nan,
            }
        )

    summary = pd.DataFrame(summary_rows)
    summary.sort_values(["metric_signal_id", "project_id"], inplace=True)
    return ranks, pairs, summary


def build_rank_overall(rank_summary: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict] = []
    for metric_id, group in rank_summary.groupby("metric_signal_id", sort=True):
        first = group.iloc[0]
        rows.append(
            {
                "metric_signal_id": metric_id,
                "metric_family": first["metric_family"],
                "metric_label": first["metric_label"],
                "projects": int(group["project_id"].nunique()),
                "median_project_spearman": group[
                    "median_spearman_rank_correlation"
                ].median(skipna=True),
                "median_project_primary_spearman": group[
                    "primary_median_spearman_rank_correlation"
                ].median(skipna=True),
                "median_common_developer_share": group[
                    "mean_common_developer_share"
                ].median(skipna=True),
                "total_adjacent_pairs": int(group["adjacent_pairs"].sum()),
                "total_pairs_with_rank_correlation": int(
                    group["pairs_with_rank_correlation"].sum()
                ),
                "total_primary_adjacent_pairs": int(
                    group["primary_adjacent_pairs"].sum()
                ),
                "total_primary_pairs_with_rank_correlation": int(
                    group["primary_pairs_with_rank_correlation"].sum()
                ),
            }
        )
    result = pd.DataFrame(rows)
    result.sort_values("metric_signal_id", inplace=True)
    return result


def write_csv(df: pd.DataFrame, path: Path) -> None:
    ensure_parent(path)
    df.to_csv(path, index=False, float_format="%.6f")


def save_figure(fig: plt.Figure, filename: str, fig_dirs: list[Path]) -> None:
    for fig_dir in fig_dirs:
        ensure_dir(fig_dir)
        fig.savefig(fig_dir / filename, bbox_inches="tight")
    plt.close(fig)


def plot_volatility(project_stability: pd.DataFrame, fig_dirs: list[Path]) -> None:
    labels = [
        metric["metric_label"]
        for metric in WINDOW_METRICS
    ]
    metric_ids = [metric["metric_signal_id"] for metric in WINDOW_METRICS]

    fig, axes = plt.subplots(1, 2, figsize=(12, 4.8), sharey=True)
    for axis, column, title in [
        (axes[0], "full_cv", "All windows"),
        (axes[1], "primary_cv", "Primary windows only"),
    ]:
        data = [
            project_stability.loc[
                project_stability["metric_signal_id"] == metric_id,
                column,
            ]
            .dropna()
            .to_numpy()
            for metric_id in metric_ids
        ]
        axis.boxplot(data, tick_labels=labels, showfliers=True)
        axis.set_title(title)
        axis.set_ylabel("Coefficient of variation")
        axis.tick_params(axis="x", rotation=35)
        axis.grid(axis="y", linestyle=":", alpha=0.5)
    fig.suptitle("C1 metric volatility by project")
    fig.tight_layout()
    save_figure(fig, "c1_volatility_by_metric.pdf", fig_dirs)


def plot_rank_stability(pairs: pd.DataFrame, fig_dirs: list[Path]) -> None:
    if pairs.empty:
        return
    metric_order = [
        metric["metric_signal_id"]
        for metric in RANK_METRICS
    ]
    labels = [
        metric["metric_label"]
        for metric in RANK_METRICS
    ]
    fig, axis = plt.subplots(figsize=(8.5, 4.8))
    data = [
        pairs.loc[
            pairs["metric_signal_id"] == metric_id,
            "spearman_rank_correlation",
        ]
        .dropna()
        .to_numpy()
        for metric_id in metric_order
    ]
    axis.boxplot(data, tick_labels=labels, showfliers=True)
    axis.axhline(0, color="black", linewidth=0.8)
    axis.set_ylabel("Adjacent-window Spearman rank correlation")
    axis.set_title("C1 developer-rank stability")
    axis.tick_params(axis="x", rotation=25)
    axis.grid(axis="y", linestyle=":", alpha=0.5)
    fig.tight_layout()
    save_figure(fig, "c1_rank_stability_by_metric.pdf", fig_dirs)


def plot_indexed_trends(window_values: pd.DataFrame, fig_dirs: list[Path]) -> None:
    metric_ids = [metric["metric_signal_id"] for metric in WINDOW_METRICS]
    fig, axes = plt.subplots(3, 2, figsize=(11.5, 10.5), sharex=True)
    axes_flat = axes.flatten()
    for axis, metric_id in zip(axes_flat, metric_ids):
        metric_data = window_values[window_values["metric_signal_id"] == metric_id]
        label = metric_data["metric_label"].iloc[0]
        for project_id, project_data in metric_data.groupby("project_id", sort=True):
            project_data = project_data.sort_values("window_index")
            median_value = project_data["value"].median(skipna=True)
            if pd.isna(median_value) or median_value == 0:
                continue
            indexed = project_data["value"] / median_value
            axis.plot(
                project_data["window_index"],
                indexed,
                marker="o",
                linewidth=1.0,
                markersize=3,
                alpha=0.75,
                label=project_id,
            )
        axis.axhline(1.0, color="black", linewidth=0.7, alpha=0.6)
        axis.set_title(label)
        axis.set_ylabel("value / project median")
        axis.grid(axis="y", linestyle=":", alpha=0.5)
    axes_flat[-1].axis("off")
    handles, labels = axes_flat[0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="lower center", ncol=5, fontsize=8)
    fig.suptitle("C1 indexed metric trajectories by project", y=0.98)
    fig.supxlabel("Release-window index")
    fig.tight_layout(rect=[0, 0.05, 1, 0.96])
    save_figure(fig, "c1_indexed_metric_trends.pdf", fig_dirs)


def write_log(
    path: Path,
    window_values: pd.DataFrame,
    project_stability: pd.DataFrame,
    overall_stability: pd.DataFrame,
    rank_pairs: pd.DataFrame,
    rank_summary: pd.DataFrame,
    rank_overall: pd.DataFrame,
) -> None:
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    lines = [
        f"[{stamp}] c1_stability_analysis=completed",
        f"[{stamp}] window_metric_rows={len(window_values)}",
        f"[{stamp}] project_stability_rows={len(project_stability)}",
        f"[{stamp}] overall_stability_rows={len(overall_stability)}",
        f"[{stamp}] rank_pair_rows={len(rank_pairs)}",
        f"[{stamp}] rank_project_summary_rows={len(rank_summary)}",
        f"[{stamp}] rank_overall_rows={len(rank_overall)}",
        f"[{stamp}] projects={','.join(sorted(window_values['project_id'].unique()))}",
        f"[{stamp}] window_metric_signals={','.join(sorted(window_values['metric_signal_id'].unique()))}",
        f"[{stamp}] rank_metric_signals={','.join(sorted(rank_pairs['metric_signal_id'].unique())) if not rank_pairs.empty else ''}",
        f"[{stamp}] result=derived_c1_tables_and_figures_written",
    ]
    ensure_parent(path)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    args = parse_args()
    base_dir = Path.cwd()

    phase1_dir = normalize_path(args.phase1_dir, base_dir)
    out_dir = normalize_path(args.out_dir, base_dir)
    fig_dir = normalize_path(args.fig_dir, base_dir)
    log_path = normalize_path(args.log, base_dir)
    report_fig_dir = (
        normalize_path(args.report_fig_dir, base_dir)
        if args.report_fig_dir is not None
        else None
    )
    fig_dirs = [fig_dir]
    if report_fig_dir is not None:
        fig_dirs.append(report_fig_dir)

    ensure_dir(out_dir)
    ensure_dir(fig_dir)
    if report_fig_dir is not None:
        ensure_dir(report_fig_dir)

    window_values = build_window_metric_values(phase1_dir)
    project_stability = build_project_stability(window_values)
    overall_stability = build_overall_stability(project_stability)
    rank_values, rank_pairs, rank_summary = build_rank_stability(phase1_dir)
    rank_overall = build_rank_overall(rank_summary)

    write_csv(window_values, out_dir / "c1_metric_window_values_all.csv")
    write_csv(project_stability, out_dir / "c1_metric_stability_by_project_all.csv")
    write_csv(overall_stability, out_dir / "c1_metric_stability_overall_all.csv")
    write_csv(rank_values, out_dir / "c1_rank_input_values_all.csv")
    write_csv(rank_pairs, out_dir / "c1_rank_stability_pairs_all.csv")
    write_csv(rank_summary, out_dir / "c1_rank_stability_by_project_all.csv")
    write_csv(rank_overall, out_dir / "c1_rank_stability_overall_all.csv")

    plot_volatility(project_stability, fig_dirs)
    plot_rank_stability(rank_pairs, fig_dirs)
    plot_indexed_trends(window_values, fig_dirs)

    write_log(
        log_path,
        window_values,
        project_stability,
        overall_stability,
        rank_pairs,
        rank_summary,
        rank_overall,
    )

    print(f"Wrote C1 stability outputs to {out_dir}")
    print(f"Wrote C1 figures to {', '.join(str(path) for path in fig_dirs)}")
    print(f"Wrote log to {log_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
