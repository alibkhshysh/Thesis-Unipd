# Fabric network deployment and integration report

## Scope and result

The unchanged `m4evidence` JavaScript chaincode was deployed to a local
Hyperledger Fabric two-organization test network and exercised through real
Fabric Gateway connections and X.509 MSP identities. The measured run passed
all 17 Gateway integration checks and all 47 independent network-validation
checks.

This result establishes the intended thesis-scale integration boundary: both
organizational peers endorsed the accepted write, the orderer committed it,
both peers returned the same state, and the Gateway delivered the chaincode
event. It is not a production-network, performance, availability, governance,
or Byzantine-resilience evaluation.

## Frozen environment

| Component | Measured version or commitment |
|---|---|
| Hyperledger Fabric binaries | `v2.5.15`, commit `83c7930` |
| Fabric CA binaries | `v1.5.17` |
| `fabric-samples` | detached commit `65592350d7d7c51b02c8a4d89383d4bbdcc45725` |
| Docker Engine | `29.4.3`, Linux/amd64 |
| Docker Compose | `5.1.3` |
| Node.js Gateway API | `@hyperledger/fabric-gateway` `1.10.1` |
| gRPC client | `@grpc/grpc-js` `1.14.4` |
| `jq` | `1.8.1` |
| State database | GoLevelDB |
| Channel | `mychannel` |

Fabric `v2.5.15` is a deliberately frozen release from the Fabric 2.5 LTS
line, not a claim that it is the newest 2.5 patch. The official installer did
not provide a `fabric-samples` tag named `v2.5.15`, so the sample repository was
detached at the exact compatible commit shown above. The network generated its
local X.509 MSP material with `cryptogen`; although the CA image and binaries
were installed as part of the frozen tool set, no Fabric CA service was used in
this run.

The validated container image digests were:

| Image | Digest |
|---|---|
| `hyperledger/fabric-peer:2.5.15` | `sha256:3e25adc31a757ee19dd8a24afdc9ac5aa46a86b3cb56fc93068b0e594706d6aa` |
| `hyperledger/fabric-orderer:2.5.15` | `sha256:9972c209be47f45e377a24c88f2e3d21fae4dc224751c68bdd33f2e7a603ffa8` |
| `hyperledger/fabric-ccenv:2.5.15` | `sha256:86dded7eda9268e2cbf3691cb952edf545dc5faea1a79bfc9b47ec47d3ecfa9e` |
| `hyperledger/fabric-baseos:2.5.15` | `sha256:654bd4554bf97c70902e56d530294795372518da7ae2a7cdfccbe397a878c513` |
| `hyperledger/fabric-ca:1.5.17` | `sha256:453a0a727e82c4960b797e379adc231e853ee23ae7526db53afef77b5074117e` |
| `hyperledger/fabric-nodeenv:2.5` | `sha256:17e2d447ca0de5b4e3f6950a1c9b24ecfdeecdd90e111e11d771970d35159bf1` |

The Node builder is published under the compatible minor tag `2.5`; the
validated image identifies its chaincode Node runtime as `2.5.8`.

## Topology and deployment

The official educational test-network topology ran three infrastructure
containers: one Raft orderer, `peer0.org1.example.com`, and
`peer0.org2.example.com`. Both peers joined `mychannel`. The chaincode definition
was committed as:

| Property | Value |
|---|---|
| Name | `m4evidence` |
| Version / sequence | `1.0` / `1` |
| Package source files | 4 |
| Package size | 13,275 bytes |
| Package ID | `m4evidence_1.0:5e767ab94efbb4a63b8958f44249b0c0c2d7cede71738593c813282f091fabb7` |
| Endorsement policy | `AND('Org1MSP.peer','Org2MSP.peer')` |
| Org1 / Org2 approval | `true` / `true` |

The independent validator decoded the channel validation parameter rather than
trusting its display string. It contains a threshold of two with the
`Org1MSP PEER` and `Org2MSP PEER` principals.

Only the four runtime files required by the contract were staged and packaged:
`index.js`, `lib/m4-evidence-contract.js`, `package.json`, and
`package-lock.json`. Each staged file was checked byte-for-byte against the
locally validated source. The Windows workspace contains spaces, so a short
junction path and small Docker argument-conversion wrappers were required for
the upstream Bash scripts; these affect invocation only, not chaincode bytes or
Fabric policy.

## Authenticated Gateway checks

The integration client used the actual `User1` key and certificate from each
organization. A valid Org1 proposal explicitly requested endorsements from
both organizations. The following 17 checks passed:

1. independently derive the expected record ID;
2. establish that the record is initially absent;
3. reject malformed JSON;
4. reject a one-ppm arithmetic mutation;
5. reject an Org2 submission under the Org1-only submitter policy;
6. confirm rejected proposals created no state;
7. commit the valid Org1 submission;
8. receive the Gateway chaincode event;
9. validate the exact 26-field proposed record;
10. validate the exact event payload;
11. establish that committed state exists;
12. read the identical record from both peers;
13. query it through the project index;
14. query it through the developer index;
15. retrieve the exact ledger history;
16. reject a duplicate submission; and
17. confirm duplicate rejection preserved the original state.

The committed transaction evidence is:

| Property | Value |
|---|---|
| Transaction ID | `960e5630c0427ca7f74c87930b4611646c9e124969efb31b6514dca5c95be031` |
| Block / validation code | `6` / `0` (`VALID`) |
| Record ID | `72ca9db25cfcd77fdbe95592a2b1b2debbf9bbf006a16a419dd97a31c7b57309` |
| Recorded at | `2026-07-26T13:21:13.565Z` |
| Event | `M4MetricEvidenceSubmitted` |
| Canonical record SHA-256 | `0f6840a59706211533ac4e84987a26baf89dccce222f8b61ef22bd443ebe3d29` |
| Submission SHA-256 | `077e65f900aedc0f066cc01725a62f721c314a0932cdcd3b6f722c0c17a14fbe` |

The channel height was seven immediately after the run. The independent Python
validator queried block 6 through each peer's local QSCC service, located the
transaction ID, and confirmed validation code 0; it did not rely only on the
Gateway client's success return.

## Artifact-integrity negative check

The canonical standalone Git bundle remained byte-identical with SHA-256
`a41205eff782ce4af65f345e0afb97f16fd8677af215c7bdd06f460ce9602272`.
The validator changed one byte only in a temporary copy, producing SHA-256
`debeb80119a125f617cfdc5ec33537460ab07625a49592711d56601e2f203fdf`.
The independent replay process rejected that copy, and the canonical bundle was
not modified. This is a separate off-chain commitment check: Fabric validates
the submitted commitment's form and immutable storage, but does not inspect Git
bundle contents.

## Reproducible evidence

The principal machine-readable evidence is:

- `out/fabric_gateway_integration_summary.json` — the 17 Gateway checks;
- `out/fabric_network_validation_summary.csv` — the 47 independent checks;
- `out/fabric_chaincode_endorsement_policy.json` — decoded policy principals;
- `logs/fabric_gateway_integration.log` — Gateway execution log;
- `logs/fabric_network_validation.log` — independent validation log; and
- `fabric_runtime/README.md` — reconstruction and execution procedure.

At evidence capture, the relevant source/output commitments were:

| Object | SHA-256 |
|---|---|
| Gateway runner | `d78fedc2e9a7c013e521e0c87769eba70c6d7c1db707ab01392e1a1e732f91c2` |
| Gateway dependency lock | `930b60fb7607503e44ca1bd78ada80405123ebcb89c94b0500b17f91543ff82b` |
| Network validator | `768a0edfcec07ed249f7d49616703882483a970f4233545705f8091a17e0183a` |
| Gateway summary | `889888bb1a4979731b1f5f0ddc3500bc19a1323be0df79649d431477798b6d31` |
| Network summary | `68b6525b3fe4857d36d7ecdbb902984eda1340a2e54d61bd805ce8f557cd030a` |

Official context: [Installing Hyperledger Fabric](https://hyperledger-fabric.readthedocs.io/en/latest/install.html),
[Using the Fabric test network](https://hyperledger-fabric.readthedocs.io/en/latest/test_network.html), and
[Fabric v2.5.15 release notes](https://github.com/hyperledger/fabric/releases/tag/v2.5.15).
