#!/usr/bin/env python3
"""Independently validate and freeze the M4 calculation for the baseline PoC.

The validator reads frozen Phase I/II and post-hoc artifacts, reconstructs M4
from integer developer churn values, and writes only under ``Phase 3 PoC``.
It fails if a total, share, supporting M4 signal, or conclusion cross-check does
not pass.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from collections import defaultdict
from decimal import Decimal, ROUND_HALF_EVEN, getcontext
from fractions import Fraction
from pathlib import Path
from typing import Iterable


getcontext().prec = 50

SCRIPT_DIR = Path(__file__).resolve().parent
PACKAGE_DIR = SCRIPT_DIR.parent
DATA_ROOT = PACKAGE_DIR.parent
DEFAULT_PHASE1_DIR = DATA_ROOT / "Phase 1"
DEFAULT_PHASE2_DIR = DATA_ROOT / "Phase 2"
DEFAULT_POSTHOC_DIR = DATA_ROOT / "Posthoc Validation"
DEFAULT_POLICY = PACKAGE_DIR / "spec" / "m4_metric_policy_v1.json"

SCALE = 1_000_000
SIX_DP_TOLERANCE = Decimal("0.000000500001")
DEVELOPER_HASH_DOMAIN = b"m4-developer-id-v1\x00"

DEVELOPER_OUTPUT_FIELDS = [
    "project_id",
    "window_id",
    "from_tag",
    "to_tag",
    "author_email",
    "developer_id_hash",
    "ancestry_status",
    "eligible_for_baseline_poc",
    "numerator_churn",
    "denominator_churn",
    "exact_share_12dp",
    "frozen_share_6dp",
    "frozen_share_absolute_error",
    "metric_value_ppm",
    "ppm_share_6dp",
    "ppm_absolute_error_from_exact_share",
    "churn_equals_added_plus_deleted",
    "frozen_ownership_counts_match",
    "frozen_share_matches_exact_to_6dp",
    "developer_validation_status",
]

WINDOW_OUTPUT_FIELDS = [
    "project_id",
    "window_id",
    "from_tag",
    "to_tag",
    "ancestry_status",
    "eligible_for_baseline_poc",
    "human_developers",
    "zero_churn_human_developers",
    "recomputed_total_commits",
    "frozen_total_commits",
    "recomputed_total_added",
    "frozen_total_added",
    "recomputed_total_deleted",
    "frozen_total_deleted",
    "recomputed_total_churn",
    "frozen_total_churn",
    "recomputed_top1_share_churn_12dp",
    "frozen_top1_share_churn_6dp",
    "recomputed_gini_churn_12dp",
    "frozen_gini_churn_6dp",
    "c1_top1_share_churn_6dp",
    "c1_gini_churn_6dp",
    "sum_exact_shares_12dp",
    "sum_metric_value_ppm",
    "ppm_sum_deviation_from_scale",
    "developer_rows_valid",
    "totals_match",
    "ownership_summary_matches",
    "c1_source_values_match",
    "window_metadata_match",
    "window_validation_status",
]

SUMMARY_FIELDS = [
    "policy_id",
    "policy_version",
    "analysis_policy_hash_sha256",
    "metric_id",
    "frozen_phase2_selected_signal_id",
    "selected_signal_matches_policy",
    "total_windows",
    "ancestral_windows",
    "non_ancestral_windows",
    "eligible_poc_windows",
    "total_developer_rows",
    "eligible_poc_developer_rows",
    "developer_validation_failures",
    "window_validation_failures",
    "zero_denominator_windows",
    "total_mismatch_windows",
    "ownership_summary_mismatch_windows",
    "c1_source_mismatch_windows",
    "window_metadata_mismatch_windows",
    "max_frozen_share_absolute_error",
    "max_frozen_top1_absolute_error",
    "max_frozen_gini_absolute_error",
    "max_abs_ppm_sum_deviation",
    "m4_behavioral_stability_ordering_retained",
    "calculation_conclusion_supported",
    "validation_status",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase1-dir", type=Path, default=DEFAULT_PHASE1_DIR)
    parser.add_argument("--phase2-dir", type=Path, default=DEFAULT_PHASE2_DIR)
    parser.add_argument("--posthoc-dir", type=Path, default=DEFAULT_POSTHOC_DIR)
    parser.add_argument("--policy", type=Path, default=DEFAULT_POLICY)
    parser.add_argument("--output-dir", type=Path, default=PACKAGE_DIR / "out")
    parser.add_argument(
        "--log-file",
        type=Path,
        default=PACKAGE_DIR / "logs" / "m4_calculation_validation.log",
    )
    return parser.parse_args()


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        raise FileNotFoundError(path)
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, fields: list[str], rows: Iterable[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def as_bool(value: bool) -> str:
    return "true" if value else "false"


def canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def policy_hash(policy: dict[str, object]) -> str:
    return hashlib.sha256(canonical_json_bytes(policy)).hexdigest()


def developer_id_hash(canonical_email: str) -> str:
    payload = DEVELOPER_HASH_DOMAIN + canonical_email.encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def ppm_round_half_up(numerator: int, denominator: int) -> int:
    if denominator <= 0:
        raise ValueError("M4 denominator must be greater than zero")
    if numerator < 0 or numerator > denominator:
        raise ValueError("M4 numerator must satisfy 0 <= numerator <= denominator")
    return (numerator * SCALE + denominator // 2) // denominator


def fraction_decimal(value: Fraction) -> Decimal:
    return Decimal(value.numerator) / Decimal(value.denominator)


def decimal_string(value: Fraction, places: int) -> str:
    quantum = Decimal(1).scaleb(-places)
    rounded = fraction_decimal(value).quantize(quantum, rounding=ROUND_HALF_EVEN)
    return f"{rounded:.{places}f}"


def decimal_error(stored: str, exact: Fraction) -> Decimal:
    return abs(Decimal(stored) - fraction_decimal(exact))


def gini_fraction(values: list[int]) -> Fraction:
    clean = sorted(value for value in values if value >= 0)
    count = len(clean)
    total = sum(clean)
    if count == 0 or total == 0:
        return Fraction(0, 1)
    weighted = sum((index + 1) * value for index, value in enumerate(clean))
    return Fraction(2 * weighted, count * total) - Fraction(count + 1, count)


def unique_by(
    rows: list[dict[str, str]], fields: tuple[str, ...], label: str
) -> dict[tuple[str, ...], dict[str, str]]:
    result: dict[tuple[str, ...], dict[str, str]] = {}
    for row in rows:
        key = tuple(row[field] for field in fields)
        if key in result:
            raise RuntimeError(f"Duplicate {label} key: {key}")
        result[key] = row
    return result


def validate_policy(policy: dict[str, object]) -> None:
    if policy["policy_id"] != "M4_DEVELOPER_CHURN_SHARE_POLICY":
        raise RuntimeError("Unexpected M4 policy_id")
    if policy["metric"]["metric_id"] != "M4_DEVELOPER_CHURN_SHARE":
        raise RuntimeError("Unexpected M4 metric_id")
    calculation = policy["calculation_policy"]
    if calculation["fixed_point_scale"] != SCALE:
        raise RuntimeError("Policy scale does not match validator scale")
    expected_formula = (
        "metric_value_ppm = (numerator * 1000000 + floor(denominator / 2)) // denominator"
    )
    if calculation["integer_formula"] != expected_formula:
        raise RuntimeError("Policy integer formula does not match validator formula")


def behavioral_stability_ordering(posthoc_dir: Path) -> bool:
    rows = read_csv(posthoc_dir / "out" / "c1_original_vs_ancestral_sensitivity.csv")
    by_metric = {row["metric_signal_id"]: row for row in rows}
    required = {
        "M2_churn_per_kloc_day",
        "M3_commits_per_day",
        "M4_gini_churn",
        "M4_top1_share_churn",
    }
    if not required.issubset(by_metric):
        raise RuntimeError("Post-hoc comparison is missing required behavioral signals")
    m2 = Decimal(by_metric["M2_churn_per_kloc_day"]["ancestral_median_primary_cv"])
    m3 = Decimal(by_metric["M3_commits_per_day"]["ancestral_median_primary_cv"])
    m4_gini = Decimal(by_metric["M4_gini_churn"]["ancestral_median_primary_cv"])
    m4_top1 = Decimal(by_metric["M4_top1_share_churn"]["ancestral_median_primary_cv"])
    return max(m4_gini, m4_top1) < min(m2, m3)


def main() -> int:
    args = parse_args()
    phase1_dir = args.phase1_dir.resolve()
    phase2_dir = args.phase2_dir.resolve()
    posthoc_dir = args.posthoc_dir.resolve()
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    with args.policy.resolve().open("r", encoding="utf-8") as handle:
        policy = json.load(handle)
    validate_policy(policy)
    current_policy_hash = policy_hash(policy)

    dev_rows = read_csv(phase1_dir / "out" / "metrics_window_dev_human_all.csv")
    total_rows = read_csv(phase1_dir / "out" / "metrics_window_totals_human_all.csv")
    ownership_rows = read_csv(phase1_dir / "out" / "ownership_dev_shares_human_all.csv")
    summary_rows = read_csv(phase1_dir / "out" / "ownership_summary_human_all.csv")
    c1_rows = read_csv(phase2_dir / "out" / "c1_metric_window_values_all.csv")
    ancestry_rows = read_csv(posthoc_dir / "out" / "window_ancestry_audit_all.csv")
    selection_rows = read_csv(phase2_dir / "out" / "poc_metric_selection_all.csv")

    totals_by_window = unique_by(total_rows, ("project_id", "window_id"), "total")
    summary_by_window = unique_by(summary_rows, ("project_id", "window_id"), "ownership summary")
    ancestry_by_window = unique_by(ancestry_rows, ("project_id", "window_id"), "ancestry")
    ownership_by_developer = unique_by(
        ownership_rows,
        ("project_id", "window_id", "author_email"),
        "developer ownership",
    )

    c1_m4_rows = [
        row
        for row in c1_rows
        if row["metric_signal_id"] in {"M4_gini_churn", "M4_top1_share_churn"}
    ]
    c1_by_signal_window = unique_by(
        c1_m4_rows,
        ("metric_signal_id", "project_id", "window_id"),
        "C1 M4 source",
    )

    dev_by_window: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
    seen_dev_keys: set[tuple[str, str, str]] = set()
    for row in dev_rows:
        email = row["author_email"].strip().lower()
        key = (row["project_id"], row["window_id"], email)
        if key in seen_dev_keys:
            raise RuntimeError(f"Duplicate human developer row: {key}")
        seen_dev_keys.add(key)
        dev_by_window[(row["project_id"], row["window_id"])].append(row)

    if set(totals_by_window) != set(summary_by_window):
        raise RuntimeError("Human totals and ownership-summary window keys differ")
    if set(totals_by_window) != set(ancestry_by_window):
        raise RuntimeError("Human totals and ancestry-audit window keys differ")

    developer_output: list[dict[str, object]] = []
    window_output: list[dict[str, object]] = []
    share_errors: list[Decimal] = []
    top1_errors: list[Decimal] = []
    gini_errors: list[Decimal] = []

    for window_key in sorted(totals_by_window):
        project_id, window_id = window_key
        frozen_totals = totals_by_window[window_key]
        frozen_summary = summary_by_window[window_key]
        ancestry = ancestry_by_window[window_key]
        group = sorted(
            dev_by_window[window_key], key=lambda row: row["author_email"].strip().lower()
        )
        if not group:
            raise RuntimeError(f"No human developer rows for {window_key}")

        recomputed_commits = sum(int(row["commits"]) for row in group)
        recomputed_added = sum(int(row["added"]) for row in group)
        recomputed_deleted = sum(int(row["deleted"]) for row in group)
        recomputed_churn = sum(int(row["churn"]) for row in group)
        frozen_total_commits = int(frozen_totals["total_commits"])
        frozen_total_added = int(frozen_totals["total_added"])
        frozen_total_deleted = int(frozen_totals["total_deleted"])
        frozen_total_churn = int(frozen_totals["total_churn"])

        totals_match = (
            recomputed_commits == frozen_total_commits
            and recomputed_added == frozen_total_added
            and recomputed_deleted == frozen_total_deleted
            and recomputed_churn == frozen_total_churn
            and recomputed_churn == recomputed_added + recomputed_deleted
            and len(group) == int(frozen_totals["unique_authors"])
        )
        denominator_valid = recomputed_churn > 0
        if not denominator_valid:
            # A zero denominator is recorded below and makes the window ineligible.
            denominator = 0
        else:
            denominator = recomputed_churn

        metadata_match = all(
            row["project_id"] == project_id
            and row["window_id"] == window_id
            and row["from_tag"] == frozen_totals["from_tag"]
            and row["to_tag"] == frozen_totals["to_tag"]
            and row["is_bot"].strip().lower() == "false"
            and row["author_email"] == row["author_email"].strip().lower()
            for row in group
        ) and (
            frozen_summary["from_tag"] == frozen_totals["from_tag"]
            and frozen_summary["to_tag"] == frozen_totals["to_tag"]
            and ancestry["from_tag"] == frozen_totals["from_tag"]
            and ancestry["to_tag"] == frozen_totals["to_tag"]
        )

        churn_values = [int(row["churn"]) for row in group]
        if denominator_valid:
            shares = [Fraction(value, denominator) for value in churn_values]
            top1 = max(shares)
            exact_share_sum = sum(shares, Fraction(0, 1))
        else:
            shares = [Fraction(0, 1) for _ in churn_values]
            top1 = Fraction(0, 1)
            exact_share_sum = Fraction(0, 1)
        gini = gini_fraction(churn_values)

        top1_error = decimal_error(frozen_summary["top1_share_churn"], top1)
        gini_error = decimal_error(frozen_summary["gini_churn"], gini)
        top1_errors.append(top1_error)
        gini_errors.append(gini_error)
        ownership_summary_matches = (
            int(frozen_summary["total_commits"]) == recomputed_commits
            and int(frozen_summary["total_churn"]) == recomputed_churn
            and int(frozen_summary["unique_authors"]) == len(group)
            and top1_error <= SIX_DP_TOLERANCE
            and gini_error <= SIX_DP_TOLERANCE
        )

        c1_top1 = c1_by_signal_window[("M4_top1_share_churn", project_id, window_id)]["value"]
        c1_gini = c1_by_signal_window[("M4_gini_churn", project_id, window_id)]["value"]
        c1_source_matches = (
            decimal_error(c1_top1, top1) <= SIX_DP_TOLERANCE
            and decimal_error(c1_gini, gini) <= SIX_DP_TOLERANCE
        )

        developer_rows_valid = True
        ppm_values: list[int] = []
        pending_developer_rows: list[dict[str, object]] = []
        for row, exact_share in zip(group, shares):
            email = row["author_email"].strip().lower()
            numerator = int(row["churn"])
            frozen_ownership = ownership_by_developer.get((project_id, window_id, email))
            if frozen_ownership is None:
                raise RuntimeError(f"Missing frozen ownership row for {project_id}/{window_id}/{email}")

            churn_formula_match = numerator == int(row["added"]) + int(row["deleted"])
            ownership_counts_match = (
                int(frozen_ownership["commits"]) == int(row["commits"])
                and int(frozen_ownership["churn"]) == numerator
                and frozen_ownership["is_bot"].strip().lower() == "false"
            )
            share_error = decimal_error(frozen_ownership["share_churn"], exact_share)
            share_errors.append(share_error)
            share_match = share_error <= SIX_DP_TOLERANCE
            ppm = ppm_round_half_up(numerator, denominator) if denominator_valid else 0
            ppm_values.append(ppm)
            ppm_share = Fraction(ppm, SCALE)
            ppm_error = abs(fraction_decimal(ppm_share) - fraction_decimal(exact_share))
            row_valid = (
                denominator_valid
                and churn_formula_match
                and ownership_counts_match
                and share_match
                and 0 <= numerator <= denominator
                and 0 <= ppm <= SCALE
            )
            developer_rows_valid = developer_rows_valid and row_valid
            pending_developer_rows.append(
                {
                    "project_id": project_id,
                    "window_id": window_id,
                    "from_tag": frozen_totals["from_tag"],
                    "to_tag": frozen_totals["to_tag"],
                    "author_email": email,
                    "developer_id_hash": developer_id_hash(email),
                    "ancestry_status": ancestry["ancestry_status"],
                    "numerator_churn": numerator,
                    "denominator_churn": denominator,
                    "exact_share_12dp": decimal_string(exact_share, 12),
                    "frozen_share_6dp": frozen_ownership["share_churn"],
                    "frozen_share_absolute_error": f"{share_error:.12f}",
                    "metric_value_ppm": ppm,
                    "ppm_share_6dp": f"{Decimal(ppm) / Decimal(SCALE):.6f}",
                    "ppm_absolute_error_from_exact_share": f"{ppm_error:.12f}",
                    "churn_equals_added_plus_deleted": as_bool(churn_formula_match),
                    "frozen_ownership_counts_match": as_bool(ownership_counts_match),
                    "frozen_share_matches_exact_to_6dp": as_bool(share_match),
                    "developer_validation_status": "pass" if row_valid else "fail",
                }
            )

        window_validation = (
            denominator_valid
            and totals_match
            and ownership_summary_matches
            and c1_source_matches
            and metadata_match
            and developer_rows_valid
            and exact_share_sum == Fraction(1, 1)
        )
        eligible = ancestry["ancestry_status"] == "ancestral" and window_validation
        for output_row in pending_developer_rows:
            output_row["eligible_for_baseline_poc"] = as_bool(eligible)
            developer_output.append(output_row)

        ppm_sum = sum(ppm_values)
        window_output.append(
            {
                "project_id": project_id,
                "window_id": window_id,
                "from_tag": frozen_totals["from_tag"],
                "to_tag": frozen_totals["to_tag"],
                "ancestry_status": ancestry["ancestry_status"],
                "eligible_for_baseline_poc": as_bool(eligible),
                "human_developers": len(group),
                "zero_churn_human_developers": sum(value == 0 for value in churn_values),
                "recomputed_total_commits": recomputed_commits,
                "frozen_total_commits": frozen_total_commits,
                "recomputed_total_added": recomputed_added,
                "frozen_total_added": frozen_total_added,
                "recomputed_total_deleted": recomputed_deleted,
                "frozen_total_deleted": frozen_total_deleted,
                "recomputed_total_churn": recomputed_churn,
                "frozen_total_churn": frozen_total_churn,
                "recomputed_top1_share_churn_12dp": decimal_string(top1, 12),
                "frozen_top1_share_churn_6dp": frozen_summary["top1_share_churn"],
                "recomputed_gini_churn_12dp": decimal_string(gini, 12),
                "frozen_gini_churn_6dp": frozen_summary["gini_churn"],
                "c1_top1_share_churn_6dp": c1_top1,
                "c1_gini_churn_6dp": c1_gini,
                "sum_exact_shares_12dp": decimal_string(exact_share_sum, 12),
                "sum_metric_value_ppm": ppm_sum,
                "ppm_sum_deviation_from_scale": ppm_sum - SCALE,
                "developer_rows_valid": as_bool(developer_rows_valid),
                "totals_match": as_bool(totals_match),
                "ownership_summary_matches": as_bool(ownership_summary_matches),
                "c1_source_values_match": as_bool(c1_source_matches),
                "window_metadata_match": as_bool(metadata_match),
                "window_validation_status": "pass" if window_validation else "fail",
            }
        )

    if len(ownership_by_developer) != len(developer_output):
        raise RuntimeError(
            "Frozen ownership rows and independently reconstructed developer rows differ in count"
        )

    selection = selection_rows[0]
    selected_signal_matches = (
        len(selection_rows) == 1
        and selection["selected_metric_family"] == "M4"
        and selection["selected_signal_id"] == "M4_developer_share_churn"
        and policy["metric"]["metric_id"] == "M4_DEVELOPER_CHURN_SHARE"
    )
    ordering_retained = behavioral_stability_ordering(posthoc_dir)

    developer_failures = sum(
        row["developer_validation_status"] != "pass" for row in developer_output
    )
    window_failures = sum(row["window_validation_status"] != "pass" for row in window_output)
    zero_denominators = sum(int(row["recomputed_total_churn"]) == 0 for row in window_output)
    total_mismatches = sum(row["totals_match"] != "true" for row in window_output)
    summary_mismatches = sum(
        row["ownership_summary_matches"] != "true" for row in window_output
    )
    c1_mismatches = sum(row["c1_source_values_match"] != "true" for row in window_output)
    metadata_mismatches = sum(row["window_metadata_match"] != "true" for row in window_output)
    ancestral_windows = sum(row["ancestry_status"] == "ancestral" for row in window_output)
    eligible_windows = sum(row["eligible_for_baseline_poc"] == "true" for row in window_output)
    eligible_developers = sum(
        row["eligible_for_baseline_poc"] == "true" for row in developer_output
    )

    conclusion_supported = (
        developer_failures == 0
        and window_failures == 0
        and zero_denominators == 0
        and total_mismatches == 0
        and summary_mismatches == 0
        and c1_mismatches == 0
        and metadata_mismatches == 0
        and ancestral_windows == 58
        and eligible_windows == 58
        and selected_signal_matches
        and ordering_retained
    )
    validation_status = "pass" if conclusion_supported else "fail"

    summary = {
        "policy_id": policy["policy_id"],
        "policy_version": policy["policy_version"],
        "analysis_policy_hash_sha256": current_policy_hash,
        "metric_id": policy["metric"]["metric_id"],
        "frozen_phase2_selected_signal_id": selection.get("selected_signal_id", ""),
        "selected_signal_matches_policy": as_bool(selected_signal_matches),
        "total_windows": len(window_output),
        "ancestral_windows": ancestral_windows,
        "non_ancestral_windows": len(window_output) - ancestral_windows,
        "eligible_poc_windows": eligible_windows,
        "total_developer_rows": len(developer_output),
        "eligible_poc_developer_rows": eligible_developers,
        "developer_validation_failures": developer_failures,
        "window_validation_failures": window_failures,
        "zero_denominator_windows": zero_denominators,
        "total_mismatch_windows": total_mismatches,
        "ownership_summary_mismatch_windows": summary_mismatches,
        "c1_source_mismatch_windows": c1_mismatches,
        "window_metadata_mismatch_windows": metadata_mismatches,
        "max_frozen_share_absolute_error": f"{max(share_errors, default=Decimal(0)):.12f}",
        "max_frozen_top1_absolute_error": f"{max(top1_errors, default=Decimal(0)):.12f}",
        "max_frozen_gini_absolute_error": f"{max(gini_errors, default=Decimal(0)):.12f}",
        "max_abs_ppm_sum_deviation": max(
            (abs(int(row["ppm_sum_deviation_from_scale"])) for row in window_output),
            default=0,
        ),
        "m4_behavioral_stability_ordering_retained": as_bool(ordering_retained),
        "calculation_conclusion_supported": as_bool(conclusion_supported),
        "validation_status": validation_status,
    }

    write_csv(
        output_dir / "m4_developer_metric_values_all.csv",
        DEVELOPER_OUTPUT_FIELDS,
        developer_output,
    )
    write_csv(
        output_dir / "m4_window_calculation_audit_all.csv",
        WINDOW_OUTPUT_FIELDS,
        window_output,
    )
    write_csv(
        output_dir / "m4_calculation_audit_summary_all.csv",
        SUMMARY_FIELDS,
        [summary],
    )
    (output_dir / "m4_metric_policy_hash_v1.txt").write_text(
        current_policy_hash + "\n", encoding="ascii"
    )

    args.log_file.resolve().parent.mkdir(parents=True, exist_ok=True)
    args.log_file.resolve().write_text(
        "\n".join(
            [
                "M4 deterministic calculation validation",
                f"Policy: {args.policy.resolve()}",
                f"Policy hash: {current_policy_hash}",
                f"Windows: {len(window_output)}",
                f"Ancestral windows: {ancestral_windows}",
                f"Eligible PoC windows: {eligible_windows}",
                f"Developer rows: {len(developer_output)}",
                f"Developer validation failures: {developer_failures}",
                f"Window validation failures: {window_failures}",
                f"M4 behavioral stability ordering retained: {as_bool(ordering_retained)}",
                f"Calculation conclusion supported: {as_bool(conclusion_supported)}",
                f"Validation status: {validation_status}",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    print(
        f"Validated {len(developer_output)} developer rows across {len(window_output)} windows; "
        f"eligible ancestral windows: {eligible_windows}."
    )
    print(f"Policy hash: {current_policy_hash}")
    print(f"Validation status: {validation_status}")
    return 0 if conclusion_supported else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc

