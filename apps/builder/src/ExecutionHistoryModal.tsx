import {
  Badge,
  Button,
  Card,
  Divider,
  Group,
  Modal,
  NumberInput,
  ScrollArea,
  Select,
  SimpleGrid,
  Stack,
  Text,
} from '@mantine/core';
import { useMemo } from 'react';
import type { RunRecord } from './api';

type RunNodeRecord = NonNullable<RunRecord['node_runs']>[number];
type TokenSummary = { inputTokens: number; outputTokens: number; totalTokens: number };
type DailyRunSummary = {
  day: string;
  runs: number;
  inputTokens: number;
  outputTokens: number;
  totalTokens: number;
  totalCostUsd: number;
  avgTokens: number;
  avgCostUsd: number;
};
type HistorySummary = {
  runCount: number;
  inputTokens: number;
  outputTokens: number;
  totalTokens: number;
  totalCostUsd: number;
  avgTokensPerRun: number;
  avgCostPerRun: number;
  days: DailyRunSummary[];
};
export type HistoryWorkflowScope = 'selected' | 'all';
export type HistoryProjectScope = 'active' | 'all';
type RunInputDocumentPreview = {
  docId: string;
  filename: string;
  docType: string;
  pages: number;
  textChars: number;
  imageBase64Chars: number;
  textSample: string;
};

const TOKENS_IN_MILLION = 1_000_000;

const formatTimestamp = (value?: string | null) => {
  if (!value) return '';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString();
};

const runStatusBadgeColor = (status: string) => {
  if (status === 'COMPLETED') return 'teal';
  if (status === 'FAILED') return 'red';
  if (status === 'CANCELLED') return 'gray';
  if (status === 'WAITING_FOR_INPUT') return 'yellow';
  return 'blue';
};

const nodeStatusBadgeColor = (status: string) => {
  if (status === 'SUCCESS' || status === 'COMPLETED' || status === 'RESOLVED') return 'teal';
  if (status === 'ERROR' || status === 'FAILED') return 'red';
  if (status === 'SKIPPED' || status === 'CANCELLED') return 'gray';
  if (status === 'WAITING_FOR_INPUT') return 'yellow';
  return 'blue';
};

const runFailureReason = (run: RunRecord) => {
  if (run.status !== 'FAILED') return null;
  const failedNode =
    run.node_runs?.find((nodeRun) => nodeRun.status === 'ERROR' && nodeRun.last_error) ||
    run.node_runs?.find((nodeRun) => !!nodeRun.last_error);
  if (!failedNode?.last_error) return null;
  return String(failedNode.last_error);
};

const asUsageNumber = (value: unknown) => {
  if (typeof value === 'number' && Number.isFinite(value)) return value;
  if (typeof value === 'string') {
    const parsed = Number(value);
    if (Number.isFinite(parsed)) return parsed;
  }
  return 0;
};

const nodeTokenSummary = (nodeRun: RunNodeRecord): TokenSummary | null => {
  const usage = nodeRun.usage;
  if (!usage || typeof usage !== 'object') return null;
  const inputTokens = asUsageNumber(usage.input_tokens);
  const outputTokens = asUsageNumber(usage.output_tokens);
  const totalTokens = asUsageNumber(usage.total_tokens) || inputTokens + outputTokens;
  if (!totalTokens && !inputTokens && !outputTokens) return null;
  return { inputTokens, outputTokens, totalTokens };
};

const runTokenSummary = (run: RunRecord): TokenSummary =>
  (run.node_runs || []).reduce<TokenSummary>(
    (acc, nodeRun) => {
      const nodeTotals = nodeTokenSummary(nodeRun);
      if (!nodeTotals) return acc;
      return {
        inputTokens: acc.inputTokens + nodeTotals.inputTokens,
        outputTokens: acc.outputTokens + nodeTotals.outputTokens,
        totalTokens: acc.totalTokens + nodeTotals.totalTokens
      };
    },
    { inputTokens: 0, outputTokens: 0, totalTokens: 0 }
  );

const runNodeStats = (run: RunRecord) =>
  (run.node_runs || []).reduce(
    (acc, nodeRun) => {
      acc.total += 1;
      if (nodeRun.status === 'COMPLETED' || nodeRun.status === 'SUCCESS' || nodeRun.status === 'RESOLVED') {
        acc.completed += 1;
      } else if (nodeRun.status === 'FAILED' || nodeRun.status === 'ERROR') {
        acc.failed += 1;
      } else if (nodeRun.status === 'WAITING_FOR_INPUT') {
        acc.waiting += 1;
      } else if (nodeRun.status === 'IN_PROGRESS') {
        acc.inProgress += 1;
      } else {
        acc.todo += 1;
      }
      return acc;
    },
    { total: 0, completed: 0, failed: 0, waiting: 0, inProgress: 0, todo: 0 }
  );

const asUsdRate = (value: unknown) => {
  if (typeof value === 'number' && Number.isFinite(value) && value >= 0) return value;
  if (typeof value === 'string') {
    const parsed = Number(value);
    if (Number.isFinite(parsed) && parsed >= 0) return parsed;
  }
  return 0;
};

export const DEFAULT_INPUT_RATE_USD_PER_1M = asUsdRate(import.meta.env.VITE_USAGE_COST_INPUT_USD_PER_1M);
export const DEFAULT_OUTPUT_RATE_USD_PER_1M = asUsdRate(import.meta.env.VITE_USAGE_COST_OUTPUT_USD_PER_1M);

const estimateCostUsd = (
  tokens: TokenSummary | null,
  inputRateUsdPer1M: number,
  outputRateUsdPer1M: number
) => {
  if (!tokens) return 0;
  const inputCost = (tokens.inputTokens / TOKENS_IN_MILLION) * inputRateUsdPer1M;
  const outputCost = (tokens.outputTokens / TOKENS_IN_MILLION) * outputRateUsdPer1M;
  return inputCost + outputCost;
};

const runDayKey = (run: RunRecord) => {
  const value = run.created_at || run.updated_at;
  if (!value) return 'Unknown date';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return 'Unknown date';
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, '0');
  const day = String(date.getDate()).padStart(2, '0');
  return `${year}-${month}-${day}`;
};

const summarizeHistory = (
  runs: RunRecord[],
  inputRateUsdPer1M: number,
  outputRateUsdPer1M: number
): HistorySummary => {
  const daily = new Map<
    string,
    {
      runs: number;
      inputTokens: number;
      outputTokens: number;
      totalTokens: number;
      totalCostUsd: number;
    }
  >();

  let inputTokens = 0;
  let outputTokens = 0;
  let totalTokens = 0;
  let totalCostUsd = 0;

  runs.forEach((run) => {
    const tokens = runTokenSummary(run);
    const runCost = estimateCostUsd(tokens, inputRateUsdPer1M, outputRateUsdPer1M);
    const day = runDayKey(run);
    const dayState = daily.get(day) || {
      runs: 0,
      inputTokens: 0,
      outputTokens: 0,
      totalTokens: 0,
      totalCostUsd: 0
    };

    dayState.runs += 1;
    dayState.inputTokens += tokens.inputTokens;
    dayState.outputTokens += tokens.outputTokens;
    dayState.totalTokens += tokens.totalTokens;
    dayState.totalCostUsd += runCost;
    daily.set(day, dayState);

    inputTokens += tokens.inputTokens;
    outputTokens += tokens.outputTokens;
    totalTokens += tokens.totalTokens;
    totalCostUsd += runCost;
  });

  const days: DailyRunSummary[] = Array.from(daily.entries())
    .map(([day, totals]) => ({
      day,
      runs: totals.runs,
      inputTokens: totals.inputTokens,
      outputTokens: totals.outputTokens,
      totalTokens: totals.totalTokens,
      totalCostUsd: totals.totalCostUsd,
      avgTokens: totals.runs > 0 ? totals.totalTokens / totals.runs : 0,
      avgCostUsd: totals.runs > 0 ? totals.totalCostUsd / totals.runs : 0
    }))
    .sort((a, b) => {
      if (a.day === 'Unknown date') return 1;
      if (b.day === 'Unknown date') return -1;
      return a.day < b.day ? 1 : -1;
    });

  const runCount = runs.length;
  return {
    runCount,
    inputTokens,
    outputTokens,
    totalTokens,
    totalCostUsd,
    avgTokensPerRun: runCount > 0 ? totalTokens / runCount : 0,
    avgCostPerRun: runCount > 0 ? totalCostUsd / runCount : 0,
    days
  };
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

const hasContent = (value: unknown) => {
  if (value === null || value === undefined) return false;
  if (Array.isArray(value)) return value.length > 0;
  if (typeof value === 'object') return Object.keys(value as Record<string, unknown>).length > 0;
  return true;
};

const asObjectRecord = (value: unknown): Record<string, unknown> | null => {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return null;
  return value as Record<string, unknown>;
};

const asUnknownArray = (value: unknown): unknown[] => {
  if (!Array.isArray(value)) return [];
  return value;
};

const asString = (value: unknown): string => {
  if (typeof value !== 'string') return '';
  return value;
};

const truncateText = (value: string, maxLength = 320): string => {
  if (!value) return '';
  if (value.length <= maxLength) return value;
  return `${value.slice(0, maxLength - 3)}...`;
};

const summarizeRunDocuments = (inputs: unknown): RunInputDocumentPreview[] => {
  const inputsObject = asObjectRecord(inputs);
  if (!inputsObject) return [];
  const documents = asUnknownArray(inputsObject.documents);

  return documents
    .map((item, index) => {
      const doc = asObjectRecord(item);
      if (!doc) return null;

      const pages = asUnknownArray(doc.pages);
      let textChars = 0;
      let imageBase64Chars = 0;
      let firstTextSample = '';

      pages.forEach((pageItem) => {
        const page = asObjectRecord(pageItem);
        if (!page) return;

        const textSources = [asString(page.text), asString(page.ocr_text), asString(page.markdown)];
        textSources.forEach((source) => {
          if (!source) return;
          textChars += source.length;
          if (!firstTextSample) {
            firstTextSample = source;
          }
        });

        const imageBase64 = asString(page.image_base64);
        if (imageBase64) {
          imageBase64Chars += imageBase64.length;
        }
      });

      const docLevelImageBase64 = asString(doc.image_base64);
      if (docLevelImageBase64) {
        imageBase64Chars += docLevelImageBase64.length;
      }

      return {
        docId: asString(doc.doc_id) || `doc_${index + 1}`,
        filename: asString(doc.filename) || `Document ${index + 1}`,
        docType: asString(doc.type) || 'unknown',
        pages: pages.length,
        textChars,
        imageBase64Chars,
        textSample: truncateText(firstTextSample.trim())
      };
    })
    .filter((item): item is RunInputDocumentPreview => !!item);
};

const formatJson = (value: unknown) => {
  try {
    return JSON.stringify(value ?? {}, null, 2);
  } catch {
    return String(value);
  }
};

type JsonPreviewCardProps = {
  title: string;
  value: unknown;
  emptyLabel?: string;
  maxHeight?: number;
};

function JsonPreviewCard({ title, value, emptyLabel = 'No data', maxHeight = 220 }: JsonPreviewCardProps) {
  const contentVisible = hasContent(value);
  return (
    <Card withBorder radius="sm" padding="sm">
      <Stack gap={6}>
        <Group justify="space-between" align="center">
          <Text size="xs" fw={600}>
            {title}
          </Text>
          {!contentVisible && (
            <Text size="xs" c="dimmed">
              {emptyLabel}
            </Text>
          )}
        </Group>
        {contentVisible && (
          <ScrollArea.Autosize mah={maxHeight}>
            <Text
              component="pre"
              fz="xs"
              ff="monospace"
              style={{ margin: 0, whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}
            >
              {formatJson(value)}
            </Text>
          </ScrollArea.Autosize>
        )}
      </Stack>
    </Card>
  );
}

type ExecutionHistoryModalProps = {
  opened: boolean;
  onClose: () => void;
  workflowId: string;
  activeProjectId?: string;
  runHistoryRaw: RunRecord[];
  runHistory: RunRecord[];
  runHistoryLoading: boolean;
  runHistoryExpandedId: string | null;
  historyWorkflowScope: HistoryWorkflowScope;
  historyProjectScope: HistoryProjectScope;
  historyInputRateUsdPer1M: number;
  historyOutputRateUsdPer1M: number;
  onWorkflowScopeChange: (value: HistoryWorkflowScope) => void;
  onProjectScopeChange: (value: HistoryProjectScope) => void;
  onInputRateChange: (value: number) => void;
  onOutputRateChange: (value: number) => void;
  onToggleExpanded: (runId: string) => void;
  onRefresh: () => void;
  onOpenRunDebug: (run: RunRecord) => void;
};

export function ExecutionHistoryModal({
  opened,
  onClose,
  workflowId,
  activeProjectId,
  runHistoryRaw,
  runHistory,
  runHistoryLoading,
  runHistoryExpandedId,
  historyWorkflowScope,
  historyProjectScope,
  historyInputRateUsdPer1M,
  historyOutputRateUsdPer1M,
  onWorkflowScopeChange,
  onProjectScopeChange,
  onInputRateChange,
  onOutputRateChange,
  onToggleExpanded,
  onRefresh,
  onOpenRunDebug
}: ExecutionHistoryModalProps) {
  const runHistoryProjectIds = useMemo(
    () =>
      Array.from(
        new Set(
          runHistoryRaw
            .map((item) => {
              if (typeof item.project_id !== 'string') return '';
              return item.project_id.trim();
            })
            .filter((value): value is string => !!value)
        )
      ).sort(),
    [runHistoryRaw]
  );
  const filteredOutRunCount = Math.max(runHistoryRaw.length - runHistory.length, 0);
  const historySummary = useMemo(
    () => summarizeHistory(runHistory, historyInputRateUsdPer1M, historyOutputRateUsdPer1M),
    [runHistory, historyInputRateUsdPer1M, historyOutputRateUsdPer1M]
  );
  const hasCostRates = historyInputRateUsdPer1M > 0 || historyOutputRateUsdPer1M > 0;

  return (
    <Modal opened={opened} onClose={onClose} title="Execution history" centered size="lg">
      <Stack gap="sm">
        <Group justify="space-between" align="center">
          <Stack gap={2}>
            <Text size="sm" c="dimmed">
              {workflowId ? `Workflow ${workflowId}` : 'No workflow selected'}
            </Text>
            <Text size="xs" c="dimmed">
              Active project {activeProjectId || '—'}
            </Text>
          </Stack>
          <Button
            variant="light"
            loading={runHistoryLoading}
            onClick={onRefresh}
            disabled={historyWorkflowScope === 'selected' && !workflowId}
          >
            Refresh
          </Button>
        </Group>
        <Card withBorder radius="md" padding="sm">
          <Stack gap="xs">
            <SimpleGrid cols={{ base: 1, sm: 2 }} spacing="sm">
              <Select
                label="Workflow scope"
                value={historyWorkflowScope}
                data={[
                  { value: 'selected', label: 'Selected workflow' },
                  { value: 'all', label: 'All workflows' }
                ]}
                allowDeselect={false}
                onChange={(value) => onWorkflowScopeChange((value as HistoryWorkflowScope) || 'selected')}
              />
              <Select
                label="Project scope"
                value={historyProjectScope}
                data={[
                  { value: 'active', label: 'Active project' },
                  { value: 'all', label: 'All projects' }
                ]}
                allowDeselect={false}
                onChange={(value) => onProjectScopeChange((value as HistoryProjectScope) || 'active')}
              />
            </SimpleGrid>
            <Group gap={6} wrap="wrap">
              <Badge variant="outline" color="gray">
                Showing {runHistory.length}
              </Badge>
              <Badge variant="outline" color="gray">
                Fetched {runHistoryRaw.length}
              </Badge>
              {filteredOutRunCount > 0 && (
                <Badge variant="light" color="yellow">
                  Filtered out {filteredOutRunCount}
                </Badge>
              )}
              <Badge variant="outline" color="gray">
                Projects in data {runHistoryProjectIds.length}
              </Badge>
            </Group>
            {historyProjectScope === 'active' && !activeProjectId && (
              <Text size="xs" c="yellow">
                Select a project to scope run history.
              </Text>
            )}
          </Stack>
        </Card>
        <ScrollArea h={360}>
          <Stack gap="sm">
            <Card withBorder radius="md" padding="sm">
              <Stack gap="xs">
                <Group justify="space-between" align="center">
                  <Text size="sm" fw={600}>
                    Cost settings
                  </Text>
                  <Text size="xs" c="dimmed">
                    USD per 1M tokens
                  </Text>
                </Group>
                <SimpleGrid cols={{ base: 1, sm: 2 }} spacing="sm">
                  <NumberInput
                    label="Input tokens rate"
                    value={historyInputRateUsdPer1M}
                    onChange={(value) => onInputRateChange(asUsdRate(value))}
                    min={0}
                    decimalScale={4}
                    fixedDecimalScale={false}
                    allowNegative={false}
                  />
                  <NumberInput
                    label="Output tokens rate"
                    value={historyOutputRateUsdPer1M}
                    onChange={(value) => onOutputRateChange(asUsdRate(value))}
                    min={0}
                    decimalScale={4}
                    fixedDecimalScale={false}
                    allowNegative={false}
                  />
                </SimpleGrid>
                {!hasCostRates && (
                  <Text size="xs" c="dimmed">
                    Set token rates to see money estimates.
                  </Text>
                )}
              </Stack>
            </Card>

            <SimpleGrid cols={{ base: 2, sm: 4 }} spacing="sm">
              <Card withBorder radius="sm" padding="sm">
                <Text size="xs" c="dimmed">
                  Runs
                </Text>
                <Text fw={700}>{historySummary.runCount}</Text>
              </Card>
              <Card withBorder radius="sm" padding="sm">
                <Text size="xs" c="dimmed">
                  Total tokens
                </Text>
                <Text fw={700}>{Math.round(historySummary.totalTokens).toLocaleString()}</Text>
              </Card>
              <Card withBorder radius="sm" padding="sm">
                <Text size="xs" c="dimmed">
                  Avg tokens / run
                </Text>
                <Text fw={700}>{Math.round(historySummary.avgTokensPerRun).toLocaleString()}</Text>
              </Card>
              <Card withBorder radius="sm" padding="sm">
                <Text size="xs" c="dimmed">
                  Total est. cost
                </Text>
                <Text fw={700}>{formatUsd(historySummary.totalCostUsd)}</Text>
              </Card>
            </SimpleGrid>

            <Card withBorder radius="md" padding="sm">
              <Stack gap="xs">
                <Group justify="space-between" align="center">
                  <Text size="sm" fw={600}>
                    Daily totals
                  </Text>
                  <Text size="xs" c="dimmed">
                    Avg cost/run {formatUsd(historySummary.avgCostPerRun)}
                  </Text>
                </Group>
                {historySummary.days.length === 0 ? (
                  <Text size="xs" c="dimmed">
                    No day-level data yet.
                  </Text>
                ) : (
                  historySummary.days.map((day, index) => (
                    <Stack key={day.day} gap={6}>
                      {index > 0 && <Divider />}
                      <Group justify="space-between" align="flex-start">
                        <Stack gap={2}>
                          <Text size="sm" fw={600}>
                            {day.day}
                          </Text>
                          <Text size="xs" c="dimmed">
                            {day.runs} run{day.runs === 1 ? '' : 's'}
                          </Text>
                        </Stack>
                        <Group gap={6} wrap="wrap" justify="flex-end">
                          <Badge variant="outline" color="gray">
                            Tokens {Math.round(day.totalTokens).toLocaleString()}
                          </Badge>
                          <Badge variant="outline" color="gray">
                            Avg {Math.round(day.avgTokens).toLocaleString()} / run
                          </Badge>
                          <Badge variant="light" color="indigo">
                            {formatUsd(day.totalCostUsd)}
                          </Badge>
                        </Group>
                      </Group>
                    </Stack>
                  ))
                )}
              </Stack>
            </Card>

            {runHistoryLoading ? (
              <Text size="sm" c="dimmed">
                Loading run history...
              </Text>
            ) : runHistory.length === 0 ? (
              <Text size="sm" c="dimmed">
                No executions yet.
              </Text>
            ) : (
              runHistory.map((run) => {
                const failureReason = runFailureReason(run);
                const tokenSummary = runTokenSummary(run);
                const runEstimatedCost = estimateCostUsd(
                  tokenSummary,
                  historyInputRateUsdPer1M,
                  historyOutputRateUsdPer1M
                );
                const nodeStats = runNodeStats(run);
                const documentPreviews = summarizeRunDocuments(run.inputs);
                const isExpanded = runHistoryExpandedId === run.run_id;
                return (
                  <Card key={run.run_id} withBorder radius="md">
                    <Group justify="space-between" align="flex-start">
                      <Stack gap={2}>
                        <Text fw={600}>{run.run_id}</Text>
                        <Text size="xs" c="dimmed">
                          Workflow {run.workflow_id}
                        </Text>
                        <Text size="xs" c="dimmed">
                          Project {run.project_id || '—'}
                        </Text>
                        <Text size="xs" c="dimmed">
                          Version {run.version_id}
                        </Text>
                      </Stack>
                      <Stack gap={4} align="flex-end">
                        <Badge color={runStatusBadgeColor(run.status)} variant="light">
                          {run.status}
                        </Badge>
                        {run.mode && (
                          <Badge color="gray" variant="outline">
                            {run.mode.toUpperCase()}
                          </Badge>
                        )}
                        <Button
                          size="xs"
                          variant="subtle"
                          onClick={() => onToggleExpanded(run.run_id)}
                        >
                          {isExpanded ? 'Hide details' : 'Show details'}
                        </Button>
                        <Button
                          size="xs"
                          variant="light"
                          onClick={() => onOpenRunDebug(run)}
                          data-testid={`open-run-debug-${run.run_id}`}
                        >
                          Open Run Debug
                        </Button>
                      </Stack>
                    </Group>
                    <Group gap={6} mt="xs" wrap="wrap">
                      <Badge variant="outline" color="gray">
                        Nodes {nodeStats.total}
                      </Badge>
                      {nodeStats.completed > 0 && (
                        <Badge variant="light" color="teal">
                          Resolved {nodeStats.completed}
                        </Badge>
                      )}
                      {nodeStats.failed > 0 && (
                        <Badge variant="light" color="red">
                          Failed {nodeStats.failed}
                        </Badge>
                      )}
                      {nodeStats.waiting > 0 && (
                        <Badge variant="light" color="yellow">
                          Waiting {nodeStats.waiting}
                        </Badge>
                      )}
                      {nodeStats.inProgress > 0 && (
                        <Badge variant="light" color="blue">
                          Running {nodeStats.inProgress}
                        </Badge>
                      )}
                      <Badge variant="light" color="indigo">
                        Tokens {Math.round(tokenSummary.totalTokens).toLocaleString()}
                      </Badge>
                      <Badge variant="light" color="green">
                        {formatUsd(runEstimatedCost)}
                      </Badge>
                    </Group>
                    {(run.created_at || run.updated_at) && (
                      <Stack gap={2} mt="xs">
                        {run.created_at && (
                          <Text size="xs" c="dimmed">
                            Started {formatTimestamp(run.created_at)}
                          </Text>
                        )}
                        {run.updated_at && (
                          <Text size="xs" c="dimmed">
                            Updated {formatTimestamp(run.updated_at)}
                          </Text>
                        )}
                      </Stack>
                    )}
                    {failureReason && (
                      <Text size="xs" c="red" mt="xs">
                        Error: {failureReason}
                      </Text>
                    )}
                    {isExpanded && (
                      <Stack gap="sm" mt="sm">
                        <Divider />
                        <SimpleGrid cols={{ base: 1, sm: 2 }} spacing="sm">
                          <JsonPreviewCard title="Inputs sent" value={run.inputs || {}} emptyLabel="No inputs" />
                          <JsonPreviewCard title="Run outputs" value={run.outputs} emptyLabel="No outputs" />
                        </SimpleGrid>

                        <JsonPreviewCard title="Metadata" value={run.metadata} emptyLabel="No metadata" maxHeight={160} />

                        <Stack gap="xs">
                          <Text size="xs" fw={600}>
                            Documents preview
                          </Text>
                          {documentPreviews.length === 0 ? (
                            <Text size="xs" c="dimmed">
                              No documents in run inputs.
                            </Text>
                          ) : (
                            documentPreviews.map((doc) => (
                              <Card
                                key={`${run.run_id}-${doc.docId}-${doc.filename}`}
                                withBorder
                                radius="sm"
                                padding="sm"
                              >
                                <Stack gap={6}>
                                  <Group justify="space-between" align="flex-start">
                                    <Stack gap={2}>
                                      <Text size="sm" fw={600}>
                                        {doc.filename}
                                      </Text>
                                      <Text size="xs" c="dimmed">
                                        {doc.docId}
                                      </Text>
                                    </Stack>
                                    <Badge variant="light" color="gray">
                                      {doc.docType}
                                    </Badge>
                                  </Group>
                                  <Group gap={6} wrap="wrap">
                                    <Badge variant="outline" color="gray">
                                      Pages {doc.pages}
                                    </Badge>
                                    <Badge variant="outline" color="gray">
                                      Text chars {doc.textChars.toLocaleString()}
                                    </Badge>
                                    {doc.imageBase64Chars > 0 && (
                                      <Badge variant="light" color="orange">
                                        image_base64 {doc.imageBase64Chars.toLocaleString()} chars
                                      </Badge>
                                    )}
                                  </Group>
                                  {doc.textSample ? (
                                    <Text size="xs" c="dimmed" style={{ whiteSpace: 'pre-wrap' }}>
                                      {doc.textSample}
                                    </Text>
                                  ) : (
                                    <Text size="xs" c="dimmed">
                                      No text/ocr/markdown in this document payload.
                                    </Text>
                                  )}
                                </Stack>
                              </Card>
                            ))
                          )}
                        </Stack>

                        <Group gap={8} wrap="wrap">
                          <Badge variant="outline" color="gray">
                            Input tokens {Math.round(tokenSummary.inputTokens).toLocaleString()}
                          </Badge>
                          <Badge variant="outline" color="gray">
                            Output tokens {Math.round(tokenSummary.outputTokens).toLocaleString()}
                          </Badge>
                          <Badge variant="light" color="indigo">
                            Total tokens {Math.round(tokenSummary.totalTokens).toLocaleString()}
                          </Badge>
                          <Badge variant="light" color="green">
                            Est. cost {formatUsd(runEstimatedCost)}
                          </Badge>
                        </Group>

                        <Stack gap="xs">
                          <Text size="xs" fw={600}>
                            Node execution log
                          </Text>
                          {(run.node_runs || []).length === 0 ? (
                            <Text size="xs" c="dimmed">
                              No node details for this run.
                            </Text>
                          ) : (
                            (run.node_runs || []).map((nodeRun) => {
                              const nodeTokens = nodeTokenSummary(nodeRun);
                              const nodeCost = estimateCostUsd(
                                nodeTokens,
                                historyInputRateUsdPer1M,
                                historyOutputRateUsdPer1M
                              );
                              return (
                                <Card
                                  key={`${run.run_id}-${nodeRun.node_id}`}
                                  withBorder
                                  radius="sm"
                                  padding="sm"
                                >
                                  <Stack gap="xs">
                                    <Group justify="space-between" align="flex-start">
                                      <Stack gap={2}>
                                        <Text size="sm" fw={600}>
                                          {nodeRun.node_id}
                                        </Text>
                                        <Group gap={6} wrap="wrap">
                                          {typeof nodeRun.attempt === 'number' && (
                                            <Badge variant="outline" color="gray">
                                              Attempt {nodeRun.attempt}
                                            </Badge>
                                          )}
                                          {nodeTokens && (
                                            <Badge variant="outline" color="indigo">
                                              Tokens {nodeTokens.totalTokens}
                                            </Badge>
                                          )}
                                          {nodeTokens && (
                                            <Badge variant="outline" color="green">
                                              {formatUsd(nodeCost)}
                                            </Badge>
                                          )}
                                          {nodeRun.trace_id && (
                                            <Text size="xs" c="dimmed" ff="monospace">
                                              Trace {nodeRun.trace_id}
                                            </Text>
                                          )}
                                        </Group>
                                      </Stack>
                                      <Badge color={nodeStatusBadgeColor(nodeRun.status)} variant="light">
                                        {nodeRun.status}
                                      </Badge>
                                    </Group>
                                    {nodeRun.last_error && (
                                      <Text size="xs" c="red" mt="xs">
                                        {nodeRun.last_error}
                                      </Text>
                                    )}
                                    {(hasContent(nodeRun.output) || hasContent(nodeRun.usage)) && (
                                      <SimpleGrid cols={{ base: 1, sm: 2 }} spacing="sm">
                                        {hasContent(nodeRun.output) && (
                                          <JsonPreviewCard title="Output" value={nodeRun.output} maxHeight={160} />
                                        )}
                                        {hasContent(nodeRun.usage) && (
                                          <JsonPreviewCard title="Usage" value={nodeRun.usage} maxHeight={160} />
                                        )}
                                      </SimpleGrid>
                                    )}
                                  </Stack>
                                </Card>
                              );
                            })
                          )}
                        </Stack>
                      </Stack>
                    )}
                  </Card>
                );
              })
            )}
          </Stack>
        </ScrollArea>
      </Stack>
    </Modal>
  );
}
