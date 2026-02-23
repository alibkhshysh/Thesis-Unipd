# Round 1 Dataset + Version Freeze Report

Generated: 2026-02-23 18:56:27 +01:00

## Scope

- Round: 1 (4 repositories, httpx excluded)
- Base path: `E:\Thesis - Large Files`
- Freeze rule: latest 8 stable tags per repo (`^v?\d+\.\d+\.\d+$`; excludes `.x`, `rc`, `beta`, `alpha`)

## Dataset Freeze (Step 2.1)

| project_id | repo | storage_persistence | software_type_tags |
|---|---|---|---|
| flask | https://github.com/pallets/flask | High (GitHub) | web-framework, library |
| requests | https://github.com/psf/requests | High (GitHub) | http-client, library |
| urllib3 | https://github.com/urllib3/urllib3 | High (GitHub) | http-client, library |
| click | https://github.com/pallets/click | High (GitHub) | cli-toolkit, library |

## Versions Freeze (Step 2.2)

| project_id | frozen_versions | earliest_tag_date | latest_tag_date |
|---|---:|---|---|
| flask | 8 | 2023-09-30 | 2026-02-19 |
| requests | 8 | 2023-05-03 | 2025-08-18 |
| urllib3 | 8 | 2024-09-12 | 2026-01-07 |
| click | 8 | 2023-07-18 | 2025-11-15 |

### Frozen Tags by Repo

- **flask**: 3.1.3, 3.1.2, 3.1.1, 3.1.0, 3.0.3, 3.0.2, 3.0.1, 3.0.0
- **requests**: v2.32.5, v2.32.4, v2.32.3, v2.32.2, v2.32.1, v2.32.0, v2.31.0, v2.30.0
- **urllib3**: 2.6.3, 2.6.2, 2.6.1, 2.6.0, 2.5.0, 2.4.0, 2.3.0, 2.2.3
- **click**: 8.3.1, 8.3.0, 8.2.2, 8.2.1, 8.2.0, 8.1.8, 8.1.7, 8.1.6

## Output Files

- `dataset_freeze_round1.csv`
- `versions.csv`
- `round1_freeze_report.md` (this file)
