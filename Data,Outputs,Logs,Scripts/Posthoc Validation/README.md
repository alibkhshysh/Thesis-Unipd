# Post-hoc release-window validation

This package supplements the frozen Phase I and Phase II analysis. It does not
replace or modify any existing input, output, figure, or selection file.

The original dataset selected the latest stable tags by tag date and formed
chronological adjacent pairs. A chronological pair is a linear Git development
interval only when the `from` commit is an ancestor of the `to` commit. The
audit in this package checks that condition for all frozen windows.

## Ancestry audit

Run from this directory:

```powershell
python scripts/audit_window_ancestry.py
```

The audit reads:

- `../Phase 1/data/windows_all.csv`
- `../Phase 1/out/metrics_window_totals_human_all.csv`
- the repositories under `../Phase 1/repos/`

It writes only under this package:

- `out/window_ancestry_audit_all.csv`
- `out/window_ancestry_summary_by_project_all.csv`
- `out/window_ancestry_impact_summary_all.csv`
- `logs/window_ancestry_audit.log`

An `ancestral` row satisfies:

```text
git merge-base --is-ancestor FROM_COMMIT TO_COMMIT
```

A `non_ancestral` row is excluded from the later ancestry-only sensitivity
analysis. The original Phase I and Phase II tables remain the official frozen
baseline and are retained for comparison.

## C1 ancestry-only sensitivity analysis

After the audit, run:

```powershell
python scripts/analyze_ancestral_c1_sensitivity.py
```

This script imports the frozen official C1 analysis implementation so that the
metric definitions, primary-window policy, summary statistics, and volatility
thresholds remain identical. It filters only by the ancestry audit and writes:

- `out/c1_metric_window_values_ancestral_sensitivity.csv`
- `out/c1_metric_stability_by_project_ancestral_sensitivity.csv`
- `out/c1_metric_stability_overall_ancestral_sensitivity.csv`
- `out/c1_original_vs_ancestral_sensitivity.csv`
- `logs/c1_ancestral_sensitivity.log`

The sensitivity comparison does not overwrite the official Phase II results or
recalculate the frozen multi-criterion readiness score. Its purpose is to test
whether the qualitative M4 selection is dependent on divergent release lines.

