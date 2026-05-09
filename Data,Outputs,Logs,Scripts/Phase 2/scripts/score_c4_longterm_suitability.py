#!/usr/bin/env python3
"""Generate Month 3 / Phase II C4 long-term suitability artifacts.

C4 evaluates whether each candidate metric remains useful as the project
history grows, whether it survives different release-cycle patterns, and
whether it can be updated incrementally from the centralized Phase I evidence.
"""

from __future__ import annotations

import argparse
import datetime as dt
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import pandas as pd


DIMENSIONS = [
    {
        "dimension_id": "C4_D1",
        "dimension": "Historical coverage",
        "max_score": 2,
        "description": "Whether the current Phase I evidence covers the metric over all frozen projects and windows.",
    },
    {
        "dimension_id": "C4_D2",
        "dimension": "Lifecycle robustness",
        "max_score": 2,
        "description": "Whether the metric remains meaningful across growth, maintenance, and short-release phases.",
    },
    {
        "dimension_id": "C4_D3",
        "dimension": "Incremental update feasibility",
        "max_score": 2,
        "description": "Whether the metric can be updated from a new tag or release window without recomputing full history.",
    },
    {
        "dimension_id": "C4_D4",
        "dimension": "Compact audit record",
        "max_score": 2,
        "description": "Whether long-term evidence can be stored as compact, hash-anchored records.",
    },
    {
        "dimension_id": "C4_D5",
        "dimension": "Long-term reputation fit",
        "max_score": 2,
        "description": "Whether the metric remains useful for reputation reasoning over extended histories.",
    },
]


METRIC_SCORES = [
    {
        "metric_id": "M1",
        "metric_name": "Snapshot size (LOC/SLOC)",
        "implementation_status": "implemented",
        "evidence_source": "loc_per_tag_all.csv",
        "dimension_scores": {
            "C4_D1": (2, "The LOC/SLOC evidence covers every frozen tag in the ten-repository dataset."),
            "C4_D2": (1, "Size remains useful as project context, but its meaning changes as projects mature."),
            "C4_D3": (2, "A new release only requires counting the new endpoint tag."),
            "C4_D4": (2, "The stored record is compact: tag identity plus line-count fields."),
            "C4_D5": (0, "Size is not a developer-reputation signal by itself."),
        },
    },
    {
        "metric_id": "M2",
        "metric_name": "Patch complexity proxy (churn)",
        "implementation_status": "implemented",
        "evidence_source": "metrics_window_dev_human_all.csv; metrics_window_totals_human_normalized_all.csv",
        "dimension_scores": {
            "C4_D1": (2, "Human-only churn evidence is available for all frozen release windows."),
            "C4_D2": (1, "Churn remains informative, but release style and refactoring cycles can change its interpretation."),
            "C4_D3": (2, "A new window can be added from the diff between the previous and new release tag."),
            "C4_D4": (1, "Aggregates are compact, but developer-level churn histories can grow with contributor count."),
            "C4_D5": (1, "It is a useful effort signal over time, but not a sufficient reputation measure alone."),
        },
    },
    {
        "metric_id": "M3",
        "metric_name": "Activity cadence",
        "implementation_status": "implemented",
        "evidence_source": "metrics_window_dev_human_all.csv; metrics_window_dev_human_normalized_all.csv",
        "dimension_scores": {
            "C4_D1": (2, "Human-only commit and active-day evidence covers all release windows."),
            "C4_D2": (1, "Cadence remains readable, but project activity naturally changes across lifecycle phases."),
            "C4_D3": (2, "New commits and active days can be appended per new release window."),
            "C4_D4": (2, "Counts, dates, and normalized rates are compact to store and audit."),
            "C4_D5": (1, "It helps explain continuity, but must be paired with quality and ownership context."),
        },
    },
    {
        "metric_id": "M4",
        "metric_name": "Ownership / concentration",
        "implementation_status": "implemented",
        "evidence_source": "ownership_dev_shares_human_all.csv; ownership_summary_human_all.csv",
        "dimension_scores": {
            "C4_D1": (2, "Ownership summaries and developer-share rows are available for all release windows."),
            "C4_D2": (2, "Relative shares remain meaningful across project size and lifecycle changes."),
            "C4_D3": (1, "A new window can be added incrementally, but identity and share distributions must be maintained."),
            "C4_D4": (1, "Summary records are compact, while full developer-share evidence is larger."),
            "C4_D5": (2, "Sustained ownership is directly relevant to long-term maintainer reputation."),
        },
    },
    {
        "metric_id": "M5",
        "metric_name": "Maintenance responsiveness",
        "implementation_status": "design_extension",
        "evidence_source": "not available in current Phase I artifacts",
        "dimension_scores": {
            "C4_D1": (0, "The current dataset does not include issue or pull-request response events."),
            "C4_D2": (2, "Responsiveness would be meaningful across long maintenance histories if collected."),
            "C4_D3": (0, "No current event stream exists to update incrementally."),
            "C4_D4": (0, "The compact record shape cannot be validated without event definitions and sampling rules."),
            "C4_D5": (2, "Conceptually, responsiveness would fit long-term maintenance reputation."),
        },
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
        default=Path("logs/c4_longterm_suitability_20260508.log"),
        type=Path,
    )
    return parser.parse_args()


def normalize_path(path: Path, base_dir: Path) -> Path:
    return path if path.is_absolute() else base_dir / path


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def score_label(score: int) -> str:
    if score == 2:
        return "strong"
    if score == 1:
        return "partial"
    return "weak"


def suitability_band(normalized_score: float) -> str:
    if normalized_score >= 0.8:
        return "high"
    if normalized_score >= 0.5:
        return "medium"
    return "low"


def decision_note(metric_id: str, status: str) -> str:
    if status == "design_extension":
        return "Promising for future work, but not eligible for the current empirical PoC decision."
    if metric_id == "M1":
        return "Retain as long-term context and normalization support, not as a standalone reputation metric."
    if metric_id == "M2":
        return "Retain as an incremental effort signal with volatility and churn-quality caveats."
    if metric_id == "M3":
        return "Retain as a compact continuity signal, but combine with churn and ownership evidence."
    if metric_id == "M4":
        return "Strong long-term candidate because relative ownership remains meaningful across project histories."
    return "Retain for comparison."


def read_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(path)
    return pd.read_csv(path)


def build_lifecycle_coverage(phase1_dir: Path) -> pd.DataFrame:
    windows = read_csv(phase1_dir / "data" / "windows_all.csv")
    loc = read_csv(phase1_dir / "out" / "loc_per_tag_all.csv")
    totals = read_csv(phase1_dir / "out" / "metrics_window_totals_human_normalized_all.csv")

    windows["from_dt"] = pd.to_datetime(windows["from_date"], utc=True)
    windows["to_dt"] = pd.to_datetime(windows["to_date"], utc=True)
    windows["duration_days_from_tags"] = (
        windows["to_dt"] - windows["from_dt"]
    ).dt.total_seconds() / 86400

    loc["code_lines"] = pd.to_numeric(loc["code_lines"], errors="coerce")
    totals["duration_days"] = pd.to_numeric(totals["duration_days"], errors="coerce")
    totals["total_commits"] = pd.to_numeric(totals["total_commits"], errors="coerce")
    totals["total_churn"] = pd.to_numeric(totals["total_churn"], errors="coerce")
    totals["mean_endpoint_kloc"] = pd.to_numeric(totals["mean_endpoint_kloc"], errors="coerce")

    rows: list[dict] = []
    for project_id, project_windows in windows.groupby("project_id", sort=True):
        project_loc = loc[loc["project_id"] == project_id]
        project_totals = totals[totals["project_id"] == project_id]
        primary_windows = int((project_totals["analysis_set"] == "primary").sum())
        sensitivity_windows = int((project_totals["analysis_set"] == "sensitivity_only").sum())
        span_days = (
            project_windows["to_dt"].max() - project_windows["from_dt"].min()
        ).total_seconds() / 86400
        rows.append(
            {
                "project_id": project_id,
                "frozen_tags": int(project_loc["tag_name"].nunique()),
                "release_windows": int(project_windows["window_id"].nunique()),
                "history_span_days": span_days,
                "median_window_days": float(project_totals["duration_days"].median()),
                "primary_windows": primary_windows,
                "sensitivity_only_windows": sensitivity_windows,
                "total_human_commits": int(project_totals["total_commits"].sum()),
                "total_human_churn": int(project_totals["total_churn"].sum()),
                "median_endpoint_kloc": float(project_totals["mean_endpoint_kloc"].median()),
            }
        )
    return pd.DataFrame(rows)


def build_metric_evidence(phase1_dir: Path) -> pd.DataFrame:
    loc = read_csv(phase1_dir / "out" / "loc_per_tag_all.csv")
    totals = read_csv(phase1_dir / "out" / "metrics_window_totals_human_normalized_all.csv")
    dev = read_csv(phase1_dir / "out" / "metrics_window_dev_human_all.csv")
    ownership_summary = read_csv(phase1_dir / "out" / "ownership_summary_human_all.csv")
    ownership_dev = read_csv(phase1_dir / "out" / "ownership_dev_shares_human_all.csv")

    evidence = {
        "M1": {
            "observed_projects": loc["project_id"].nunique(),
            "observed_records": len(loc),
            "analysis_unit": "project tag",
            "coverage_note": "all frozen tags",
        },
        "M2": {
            "observed_projects": totals["project_id"].nunique(),
            "observed_records": len(dev),
            "analysis_unit": "project window developer",
            "coverage_note": "all frozen human-only windows",
        },
        "M3": {
            "observed_projects": totals["project_id"].nunique(),
            "observed_records": len(dev),
            "analysis_unit": "project window developer",
            "coverage_note": "all frozen human-only windows",
        },
        "M4": {
            "observed_projects": ownership_summary["project_id"].nunique(),
            "observed_records": len(ownership_dev),
            "analysis_unit": "project window developer share",
            "coverage_note": "all frozen human-only windows",
        },
        "M5": {
            "observed_projects": 0,
            "observed_records": 0,
            "analysis_unit": "issue or pull-request event",
            "coverage_note": "not collected in current Phase I",
        },
    }

    rows: list[dict] = []
    metric_lookup = {item["metric_id"]: item for item in METRIC_SCORES}
    for metric_id, details in evidence.items():
        metric = metric_lookup[metric_id]
        rows.append(
            {
                "metric_id": metric_id,
                "metric_name": metric["metric_name"],
                "implementation_status": metric["implementation_status"],
                "evidence_source": metric["evidence_source"],
                **details,
            }
        )
    return pd.DataFrame(rows)


def build_rubric() -> pd.DataFrame:
    return pd.DataFrame(DIMENSIONS)


def build_scores() -> pd.DataFrame:
    rows: list[dict] = []
    dimension_lookup = {item["dimension_id"]: item for item in DIMENSIONS}
    for metric in METRIC_SCORES:
        for dimension_id, (score, rationale) in metric["dimension_scores"].items():
            dimension = dimension_lookup[dimension_id]
            rows.append(
                {
                    "metric_id": metric["metric_id"],
                    "metric_name": metric["metric_name"],
                    "implementation_status": metric["implementation_status"],
                    "dimension_id": dimension_id,
                    "dimension": dimension["dimension"],
                    "score": score,
                    "max_score": dimension["max_score"],
                    "score_label": score_label(score),
                    "rationale": rationale,
                }
            )
    return pd.DataFrame(rows)


def build_summary(scores: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict] = []
    metric_order = {metric["metric_id"]: index for index, metric in enumerate(METRIC_SCORES)}
    for (metric_id, metric_name, status), group in scores.groupby(
        ["metric_id", "metric_name", "implementation_status"],
        sort=True,
    ):
        total = int(group["score"].sum())
        max_total = int(group["max_score"].sum())
        normalized = total / max_total if max_total else 0.0
        weakest = group[group["score"] == group["score"].min()]
        strongest = group[group["score"] == group["score"].max()]
        rows.append(
            {
                "metric_id": metric_id,
                "metric_name": metric_name,
                "implementation_status": status,
                "total_score": total,
                "max_score": max_total,
                "normalized_score": normalized,
                "longterm_suitability_band": suitability_band(normalized),
                "strongest_dimensions": "; ".join(strongest["dimension"].tolist()),
                "weakest_dimensions": "; ".join(weakest["dimension"].tolist()),
                "decision_note": decision_note(metric_id, status),
            }
        )
    result = pd.DataFrame(rows)
    result["_status_rank"] = result["implementation_status"].map(
        {"implemented": 0, "design_extension": 1}
    )
    result["_metric_rank"] = result["metric_id"].map(metric_order)
    result.sort_values(
        ["_status_rank", "normalized_score", "_metric_rank"],
        ascending=[True, False, True],
        inplace=True,
    )
    result.drop(columns=["_status_rank", "_metric_rank"], inplace=True)
    return result


def write_csv(df: pd.DataFrame, path: Path) -> None:
    ensure_parent(path)
    df.to_csv(path, index=False, float_format="%.3f")


def plot_summary(summary: pd.DataFrame, fig_dirs: list[Path]) -> None:
    plot_data = summary.copy()
    plot_data["label"] = plot_data["metric_id"] + " " + plot_data["metric_name"]
    colors = [
        "#4c78a8" if status == "implemented" else "#9e9e9e"
        for status in plot_data["implementation_status"]
    ]

    fig, axis = plt.subplots(figsize=(9, 4.8))
    axis.barh(plot_data["label"], plot_data["total_score"], color=colors)
    axis.set_xlim(0, 10)
    axis.set_xlabel("C4 long-term suitability score (0-10)")
    axis.set_title("C4 long-term suitability scores by metric")
    axis.grid(axis="x", linestyle=":", alpha=0.45)
    for index, value in enumerate(plot_data["total_score"]):
        axis.text(value + 0.12, index, f"{value}/10", va="center", fontsize=9)
    axis.invert_yaxis()
    fig.tight_layout()

    for fig_dir in fig_dirs:
        ensure_dir(fig_dir)
        fig.savefig(fig_dir / "c4_longterm_suitability_scores.pdf", bbox_inches="tight")
    plt.close(fig)


def write_log(
    path: Path,
    lifecycle: pd.DataFrame,
    evidence: pd.DataFrame,
    rubric: pd.DataFrame,
    scores: pd.DataFrame,
    summary: pd.DataFrame,
) -> None:
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    lines = [
        f"[{stamp}] c4_longterm_suitability_scoring=completed",
        f"[{stamp}] lifecycle_project_rows={len(lifecycle)}",
        f"[{stamp}] metric_evidence_rows={len(evidence)}",
        f"[{stamp}] rubric_dimensions={len(rubric)}",
        f"[{stamp}] score_rows={len(scores)}",
        f"[{stamp}] summary_rows={len(summary)}",
        f"[{stamp}] frozen_projects={int(lifecycle['project_id'].nunique())}",
        f"[{stamp}] frozen_tags={int(lifecycle['frozen_tags'].sum())}",
        f"[{stamp}] frozen_windows={int(lifecycle['release_windows'].sum())}",
        f"[{stamp}] primary_windows={int(lifecycle['primary_windows'].sum())}",
        f"[{stamp}] sensitivity_only_windows={int(lifecycle['sensitivity_only_windows'].sum())}",
        f"[{stamp}] implemented_metrics={','.join(metric['metric_id'] for metric in METRIC_SCORES if metric['implementation_status'] == 'implemented')}",
        f"[{stamp}] design_extension_metrics={','.join(metric['metric_id'] for metric in METRIC_SCORES if metric['implementation_status'] == 'design_extension')}",
        f"[{stamp}] result=derived_c4_longterm_tables_and_figure_written",
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

    lifecycle = build_lifecycle_coverage(phase1_dir)
    evidence = build_metric_evidence(phase1_dir)
    rubric = build_rubric()
    scores = build_scores()
    summary = build_summary(scores)

    write_csv(lifecycle, out_dir / "c4_lifecycle_coverage_all.csv")
    write_csv(evidence, out_dir / "c4_metric_evidence_all.csv")
    write_csv(rubric, out_dir / "c4_longterm_rubric_all.csv")
    write_csv(scores, out_dir / "c4_longterm_scores_all.csv")
    write_csv(summary, out_dir / "c4_longterm_summary_all.csv")
    plot_summary(summary, fig_dirs)
    write_log(log_path, lifecycle, evidence, rubric, scores, summary)

    print(f"Wrote C4 long-term suitability outputs to {out_dir}")
    print(f"Wrote C4 figure to {', '.join(str(path) for path in fig_dirs)}")
    print(f"Wrote log to {log_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
