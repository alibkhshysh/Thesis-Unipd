# M4 deterministic metric freeze

## Frozen decision

The baseline PoC retains M4 developer churn ownership share as the selected
repository-derived evidence signal. The implementation identifier is
`M4_DEVELOPER_CHURN_SHARE`, policy version `1.0.0`.

The complete versioned policy is `spec/m4_metric_policy_v1.json`. Its canonical
SHA-256 policy hash is:

```text
4e81843340041da45a13ebb742a0c5fdfebdf6c8f5e64a7d6629f58990b287a4
```

## Exact calculation

For human developer `i` in eligible release window `w`:

```text
developer_churn(i,w) = added_text_lines(i,w) + deleted_text_lines(i,w)
window_human_churn(w) = sum of developer_churn(j,w) over all human developers j
share_churn(i,w) = developer_churn(i,w) / window_human_churn(w)
```

The ledger value uses deterministic nonnegative integer arithmetic:

```text
metric_value_ppm =
    (developer_churn * 1000000 + floor(window_human_churn / 2))
    // window_human_churn
```

This is round-to-nearest with exact ties rounded upward. It avoids language- or
platform-dependent floating-point behavior. Independently rounded developer
values are not expected to sum to exactly one million.

## Independent calculation audit

The validator rebuilt M4 from integer human developer metrics and cross-checked
the frozen ownership and Phase II inputs.

Results:

- 1,063 developer rows checked;
- 70 windows checked;
- 58 ancestral windows eligible for the baseline PoC;
- 848 developer rows in eligible windows;
- zero developer calculation failures;
- zero window total failures;
- zero zero-denominator windows;
- zero ownership-summary mismatches;
- zero Phase II C1 source-value mismatches;
- zero window metadata mismatches.

The maximum errors relative to the stored six-decimal CSV values are:

| Cross-check | Maximum absolute error |
|---|---:|
| Individual developer share | 0.000000498168 |
| Top-one developer share | 0.000000492063 |
| Churn Gini | 0.000000495298 |

All are below half of one millionth, the expected maximum error after storage to
six decimal places.

The largest sum deviation caused by independently rounding every developer to
ppm is five ppm across the complete dataset. This is expected and must not be
treated by the chaincode as a failed invariant.

## Conclusion cross-check

The ancestry-only C1 sensitivity analysis retains the behavioral stability
ordering used for the engineering choice:

```text
M4 top-one primary median CV = 0.246522
M4 Gini primary median CV    = 0.351228
M3 commits/day median CV     = 0.631179
M2 churn/KLOC/day median CV  = 0.890454
```

It is therefore supported to state that M4 remains a suitable candidate for the
baseline PoC under the thesis evaluation framework.

It is not supported to state that M4 is universally the best reputation metric,
that it directly measures developer quality, or that its gaming resistance has
been empirically proven. C2-C4 remain structured assessment criteria, while the
arithmetic and C1 stability cross-checks are empirical/reproducible.

## Baseline demonstration fixture

The first PoC fixture is `urllib3_W03`, tags `2.4.0` to `2.5.0`. It was selected
because it is ancestral, belongs to the primary duration set, includes nine
human developers, and exercises bot exclusion through one Dependabot identity.

For the top human contributor in that window:

```text
numerator churn   = 325
denominator churn = 1058
exact share       = 0.307183364839...
metric value      = 307183 ppm
```

The full fixture, including pinned commit hashes and expected supporting values,
is `spec/baseline_demo_case_v1.json`.

