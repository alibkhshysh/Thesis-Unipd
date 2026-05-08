#!/usr/bin/env python3
"""Generate Month 3 / Phase II C3 gaming-resistance artifacts.

C3 compares how each candidate metric can be manipulated, whether manipulation
is costly, and whether the current evidence base can detect suspicious patterns.
Scores are explicit and reproducible so the qualitative assessment remains
auditable.
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
        "dimension_id": "C3_D1",
        "dimension": "Manipulation difficulty",
        "max_score": 2,
        "description": "How difficult it is to artificially improve the metric.",
    },
    {
        "dimension_id": "C3_D2",
        "dimension": "Manipulation cost",
        "max_score": 2,
        "description": "How much real work or coordination manipulation requires.",
    },
    {
        "dimension_id": "C3_D3",
        "dimension": "Detectability from current evidence",
        "max_score": 2,
        "description": "Whether manipulation can be flagged from existing Phase I artifacts.",
    },
    {
        "dimension_id": "C3_D4",
        "dimension": "Cross-metric consistency",
        "max_score": 2,
        "description": "Whether the metric can be checked against other candidate signals.",
    },
    {
        "dimension_id": "C3_D5",
        "dimension": "Residual-risk control",
        "max_score": 2,
        "description": "Whether remaining gaming risk is acceptable after safeguards.",
    },
]


METRIC_SCORES = [
    {
        "metric_id": "M1",
        "metric_name": "Snapshot size (LOC/SLOC)",
        "implementation_status": "implemented",
        "dimension_scores": {
            "C3_D1": (1, "Project size can be inflated by adding low-value code."),
            "C3_D2": (1, "Inflating size requires code changes, but not necessarily useful changes."),
            "C3_D3": (1, "Large size jumps are visible through LOC and churn, but intent is hard to infer."),
            "C3_D4": (1, "Can be checked against churn and window duration, but weakly against developer value."),
            "C3_D5": (1, "Safe as context or denominator, risky as a standalone reputation signal."),
        },
    },
    {
        "metric_id": "M2",
        "metric_name": "Patch complexity proxy (churn)",
        "implementation_status": "implemented",
        "dimension_scores": {
            "C3_D1": (1, "Churn can be increased through unnecessary rewrites or formatting-heavy changes."),
            "C3_D2": (1, "Manipulation costs some repository activity but can be cheaper than meaningful maintenance."),
            "C3_D3": (2, "High churn with weak commit cadence or concentrated ownership is visible in current outputs."),
            "C3_D4": (2, "Can be checked against M3 cadence, M4 concentration, LOC deltas, and short-window flags."),
            "C3_D5": (1, "Useful as effort evidence, but unsafe as a direct quality or reputation proxy alone."),
        },
    },
    {
        "metric_id": "M3",
        "metric_name": "Activity cadence",
        "implementation_status": "implemented",
        "dimension_scores": {
            "C3_D1": (0, "Commit counts can be inflated by splitting work into many small commits."),
            "C3_D2": (1, "Sustained active days require some continuity, but commit splitting remains cheap."),
            "C3_D3": (2, "Commit/churn imbalance and bot-sensitive rows are visible in current outputs."),
            "C3_D4": (2, "Can be checked against churn magnitude, active days, ownership shares, and bot summaries."),
            "C3_D5": (1, "Good for continuity evidence, but vulnerable if read without churn and ownership context."),
        },
    },
    {
        "metric_id": "M4",
        "metric_name": "Ownership / concentration",
        "implementation_status": "implemented",
        "dimension_scores": {
            "C3_D1": (2, "Sustained ownership share is harder to fake than isolated commits or churn spikes."),
            "C3_D2": (2, "Manipulation usually requires controlling a large share of project activity over a window."),
            "C3_D3": (2, "Top-1/top-3 shares and Gini expose concentration spikes and dominance patterns."),
            "C3_D4": (2, "Can be checked against M2 churn, M3 cadence, bot flags, and developer-share rows."),
            "C3_D5": (1, "Residual risk remains for coordinated or review-light dominance, so it needs context."),
        },
    },
    {
        "metric_id": "M5",
        "metric_name": "Maintenance responsiveness",
        "implementation_status": "design_extension",
        "dimension_scores": {
            "C3_D1": (1, "Fast shallow replies can improve apparent responsiveness without resolving issues."),
            "C3_D2": (1, "Manipulation requires interaction with issue/PR workflows but may not require code work."),
            "C3_D3": (0, "Current Phase I evidence does not include issue or pull-request event streams."),
            "C3_D4": (0, "Current artifacts cannot cross-check response quality or event severity."),
            "C3_D5": (1, "Potentially useful later, but current evidence cannot control gaming risk."),
        },
    },
]


ATTACK_SURFACE = [
    {
        "metric_id": "M1",
        "attack_vector": "Add low-value or generated source files to increase apparent project size.",
        "current_detectability": "medium",
        "evidence_fields": "loc_per_tag_all.code_lines; metrics_window_totals_human_all.total_churn",
        "recommended_safeguard": "Use M1 only as context or normalization, not as direct reputation evidence.",
    },
    {
        "metric_id": "M1",
        "attack_vector": "Large formatting or vendoring changes alter size without improving maintainership.",
        "current_detectability": "medium",
        "evidence_fields": "loc_per_tag_all; churn_per_kloc_day; window_duration_flags_all",
        "recommended_safeguard": "Flag large LOC jumps and interpret them with churn and release-window context.",
    },
    {
        "metric_id": "M2",
        "attack_vector": "Inflate churn through unnecessary rewrites or formatting-only commits.",
        "current_detectability": "high",
        "evidence_fields": "metrics_window_dev_human_all.churn; churn_per_kloc_day; ownership_dev_shares_human_all.share_churn",
        "recommended_safeguard": "Do not reward churn alone; compare against cadence, ownership concentration, and short-window flags.",
    },
    {
        "metric_id": "M2",
        "attack_vector": "Concentrate a large churn spike in a short release window.",
        "current_detectability": "high",
        "evidence_fields": "window_duration_flags_all.analysis_set; churn_per_day; top1_share_churn",
        "recommended_safeguard": "Report robust results excluding sensitivity-only windows and inspect top-contributor shares.",
    },
    {
        "metric_id": "M3",
        "attack_vector": "Split one logical change into many commits to inflate cadence.",
        "current_detectability": "high",
        "evidence_fields": "commits_per_day; churn_per_day; active_days_per_window_day",
        "recommended_safeguard": "Compare commits/day with churn/day and active-day coverage before interpreting activity.",
    },
    {
        "metric_id": "M3",
        "attack_vector": "Use automation or bot-like activity to inflate commit/activity counts.",
        "current_detectability": "high",
        "evidence_fields": "is_bot; bot_summary_by_project_all; bot_summary_by_window_all",
        "recommended_safeguard": "Use human-only M3 outputs as primary evidence and retain bot summaries as sensitivity checks.",
    },
    {
        "metric_id": "M4",
        "attack_vector": "Create dominance through one large churn event rather than sustained responsibility.",
        "current_detectability": "high",
        "evidence_fields": "top1_share_churn; gini_churn; churn_per_kloc_day",
        "recommended_safeguard": "Interpret high concentration with churn magnitude, window duration, and adjacent-window stability.",
    },
    {
        "metric_id": "M4",
        "attack_vector": "Coordinate identities or aliases to change apparent ownership distribution.",
        "current_detectability": "medium",
        "evidence_fields": "canonical author_email; ownership_dev_shares_human_all; clean_all_metrics.log",
        "recommended_safeguard": "Keep identity canonicalization explicit and report residual identity-linkage risk.",
    },
    {
        "metric_id": "M5",
        "attack_vector": "Post quick superficial replies to improve response time without resolving maintenance work.",
        "current_detectability": "low",
        "evidence_fields": "Not available in current Phase I artifacts.",
        "recommended_safeguard": "Do not select M5 for the baseline PoC without issue/PR event data and response-quality rules.",
    },
    {
        "metric_id": "M5",
        "attack_vector": "Selectively respond to easy events while ignoring difficult issues.",
        "current_detectability": "low",
        "evidence_fields": "Not available in current Phase I artifacts.",
        "recommended_safeguard": "Require event severity, closure, and sampling rules before using responsiveness.",
    },
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", default=Path("out"), type=Path)
    parser.add_argument("--fig-dir", default=Path("figures"), type=Path)
    parser.add_argument("--report-fig-dir", default=None, type=Path)
    parser.add_argument(
        "--log",
        default=Path("logs/c3_gaming_resistance_20260508.log"),
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


def resistance_band(normalized_score: float) -> str:
    if normalized_score >= 0.8:
        return "high"
    if normalized_score >= 0.5:
        return "medium"
    return "low"


def decision_note(metric_id: str, status: str) -> str:
    if status == "design_extension":
        return "Exclude from current empirical decision because gaming cannot be checked from current artifacts."
    if metric_id == "M1":
        return "Safe as context only; weak as a standalone reputation signal."
    if metric_id == "M2":
        return "Retain with safeguards; do not interpret churn as quality alone."
    if metric_id == "M3":
        return "Retain with churn and bot-sensitivity cross-checks."
    if metric_id == "M4":
        return "Strongest current gaming-resistance profile, but still requires identity and dominance caveats."
    return "Retain for comparison."


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
                "gaming_resistance_band": resistance_band(normalized),
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
    axis.set_xlabel("C3 gaming-resistance score (0-10)")
    axis.set_title("C3 gaming-resistance scores by metric")
    axis.grid(axis="x", linestyle=":", alpha=0.45)
    for index, value in enumerate(plot_data["total_score"]):
        axis.text(value + 0.12, index, f"{value}/10", va="center", fontsize=9)
    axis.invert_yaxis()
    fig.tight_layout()

    for fig_dir in fig_dirs:
        ensure_dir(fig_dir)
        fig.savefig(fig_dir / "c3_gaming_resistance_scores.pdf", bbox_inches="tight")
    plt.close(fig)


def write_log(
    path: Path,
    rubric: pd.DataFrame,
    attack_surface: pd.DataFrame,
    scores: pd.DataFrame,
    summary: pd.DataFrame,
) -> None:
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    lines = [
        f"[{stamp}] c3_gaming_resistance_scoring=completed",
        f"[{stamp}] rubric_dimensions={len(rubric)}",
        f"[{stamp}] attack_surface_rows={len(attack_surface)}",
        f"[{stamp}] score_rows={len(scores)}",
        f"[{stamp}] summary_rows={len(summary)}",
        f"[{stamp}] implemented_metrics={','.join(metric['metric_id'] for metric in METRIC_SCORES if metric['implementation_status'] == 'implemented')}",
        f"[{stamp}] design_extension_metrics={','.join(metric['metric_id'] for metric in METRIC_SCORES if metric['implementation_status'] == 'design_extension')}",
        f"[{stamp}] result=derived_c3_gaming_resistance_tables_and_figure_written",
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
    attack_surface = pd.DataFrame(ATTACK_SURFACE)
    scores = build_scores()
    summary = build_summary(scores)

    write_csv(rubric, out_dir / "c3_gaming_rubric_all.csv")
    write_csv(attack_surface, out_dir / "c3_gaming_attack_surface_all.csv")
    write_csv(scores, out_dir / "c3_gaming_scores_all.csv")
    write_csv(summary, out_dir / "c3_gaming_summary_all.csv")
    plot_summary(summary, fig_dirs)
    write_log(log_path, rubric, attack_surface, scores, summary)

    print(f"Wrote C3 gaming-resistance outputs to {out_dir}")
    print(f"Wrote C3 figure to {', '.join(str(path) for path in fig_dirs)}")
    print(f"Wrote log to {log_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
