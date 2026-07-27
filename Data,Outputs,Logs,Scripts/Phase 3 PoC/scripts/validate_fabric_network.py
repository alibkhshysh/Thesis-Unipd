#!/usr/bin/env python3
"""Independently validate the live Fabric deployment and committed M4 record."""

from __future__ import annotations

import base64
import csv
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import tarfile
import tempfile
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
PHASE3_DIR = SCRIPT_DIR.parent
RUNTIME_DIR = PHASE3_DIR / "fabric_runtime"
SAMPLES_DIR = RUNTIME_DIR / "fabric-samples"
NETWORK_DIR = SAMPLES_DIR / "test-network"
BIN_DIR = SAMPLES_DIR / "bin"
CHAINCODE_DIR = PHASE3_DIR / "chaincode" / "m4evidence"
STAGED_DIR = RUNTIME_DIR / "staged_chaincode" / "m4evidence"
GATEWAY_DIR = PHASE3_DIR / "integration" / "fabric_gateway"
INTEGRATION_SUMMARY = PHASE3_DIR / "out" / "fabric_gateway_integration_summary.json"
CHAINCODE_UNIT_SUMMARY = PHASE3_DIR / "out" / "chaincode_unit_validation_summary.csv"
BUNDLE_PATH = PHASE3_DIR / "artifacts" / "urllib3_W03.git.bundle"
MANIFEST_PATH = PHASE3_DIR / "evidence" / "urllib3_W03" / "evidence_manifest_v1.json"
SUBMISSION_PATH = PHASE3_DIR / "evidence" / "urllib3_W03" / "ledger_submission_v1.json"
PACKAGE_PATH = NETWORK_DIR / "m4evidence.tar.gz"
OUTPUT_PATH = PHASE3_DIR / "out" / "fabric_network_validation_summary.csv"
POLICY_OUTPUT_PATH = PHASE3_DIR / "out" / "fabric_chaincode_endorsement_policy.json"
LOG_PATH = PHASE3_DIR / "logs" / "fabric_network_validation.log"

EXPECTED_SAMPLES_COMMIT = "65592350d7d7c51b02c8a4d89383d4bbdcc45725"
EXPECTED_PACKAGE_ID = (
    "m4evidence_1.0:"
    "5e767ab94efbb4a63b8958f44249b0c0c2d7cede71738593c813282f091fabb7"
)
EXPECTED_RECORD_ID = "72ca9db25cfcd77fdbe95592a2b1b2debbf9bbf006a16a419dd97a31c7b57309"
EXPECTED_BUNDLE_HASH = "a41205eff782ce4af65f345e0afb97f16fd8677af215c7bdd06f460ce9602272"
EXPECTED_SUBMISSION_HASH = "077e65f900aedc0f066cc01725a62f721c314a0932cdcd3b6f722c0c17a14fbe"
EXPECTED_JQ_HASH = "23cb60a1354eed6bcc8d9b9735e8c7b388cd1fdcb75726b93bc299ef22dd9334"
EXPECTED_IMAGE_DIGESTS = {
    "hyperledger/fabric-peer:2.5.15": "3e25adc31a757ee19dd8a24afdc9ac5aa46a86b3cb56fc93068b0e594706d6aa",
    "hyperledger/fabric-orderer:2.5.15": "9972c209be47f45e377a24c88f2e3d21fae4dc224751c68bdd33f2e7a603ffa8",
    "hyperledger/fabric-ccenv:2.5.15": "86dded7eda9268e2cbf3691cb952edf545dc5faea1a79bfc9b47ec47d3ecfa9e",
    "hyperledger/fabric-baseos:2.5.15": "654bd4554bf97c70902e56d530294795372518da7ae2a7cdfccbe397a878c513",
    "hyperledger/fabric-ca:1.5.17": "453a0a727e82c4960b797e379adc231e853ee23ae7526db53afef77b5074117e",
    "hyperledger/fabric-nodeenv:2.5": "17e2d447ca0de5b4e3f6950a1c9b24ecfdeecdd90e111e11d771970d35159bf1",
}
INFRA_CONTAINERS = {
    "peer0.org1.example.com": EXPECTED_IMAGE_DIGESTS["hyperledger/fabric-peer:2.5.15"],
    "peer0.org2.example.com": EXPECTED_IMAGE_DIGESTS["hyperledger/fabric-peer:2.5.15"],
    "orderer.example.com": EXPECTED_IMAGE_DIGESTS["hyperledger/fabric-orderer:2.5.15"],
}
RUNTIME_FILES = [
    "index.js",
    "lib/m4-evidence-contract.js",
    "package-lock.json",
    "package.json",
]
SUMMARY_FIELDS = [
    "validation_id",
    "validation_status",
    "checks_total",
    "fabric_version",
    "fabric_commit",
    "fabric_ca_version",
    "fabric_samples_commit",
    "docker_server_version",
    "docker_compose_version",
    "jq_version",
    "gateway_version",
    "grpc_version",
    "npm_audit_total",
    "channel_name",
    "channel_height",
    "infrastructure_containers_running",
    "chaincode_containers_running",
    "chaincode_name",
    "chaincode_version",
    "chaincode_sequence",
    "package_id",
    "package_sha256",
    "package_bytes",
    "package_source_files",
    "org1_approved",
    "org2_approved",
    "endorsement_policy",
    "gateway_checks_passed",
    "gateway_checks_total",
    "transaction_id",
    "transaction_block",
    "transaction_validation_code",
    "record_id",
    "recorded_at",
    "event_name",
    "record_canonical_sha256",
    "bundle_sha256",
    "tampered_bundle_sha256",
    "tampered_replay_rejected",
]


def run(
    command: list[str],
    *,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        command,
        cwd=cwd,
        env=env,
        text=True,
        capture_output=True,
        encoding="utf-8",
        errors="strict",
        check=False,
    )
    if check and result.returncode != 0:
        raise RuntimeError(
            f"Command failed ({result.returncode}): {' '.join(command)}\n"
            f"STDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
        )
    return result


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def read_json(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"Expected JSON object: {path}")
    return value


def version_value(output: str, label: str) -> str:
    match = re.search(rf"^\s*{re.escape(label)}:\s*(\S+)\s*$", output, re.MULTILINE)
    if not match:
        raise RuntimeError(f"Could not parse {label} from:\n{output}")
    return match.group(1)


def peer_environment(org_number: int) -> dict[str, str]:
    org_name = f"org{org_number}.example.com"
    peer_name = f"peer0.{org_name}"
    org_root = NETWORK_DIR / "organizations" / "peerOrganizations" / org_name
    environment = os.environ.copy()
    environment.update(
        {
            "FABRIC_CFG_PATH": str(SAMPLES_DIR / "config"),
            "CORE_PEER_TLS_ENABLED": "true",
            "CORE_PEER_LOCALMSPID": f"Org{org_number}MSP",
            "CORE_PEER_TLS_ROOTCERT_FILE": str(org_root / "peers" / peer_name / "tls" / "ca.crt"),
            "CORE_PEER_MSPCONFIGPATH": str(
                org_root / "users" / f"Admin@{org_name}" / "msp"
            ),
            "CORE_PEER_ADDRESS": "localhost:7051" if org_number == 1 else "localhost:9051",
        }
    )
    return environment


def peer_json(arguments: list[str], org_number: int) -> dict:
    result = run(
        [str(BIN_DIR / "peer.exe"), *arguments],
        cwd=NETWORK_DIR,
        env=peer_environment(org_number),
    )
    value = json.loads(result.stdout)
    if not isinstance(value, dict):
        raise RuntimeError("Peer output was not a JSON object")
    return value


def decode_proto(payload: bytes, message_type: str, temp_dir: Path) -> dict:
    input_path = temp_dir / "decode_input.pb"
    output_path = temp_dir / "decode_output.json"
    input_path.write_bytes(payload)
    run(
        [
            str(BIN_DIR / "configtxlator.exe"),
            "proto_decode",
            "--input",
            str(input_path),
            "--type",
            message_type,
            "--output",
            str(output_path),
        ]
    )
    return read_json(output_path)


def validate_policy(validation_parameter: str, temp_dir: Path) -> dict:
    application_policy = decode_proto(
        base64.b64decode(validation_parameter),
        "common.ApplicationPolicy",
        temp_dir,
    )
    signature_policy = application_policy["signature_policy"]
    rule = signature_policy["rule"]["n_out_of"]
    if rule != {"n": 2, "rules": [{"signed_by": 0}, {"signed_by": 1}]}:
        raise RuntimeError(f"Unexpected signature rule: {rule}")
    principals: list[dict[str, str]] = []
    for identity in signature_policy["identities"]:
        if identity["principal_classification"] != "ROLE":
            raise RuntimeError(f"Unexpected principal classification: {identity}")
        role = decode_proto(
            base64.b64decode(identity["principal"]),
            "common.MSPRole",
            temp_dir,
        )
        principals.append({"mspId": role["msp_identifier"], "role": role["role"]})
    if principals != [
        {"mspId": "Org1MSP", "role": "PEER"},
        {"mspId": "Org2MSP", "role": "PEER"},
    ]:
        raise RuntimeError(f"Unexpected endorsement principals: {principals}")
    return {
        "policyType": "signature",
        "threshold": 2,
        "principals": principals,
        "validationParameterBase64": validation_parameter,
    }


def validate_chaincode_package() -> tuple[str, int, int]:
    package_bytes = PACKAGE_PATH.read_bytes()
    package_hash = sha256_bytes(package_bytes)
    if EXPECTED_PACKAGE_ID != f"m4evidence_1.0:{package_hash}":
        raise RuntimeError("Package hash does not match the frozen package ID")
    with tarfile.open(fileobj=io.BytesIO(package_bytes), mode="r:gz") as outer:
        if sorted(member.name for member in outer.getmembers()) != ["code.tar.gz", "metadata.json"]:
            raise RuntimeError("Unexpected outer chaincode package contents")
        metadata = json.loads(outer.extractfile("metadata.json").read())
        if metadata != {
            "path": "../../staged_chaincode/m4evidence",
            "type": "node",
            "label": "m4evidence_1.0",
        }:
            raise RuntimeError(f"Unexpected chaincode metadata: {metadata}")
        code_bytes = outer.extractfile("code.tar.gz").read()
    with tarfile.open(fileobj=io.BytesIO(code_bytes), mode="r:gz") as inner:
        members = {member.name: member for member in inner.getmembers() if member.isfile()}
        expected_names = [f"src/{name.replace(os.sep, '/')}" for name in RUNTIME_FILES]
        if sorted(members) != sorted(expected_names):
            raise RuntimeError(f"Unexpected packaged source files: {sorted(members)}")
        for relative_name in RUNTIME_FILES:
            package_name = f"src/{relative_name.replace(os.sep, '/')}"
            packaged_bytes = inner.extractfile(members[package_name]).read()
            original_bytes = (CHAINCODE_DIR / relative_name).read_bytes()
            staged_bytes = (STAGED_DIR / relative_name).read_bytes()
            if packaged_bytes != original_bytes or staged_bytes != original_bytes:
                raise RuntimeError(f"Staged/package bytes differ for {relative_name}")
    return package_hash, len(package_bytes), len(members)


def validate_images() -> None:
    for image, expected_digest in EXPECTED_IMAGE_DIGESTS.items():
        inspected = json.loads(run(["docker", "image", "inspect", image]).stdout)[0]
        digests = inspected.get("RepoDigests", [])
        if not any(value.endswith(f"@sha256:{expected_digest}") for value in digests):
            raise RuntimeError(f"Image digest mismatch for {image}: {digests}")
        if inspected["Os"] != "linux" or inspected["Architecture"] != "amd64":
            raise RuntimeError(f"Unexpected image platform for {image}")


def validate_containers() -> tuple[int, int]:
    for name, expected_image_id in INFRA_CONTAINERS.items():
        container = json.loads(run(["docker", "inspect", name]).stdout)[0]
        if not container["State"]["Running"] or container["RestartCount"] != 0:
            raise RuntimeError(f"Infrastructure container is not healthy: {name}")
        if container["Image"] != f"sha256:{expected_image_id}":
            raise RuntimeError(f"Infrastructure image mismatch: {name}")
    chaincode_names = [
        line.strip()
        for line in run(
            ["docker", "ps", "--filter", "name=dev-peer0", "--format", "{{.Names}}"]
        ).stdout.splitlines()
        if line.strip()
    ]
    if len(chaincode_names) != 2 or not all(EXPECTED_PACKAGE_ID.split(":", 1)[1] in name for name in chaincode_names):
        raise RuntimeError(f"Unexpected chaincode containers: {chaincode_names}")
    for name in chaincode_names:
        container = json.loads(run(["docker", "inspect", name]).stdout)[0]
        labels = container["Config"]["Labels"]
        if not container["State"]["Running"] or container["RestartCount"] != 0:
            raise RuntimeError(f"Chaincode container is not healthy: {name}")
        if labels.get("org.hyperledger.fabric.version") != "v2.5.15":
            raise RuntimeError(f"Unexpected peer builder version: {labels}")
        if labels.get("org.opencontainers.image.version") != "2.5.8":
            raise RuntimeError(f"Unexpected Node chaincode version: {labels}")
    return len(INFRA_CONTAINERS), len(chaincode_names)


def validate_block(
    transaction_id: str,
    block_number: int,
    temp_dir: Path,
    org_number: int,
) -> tuple[int, int]:
    block_path = temp_dir / f"committed_org{org_number}.block"
    block_json_path = temp_dir / f"committed_block_org{org_number}.json"
    block_result = run(
        [
            str(BIN_DIR / "peer.exe"),
            "chaincode",
            "query",
            "-C",
            "mychannel",
            "-n",
            "qscc",
            "-c",
            json.dumps({"Args": ["GetBlockByNumber", "mychannel", str(block_number)]}),
            "--hex",
        ],
        cwd=NETWORK_DIR,
        env=peer_environment(org_number),
    )
    try:
        block_path.write_bytes(bytes.fromhex(block_result.stdout.strip()))
    except ValueError as error:
        raise RuntimeError(f"Org{org_number} QSCC did not return a hexadecimal block") from error
    run(
        [
            str(BIN_DIR / "configtxlator.exe"),
            "proto_decode",
            "--input",
            str(block_path),
            "--type",
            "common.Block",
            "--output",
            str(block_json_path),
        ]
    )
    block = read_json(block_json_path)
    if int(block["header"]["number"]) != block_number:
        raise RuntimeError(f"Org{org_number} returned the wrong transaction block")
    entries = block["data"]["data"]
    transaction_ids = [entry["payload"]["header"]["channel_header"]["tx_id"] for entry in entries]
    if transaction_id not in transaction_ids:
        raise RuntimeError(
            f"Transaction not present in Org{org_number} block: {transaction_ids}"
        )
    transaction_index = transaction_ids.index(transaction_id)
    validation_codes = base64.b64decode(block["metadata"]["metadata"][2])
    validation_code = validation_codes[transaction_index]
    if validation_code != 0:
        raise RuntimeError(
            f"Org{org_number} transaction validation code is {validation_code}, not VALID(0)"
        )
    return len(entries), validation_code


def validate_tampered_replay() -> tuple[str, bool]:
    original = BUNDLE_PATH.read_bytes()
    if sha256_bytes(original) != EXPECTED_BUNDLE_HASH:
        raise RuntimeError("Canonical bundle hash changed")
    tampered = bytearray(original)
    tampered[0] ^= 1
    tampered_hash = sha256_bytes(tampered)
    if tampered_hash == EXPECTED_BUNDLE_HASH:
        raise RuntimeError("Tampered bundle unexpectedly retained the committed hash")
    with tempfile.TemporaryDirectory(prefix="m4-tampered-replay-") as temp_name:
        temp_dir = Path(temp_name)
        tampered_path = temp_dir / "tampered.bundle"
        tampered_path.write_bytes(tampered)
        result = run(
            [
                os.fspath(Path(os.sys.executable)),
                str(SCRIPT_DIR / "replay_m4_evidence.py"),
                "--bundle",
                str(tampered_path),
                "--output",
                str(temp_dir / "summary.csv"),
                "--log-file",
                str(temp_dir / "replay.log"),
            ],
            check=False,
        )
    if result.returncode == 0:
        raise RuntimeError("Tampered bundle unexpectedly passed independent replay")
    return tampered_hash, True


def write_csv(path: Path, row: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=SUMMARY_FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerow(row)


def main() -> int:
    checks = 0

    def passed(condition: bool, message: str) -> None:
        nonlocal checks
        if not condition:
            raise RuntimeError(message)
        checks += 1

    peer_version_output = run([str(BIN_DIR / "peer.exe"), "version"]).stdout
    fabric_version = version_value(peer_version_output, "Version")
    fabric_commit = version_value(peer_version_output, "Commit SHA")
    passed(fabric_version == "v2.5.15" and fabric_commit == "83c7930", "Fabric binary changed")

    ca_version_output = run([str(BIN_DIR / "fabric-ca-client.exe"), "version"]).stdout
    fabric_ca_version = version_value(ca_version_output, "Version")
    passed(fabric_ca_version == "v1.5.17", "Fabric CA binary changed")

    samples_commit = run(["git", "rev-parse", "HEAD"], cwd=SAMPLES_DIR).stdout.strip()
    passed(samples_commit == EXPECTED_SAMPLES_COMMIT, "Fabric samples commit changed")

    jq_version = run([str(BIN_DIR / "jq.exe"), "--version"]).stdout.strip()
    passed(jq_version == "jq-1.8.1" and sha256_file(BIN_DIR / "jq.exe") == EXPECTED_JQ_HASH, "jq changed")

    docker_info = run(["docker", "version", "--format", "{{.Server.Version}}|{{.Server.Os}}|{{.Server.Arch}}"])
    docker_version, docker_os, docker_arch = docker_info.stdout.strip().split("|")
    passed(docker_os == "linux" and docker_arch == "amd64", "Docker platform changed")
    compose_version = run(["docker", "compose", "version", "--short"]).stdout.strip()
    checks += 1

    validate_images()
    checks += len(EXPECTED_IMAGE_DIGESTS)
    infra_count, chaincode_container_count = validate_containers()
    checks += infra_count + chaincode_container_count

    package_hash, package_bytes, package_file_count = validate_chaincode_package()
    checks += package_file_count + 2
    calculated_package_id = run(
        [str(BIN_DIR / "peer.exe"), "lifecycle", "chaincode", "calculatepackageid", str(PACKAGE_PATH)],
        env=peer_environment(1),
    ).stdout.strip()
    passed(calculated_package_id == EXPECTED_PACKAGE_ID, "Calculated package ID changed")

    installed_ids: list[str] = []
    definitions: list[dict] = []
    for org_number in [1, 2]:
        installed = peer_json(
            ["lifecycle", "chaincode", "queryinstalled", "--output", "json"],
            org_number,
        )
        ids = [entry["package_id"] for entry in installed["installed_chaincodes"]]
        passed(EXPECTED_PACKAGE_ID in ids, f"Package is absent from Org{org_number}")
        installed_ids.append(EXPECTED_PACKAGE_ID)
        definitions.append(
            peer_json(
                [
                    "lifecycle",
                    "chaincode",
                    "querycommitted",
                    "--channelID",
                    "mychannel",
                    "--name",
                    "m4evidence",
                    "--output",
                    "json",
                ],
                org_number,
            )
        )
    passed(definitions[0] == definitions[1], "Peers report different committed definitions")
    definition = definitions[0]
    passed(definition["sequence"] == 1 and definition["version"] == "1.0", "Wrong definition version")
    passed(definition["approvals"] == {"Org1MSP": True, "Org2MSP": True}, "Approvals changed")

    integration = read_json(INTEGRATION_SUMMARY)
    passed(integration["validationStatus"] == "pass", "Gateway integration did not pass")
    passed(integration["checksPassed"] == integration["checksTotal"] == 17, "Gateway check count changed")
    passed(integration["recordId"] == EXPECTED_RECORD_ID, "Committed record ID changed")
    passed(integration["submissionSha256"] == EXPECTED_SUBMISSION_HASH, "Submission hash changed")
    passed(sha256_file(SUBMISSION_PATH) == EXPECTED_SUBMISSION_HASH, "Submission bytes changed")

    with CHAINCODE_UNIT_SUMMARY.open("r", encoding="utf-8", newline="") as handle:
        unit_summary = next(csv.DictReader(handle))
    passed(unit_summary["validation_status"] == "pass", "Chaincode unit validation changed")

    gateway_lock = read_json(GATEWAY_DIR / "package-lock.json")
    gateway_version = gateway_lock["packages"]["node_modules/@hyperledger/fabric-gateway"]["version"]
    grpc_version = gateway_lock["packages"]["node_modules/@grpc/grpc-js"]["version"]
    passed(gateway_version == "1.10.1" and grpc_version == "1.14.4", "Gateway dependencies changed")
    npm = shutil.which("npm")
    if not npm:
        raise RuntimeError("npm is required for Gateway dependency validation")
    audit = json.loads(
        run([npm, "audit", "--omit=dev", "--json"], cwd=GATEWAY_DIR).stdout
    )
    audit_total = audit["metadata"]["vulnerabilities"]["total"]
    passed(audit_total == 0, "Gateway npm audit is not clean")

    manifest = read_json(MANIFEST_PATH)
    passed(manifest["evidenceArtifact"]["sha256"] == EXPECTED_BUNDLE_HASH, "Manifest bundle hash changed")
    tampered_hash, tampered_rejected = validate_tampered_replay()
    checks += 3

    with tempfile.TemporaryDirectory(prefix="m4-fabric-validation-") as temp_name:
        temp_dir = Path(temp_name)
        policy = validate_policy(definition["validation_parameter"], temp_dir)
        checks += 4
        block_results = [
            validate_block(
                integration["transactionId"],
                int(integration["blockNumber"]),
                temp_dir,
                org_number,
            )
            for org_number in (1, 2)
        ]
        block_entries, validation_code = block_results[0]
        passed(
            all(entries >= 1 and code == validation_code for entries, code in block_results),
            "The peers did not return the same valid transaction-block result",
        )

    POLICY_OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    POLICY_OUTPUT_PATH.write_text(
        json.dumps(policy, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )

    channel_output = run(
        [str(BIN_DIR / "peer.exe"), "channel", "getinfo", "-c", "mychannel"],
        cwd=NETWORK_DIR,
        env=peer_environment(1),
    ).stdout
    channel_match = re.search(r"Blockchain info:\s*(\{.*\})", channel_output)
    if not channel_match:
        raise RuntimeError(f"Could not parse channel info: {channel_output}")
    channel_info = json.loads(channel_match.group(1))
    passed(channel_info["height"] >= 7, "Channel height is below the measured result")

    row: dict[str, object] = {
        "validation_id": "M4_FABRIC_NETWORK_VALIDATION_V1",
        "validation_status": "pass",
        "checks_total": checks,
        "fabric_version": fabric_version,
        "fabric_commit": fabric_commit,
        "fabric_ca_version": fabric_ca_version,
        "fabric_samples_commit": samples_commit,
        "docker_server_version": docker_version,
        "docker_compose_version": compose_version,
        "jq_version": jq_version,
        "gateway_version": gateway_version,
        "grpc_version": grpc_version,
        "npm_audit_total": audit_total,
        "channel_name": "mychannel",
        "channel_height": channel_info["height"],
        "infrastructure_containers_running": infra_count,
        "chaincode_containers_running": chaincode_container_count,
        "chaincode_name": "m4evidence",
        "chaincode_version": definition["version"],
        "chaincode_sequence": definition["sequence"],
        "package_id": EXPECTED_PACKAGE_ID,
        "package_sha256": package_hash,
        "package_bytes": package_bytes,
        "package_source_files": package_file_count,
        "org1_approved": str(definition["approvals"]["Org1MSP"]).lower(),
        "org2_approved": str(definition["approvals"]["Org2MSP"]).lower(),
        "endorsement_policy": "AND('Org1MSP.peer','Org2MSP.peer')",
        "gateway_checks_passed": integration["checksPassed"],
        "gateway_checks_total": integration["checksTotal"],
        "transaction_id": integration["transactionId"],
        "transaction_block": integration["blockNumber"],
        "transaction_validation_code": validation_code,
        "record_id": integration["recordId"],
        "recorded_at": integration["recordedAt"],
        "event_name": integration["eventName"],
        "record_canonical_sha256": integration["recordCanonicalSha256"],
        "bundle_sha256": EXPECTED_BUNDLE_HASH,
        "tampered_bundle_sha256": tampered_hash,
        "tampered_replay_rejected": str(tampered_rejected).lower(),
    }
    write_csv(OUTPUT_PATH, row)
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    LOG_PATH.write_text(
        "\n".join(f"{field}={row[field]}" for field in SUMMARY_FIELDS) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(
        f"Validated Fabric network: {checks} checks passed; transaction "
        f"{integration['transactionId']} is VALID in block {integration['blockNumber']}."
    )
    print(f"Package ID: {EXPECTED_PACKAGE_ID}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
