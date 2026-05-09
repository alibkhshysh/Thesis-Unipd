#!/usr/bin/env python3
"""Generate Phase II smart-contract feasibility scoring artifacts.

This step combines the completed C1--C4 comparative evidence with the
predefined smart-contract feasibility rubric. The output does not rely on a
new metric definition; it records the decision inputs needed before selecting a
single proof-of-concept metric.
"""

from __future__ import annotations

import argparse
import datetime as dt
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import pandas as pd


METRICS = [
    {
        "metric_id": "M1",
        "metric_name": "Snapshot size (LOC/SLOC)",
        "implementation_status": "implemented",
        "decision_role": "context_only",
        "eligibility_note": "Useful as context and normalization support, but not a standalone developer-reputation metric.",
    },
    {
        "metric_id": "M2",
        "metric_name": "Patch complexity proxy (churn)",
        "implementation_status": "implemented",
        "decision_role": "eligible_supporting_candidate",
        "eligibility_note": "Eligible as an effort signal only when interpreted with volatility and gaming safeguards.",
    },
    {
        "metric_id": "M3",
        "metric_name": "Activity cadence",
        "implementation_status": "implemented",
        "decision_role": "eligible_candidate",
        "eligibility_note": "Eligible as a compact continuity signal, but requires churn and bot-sensitivity checks.",
    },
    {
        "metric_id": "M4",
        "metric_name": "Ownership / concentration",
        "implementation_status": "implemented",
        "decision_role": "eligible_candidate",
        "eligibility_note": "Eligible as the strongest implemented reputation-oriented signal, with identity caveats.",
    },
    {
        "metric_id": "M5",
        "metric_name": "Maintenance responsiveness",
        "implementation_status": "design_extension",
        "decision_role": "design_extension_excluded",
        "eligibility_note": "Excluded from the current PoC decision because issue and pull-request event evidence was not collected.",
    },
]


FEASIBILITY_DIMENSIONS = [
    {
        "dimension_id": "D1",
        "dimension": "Determinism of computation",
        "max_score": 2,
        "exclusion_sensitive": True,
        "description": "Whether the metric is deterministic given pinned artifacts, windows, tool versions, and parameters.",
    },
    {
        "dimension_id": "D2",
        "dimension": "Bounded on-chain computation",
        "max_score": 2,
        "exclusion_sensitive": False,
        "description": "Whether contract-side logic remains constant-time or otherwise tightly bounded.",
    },
    {
        "dimension_id": "D3",
        "dimension": "Bounded on-chain storage growth",
        "max_score": 2,
        "exclusion_sensitive": False,
        "description": "Whether on-chain state can stay compact as histories grow.",
    },
    {
        "dimension_id": "D4",
        "dimension": "Update frequency feasibility",
        "max_score": 2,
        "exclusion_sensitive": True,
        "description": "Whether updates can be made per release or batched window rather than high-frequency events.",
    },
    {
        "dimension_id": "D5",
        "dimension": "External data/oracle dependence",
        "max_score": 2,
        "exclusion_sensitive": True,
        "description": "Whether inputs are hash-anchored artifacts or signed attestations rather than unverifiable services.",
    },
    {
        "dimension_id": "D6",
        "dimension": "Auditability and re-checking",
        "max_score": 2,
        "exclusion_sensitive": True,
        "description": "Whether third parties can recompute and compare the metric from public committed evidence.",
    },
    {
        "dimension_id": "D7",
        "dimension": "Identity binding and provenance",
        "max_score": 2,
        "exclusion_sensitive": False,
        "description": "Whether metric evidence is bound to a stable developer identity and provenance path.",
    },
    {
        "dimension_id": "D8",
        "dimension": "Integrity of artifact linkage",
        "max_score": 2,
        "exclusion_sensitive": True,
        "description": "Whether archive hashes, version identifiers, and evidence records prevent artifact substitution.",
    },
    {
        "dimension_id": "D9",
        "dimension": "Metric-value representation",
        "max_score": 2,
        "exclusion_sensitive": False,
        "description": "Whether the metric can be encoded as bounded integers or fixed-point values.",
    },
    {
        "dimension_id": "D10",
        "dimension": "Adversarial resilience",
        "max_score": 2,
        "exclusion_sensitive": False,
        "description": "Whether the metric resists low-cost manipulation in a public-ledger context.",
    },
]


FEASIBILITY_SCORES = [
    {
        "metric_id": "M1",
        "implementation_story": (
            "The off-chain verifier counts source lines for a pinned release artifact and stores a compact "
            "integer value plus evidence hash on-chain."
        ),
        "dimension_scores": {
            "D1": (2, "Deterministic when the source-extension policy and tool version are pinned."),
            "D2": (2, "The contract stores and checks commitments; line counting stays off-chain."),
            "D3": (2, "Only a compact line-count value, metadata, and evidence hash need to be stored."),
            "D4": (2, "A per-release update cadence is sufficient."),
            "D5": (2, "The input is the hash-pinned artifact rather than an unverifiable external service."),
            "D6": (2, "Auditors can retrieve the artifact, verify the hash, and recompute the line count."),
            "D7": (1, "The submission can be signed, but project size is not developer-specific attribution."),
            "D8": (2, "Artifact hash and version metadata provide a strong linkage path."),
            "D9": (2, "The metric is stored as bounded integer line counts or KLOC fixed-point values."),
            "D10": (1, "Size can be inflated with low-value code, so it is safe only as context."),
        },
    },
    {
        "metric_id": "M2",
        "implementation_story": (
            "The off-chain verifier computes added and deleted lines for a pinned release window, then stores "
            "compact churn aggregates and an evidence hash."
        ),
        "dimension_scores": {
            "D1": (2, "Deterministic from frozen tags, hashes, diff policy, and tool version."),
            "D2": (2, "Diff computation remains off-chain; the contract records bounded values."),
            "D3": (1, "Window totals are compact, but developer-level histories can grow with contributor count."),
            "D4": (2, "Release-window updates avoid per-commit writes."),
            "D5": (1, "The metric needs release-window history and previous artifacts, but those inputs can be hash-anchored."),
            "D6": (2, "Auditors can replay the window diff from pinned release evidence."),
            "D7": (1, "Developer attribution depends on commit-author mapping and canonicalization rules."),
            "D8": (2, "Frozen tags and artifact hashes give a strong integrity boundary."),
            "D9": (2, "Added, deleted, and churn values are integer counts; rates can be fixed-point."),
            "D10": (1, "Artificial churn is possible, so safeguards from C3 remain necessary."),
        },
    },
    {
        "metric_id": "M3",
        "implementation_story": (
            "The off-chain verifier counts human-only commits and active days for a pinned release window, "
            "then stores compact cadence values and an evidence hash."
        ),
        "dimension_scores": {
            "D1": (2, "Deterministic from frozen window boundaries, commit timestamps, and bot-handling policy."),
            "D2": (2, "Commit traversal is off-chain; the contract stores only compact values."),
            "D3": (2, "Commit counts, active-day counts, and normalized rates are compact records."),
            "D4": (2, "Release-window batching avoids high-frequency per-commit ledger writes."),
            "D5": (1, "The metric depends on Git history, but the history can be pinned through archived evidence."),
            "D6": (2, "Auditors can replay the commit-window extraction from the pinned repository evidence."),
            "D7": (1, "Identity binding depends on author canonicalization and the submission identity model."),
            "D8": (2, "Frozen tags, hashes, and evidence reports support artifact linkage."),
            "D9": (2, "Counts and per-day rates can be represented as integers or fixed-point values."),
            "D10": (1, "Commit splitting is cheap, so cadence needs C3 safeguards."),
        },
    },
    {
        "metric_id": "M4",
        "implementation_story": (
            "The off-chain verifier computes contributor ownership shares and concentration statistics for a "
            "pinned release window, then stores compact share or concentration values plus evidence hash."
        ),
        "dimension_scores": {
            "D1": (2, "Deterministic when identity canonicalization and aggregation rules are pinned."),
            "D2": (2, "Share and Gini calculations stay off-chain; contract work is bounded record storage."),
            "D3": (1, "Summary values are compact, but full developer-share evidence grows with contributors."),
            "D4": (2, "Release-window updates are feasible and avoid per-event writes."),
            "D5": (1, "The metric needs Git history and identity canonicalization, but both can be documented and hash-anchored."),
            "D6": (2, "Auditors can replay the ownership calculation from pinned release evidence and the canonicalization policy."),
            "D7": (1, "Identity binding is the main caveat because commit authors and signed submitters may not always align."),
            "D8": (2, "Frozen tags, hashes, and evidence reports provide strong artifact linkage."),
            "D9": (1, "Shares and Gini values require fixed-point scaling or numerator-denominator storage."),
            "D10": (2, "Sustained ownership is harder to manipulate than isolated churn or commit counts."),
        },
    },
    {
        "metric_id": "M5",
        "implementation_story": (
            "A future verifier would compute response times from issue and pull-request event streams, but those "
            "events are not present in the current Phase I evidence."
        ),
        "dimension_scores": {
            "D1": (1, "Determinism depends on defining event boundaries, response semantics, and workflow rules."),
            "D2": (2, "A hybrid design could keep event analysis off-chain and store compact values."),
            "D3": (1, "Aggregates are compact, but raw event histories can grow quickly."),
            "D4": (1, "Issue and pull-request events can be batched, but they are more frequent than release windows."),
            "D5": (0, "Current evidence would depend on external platform event data without a validated attestation model."),
            "D6": (0, "The current dataset cannot support replay or re-checking for responsiveness."),
            "D7": (1, "Platform identities would need mapping to developer submissions."),
            "D8": (1, "Event artifact pinning is not yet specified."),
            "D9": (2, "Response times can be stored as integer durations."),
            "D10": (1, "Fast superficial replies can game response-time metrics."),
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
        default=Path("logs/feasibility_scoring_20260509.log"),
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


def score_label(score: int) -> str:
    if score == 2:
        return "strong"
    if score == 1:
        return "partial"
    return "weak"


def band(score_0_to_10: float) -> str:
    if score_0_to_10 >= 8:
        return "high"
    if score_0_to_10 >= 5:
        return "medium"
    return "low"


def build_c1_scores(out_dir: Path) -> pd.DataFrame:
    stability = read_csv(out_dir / "c1_metric_stability_overall_all.csv")
    rows: list[dict] = []
    for metric_id in ["M1", "M2", "M3"]:
        subset = stability[stability["metric_family"] == metric_id]
        if subset.empty:
            raise ValueError(f"Missing C1 stability row for {metric_id}")
        row = subset.iloc[0]
        high_vol_projects = float(row["primary_high_volatility_projects"])
        score = max(0.0, 10.0 - high_vol_projects)
        rows.append(
            {
                "metric_id": metric_id,
                "c1_stability_score": score,
                "c1_basis": (
                    f"{row['metric_label']}; score = 10 - primary high-volatility projects "
                    f"({int(high_vol_projects)} of {int(row['projects'])})"
                ),
            }
        )

    m4_subset = stability[stability["metric_family"] == "M4"].copy()
    if len(m4_subset) != 2:
        raise ValueError("Expected two M4 C1 stability rows")
    m4_scores = 10.0 - m4_subset["primary_high_volatility_projects"].astype(float)
    rows.append(
        {
            "metric_id": "M4",
            "c1_stability_score": float(m4_scores.mean()),
            "c1_basis": (
                "Average of M4 churn Gini and M4 top-1 churn share stability; "
                f"primary high-volatility projects = {', '.join(str(int(value)) for value in m4_subset['primary_high_volatility_projects'])}"
            ),
        }
    )
    rows.append(
        {
            "metric_id": "M5",
            "c1_stability_score": 0.0,
            "c1_basis": "No current Phase I issue/PR event evidence for responsiveness stability.",
        }
    )
    return pd.DataFrame(rows)


def build_comparative_summary(out_dir: Path) -> pd.DataFrame:
    metric_rows = pd.DataFrame(METRICS)
    c1 = build_c1_scores(out_dir)
    c2 = read_csv(out_dir / "c2_interpretability_summary_all.csv")[
        ["metric_id", "total_score", "interpretability_band"]
    ].rename(
        columns={
            "total_score": "c2_interpretability_score",
            "interpretability_band": "c2_band",
        }
    )
    c3 = read_csv(out_dir / "c3_gaming_summary_all.csv")[
        ["metric_id", "total_score", "gaming_resistance_band"]
    ].rename(
        columns={
            "total_score": "c3_gaming_resistance_score",
            "gaming_resistance_band": "c3_band",
        }
    )
    c4 = read_csv(out_dir / "c4_longterm_summary_all.csv")[
        ["metric_id", "total_score", "longterm_suitability_band"]
    ].rename(
        columns={
            "total_score": "c4_longterm_suitability_score",
            "longterm_suitability_band": "c4_band",
        }
    )

    result = metric_rows.merge(c1, on="metric_id").merge(c2, on="metric_id").merge(
        c3, on="metric_id"
    ).merge(c4, on="metric_id")
    score_columns = [
        "c1_stability_score",
        "c2_interpretability_score",
        "c3_gaming_resistance_score",
        "c4_longterm_suitability_score",
    ]
    for column in score_columns:
        result[column] = pd.to_numeric(result[column], errors="raise")
    result["empirical_average_score"] = result[score_columns].mean(axis=1)
    result["empirical_band"] = result["empirical_average_score"].map(band)
    result["_metric_order"] = result["metric_id"].map(
        {metric["metric_id"]: index for index, metric in enumerate(METRICS)}
    )
    result.sort_values("_metric_order", inplace=True)
    result.drop(columns=["_metric_order"], inplace=True)
    return result


def build_feasibility_rubric() -> pd.DataFrame:
    return pd.DataFrame(FEASIBILITY_DIMENSIONS)


def build_feasibility_scores() -> pd.DataFrame:
    metric_lookup = {metric["metric_id"]: metric for metric in METRICS}
    dimension_lookup = {item["dimension_id"]: item for item in FEASIBILITY_DIMENSIONS}
    rows: list[dict] = []
    for metric in FEASIBILITY_SCORES:
        metric_meta = metric_lookup[metric["metric_id"]]
        for dimension_id, (score, rationale) in metric["dimension_scores"].items():
            dimension = dimension_lookup[dimension_id]
            rows.append(
                {
                    "metric_id": metric["metric_id"],
                    "metric_name": metric_meta["metric_name"],
                    "implementation_status": metric_meta["implementation_status"],
                    "decision_role": metric_meta["decision_role"],
                    "dimension_id": dimension_id,
                    "dimension": dimension["dimension"],
                    "score": score,
                    "max_score": dimension["max_score"],
                    "score_label": score_label(score),
                    "exclusion_sensitive": dimension["exclusion_sensitive"],
                    "rationale": rationale,
                }
            )
    return pd.DataFrame(rows)


def exclusion_conditions(group: pd.DataFrame) -> str:
    score_by_dim = dict(zip(group["dimension_id"], group["score"]))
    exclusions: list[str] = []
    if any(score_by_dim.get(dim, 2) == 0 for dim in ["D1", "D6", "D8"]):
        exclusions.append("A")
    if score_by_dim.get("D4", 2) == 0:
        exclusions.append("B")
    if score_by_dim.get("D5", 2) == 0:
        exclusions.append("C")
    return ";".join(exclusions) if exclusions else "none"


def build_feasibility_summary(scores: pd.DataFrame) -> pd.DataFrame:
    metric_lookup = {metric["metric_id"]: metric for metric in METRICS}
    story_lookup = {
        metric["metric_id"]: metric["implementation_story"] for metric in FEASIBILITY_SCORES
    }
    rows: list[dict] = []
    for (metric_id, metric_name, status, role), group in scores.groupby(
        ["metric_id", "metric_name", "implementation_status", "decision_role"],
        sort=True,
    ):
        total = int(group["score"].sum())
        max_total = int(group["max_score"].sum())
        normalized = total / max_total if max_total else 0.0
        exclusions = exclusion_conditions(group)
        poc_eligible = (
            status == "implemented"
            and role != "context_only"
            and exclusions == "none"
        )
        rows.append(
            {
                "metric_id": metric_id,
                "metric_name": metric_name,
                "implementation_status": status,
                "decision_role": role,
                "total_score": total,
                "max_score": max_total,
                "normalized_score": normalized,
                "feasibility_score_0_10": normalized * 10,
                "feasibility_band": band(normalized * 10),
                "exclusion_conditions": exclusions,
                "poc_eligible_after_feasibility": poc_eligible,
                "implementation_story": story_lookup[metric_id],
                "decision_note": metric_lookup[metric_id]["eligibility_note"],
            }
        )
    result = pd.DataFrame(rows)
    result["_metric_order"] = result["metric_id"].map(
        {metric["metric_id"]: index for index, metric in enumerate(METRICS)}
    )
    result.sort_values("_metric_order", inplace=True)
    result.drop(columns=["_metric_order"], inplace=True)
    return result


def build_decision_inputs(comparative: pd.DataFrame, feasibility: pd.DataFrame) -> pd.DataFrame:
    result = comparative.merge(
        feasibility[
            [
                "metric_id",
                "feasibility_score_0_10",
                "feasibility_band",
                "exclusion_conditions",
                "poc_eligible_after_feasibility",
            ]
        ],
        on="metric_id",
    )
    result["combined_readiness_score"] = (
        result["empirical_average_score"] * 0.6
        + result["feasibility_score_0_10"] * 0.4
    )
    eligible = result["poc_eligible_after_feasibility"] == True
    result["selection_rank_among_eligible"] = ""
    ranked = result[eligible].sort_values(
        ["combined_readiness_score", "empirical_average_score", "feasibility_score_0_10"],
        ascending=False,
    )
    for rank, index in enumerate(ranked.index, start=1):
        result.at[index, "selection_rank_among_eligible"] = rank
    result["selection_status"] = result.apply(selection_status, axis=1)
    result.sort_values(
        ["poc_eligible_after_feasibility", "combined_readiness_score"],
        ascending=[False, False],
        inplace=True,
    )
    return result


def selection_status(row: pd.Series) -> str:
    if row["decision_role"] == "context_only":
        return "not_selected_context_only"
    if row["implementation_status"] == "design_extension":
        return "not_selected_no_current_evidence"
    if row["exclusion_conditions"] != "none":
        return "not_selected_feasibility_exclusion"
    if row["selection_rank_among_eligible"] == 1:
        return "preferred_for_final_selection_gate"
    return "eligible_alternative"


def write_csv(df: pd.DataFrame, path: Path) -> None:
    ensure_parent(path)
    df.to_csv(path, index=False, float_format="%.3f")


def plot_feasibility(summary: pd.DataFrame, fig_dirs: list[Path]) -> None:
    plot_data = summary.sort_values("feasibility_score_0_10", ascending=True)
    colors = [
        "#4c78a8" if eligible else "#9e9e9e"
        for eligible in plot_data["poc_eligible_after_feasibility"]
    ]
    fig, axis = plt.subplots(figsize=(9, 4.8))
    labels = plot_data["metric_id"] + " " + plot_data["metric_name"]
    axis.barh(labels, plot_data["feasibility_score_0_10"], color=colors)
    axis.set_xlim(0, 10)
    axis.set_xlabel("Smart-contract feasibility score (0-10)")
    axis.set_title("Smart-contract feasibility by metric")
    axis.grid(axis="x", linestyle=":", alpha=0.45)
    for index, value in enumerate(plot_data["feasibility_score_0_10"]):
        axis.text(value + 0.12, index, f"{value:.1f}", va="center", fontsize=9)
    fig.tight_layout()
    for fig_dir in fig_dirs:
        ensure_dir(fig_dir)
        fig.savefig(fig_dir / "feasibility_scores.pdf", bbox_inches="tight")
    plt.close(fig)


def plot_decision_inputs(decision: pd.DataFrame, fig_dirs: list[Path]) -> None:
    plot_data = decision.sort_values("combined_readiness_score", ascending=True)
    fig, axis = plt.subplots(figsize=(9.5, 5.2))
    y_positions = range(len(plot_data))
    axis.scatter(
        plot_data["empirical_average_score"],
        y_positions,
        label="C1-C4 empirical average",
        color="#4c78a8",
        s=55,
    )
    axis.scatter(
        plot_data["feasibility_score_0_10"],
        y_positions,
        label="Feasibility",
        color="#f58518",
        s=55,
    )
    axis.scatter(
        plot_data["combined_readiness_score"],
        y_positions,
        label="Combined readiness",
        color="#54a24b",
        s=55,
    )
    axis.set_yticks(list(y_positions))
    axis.set_yticklabels(plot_data["metric_id"] + " " + plot_data["metric_name"])
    axis.set_xlim(0, 10)
    axis.set_xlabel("Score (0-10)")
    axis.set_title("Empirical and feasibility decision inputs")
    axis.grid(axis="x", linestyle=":", alpha=0.45)
    axis.legend(loc="lower right", fontsize=8)
    fig.tight_layout()
    for fig_dir in fig_dirs:
        ensure_dir(fig_dir)
        fig.savefig(fig_dir / "poc_candidate_readiness_scores.pdf", bbox_inches="tight")
    plt.close(fig)


def write_log(
    path: Path,
    comparative: pd.DataFrame,
    rubric: pd.DataFrame,
    scores: pd.DataFrame,
    summary: pd.DataFrame,
    decision: pd.DataFrame,
) -> None:
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    eligible = decision[decision["poc_eligible_after_feasibility"] == True]
    preferred = eligible.sort_values("selection_rank_among_eligible").iloc[0]
    lines = [
        f"[{stamp}] smart_contract_feasibility_scoring=completed",
        f"[{stamp}] comparative_metric_rows={len(comparative)}",
        f"[{stamp}] feasibility_dimensions={len(rubric)}",
        f"[{stamp}] feasibility_score_rows={len(scores)}",
        f"[{stamp}] feasibility_summary_rows={len(summary)}",
        f"[{stamp}] decision_input_rows={len(decision)}",
        f"[{stamp}] poc_eligible_metrics={','.join(eligible['metric_id'].tolist())}",
        f"[{stamp}] preferred_for_final_selection_gate={preferred['metric_id']}",
        f"[{stamp}] result=derived_feasibility_and_decision_input_tables_written",
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

    comparative = build_comparative_summary(out_dir)
    rubric = build_feasibility_rubric()
    scores = build_feasibility_scores()
    summary = build_feasibility_summary(scores)
    decision = build_decision_inputs(comparative, summary)

    write_csv(comparative, out_dir / "phase2_metric_comparison_all.csv")
    write_csv(rubric, out_dir / "feasibility_rubric_all.csv")
    write_csv(scores, out_dir / "feasibility_scores_all.csv")
    write_csv(summary, out_dir / "feasibility_summary_all.csv")
    write_csv(decision, out_dir / "poc_candidate_decision_inputs_all.csv")
    plot_feasibility(summary, fig_dirs)
    plot_decision_inputs(decision, fig_dirs)
    write_log(log_path, comparative, rubric, scores, summary, decision)

    print(f"Wrote feasibility outputs to {out_dir}")
    print(f"Wrote feasibility figures to {', '.join(str(path) for path in fig_dirs)}")
    print(f"Wrote log to {log_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
