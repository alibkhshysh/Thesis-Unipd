# M4 chaincode implementation and local validation report

## Status and scope

Validation ID: `M4_CHAINCODE_UNIT_VALIDATION_V1`  
Chaincode: `m4evidence` version `1.0.0`  
Result: **pass** (34/34 tests, 0 failed, 0 skipped)

This step implements the frozen JavaScript chaincode contract and validates it
locally with deterministic mocks of the Fabric stub and client identity. It is
not a substitute for deployment to Fabric peers: endorsement, ordering,
commit events, discovery, and ledger persistence still require the network
integration step.

## Implemented transaction surface

The contract exposes exactly the six frozen public transactions:

1. `SubmitMetricEvidence`
2. `MetricEvidenceExists`
3. `ReadMetricEvidence`
4. `GetMetricEvidenceHistory`
5. `QueryByProject`
6. `QueryByDeveloper`

`SubmitMetricEvidence` enforces the `Org1MSP` submitter allow-list, exact
top-level submission fields, versioned constants, identifier and hash formats,
decimal-string integer encodings, `0 <= numerator <= denominator`, and a
positive denominator. It recomputes

```text
ppm = floor((numerator * 1,000,000 + floor(denominator / 2)) / denominator)
```

entirely with JavaScript `BigInt`, rejects a one-ppm mismatch, and rejects an
existing composite identity instead of overwriting it. A successful call
writes the 26-field ledger record, project and developer secondary indexes, and
the `M4MetricEvidenceSubmitted` event. Transaction ID, timestamp, submitter MSP,
and the domain-separated submitter identity hash are derived from the Fabric
context rather than accepted from the client.

The immutable primary identity is project, window, developer hash, metric, and
policy version. For the canonical `urllib3_W03` submission, the independently
derived record ID is:

```text
72ca9db25cfcd77fdbe95592a2b1b2debbf9bbf006a16a419dd97a31c7b57309
```

## Validation coverage

The 34 passing Node tests cover:

- the exact six-method transaction surface and exact 26-field record shape;
- all submission-to-record mappings, deterministic record ID, submitter hash,
  transaction metadata, three state writes, and event content;
- existence, read, history, project-index, and developer-index behavior;
- duplicate and unauthorized-submitter rejection before additional writes;
- exact missing/additional-field rejection and malformed/non-object JSON;
- metric and policy constants, identifiers, Git hashes, and SHA-256 formats;
- invalid decimal encodings, zero denominator, and numerator above denominator;
- one-ppm arithmetic tampering;
- zero share, full share, exact half, half-ppm upward rounding, and integers
  larger than `Number.MAX_SAFE_INTEGER`.

The validator also confirms the installed and locked Fabric dependencies, the
deployable npm package contents, and the production-dependency audit:

| Quantity | Result |
|---|---:|
| `fabric-contract-api` | 2.5.8 |
| `fabric-shim` | 2.5.8 |
| Node / npm used for local validation | v24.13.0 / 11.7.0 |
| Tests passed / total | 34 / 34 |
| npm audit findings | 0 |
| Packaged files | 3 |
| Unpacked package size | 15,053 bytes |
| Required ledger-record fields | 26 |

## Reproducibility commitments

The source commitment is SHA-256 over a domain-separated sequence containing
`index.js` and `lib/m4-evidence-contract.js`, their relative names, raw bytes,
and NUL separators.

| Committed object | SHA-256 |
|---|---|
| Chaincode source set | `9f41f699a0cd0c8db239c8ccdcf8b9ac3113ec65b26a9872b4015173a5b0d0be` |
| `package-lock.json` | `f16d29bd8ce1295b79a68313ad359c66bbb25f45cca2d13218a715ec8cfb20c0` |
| Canonical ledger submission | `077e65f900aedc0f066cc01725a62f721c314a0932cdcd3b6f722c0c17a14fbe` |

Reproduce the complete local check from the Phase 3 directory with:

```powershell
python scripts/validate_chaincode_unit.py
```

The machine-readable result is
`out/chaincode_unit_validation_summary.csv`; the corresponding key-value log
is `logs/chaincode_unit_validation.log`.

## Remaining claims to test on Fabric

The local tests show that the contract logic gives the intended result for the
tested inputs. They do not show that two peers produce matching endorsements,
that the channel policy requires both organizations, that an unauthorized
network identity is rejected in a real proposal, or that committed state,
history, and events are observable through Fabric Gateway. Those are the next
integration acceptance tests. Chaincode also cannot establish whether a
well-formed submitted hash corresponds to true Git evidence; that remains an
off-chain replay responsibility by design.
