'use strict';

const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');

const M4EvidenceContract = require('../lib/m4-evidence-contract');

const PHASE3_DIR = path.resolve(__dirname, '..', '..', '..');
const SUBMISSION_PATH = path.join(
    PHASE3_DIR,
    'evidence',
    'urllib3_W03',
    'ledger_submission_v1.json',
);
const RECORD_SCHEMA_PATH = path.join(PHASE3_DIR, 'spec', 'ledger_record_schema_v1.json');
const CLIENT_ID = 'x509::/OU=client/CN=org1-verifier::/C=US/O=Hyperledger/OU=Fabric/CN=ca.org1.example.com';
const TX_ID = '0123456789abcdef'.repeat(4);
const TX_TIME = '2026-07-26T12:34:56.123Z';

function loadJson(filePath) {
    return JSON.parse(fs.readFileSync(filePath, 'utf8'));
}

function clone(value) {
    return JSON.parse(JSON.stringify(value));
}

function timestampFromIso(isoValue) {
    const milliseconds = Date.parse(isoValue);
    return {
        seconds: BigInt(Math.floor(milliseconds / 1000)),
        nanos: (milliseconds % 1000) * 1_000_000,
    };
}

class MockIterator {
    constructor(entries) {
        this.entries = entries;
        this.position = 0;
        this.closed = false;
    }

    async next() {
        if (this.position >= this.entries.length) {
            return { done: true };
        }
        const value = this.entries[this.position];
        this.position += 1;
        return { done: false, value };
    }

    async close() {
        this.closed = true;
    }
}

class MockStub {
    constructor() {
        this.state = new Map();
        this.history = new Map();
        this.events = [];
        this.txId = TX_ID;
        this.timestamp = timestampFromIso(TX_TIME);
    }

    createCompositeKey(objectType, attributes) {
        return `\u0000${objectType}\u0000${attributes.join('\u0000')}\u0000`;
    }

    async getState(key) {
        return this.state.get(key) || Buffer.alloc(0);
    }

    async putState(key, value) {
        const stored = Buffer.from(value);
        this.state.set(key, stored);
        const entries = this.history.get(key) || [];
        entries.push({
            txId: this.txId,
            timestamp: this.timestamp,
            isDelete: false,
            value: stored,
        });
        this.history.set(key, entries);
    }

    getTxID() {
        return this.txId;
    }

    getTxTimestamp() {
        return this.timestamp;
    }

    setEvent(name, payload) {
        this.events.push({ name, payload: Buffer.from(payload) });
    }

    async getStateByPartialCompositeKey(objectType, attributes) {
        const prefix = this.createCompositeKey(objectType, attributes);
        const entries = [...this.state.entries()]
            .filter(([key]) => key.startsWith(prefix))
            .sort(([left], [right]) => (left < right ? -1 : left > right ? 1 : 0))
            .map(([key, value]) => ({ key, value }));
        return new MockIterator(entries);
    }

    async getHistoryForKey(key) {
        return new MockIterator(this.history.get(key) || []);
    }
}

function context(mspId = 'Org1MSP', clientId = CLIENT_ID) {
    return {
        stub: new MockStub(),
        clientIdentity: {
            getMSPID: () => mspId,
            getID: () => clientId,
        },
    };
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

function manualDomainHash(domain, values) {
    return crypto
        .createHash('sha256')
        .update(Buffer.from(`${domain}\u0000${values.join('\u0000')}`, 'utf8'))
        .digest('hex');
}

test('contract exposes exactly the six frozen public transactions', () => {
    const transactionMethods = Object.getOwnPropertyNames(M4EvidenceContract.prototype)
        .filter((name) => name !== 'constructor')
        .sort();
    assert.deepEqual(transactionMethods, [
        'GetMetricEvidenceHistory',
        'MetricEvidenceExists',
        'QueryByDeveloper',
        'QueryByProject',
        'ReadMetricEvidence',
        'SubmitMetricEvidence',
    ]);
});

test('generated ledger submission produces the exact immutable record schema', async () => {
    const contract = new M4EvidenceContract();
    const ctx = context();
    const submission = loadJson(SUBMISSION_PATH);
    const record = JSON.parse(await contract.SubmitMetricEvidence(ctx, JSON.stringify(submission)));
    const schema = loadJson(RECORD_SCHEMA_PATH);

    assert.deepEqual(Object.keys(record).sort(), [...schema.required].sort());
    assert.equal(record.docType, 'm4MetricEvidence');
    assert.equal(record.schemaId, 'M4_LEDGER_RECORD');
    assert.equal(record.schemaVersion, '1.0.0');
    assert.equal(record.status, 'ACTIVE');
    assert.equal(record.submitterMspId, 'Org1MSP');
    assert.equal(record.transactionId, TX_ID);
    assert.equal(record.recordedAt, TX_TIME);
    assert.match(record.recordId, /^[0-9a-f]{64}$/);
    assert.match(record.submitterIdHash, /^[0-9a-f]{64}$/);

    for (const field of [
        'projectId', 'windowId', 'developerIdHash', 'metricId', 'metricVersion',
        'metricValuePpm', 'numeratorChurn', 'denominatorChurn', 'fromCommitHash',
        'toCommitHash', 'policyId', 'policyVersion', 'analysisPolicyHash',
        'evidenceManifestHash', 'evidenceArtifactHash', 'storageReference',
        'storagePersistence',
    ]) {
        assert.deepEqual(record[field], submission[field], `record field ${field}`);
    }

    const expectedRecordId = manualDomainHash('m4-record-id-v1', [
        submission.projectId,
        submission.windowId,
        submission.developerIdHash,
        submission.metricId,
        submission.policyVersion,
    ]);
    const expectedSubmitterHash = manualDomainHash('m4-fabric-submitter-v1', [CLIENT_ID]);
    assert.equal(record.recordId, expectedRecordId);
    assert.equal(record.submitterIdHash, expectedSubmitterHash);
    assert.equal(ctx.stub.state.size, 3);
    assert.equal(ctx.stub.events.length, 1);
    assert.equal(ctx.stub.events[0].name, 'M4MetricEvidenceSubmitted');
    const event = JSON.parse(ctx.stub.events[0].payload.toString('utf8'));
    assert.equal(event.recordId, record.recordId);
    assert.equal(event.projectId, 'urllib3');
    assert.equal(event.windowId, 'urllib3_W03');
});

test('exists and read return the submitted fixture record', async () => {
    const contract = new M4EvidenceContract();
    const ctx = context();
    const submission = loadJson(SUBMISSION_PATH);
    assert.equal(await contract.MetricEvidenceExists(ctx, ...lookupArguments(submission)), false);
    const submitted = await contract.SubmitMetricEvidence(ctx, JSON.stringify(submission));
    assert.equal(await contract.MetricEvidenceExists(ctx, ...lookupArguments(submission)), true);
    assert.equal(await contract.ReadMetricEvidence(ctx, ...lookupArguments(submission)), submitted);
});

test('duplicate composite identity is rejected without additional writes', async () => {
    const contract = new M4EvidenceContract();
    const ctx = context();
    const submission = loadJson(SUBMISSION_PATH);
    await contract.SubmitMetricEvidence(ctx, JSON.stringify(submission));
    const stateSize = ctx.stub.state.size;
    const eventCount = ctx.stub.events.length;
    await assert.rejects(
        contract.SubmitMetricEvidence(ctx, JSON.stringify(submission)),
        /already exists/,
    );
    assert.equal(ctx.stub.state.size, stateSize);
    assert.equal(ctx.stub.events.length, eventCount);
});

test('Org2 submitter is rejected before any state write', async () => {
    const contract = new M4EvidenceContract();
    const ctx = context('Org2MSP');
    const submission = loadJson(SUBMISSION_PATH);
    await assert.rejects(
        contract.SubmitMetricEvidence(ctx, JSON.stringify(submission)),
        /not authorized/,
    );
    assert.equal(ctx.stub.state.size, 0);
    assert.equal(ctx.stub.events.length, 0);
});

test('one-ppm mutation is rejected by BigInt recomputation', async () => {
    const contract = new M4EvidenceContract();
    const ctx = context();
    const submission = loadJson(SUBMISSION_PATH);
    submission.metricValuePpm += 1;
    await assert.rejects(
        contract.SubmitMetricEvidence(ctx, JSON.stringify(submission)),
        /arithmetic mismatch: expected 307183/,
    );
    assert.equal(ctx.stub.state.size, 0);
});

test('numerator greater than denominator is rejected', async () => {
    const contract = new M4EvidenceContract();
    const ctx = context();
    const submission = loadJson(SUBMISSION_PATH);
    submission.numeratorChurn = '1059';
    await assert.rejects(
        contract.SubmitMetricEvidence(ctx, JSON.stringify(submission)),
        /less than or equal/,
    );
});

test('BigInt arithmetic handles boundaries, half-up rounding, and values above Number safety', async (t) => {
    const contract = new M4EvidenceContract();
    const base = loadJson(SUBMISSION_PATH);
    const cases = [
        ['zero share', '0', '1', 0],
        ['full share', '1', '1', 1_000_000],
        ['exact half', '1', '2', 500_000],
        ['half-ppm rounds upward', '1', '128', 7_813],
        ['above Number.MAX_SAFE_INTEGER', '9007199254740993', '18014398509481986', 500_000],
    ];
    for (const [name, numerator, denominator, expectedPpm] of cases) {
        await t.test(name, async () => {
            const submission = clone(base);
            submission.windowId = `${base.windowId}:${name.replaceAll(' ', '_')}`;
            submission.numeratorChurn = numerator;
            submission.denominatorChurn = denominator;
            submission.metricValuePpm = expectedPpm;
            const record = JSON.parse(
                await contract.SubmitMetricEvidence(context(), JSON.stringify(submission)),
            );
            assert.equal(record.metricValuePpm, expectedPpm);
            assert.equal(record.numeratorChurn, numerator);
            assert.equal(record.denominatorChurn, denominator);
        });
    }
});

test('missing and additional fields are rejected exactly', async (t) => {
    const contract = new M4EvidenceContract();
    const submission = loadJson(SUBMISSION_PATH);
    await t.test('missing field', async () => {
        const mutated = clone(submission);
        delete mutated.evidenceManifestHash;
        await assert.rejects(
            contract.SubmitMetricEvidence(context(), JSON.stringify(mutated)),
            /missing=\[evidenceManifestHash\]/,
        );
    });
    await t.test('additional field', async () => {
        const mutated = clone(submission);
        mutated.unexpected = true;
        await assert.rejects(
            contract.SubmitMetricEvidence(context(), JSON.stringify(mutated)),
            /additional=\[unexpected\]/,
        );
    });
});

test('malformed JSON and non-object JSON are rejected', async (t) => {
    const contract = new M4EvidenceContract();
    await t.test('malformed JSON', async () => {
        await assert.rejects(contract.SubmitMetricEvidence(context(), '{'), /not valid JSON/);
    });
    await t.test('array JSON', async () => {
        await assert.rejects(contract.SubmitMetricEvidence(context(), '[]'), /one JSON object/);
    });
});

test('invalid decimal encodings are rejected before BigInt parsing', async (t) => {
    const contract = new M4EvidenceContract();
    const base = loadJson(SUBMISSION_PATH);
    const cases = [
        ['leading zero numerator', 'numeratorChurn', '0325'],
        ['negative numerator', 'numeratorChurn', '-1'],
        ['zero denominator', 'denominatorChurn', '0'],
        ['scientific denominator', 'denominatorChurn', '1e3'],
    ];
    for (const [name, field, value] of cases) {
        await t.test(name, async () => {
            const submission = clone(base);
            submission[field] = value;
            await assert.rejects(
                contract.SubmitMetricEvidence(context(), JSON.stringify(submission)),
                new RegExp(`${field} has an invalid format`),
            );
        });
    }
});

test('invalid constants, hashes, and fixed-point type are rejected', async (t) => {
    const contract = new M4EvidenceContract();
    const base = loadJson(SUBMISSION_PATH);
    const cases = [
        ['metric constant', 'metricId', 'M2_CHURN', /metricId must equal/],
        ['policy version', 'policyVersion', '2.0.0', /policyVersion must equal/],
        ['uppercase hash', 'analysisPolicyHash', base.analysisPolicyHash.toUpperCase(), /invalid format/],
        ['short commit', 'fromCommitHash', 'abc123', /invalid format/],
        ['floating ppm', 'metricValuePpm', 307183.1, /must be an integer/],
    ];
    for (const [name, field, value, pattern] of cases) {
        await t.test(name, async () => {
            const submission = clone(base);
            submission[field] = value;
            await assert.rejects(
                contract.SubmitMetricEvidence(context(), JSON.stringify(submission)),
                pattern,
            );
        });
    }
});

test('project and developer secondary-index queries return the record', async () => {
    const contract = new M4EvidenceContract();
    const ctx = context();
    const submission = loadJson(SUBMISSION_PATH);
    const submitted = JSON.parse(
        await contract.SubmitMetricEvidence(ctx, JSON.stringify(submission)),
    );
    const byProject = JSON.parse(await contract.QueryByProject(ctx, submission.projectId));
    const byDeveloper = JSON.parse(
        await contract.QueryByDeveloper(ctx, submission.developerIdHash),
    );
    assert.deepEqual(byProject, [submitted]);
    assert.deepEqual(byDeveloper, [submitted]);
    assert.deepEqual(JSON.parse(await contract.QueryByProject(ctx, 'absent-project')), []);
});

test('history exposes Fabric transaction metadata and immutable value', async () => {
    const contract = new M4EvidenceContract();
    const ctx = context();
    const submission = loadJson(SUBMISSION_PATH);
    const submitted = JSON.parse(
        await contract.SubmitMetricEvidence(ctx, JSON.stringify(submission)),
    );
    const history = JSON.parse(
        await contract.GetMetricEvidenceHistory(ctx, ...lookupArguments(submission)),
    );
    assert.equal(history.length, 1);
    assert.equal(history[0].transactionId, TX_ID);
    assert.equal(history[0].recordedAt, TX_TIME);
    assert.equal(history[0].isDelete, false);
    assert.deepEqual(history[0].value, submitted);
});

test('missing record read fails while missing history is empty', async () => {
    const contract = new M4EvidenceContract();
    const ctx = context();
    const submission = loadJson(SUBMISSION_PATH);
    await assert.rejects(
        contract.ReadMetricEvidence(ctx, ...lookupArguments(submission)),
        /does not exist/,
    );
    assert.deepEqual(
        JSON.parse(await contract.GetMetricEvidenceHistory(ctx, ...lookupArguments(submission))),
        [],
    );
});

test('invalid transaction identity metadata is rejected before writing', async () => {
    const contract = new M4EvidenceContract();
    const ctx = context();
    ctx.stub.txId = 'not-a-fabric-transaction-id';
    const submission = loadJson(SUBMISSION_PATH);
    await assert.rejects(
        contract.SubmitMetricEvidence(ctx, JSON.stringify(submission)),
        /transactionId has an invalid format/,
    );
    assert.equal(ctx.stub.state.size, 0);
});
