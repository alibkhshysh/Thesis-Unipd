# M4 off-chain verifier and evidence replay report

## Result

Status: **pass**

The frozen `urllib3_W03` fixture was extracted directly from Git, encoded as a
canonical evidence manifest and ledger submission, and independently replayed
from a standalone Git bundle. No Phase I or Phase II artifact was modified.

## Frozen input

- project/window: `urllib3` / `urllib3_W03`
- annotated tags: `2.4.0` to `2.5.0`
- commits: `a5ff7ac3bbb8659e2ec3ed41dd43889f06a7d7bc` to
  `aaab4eccc10c965897540b21e15f11859d0b62e7`
- ancestry: pass
- tagger-time duration: 5,957,933 seconds (68.957558 days)
- policy: `M4_DEVELOPER_CHURN_SHARE_POLICY` version `1.0.0`
- policy SHA-256:
  `4e81843340041da45a13ebb742a0c5fdfebdf6c8f5e64a7d6629f58990b287a4`

## Standalone evidence artifact

The bundle is Git bundle version 2 and contains both annotated tag refs with no
prerequisite objects. The builder generated the bundle twice with single-thread
packing and required byte-identical SHA-256 values before keeping the artifact.

- file: `artifacts/urllib3_W03.git.bundle`
- size: 7,206,262 bytes
- SHA-256:
  `a41205eff782ce4af65f345e0afb97f16fd8677af215c7bdd06f460ce9602272`

## Direct extraction and calculation

| Quantity | Verified value |
|---|---:|
| Non-merge commits | 16 |
| Human developers | 9 |
| Human commits | 14 |
| Human added lines | 703 |
| Human deleted lines | 355 |
| Human churn denominator | 1,058 |
| Excluded bot identities | 1 |
| Excluded bot commits | 2 |
| Excluded bot churn | 18 |
| Binary file changes | 0 |
| Selected developer churn numerator | 325 |
| M4 integer value | 307,183 ppm |

The verifier source SHA-256 is
`b4e8171dfe228aec96c8e67de526f037af253bc85bd502cc6bc5c96991aedb19`.

Generated commitments:

- evidence manifest SHA-256:
  `df9e35adde01937b12da29eb21a3135268705d84168f9f1159a086b769d583ec`
- ledger submission SHA-256:
  `077e65f900aedc0f066cc01725a62f721c314a0932cdcd3b6f722c0c17a14fbe`
- developer audit SHA-256:
  `65c770e8ad44fae8c468a299e80bc2237bf8675c9b87c92ff484cb884134b5d4`

## Replay and independent checks

The replay initialized a new bare repository, fetched only the two tag refs from
the bundle, and reran the primary verifier. All four generated evidence files
were byte-identical to the originals.

A second traversal did not use the verifier's `git log --numstat` parser. It
enumerated non-merge commits with `git rev-list`, obtained author metadata per
commit, and accumulated changes with `git diff-tree --numstat`. It independently
matched all commit, developer, bot, added, deleted, churn, binary, numerator,
denominator, and ppm values.

Thirteen automated tests passed. Negative tests confirm rejection of an
additional ledger-submission field and a one-ppm arithmetic mutation. Repeated
execution of the complete step produced zero hash differences across nine
generated artifacts and logs.

## Claim boundary

This result establishes deterministic extraction, calculation, serialization,
commitment, and local replay for one ancestral fixture. It does not establish
real-world email ownership, perfect bot classification, semantic code quality,
permanent artifact availability, production-grade Fabric governance, or
generalization beyond the evaluated repository windows.
