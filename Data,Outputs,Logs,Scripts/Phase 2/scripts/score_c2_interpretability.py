#!/usr/bin/env python3
"""Generate Month 3 / Phase II C2 interpretability scoring artifacts.

C2 is partly qualitative, but the scoring should still be explicit and
reproducible. This script writes the fixed rubric, per-dimension scores, summary
scores, and a simple report figure from the predefined candidate definitions.
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
        "dimension_id": "C2_D1",
        "dimension": "Semantic clarity",
        "max_score": 2,
        "description": "Whether the metric has a plain and stable meaning.",
    },
    {
        "dimension_id": "C2_D2",
        "dimension": "Unit clarity",
        "max_score": 2,
        "description": "Whether the unit can be explained without ambiguity.",
    },
    {
        "dimension_id": "C2_D3",
        "dimension": "Normalization clarity",
        "max_score": 2,
        "description": "Whether normalization improves comparison without obscuring meaning.",
    },
    {
        "dimension_id": "C2_D4",
        "dimension": "Tooling transparency",
        "max_score": 2,
        "description": "Whether extraction can be reproduced from explicit inputs.",
    },
    {
        "dimension_id": "C2_D5",
        "dimension": "Reputation explanation fit",
        "max_score": 2,
        "description": "Whether the metric can support a developer-reputation explanation.",
    },
]


SCORES = [
    {
        "metric_id": "M1",
        "metric_name": "Snapshot size (LOC/SLOC)",
        "implementation_status": "implemented",
        "dimension_scores": {
            "C2_D1": (
                2,
                "The concept is plain: the codebase size at a frozen release tag.",
            ),
            "C2_D2": (
                2,
                "The unit is directly countable as lines or KLOC.",
            ),
            "C2_D3": (
                2,
                "It is mostly used as context or a denominator, so the normalization role is simple.",
            ),
            "C2_D4": (
                2,
                "The value is reproducible from frozen tags and the explicit source-extension policy.",
            ),
            "C2_D5": (
                0,
                "It describes project size, not an individual developer's reputation or contribution quality.",
            ),
        },
    },
    {
        "metric_id": "M2",
        "metric_name": "Patch complexity proxy (churn)",
        "implementation_status": "implemented",
        "dimension_scores": {
            "C2_D1": (
                2,
                "Added, deleted, and changed lines have an intuitive interpretation as change magnitude.",
            ),
            "C2_D2": (
                2,
                "The base unit is lines changed, which is easy to inspect and aggregate.",
            ),
            "C2_D3": (
                1,
                "Per-day and per-KLOC-day forms help comparison but require careful explanation.",
            ),
            "C2_D4": (
                2,
                "The value is reproducible from Git diff evidence over frozen windows.",
            ),
            "C2_D5": (
                1,
                "It is a useful effort signal, but high churn does not necessarily mean high-quality work.",
            ),
        },
    },
    {
        "metric_id": "M3",
        "metric_name": "Activity cadence",
        "implementation_status": "implemented",
        "dimension_scores": {
            "C2_D1": (
                2,
                "Commit frequency and active days have a clear continuity meaning.",
            ),
            "C2_D2": (
                2,
                "Commits, active days, and commits/day are familiar units.",
            ),
            "C2_D3": (
                2,
                "Per-day normalization is direct and aligns with uneven release-window duration.",
            ),
            "C2_D4": (
                2,
                "The fields are reproducible from commit timestamps and frozen release windows.",
            ),
            "C2_D5": (
                1,
                "It supports continuity claims, but activity alone does not prove maintainership quality.",
            ),
        },
    },
    {
        "metric_id": "M4",
        "metric_name": "Ownership / concentration",
        "implementation_status": "implemented",
        "dimension_scores": {
            "C2_D1": (
                1,
                "Ownership share is intuitive, but Gini and concentration need a short explanation.",
            ),
            "C2_D2": (
                1,
                "Shares are clear, while Gini is less immediately readable to a non-specialist.",
            ),
            "C2_D3": (
                2,
                "Within-window shares give a clear scale-free comparison across projects.",
            ),
            "C2_D4": (
                1,
                "The metric is reproducible, but it depends on identity canonicalization and aggregation choices.",
            ),
            "C2_D5": (
                2,
                "It maps well to maintainer responsibility and sustained influence within a project.",
            ),
        },
    },
    {
        "metric_id": "M5",
        "metric_name": "Maintenance responsiveness",
        "implementation_status": "design_extension",
        "dimension_scores": {
            "C2_D1": (
                2,
                "Responsiveness is conceptually clear as time to react to maintenance events.",
            ),
            "C2_D2": (
                1,
                "Time-to-response units are clear, but the event boundary must be defined.",
            ),
            "C2_D3": (
                1,
                "Normalization would depend on issue volume, severity, and project workflow.",
            ),
            "C2_D4": (
                0,
                "The current Phase I evidence does not include issue or pull-request event data.",
            ),
            "C2_D5": (
                2,
                "If collected, it would map strongly to maintenance reputation.",
            ),
        },
    },
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", default=Path("out"), type=Path)
    parser.add_argument("--fig-dir", default=Path("figures"), type=Path)
    parser.add_argument("--report-fig-dir", default=None, type=Path)
    parser.add_argument(
        "--log",
        default=Path("logs/c2_interpretability_20260508.log"),
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
        return "clear"
    if score == 1:
        return "partial"
    return "weak"


def interpretability_band(normalized_score: float) -> str:
    if normalized_score >= 0.8:
        return "high"
    if normalized_score >= 0.5:
        return "medium"
    return "low"


def build_rubric() -> pd.DataFrame:
    return pd.DataFrame(DIMENSIONS)


def build_scores() -> pd.DataFrame:
    rows: list[dict] = []
    dimension_lookup = {item["dimension_id"]: item for item in DIMENSIONS}
    for metric in SCORES:
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
    metric_order = {metric["metric_id"]: index for index, metric in enumerate(SCORES)}
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
                "interpretability_band": interpretability_band(normalized),
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


def decision_note(metric_id: str, status: str) -> str:
    if status == "design_extension":
        return "Keep as a documented extension; exclude from current empirical PoC decision."
    if metric_id == "M1":
        return "Use mainly as context and normalization support."
    if metric_id == "M2":
        return "Retain as an interpretable effort signal, with quality and volatility caveats."
    if metric_id == "M3":
        return "Retain as the clearest activity-continuity signal."
    if metric_id == "M4":
        return "Retain as reputation-relevant but explain carefully because concentration statistics are less immediate."
    return "Retain for comparison."


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
    axis.set_xlabel("C2 interpretability score (0-10)")
    axis.set_title("C2 interpretability scores by metric")
    axis.grid(axis="x", linestyle=":", alpha=0.45)
    for index, value in enumerate(plot_data["total_score"]):
        axis.text(value + 0.12, index, f"{value}/10", va="center", fontsize=9)
    axis.invert_yaxis()
    fig.tight_layout()

    for fig_dir in fig_dirs:
        ensure_dir(fig_dir)
        fig.savefig(fig_dir / "c2_interpretability_scores.pdf", bbox_inches="tight")
    plt.close(fig)


def write_log(
    path: Path,
    rubric: pd.DataFrame,
    scores: pd.DataFrame,
    summary: pd.DataFrame,
) -> None:
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    lines = [
        f"[{stamp}] c2_interpretability_scoring=completed",
        f"[{stamp}] rubric_dimensions={len(rubric)}",
        f"[{stamp}] score_rows={len(scores)}",
        f"[{stamp}] summary_rows={len(summary)}",
        f"[{stamp}] implemented_metrics={','.join(metric['metric_id'] for metric in SCORES if metric['implementation_status'] == 'implemented')}",
        f"[{stamp}] design_extension_metrics={','.join(metric['metric_id'] for metric in SCORES if metric['implementation_status'] == 'design_extension')}",
        f"[{stamp}] result=derived_c2_interpretability_tables_and_figure_written",
    ]
    ensure_parent(path)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    args = parse_args()
    base_dir = Path.cwd()
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

    rubric = build_rubric()
    scores = build_scores()
    summary = build_summary(scores)

    write_csv(rubric, out_dir / "c2_interpretability_rubric_all.csv")
    write_csv(scores, out_dir / "c2_interpretability_scores_all.csv")
    write_csv(summary, out_dir / "c2_interpretability_summary_all.csv")
    plot_summary(summary, fig_dirs)
    write_log(log_path, rubric, scores, summary)

    print(f"Wrote C2 interpretability outputs to {out_dir}")
    print(f"Wrote C2 figure to {', '.join(str(path) for path in fig_dirs)}")
    print(f"Wrote log to {log_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
