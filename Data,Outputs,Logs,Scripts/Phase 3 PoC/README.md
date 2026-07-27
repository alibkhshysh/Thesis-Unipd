# Phase 3 baseline PoC

This phase implements the selected M4 developer churn-ownership evidence after
the frozen Phase I/II analysis and the separate post-hoc ancestry validation.

Existing Phase I, Phase II, and post-hoc artifacts are immutable inputs. Phase 3
does not overwrite them.

## Step 1: deterministic metric freeze

The versioned calculation policy is:

- `spec/m4_metric_policy_v1.json`

Validate the frozen calculations with:

```powershell
python scripts/validate_m4_calculation.py
```

The validator independently rebuilds human developer churn totals, individual
shares, deterministic ppm values, top-one ownership, and churn Gini. It compares
them with the frozen Phase I ownership tables and the Phase II C1 source values.

Generated files are written only under this phase:

- `out/m4_developer_metric_values_all.csv`
- `out/m4_window_calculation_audit_all.csv`
- `out/m4_calculation_audit_summary_all.csv`
- `out/m4_metric_policy_hash_v1.txt`
- `logs/m4_calculation_validation.log`

The baseline PoC may use a record only when its window is ancestral and every
calculation validation passes.

## Step 2: architecture, schemas, and trust boundary

The implementation contract is frozen in:

- `spec/poc_design_v1.json`
- `spec/evidence_manifest_schema_v1.json`
- `spec/ledger_submission_schema_v1.json`
- `spec/ledger_record_schema_v1.json`
- `docs/POC_ARCHITECTURE_AND_TRUST_MODEL.md`

Validate the design, schema references, shared constraints, and baseline fixture
with:

```powershell
python scripts/validate_poc_design.py
```

The validator writes only to `out/` and `logs/`. The design uses the frozen
Fabric 2.5.15 release from the 2.5 LTS line, the official two-organization
test-network topology, JavaScript chaincode,
two-organization write endorsement, and an Org1-only baseline submitter policy.
The ledger records a compact deterministic commitment; Git extraction and
evidence replay remain off-chain.

The original Phase II decision-input CSV is retained unchanged. A corrected
paper figure labels its C1--C4 value as a *comparison average* because C1 is
data-derived while C2--C4 are structured assessments:

```powershell
python scripts/render_corrected_decision_figure.py
```

## Step 3: off-chain verifier and replayable evidence

Create the standalone version-2 Git bundle. The creator resolves both annotated
tags, checks the frozen commits and ancestry, rejects bundle prerequisites, and
requires two independently generated bundle files to have the same SHA-256:

```powershell
python scripts/create_git_evidence_bundle.py
```

Run the verifier directly against Git and generate the canonical manifest,
compact ledger submission, developer audit, and verification summary:

```powershell
python scripts/m4_offchain_verifier.py
```

Replay from a fresh bare repository populated only from the bundle:

```powershell
python scripts/replay_m4_evidence.py
```

The replay performs two checks. It reruns the primary verifier and compares four
generated files byte-for-byte, then independently traverses commits with
`git rev-list` and `git diff-tree` and compares all extraction totals and the M4
calculation with the manifest.

Run all arithmetic, schema, negative-case, and generated-artifact tests with:

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
python -m unittest discover -s tests -p 'test*.py' -v
```

The measured implementation result and exact hashes are documented in
`OFFCHAIN_VERIFIER_REPORT.md`.

## Step 4: JavaScript chaincode and local unit validation

The frozen `m4evidence` contract is implemented in:

- `chaincode/m4evidence/index.js`
- `chaincode/m4evidence/lib/m4-evidence-contract.js`

Install the exact locked dependencies and run the chaincode checks with:

```powershell
Set-Location chaincode/m4evidence
npm ci --no-fund
Set-Location ../..
python scripts/validate_chaincode_unit.py
```

The validator runs the Node test suite, verifies installed and locked Fabric
library versions, runs the production-dependency audit, inspects the deployable
npm package, independently derives the fixture record ID, and writes the
machine-readable result and log under `out/` and `logs/`.

All 34 tests pass. They cover the exact six-transaction surface, the exact
26-field immutable record, `BigInt` arithmetic and rounding boundaries,
authorization, duplicates, state/index/event writes, reads, queries, history,
and malformed or manipulated submissions. Exact results and source commitments
are documented in `CHAINCODE_UNIT_TEST_REPORT.md`.

This is local contract validation with deterministic Fabric mocks. The live
network boundary is evaluated separately in Step 5.

## Step 5: Fabric deployment and authenticated integration validation

The unchanged four-file chaincode runtime was deployed to the official local
two-organization test network on channel `mychannel`. Both organizations
approved the definition, and the committed policy requires both organizational
peers to endorse writes.

The Gateway client and independent network validator are:

- `integration/fabric_gateway/run_integration.js`
- `scripts/validate_fabric_network.py`

Install the exact client dependencies, run the integration once on a fresh
network, and validate the resulting ledger state with:

```powershell
Set-Location integration/fabric_gateway
npm ci --no-fund
npm audit --omit=dev
npm run integration
Set-Location ../..
$env:PYTHONDONTWRITEBYTECODE='1'
python scripts/validate_fabric_network.py
```

All 17 Gateway checks and all 47 independent network checks pass. The accepted
Org1 submission was endorsed by Org1 and Org2, committed as a valid transaction
in block 6, read identically from both peers, returned by both secondary-index
queries and history, and accompanied by the expected chaincode event. Malformed
JSON, a one-ppm mutation, an Org2 submission, and a duplicate were rejected.
Rejected proposals created no state, and a temporary one-byte modification of
the Git bundle failed independent replay.

Exact environment versions, image digests, package and transaction commitments,
measured results, limitations, and reconstruction commands are documented in:

- `FABRIC_NETWORK_REPORT.md`
- `fabric_runtime/README.md`
- `out/fabric_gateway_integration_summary.json`
- `out/fabric_network_validation_summary.csv`
