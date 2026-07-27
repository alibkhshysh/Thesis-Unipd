'use strict';

const crypto = require('node:crypto');
const { Contract } = require('fabric-contract-api');

const SCALE = 1_000_000n;
const ALLOWED_SUBMITTER_MSPS = new Set(['Org1MSP']);
const IDENTIFIER_PATTERN = /^[A-Za-z0-9._:-]{1,128}$/;
const MSP_PATTERN = /^[A-Za-z0-9._-]{1,64}$/;
const SHA256_PATTERN = /^[0-9a-f]{64}$/;
const GIT_COMMIT_PATTERN = /^[0-9a-f]{40}$/;
const UINT_DECIMAL_PATTERN = /^(0|[1-9][0-9]*)$/;
const POSITIVE_UINT_DECIMAL_PATTERN = /^[1-9][0-9]*$/;
const STORAGE_PERSISTENCE = new Set(['LOCAL_POC', 'CONTENT_ADDRESSED', 'EXTERNAL_DURABLE']);
const SUBMISSION_FIELDS = [
    'schemaId',
    'schemaVersion',
    'projectId',
    'windowId',
    'developerIdHash',
    'metricId',
    'metricVersion',
    'metricValuePpm',
    'numeratorChurn',
    'denominatorChurn',
    'fromCommitHash',
    'toCommitHash',
    'policyId',
    'policyVersion',
    'analysisPolicyHash',
    'evidenceManifestHash',
    'evidenceArtifactHash',
    'storageReference',
    'storagePersistence',
];

const PRIMARY_OBJECT_TYPE = 'm4record';
const PROJECT_INDEX_OBJECT_TYPE = 'm4project';
const DEVELOPER_INDEX_OBJECT_TYPE = 'm4developer';
const EVENT_NAME = 'M4MetricEvidenceSubmitted';

function sha256Domain(domain, values) {
    const chunks = [Buffer.from(domain, 'utf8'), Buffer.from([0])];
    values.forEach((value, index) => {
        chunks.push(Buffer.from(value, 'utf8'));
        if (index < values.length - 1) {
            chunks.push(Buffer.from([0]));
        }
    });
    return crypto.createHash('sha256').update(Buffer.concat(chunks)).digest('hex');
}

function recordIdFor(submission) {
    return sha256Domain('m4-record-id-v1', [
        submission.projectId,
        submission.windowId,
        submission.developerIdHash,
        submission.metricId,
        submission.policyVersion,
    ]);
}

function submitterIdHash(identity) {
    return sha256Domain('m4-fabric-submitter-v1', [identity]);
}

function assertString(value, field, minimum = 1, maximum = Number.MAX_SAFE_INTEGER) {
    if (typeof value !== 'string' || value.length < minimum || value.length > maximum) {
        throw new Error(`${field} must be a string with length ${minimum}..${maximum}`);
    }
}

function assertPattern(value, field, pattern) {
    assertString(value, field);
    if (!pattern.test(value)) {
        throw new Error(`${field} has an invalid format`);
    }
}

function assertConstant(value, field, expected) {
    if (value !== expected) {
        throw new Error(`${field} must equal ${expected}`);
    }
}

function parseSubmission(submissionJson) {
    assertString(submissionJson, 'submissionJson');
    let submission;
    try {
        submission = JSON.parse(submissionJson);
    } catch (error) {
        throw new Error(`submissionJson is not valid JSON: ${error.message}`);
    }
    if (submission === null || Array.isArray(submission) || typeof submission !== 'object') {
        throw new Error('submissionJson must contain one JSON object');
    }

    const actualFields = Object.keys(submission).sort();
    const expectedFields = [...SUBMISSION_FIELDS].sort();
    if (actualFields.length !== expectedFields.length ||
        actualFields.some((field, index) => field !== expectedFields[index])) {
        const missing = expectedFields.filter((field) => !actualFields.includes(field));
        const additional = actualFields.filter((field) => !expectedFields.includes(field));
        throw new Error(
            `submission fields differ from schema; missing=[${missing.join(',')}], additional=[${additional.join(',')}]`,
        );
    }

    assertConstant(submission.schemaId, 'schemaId', 'M4_LEDGER_SUBMISSION');
    assertConstant(submission.schemaVersion, 'schemaVersion', '1.0.0');
    assertPattern(submission.projectId, 'projectId', IDENTIFIER_PATTERN);
    assertPattern(submission.windowId, 'windowId', IDENTIFIER_PATTERN);
    assertPattern(submission.developerIdHash, 'developerIdHash', SHA256_PATTERN);
    assertConstant(submission.metricId, 'metricId', 'M4_DEVELOPER_CHURN_SHARE');
    assertConstant(submission.metricVersion, 'metricVersion', '1.0.0');
    if (!Number.isInteger(submission.metricValuePpm) ||
        submission.metricValuePpm < 0 || submission.metricValuePpm > Number(SCALE)) {
        throw new Error('metricValuePpm must be an integer in the range 0..1000000');
    }
    assertPattern(submission.numeratorChurn, 'numeratorChurn', UINT_DECIMAL_PATTERN);
    assertPattern(submission.denominatorChurn, 'denominatorChurn', POSITIVE_UINT_DECIMAL_PATTERN);
    assertPattern(submission.fromCommitHash, 'fromCommitHash', GIT_COMMIT_PATTERN);
    assertPattern(submission.toCommitHash, 'toCommitHash', GIT_COMMIT_PATTERN);
    assertConstant(submission.policyId, 'policyId', 'M4_DEVELOPER_CHURN_SHARE_POLICY');
    assertConstant(submission.policyVersion, 'policyVersion', '1.0.0');
    assertPattern(submission.analysisPolicyHash, 'analysisPolicyHash', SHA256_PATTERN);
    assertPattern(submission.evidenceManifestHash, 'evidenceManifestHash', SHA256_PATTERN);
    assertPattern(submission.evidenceArtifactHash, 'evidenceArtifactHash', SHA256_PATTERN);
    assertString(submission.storageReference, 'storageReference', 1, 2048);
    if (!STORAGE_PERSISTENCE.has(submission.storagePersistence)) {
        throw new Error('storagePersistence is not an allowed value');
    }

    const numerator = BigInt(submission.numeratorChurn);
    const denominator = BigInt(submission.denominatorChurn);
    if (numerator > denominator) {
        throw new Error('numeratorChurn must be less than or equal to denominatorChurn');
    }
    const recomputedPpm = (numerator * SCALE + denominator / 2n) / denominator;
    if (recomputedPpm !== BigInt(submission.metricValuePpm)) {
        throw new Error(
            `metricValuePpm arithmetic mismatch: expected ${recomputedPpm.toString()}`,
        );
    }
    return submission;
}

function timestampToISOString(timestamp) {
    if (!timestamp || timestamp.seconds === undefined || timestamp.nanos === undefined) {
        throw new Error('Fabric transaction timestamp is unavailable');
    }
    const seconds = BigInt(timestamp.seconds.toString());
    const nanos = Number(timestamp.nanos);
    if (!Number.isInteger(nanos) || nanos < 0 || nanos >= 1_000_000_000) {
        throw new Error('Fabric transaction timestamp nanoseconds are invalid');
    }
    const milliseconds = seconds * 1000n + BigInt(Math.floor(nanos / 1_000_000));
    if (milliseconds < -8_640_000_000_000_000n || milliseconds > 8_640_000_000_000_000n) {
        throw new Error('Fabric transaction timestamp is outside the supported Date range');
    }
    return new Date(Number(milliseconds)).toISOString();
}

function primaryKey(ctx, projectId, windowId, developerIdHash, metricId, policyVersion) {
    return ctx.stub.createCompositeKey(PRIMARY_OBJECT_TYPE, [
        projectId,
        windowId,
        developerIdHash,
        metricId,
        policyVersion,
    ]);
}

function validateLookupIdentity(projectId, windowId, developerIdHash, metricId, policyVersion) {
    assertPattern(projectId, 'projectId', IDENTIFIER_PATTERN);
    assertPattern(windowId, 'windowId', IDENTIFIER_PATTERN);
    assertPattern(developerIdHash, 'developerIdHash', SHA256_PATTERN);
    assertConstant(metricId, 'metricId', 'M4_DEVELOPER_CHURN_SHARE');
    assertConstant(policyVersion, 'policyVersion', '1.0.0');
}

async function iteratorValues(iterator) {
    const values = [];
    try {
        while (true) {
            const result = await iterator.next();
            if (result.done) {
                break;
            }
            values.push(result.value);
        }
    } finally {
        await iterator.close();
    }
    return values;
}

async function queryByIndex(ctx, objectType, attributes) {
    const iterator = await ctx.stub.getStateByPartialCompositeKey(objectType, attributes);
    const entries = await iteratorValues(iterator);
    const records = [];
    for (const entry of entries) {
        const stateKey = entry.value.toString('utf8');
        const state = await ctx.stub.getState(stateKey);
        if (!state || state.length === 0) {
            throw new Error(`Secondary index ${entry.key} references missing state`);
        }
        records.push(JSON.parse(state.toString('utf8')));
    }
    records.sort((left, right) => (
        left.recordId < right.recordId ? -1 : left.recordId > right.recordId ? 1 : 0
    ));
    return JSON.stringify(records);
}

class M4EvidenceContract extends Contract {
    constructor() {
        super('M4EvidenceContract');
    }

    async SubmitMetricEvidence(ctx, submissionJson) {
        const mspId = ctx.clientIdentity.getMSPID();
        if (!ALLOWED_SUBMITTER_MSPS.has(mspId)) {
            throw new Error(`MSP ${mspId} is not authorized to submit M4 evidence`);
        }
        assertPattern(mspId, 'submitterMspId', MSP_PATTERN);
        const clientId = ctx.clientIdentity.getID();
        assertString(clientId, 'Fabric client identity');

        const submission = parseSubmission(submissionJson);
        const key = primaryKey(
            ctx,
            submission.projectId,
            submission.windowId,
            submission.developerIdHash,
            submission.metricId,
            submission.policyVersion,
        );
        const existing = await ctx.stub.getState(key);
        if (existing && existing.length > 0) {
            throw new Error('M4 evidence already exists for this composite identity');
        }

        const transactionId = ctx.stub.getTxID();
        assertPattern(transactionId, 'transactionId', SHA256_PATTERN);
        const recordId = recordIdFor(submission);
        const record = {
            docType: 'm4MetricEvidence',
            recordId,
            schemaId: 'M4_LEDGER_RECORD',
            schemaVersion: '1.0.0',
            projectId: submission.projectId,
            windowId: submission.windowId,
            developerIdHash: submission.developerIdHash,
            metricId: submission.metricId,
            metricVersion: submission.metricVersion,
            metricValuePpm: submission.metricValuePpm,
            numeratorChurn: submission.numeratorChurn,
            denominatorChurn: submission.denominatorChurn,
            fromCommitHash: submission.fromCommitHash,
            toCommitHash: submission.toCommitHash,
            policyId: submission.policyId,
            policyVersion: submission.policyVersion,
            analysisPolicyHash: submission.analysisPolicyHash,
            evidenceManifestHash: submission.evidenceManifestHash,
            evidenceArtifactHash: submission.evidenceArtifactHash,
            storageReference: submission.storageReference,
            storagePersistence: submission.storagePersistence,
            submitterMspId: mspId,
            submitterIdHash: submitterIdHash(clientId),
            transactionId,
            recordedAt: timestampToISOString(ctx.stub.getTxTimestamp()),
            status: 'ACTIVE',
        };
        const recordBytes = Buffer.from(JSON.stringify(record), 'utf8');
        await ctx.stub.putState(key, recordBytes);

        const projectIndexKey = ctx.stub.createCompositeKey(PROJECT_INDEX_OBJECT_TYPE, [
            record.projectId,
            record.windowId,
            record.recordId,
        ]);
        const developerIndexKey = ctx.stub.createCompositeKey(DEVELOPER_INDEX_OBJECT_TYPE, [
            record.developerIdHash,
            record.projectId,
            record.windowId,
            record.recordId,
        ]);
        const keyBytes = Buffer.from(key, 'utf8');
        await ctx.stub.putState(projectIndexKey, keyBytes);
        await ctx.stub.putState(developerIndexKey, keyBytes);

        const eventPayload = Buffer.from(JSON.stringify({
            recordId: record.recordId,
            projectId: record.projectId,
            windowId: record.windowId,
            developerIdHash: record.developerIdHash,
            metricId: record.metricId,
            policyVersion: record.policyVersion,
        }), 'utf8');
        ctx.stub.setEvent(EVENT_NAME, eventPayload);
        return JSON.stringify(record);
    }

    async MetricEvidenceExists(ctx, projectId, windowId, developerIdHash, metricId, policyVersion) {
        validateLookupIdentity(projectId, windowId, developerIdHash, metricId, policyVersion);
        const key = primaryKey(ctx, projectId, windowId, developerIdHash, metricId, policyVersion);
        const state = await ctx.stub.getState(key);
        return Boolean(state && state.length > 0);
    }

    async ReadMetricEvidence(ctx, projectId, windowId, developerIdHash, metricId, policyVersion) {
        validateLookupIdentity(projectId, windowId, developerIdHash, metricId, policyVersion);
        const key = primaryKey(ctx, projectId, windowId, developerIdHash, metricId, policyVersion);
        const state = await ctx.stub.getState(key);
        if (!state || state.length === 0) {
            throw new Error('M4 evidence does not exist for this composite identity');
        }
        return state.toString('utf8');
    }

    async GetMetricEvidenceHistory(ctx, projectId, windowId, developerIdHash, metricId, policyVersion) {
        validateLookupIdentity(projectId, windowId, developerIdHash, metricId, policyVersion);
        const key = primaryKey(ctx, projectId, windowId, developerIdHash, metricId, policyVersion);
        const iterator = await ctx.stub.getHistoryForKey(key);
        const entries = await iteratorValues(iterator);
        return JSON.stringify(entries.map((entry) => ({
            transactionId: entry.txId,
            recordedAt: timestampToISOString(entry.timestamp),
            isDelete: Boolean(entry.isDelete),
            value: entry.isDelete || !entry.value || entry.value.length === 0
                ? null
                : JSON.parse(entry.value.toString('utf8')),
        })));
    }

    async QueryByProject(ctx, projectId) {
        assertPattern(projectId, 'projectId', IDENTIFIER_PATTERN);
        return queryByIndex(ctx, PROJECT_INDEX_OBJECT_TYPE, [projectId]);
    }

    async QueryByDeveloper(ctx, developerIdHash) {
        assertPattern(developerIdHash, 'developerIdHash', SHA256_PATTERN);
        return queryByIndex(ctx, DEVELOPER_INDEX_OBJECT_TYPE, [developerIdHash]);
    }
}

module.exports = M4EvidenceContract;
module.exports._private = {
    parseSubmission,
    recordIdFor,
    sha256Domain,
    submitterIdHash,
    timestampToISOString,
};
