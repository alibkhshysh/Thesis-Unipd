# Phase 1 centralized dataset and Git metric extraction

This phase freezes the repository evidence base and derives the Git-based
candidate metrics used by the thesis. The active dataset contains 10
open-source repositories, 80 frozen release tags, and 70 consecutive
tag-chronological windows. It produces M1 snapshot-size evidence, M2 churn,
M3 activity-cadence fields, and M4 ownership/concentration evidence.

Phase 1 is descriptive and methodological. It does not rank the candidates or
select the proof-of-concept metric. Its centralized outputs are immutable
inputs to Phase 2, the separate post-hoc ancestry audit, and the Phase 3 metric
freeze.

## Active evidence and historical material

The files ending in `_all` are the active centralized evidence layer. Earlier
pilot-only and extended-only duplicates were consolidated and removed after
validation; the cleanup records are retained in `logs/`.

`archive/pilot/PILOT_round1_freeze_report_20260223.md` is the historical
four-repository pilot report. It is archived for provenance, but it is not the
definition of the final 10-repository dataset. The authoritative freeze files
are under `data/` and use the `_all` suffix.

## Directory layout

- `data/` — repository metadata, stable-tag rules, language policy, frozen
  tags and commit hashes, and release-window definitions.
- `repos/` — the 10 canonical Git working copies used for extraction.
- `scripts/` — deterministic extraction, cleaning, ownership, bot-sensitivity,
  and duration-normalization programs.
- `out/` — centralized raw, clean, human-only, normalized, ownership, and
  sensitivity CSV artifacts.
- `logs/` — execution, validation, recomputation, and consolidation records.
- `archive/pilot/` — historical pilot documentation excluded from the active
  centralized evidence layer.

The canonical repositories are `brew`, `click`, `curl`, `flask`, `gin`,
`junit5`, `prettier`, `requests`, `tokio`, and `urllib3`.

## Frozen inputs

The declared Phase 1 inputs are:

- `data/dataset_freeze_all.csv` — 10 repository records, cohort labels, URLs,
  persistence status, and software-type tags;
- `data/version_tag_rules_all.csv` — 10 stable-tag selection policies;
- `data/loc_language_policy_all.csv` — 10 project-specific source-language
  policies for M1;
- `data/versions_all.csv` — 80 tags, eight per repository, each tied to an
  immutable commit hash and tag date;
- `data/windows_all.csv` — 70 adjacent tag-date pairs, seven per repository.

The extraction scripts consume these frozen CSVs and the repositories under
`repos/`. The scripts in this folder do not recreate the repository/tag freeze
policy from an external service.

## Reproduce the centralized pipeline

Run the commands from this `Phase 1` directory. The defaults target the active
`_all` files. A rerun rewrites the corresponding outputs and logs, so use a
copy of the phase directory when comparing against the frozen evidence.

### Step 1: extract Git window metrics

```powershell
python scripts/extract_window_metrics.py
```

This reads `data/windows_all.csv` and `repos/`, then writes:

- `out/metrics_window_dev_all.csv`;
- `out/metrics_window_totals_all.csv`.

The developer table records commits, added/deleted lines, churn, binary-file
counts, activity days, committer-time bounds, identity fields, and bot flags.

### Step 2: canonicalize and validate developer rows

```powershell
python scripts/clean_round1_metrics.py
```

This consolidates rows by project, window, and canonical author email and
recomputes:

- `out/metrics_window_dev_clean_all.csv`;
- `out/metrics_window_totals_clean_all.csv`;
- `logs/clean_all_metrics.log`.

The script name retains the original `round1` development label; its defaults
operate on the final centralized `_all` dataset.

### Step 3: compute M1 multi-language snapshots

```powershell
python scripts/compute_loc_per_tag_multilang.py
```

This applies `data/loc_language_policy_all.csv` to tracked source files at each
frozen tag and writes `out/loc_per_tag_all.csv`. The older
`compute_loc_per_tag.py` is retained only for audit continuity with the
Python-only pilot workflow.

### Step 4: compute M4 ownership and concentration

```powershell
python scripts/recompute_ownership_from_clean.py
```

This derives developer churn/commit shares, top-1 and top-3 concentration, and
Gini values from the clean all-account table. Primary outputs are:

- `out/ownership_dev_shares_clean_all.csv`;
- `out/ownership_summary_clean_all.csv`;
- `logs/ownership_recompute_all.log`.

`compute_ownership.py` is a legacy helper; the centralized audited path uses
`recompute_ownership_from_clean.py`.

### Step 5: separate human and automated activity

```powershell
python scripts/compute_bot_sensitivity_outputs.py
```

This retains all-account evidence while exporting the primary human-only M3/M4
population and bot-sensitivity summaries:

- `out/metrics_window_dev_human_all.csv`;
- `out/metrics_window_totals_human_all.csv`;
- `out/ownership_dev_shares_human_all.csv`;
- `out/ownership_summary_human_all.csv`;
- `out/bot_summary_by_project_all.csv`;
- `out/bot_summary_by_window_all.csv`;
- `out/bot_identity_summary_all.csv`.

### Step 6: normalize uneven window durations

Run the all-account layer:

```powershell
python scripts/compute_duration_normalized_metrics.py
```

Then run the human-only layer:

```powershell
python scripts/compute_duration_normalized_metrics.py `
  --totals-clean out/metrics_window_totals_human_all.csv `
  --dev-clean out/metrics_window_dev_human_all.csv `
  --analysis-scope human `
  --log logs/duration_normalization_human_all.log
```

These runs derive commits/day, churn/day, churn/KLOC/day, developer-normalized
fields, and the short-window flags in `out/window_duration_flags*_all.csv` and
`out/window_duration_sensitivity_summary*_all.csv`.

## Validation snapshot

The retained logs record the following centralized results:

- 10 canonical repositories and 80 frozen tag rows checked;
- 0 missing or mismatched frozen tags or commits;
- 1,118 extracted and cleaned all-account developer-window rows;
- 70 window-total and ownership-summary rows;
- 0 duplicate key groups merged;
- 0 zero-commit or zero-churn windows;
- 0 ownership share-sum or unique-author validation failures;
- 1,063 human-only developer-window rows and 55 bot-flagged rows;
- 6 recognized automation identities across 42 windows;
- 9,560 total commits and 2,066,059 total churn lines;
- 999 bot commits and 9,294 bot churn lines;
- 22 windows shorter than seven days marked `sensitivity_only`;
- 80 M1 tag rows reproduced with 0 mismatches.

Primary evidence for M3 and M4 is human-only. All-account and bot-only summaries
remain available for audit and sensitivity analysis. Chronological windows are
not assumed to be ancestral; that separate condition is evaluated under
`../Posthoc Validation/` without overwriting this phase.

## Downstream lineage

- Phase 2 reads the centralized Phase 1 tables for C1 stability and C4
  long-term suitability, then combines those results with the declared C2/C3
  rubrics and the feasibility gate.
- Post-hoc Validation reads `data/windows_all.csv`, the human window totals,
  and `repos/` to audit Git ancestry.
- Phase 3 independently checks the frozen M4 calculations against the Phase 1
  human ownership tables and the Phase 2 C1 source values.
