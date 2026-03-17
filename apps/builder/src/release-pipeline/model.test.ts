import { describe, expect, it } from 'vitest';
import type { RunRecord } from '../api';
import type { ValidationIssue, WorkflowDraft } from '../builder/types';
import {
  buildReleaseReport,
  buildReleaseReportFilename,
  evaluatePublishGates,
  normalizeSmokeResult,
  resolveReleaseStageStates,
  summarizeValidation,
  summarizeWorkflowDiff,
  type SimulationExecutionResult,
} from './model';

const baselineDraft: WorkflowDraft = {
  nodes: [
    { id: 'start', type: 'start', config: {} },
    { id: 'end', type: 'end', config: {} },
  ],
  edges: [{ source: 'start', target: 'end' }],
  variables_schema: { type: 'object', properties: { customer_id: { type: 'string' } } },
};

describe('release pipeline model', () => {
  it('evaluates publish gates from validation + simulation + diff', () => {
    const validation = summarizeValidation([
      { id: 'err_1', level: 'error', message: 'missing end node' } as ValidationIssue,
    ]);
    const noPublish = evaluatePublishGates({
      validation,
      simulation: null,
      diff: null,
    });
    expect(noPublish.can_publish).toBe(false);
    expect(noPublish.gates.map((gate) => gate.passed)).toEqual([false, false, false]);

    const simulation: SimulationExecutionResult = {
      status: 'passed',
      total_cases: 3,
      passed_cases: 3,
      failed_cases: 0,
      typed_failures: [],
      metrics: {
        action_accuracy: 1,
        workflow_accuracy: 1,
        exact_match_rate: 1,
        average_confidence: 0.9,
      },
      outcomes: [],
    };
    const diff = summarizeWorkflowDiff(baselineDraft, baselineDraft, 'wfv_1');
    const canPublish = evaluatePublishGates({
      validation: summarizeValidation([]),
      simulation,
      diff,
    });
    expect(canPublish.can_publish).toBe(true);
    expect(canPublish.gates.map((gate) => gate.passed)).toEqual([true, true, true]);
  });

  it('builds deterministic diff summaries', () => {
    const candidateDraft: WorkflowDraft = {
      nodes: [
        { id: 'start', type: 'start', config: {} },
        { id: 'agent_1', type: 'agent', config: { instructions: 'new instructions' } },
        { id: 'end', type: 'end', config: {} },
      ],
      edges: [
        { source: 'start', target: 'agent_1' },
        { source: 'agent_1', target: 'end' },
      ],
      variables_schema: {
        type: 'object',
        properties: { customer_id: { type: 'string' }, order_id: { type: 'string' } },
      },
    };

    const diff = summarizeWorkflowDiff(candidateDraft, baselineDraft, 'wfv_1');
    expect(diff.has_changes).toBe(true);
    expect(diff.node_additions).toEqual(['agent_1']);
    expect(diff.edge_additions).toEqual(['agent_1->end', 'start->agent_1']);
    expect(diff.edge_removals).toEqual(['start->end']);
    expect(diff.variables_schema_changes.length).toBeGreaterThan(0);
    expect(diff.routing_policy_changes).toContain('graph:edges');
  });

  it('resolves stage transitions in sequence', () => {
    const validationFailed = summarizeValidation([
      { id: 'err_1', level: 'error', message: 'broken graph' } as ValidationIssue,
    ]);
    const blocked = resolveReleaseStageStates({
      validation: validationFailed,
      simulation: null,
      diff: summarizeWorkflowDiff(baselineDraft, baselineDraft, 'wfv_1'),
      published: false,
      bind_completed: false,
      smoke: null,
    });
    expect(blocked.find((stage) => stage.stage === 'simulate')?.status).toBe('blocked');
    expect(blocked.find((stage) => stage.stage === 'publish')?.status).toBe('blocked');

    const ready = resolveReleaseStageStates({
      validation: summarizeValidation([]),
      simulation: {
        status: 'passed',
        total_cases: 2,
        passed_cases: 2,
        failed_cases: 0,
        typed_failures: [],
        metrics: {
          action_accuracy: 1,
          workflow_accuracy: 1,
          exact_match_rate: 1,
          average_confidence: 0.8,
        },
        outcomes: [],
      },
      diff: summarizeWorkflowDiff(baselineDraft, baselineDraft, 'wfv_1'),
      published: true,
      bind_completed: true,
      smoke: {
        status: 'success',
        run_id: 'run_1',
        correlation_id: 'corr_1',
        typed_errors: [],
      },
    });
    expect(ready.find((stage) => stage.stage === 'publish')?.status).toBe('passed');
    expect(ready.find((stage) => stage.stage === 'bind')?.status).toBe('passed');
    expect(ready.find((stage) => stage.stage === 'smoke')?.status).toBe('passed');
    expect(ready.find((stage) => stage.stage === 'observe')?.status).toBe('ready');
  });

  it('normalizes smoke results and typed errors', () => {
    const failedRun: RunRecord = {
      run_id: 'run_failed_1',
      workflow_id: 'wf_1',
      version_id: 'wfv_1',
      status: 'FAILED',
      correlation_id: 'corr_1',
      node_runs: [
        {
          node_id: 'agent_1',
          status: 'ERROR',
          last_error: 'timeout waiting for model',
        },
      ],
    };
    const failed = normalizeSmokeResult({ run: failedRun });
    expect(failed.status).toBe('failed');
    expect(failed.typed_errors).toContain('timeout waiting for model');

    const timeout = normalizeSmokeResult({
      run: {
        run_id: 'run_pending_1',
        workflow_id: 'wf_1',
        version_id: 'wfv_1',
        status: 'RUNNING',
      },
      timedOut: true,
    });
    expect(timeout.status).toBe('timeout');
  });

  it('builds release report artifact payloads and export filenames', () => {
    const report = buildReleaseReport({
      workflow_id: 'wf_release_1',
      tenant_id: 'tenant_1',
      project_id: 'proj_1',
      candidate_version_id: 'draft_deadbeef',
      published_version_id: 'wfv_2',
      validation: summarizeValidation([]),
      simulation: {
        status: 'passed',
        total_cases: 3,
        passed_cases: 3,
        failed_cases: 0,
        typed_failures: [],
        metrics: {
          action_accuracy: 1,
          workflow_accuracy: 1,
          exact_match_rate: 1,
          average_confidence: 0.9,
        },
        outcomes: [],
      },
      diff: summarizeWorkflowDiff(baselineDraft, baselineDraft, 'wfv_1'),
      bind_targets: {
        project_default_chat_workflow_id: 'wf_release_1',
        routing_definition_registered: true,
        observed_direct_runs: 2,
      },
      smoke: {
        status: 'success',
        run_id: 'run_smoke_1',
        correlation_id: 'corr_smoke_1',
        typed_errors: [],
      },
      operator_timestamps: {
        opened_at: '2026-03-10T10:00:00Z',
        publish_at: '2026-03-10T10:02:00Z',
      },
      exported_at: '2026-03-10T10:03:00Z',
    });

    expect(report.workflow_id).toBe('wf_release_1');
    expect(report.run_ids).toEqual(['run_smoke_1']);
    expect(report.correlation_ids).toEqual(['corr_smoke_1']);
    expect(report.simulation_result.total_cases).toBe(3);
    expect(report.diff_summary.baseline_version_id).toBe('wfv_1');
    expect(report.bind_targets).toEqual({
      project_default_chat_workflow_id: 'wf_release_1',
      routing_definition_registered: true,
      observed_direct_runs: 2,
    });
    expect(report.smoke_result).toEqual({
      status: 'success',
      run_id: 'run_smoke_1',
      correlation_id: 'corr_smoke_1',
      typed_errors: [],
    });

    const filename = buildReleaseReportFilename('wf_release_1', '2026-03-10T10:03:00.000Z');
    expect(filename).toBe('wf_release_1-release-report-2026-03-10T10-03-00-000Z.json');
  });
});
