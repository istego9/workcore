import {
  Anchor,
  Badge,
  Button,
  Card,
  CopyButton,
  Divider,
  Drawer,
  Group,
  Select,
  SimpleGrid,
  Stack,
  Text
} from '@mantine/core';
import { useEffect, useMemo, useState } from 'react';
import { API_BASE, cancelRun, getRun, getRunLedger, rerunNode, type RunLedgerRecord, type RunRecord } from '../api';
import { JsonPreviewCard } from './JsonPreviewCard';
import {
  estimateRunCostUsd,
  formatTimestamp,
  normalizeRunDebugData,
  nodeStatusBadgeColor,
  runStatusBadgeColor,
  summarizeRunTokens,
  type RunDebugModel
} from './model';
import { RunAttemptHistory } from './RunAttemptHistory';
import { RunSupportBundleExport } from './RunSupportBundleExport';
import { RunTimeline } from './RunTimeline';

type StatusTone = 'idle' | 'ok' | 'warn' | 'error' | 'working';

type StatusUpdate = {
  tone: StatusTone;
  label: string;
  detail?: string;
};

type RunDebugPanelProps = {
  opened: boolean;
  runId: string | null;
  seedRun?: RunRecord | null;
  inputRateUsdPer1M: number;
  outputRateUsdPer1M: number;
  onClose: () => void;
  onStatus?: (status: StatusUpdate) => void;
  onRunUpdated?: (run: RunRecord) => void;
};

const formatUsd = (value: number) => {
  const safeValue = Number.isFinite(value) && value > 0 ? value : 0;
  if (safeValue > 0 && safeValue < 0.0001) return '< $0.0001';
  const digits = safeValue >= 1 ? 2 : 4;
  return new Intl.NumberFormat(undefined, {
    style: 'currency',
    currency: 'USD',
    minimumFractionDigits: digits,
    maximumFractionDigits: digits
  }).format(safeValue);
};

const asMetadataRecord = (run: RunRecord | null): Record<string, unknown> => {
  if (!run?.metadata || typeof run.metadata !== 'object' || Array.isArray(run.metadata)) {
    return {};
  }
  return run.metadata as Record<string, unknown>;
};

const metadataString = (run: RunRecord | null, key: string): string => {
  const metadata = asMetadataRecord(run);
  const value = metadata[key];
  return typeof value === 'string' ? value : '';
};

const emitRunInspectorLog = (eventType: string, run: RunRecord | null, runId: string | null, details?: Record<string, unknown>) => {
  const payload = {
    event: 'run_inspector',
    event_type: eventType,
    run_id: run?.run_id || runId || null,
    workflow_id: run?.workflow_id || null,
    version_id: run?.version_id || null,
    tenant_id: run?.tenant_id || metadataString(run, 'tenant_id') || null,
    project_id: run?.project_id || metadataString(run, 'project_id') || null,
    correlation_id: run?.correlation_id || metadataString(run, 'correlation_id') || null,
    trace_id: run?.trace_id || metadataString(run, 'trace_id') || null,
    timestamp: new Date().toISOString(),
    ...details
  };
  // Keep inspector logs structured and free of payload contents.
  console.info('[run-inspector]', payload);
};

const runIsCancellable = (run: RunRecord | null): boolean => {
  if (!run) return false;
  if (typeof (run as Record<string, unknown>).cancellable === 'boolean') {
    return Boolean((run as Record<string, unknown>).cancellable);
  }
  return run.status === 'RUNNING' || run.status === 'WAITING_FOR_INPUT';
};

const runActiveStatuses = new Set(['RUNNING', 'WAITING_FOR_INPUT']);

export function RunDebugPanel({
  opened,
  runId,
  seedRun = null,
  inputRateUsdPer1M,
  outputRateUsdPer1M,
  onClose,
  onStatus,
  onRunUpdated
}: RunDebugPanelProps) {
  const [run, setRun] = useState<RunRecord | null>(seedRun);
  const [ledgerEntries, setLedgerEntries] = useState<RunLedgerRecord[]>([]);
  const [loading, setLoading] = useState(false);
  const [rerunScope, setRerunScope] = useState<'node_only' | 'downstream'>('downstream');
  const [selectedNodeForRerun, setSelectedNodeForRerun] = useState<string | null>(null);
  const [rerunLoadingNodeId, setRerunLoadingNodeId] = useState<string | null>(null);
  const [cancelLoading, setCancelLoading] = useState(false);

  useEffect(() => {
    if (!opened || !runId) return;
    if (seedRun && seedRun.run_id === runId) {
      setRun(seedRun);
    }
  }, [opened, runId, seedRun]);

  const refreshInspector = async (reason: 'open' | 'manual' | 'action' = 'manual') => {
    if (!runId) return;

    setLoading(true);
    const [runResult, ledgerResult] = await Promise.all([getRun(runId), getRunLedger(runId, { limit: 500 })]);

    if (runResult.error && ledgerResult.error) {
      onStatus?.({
        tone: 'error',
        label: 'Run inspector refresh failed',
        detail: `${runResult.error.message}; ${ledgerResult.error.message}`
      });
      setLoading(false);
      return;
    }

    if (runResult.error) {
      onStatus?.({ tone: 'warn', label: 'Run details partially loaded', detail: runResult.error.message });
    }
    if (ledgerResult.error) {
      onStatus?.({ tone: 'warn', label: 'Run ledger partially loaded', detail: ledgerResult.error.message });
    }

    if (runResult.data) {
      setRun(runResult.data);
      onRunUpdated?.(runResult.data);
      emitRunInspectorLog('inspector_opened', runResult.data, runId, {
        refresh_reason: reason,
        active: runActiveStatuses.has(runResult.data.status)
      });
    }
    if (ledgerResult.data?.items) {
      setLedgerEntries(ledgerResult.data.items);
    }
    if (reason === 'manual') {
      onStatus?.({ tone: 'ok', label: 'Run inspector refreshed' });
    }

    setLoading(false);
  };

  useEffect(() => {
    if (!opened || !runId) return;
    void refreshInspector('open');
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [opened, runId]);

  const model: RunDebugModel | null = useMemo(() => {
    if (!run) return null;
    return normalizeRunDebugData(run, ledgerEntries);
  }, [run, ledgerEntries]);

  const nodeOptions = useMemo(() => {
    if (!model) return [];
    return model.nodeAttempts.map((group) => ({ value: group.nodeId, label: group.nodeId }));
  }, [model]);

  useEffect(() => {
    if (!nodeOptions.length) {
      setSelectedNodeForRerun(null);
      return;
    }
    if (selectedNodeForRerun && nodeOptions.some((item) => item.value === selectedNodeForRerun)) {
      return;
    }
    setSelectedNodeForRerun(nodeOptions[0].value);
  }, [nodeOptions, selectedNodeForRerun]);

  const tokenSummary = useMemo(() => (run ? summarizeRunTokens(run) : null), [run]);
  const estimatedCost = useMemo(() => {
    if (!tokenSummary) return 0;
    return estimateRunCostUsd(tokenSummary, inputRateUsdPer1M, outputRateUsdPer1M);
  }, [tokenSummary, inputRateUsdPer1M, outputRateUsdPer1M]);

  const correlationId = run?.correlation_id || metadataString(run, 'correlation_id') || '';
  const traceId = run?.trace_id || metadataString(run, 'trace_id') || '';
  const projectId = run?.project_id || metadataString(run, 'project_id') || '';

  const handleRerunNode = async (nodeId: string) => {
    if (!run || !runId) return;
    setRerunLoadingNodeId(nodeId);
    emitRunInspectorLog('rerun_initiated', run, runId, { node_id: nodeId, scope: rerunScope });

    const result = await rerunNode(runId, { node_id: nodeId, scope: rerunScope });
    if (result.error) {
      onStatus?.({ tone: 'error', label: 'Rerun failed', detail: result.error.message });
      setRerunLoadingNodeId(null);
      return;
    }

    if (result.data) {
      setRun(result.data);
      onRunUpdated?.(result.data);
      onStatus?.({ tone: 'ok', label: 'Rerun started', detail: `${nodeId} (${rerunScope})` });
    }

    setRerunLoadingNodeId(null);
    await refreshInspector('action');
  };

  const handleCancelRun = async () => {
    if (!run || !runId) return;
    setCancelLoading(true);
    emitRunInspectorLog('cancel_initiated', run, runId);

    const result = await cancelRun(runId);
    if (result.error) {
      onStatus?.({ tone: 'error', label: 'Cancel failed', detail: result.error.message });
      setCancelLoading(false);
      return;
    }

    if (result.data) {
      setRun(result.data);
      onRunUpdated?.(result.data);
      onStatus?.({ tone: 'ok', label: 'Run cancelled', detail: result.data.run_id });
    }

    setCancelLoading(false);
    await refreshInspector('action');
  };

  const handleExported = () => {
    emitRunInspectorLog('support_bundle_exported', run, runId, { ledger_entries: ledgerEntries.length });
    onStatus?.({ tone: 'ok', label: 'Support bundle exported', detail: run?.run_id });
  };

  return (
    <Drawer
      opened={opened}
      onClose={onClose}
      title={runId ? `Run Debug · ${runId}` : 'Run Debug'}
      position="right"
      size="xl"
      padding="md"
    >
      {!runId ? (
        <Text size="sm" c="dimmed">
          Select a run from execution history.
        </Text>
      ) : (
        <Stack gap="sm">
          <Group justify="space-between" align="center" wrap="wrap">
            <Group gap={6} wrap="wrap">
              {run && (
                <Badge color={runStatusBadgeColor(run.status)} variant="light">
                  {run.status}
                </Badge>
              )}
              {run?.mode && (
                <Badge variant="outline" color="gray">
                  {run.mode.toUpperCase()}
                </Badge>
              )}
              {tokenSummary && (
                <Badge variant="outline" color="indigo">
                  Tokens {Math.round(tokenSummary.totalTokens).toLocaleString()}
                </Badge>
              )}
              <Badge variant="outline" color="green">
                {formatUsd(estimatedCost)}
              </Badge>
            </Group>
            <Group gap={6}>
              <Button size="xs" variant="light" onClick={() => void refreshInspector('manual')} loading={loading}>
                Refresh inspector
              </Button>
              <Button
                size="xs"
                variant="light"
                color="red"
                onClick={() => void handleCancelRun()}
                loading={cancelLoading}
                disabled={!runIsCancellable(run)}
              >
                Cancel run
              </Button>
            </Group>
          </Group>

          <Card withBorder radius="sm" padding="sm">
            <Stack gap="xs">
              <Text size="sm" fw={600}>
                Run summary
              </Text>
              <SimpleGrid cols={{ base: 1, sm: 2 }} spacing="sm">
                <Group justify="space-between" wrap="nowrap">
                  <Text size="xs" c="dimmed">
                    run_id
                  </Text>
                  <CopyButton value={run?.run_id || runId}>
                    {({ copied, copy }) => (
                      <Button size="compact-xs" variant="light" onClick={copy}>
                        {copied ? 'Copied' : run?.run_id || runId}
                      </Button>
                    )}
                  </CopyButton>
                </Group>
                <Group justify="space-between" wrap="nowrap">
                  <Text size="xs" c="dimmed">
                    workflow_id
                  </Text>
                  <CopyButton value={run?.workflow_id || ''}>
                    {({ copied, copy }) => (
                      <Button size="compact-xs" variant="light" onClick={copy} disabled={!run?.workflow_id}>
                        {copied ? 'Copied' : run?.workflow_id || '—'}
                      </Button>
                    )}
                  </CopyButton>
                </Group>
                <Group justify="space-between" wrap="nowrap">
                  <Text size="xs" c="dimmed">
                    version_id
                  </Text>
                  <CopyButton value={run?.version_id || ''}>
                    {({ copied, copy }) => (
                      <Button size="compact-xs" variant="light" onClick={copy} disabled={!run?.version_id}>
                        {copied ? 'Copied' : run?.version_id || '—'}
                      </Button>
                    )}
                  </CopyButton>
                </Group>
                <Group justify="space-between" wrap="nowrap">
                  <Text size="xs" c="dimmed">
                    project_id
                  </Text>
                  <CopyButton value={projectId}>
                    {({ copied, copy }) => (
                      <Button size="compact-xs" variant="light" onClick={copy} disabled={!projectId}>
                        {copied ? 'Copied' : projectId || '—'}
                      </Button>
                    )}
                  </CopyButton>
                </Group>
                <Group justify="space-between" wrap="nowrap">
                  <Text size="xs" c="dimmed">
                    correlation_id
                  </Text>
                  <CopyButton value={correlationId}>
                    {({ copied, copy }) => (
                      <Button size="compact-xs" variant="light" onClick={copy} disabled={!correlationId}>
                        {copied ? 'Copied' : correlationId || '—'}
                      </Button>
                    )}
                  </CopyButton>
                </Group>
                <Group justify="space-between" wrap="nowrap">
                  <Text size="xs" c="dimmed">
                    trace_id
                  </Text>
                  <CopyButton value={traceId}>
                    {({ copied, copy }) => (
                      <Button size="compact-xs" variant="light" onClick={copy} disabled={!traceId}>
                        {copied ? 'Copied' : traceId || '—'}
                      </Button>
                    )}
                  </CopyButton>
                </Group>
              </SimpleGrid>
              <Group gap={6} wrap="wrap">
                <Text size="xs" c="dimmed">
                  Started {formatTimestamp(run?.created_at || null) || '—'}
                </Text>
                <Text size="xs" c="dimmed">
                  Updated {formatTimestamp(run?.updated_at || null) || '—'}
                </Text>
              </Group>
              {run && (
                <Group gap={8} wrap="wrap">
                  <Anchor href={`${API_BASE}/runs/${encodeURIComponent(run.run_id)}`} target="_blank" rel="noreferrer">
                    Run snapshot endpoint
                  </Anchor>
                  <Anchor
                    href={`${API_BASE}/runs/${encodeURIComponent(run.run_id)}/ledger?limit=500`}
                    target="_blank"
                    rel="noreferrer"
                  >
                    Ledger endpoint
                  </Anchor>
                </Group>
              )}
            </Stack>
          </Card>

          <Card withBorder radius="sm" padding="sm">
            <Stack gap="xs">
              <Text size="sm" fw={600}>
                Debug actions
              </Text>
              <SimpleGrid cols={{ base: 1, sm: 3 }} spacing="sm">
                <Select
                  label="Node"
                  value={selectedNodeForRerun}
                  data={nodeOptions}
                  onChange={(value) => setSelectedNodeForRerun(value)}
                  placeholder="Select node"
                  searchable
                />
                <Select
                  label="Rerun scope"
                  value={rerunScope}
                  data={[
                    { value: 'downstream', label: 'downstream' },
                    { value: 'node_only', label: 'node_only' }
                  ]}
                  onChange={(value) => setRerunScope((value as 'downstream' | 'node_only') || 'downstream')}
                />
                <Stack gap={6} justify="flex-end">
                  <Text size="xs" c="dimmed">
                    Use existing rerun contract
                  </Text>
                  <Button
                    size="xs"
                    variant="light"
                    onClick={() => selectedNodeForRerun && void handleRerunNode(selectedNodeForRerun)}
                    loading={!!rerunLoadingNodeId && rerunLoadingNodeId === selectedNodeForRerun}
                    disabled={!selectedNodeForRerun}
                  >
                    Rerun node
                  </Button>
                </Stack>
              </SimpleGrid>
              {run?.status === 'WAITING_FOR_INPUT' && (
                <Text size="xs" c="yellow">
                  Run is waiting for input. Inspect interrupt details through run state/metadata before retrying.
                </Text>
              )}
            </Stack>
          </Card>

          <Divider />

          {run && model ? (
            <Stack gap="sm">
              <Card withBorder radius="sm" padding="sm">
                <Stack gap="xs">
                  <Text size="sm" fw={600}>
                    Timeline
                  </Text>
                  <RunTimeline runTimeline={model.runTimeline} nodeAttempts={model.nodeAttempts} />
                </Stack>
              </Card>

              <Card withBorder radius="sm" padding="sm">
                <Stack gap="xs">
                  <Text size="sm" fw={600}>
                    Node attempts
                  </Text>
                  <RunAttemptHistory
                    nodeAttempts={model.nodeAttempts}
                    onRerunNode={(nodeId) => void handleRerunNode(nodeId)}
                    rerunLoadingNodeId={rerunLoadingNodeId}
                  />
                </Stack>
              </Card>

              <Card withBorder radius="sm" padding="sm">
                <Stack gap="xs">
                  <Text size="sm" fw={600}>
                    Last good output
                  </Text>
                  <Text size="xs" c="dimmed">
                    Rule: if run.outputs exists and run is COMPLETED, that output is canonical. Otherwise use the most
                    recent RESOLVED node attempt output in execution order.
                  </Text>
                  {!model.lastGoodOutput ? (
                    <Text size="xs" c="dimmed">
                      No last known good output was found.
                    </Text>
                  ) : model.lastGoodOutput.source === 'run.outputs' ? (
                    <JsonPreviewCard title="run.outputs" value={model.lastGoodOutput.output} withCopy maxHeight={220} />
                  ) : (
                    <Stack gap="xs">
                      <Group gap={6}>
                        <Badge variant="outline" color="gray">
                          Node {model.lastGoodOutput.nodeId}
                        </Badge>
                        <Badge variant="outline" color={nodeStatusBadgeColor('RESOLVED')}>
                          Attempt {model.lastGoodOutput.attempt}
                        </Badge>
                      </Group>
                      <JsonPreviewCard title="Node attempt output" value={model.lastGoodOutput.output} withCopy maxHeight={220} />
                    </Stack>
                  )}
                </Stack>
              </Card>

              <Card withBorder radius="sm" padding="sm">
                <Stack gap="xs">
                  <Text size="sm" fw={600}>
                    Retry / rerun history
                  </Text>
                  {model.retryOrRerunHistory.length === 0 ? (
                    <Text size="xs" c="dimmed">
                      No retry or rerun transitions inferred from ledger.
                    </Text>
                  ) : (
                    model.retryOrRerunHistory.map((item, index) => (
                      <Stack key={`${item.nodeId}-${item.fromAttempt}-${item.toAttempt}-${index}`} gap={6}>
                        {index > 0 && <Divider />}
                        <Group justify="space-between" align="flex-start">
                          <Stack gap={2}>
                            <Text size="sm" fw={500}>
                              {item.nodeId}: attempt {item.fromAttempt} → {item.toAttempt}
                            </Text>
                            <Text size="xs" c="dimmed">
                              {formatTimestamp(item.timestamp)}
                            </Text>
                            {item.reason !== undefined && item.reason !== null && item.reason !== '' && (
                              <Text size="xs" c="dimmed" ff="monospace">
                                {typeof item.reason === 'string' ? item.reason : JSON.stringify(item.reason)}
                              </Text>
                            )}
                          </Stack>
                          <Badge variant="light" color={item.kind === 'auto_retry' ? 'orange' : 'blue'}>
                            {item.kind === 'auto_retry' ? 'Auto retry' : 'Manual rerun'}
                          </Badge>
                        </Group>
                      </Stack>
                    ))
                  )}
                </Stack>
              </Card>

              <RunSupportBundleExport
                run={run}
                ledgerEntries={ledgerEntries}
                model={model}
                loading={loading}
                onExported={handleExported}
              />
            </Stack>
          ) : (
            <Text size="xs" c="dimmed">
              {loading ? 'Loading run inspector…' : 'Run details are not available.'}
            </Text>
          )}
        </Stack>
      )}
    </Drawer>
  );
}
