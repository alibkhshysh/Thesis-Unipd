'use strict';

const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const fs = require('node:fs/promises');
const path = require('node:path');
const { TextDecoder } = require('node:util');

const grpc = require('@grpc/grpc-js');
const { connect, hash, signers } = require('@hyperledger/fabric-gateway');

const PHASE3_DIR = path.resolve(__dirname, '..', '..');
const TEST_NETWORK_DIR = path.join(
    PHASE3_DIR,
    'fabric_runtime',
    'fabric-samples',
    'test-network',
);
const SUBMISSION_PATH = path.join(
    PHASE3_DIR,
    'evidence',
    'urllib3_W03',
    'ledger_submission_v1.json',
);
const RECORD_SCHEMA_PATH = path.join(PHASE3_DIR, 'spec', 'ledger_record_schema_v1.json');
const OUTPUT_PATH = path.join(PHASE3_DIR, 'out', 'fabric_gateway_integration_summary.json');
const LOG_PATH = path.join(PHASE3_DIR, 'logs', 'fabric_gateway_integration.log');

const CHANNEL_NAME = 'mychannel';
const CHAINCODE_NAME = 'm4evidence';
const EVENT_NAME = 'M4MetricEvidenceSubmitted';
const EXPECTED_RECORD_ID = '72ca9db25cfcd77fdbe95592a2b1b2debbf9bbf006a16a419dd97a31c7b57309';
const decoder = new TextDecoder();

function canonicalJson(value) {
    if (Array.isArray(value)) {
        return `[${value.map(canonicalJson).join(',')}]`;
    }
    if (value !== null && typeof value === 'object') {
        return `{${Object.keys(value).sort().map((key) => (
            `${JSON.stringify(key)}:${canonicalJson(value[key])}`
        )).join(',')}}`;
    }
    return JSON.stringify(value);
}

function sha256(bytes) {
    return crypto.createHash('sha256').update(bytes).digest('hex');
}

function domainHash(domain, values) {
    return sha256(Buffer.from(`${domain}\u0000${values.join('\u0000')}`, 'utf8'));
}

async function firstFile(directory) {
    const entries = (await fs.readdir(directory)).sort();
    assert.ok(entries.length > 0, `No files found in ${directory}`);
    return path.join(directory, entries[0]);
}

function orgProfile(orgNumber) {
    const orgName = `org${orgNumber}.example.com`;
    const peerName = `peer0.${orgName}`;
    const cryptoRoot = path.join(
        TEST_NETWORK_DIR,
        'organizations',
        'peerOrganizations',
        orgName,
    );
    return {
        mspId: `Org${orgNumber}MSP`,
        peerEndpoint: orgNumber === 1 ? 'localhost:7051' : 'localhost:9051',
        peerHostAlias: peerName,
        keyDirectory: path.join(
            cryptoRoot,
            'users',
            `User1@${orgName}`,
            'msp',
            'keystore',
        ),
        certDirectory: path.join(
            cryptoRoot,
            'users',
            `User1@${orgName}`,
            'msp',
            'signcerts',
        ),
        tlsCertPath: path.join(cryptoRoot, 'peers', peerName, 'tls', 'ca.crt'),
    };
}

async function openGateway(orgNumber) {
    const profile = orgProfile(orgNumber);
    const tlsRootCert = await fs.readFile(profile.tlsCertPath);
    const client = new grpc.Client(
        profile.peerEndpoint,
        grpc.credentials.createSsl(tlsRootCert),
        { 'grpc.ssl_target_name_override': profile.peerHostAlias },
    );
    const certificate = await fs.readFile(await firstFile(profile.certDirectory));
    const privateKeyPem = await fs.readFile(await firstFile(profile.keyDirectory));
    const privateKey = crypto.createPrivateKey(privateKeyPem);
    const gateway = connect({
        client,
        identity: { mspId: profile.mspId, credentials: certificate },
        signer: signers.newPrivateKeySigner(privateKey),
        hash: hash.sha256,
        evaluateOptions: () => ({ deadline: Date.now() + 15_000 }),
        endorseOptions: () => ({ deadline: Date.now() + 60_000 }),
        submitOptions: () => ({ deadline: Date.now() + 15_000 }),
        commitStatusOptions: () => ({ deadline: Date.now() + 60_000 }),
    });
    const network = gateway.getNetwork(CHANNEL_NAME);
    return {
        client,
        gateway,
        network,
        contract: network.getContract(CHAINCODE_NAME),
        mspId: profile.mspId,
    };
}

function decodeJson(bytes) {
    return JSON.parse(decoder.decode(bytes));
}

function errorText(error) {
    const parts = [];
    const seen = new Set();
    function add(value) {
        if (typeof value === 'string' && value.length > 0 && !seen.has(value)) {
            seen.add(value);
            parts.push(value);
        }
    }
    if (error && typeof error === 'object') {
        add(error.message);
        add(error.details);
        if (Array.isArray(error.details)) {
            for (const detail of error.details) {
                if (typeof detail === 'string') {
                    add(detail);
                } else if (detail && typeof detail === 'object') {
                    add(detail.message);
                    add(detail.details);
                }
            }
        }
        if (error.cause) {
            add(error.cause.message);
            add(error.cause.details);
        }
    }
    add(String(error));
    return parts.join(' | ');
}

async function expectRejected(action, expectedPattern) {
    try {
        await action();
    } catch (error) {
        const text = errorText(error);
        assert.match(text, expectedPattern);
        return text;
    }
    assert.fail(`Expected rejection matching ${expectedPattern}`);
}

function withTimeout(promise, milliseconds, label) {
    let timer;
    const timeout = new Promise((resolve, reject) => {
        timer = setTimeout(() => reject(new Error(`${label} timed out`)), milliseconds);
    });
    return Promise.race([promise, timeout]).finally(() => clearTimeout(timer));
}

async function waitForEvent(events) {
    for await (const event of events) {
        if (event.eventName === EVENT_NAME) {
            return {
                blockNumber: event.blockNumber.toString(),
                transactionId: event.transactionId,
                eventName: event.eventName,
                payload: decodeJson(event.payload),
            };
        }
    }
    throw new Error(`Event stream ended before ${EVENT_NAME}`);
}

function lookupArguments(submission) {
    return [
        submission.projectId,
        submission.windowId,
        submission.developerIdHash,
        submission.metricId,
        submission.policyVersion,
    ];
}

async function evaluateJson(contract, transactionName, ...args) {
    return decodeJson(await contract.evaluateTransaction(transactionName, ...args));
}

async function writeResults(summary) {
    await fs.mkdir(path.dirname(OUTPUT_PATH), { recursive: true });
    await fs.mkdir(path.dirname(LOG_PATH), { recursive: true });
    await fs.writeFile(OUTPUT_PATH, `${JSON.stringify(summary, null, 2)}\n`, 'utf8');
    const logFields = [
        ['validation_id', summary.validationId],
        ['validation_status', summary.validationStatus],
        ['checks_total', summary.checksTotal],
        ['checks_passed', summary.checksPassed],
        ['channel_name', summary.channelName],
        ['chaincode_name', summary.chaincodeName],
        ['transaction_id', summary.transactionId],
        ['block_number', summary.blockNumber],
        ['record_id', summary.recordId],
        ['recorded_at', summary.recordedAt],
        ['event_name', summary.eventName],
        ['submission_sha256', summary.submissionSha256],
        ['record_canonical_sha256', summary.recordCanonicalSha256],
    ];
    await fs.writeFile(
        LOG_PATH,
        `${logFields.map(([key, value]) => `${key}=${value}`).join('\n')}\n`,
        'utf8',
    );
}

async function main() {
    const checks = [];
    const pass = (checkId, detail = 'pass') => checks.push({ checkId, status: 'pass', detail });
    const submissionBytes = await fs.readFile(SUBMISSION_PATH);
    const submissionJson = submissionBytes.toString('utf8');
    const submission = JSON.parse(submissionJson);
    const recordSchema = JSON.parse(await fs.readFile(RECORD_SCHEMA_PATH, 'utf8'));
    const lookup = lookupArguments(submission);
    const expectedRecordId = domainHash('m4-record-id-v1', [
        submission.projectId,
        submission.windowId,
        submission.developerIdHash,
        submission.metricId,
        submission.policyVersion,
    ]);
    assert.equal(expectedRecordId, EXPECTED_RECORD_ID);
    pass('independent_record_id', expectedRecordId);

    const org1 = await openGateway(1);
    const org2 = await openGateway(2);
    let events;
    try {
        assert.equal(await evaluateJson(org1.contract, 'MetricEvidenceExists', ...lookup), false);
        pass('initial_state_absent');

        const malformedError = await expectRejected(
            () => org1.contract.submitTransaction('SubmitMetricEvidence', '{'),
            /submissionJson is not valid JSON/,
        );
        pass('malformed_json_rejected', malformedError);

        const arithmeticMutation = structuredClone(submission);
        arithmeticMutation.metricValuePpm += 1;
        const arithmeticError = await expectRejected(
            () => org1.contract.submitTransaction(
                'SubmitMetricEvidence',
                JSON.stringify(arithmeticMutation),
            ),
            /arithmetic mismatch: expected 307183/,
        );
        pass('one_ppm_mutation_rejected', arithmeticError);

        const unauthorizedError = await expectRejected(
            () => org2.contract.submitTransaction('SubmitMetricEvidence', submissionJson),
            /MSP Org2MSP is not authorized/,
        );
        pass('org2_submitter_rejected', unauthorizedError);

        assert.equal(await evaluateJson(org1.contract, 'MetricEvidenceExists', ...lookup), false);
        pass('negative_cases_created_no_state');

        events = await org1.network.getChaincodeEvents(CHAINCODE_NAME);
        const eventPromise = withTimeout(waitForEvent(events), 60_000, 'chaincode event');
        const submitted = await org1.contract.submitAsync('SubmitMetricEvidence', {
            arguments: [submissionJson],
            endorsingOrganizations: ['Org1MSP', 'Org2MSP'],
        });
        const proposalRecord = decodeJson(submitted.getResult());
        const commitStatus = await submitted.getStatus();
        assert.equal(commitStatus.successful, true);
        pass('submit_committed_valid', commitStatus.transactionId);

        const event = await eventPromise;
        assert.equal(event.transactionId, commitStatus.transactionId);
        assert.equal(event.blockNumber, commitStatus.blockNumber.toString());
        assert.equal(event.eventName, EVENT_NAME);
        pass('gateway_chaincode_event_received', event.eventName);

        assert.deepEqual(Object.keys(proposalRecord).sort(), [...recordSchema.required].sort());
        assert.equal(proposalRecord.recordId, EXPECTED_RECORD_ID);
        assert.equal(proposalRecord.transactionId, commitStatus.transactionId);
        assert.equal(proposalRecord.submitterMspId, 'Org1MSP');
        assert.match(proposalRecord.submitterIdHash, /^[0-9a-f]{64}$/);
        assert.equal(proposalRecord.metricValuePpm, 307183);
        assert.equal(proposalRecord.numeratorChurn, '325');
        assert.equal(proposalRecord.denominatorChurn, '1058');
        assert.equal(new Date(proposalRecord.recordedAt).toISOString(), proposalRecord.recordedAt);
        pass('proposal_record_exact_schema');

        const expectedEventPayload = {
            recordId: proposalRecord.recordId,
            projectId: submission.projectId,
            windowId: submission.windowId,
            developerIdHash: submission.developerIdHash,
            metricId: submission.metricId,
            policyVersion: submission.policyVersion,
        };
        assert.deepEqual(event.payload, expectedEventPayload);
        pass('event_payload_exact');

        assert.equal(await evaluateJson(org1.contract, 'MetricEvidenceExists', ...lookup), true);
        pass('committed_state_exists');

        const org1Record = await evaluateJson(org1.contract, 'ReadMetricEvidence', ...lookup);
        const org2Record = await evaluateJson(org2.contract, 'ReadMetricEvidence', ...lookup);
        assert.deepEqual(org1Record, proposalRecord);
        assert.deepEqual(org2Record, proposalRecord);
        pass('both_peers_read_identical_record');

        const projectRecords = await evaluateJson(
            org1.contract,
            'QueryByProject',
            submission.projectId,
        );
        assert.deepEqual(projectRecords, [proposalRecord]);
        pass('project_index_query');

        const developerRecords = await evaluateJson(
            org2.contract,
            'QueryByDeveloper',
            submission.developerIdHash,
        );
        assert.deepEqual(developerRecords, [proposalRecord]);
        pass('developer_index_query');

        const history = await evaluateJson(
            org1.contract,
            'GetMetricEvidenceHistory',
            ...lookup,
        );
        assert.equal(history.length, 1);
        assert.equal(history[0].transactionId, commitStatus.transactionId);
        assert.equal(history[0].recordedAt, proposalRecord.recordedAt);
        assert.equal(history[0].isDelete, false);
        assert.deepEqual(history[0].value, proposalRecord);
        pass('ledger_history_exact');

        const duplicateError = await expectRejected(
            () => org1.contract.submitTransaction('SubmitMetricEvidence', submissionJson),
            /already exists for this composite identity/,
        );
        pass('duplicate_rejected', duplicateError);

        const recordAfterDuplicate = await evaluateJson(
            org2.contract,
            'ReadMetricEvidence',
            ...lookup,
        );
        assert.deepEqual(recordAfterDuplicate, proposalRecord);
        pass('duplicate_preserved_original_state');

        const summary = {
            validationId: 'M4_FABRIC_GATEWAY_INTEGRATION_V1',
            validationStatus: 'pass',
            checksTotal: checks.length,
            checksPassed: checks.filter((check) => check.status === 'pass').length,
            channelName: CHANNEL_NAME,
            chaincodeName: CHAINCODE_NAME,
            submittingMspId: 'Org1MSP',
            endorsingOrganizations: ['Org1MSP', 'Org2MSP'],
            transactionId: commitStatus.transactionId,
            blockNumber: commitStatus.blockNumber.toString(),
            recordId: proposalRecord.recordId,
            recordedAt: proposalRecord.recordedAt,
            eventName: event.eventName,
            submissionSha256: sha256(submissionBytes),
            recordCanonicalSha256: sha256(Buffer.from(canonicalJson(proposalRecord), 'utf8')),
            checks,
        };
        assert.equal(summary.checksTotal, summary.checksPassed);
        await writeResults(summary);
        console.log(JSON.stringify(summary, null, 2));
    } finally {
        events?.close();
        org1.gateway.close();
        org1.client.close();
        org2.gateway.close();
        org2.client.close();
    }
}

main().catch((error) => {
    console.error(error);
    process.exitCode = 1;
});
