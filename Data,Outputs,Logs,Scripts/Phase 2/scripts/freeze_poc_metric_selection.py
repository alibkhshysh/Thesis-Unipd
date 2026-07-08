#!/usr/bin/env python3
"""Freeze the selected proof-of-concept metric after Phase II scoring.

This script records the final selection rationale using the already-computed
C1--C4 and smart-contract feasibility decision inputs. It does not recompute
the metric values themselves. It freezes the metric definition, analysis
policy, value encoding, evidence boundary, and supporting signals needed before
the PoC implementation starts.
"""

from __future__ import annotations

import argparse
import datetime as dt
from pathlib import Path

import pandas as pd


SELECTED_METRIC_ID = "M4"
SELECTED_SIGNAL_ID = "M4_developer_share_churn"
FIXED_POINT_SCALE = 1_000_000


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", default=Path("out"), type=Path)
    parser.add_argument(
        "--log",
        default=Path("logs/poc_metric_selection_20260708.log"),
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


def write_csv(df: pd.DataFrame, path: Path) -> None:
    ensure_parent(path)
    df.to_csv(path, index=False, float_format="%.3f")


def selected_decision_row(decision: pd.DataFrame) -> pd.Series:
    selected = decision[
        (decision["metric_id"] == SELECTED_METRIC_ID)
        & (decision["selection_status"] == "preferred_for_final_selection_gate")
    ]
    if len(selected) != 1:
        raise ValueError("Expected exactly one preferred M4 decision row.")
    return selected.iloc[0]


def build_selection(decision: pd.DataFrame, feasibility: pd.DataFrame) -> pd.DataFrame:
    row = selected_decision_row(decision)
    feasibility_row = feasibility[feasibility["metric_id"] == SELECTED_METRIC_ID].iloc[0]
    return pd.DataFrame(
        [
            {
                "selected_metric_family": row["metric_id"],
                "selected_metric_name": row["metric_name"],
                "selected_signal_id": SELECTED_SIGNAL_ID,
                "selected_signal_name": "Developer churn ownership share",
                "selection_status": "selected_for_baseline_poc",
                "selection_basis": "Highest rank among eligible metrics after combining C1-C4 evidence and smart-contract feasibility.",
                "c1_stability_score": row["c1_stability_score"],
                "c2_interpretability_score": row["c2_interpretability_score"],
                "c3_gaming_resistance_score": row["c3_gaming_resistance_score"],
                "c4_longterm_suitability_score": row["c4_longterm_suitability_score"],
                "empirical_average_score": row["empirical_average_score"],
                "feasibility_score_0_10": row["feasibility_score_0_10"],
                "combined_readiness_score": row["combined_readiness_score"],
                "feasibility_exclusion_conditions": row["exclusion_conditions"],
                "implementation_story": feasibility_row["implementation_story"],
                "primary_value_definition": "share_churn = developer_human_churn / window_total_human_churn",
                "primary_population": "human-only Git authors after bot filtering and email-based identity canonicalization",
                "primary_window_definition": "frozen consecutive semantic-version release window from data/windows_all.csv",
                "primary_source_table": "out/ownership_dev_shares_human_all.csv",
                "supporting_source_tables": "out/metrics_window_dev_human_all.csv; out/ownership_summary_human_all.csv; out/bot_summary_by_window_all.csv; out/window_duration_flags_all.csv",
            }
        ]
    )


def build_rationale(decision: pd.DataFrame) -> pd.DataFrame:
    lookup = decision.set_index("metric_id")
    rows = [
        {
            "reason_id": "R1",
            "topic": "Best eligible combined result",
            "evidence": (
                f"M4 ranks first among eligible candidates with combined readiness "
                f"{lookup.at['M4', 'combined_readiness_score']:.3f}."
            ),
            "decision_effect": "Select M4 as the baseline PoC metric family.",
        },
        {
            "reason_id": "R2",
            "topic": "Reputation meaning",
            "evidence": "M4 measures relative developer ownership in a release window rather than only project size or raw activity.",
            "decision_effect": "Use developer churn ownership share as the concrete PoC value.",
        },
        {
            "reason_id": "R3",
            "topic": "Gaming resistance",
            "evidence": f"M4 has C3 score {lookup.at['M4', 'c3_gaming_resistance_score']}/10, higher than M2 and M3.",
            "decision_effect": "Prefer M4 over metrics that can be inflated by simple churn spikes or commit splitting.",
        },
        {
            "reason_id": "R4",
            "topic": "Long-term suitability",
            "evidence": f"M4 has C4 score {lookup.at['M4', 'c4_longterm_suitability_score']}/10 and remains meaningful across project sizes through relative shares.",
            "decision_effect": "Treat M4 as suitable for incremental release-window records.",
        },
        {
            "reason_id": "R5",
            "topic": "Feasibility",
            "evidence": f"M4 has feasibility score {lookup.at['M4', 'feasibility_score_0_10']}/10 with no exclusion conditions.",
            "decision_effect": "Use a hybrid implementation: off-chain computation, compact on-chain record.",
        },
        {
            "reason_id": "R6",
            "topic": "Known caveat",
            "evidence": "M4 depends on identity canonicalization and share computation policy.",
            "decision_effect": "Store analysis policy and evidence hash; keep M2 and M3 as supporting audit signals.",
        },
    ]
    return pd.DataFrame(rows)


def build_policy() -> pd.DataFrame:
    rows = [
        {
            "policy_field": "metric_formula",
            "value": "share_churn = developer_human_churn / window_total_human_churn",
            "reason": "Measures the developer's relative ownership of changed lines in one release window.",
        },
        {
            "policy_field": "fixed_point_encoding",
            "value": f"share_churn_ppm = round(share_churn * {FIXED_POINT_SCALE})",
            "reason": "Avoids floating point values in the PoC record while preserving six decimal places.",
        },
        {
            "policy_field": "population",
            "value": "human-only rows; bot rows excluded from primary metric",
            "reason": "Developer reputation should not silently mix automation with human behavior.",
        },
        {
            "policy_field": "identity_key",
            "value": "canonical author email, optionally hashed before on-chain storage",
            "reason": "Matches the current Phase I identity-cleaning policy and avoids storing raw email on-chain.",
        },
        {
            "policy_field": "window_boundary",
            "value": "from_tag/to_tag and from_hash/to_hash from frozen windows_all.csv",
            "reason": "Makes the metric replayable from immutable release-window evidence.",
        },
        {
            "policy_field": "evidence_hash",
            "value": "hash of the off-chain evidence packet: input identifiers, analysis policy, numerator, denominator, encoded value, and supporting audit fields",
            "reason": "Allows a verifier to recompute the value and compare it with the committed record.",
        },
        {
            "policy_field": "short_window_policy",
            "value": "retain sensitivity_only flag in the evidence packet",
            "reason": "Short windows are valid audit evidence but require careful interpretation.",
        },
        {
            "policy_field": "supporting_checks",
            "value": "M2 churn magnitude, M3 activity cadence, M4 top-1/top-3/Gini, bot summaries",
            "reason": "Prevents the selected ownership share from being interpreted without context.",
        },
    ]
    return pd.DataFrame(rows)


def build_record_fields() -> pd.DataFrame:
    rows = [
        ("project_id", "string or bytes32", "Project identifier from the frozen dataset."),
        ("window_id", "string or bytes32", "Frozen release-window identifier."),
        ("developer_id_hash", "bytes32", "Hash of the canonical developer identifier used by the off-chain verifier."),
        ("metric_id", "string or bytes32", SELECTED_SIGNAL_ID),
        ("metric_value_ppm", "uint32 or uint64", f"Fixed-point share_churn scaled by {FIXED_POINT_SCALE}."),
        ("numerator_churn", "uint64", "Developer human-only churn in the selected window."),
        ("denominator_churn", "uint64", "Total human-only churn in the selected window."),
        ("from_commit_hash", "bytes20 or bytes32", "Frozen start commit hash for the release window."),
        ("to_commit_hash", "bytes20 or bytes32", "Frozen end commit hash for the release window."),
        ("analysis_policy_hash", "bytes32", "Hash of the declared extraction, identity, bot, and encoding policy."),
        ("evidence_hash", "bytes32", "Hash of the replayable off-chain evidence packet."),
        ("storage_persistence", "string or enum", "Persistence status/reference inherited from the submission metadata."),
        ("recorded_at", "uint64", "Timestamp or block-time metadata for the PoC record."),
    ]
    return pd.DataFrame(rows, columns=["field_name", "suggested_type", "role"])


def build_supporting_signals() -> pd.DataFrame:
    rows = [
        {
            "signal_id": "M1_endpoint_kloc",
            "role": "context",
            "use_in_poc": "not primary",
            "reason": "Project size helps interpret ownership share but does not measure developer reputation alone.",
        },
        {
            "signal_id": "M2_developer_churn",
            "role": "supporting audit signal",
            "use_in_poc": "off-chain evidence packet",
            "reason": "Shows the absolute amount of change behind the ownership share.",
        },
        {
            "signal_id": "M3_developer_commits_or_active_days",
            "role": "supporting audit signal",
            "use_in_poc": "off-chain evidence packet",
            "reason": "Helps distinguish sustained activity from one isolated ownership spike.",
        },
        {
            "signal_id": "M4_top1_top3_gini_churn",
            "role": "window-level concentration context",
            "use_in_poc": "off-chain evidence packet",
            "reason": "Shows whether the whole release window is unusually concentrated.",
        },
        {
            "signal_id": "bot_summary_by_window",
            "role": "sensitivity audit signal",
            "use_in_poc": "off-chain evidence packet",
            "reason": "Documents whether automation affected the surrounding project activity.",
        },
    ]
    return pd.DataFrame(rows)


def write_log(
    path: Path,
    selection: pd.DataFrame,
    rationale: pd.DataFrame,
    policy: pd.DataFrame,
    fields: pd.DataFrame,
    supporting: pd.DataFrame,
) -> None:
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    lines = [
        f"[{stamp}] poc_metric_selection_freeze=completed",
        f"[{stamp}] selected_metric_family={selection.at[0, 'selected_metric_family']}",
        f"[{stamp}] selected_signal_id={selection.at[0, 'selected_signal_id']}",
        f"[{stamp}] selection_rows={len(selection)}",
        f"[{stamp}] rationale_rows={len(rationale)}",
        f"[{stamp}] policy_rows={len(policy)}",
        f"[{stamp}] record_field_rows={len(fields)}",
        f"[{stamp}] supporting_signal_rows={len(supporting)}",
        f"[{stamp}] result=derived_poc_metric_selection_artifacts_written",
    ]
    ensure_parent(path)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    args = parse_args()
    base_dir = Path.cwd()
    out_dir = normalize_path(args.out_dir, base_dir)
    log_path = normalize_path(args.log, base_dir)
    ensure_dir(out_dir)

    decision = read_csv(out_dir / "poc_candidate_decision_inputs_all.csv")
    feasibility = read_csv(out_dir / "feasibility_summary_all.csv")

    selection = build_selection(decision, feasibility)
    rationale = build_rationale(decision)
    policy = build_policy()
    fields = build_record_fields()
    supporting = build_supporting_signals()

    write_csv(selection, out_dir / "poc_metric_selection_all.csv")
    write_csv(rationale, out_dir / "poc_metric_selection_rationale_all.csv")
    write_csv(policy, out_dir / "poc_metric_analysis_policy_all.csv")
    write_csv(fields, out_dir / "poc_metric_record_fields_all.csv")
    write_csv(supporting, out_dir / "poc_metric_supporting_signals_all.csv")
    write_log(log_path, selection, rationale, policy, fields, supporting)

    print(f"Wrote PoC metric selection artifacts to {out_dir}")
    print(f"Wrote log to {log_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
