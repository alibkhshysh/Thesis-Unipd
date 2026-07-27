# Post-hoc release-window validation findings

## Purpose and status

This document supplements the frozen Phase I and Phase II analysis. No existing
dataset, output, figure, score, or selection artifact was replaced. The goal is
to test whether the qualitative choice of M4 for the baseline PoC depends on
release windows that cross divergent Git history paths.

## Ancestry audit result

The audit evaluated all 70 frozen tag-chronological windows with:

```text
git merge-base --is-ancestor FROM_COMMIT TO_COMMIT
```

Results:

- 58 windows are linear ancestor-to-descendant intervals.
- 12 windows are non-ancestral.
- 5 of the 10 projects contain at least one non-ancestral window.
- 3,576 of 8,561 human commits (41.770821%) occur in non-ancestral windows.
- 1,471,597 of 2,056,765 human churn lines (71.549107%) occur in
  non-ancestral windows.

The affected windows are:

| Project | Window | From tag | To tag |
|---|---|---|---|
| flask | flask_W01 | 3.0.0 | 3.0.1 |
| gin | gin_W02 | v1.8.2 | v1.9.0 |
| gin | gin_W06 | v1.10.1 | v1.11.0 |
| junit5 | junit5_W01 | r6.0.0 | r5.14.1 |
| junit5 | junit5_W02 | r5.14.1 | r6.0.1 |
| junit5 | junit5_W03 | r6.0.1 | r5.14.2 |
| junit5 | junit5_W04 | r5.14.2 | r6.0.2 |
| junit5 | junit5_W05 | r6.0.2 | r5.14.3 |
| junit5 | junit5_W06 | r5.14.3 | r6.0.3 |
| junit5 | junit5_W07 | r6.0.3 | r5.14.4 |
| prettier | prettier_W05 | 3.8.0 | 3.8.1 |
| tokio | tokio_W03 | tokio-1.50.0 | tokio-1.47.4 |

For these rows, `from..to` remains a valid Git set difference but is not a
sequential release-development interval. JUnit alternates between two active
release lines and therefore has no window in the ancestry-only subset.

## Ancestry-only C1 sensitivity result

The sensitivity run imports the frozen official C1 implementation. Metric
definitions, primary-window flags, coefficients of variation, and volatility
thresholds are unchanged. The only added condition is inclusion in the
ancestry audit.

The reduced analysis contains:

- 58 windows;
- 9 projects with at least one retained window;
- 8 projects with at least two retained primary windows.

| Metric signal | Original median primary CV | Ancestral-only median primary CV | Original primary high-volatility projects | Ancestral-only primary high-volatility projects |
|---|---:|---:|---:|---:|
| M1 endpoint KLOC | 0.014392 | 0.014392 | 0/10 | 0/8 |
| M2 churn/KLOC/day | 0.890454 | 0.890454 | 6/10 | 5/8 |
| M3 commits/day | 0.607560 | 0.631179 | 4/10 | 3/8 |
| M4 churn Gini | 0.328938 | 0.351228 | 2/10 | 1/8 |
| M4 top-1 churn share | 0.235787 | 0.246522 | 1/10 | 0/8 |

M1 remains the most stable context signal but is not eligible as standalone
developer-reputation evidence. Among the implemented behavioral candidates,
the ancestry-only result retains the original qualitative ordering: M4 is less
volatile than M2 and M3. M4 top-one churn share remains inside the frozen
low-volatility threshold (`CV <= 0.25`), while M4 churn Gini remains moderate.

## Decision for the baseline PoC

The post-hoc check supports retaining M4 developer churn ownership share for the
baseline PoC. This is an engineering selection for demonstrating verifiable
repository-derived evidence, not a claim that M4 is a universal or complete
measure of developer quality or reputation.

The final thesis should report both the original analysis and this sensitivity
check. It should not describe all original chronological tag pairs as linear
release intervals, and it should identify the C2-C4 rubric scores as structured
author assessments rather than fully empirical measurements.

## Generated evidence

The machine-readable audit and sensitivity tables are under `out/`; execution
details are under `logs/`. Commands and file names are documented in
`README.md`.

