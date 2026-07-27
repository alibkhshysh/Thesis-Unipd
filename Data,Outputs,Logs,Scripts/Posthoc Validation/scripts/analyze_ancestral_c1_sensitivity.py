#!/usr/bin/env python3
"""Run the official C1 window-stability method on ancestral windows only.

The script reuses the frozen Phase II implementation instead of copying its
metric definitions or statistical rules. Existing Phase I and Phase II files
are read-only inputs; every result is written under ``Posthoc Validation``.
"""

from __future__ import annotations

import argparse
import csv
import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pandas as pd


# Import the frozen Phase II implementation without leaving a bytecode cache in
# its read-only source directory.
sys.dont_write_bytecode = True


SCRIPT_DIR = Path(__file__).resolve().parent
PACKAGE_DIR = SCRIPT_DIR.parent
WORK_ROOT = PACKAGE_DIR.parent.parent.parent
DEFAULT_PHASE1_DIR = PACKAGE_DIR.parent / "Phase 1"
DEFAULT_PHASE2_DIR = PACKAGE_DIR.parent / "Phase 2"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase1-dir", type=Path, default=DEFAULT_PHASE1_DIR)
    parser.add_argument("--phase2-dir", type=Path, default=DEFAULT_PHASE2_DIR)
    parser.add_argument(
        "--audit-file",
        type=Path,
        default=PACKAGE_DIR / "out" / "window_ancestry_audit_all.csv",
    )
    parser.add_argument("--output-dir", type=Path, default=PACKAGE_DIR / "out")
    parser.add_argument(
        "--log-file",
        type=Path,
        default=PACKAGE_DIR / "logs" / "c1_ancestral_sensitivity.log",
    )
    return parser.parse_args()


def load_official_c1_module(phase2_dir: Path) -> ModuleType:
    script_path = phase2_dir / "scripts" / "analyze_c1_stability.py"
    if not script_path.exists():
        raise FileNotFoundError(script_path)
    spec = importlib.util.spec_from_file_location("frozen_phase2_c1", script_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load the official C1 script: {script_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def read_valid_keys(audit_file: Path) -> set[tuple[str, str]]:
    if not audit_file.exists():
        raise FileNotFoundError(
            f"Ancestry audit not found: {audit_file}. Run audit_window_ancestry.py first."
        )
    with audit_file.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    valid = {
        (row["project_id"], row["window_id"])
        for row in rows
        if row["ancestry_status"] == "ancestral"
    }
    if len(rows) != 70 or len(valid) != 58:
        raise RuntimeError(
            f"Expected a 70-window audit with 58 ancestral windows; found {len(rows)} and {len(valid)}"
        )
    return valid


def filter_window_values(
    window_values: pd.DataFrame, valid_keys: set[tuple[str, str]]
) -> pd.DataFrame:
    mask = [
        (project_id, window_id) in valid_keys
        for project_id, window_id in zip(
            window_values["project_id"], window_values["window_id"]
        )
    ]
    result = window_values.loc[mask].copy()
    result.sort_values(["metric_signal_id", "project_id", "window_index"], inplace=True)
    expected_rows = len(valid_keys) * window_values["metric_signal_id"].nunique()
    if len(result) != expected_rows:
        raise RuntimeError(
            f"Expected {expected_rows} filtered window-metric rows, found {len(result)}"
        )
    return result


def build_comparison(
    official: pd.DataFrame, sensitivity: pd.DataFrame
) -> pd.DataFrame:
    official_prefix = official.rename(
        columns={
            column: f"original_{column}"
            for column in official.columns
            if column not in {"metric_signal_id", "metric_family", "metric_label", "unit"}
        }
    )
    sensitivity_prefix = sensitivity.rename(
        columns={
            column: f"ancestral_{column}"
            for column in sensitivity.columns
            if column not in {"metric_signal_id", "metric_family", "metric_label", "unit"}
        }
    )
    result = official_prefix.merge(
        sensitivity_prefix,
        on=["metric_signal_id", "metric_family", "metric_label", "unit"],
        how="outer",
        validate="one_to_one",
    )
    result["original_primary_high_volatility_share"] = (
        result["original_primary_high_volatility_projects"]
        / result["original_projects_with_primary_n_ge_2"]
    )
    result["ancestral_primary_high_volatility_share"] = (
        result["ancestral_primary_high_volatility_projects"]
        / result["ancestral_projects_with_primary_n_ge_2"]
    )
    result["median_primary_cv_change"] = (
        result["ancestral_median_primary_cv"] - result["original_median_primary_cv"]
    )
    result["primary_high_volatility_share_change"] = (
        result["ancestral_primary_high_volatility_share"]
        - result["original_primary_high_volatility_share"]
    )
    result.sort_values("metric_signal_id", inplace=True)
    return result


def write_log(
    path: Path,
    official_script: Path,
    valid_keys: set[tuple[str, str]],
    filtered_values: pd.DataFrame,
    project_stability: pd.DataFrame,
    overall_stability: pd.DataFrame,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "C1 ancestry-only sensitivity analysis",
        f"Official C1 implementation: {official_script.resolve()}",
        "Official Phase I and Phase II artifacts modified: false",
        f"Ancestral windows included: {len(valid_keys)}",
        f"Window-metric rows: {len(filtered_values)}",
        f"Project-metric rows: {len(project_stability)}",
        f"Overall metric rows: {len(overall_stability)}",
        "Volatility thresholds: identical to frozen official C1 implementation",
        "Primary-window policy: identical to frozen official C1 implementation",
        "Result: separate sensitivity tables written",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    args = parse_args()
    phase1_dir = args.phase1_dir.resolve()
    phase2_dir = args.phase2_dir.resolve()
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    official_c1 = load_official_c1_module(phase2_dir)
    valid_keys = read_valid_keys(args.audit_file.resolve())

    all_window_values = official_c1.build_window_metric_values(phase1_dir)
    filtered_values = filter_window_values(all_window_values, valid_keys)
    project_stability = official_c1.build_project_stability(filtered_values)
    overall_stability = official_c1.build_overall_stability(project_stability)

    official_overall = official_c1.read_csv(
        phase2_dir / "out" / "c1_metric_stability_overall_all.csv"
    )
    comparison = build_comparison(official_overall, overall_stability)

    official_c1.write_csv(
        filtered_values,
        output_dir / "c1_metric_window_values_ancestral_sensitivity.csv",
    )
    official_c1.write_csv(
        project_stability,
        output_dir / "c1_metric_stability_by_project_ancestral_sensitivity.csv",
    )
    official_c1.write_csv(
        overall_stability,
        output_dir / "c1_metric_stability_overall_ancestral_sensitivity.csv",
    )
    official_c1.write_csv(
        comparison,
        output_dir / "c1_original_vs_ancestral_sensitivity.csv",
    )
    write_log(
        args.log_file.resolve(),
        phase2_dir / "scripts" / "analyze_c1_stability.py",
        valid_keys,
        filtered_values,
        project_stability,
        overall_stability,
    )

    print(f"Included {len(valid_keys)} ancestral windows and {len(filtered_values)} metric rows.")
    print(f"Wrote ancestry-only C1 sensitivity outputs to {output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
