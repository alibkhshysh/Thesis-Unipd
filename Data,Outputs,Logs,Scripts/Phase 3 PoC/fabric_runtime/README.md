# Reconstructing the local Fabric runtime

This directory holds ignored, reproducible runtime dependencies for the Phase 3
PoC. The committed evidence, integration client, validators, and reports live
one directory above; the large upstream sample checkout, generated network
material, deployment staging, and installed dependencies are intentionally not
source artifacts.

The commands below describe the measured Windows/Git-Bash run. They recreate an
ephemeral educational network and therefore generate new certificates,
transaction IDs, timestamps, and channel blocks.

## 1. Prerequisites and short path

Start Docker Desktop and confirm that Linux containers are available. From
PowerShell, create the short path used to avoid the space in the workspace
path:

```powershell
$runtimeTarget = 'E:\Thesis Unipd\Data,Outputs,Logs,Scripts\Phase 3 PoC\fabric_runtime'
if (-not (Test-Path -LiteralPath 'E:\fabric_poc_runtime')) {
    New-Item -ItemType Junction -Path 'E:\fabric_poc_runtime' -Target $runtimeTarget
}
docker version
docker compose version
```

The junction points to this runtime directory; it does not duplicate source or
evidence files.

## 2. Frozen Fabric tools and samples

In Git Bash:

```bash
cd /e/fabric_poc_runtime
curl -sSLO https://raw.githubusercontent.com/hyperledger/fabric/main/scripts/install-fabric.sh
bash install-fabric.sh --fabric-version 2.5.15 --ca-version 1.5.17 samples binary docker
git -C fabric-samples checkout --detach 65592350d7d7c51b02c8a4d89383d4bbdcc45725
```

The official installer did not expose a `fabric-samples v2.5.15` tag during the
measured run, so the sample checkout is pinned explicitly. Verify:

```bash
fabric-samples/bin/peer version
fabric-samples/bin/fabric-ca-client version
git -C fabric-samples rev-parse HEAD
```

The measured binary results are Fabric `v2.5.15` commit `83c7930` and Fabric CA
`v1.5.17`. The local `fabric-samples/bin/jq.exe` is jq `1.8.1`; its expected
SHA-256 is
`23cb60a1354eed6bcc8d9b9735e8c7b388cd1fdcb75726b93bc299ef22dd9334`.

## 3. Stage the exact chaincode runtime

The Windows Fabric packager did not traverse the source junction reliably, so
copy only the four deployment inputs into the ignored staging directory. From
PowerShell at the Phase 3 root:

```powershell
$source = 'chaincode\m4evidence'
$stage = 'fabric_runtime\staged_chaincode\m4evidence'
New-Item -ItemType Directory -Force -Path "$stage\lib" | Out-Null
Copy-Item -LiteralPath "$source\index.js" -Destination "$stage\index.js"
Copy-Item -LiteralPath "$source\package.json" -Destination "$stage\package.json"
Copy-Item -LiteralPath "$source\package-lock.json" -Destination "$stage\package-lock.json"
Copy-Item -LiteralPath "$source\lib\m4-evidence-contract.js" -Destination "$stage\lib\m4-evidence-contract.js"
```

Before deployment, compare each copied file with `Get-FileHash -Algorithm
SHA256`. The independent validator repeats this byte-level comparison and checks
the exact package contents.

## 4. Start the network and deploy

The tracked wrappers in `wrappers/` prevent MSYS from rewriting container paths
passed to Docker. In Git Bash:

```bash
export PATH="/e/fabric_poc_runtime/wrappers:/e/fabric_poc_runtime/fabric-samples/bin:$PATH"
cd /e/fabric_poc_runtime/fabric-samples/test-network
./network.sh down
./network.sh up createChannel -c mychannel
docker pull hyperledger/fabric-nodeenv:2.5
./network.sh deployCC \
  -c mychannel \
  -ccn m4evidence \
  -ccp /e/fabric_poc_runtime/staged_chaincode/m4evidence \
  -ccl javascript \
  -ccv 1.0 \
  -ccs 1 \
  -ccep "AND('Org1MSP.peer','Org2MSP.peer')"
```

No `-ca` option is used: the measured network generated its local MSP material
with `cryptogen`. The committed definition must show sequence 1 and approval by
both organizations.

## 5. Run the authenticated integration client

From PowerShell at the Phase 3 root:

```powershell
Set-Location integration\fabric_gateway
npm ci --no-fund
npm audit --omit=dev
npm run integration
Set-Location ..\..
```

Run the integration client only on a fresh network because the record is
immutable and a second valid submission is expected to be rejected as a
duplicate. The client uses the generated Org1 and Org2 `User1` certificates and
keys; it does not use mock identities.

## 6. Independently validate the live result

```powershell
$env:PYTHONDONTWRITEBYTECODE = '1'
python scripts\validate_fabric_network.py
```

The validator checks versions and digests, running topology, exact package
bytes, installation and approvals on both peers, decoded endorsement principals,
Gateway checks, dependency audit, peer-local block contents and validation
code, and rejection of a one-byte-tampered temporary bundle. The measured run
passed 47 checks and wrote its summary and log under `out/` and `logs/`.

When the ephemeral ledger is no longer needed, run `./network.sh down` from the
test-network directory with the wrapper/bin `PATH` still active.
