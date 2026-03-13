import type { RunRecord } from '../api';
import type { ValidationIssue, WorkflowDraft } from '../builder/types';

export type ReleaseStageId =
  | 'validate'
  | 'simulate'
  | 'diff'
  | 'publish'
  | 'bind'
  | 'smoke'
  | 'observe';

export type ReleaseStageStatus = 'pending' | 'ready' | 'blocked' | 'passed' | 'failed';

export type ReleaseStageState = {
  stage: ReleaseStageId;
  status: ReleaseStageStatus;
  detail: string;
};

export type ValidationGateSummary = {
  passed: boolean;
  blocking_issues: ValidationIssue[];
  warnings: ValidationIssue[];
};

export type WorkflowDiffSummary = {
  baseline_version_id: string | null;
  candidate_fingerprint: string;
  has_changes: boolean;
  node_additions: string[];
  node_removals: string[];
  edge_additions: string[];
  edge_removals: string[];
  config_changes: Array<{ node_id: string; paths: string[] }>;
  routing_policy_changes: string[];
  affected_bindings: string[];
  variables_schema_changes: string[];
};

export type PublishGateResult = {
  id: 'validate' | 'simulate' | 'diff';
  label: string;
  passed: boolean;
  detail: string;
};

export type PublishGateEvaluation = {
  can_publish: boolean;
  gates: PublishGateResult[];
};

export type SimulationExecutionResult = {
  status: 'not_run' | 'passed' | 'failed';
  total_cases: number;
  passed_cases: number;
  failed_cases: number;
  typed_failures: string[];
  metrics: {
    action_accuracy: number;
    workflow_accuracy: number;
    exact_match_rate: number;
    average_confidence: number;
  };
  outcomes: Array<{
    case_id: string;
    chosen_action: string | null;
    chosen_workflow_id: string | null;
    matched_action: boolean | null;
    matched_workflow_id: boolean | null;
    matched_exact: boolean | null;
    latency_ms: number | null;
  }>;
};

export type SmokeResultSummary = {
  status: 'not_started' | 'running' | 'timeout' | 'success' | 'failed';
  run_id: string | null;
  correlation_id: string | null;
  typed_errors: string[];
};

export type ReleaseReport = {
  workflow_id: string;
  tenant_id: string | null;
  project_id: string | null;
  candidate_version_id: string;
  published_version_id: string | null;
  validation_result: {
    passed: boolean;
    blocking_issues: number;
    warnings: number;
  };
  simulation_result: {
    status: SimulationExecutionResult['status'];
    total_cases: number;
    passed_cases: number;
    failed_cases: number;
    typed_failures: string[];
    metrics: SimulationExecutionResult['metrics'];
  };
  diff_summary: WorkflowDiffSummary;
  bind_targets: {
    project_default_chat_workflow_id: string | null;
    routing_definition_registered: boolean;
    observed_direct_runs: number;
  };
  smoke_result: SmokeResultSummary;
  operator_timestamps: Record<string, string>;
  run_ids: string[];
  correlation_ids: string[];
  exported_at: string;
};

const INTERNAL_WORKCORE_KEY = '_workcore';

const isRecord = (value: unknown): value is Record<string, any> =>
  typeof value === 'object' && value !== null && !Array.isArray(value);

const ensureRecord = (value: unknown): Record<string, any> => (isRecord(value) ? value : {});

const normalizeDraftNode = (value: unknown, index: number) => {
  const record = ensureRecord(value);
  const idRaw = typeof record.id === 'string' ? record.id.trim() : '';
  const typeRaw = typeof record.type === 'string' ? record.type.trim() : '';
  return {
    id: idRaw || `node_${index + 1}`,
    type: typeRaw || 'unknown',
    config: ensureRecord(record.config),
  };
};

const normalizeDraftEdge = (value: unknown) => {
  const record = ensureRecord(value);
  const source = typeof record.source === 'string' ? record.source.trim() : '';
  const target = typeof record.target === 'string' ? record.target.trim() : '';
  return { source, target };
};

const stripInternalWorkcoreContent = (value: unknown): Record<string, any> => {
  const content = ensureRecord(value);
  const next = { ...content };
  delete next[INTERNAL_WORKCORE_KEY];
  return next;
};

const toWorkflowDraft = (value: unknown): WorkflowDraft => {
  const content = ensureRecord(value);
  const nodesRaw = Array.isArray(content.nodes) ? content.nodes : [];
  const edgesRaw = Array.isArray(content.edges) ? content.edges : [];
  const variablesSchema = ensureRecord(content.variables_schema);

  const nodes = nodesRaw.map(normalizeDraftNode).sort((left, right) => left.id.localeCompare(right.id));
  const edges = edgesRaw
    .map(normalizeDraftEdge)
    .filter((edge) => edge.source && edge.target)
    .sort((left, right) => {
      if (left.source !== right.source) return left.source.localeCompare(right.source);
      return left.target.localeCompare(right.target);
    });

  return {
    nodes,
    edges,
    variables_schema: variablesSchema,
  };
};

const stableValue = (value: unknown): unknown => {
  if (Array.isArray(value)) {
    return value.map((item) => stableValue(item));
  }
  if (isRecord(value)) {
    const next: Record<string, unknown> = {};
    Object.keys(value)
      .sort()
      .forEach((key) => {
        next[key] = stableValue(value[key]);
      });
    return next;
  }
  return value;
};

const stableStringify = (value: unknown): string => JSON.stringify(stableValue(value));

const hashString = (value: string): string => {
  let hash = 2166136261;
  for (let index = 0; index < value.length; index += 1) {
    hash ^= value.charCodeAt(index);
    hash += (hash << 1) + (hash << 4) + (hash << 7) + (hash << 8) + (hash << 24);
  }
  const normalized = hash >>> 0;
  return normalized.toString(16).padStart(8, '0');
};

const edgeKey = (edge: { source: string; target: string }) => `${edge.source}->${edge.target}`;

const toComparableValue = (value: unknown) => {
  if (typeof value === 'number' && Number.isNaN(value)) return 'NaN';
  return value;
};

const valuesEqual = (left: unknown, right: unknown) =>
  stableStringify(toComparableValue(left)) === stableStringify(toComparableValue(right));

const joinPath = (base: string, key: string) => (base ? `${base}.${key}` : key);

const collectChangedPaths = (left: unknown, right: unknown, basePath = ''): string[] => {
  const changes = new Set<string>();

  const visit = (leftValue: unknown, rightValue: unknown, path: string) => {
    if (valuesEqual(leftValue, rightValue)) return;

    if (Array.isArray(leftValue) || Array.isArray(rightValue)) {
      const leftArray = Array.isArray(leftValue) ? leftValue : [];
      const rightArray = Array.isArray(rightValue) ? rightValue : [];
      if (leftArray.length !== rightArray.length) {
        changes.add(path ? `${path}.length` : 'length');
      }
      const maxLength = Math.max(leftArray.length, rightArray.length);
      for (let index = 0; index < maxLength; index += 1) {
        visit(leftArray[index], rightArray[index], `${path}[${index}]`);
      }
      return;
    }

    if (isRecord(leftValue) || isRecord(rightValue)) {
      const leftRecord = ensureRecord(leftValue);
      const rightRecord = ensureRecord(rightValue);
      const keys = Array.from(new Set([...Object.keys(leftRecord), ...Object.keys(rightRecord)])).sort();
      keys.forEach((key) => {
        visit(leftRecord[key], rightRecord[key], joinPath(path, key));
      });
      return;
    }

    changes.add(path || '$');
  };

  visit(left, right, basePath);
  return Array.from(changes).sort();
};

const bindingPathHints = [
  'config.expression',
  'config.target',
  'config.state_target',
  'config.user_input',
  'config.instructions',
  'config.request_body_expression',
  'config.response_state_target',
  'config.response_body_state_target',
  'config.condition',
  'config.branches',
  'config.else_target',
  'config.body_target',
  'config.exit_target',
  'config.loop_back',
];

const routingPathHints = [
  'config.condition',
  'config.branches',
  'config.else_target',
  'config.body_target',
  'config.exit_target',
  'config.loop_back',
];

const extractRunErrorStrings = (run: RunRecord | null): string[] => {
  if (!run) return [];
  const errors = new Set<string>();
  const runError = (run as Record<string, any>).error;
  const runLastError = (run as Record<string, any>).last_error;
  [runError, runLastError].forEach((item) => {
    if (typeof item === 'string' && item.trim()) {
      errors.add(item.trim());
    }
  });
  (run.node_runs || []).forEach((nodeRun) => {
    if (typeof nodeRun.last_error === 'string' && nodeRun.last_error.trim()) {
      errors.add(nodeRun.last_error.trim());
    }
  });
  return Array.from(errors);
};

export const computeDraftFingerprint = (draft: WorkflowDraft): string => {
  const normalized = toWorkflowDraft(draft);
  return hashString(stableStringify(normalized));
};

export const summarizeValidation = (issues: ValidationIssue[]): ValidationGateSummary => {
  const blocking_issues = issues.filter((issue) => issue.level === 'error');
  const warnings = issues.filter((issue) => issue.level !== 'error');
  return {
    passed: blocking_issues.length === 0,
    blocking_issues,
    warnings,
  };
};

export const summarizeWorkflowDiff = (
  candidateDraft: WorkflowDraft,
  publishedContent: unknown,
  baselineVersionId: string | null
): WorkflowDiffSummary => {
  const candidate = toWorkflowDraft(candidateDraft);
  const published = toWorkflowDraft(stripInternalWorkcoreContent(publishedContent));

  const candidateNodeMap = new Map(candidate.nodes.map((node) => [node.id, node]));
  const publishedNodeMap = new Map(published.nodes.map((node) => [node.id, node]));
  const candidateNodeIds = Array.from(candidateNodeMap.keys()).sort();
  const publishedNodeIds = Array.from(publishedNodeMap.keys()).sort();

  const node_additions = candidateNodeIds.filter((nodeId) => !publishedNodeMap.has(nodeId));
  const node_removals = publishedNodeIds.filter((nodeId) => !candidateNodeMap.has(nodeId));

  const config_changes: Array<{ node_id: string; paths: string[] }> = [];
  const routingChanges = new Set<string>();
  const affectedBindings = new Set<string>();

  candidateNodeIds
    .filter((nodeId) => publishedNodeMap.has(nodeId))
    .forEach((nodeId) => {
      const candidateNode = candidateNodeMap.get(nodeId)!;
      const publishedNode = publishedNodeMap.get(nodeId)!;
      const paths = collectChangedPaths(
        {
          type: publishedNode.type,
          config: ensureRecord(publishedNode.config),
        },
        {
          type: candidateNode.type,
          config: ensureRecord(candidateNode.config),
        }
      ).filter((path) => path !== '$');
      if (!paths.length) return;

      config_changes.push({ node_id: nodeId, paths });
      if (paths.some((path) => bindingPathHints.some((hint) => path.startsWith(hint)))) {
        affectedBindings.add(`node:${nodeId}`);
      }
      if (
        candidateNode.type === 'if_else' ||
        candidateNode.type === 'while' ||
        paths.some((path) => routingPathHints.some((hint) => path.startsWith(hint)))
      ) {
        routingChanges.add(`node:${nodeId}`);
      }
    });

  const candidateEdgeMap = new Map(candidate.edges.map((edge) => [edgeKey(edge), edge]));
  const publishedEdgeMap = new Map(published.edges.map((edge) => [edgeKey(edge), edge]));
  const edge_additions = Array.from(candidateEdgeMap.keys())
    .filter((key) => !publishedEdgeMap.has(key))
    .sort();
  const edge_removals = Array.from(publishedEdgeMap.keys())
    .filter((key) => !candidateEdgeMap.has(key))
    .sort();
  if (edge_additions.length || edge_removals.length) {
    routingChanges.add('graph:edges');
  }

  const variables_schema_changes = collectChangedPaths(
    ensureRecord(published.variables_schema),
    ensureRecord(candidate.variables_schema),
    'variables_schema'
  );
  if (variables_schema_changes.length) {
    affectedBindings.add('variables_schema');
  }

  return {
    baseline_version_id: baselineVersionId,
    candidate_fingerprint: computeDraftFingerprint(candidate),
    has_changes:
      node_additions.length > 0 ||
      node_removals.length > 0 ||
      edge_additions.length > 0 ||
      edge_removals.length > 0 ||
      config_changes.length > 0 ||
      variables_schema_changes.length > 0,
    node_additions,
    node_removals,
    edge_additions,
    edge_removals,
    config_changes,
    routing_policy_changes: Array.from(routingChanges).sort(),
    affected_bindings: Array.from(affectedBindings).sort(),
    variables_schema_changes,
  };
};

export const evaluatePublishGates = (params: {
  validation: ValidationGateSummary;
  simulation: SimulationExecutionResult | null;
  diff: WorkflowDiffSummary | null;
}): PublishGateEvaluation => {
  const gates: PublishGateResult[] = [
    {
      id: 'validate',
      label: 'Validate',
      passed: params.validation.passed,
      detail: params.validation.passed
        ? 'No blocking validation errors'
        : `${params.validation.blocking_issues.length} blocking issues`,
    },
    {
      id: 'simulate',
      label: 'Simulate',
      passed: params.simulation?.status === 'passed',
      detail:
        params.simulation?.status === 'passed'
          ? `${params.simulation.total_cases} cases passed`
          : params.simulation?.status === 'failed'
            ? `${params.simulation.failed_cases} simulation failures`
            : 'Run simulation before publish',
    },
    {
      id: 'diff',
      label: 'Diff',
      passed: Boolean(params.diff),
      detail: params.diff
        ? params.diff.baseline_version_id
          ? 'Diff generated against active published version'
          : 'No published baseline; full candidate publish'
        : 'Diff unavailable',
    },
  ];

  return {
    can_publish: gates.every((gate) => gate.passed),
    gates,
  };
};

export const normalizeSimulationResult = (
  payload: any,
  fallbackWorkflowId: string
): SimulationExecutionResult => {
  const items = Array.isArray(payload?.items) ? payload.items : [];
  const metrics = ensureRecord(payload?.metrics);
  const outcomes = items.map((item: any, index: number) => ({
    case_id:
      (typeof item?.case_id === 'string' && item.case_id.trim()) || `case_${index + 1}`,
    chosen_action: typeof item?.chosen_action === 'string' ? item.chosen_action : null,
    chosen_workflow_id:
      typeof item?.chosen_workflow_id === 'string' ? item.chosen_workflow_id : null,
    matched_action: typeof item?.matched_action === 'boolean' ? item.matched_action : null,
    matched_workflow_id:
      typeof item?.matched_workflow_id === 'boolean' ? item.matched_workflow_id : null,
    matched_exact: typeof item?.matched_exact === 'boolean' ? item.matched_exact : null,
    latency_ms: typeof item?.latency_ms === 'number' ? item.latency_ms : null,
  }));

  const typedFailureSet = new Set<string>();
  let failedCases = 0;
  outcomes.forEach((outcome, index) => {
    const source = ensureRecord(items[index]);
    const actionError = typeof source.action_error === 'string' ? source.action_error.trim() : '';
    if (actionError) {
      failedCases += 1;
      typedFailureSet.add(`${outcome.case_id}: ${actionError}`);
      return;
    }

    const expectedWorkflowId =
      typeof source.expected_workflow_id === 'string' && source.expected_workflow_id.trim()
        ? source.expected_workflow_id.trim()
        : fallbackWorkflowId;
    const workflowMismatch =
      Boolean(expectedWorkflowId) &&
      typeof source.chosen_workflow_id === 'string' &&
      source.chosen_workflow_id.trim() !== expectedWorkflowId;
    const explicitMismatch =
      source.matched_exact === false ||
      source.matched_action === false ||
      source.matched_workflow_id === false;
    if (workflowMismatch || explicitMismatch) {
      failedCases += 1;
      typedFailureSet.add(
        `${outcome.case_id}: expected ${expectedWorkflowId}, got ${outcome.chosen_workflow_id || 'none'}`
      );
    }
  });

  const totalCases = outcomes.length;
  const passedCases = Math.max(totalCases - failedCases, 0);
  const status: SimulationExecutionResult['status'] =
    totalCases === 0 ? 'not_run' : failedCases > 0 ? 'failed' : 'passed';

  return {
    status,
    total_cases: totalCases,
    passed_cases: passedCases,
    failed_cases: failedCases,
    typed_failures: Array.from(typedFailureSet),
    metrics: {
      action_accuracy:
        typeof metrics.action_accuracy === 'number' ? metrics.action_accuracy : 0,
      workflow_accuracy:
        typeof metrics.workflow_accuracy === 'number' ? metrics.workflow_accuracy : 0,
      exact_match_rate:
        typeof metrics.exact_match_rate === 'number' ? metrics.exact_match_rate : 0,
      average_confidence:
        typeof metrics.average_confidence === 'number' ? metrics.average_confidence : 0,
    },
    outcomes,
  };
};

export const normalizeSmokeResult = (params: {
  run: RunRecord | null;
  fallbackRunId?: string | null;
  timedOut?: boolean;
  requestError?: string | null;
}): SmokeResultSummary => {
  const { run, fallbackRunId = null, timedOut = false, requestError = null } = params;
  const runStatus = typeof run?.status === 'string' ? run.status : '';
  const runId = run?.run_id || fallbackRunId || null;
  const correlationId =
    run?.correlation_id ||
    (isRecord(run?.metadata) && typeof run?.metadata?.correlation_id === 'string'
      ? String(run?.metadata?.correlation_id)
      : null);

  if (requestError) {
    return {
      status: 'failed',
      run_id: runId,
      correlation_id: correlationId,
      typed_errors: [requestError],
    };
  }
  if (!run) {
    return { status: 'not_started', run_id: runId, correlation_id: correlationId, typed_errors: [] };
  }
  if (runStatus === 'COMPLETED') {
    return { status: 'success', run_id: runId, correlation_id: correlationId, typed_errors: [] };
  }
  if (runStatus === 'FAILED' || runStatus === 'CANCELLED') {
    return {
      status: 'failed',
      run_id: runId,
      correlation_id: correlationId,
      typed_errors: extractRunErrorStrings(run),
    };
  }
  if (timedOut) {
    return {
      status: 'timeout',
      run_id: runId,
      correlation_id: correlationId,
      typed_errors: extractRunErrorStrings(run),
    };
  }
  return {
    status: 'running',
    run_id: runId,
    correlation_id: correlationId,
    typed_errors: extractRunErrorStrings(run),
  };
};

export const resolveReleaseStageStates = (params: {
  validation: ValidationGateSummary;
  simulation: SimulationExecutionResult | null;
  diff: WorkflowDiffSummary | null;
  published: boolean;
  bind_completed: boolean;
  smoke: SmokeResultSummary | null;
}): ReleaseStageState[] => {
  const stageStates: ReleaseStageState[] = [];

  if (params.validation.passed) {
    stageStates.push({ stage: 'validate', status: 'passed', detail: 'Validation passed' });
  } else {
    stageStates.push({
      stage: 'validate',
      status: 'failed',
      detail: `${params.validation.blocking_issues.length} blocking issues`,
    });
  }

  if (!params.validation.passed) {
    stageStates.push({ stage: 'simulate', status: 'blocked', detail: 'Validation must pass first' });
  } else if (!params.simulation || params.simulation.status === 'not_run') {
    stageStates.push({ stage: 'simulate', status: 'ready', detail: 'Run simulation' });
  } else if (params.simulation.status === 'failed') {
    stageStates.push({
      stage: 'simulate',
      status: 'failed',
      detail: `${params.simulation.failed_cases} failing simulation cases`,
    });
  } else {
    stageStates.push({ stage: 'simulate', status: 'passed', detail: 'Simulation passed' });
  }

  if (!params.simulation || params.simulation.status !== 'passed') {
    stageStates.push({ stage: 'diff', status: 'blocked', detail: 'Simulation must pass first' });
  } else if (!params.diff) {
    stageStates.push({ stage: 'diff', status: 'pending', detail: 'Diff not generated' });
  } else {
    stageStates.push({ stage: 'diff', status: 'passed', detail: 'Diff summary ready' });
  }

  if (!params.validation.passed || params.simulation?.status !== 'passed' || !params.diff) {
    stageStates.push({ stage: 'publish', status: 'blocked', detail: 'Required gates are not passing' });
  } else if (!params.published) {
    stageStates.push({ stage: 'publish', status: 'ready', detail: 'Ready to publish' });
  } else {
    stageStates.push({ stage: 'publish', status: 'passed', detail: 'Published' });
  }

  if (!params.published) {
    stageStates.push({ stage: 'bind', status: 'blocked', detail: 'Publish first' });
  } else if (!params.bind_completed) {
    stageStates.push({ stage: 'bind', status: 'ready', detail: 'Apply binding to serving scope' });
  } else {
    stageStates.push({ stage: 'bind', status: 'passed', detail: 'Binding updated' });
  }

  if (!params.bind_completed) {
    stageStates.push({ stage: 'smoke', status: 'blocked', detail: 'Binding stage must pass first' });
  } else if (!params.smoke || params.smoke.status === 'not_started') {
    stageStates.push({ stage: 'smoke', status: 'ready', detail: 'Run release smoke test' });
  } else if (params.smoke.status === 'success') {
    stageStates.push({ stage: 'smoke', status: 'passed', detail: 'Smoke test passed' });
  } else if (params.smoke.status === 'running' || params.smoke.status === 'timeout') {
    stageStates.push({ stage: 'smoke', status: 'pending', detail: 'Smoke test still running' });
  } else {
    stageStates.push({ stage: 'smoke', status: 'failed', detail: 'Smoke test failed' });
  }

  if (!params.smoke || params.smoke.status === 'not_started') {
    stageStates.push({ stage: 'observe', status: 'blocked', detail: 'Smoke stage not executed yet' });
  } else {
    stageStates.push({ stage: 'observe', status: 'ready', detail: 'Observe post-release run health' });
  }

  return stageStates;
};

export const summarizeFailureTrend = (runs: RunRecord[]): {
  signal: 'insufficient_data' | 'stable' | 'increasing_failures';
  recent_failure_rate: number;
  previous_failure_rate: number;
} => {
  if (runs.length < 6) {
    return { signal: 'insufficient_data', recent_failure_rate: 0, previous_failure_rate: 0 };
  }
  const sorted = [...runs].sort((left, right) => {
    const leftTimestamp = Date.parse(left.created_at || left.updated_at || '') || 0;
    const rightTimestamp = Date.parse(right.created_at || right.updated_at || '') || 0;
    return rightTimestamp - leftTimestamp;
  });
  const recentWindow = sorted.slice(0, 5);
  const previousWindow = sorted.slice(5, 10);
  if (!recentWindow.length || !previousWindow.length) {
    return { signal: 'insufficient_data', recent_failure_rate: 0, previous_failure_rate: 0 };
  }
  const countFailures = (items: RunRecord[]) =>
    items.filter((item) => item.status === 'FAILED' || item.status === 'CANCELLED').length;
  const recentRate = countFailures(recentWindow) / recentWindow.length;
  const previousRate = countFailures(previousWindow) / previousWindow.length;
  return {
    signal: recentRate > previousRate + 0.2 ? 'increasing_failures' : 'stable',
    recent_failure_rate: recentRate,
    previous_failure_rate: previousRate,
  };
};

export const buildReleaseReport = (params: {
  workflow_id: string;
  tenant_id: string | null;
  project_id: string | null;
  candidate_version_id: string;
  published_version_id: string | null;
  validation: ValidationGateSummary;
  simulation: SimulationExecutionResult | null;
  diff: WorkflowDiffSummary;
  bind_targets: ReleaseReport['bind_targets'];
  smoke: SmokeResultSummary | null;
  operator_timestamps: Record<string, string>;
  exported_at?: string;
}): ReleaseReport => {
  const simulation = params.simulation || {
    status: 'not_run' as const,
    total_cases: 0,
    passed_cases: 0,
    failed_cases: 0,
    typed_failures: [],
    metrics: {
      action_accuracy: 0,
      workflow_accuracy: 0,
      exact_match_rate: 0,
      average_confidence: 0,
    },
    outcomes: [],
  };
  const smoke = params.smoke || {
    status: 'not_started' as const,
    run_id: null,
    correlation_id: null,
    typed_errors: [],
  };
  const runIds = smoke.run_id ? [smoke.run_id] : [];
  const correlationIds = smoke.correlation_id ? [smoke.correlation_id] : [];

  return {
    workflow_id: params.workflow_id,
    tenant_id: params.tenant_id,
    project_id: params.project_id,
    candidate_version_id: params.candidate_version_id,
    published_version_id: params.published_version_id,
    validation_result: {
      passed: params.validation.passed,
      blocking_issues: params.validation.blocking_issues.length,
      warnings: params.validation.warnings.length,
    },
    simulation_result: {
      status: simulation.status,
      total_cases: simulation.total_cases,
      passed_cases: simulation.passed_cases,
      failed_cases: simulation.failed_cases,
      typed_failures: simulation.typed_failures,
      metrics: simulation.metrics,
    },
    diff_summary: params.diff,
    bind_targets: params.bind_targets,
    smoke_result: smoke,
    operator_timestamps: params.operator_timestamps,
    run_ids: runIds,
    correlation_ids: correlationIds,
    exported_at: params.exported_at || new Date().toISOString(),
  };
};

export const buildReleaseReportFilename = (workflowId: string, timestamp: string): string => {
  const safeWorkflowId = workflowId.trim().replace(/[^a-zA-Z0-9_-]+/g, '_') || 'workflow';
  const safeTimestamp = timestamp.replace(/[:.]/g, '-');
  return `${safeWorkflowId}-release-report-${safeTimestamp}.json`;
};
