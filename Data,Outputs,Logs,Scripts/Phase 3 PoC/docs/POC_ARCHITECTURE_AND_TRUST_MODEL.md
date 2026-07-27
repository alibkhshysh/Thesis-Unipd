# Baseline M4 PoC architecture and trust model

## Status

Design ID: `M4_HYBRID_FABRIC_POC`  
Design version: `1.0.0`  
Metric policy: `M4_DEVELOPER_CHURN_SHARE_POLICY` version `1.0.0`

This document froze the implementation boundary before the verifier and
chaincode were written. The off-chain verifier, local chaincode tests, and live
Fabric test-network evaluation now satisfy their corresponding gates. This is a
thesis-scale demonstrator, not a production network or a complete reputation
system.

## Platform decision

The baseline freezes Hyperledger Fabric `2.5.15` from the 2.5 LTS line. The
official Fabric test network provides two peer organizations and
an ordering organization through Docker Compose. It is explicitly intended for
education and testing, not as a production topology.

The implementation uses:

- the official `fabric-samples/test-network`;
- `Org1MSP` and `Org2MSP`, one peer each;
- a single-node Raft ordering service;
- channel `mychannel`;
- default GoLevelDB state;
- JavaScript chaincode named `m4evidence`;
- `fabric-contract-api` and `fabric-shim` version `2.5.8`;
- an endorsement policy requiring both Org1 and Org2 peers;
- `Org1MSP` as the baseline authorized evidence submitter.

Primary platform sources:

- https://hyperledger-fabric.readthedocs.io/en/latest/test_network.html
- https://hyperledger-fabric.readthedocs.io/en/latest/deploy_chaincode.html
- https://github.com/hyperledger/fabric/releases/tag/v2.5.15

## Component boundary

```text
Pinned Git repository / Git bundle
                |
                v
        Off-chain verifier
        - ancestry check
        - Git numstat extraction
        - bot and identity policy
        - M4 integer calculation
        - artifact/policy/manifest hashing
                |
                | canonical manifest + compact submission
                v
  Fabric Gateway / transaction proposal
                |
                v
       m4evidence chaincode
       - submitter authorization
       - format/range checks
       - integer ppm recomputation
       - duplicate prevention
       - compact state + indexes + event
                |
                v
       Fabric ledger and history
                |
                v
      Independent auditor replay
```

Repository traversal and developer aggregation remain off-chain. Chaincode does
not have filesystem or Git access and cannot independently establish whether a
commit is an ancestor, whether an author is human, or whether changed code is
semantically valuable.

## Evidence layers

### 1. Evidence artifact

The replayable repository evidence should be a Git bundle or an equivalently
pinned repository artifact containing the required commits. The artifact is
hashed as raw bytes with SHA-256. Its storage reference and persistence class
are recorded, but the ledger cannot guarantee future availability.

### 2. Evidence manifest

`M4_EVIDENCE_MANIFEST` contains:

- policy identity and canonical policy hash;
- project and repository identity;
- release-window tags and commit hashes;
- ancestry and primary/sensitivity classification;
- pseudonymous developer identity;
- human and excluded-bot extraction totals;
- exact integer numerator, denominator, scale, and ppm value;
- evidence-artifact hash and storage reference;
- verifier identity, version, and source hash.

The manifest deliberately excludes generation time, local paths, transaction
IDs, and Fabric identity metadata. Therefore identical evidence and verifier
versions produce identical canonical manifest bytes and the same manifest hash.

### 3. Ledger submission

`M4_LEDGER_SUBMISSION` is the compact client payload. It repeats the fields the
chaincode must validate without retrieving the manifest:

- project, window, and developer hashes;
- metric and policy versions;
- numerator and denominator as decimal strings;
- ppm value as an integer;
- from/to commit hashes;
- policy, manifest, and artifact SHA-256 commitments;
- storage reference and persistence class.

Numerator and denominator use decimal strings in JSON so JavaScript never loses
precision before converting them to `BigInt`.

### 4. Ledger record

`M4_LEDGER_RECORD` contains the validated submission plus ledger-derived data:

- deterministic record ID;
- Fabric submitter MSP and hashed client identity;
- Fabric transaction ID;
- transaction timestamp;
- `ACTIVE` status.

The baseline record is immutable. A different record with the same composite
identity is rejected instead of overwriting evidence.

## Canonical hashing rules

Policy and manifest objects are hashed after canonical serialization:

1. UTF-8 encoding;
2. object keys sorted lexicographically;
3. arrays retained in their declared semantic order;
4. no insignificant whitespace;
5. no NaN or Infinity;
6. metric quantities represented as integers;
7. no trailing newline in the bytes passed to SHA-256.

The evidence manifest does not contain its own hash. Its SHA-256 is calculated
over the complete canonical manifest and placed in the ledger submission.

Domain-separated identity hashes are:

```text
developer_id_hash = SHA256(
    UTF8("m4-developer-id-v1") || NUL || UTF8(canonical_email)
)

submitter_id_hash = SHA256(
    UTF8("m4-fabric-submitter-v1") || NUL || UTF8(Fabric_client_identity)
)

record_id = SHA256(
    UTF8("m4-record-id-v1") || NUL ||
    UTF8(project_id) || NUL ||
    UTF8(window_id) || NUL ||
    UTF8(developer_id_hash) || NUL ||
    UTF8(metric_id) || NUL ||
    UTF8(policy_version)
)
```

## Chaincode transaction rules

`SubmitMetricEvidence(submissionJson)` must:

1. parse exactly one JSON submission;
2. require `Org1MSP` as the submitting client MSP in the baseline;
3. reject unknown or additional top-level fields;
4. validate schema, metric, and policy constants;
5. validate identifier and SHA-256 formats;
6. parse numerator and denominator with `BigInt`;
7. require `0 <= numerator <= denominator` and `denominator > 0`;
8. recompute ppm with the frozen integer formula;
9. reject a mismatching submitted ppm;
10. derive the composite key and reject an existing record;
11. derive the record ID, submitter hash, transaction ID, and timestamp;
12. store the canonical record;
13. write project and developer secondary indexes;
14. emit `M4MetricEvidenceSubmitted`.

Read and query operations do not modify state. Secondary composite-key entries
support project and developer queries without requiring CouchDB rich queries.

## Trust model

| Actor/component | Trusted for | Not trusted or not able to establish |
|---|---|---|
| Evidence submitter | Authentic Fabric transaction under its configured X.509 MSP identity | Correct Git analysis merely because it submitted a value |
| Off-chain verifier | Deterministic application of the frozen policy when its source/version is trusted | Real-world developer identity or semantic code quality |
| Chaincode | Authorization, arithmetic, duplicate prevention, state transition, commitments | Git ancestry, bot truth, archive contents, external availability |
| Fabric peers/orderer | Endorsed execution and ledger ordering under the configured network assumptions | Truth of off-chain evidence not checked by chaincode |
| Artifact storage | Returning bytes at a reference | Integrity unless returned bytes match the committed hash; permanent availability |
| Independent auditor | Replay and comparison with committed hashes | Correct interpretation if it uses a different policy/version |

Org1 is the evidence-verifier/submitter organization in the baseline. Org2
endorses the chaincode transition and acts as a second ledger participant. This
does not prove Org1's evidence is true; auditability comes from the pinned
artifact, open verifier, deterministic policy, and committed hashes.

## Threats and controls

| Threat | Baseline control | Residual limitation |
|---|---|---|
| Modified manifest or artifact | SHA-256 commitments | Hashes do not provide availability |
| Wrong ppm arithmetic | Chaincode recomputes with `BigInt` | Chaincode still trusts numerator/denominator evidence |
| Duplicate submission | Immutable composite-key check | A different policy version creates a distinct record |
| Unauthorized submitter | MSP allow-list plus Fabric identity | Test-network identity policy is simpler than production governance |
| Divergent release tags | Off-chain ancestry gate committed in the manifest | Chaincode cannot replay Git ancestry |
| Policy substitution | Policy ID, version, and policy hash | Auditor must possess the matching policy artifact |
| Bot misclassification | Frozen regex and bot audit totals | Heuristic false positives/negatives remain possible |
| Email aliasing/spoofing | Canonical email and domain-separated pseudonymous hash | No proof of real-world control; aliases are unresolved |
| Churn inflation or meaningless edits | Repository evidence remains replayable | Semantic gaming is observable but not automatically prevented |
| Ledger participant collusion | Two-organization endorsement for writes | A two-organization educational network is not Byzantine-resilient governance |

## Acceptance criteria for implementation

The design step is complete only when:

- all schemas parse and share the same metric/policy constants;
- calculation quantities cannot pass through JavaScript floating point;
- manifest hashing excludes dynamic ledger fields;
- chaincode arithmetic matches the Python policy implementation;
- duplicate, malformed, arithmetic-mismatch, and unauthorized submissions are
  covered by tests;
- the `urllib3_W03` fixture can be reproduced from Git and its committed artifact;
- an independent rerun produces byte-identical manifest and submission files.

All criteria above pass. The unchanged chaincode was also installed and
approved on both peers, committed with a decoded two-peer endorsement policy,
and evaluated through actual Org1 and Org2 X.509 MSP identities. All 17 Gateway
checks and 47 independent network checks pass, including two-peer reads,
queries, history, event delivery, negative proposals, and peer-local
confirmation that the accepted transaction has validation code 0 in block 6.
The measured network evidence is recorded in `FABRIC_NETWORK_REPORT.md`.
