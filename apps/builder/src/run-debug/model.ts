import type { RunLedgerRecord, RunRecord } from '../api';

type RunNodeRecord = NonNullable<RunRecord['node_runs']>[number];

type AttemptTransition = 'initial' | 'auto_retry' | 'manual_rerun';

export type RunTimelineEvent = {
  id: string;
  ledgerId: string;
  timestamp: string;
  eventType: string;
  status: string;
  scope: 'run' | 'node';
  nodeId?: string;
  attempt?: number;
  transition?: AttemptTransition;
  message: string;
  payload: Record<string, unknown>;
};

export type RunAttemptRecord = {
  nodeId: string;
  attempt: number;
  status: string;
  transition: AttemptTransition;
  startedAt?: string;
  completedAt?: string;
  traceId?: string | null;
  lastError?: unknown;
  output?: unknown;
  usage?: unknown;
  timeline: RunTimelineEvent[];
};

export type RunAttemptGroup = {
  nodeId: string;
  attempts: RunAttemptRecord[];
};

export type RetryRerunRecord = {
  nodeId: string;
  fromAttempt: number;
  toAttempt: number;
  kind: 'auto_retry' | 'manual_rerun';
  timestamp: string;
  reason?: unknown;
};

export type LastGoodOutput =
  | {
      source: 'run.outputs';
      output: unknown;
      timestamp?: string;
    }
  | {
      source: 'node_attempt';
      nodeId: string;
      attempt: number;
      output: unknown;
      timestamp?: string;
    }
  | null;

export type AttemptDiffField = {
  field: 'output' | 'last_error' | 'usage';
  before: unknown;
  after: unknown;
};

export type AttemptDiffRecord = {
  nodeId: string;
  fromAttempt: number;
  toAttempt: number;
  changes: AttemptDiffField[];
};

export type RunTokenSummary = {
  inputTokens: number;
  outputTokens: number;
  totalTokens: number;
};

export type RunDebugModel = {
  timeline: RunTimelineEvent[];
  runTimeline: RunTimelineEvent[];
  nodeAttempts: RunAttemptGroup[];
  retryOrRerunHistory: RetryRerunRecord[];
  lastGoodOutput: LastGoodOutput;
};

type InternalRunAttemptGroup = RunAttemptGroup & { firstSeenOrder: number };

const EVENT_LABELS: Record<string, string> = {
  run_started: 'Run started',
  run_waiting_for_input: 'Waiting for input',
  run_completed: 'Run completed',
  run_failed: 'Run failed',
  run_cancelled: 'Run cancelled',
  node_started: 'Node started',
  node_completed: 'Node completed',
  node_failed: 'Node failed',
  node_retry: 'Node retry scheduled',
  message_generated: 'Message generated',
  snapshot: 'Snapshot emitted',
  stream_end: 'Stream ended'
};

const SECRET_KEY_PATTERN =
  /(authorization|auth_token|access_token|refresh_token|api[-_]?key|secret|password|credential|webhook[-_]?signature|connection[-_]?string|x-api-key)/i;
const HEAVY_BINARY_KEY_PATTERN = /(image_base64|_base64$|binary_blob|raw_image)/i;
const ARTIFACT_BODY_KEYS = new Set(['content', 'body', 'raw_body', 'blob', 'binary']);

const asUsageNumber = (value: unknown): number => {
  if (typeof value === 'number' && Number.isFinite(value)) return value;
  if (typeof value === 'string') {
    const parsed = Number(value);
    if (Number.isFinite(parsed)) return parsed;
  }
  return 0;
};

const isObjectRecord = (value: unknown): value is Record<string, unknown> => {
  return !!value && typeof value === 'object' && !Array.isArray(value);
};

const payloadAsObject = (value: unknown): Record<string, unknown> => {
  if (!isObjectRecord(value)) return {};
  return value;
};

const toTimestampMs = (value?: string): number => {
  if (!value) return Number.MAX_SAFE_INTEGER;
  const parsed = Date.parse(value);
  return Number.isFinite(parsed) ? parsed : Number.MAX_SAFE_INTEGER;
};

const nodeIdFromLedger = (entry: RunLedgerRecord): string | null => {
  if (typeof entry.node_id === 'string' && entry.node_id.trim()) return entry.node_id;
  if (typeof entry.step_id === 'string' && entry.step_id.trim()) return entry.step_id;
  return null;
};

const toEventMessage = (
  entry: RunLedgerRecord,
  payload: Record<string, unknown>,
  transition?: AttemptTransition
): string => {
  const base = EVENT_LABELS[entry.event_type] || entry.event_type;
  const error = payload.error;
  if ((entry.event_type === 'node_failed' || entry.event_type === 'run_failed') && error) {
    return `${base}: ${String(error)}`;
  }
  if (entry.event_type === 'node_retry' && error) {
    return `${base}: ${String(error)}`;
  }
  if (entry.event_type === 'node_started' && transition === 'manual_rerun') {
    return `${base} (manual rerun inferred)`;
  }
  return base;
};

const getOrCreateNodeGroup = (
  groupsByNode: Map<string, InternalRunAttemptGroup>,
  nodeId: string,
  firstSeenOrder: number
): InternalRunAttemptGroup => {
  let group = groupsByNode.get(nodeId);
  if (!group) {
    group = { nodeId, attempts: [], firstSeenOrder };
    groupsByNode.set(nodeId, group);
  }
  return group;
};

const createAttempt = (
  group: InternalRunAttemptGroup,
  nodeId: string,
  attempt: number,
  transition: AttemptTransition,
  timestamp: string | undefined
): RunAttemptRecord => {
  const created: RunAttemptRecord = {
    nodeId,
    attempt,
    status: 'IN_PROGRESS',
    transition,
    startedAt: timestamp,
    timeline: []
  };
  group.attempts.push(created);
  return created;
};

const extractTraceId = (payload: Record<string, unknown>): string | null => {
  if (typeof payload.trace_id === 'string' && payload.trace_id) return payload.trace_id;
  return null;
};

const attachPayloadToAttempt = (attempt: RunAttemptRecord, payload: Record<string, unknown>) => {
  if (Object.prototype.hasOwnProperty.call(payload, 'output')) {
    attempt.output = payload.output;
  }
  if (Object.prototype.hasOwnProperty.call(payload, 'usage')) {
    attempt.usage = payload.usage;
  }
  if (Object.prototype.hasOwnProperty.call(payload, 'error')) {
    attempt.lastError = payload.error;
  }
  const traceId = extractTraceId(payload);
  if (traceId) {
    attempt.traceId = traceId;
  }
};

const sortLedgerEntries = (entries: RunLedgerRecord[]): RunLedgerRecord[] => {
  return [...entries].sort((left, right) => {
    const leftTs = toTimestampMs(left.timestamp);
    const rightTs = toTimestampMs(right.timestamp);
    if (leftTs !== rightTs) return leftTs - rightTs;
    if (left.ledger_id && right.ledger_id && left.ledger_id !== right.ledger_id) {
      return left.ledger_id.localeCompare(right.ledger_id);
    }
    return left.event_type.localeCompare(right.event_type);
  });
};

const normalizeNodeStatus = (status: string | undefined): string => {
  if (!status) return 'UNKNOWN';
  if (status === 'SUCCESS') return 'RESOLVED';
  if (status === 'COMPLETED') return 'RESOLVED';
  if (status === 'FAILED') return 'ERROR';
  return status;
};

const mergeSnapshotNodeRuns = (
  run: RunRecord,
  groupsByNode: Map<string, InternalRunAttemptGroup>,
  timelineLength: number
) => {
  const nodeRuns = run.node_runs || [];
  nodeRuns.forEach((nodeRun, nodeRunIndex) => {
    const nodeId = nodeRun.node_id;
    if (!nodeId) return;

    const group = getOrCreateNodeGroup(groupsByNode, nodeId, timelineLength + nodeRunIndex + 1);
    let attempt = group.attempts[group.attempts.length - 1];
    if (!attempt) {
      const attemptNumber = typeof nodeRun.attempt === 'number' && nodeRun.attempt > 0 ? nodeRun.attempt : 1;
      attempt = createAttempt(group, nodeId, attemptNumber, 'initial', run.updated_at || run.created_at);
    }

    attempt.status = normalizeNodeStatus(nodeRun.status || attempt.status);
    if (Object.prototype.hasOwnProperty.call(nodeRun, 'output')) {
      attempt.output = nodeRun.output;
    }
    if (Object.prototype.hasOwnProperty.call(nodeRun, 'usage')) {
      attempt.usage = nodeRun.usage;
    }
    if (Object.prototype.hasOwnProperty.call(nodeRun, 'last_error')) {
      attempt.lastError = nodeRun.last_error;
    }
    if (Object.prototype.hasOwnProperty.call(nodeRun, 'trace_id')) {
      attempt.traceId = nodeRun.trace_id;
    }
  });
};

const sortedNodeGroups = (groupsByNode: Map<string, InternalRunAttemptGroup>): RunAttemptGroup[] => {
  return [...groupsByNode.values()]
    .sort((left, right) => {
      if (left.firstSeenOrder !== right.firstSeenOrder) {
        return left.firstSeenOrder - right.firstSeenOrder;
      }
      return left.nodeId.localeCompare(right.nodeId);
    })
    .map((group) => {
      const attempts = [...group.attempts].sort((leftAttempt, rightAttempt) => {
        if (leftAttempt.attempt !== rightAttempt.attempt) {
          return leftAttempt.attempt - rightAttempt.attempt;
        }
        return toTimestampMs(leftAttempt.startedAt) - toTimestampMs(rightAttempt.startedAt);
      });
      return { nodeId: group.nodeId, attempts };
    });
};

export const summarizeRunTokens = (run: RunRecord): RunTokenSummary => {
  return (run.node_runs || []).reduce<RunTokenSummary>(
    (acc, nodeRun) => {
      const usage = payloadAsObject(nodeRun.usage);
      const inputTokens = asUsageNumber(usage.input_tokens);
      const outputTokens = asUsageNumber(usage.output_tokens);
      const totalTokens = asUsageNumber(usage.total_tokens) || inputTokens + outputTokens;
      acc.inputTokens += inputTokens;
      acc.outputTokens += outputTokens;
      acc.totalTokens += totalTokens;
      return acc;
    },
    { inputTokens: 0, outputTokens: 0, totalTokens: 0 }
  );
};

export const estimateRunCostUsd = (
  summary: RunTokenSummary,
  inputRateUsdPer1M: number,
  outputRateUsdPer1M: number
): number => {
  const inputCost = (summary.inputTokens / 1_000_000) * Math.max(0, inputRateUsdPer1M);
  const outputCost = (summary.outputTokens / 1_000_000) * Math.max(0, outputRateUsdPer1M);
  return inputCost + outputCost;
};

export const resolveLastGoodOutput = (run: RunRecord, nodeAttempts: RunAttemptGroup[]): LastGoodOutput => {
  if (run.status === 'COMPLETED' && run.outputs !== null && run.outputs !== undefined) {
    return {
      source: 'run.outputs',
      output: run.outputs,
      timestamp: run.updated_at || run.created_at
    };
  }

  let bestCandidate: { nodeId: string; attempt: number; output: unknown; timestamp?: string; order: number } | null =
    null;
  let order = 0;

  nodeAttempts.forEach((group) => {
    group.attempts.forEach((attempt) => {
      order += 1;
      if (attempt.status !== 'RESOLVED') return;
      if (attempt.output === null || attempt.output === undefined) return;
      const timestamp = attempt.completedAt || attempt.startedAt;
      if (!bestCandidate) {
        bestCandidate = {
          nodeId: group.nodeId,
          attempt: attempt.attempt,
          output: attempt.output,
          timestamp,
          order
        };
        return;
      }
      const currentTs = toTimestampMs(bestCandidate.timestamp);
      const nextTs = toTimestampMs(timestamp);
      if (nextTs > currentTs || (nextTs === currentTs && order > bestCandidate.order)) {
        bestCandidate = {
          nodeId: group.nodeId,
          attempt: attempt.attempt,
          output: attempt.output,
          timestamp,
          order
        };
      }
    });
  });

  if (!bestCandidate) return null;
  return {
    source: 'node_attempt',
    nodeId: bestCandidate.nodeId,
    attempt: bestCandidate.attempt,
    output: bestCandidate.output,
    timestamp: bestCandidate.timestamp
  };
};

export const normalizeRunDebugData = (run: RunRecord, rawLedgerEntries: RunLedgerRecord[]): RunDebugModel => {
  const ledgerEntries = sortLedgerEntries(rawLedgerEntries);
  const timeline: RunTimelineEvent[] = [];
  const retryOrRerunHistory: RetryRerunRecord[] = [];
  const groupsByNode = new Map<string, InternalRunAttemptGroup>();
  const currentAttemptByNode = new Map<string, RunAttemptRecord>();
  const pendingRetry = new Map<string, { nextAttempt: number; reason?: unknown; timestamp: string }>();

  ledgerEntries.forEach((entry, index) => {
    const nodeId = nodeIdFromLedger(entry);
    const payload = payloadAsObject(entry.payload);
    let activeAttempt: RunAttemptRecord | undefined;

    if (nodeId) {
      const group = getOrCreateNodeGroup(groupsByNode, nodeId, index);
      const latestAttempt = group.attempts[group.attempts.length - 1];

      if (entry.event_type === 'node_started') {
        const pending = pendingRetry.get(nodeId);
        const nextAttempt = pending?.nextAttempt ?? ((latestAttempt?.attempt || 0) + 1);
        const transition: AttemptTransition = !latestAttempt
          ? 'initial'
          : pending
            ? 'auto_retry'
            : 'manual_rerun';
        activeAttempt = createAttempt(group, nodeId, nextAttempt, transition, entry.timestamp);
        activeAttempt.status = 'IN_PROGRESS';
        if (pending?.reason !== undefined) {
          activeAttempt.lastError = pending.reason;
        }
        if (latestAttempt && transition !== 'initial') {
          retryOrRerunHistory.push({
            nodeId,
            fromAttempt: latestAttempt.attempt,
            toAttempt: activeAttempt.attempt,
            kind: transition,
            timestamp: entry.timestamp,
            reason: pending?.reason
          });
        }
        pendingRetry.delete(nodeId);
        currentAttemptByNode.set(nodeId, activeAttempt);
      } else if (entry.event_type === 'node_retry') {
        activeAttempt = currentAttemptByNode.get(nodeId) || latestAttempt;
        if (!activeAttempt) {
          activeAttempt = createAttempt(group, nodeId, 1, 'initial', entry.timestamp);
          currentAttemptByNode.set(nodeId, activeAttempt);
        }
        activeAttempt.status = 'RETRYING';
        if (Object.prototype.hasOwnProperty.call(payload, 'error')) {
          activeAttempt.lastError = payload.error;
        }
        activeAttempt.completedAt = activeAttempt.completedAt || entry.timestamp;
        const payloadAttempt = asUsageNumber(payload.attempt);
        const nextAttempt = payloadAttempt > 0 ? payloadAttempt : activeAttempt.attempt + 1;
        pendingRetry.set(nodeId, {
          nextAttempt,
          reason: payload.error,
          timestamp: entry.timestamp
        });
      } else {
        activeAttempt = currentAttemptByNode.get(nodeId) || latestAttempt;
        if (!activeAttempt) {
          const attemptNumber = pendingRetry.get(nodeId)?.nextAttempt || 1;
          activeAttempt = createAttempt(group, nodeId, attemptNumber, 'initial', entry.timestamp);
          currentAttemptByNode.set(nodeId, activeAttempt);
        }

        if (entry.event_type === 'node_completed') {
          activeAttempt.status = 'RESOLVED';
          activeAttempt.completedAt = entry.timestamp;
        } else if (entry.event_type === 'node_failed') {
          activeAttempt.status = 'ERROR';
          activeAttempt.completedAt = entry.timestamp;
          if (Object.prototype.hasOwnProperty.call(payload, 'error')) {
            activeAttempt.lastError = payload.error;
          }
        } else if (entry.event_type === 'run_failed') {
          if (Object.prototype.hasOwnProperty.call(payload, 'error') && !activeAttempt.lastError) {
            activeAttempt.lastError = payload.error;
          }
          if (activeAttempt.status === 'IN_PROGRESS') {
            activeAttempt.status = 'ERROR';
            activeAttempt.completedAt = entry.timestamp;
          }
        }
      }

      if (activeAttempt) {
        attachPayloadToAttempt(activeAttempt, payload);
      }
    }

    const event: RunTimelineEvent = {
      id: entry.ledger_id || `${entry.event_type}-${index}`,
      ledgerId: entry.ledger_id,
      timestamp: entry.timestamp,
      eventType: entry.event_type,
      status: entry.status,
      scope: nodeId ? 'node' : 'run',
      nodeId: nodeId || undefined,
      attempt: activeAttempt?.attempt,
      transition: entry.event_type === 'node_started' ? activeAttempt?.transition : undefined,
      message: toEventMessage(entry, payload, activeAttempt?.transition),
      payload
    };

    timeline.push(event);
    if (activeAttempt) {
      activeAttempt.timeline.push(event);
    }
  });

  mergeSnapshotNodeRuns(run, groupsByNode, timeline.length);

  const nodeAttempts = sortedNodeGroups(groupsByNode);
  const lastGoodOutput = resolveLastGoodOutput(run, nodeAttempts);
  const runTimeline = timeline.filter((item) => item.scope === 'run');

  return {
    timeline,
    runTimeline,
    nodeAttempts,
    retryOrRerunHistory,
    lastGoodOutput
  };
};

const sortKeysDeep = (value: unknown): unknown => {
  if (Array.isArray(value)) {
    return value.map((item) => sortKeysDeep(item));
  }
  if (!isObjectRecord(value)) {
    return value;
  }
  const sortedKeys = Object.keys(value).sort((left, right) => left.localeCompare(right));
  const normalized: Record<string, unknown> = {};
  sortedKeys.forEach((key) => {
    normalized[key] = sortKeysDeep(value[key]);
  });
  return normalized;
};

export const stableStringify = (value: unknown, indent = 0): string => {
  return JSON.stringify(sortKeysDeep(value), null, indent || undefined);
};

const valuesEqual = (left: unknown, right: unknown): boolean => {
  return stableStringify(left) === stableStringify(right);
};

export const buildAttemptDiff = (
  previousAttempt: RunAttemptRecord,
  nextAttempt: RunAttemptRecord
): AttemptDiffRecord | null => {
  const changes: AttemptDiffField[] = [];
  const fields: Array<AttemptDiffField['field']> = ['output', 'last_error', 'usage'];
  fields.forEach((field) => {
    const previousValue =
      field === 'last_error' ? previousAttempt.lastError : field === 'output' ? previousAttempt.output : previousAttempt.usage;
    const nextValue = field === 'last_error' ? nextAttempt.lastError : field === 'output' ? nextAttempt.output : nextAttempt.usage;
    if (!valuesEqual(previousValue, nextValue)) {
      changes.push({ field, before: previousValue, after: nextValue });
    }
  });

  if (!changes.length) return null;
  return {
    nodeId: nextAttempt.nodeId,
    fromAttempt: previousAttempt.attempt,
    toAttempt: nextAttempt.attempt,
    changes
  };
};

const redactValue = (value: unknown): unknown => {
  if (Array.isArray(value)) {
    return value.map((item) => redactValue(item));
  }
  if (!isObjectRecord(value)) {
    return value;
  }

  const hasArtifactRef = typeof value.artifact_ref === 'string' && value.artifact_ref.trim().length > 0;
  const redacted: Record<string, unknown> = {};

  Object.keys(value)
    .sort((left, right) => left.localeCompare(right))
    .forEach((key) => {
      const rawValue = value[key];
      const keyLower = key.toLowerCase();

      if (SECRET_KEY_PATTERN.test(keyLower)) {
        redacted[key] = '[REDACTED_SECRET]';
        return;
      }
      if (HEAVY_BINARY_KEY_PATTERN.test(keyLower)) {
        const size = typeof rawValue === 'string' ? rawValue.length : 0;
        redacted[key] = `[REDACTED_BINARY:${size}]`;
        return;
      }
      if (hasArtifactRef && ARTIFACT_BODY_KEYS.has(keyLower)) {
        redacted[key] = '[REDACTED_ARTIFACT_BODY]';
        return;
      }

      redacted[key] = redactValue(rawValue);
    });

  return redacted;
};

export const redactSupportPayload = <T>(value: T): T => {
  return redactValue(value) as T;
};

export type RunSupportBundle = {
  bundle_type: 'run_support_bundle';
  bundle_version: 'run_debug_bundle_v1';
  generated_at: string;
  docs_links: string[];
  run_summary: Record<string, unknown>;
  typed_error_info: Record<string, unknown>;
  timeline: {
    total_events: number;
    items: RunTimelineEvent[];
  };
  node_attempts: RunAttemptGroup[];
  retry_rerun_history: RetryRerunRecord[];
  last_good_output: LastGoodOutput;
  ledger: {
    included_entries: number;
    total_available: number;
    truncated: boolean;
    items: RunLedgerRecord[];
  };
};

export const buildRunSupportBundle = (params: {
  run: RunRecord;
  ledgerEntries: RunLedgerRecord[];
  model?: RunDebugModel;
  ledgerLimit?: number;
  docsLinks?: string[];
}): RunSupportBundle => {
  const model = params.model || normalizeRunDebugData(params.run, params.ledgerEntries);
  const ledgerLimit = Math.max(1, Math.min(params.ledgerLimit || 500, 1000));
  const boundedLedger = sortLedgerEntries(params.ledgerEntries).slice(0, ledgerLimit);
  const tokenSummary = summarizeRunTokens(params.run);

  const bundle: RunSupportBundle = {
    bundle_type: 'run_support_bundle',
    bundle_version: 'run_debug_bundle_v1',
    generated_at: new Date().toISOString(),
    docs_links: params.docsLinks || ['/docs/api/reference.md', '/docs/architecture/runtime.md'],
    run_summary: {
      run_id: params.run.run_id,
      workflow_id: params.run.workflow_id,
      version_id: params.run.version_id,
      project_id: params.run.project_id || (payloadAsObject(params.run.metadata).project_id as string | undefined) || null,
      status: params.run.status,
      mode: params.run.mode || null,
      started_at: params.run.created_at || null,
      updated_at: params.run.updated_at || null,
      correlation_id:
        params.run.correlation_id || (payloadAsObject(params.run.metadata).correlation_id as string | undefined) || null,
      token_summary: tokenSummary,
      inputs: params.run.inputs || {},
      outputs: params.run.outputs,
      metadata: params.run.metadata || {}
    },
    typed_error_info: {
      error: (params.run as Record<string, unknown>).error,
      last_error: (params.run as Record<string, unknown>).last_error,
      failed_node_id: (params.run as Record<string, unknown>).failed_node_id
    },
    timeline: {
      total_events: model.timeline.length,
      items: model.timeline
    },
    node_attempts: model.nodeAttempts,
    retry_rerun_history: model.retryOrRerunHistory,
    last_good_output: model.lastGoodOutput,
    ledger: {
      included_entries: boundedLedger.length,
      total_available: params.ledgerEntries.length,
      truncated: boundedLedger.length < params.ledgerEntries.length,
      items: boundedLedger
    }
  };

  return redactSupportPayload(bundle);
};

export const formatSupportBundle = (bundle: RunSupportBundle): string => {
  return stableStringify(bundle, 2) + '\n';
};

export const hasContent = (value: unknown): boolean => {
  if (value === null || value === undefined) return false;
  if (Array.isArray(value)) return value.length > 0;
  if (isObjectRecord(value)) return Object.keys(value).length > 0;
  return true;
};

export const formatJson = (value: unknown): string => {
  try {
    return stableStringify(value, 2);
  } catch {
    return String(value);
  }
};

export const normalizeRunErrorText = (value: unknown): string => {
  if (value === null || value === undefined) return '';
  if (typeof value === 'string') return value;
  return stableStringify(value, 2);
};

export const formatTimestamp = (value?: string | null): string => {
  if (!value) return '';
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toLocaleString();
};

export const runStatusBadgeColor = (status: string): string => {
  if (status === 'COMPLETED') return 'teal';
  if (status === 'FAILED') return 'red';
  if (status === 'CANCELLED') return 'gray';
  if (status === 'WAITING_FOR_INPUT') return 'yellow';
  if (status === 'RUNNING') return 'blue';
  return 'gray';
};

export const nodeStatusBadgeColor = (status: string): string => {
  if (status === 'RESOLVED' || status === 'SUCCESS' || status === 'COMPLETED') return 'teal';
  if (status === 'ERROR' || status === 'FAILED') return 'red';
  if (status === 'RETRYING') return 'orange';
  if (status === 'CANCELLED' || status === 'SKIPPED') return 'gray';
  if (status === 'IN_PROGRESS') return 'blue';
  return 'gray';
};
