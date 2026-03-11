import { describe, expect, it } from 'vitest';
import type { RunLedgerRecord, RunRecord } from '../api';
import {
  buildAttemptDiff,
  buildRunSupportBundle,
  normalizeRunDebugData,
  resolveLastGoodOutput,
  type RunAttemptGroup
} from './model';

const baseRun = (overrides?: Partial<RunRecord>): RunRecord => ({
  run_id: 'run_1',
  workflow_id: 'wf_1',
  version_id: 'ver_1',
  status: 'RUNNING',
  mode: 'live',
  inputs: {},
  outputs: null,
  metadata: {
    tenant_id: 'tenant_1',
    project_id: 'proj_1',
    correlation_id: 'corr_1'
  },
  created_at: '2026-03-01T10:00:00Z',
  updated_at: '2026-03-01T10:05:00Z',
  node_runs: [],
  ...overrides
});

const entry = (event_type: string, timestamp: string, overrides?: Partial<RunLedgerRecord>): RunLedgerRecord => ({
  ledger_id: `${event_type}_${timestamp}`,
  run_id: 'run_1',
  workflow_id: 'wf_1',
  version_id: 'ver_1',
  status: 'RUNNING',
  event_type,
  payload: {},
  artifacts: [],
  timestamp,
  ...overrides
});

describe('run-debug model normalization', () => {
  it('normalizes timeline and groups node attempts with auto-retry transitions', () => {
    const run = baseRun({
      status: 'COMPLETED',
      outputs: { final: true },
      node_runs: [
        {
          node_id: 'extract',
          status: 'RESOLVED',
          attempt: 2,
          output: { total: 3 },
          usage: { input_tokens: 5, output_tokens: 7, total_tokens: 12 },
          last_error: null,
          trace_id: 'trace_2'
        }
      ]
    });

    const ledger = [
      entry('run_started', '2026-03-01T10:00:01Z'),
      entry('node_started', '2026-03-01T10:00:02Z', { node_id: 'extract', step_id: 'extract' }),
      entry('node_retry', '2026-03-01T10:00:03Z', {
        node_id: 'extract',
        step_id: 'extract',
        payload: { attempt: 2, error: 'timeout' }
      }),
      entry('node_started', '2026-03-01T10:00:04Z', { node_id: 'extract', step_id: 'extract' }),
      entry('node_completed', '2026-03-01T10:00:05Z', {
        node_id: 'extract',
        step_id: 'extract',
        status: 'RESOLVED'
      }),
      entry('run_completed', '2026-03-01T10:00:06Z', { status: 'COMPLETED' })
    ];

    const model = normalizeRunDebugData(run, ledger);
    expect(model.timeline).toHaveLength(6);
    expect(model.runTimeline.map((item) => item.eventType)).toEqual(['run_started', 'run_completed']);
    expect(model.nodeAttempts).toHaveLength(1);
    expect(model.nodeAttempts[0].nodeId).toBe('extract');
    expect(model.nodeAttempts[0].attempts).toHaveLength(2);
    expect(model.nodeAttempts[0].attempts[1].transition).toBe('auto_retry');
    expect(model.retryOrRerunHistory).toEqual([
      expect.objectContaining({
        nodeId: 'extract',
        kind: 'auto_retry',
        fromAttempt: 1,
        toAttempt: 2
      })
    ]);
  });

  it('infers manual rerun transitions when attempt restarts without node_retry event', () => {
    const run = baseRun({
      status: 'COMPLETED',
      node_runs: [
        {
          node_id: 'extract',
          status: 'RESOLVED',
          attempt: 1,
          output: { final: 'ok' },
          usage: null,
          last_error: null,
          trace_id: 'trace_new'
        }
      ]
    });

    const ledger = [
      entry('run_started', '2026-03-01T10:00:01Z'),
      entry('node_started', '2026-03-01T10:00:02Z', { node_id: 'extract', step_id: 'extract' }),
      entry('node_failed', '2026-03-01T10:00:03Z', {
        node_id: 'extract',
        step_id: 'extract',
        status: 'ERROR',
        payload: { error: 'validation_failed' }
      }),
      entry('run_failed', '2026-03-01T10:00:04Z', {
        status: 'FAILED',
        node_id: 'extract',
        step_id: 'extract',
        payload: { error: 'validation_failed', node_id: 'extract' }
      }),
      entry('node_started', '2026-03-01T10:00:05Z', { node_id: 'extract', step_id: 'extract' }),
      entry('node_completed', '2026-03-01T10:00:06Z', {
        node_id: 'extract',
        step_id: 'extract',
        status: 'RESOLVED',
        payload: { output: { final: 'ok' } }
      })
    ];

    const model = normalizeRunDebugData(run, ledger);
    expect(model.nodeAttempts[0].attempts).toHaveLength(2);
    expect(model.nodeAttempts[0].attempts[1].transition).toBe('manual_rerun');
    expect(model.retryOrRerunHistory).toContainEqual(
      expect.objectContaining({ kind: 'manual_rerun', nodeId: 'extract', fromAttempt: 1, toAttempt: 2 })
    );
  });

  it('selects canonical last-good output from run.outputs for completed runs', () => {
    const run = baseRun({ status: 'COMPLETED', outputs: { final_report: 'ok' } });
    const lastGood = resolveLastGoodOutput(run, []);

    expect(lastGood).toEqual(
      expect.objectContaining({
        source: 'run.outputs',
        output: { final_report: 'ok' }
      })
    );
  });

  it('falls back to latest resolved node attempt output when run.outputs is unavailable', () => {
    const run = baseRun({ status: 'FAILED', outputs: null });
    const attempts: RunAttemptGroup[] = [
      {
        nodeId: 'extract',
        attempts: [
          {
            nodeId: 'extract',
            attempt: 1,
            status: 'RESOLVED',
            transition: 'initial',
            output: { first: true },
            completedAt: '2026-03-01T10:00:04Z',
            timeline: []
          },
          {
            nodeId: 'extract',
            attempt: 2,
            status: 'RESOLVED',
            transition: 'manual_rerun',
            output: { second: true },
            completedAt: '2026-03-01T10:00:09Z',
            timeline: []
          }
        ]
      }
    ];

    const lastGood = resolveLastGoodOutput(run, attempts);
    expect(lastGood).toEqual(
      expect.objectContaining({
        source: 'node_attempt',
        nodeId: 'extract',
        attempt: 2,
        output: { second: true }
      })
    );
  });

  it('diffs successive attempts for output, error, and usage', () => {
    const previousAttempt = {
      nodeId: 'classify',
      attempt: 1,
      status: 'ERROR',
      transition: 'initial' as const,
      output: { score: 0.2 },
      usage: { total_tokens: 40 },
      lastError: 'timeout',
      timeline: []
    };

    const nextAttempt = {
      nodeId: 'classify',
      attempt: 2,
      status: 'RESOLVED',
      transition: 'auto_retry' as const,
      output: { score: 0.95 },
      usage: { total_tokens: 48 },
      lastError: null,
      timeline: []
    };

    const diff = buildAttemptDiff(previousAttempt, nextAttempt);
    expect(diff).toEqual(
      expect.objectContaining({
        nodeId: 'classify',
        fromAttempt: 1,
        toAttempt: 2,
        changes: expect.arrayContaining([
          expect.objectContaining({ field: 'output' }),
          expect.objectContaining({ field: 'last_error' }),
          expect.objectContaining({ field: 'usage' })
        ])
      })
    );
  });

  it('builds redacted support bundle without leaking secrets or artifact bodies', () => {
    const run = baseRun({
      status: 'FAILED',
      inputs: {
        auth_token: 'secret-token',
        documents: [
          {
            doc_id: 'doc_1',
            pages: [
              {
                artifact_ref: 'art_1',
                image_base64: 'abcd'
              }
            ]
          }
        ]
      },
      metadata: {
        tenant_id: 'tenant_1',
        project_id: 'proj_1',
        correlation_id: 'corr_1',
        webhook_signature: 'signature-secret'
      },
      node_runs: [
        {
          node_id: 'extract',
          status: 'ERROR',
          attempt: 1,
          output: { artifact_ref: 'art_2', content: 'raw artifact body' },
          usage: { total_tokens: 10 },
          last_error: { code: 'ERR_TIMEOUT', retryable: true },
          trace_id: 'trace_err'
        }
      ]
    });

    const ledger = [
      entry('run_started', '2026-03-01T10:00:01Z'),
      entry('node_started', '2026-03-01T10:00:02Z', { node_id: 'extract', step_id: 'extract' }),
      entry('node_failed', '2026-03-01T10:00:03Z', {
        node_id: 'extract',
        step_id: 'extract',
        status: 'ERROR',
        payload: {
          error: 'timeout',
          artifact_ref: 'art_2',
          content: 'should not leak',
          access_token: 'token-should-redact'
        }
      })
    ];

    const bundle = buildRunSupportBundle({ run, ledgerEntries: ledger });
    const json = JSON.stringify(bundle);

    expect(json).not.toContain('secret-token');
    expect(json).not.toContain('signature-secret');
    expect(json).not.toContain('token-should-redact');
    expect(json).not.toContain('should not leak');
    expect(json).toContain('[REDACTED_SECRET]');
    expect(json).toContain('[REDACTED_ARTIFACT_BODY]');
    expect(json).toContain('art_1');
    expect(json).toContain('art_2');
  });
});
