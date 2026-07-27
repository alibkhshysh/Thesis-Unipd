#!/usr/bin/env python3
"""Render the corrected C1--C4 decision-input figure without changing Phase II."""

from __future__ import annotations

import argparse
import csv
import hashlib
import shutil
from datetime import datetime, timezone
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402


SCRIPT_DIR = Path(__file__).resolve().parent
PACKAGE_DIR = SCRIPT_DIR.parent
DEFAULT_SOURCE = (
    PACKAGE_DIR.parent / "Phase 2" / "out" / "poc_candidate_decision_inputs_all.csv"
)
DEFAULT_OUTPUT = PACKAGE_DIR / "out" / "poc_candidate_decision_inputs_corrected.pdf"
DEFAULT_LOG = PACKAGE_DIR / "logs" / "corrected_decision_figure.log"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--paper-figure", type=Path)
    parser.add_argument("--log-file", type=Path, default=DEFAULT_LOG)
    return parser.parse_args()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> int:
    args = parse_args()
    with args.source.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))

    required = {
        "metric_id",
        "metric_name",
        "empirical_average_score",
        "feasibility_score_0_10",
        "combined_readiness_score",
    }
    missing = required.difference(rows[0] if rows else {})
    if missing:
        raise RuntimeError(f"Missing decision-input columns: {sorted(missing)}")

    plot_rows = sorted(rows, key=lambda row: float(row["combined_readiness_score"]))
    positions = list(range(len(plot_rows)))
    labels = [f'{row["metric_id"]} {row["metric_name"]}' for row in plot_rows]
    comparison = [float(row["empirical_average_score"]) for row in plot_rows]
    feasibility = [float(row["feasibility_score_0_10"]) for row in plot_rows]
    combined = [float(row["combined_readiness_score"]) for row in plot_rows]

    fig, axis = plt.subplots(figsize=(9.5, 5.2))
    axis.scatter(comparison, positions, label="C1--C4 comparison average", color="#4c78a8", s=55)
    axis.scatter(feasibility, positions, label="Feasibility", color="#f58518", s=55)
    axis.scatter(combined, positions, label="Combined readiness", color="#54a24b", s=55)
    axis.set_yticks(positions)
    axis.set_yticklabels(labels)
    axis.set_xlim(0, 10)
    axis.set_xlabel("Score (0--10)")
    axis.set_title("Criterion and feasibility decision inputs")
    axis.grid(axis="x", linestyle=":", alpha=0.45)
    axis.legend(loc="lower right", fontsize=8)
    fig.tight_layout()

    args.output.parent.mkdir(parents=True, exist_ok=True)
    fixed_time = datetime(2026, 7, 26, tzinfo=timezone.utc)
    fig.savefig(
        args.output,
        bbox_inches="tight",
        metadata={"CreationDate": fixed_time, "ModDate": fixed_time},
    )
    plt.close(fig)

    if args.paper_figure:
        args.paper_figure.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(args.output, args.paper_figure)

    args.log_file.parent.mkdir(parents=True, exist_ok=True)
    log_lines = [
        "status=pass",
        f"source={args.source.resolve()}",
        f"source_sha256={sha256_file(args.source)}",
        f"rows={len(rows)}",
        "label_correction=C1-C4 empirical average -> C1-C4 comparison average",
        "reason=C1 is data-derived; C2-C4 are structured author assessments",
        f"output={args.output.resolve()}",
        f"output_sha256={sha256_file(args.output)}",
    ]
    args.log_file.write_text("\n".join(log_lines) + "\n", encoding="utf-8", newline="\n")
    print(f"Rendered corrected decision-input figure from {len(rows)} unchanged Phase II rows.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
