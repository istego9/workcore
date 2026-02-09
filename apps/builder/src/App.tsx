import {
  Anchor,
  AppShell,
  ActionIcon,
  Badge,
  Box,
  Button,
  Card,
  CopyButton,
  Drawer,
  Divider,
  Group,
  Menu,
  Modal,
  NumberInput,
  Popover,
  ScrollArea,
  Select,
  SimpleGrid,
  Stack,
  Switch,
  Tabs,
  Text,
  Textarea,
  TextInput,
  Title
} from '@mantine/core';
import { useDisclosure } from '@mantine/hooks';
import { useEffect, useMemo, useRef, useState } from 'react';
import type { ChangeEvent as ReactChangeEvent, PointerEvent as ReactPointerEvent } from 'react';
import {
  API_BASE,
  createWorkflow,
  getWorkflow,
  listRuns,
  listWorkflows,
  publishWorkflow,
  rollbackWorkflow,
  startRun,
  deleteWorkflow,
  updateDraft,
  updateWorkflowMeta
} from './api';
import type { RunRecord } from './api';
import { buildIntegrationKitLinks } from './integration-kit';
import {
  DEFAULT_DRAFT,
  NODE_DIMENSIONS,
  NODE_PALETTE,
  autoLayoutNodes,
  buildDraft,
  createEdgeId,
  createNode,
  defaultNodeConfig,
  parseDraft,
  validateImportedDraft,
  validateGraph
} from './builder/graph';
import type {
  BuilderEdge,
  BuilderNode,
  NodeType,
  ValidationIssue,
  WorkflowExport,
  WorkflowSummary
} from './builder/types';
import './styles.css';

const statusTone = {
  idle: 'gray',
  ok: 'teal',
  warn: 'yellow',
  error: 'red',
  working: 'blue'
} as const;

const OUTPUT_FORMAT_OPTIONS = [
  { value: 'text', label: 'Text' },
  { value: 'json', label: 'JSON' },
  { value: 'widget', label: 'Widget' }
];

const WIDGET_TEMPLATES = [{ value: 'ux_presentations', label: 'UX Presentations' }];
const inferRootHost = (hostname: string) => {
  if (hostname === 'localhost' || hostname === '127.0.0.1' || hostname === '::1') {
    return 'localhost';
  }
  if (hostname.startsWith('builder.')) return hostname.slice('builder.'.length);
  if (hostname.startsWith('api.')) return hostname.slice('api.'.length);
  if (hostname.startsWith('chatkit.')) return hostname.slice('chatkit.'.length);
  return hostname;
};

const inferChatkitApiUrl = () => {
  if (typeof window === 'undefined') {
    return 'http://chatkit.localhost/chatkit';
  }
  const { protocol, hostname, port } = window.location;
  const rootHost = inferRootHost(hostname);
  const chatkitHost = rootHost === 'localhost' ? 'chatkit.localhost' : `chatkit.${rootHost}`;
  return `${protocol}//${chatkitHost}${port ? `:${port}` : ''}/chatkit`;
};

const appOrigin = typeof window === 'undefined' ? 'http://localhost' : window.location.origin;
const CHATKIT_PAGE = import.meta.env.VITE_CHATKIT_PAGE || `${appOrigin}/chatkit.html`;
const CHATKIT_API_URL = import.meta.env.VITE_CHATKIT_API_URL || inferChatkitApiUrl();
const CHATKIT_DOMAIN_KEY = import.meta.env.VITE_CHATKIT_DOMAIN_KEY || '';
const CHATKIT_AUTH_TOKEN = import.meta.env.VITE_CHATKIT_AUTH_TOKEN || '';
const EXPORT_SCHEMA_VERSION = 'workflow_export_v1';

type StatusState = { tone: keyof typeof statusTone; label: string; detail?: string };

type JsonEditorProps = {
  label: string;
  value: any;
  onApply: (value: any) => void;
  description?: string;
};

type VariableOption = {
  key: string;
  label: string;
  value: string;
  group: string;
  type?: string;
};

type SchemaPathSegment = { key: string; isArray?: boolean };
type SchemaPath = { segments: SchemaPathSegment[]; type?: string };

const toNumber = (value: string | number | null | undefined, fallback: number | null) =>
  typeof value === 'number' ? value : fallback;

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
  if (status === 'SUCCESS' || status === 'COMPLETED') return 'teal';
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

const TOKENS_IN_MILLION = 1_000_000;

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

const runTokenSummary = (run: RunRecord) => {
  const totals = (run.node_runs || []).reduce<TokenSummary>(
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

  if (!totals.totalTokens && !totals.inputTokens && !totals.outputTokens) {
    return null;
  }
  return totals;
};

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

const DEFAULT_INPUT_RATE_USD_PER_1M = asUsdRate(import.meta.env.VITE_USAGE_COST_INPUT_USD_PER_1M);
const DEFAULT_OUTPUT_RATE_USD_PER_1M = asUsdRate(import.meta.env.VITE_USAGE_COST_OUTPUT_USD_PER_1M);

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
    const tokens = runTokenSummary(run) || { inputTokens: 0, outputTokens: 0, totalTokens: 0 };
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

function JsonEditor({ label, value, onApply, description }: JsonEditorProps) {
  const [draft, setDraft] = useState(() => JSON.stringify(value ?? {}, null, 2));
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setDraft(JSON.stringify(value ?? {}, null, 2));
  }, [value]);

  const handleApply = () => {
    try {
      const parsed = JSON.parse(draft || '{}');
      setError(null);
      onApply(parsed);
    } catch (err: any) {
      setError(err?.message || 'Invalid JSON');
    }
  };

  return (
    <Stack gap="xs">
      <Group justify="space-between" align="center">
        <Text size="sm" fw={600}>
          {label}
        </Text>
        <Group gap="xs">
          <CopyButton value={draft}>
            {({ copied, copy }) => (
              <Button size="xs" variant="light" onClick={copy}>
                {copied ? 'Copied' : 'Copy JSON'}
              </Button>
            )}
          </CopyButton>
          <Button size="xs" variant="light" onClick={handleApply}>
            Apply
          </Button>
        </Group>
      </Group>
      {description && (
        <Text size="xs" c="dimmed">
          {description}
        </Text>
      )}
      <Textarea
        autosize
        minRows={3}
        value={draft}
        onChange={(event) => setDraft(event.currentTarget.value)}
      />
      {error && (
        <Text size="xs" c="red">
          {error}
        </Text>
      )}
    </Stack>
  );
}

const escapeHtml = (value: string) =>
  value
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#039;');

const renderTemplateHighlight = (value: string) => {
  const tokenRegex = /\{\{[\s\S]+?\}\}/g;
  let result = '';
  let lastIndex = 0;
  for (const match of value.matchAll(tokenRegex)) {
    const index = match.index ?? 0;
    result += escapeHtml(value.slice(lastIndex, index));
    result += `<span class="template-token">${escapeHtml(match[0])}</span>`;
    lastIndex = index + match[0].length;
  }
  result += escapeHtml(value.slice(lastIndex));
  return result;
};

const collectSchemaPaths = (schema: any, prefix: SchemaPathSegment[] = []): SchemaPath[] => {
  if (!schema || typeof schema !== 'object') return [];
  const results: SchemaPath[] = [];
  const schemaType = schema.type;
  const properties = schema.properties;
  const isObject = schemaType === 'object' || (!schemaType && properties);

  if (isObject && properties && typeof properties === 'object') {
    Object.entries(properties).forEach(([key, value]) => {
      const childSchema: any = value || {};
      const isArray = childSchema.type === 'array';
      const segment = { key, isArray };
      const next = [...prefix, segment];
      results.push({ segments: next, type: childSchema.type });

      if (childSchema.type === 'object') {
        results.push(...collectSchemaPaths(childSchema, next));
      } else if (childSchema.type === 'array' && childSchema.items) {
        const itemsSchema = childSchema.items;
        if (itemsSchema && itemsSchema.type === 'object') {
          results.push(...collectSchemaPaths(itemsSchema, next));
        }
      }
    });
  }

  return results;
};

const pathLabel = (segments: SchemaPathSegment[]) =>
  segments.map((segment) => (segment.isArray ? `${segment.key}[]` : segment.key)).join('.');

const pathExpression = (root: string, segments: SchemaPathSegment[]) => {
  let expr = root;
  segments.forEach((segment) => {
    expr += `['${segment.key}']`;
    if (segment.isArray) {
      expr += `[0]`;
    }
  });
  return expr;
};

type TemplateTextareaProps = {
  label: string;
  value: string;
  onChange: (next: string) => void;
  placeholder?: string;
  variables: VariableOption[];
  minRows?: number;
  testId?: string;
};

function TemplateTextarea({
  label,
  value,
  onChange,
  placeholder,
  variables,
  minRows = 3,
  testId
}: TemplateTextareaProps) {
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);
  const highlightRef = useRef<HTMLDivElement | null>(null);
  const [opened, setOpened] = useState(false);
  const [search, setSearch] = useState('');

  const filtered = useMemo(() => {
    const query = search.trim().toLowerCase();
    if (!query) return variables;
    return variables.filter(
      (item) =>
        item.label.toLowerCase().includes(query) ||
        item.value.toLowerCase().includes(query) ||
        item.group.toLowerCase().includes(query)
    );
  }, [variables, search]);

  const grouped = useMemo(() => {
    const groups: Record<string, VariableOption[]> = {};
    filtered.forEach((item) => {
      groups[item.group] = groups[item.group] || [];
      groups[item.group].push(item);
    });
    return Object.entries(groups);
  }, [filtered]);

  const insertVariable = (expression: string) => {
    const token = `{{${expression}}}`;
    const el = textareaRef.current;
    if (!el) {
      onChange(`${value}${token}`);
      return;
    }
    const start = el.selectionStart ?? value.length;
    const end = el.selectionEnd ?? value.length;
    const next = `${value.slice(0, start)}${token}${value.slice(end)}`;
    onChange(next);
    requestAnimationFrame(() => {
      el.focus();
      const cursor = start + token.length;
      el.selectionStart = cursor;
      el.selectionEnd = cursor;
    });
  };

  const handleScroll = () => {
    if (!textareaRef.current || !highlightRef.current) return;
    highlightRef.current.scrollTop = textareaRef.current.scrollTop;
    highlightRef.current.scrollLeft = textareaRef.current.scrollLeft;
  };

  return (
    <Stack gap={6}>
      <Group justify="space-between" align="center">
        <Text size="sm" fw={600}>
          {label}
        </Text>
        <Popover opened={opened} onChange={setOpened} position="bottom-end" withArrow shadow="md">
          <Popover.Target onClick={() => setOpened((prev) => !prev)}>
            <ActionIcon
              variant="light"
              aria-label="Insert variable"
              data-testid={testId ? `${testId}-picker` : undefined}
            >
              +
            </ActionIcon>
          </Popover.Target>
          <Popover.Dropdown className="variable-picker">
            <Stack gap="xs">
              <TextInput
                placeholder="Search variables"
                value={search}
                onChange={(event) => setSearch(event.currentTarget.value)}
              />
              <ScrollArea h={220}>
                <Stack gap="sm">
                  {grouped.length === 0 && (
                    <Text size="sm" c="dimmed">
                      No variables found.
                    </Text>
                  )}
                  {grouped.map(([group, items]) => (
                    <Stack key={group} gap={6}>
                      <Text size="xs" tt="uppercase" fw={600} c="dimmed">
                        {group}
                      </Text>
                      {items.map((item) => (
                        <Group
                          key={item.key}
                          justify="space-between"
                          wrap="nowrap"
                          className="variable-item"
                          data-var-value={item.value}
                          onClick={() => {
                            insertVariable(item.value);
                            setOpened(false);
                          }}
                        >
                          <Group gap="xs" wrap="nowrap">
                            <Badge variant="light" color="blue">
                              {item.label}
                            </Badge>
                            <Text size="xs" c="dimmed">
                              {item.value}
                            </Text>
                          </Group>
                          {item.type && (
                            <Badge variant="outline" color="gray">
                              {item.type.toUpperCase()}
                            </Badge>
                          )}
                        </Group>
                      ))}
                    </Stack>
                  ))}
                </Stack>
              </ScrollArea>
            </Stack>
          </Popover.Dropdown>
        </Popover>
      </Group>
      <div className="template-editor">
        <div
          ref={highlightRef}
          className="template-highlight"
          dangerouslySetInnerHTML={{ __html: renderTemplateHighlight(value || '') }}
          data-testid={testId ? `${testId}-highlight` : undefined}
        />
        <textarea
          ref={textareaRef}
          className="template-input"
          rows={minRows}
          value={value}
          onChange={(event) => onChange(event.currentTarget.value)}
          onScroll={handleScroll}
          placeholder={placeholder}
          data-testid={testId ? `${testId}-input` : undefined}
        />
      </div>
    </Stack>
  );
}

export default function App() {
  const [listOpen, { open: openList, close: closeList }] = useDisclosure(false);
  const [integrationOpen, { open: openIntegration, close: closeIntegration }] = useDisclosure(false);
  const [runHistoryOpen, { open: openRunHistory, close: closeRunHistory }] = useDisclosure(false);
  const [workflowId, setWorkflowId] = useState('');
  const [workflowInput, setWorkflowInput] = useState('');
  const [workflowName, setWorkflowName] = useState('');
  const [workflowDescription, setWorkflowDescription] = useState('');
  const [activeVersionId, setActiveVersionId] = useState<string | null>(null);
  const [autoSave, setAutoSave] = useState(true);
  const [dirty, setDirty] = useState(false);
  const [metaDirty, setMetaDirty] = useState(false);
  const [creatingWorkflow, setCreatingWorkflow] = useState(false);
  const importInputRef = useRef<HTMLInputElement | null>(null);
  const [status, setStatus] = useState<StatusState>({ tone: 'idle', label: 'Idle' });
  const [chatOpen, setChatOpen] = useState(false);
  const [moreMenuOpen, setMoreMenuOpen] = useState(false);
  const [autoCreatedWorkflowId, setAutoCreatedWorkflowId] = useState<string | null>(null);
  const [runMode, setRunMode] = useState<'live' | 'test'>('live');
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [connectingFrom, setConnectingFrom] = useState<string | null>(null);
  const [connectingViaDrag, setConnectingViaDrag] = useState(false);
  const [cursor, setCursor] = useState<{ x: number; y: number } | null>(null);
  const [scale, setScale] = useState(1);
  const [offset, setOffset] = useState({ x: 0, y: 0 });
  const [draggingNodeId, setDraggingNodeId] = useState<string | null>(null);
  const [dragOffset, setDragOffset] = useState({ x: 0, y: 0 });
  const [panning, setPanning] = useState(false);
  const [panStart, setPanStart] = useState({ x: 0, y: 0, ox: 0, oy: 0 });
  const [workflowList, setWorkflowList] = useState<WorkflowSummary[]>([]);
  const [workflowQuery, setWorkflowQuery] = useState('');
  const [workflowListLoading, setWorkflowListLoading] = useState(false);
  const [runHistory, setRunHistory] = useState<RunRecord[]>([]);
  const [runHistoryLoading, setRunHistoryLoading] = useState(false);
  const [runHistoryExpandedId, setRunHistoryExpandedId] = useState<string | null>(null);
  const [historyInputRateUsdPer1M, setHistoryInputRateUsdPer1M] = useState(
    DEFAULT_INPUT_RATE_USD_PER_1M
  );
  const [historyOutputRateUsdPer1M, setHistoryOutputRateUsdPer1M] = useState(
    DEFAULT_OUTPUT_RATE_USD_PER_1M
  );

  const isTestEnv = typeof navigator !== 'undefined' && navigator.webdriver;
  const appOrigin = typeof window === 'undefined' ? 'http://localhost' : window.location.origin;

  const canvasRef = useRef<HTMLDivElement | null>(null);
  const autoCreatedRef = useRef(false);

  const initialDraft = useMemo(() => parseDraft(DEFAULT_DRAFT), []);
  const [nodes, setNodes] = useState<BuilderNode[]>(initialDraft.nodes);
  const [edges, setEdges] = useState<BuilderEdge[]>(initialDraft.edges);
  const [variablesSchema, setVariablesSchema] = useState<Record<string, any>>(
    initialDraft.variablesSchema
  );

  const selectedNode = useMemo(
    () => nodes.find((node) => node.id === selectedNodeId) || null,
    [nodes, selectedNodeId]
  );

  const issues = useMemo<ValidationIssue[]>(() => validateGraph(nodes, edges), [nodes, edges]);
  const integrationLinks = useMemo(() => buildIntegrationKitLinks(API_BASE, appOrigin), [appOrigin]);
  const filteredWorkflows = useMemo(() => {
    const query = workflowQuery.trim().toLowerCase();
    if (!query) return workflowList;
    return workflowList.filter((item) => {
      const name = item.name?.toLowerCase() || '';
      const description = item.description?.toLowerCase() || '';
      const id = item.workflow_id?.toLowerCase() || '';
    return name.includes(query) || description.includes(query) || id.includes(query);
  });

  }, [workflowList, workflowQuery]);

  const historySummary = useMemo(
    () => summarizeHistory(runHistory, historyInputRateUsdPer1M, historyOutputRateUsdPer1M),
    [runHistory, historyInputRateUsdPer1M, historyOutputRateUsdPer1M]
  );
  const hasCostRates = historyInputRateUsdPer1M > 0 || historyOutputRateUsdPer1M > 0;

  const variableOptions = useMemo<VariableOption[]>(() => {
    const options: VariableOption[] = [];
    const schemaProps = variablesSchema?.properties || {};
    const schemaKeys = Object.keys(schemaProps);
    const schemaPaths = collectSchemaPaths(variablesSchema);

    if (schemaKeys.length > 0 && schemaPaths.length > 0) {
      schemaPaths.forEach((item) => {
        const label = pathLabel(item.segments);
        options.push({
          key: `input-${label}`,
          label,
          value: pathExpression('inputs', item.segments),
          group: 'Workflow inputs',
          type: item.type
        });
        options.push({
          key: `state-${label}`,
          label,
          value: pathExpression('state', item.segments),
          group: 'State',
          type: item.type
        });
      });
    } else if (schemaKeys.length > 0) {
      schemaKeys.forEach((key) => {
        const type = schemaProps[key]?.type;
        options.push({
          key: `input-${key}`,
          label: key,
          value: `inputs['${key}']`,
          group: 'Workflow inputs',
          type
        });
        options.push({
          key: `state-${key}`,
          label: key,
          value: `state['${key}']`,
          group: 'State',
          type
        });
      });
    } else {
      options.push({
        key: 'inputs-root',
        label: 'inputs',
        value: 'inputs',
        group: 'Workflow inputs'
      });
      options.push({
        key: 'state-root',
        label: 'state',
        value: 'state',
        group: 'State'
      });
    }

    nodes.forEach((node) => {
      options.push({
        key: `node-${node.id}`,
        label: node.id,
        value: `node_outputs['${node.id}']`,
        group: 'Node outputs'
      });
      const outputSchema = node.config?.output_schema;
      const outputPaths = collectSchemaPaths(outputSchema);
      if (outputPaths.length > 0) {
        outputPaths.forEach((item) => {
          const label = `${node.id}.${pathLabel(item.segments)}`;
          options.push({
            key: `node-${node.id}-${label}`,
            label,
            value: pathExpression(`node_outputs['${node.id}']`, item.segments),
            group: 'Node outputs',
            type: item.type
          });
        });
      }
    });

    return options;
  }, [nodes, variablesSchema]);

  useEffect(() => {
    if (!workflowId || !dirty || !autoSave) return;
    const handle = window.setTimeout(() => {
      void handleSaveDraft();
    }, 900);
    return () => window.clearTimeout(handle);
  }, [workflowId, dirty, autoSave, nodes, edges, variablesSchema]);

  useEffect(() => {
    if (!workflowId || !metaDirty) return;
    if (!workflowName.trim()) return;
    const handle = window.setTimeout(() => {
      void handleUpdateWorkflowMeta();
    }, 700);
    return () => window.clearTimeout(handle);
  }, [workflowId, metaDirty, workflowName, workflowDescription]);

  useEffect(() => {
    if (workflowId || autoCreatedRef.current) return;
    autoCreatedRef.current = true;
    void createNewWorkflow(undefined, { auto: true });
  }, [workflowId]);

  useEffect(() => {
    if (!isTestEnv || !autoCreatedWorkflowId) return;
    if (!workflowId || workflowId === autoCreatedWorkflowId) return;
    void deleteWorkflow(autoCreatedWorkflowId);
    setAutoCreatedWorkflowId(null);
  }, [workflowId, autoCreatedWorkflowId, isTestEnv]);

  useEffect(() => {
    return () => {
      if (isTestEnv && autoCreatedWorkflowId) {
        void deleteWorkflow(autoCreatedWorkflowId);
      }
    };
  }, [autoCreatedWorkflowId, isTestEnv]);

  useEffect(() => {
    if (!listOpen) return;
    void fetchWorkflows();
  }, [listOpen]);

  useEffect(() => {
    void fetchWorkflows();
  }, []);

  const markDirty = () => {
    setDirty(true);
  };

  const handleAddNode = (type: NodeType) => {
    if (type === 'start' && nodes.some((node) => node.type === 'start')) {
      setStatus({ tone: 'warn', label: 'Start already exists' });
      return;
    }
    if (type === 'end' && nodes.some((node) => node.type === 'end')) {
      setStatus({ tone: 'warn', label: 'End already exists' });
      return;
    }
    const rect = canvasRef.current?.getBoundingClientRect();
    const centerX = rect ? (rect.width / 2 - offset.x) / scale : 240;
    const centerY = rect ? (rect.height / 2 - offset.y) / scale : 160;
    const newNode = createNode(type, {
      x: centerX - NODE_DIMENSIONS.width / 2 + Math.random() * 30,
      y: centerY - NODE_DIMENSIONS.height / 2 + Math.random() * 30
    });
    setNodes((prev) => [...prev, newNode]);
    setSelectedNodeId(newNode.id);
    markDirty();
  };

  const updateNodeConfig = (nodeId: string, updates: Record<string, any>) => {
    setNodes((prev) =>
      prev.map((node) =>
        node.id === nodeId ? { ...node, config: { ...node.config, ...updates } } : node
      )
    );
    markDirty();
  };

  const updateNode = (nodeId: string, updates: Partial<BuilderNode>) => {
    setNodes((prev) => prev.map((node) => (node.id === nodeId ? { ...node, ...updates } : node)));
    markDirty();
  };

  const renameNode = (nodeId: string, nextId: string) => {
    if (!nextId.trim()) return;
    if (nodes.some((node) => node.id === nextId && node.id !== nodeId)) {
      setStatus({ tone: 'warn', label: 'Node ID already exists' });
      return;
    }
    setNodes((prev) => prev.map((node) => (node.id === nodeId ? { ...node, id: nextId } : node)));
    setEdges((prev) =>
      prev.map((edge) => {
        const source = edge.source === nodeId ? nextId : edge.source;
        const target = edge.target === nodeId ? nextId : edge.target;
        return { ...edge, source, target, id: createEdgeId(source, target) };
      })
    );
    if (selectedNodeId === nodeId) {
      setSelectedNodeId(nextId);
    }
    markDirty();
  };

  const handleRemoveNode = (nodeId: string) => {
    const node = nodes.find((item) => item.id === nodeId);
    if (!node) return;
    if (node.type === 'start' || node.type === 'end') {
      setStatus({ tone: 'warn', label: 'Start/End cannot be removed' });
      return;
    }
    setNodes((prev) => prev.filter((item) => item.id !== nodeId));
    setEdges((prev) => prev.filter((edge) => edge.source !== nodeId && edge.target !== nodeId));
    setSelectedNodeId(null);
    markDirty();
  };

  const handleAddEdge = (source: string, target: string) => {
    if (source === target) return;
    const edgeId = createEdgeId(source, target);
    if (edges.some((edge) => edge.id === edgeId)) return;
    setEdges((prev) => [...prev, { id: edgeId, source, target }]);
    markDirty();
  };

  const handleRemoveEdge = (edgeId: string) => {
    setEdges((prev) => prev.filter((edge) => edge.id !== edgeId));
    markDirty();
  };

  const handleAutoLayout = () => {
    setNodes((prev) => autoLayoutNodes(prev, edges));
    markDirty();
    setStatus({ tone: 'ok', label: 'Auto layout applied' });
  };

  const resetDraftToDefault = () => {
    const parsed = parseDraft(DEFAULT_DRAFT);
    setNodes(parsed.nodes);
    setEdges(parsed.edges);
    setVariablesSchema(parsed.variablesSchema);
    setSelectedNodeId(null);
    setDirty(false);
  };

  const buildExportPayload = (): WorkflowExport => {
    return {
      schema_version: EXPORT_SCHEMA_VERSION,
      exported_at: new Date().toISOString(),
      source: {
        workflow_id: workflowId,
        active_version_id: activeVersionId
      },
      workflow: {
        name: workflowName || workflowId || 'Untitled workflow',
        description: workflowDescription || ''
      },
      draft: buildDraft(nodes, edges, variablesSchema)
    };
  };

  const sanitizeFilename = (value: string) => {
    const safe = value.trim().replace(/[^a-zA-Z0-9_-]+/g, '_');
    return safe || 'workflow';
  };

  const handleExportWorkflow = () => {
    if (!workflowId) {
      setStatus({ tone: 'warn', label: 'Select a workflow first' });
      return;
    }
    const payload = buildExportPayload();
    const filenameBase = sanitizeFilename(payload.workflow.name || workflowId);
    const blob = new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = `${filenameBase}.json`;
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
    setStatus({ tone: 'ok', label: 'Export ready', detail: link.download });
  };

  const handleImportWorkflow = async (file: File) => {
    setCreatingWorkflow(true);
    setStatus({ tone: 'working', label: 'Importing workflow...' });
    try {
      const rawText = await file.text();
      const data = JSON.parse(rawText);
      if (!data || data.schema_version !== EXPORT_SCHEMA_VERSION) {
        throw new Error('Unsupported export format');
      }
      const draft = data.draft;
      if (!draft || !Array.isArray(draft.nodes) || !Array.isArray(draft.edges)) {
        throw new Error('Draft is missing nodes or edges');
      }
      const importErrors = validateImportedDraft(draft);
      if (importErrors.length > 0) {
        const preview = importErrors.slice(0, 3).join(' | ');
        const suffix = importErrors.length > 3 ? ` (+${importErrors.length - 3} more)` : '';
        throw new Error(`Draft validation failed: ${preview}${suffix}`);
      }
      const name = String(data.workflow?.name || 'Imported workflow').trim() || 'Imported workflow';
      const description =
        data.workflow?.description !== undefined && data.workflow?.description !== null
          ? String(data.workflow.description)
          : '';
      const result = await createWorkflow({
        name,
        description,
        draft
      });
      if (result.error) {
        setStatus({ tone: 'error', label: 'Import failed', detail: result.error.message });
        setCreatingWorkflow(false);
        return;
      }
      const workflow = result.data!;
      const parsed = parseDraft(workflow.draft || DEFAULT_DRAFT);
      setNodes(parsed.nodes);
      setEdges(parsed.edges);
      setVariablesSchema(parsed.variablesSchema);
      setSelectedNodeId(null);
      setWorkflowId(workflow.workflow_id);
      setWorkflowInput(workflow.workflow_id);
      setWorkflowName(workflow.name);
      setWorkflowDescription(workflow.description || '');
      setActiveVersionId(workflow.active_version_id || null);
      setRunHistory([]);
      setDirty(false);
      setMetaDirty(false);
      void fetchWorkflows();
      void fetchRunHistory(workflow.workflow_id);
      setStatus({ tone: 'ok', label: 'Import completed', detail: workflow.workflow_id });
    } catch (err: any) {
      setStatus({ tone: 'error', label: 'Import failed', detail: err?.message || 'Invalid file' });
    } finally {
      setCreatingWorkflow(false);
    }
  };

  const createNewWorkflow = async (nameOverride?: string, options?: { auto?: boolean }) => {
    if (creatingWorkflow) return;
    setCreatingWorkflow(true);
    setStatus({ tone: 'working', label: 'Creating workflow...' });
    const name = (nameOverride || 'Untitled workflow').trim() || 'Untitled workflow';
    const draft = DEFAULT_DRAFT;
    const result = await createWorkflow({
      name,
      description: '',
      draft
    });
    if (result.error) {
      setStatus({ tone: 'error', label: 'Create failed', detail: result.error.message });
      setCreatingWorkflow(false);
      autoCreatedRef.current = false;
      return;
    }
    const workflow = result.data!;
    resetDraftToDefault();
    setWorkflowId(workflow.workflow_id);
    setWorkflowInput(workflow.workflow_id);
    setWorkflowName(workflow.name);
    setWorkflowDescription(workflow.description || '');
    setActiveVersionId(workflow.active_version_id || null);
    setRunHistory([]);
    setMetaDirty(false);
    void fetchRunHistory(workflow.workflow_id);
    setStatus({ tone: 'ok', label: 'Workflow created', detail: workflow.workflow_id });
    setCreatingWorkflow(false);
    if (options?.auto) {
      setAutoCreatedWorkflowId(workflow.workflow_id);
    }
  };

  const handleUpdateWorkflowMeta = async () => {
    if (!workflowId) return;
    const name = workflowName.trim();
    if (!name) {
      setStatus({ tone: 'warn', label: 'Name is required' });
      return;
    }
    const result = await updateWorkflowMeta(workflowId, {
      name,
      description: workflowDescription || null
    });
    if (result.error) {
      setStatus({ tone: 'error', label: 'Update failed', detail: result.error.message });
      return;
    }
    setMetaDirty(false);
    setStatus({ tone: 'ok', label: 'Metadata saved' });
  };

  const handleNewWorkflow = async () => {
    await createNewWorkflow();
  };

  const loadWorkflowById = async (workflowIdToLoad: string) => {
    if (!workflowIdToLoad.trim()) {
      setStatus({ tone: 'warn', label: 'Enter workflow ID' });
      return;
    }
    setStatus({ tone: 'working', label: 'Loading workflow...' });
    const result = await getWorkflow(workflowIdToLoad.trim());
    if (result.error) {
      setStatus({ tone: 'error', label: 'Load failed', detail: result.error.message });
      return;
    }
    const workflow = result.data!;
    const parsed = parseDraft(workflow.draft || DEFAULT_DRAFT);
    setNodes(parsed.nodes);
    setEdges(parsed.edges);
    setVariablesSchema(parsed.variablesSchema);
    setSelectedNodeId(null);
    setWorkflowId(workflow.workflow_id);
    setWorkflowName(workflow.name);
    setWorkflowDescription(workflow.description || '');
    setActiveVersionId(workflow.active_version_id || null);
    setWorkflowInput(workflow.workflow_id);
    setRunHistory([]);
    setDirty(false);
    void fetchRunHistory(workflow.workflow_id);
    setStatus({ tone: 'ok', label: 'Workflow loaded' });
  };

  const handleLoadWorkflow = async () => {
    if (!workflowInput.trim()) {
      setStatus({ tone: 'warn', label: 'Enter workflow ID' });
      return;
    }
    await loadWorkflowById(workflowInput.trim());
  };

  const fetchWorkflows = async () => {
    setWorkflowListLoading(true);
    const result = await listWorkflows(100);
    if (result.error) {
      setStatus({ tone: 'error', label: 'List failed', detail: result.error.message });
      setWorkflowListLoading(false);
      return;
    }
    setWorkflowList(result.data?.items || []);
    setWorkflowListLoading(false);
  };

  const fetchRunHistory = async (workflowIdToLoad?: string) => {
    const targetWorkflowId = (workflowIdToLoad || workflowId).trim();
    if (!targetWorkflowId) {
      setRunHistory([]);
      return;
    }
    setRunHistoryLoading(true);
    const result = await listRuns({ workflowId: targetWorkflowId, limit: 100 });
    if (result.error) {
      setStatus({ tone: 'error', label: 'Run history failed', detail: result.error.message });
      setRunHistoryLoading(false);
      return;
    }
    setRunHistory(result.data?.items || []);
    setRunHistoryLoading(false);
  };

  const handleSaveDraft = async () => {
    if (!workflowId) return;
    setStatus({ tone: 'working', label: 'Saving draft...' });
    const draft = buildDraft(nodes, edges, variablesSchema);
    const result = await updateDraft(workflowId, draft);
    if (result.error) {
      setStatus({ tone: 'error', label: 'Save failed', detail: result.error.message });
      return;
    }
    setDirty(false);
    setStatus({ tone: 'ok', label: 'Draft saved' });
  };

  const publishNow = async (): Promise<string | null> => {
    if (!workflowId) {
      setStatus({ tone: 'warn', label: 'Create or load a workflow first' });
      return null;
    }
    const errors = issues.filter((issue) => issue.level === 'error');
    if (errors.length) {
      setStatus({ tone: 'error', label: 'Fix validation errors before publishing' });
      return null;
    }
    if (dirty) {
      await handleSaveDraft();
    }
    setStatus({ tone: 'working', label: 'Publishing...' });
    const result = await publishWorkflow(workflowId);
    if (result.error) {
      setStatus({ tone: 'error', label: 'Publish failed', detail: result.error.message });
      return null;
    }
    const versionId = result.data!.version_id;
    setActiveVersionId(versionId);
    setStatus({ tone: 'ok', label: 'Published' });
    return versionId;
  };

  const handlePublish = async () => {
    await publishNow();
  };

  const handleRollback = async () => {
    if (!workflowId) {
      setStatus({ tone: 'warn', label: 'No workflow to rollback' });
      return;
    }
    setStatus({ tone: 'working', label: 'Rolling back...' });
    const result = await rollbackWorkflow(workflowId);
    if (result.error) {
      setStatus({ tone: 'error', label: 'Rollback failed', detail: result.error.message });
      return;
    }
    const workflow = result.data!;
    const parsed = parseDraft(workflow.draft || DEFAULT_DRAFT);
    setNodes(parsed.nodes);
    setEdges(parsed.edges);
    setVariablesSchema(parsed.variablesSchema);
    setDirty(false);
    setActiveVersionId(workflow.active_version_id || null);
    setStatus({ tone: 'ok', label: 'Draft reset to published version' });
  };

  const handleRun = async () => {
    if (!workflowId) {
      setStatus({ tone: 'warn', label: 'Publish a workflow first' });
      return;
    }
    setStatus({ tone: 'working', label: 'Starting run...' });
    const result = await startRun(workflowId, {
      inputs: {},
      version_id: activeVersionId || undefined,
      mode: runMode
    });
    if (result.error) {
      setStatus({ tone: 'error', label: 'Run failed', detail: result.error.message });
      return;
    }
    setStatus({
      tone: 'ok',
      label: runMode === 'test' ? 'Test run started' : 'Run started',
      detail: result.data?.run_id
    });
    void fetchRunHistory(workflowId);
  };

  const handleOpenRunHistory = async () => {
    if (!workflowId) {
      setStatus({ tone: 'warn', label: 'Select a workflow first' });
      return;
    }
    setRunHistoryExpandedId(null);
    openRunHistory();
    await fetchRunHistory(workflowId);
  };

  const handleCloseRunHistory = () => {
    setRunHistoryExpandedId(null);
    closeRunHistory();
  };

  const chatkitUrl = useMemo(() => {
    if (!workflowId) return '';
    const url = new URL(CHATKIT_PAGE, window.location.origin);
    url.searchParams.set('api_url', CHATKIT_API_URL);
    if (CHATKIT_DOMAIN_KEY) {
      url.searchParams.set('domain_key', CHATKIT_DOMAIN_KEY);
    }
    if (CHATKIT_AUTH_TOKEN) {
      url.searchParams.set('auth_token', CHATKIT_AUTH_TOKEN);
    }
    url.searchParams.set('workflow_id', workflowId);
    if (activeVersionId) {
      url.searchParams.set('workflow_version_id', activeVersionId);
    }
    url.searchParams.set('auto', '1');
    url.searchParams.set('auto_start', '1');
    return url.toString();
  }, [workflowId, activeVersionId]);

  const chatkitEmbedUrl = useMemo(() => {
    if (!chatkitUrl) return '';
    const url = new URL(chatkitUrl);
    url.searchParams.set('embed', '1');
    return url.toString();
  }, [chatkitUrl]);

  const handleOpenChat = async () => {
    if (!workflowId) {
      setStatus({ tone: 'warn', label: 'Select a workflow first' });
      return;
    }
    let versionId = activeVersionId;
    if (!versionId) {
      versionId = await publishNow();
      if (!versionId) {
        return;
      }
    }
    if (!chatkitUrl) {
      setStatus({ tone: 'warn', label: 'Chat link not ready yet' });
      return;
    }
    setChatOpen(true);
  };

  const handleImportClick = () => {
    importInputRef.current?.click();
  };

  const handleImportFileChange = (event: ReactChangeEvent<HTMLInputElement>) => {
    const file = event.currentTarget.files?.[0];
    event.currentTarget.value = '';
    if (!file) return;
    void handleImportWorkflow(file);
  };

  const handlePointerMove = (event: ReactPointerEvent<HTMLDivElement>) => {
    const rect = canvasRef.current?.getBoundingClientRect();
    if (!rect) return;
    const x = (event.clientX - rect.left - offset.x) / scale;
    const y = (event.clientY - rect.top - offset.y) / scale;
    setCursor({ x, y });

    if (draggingNodeId) {
      setNodes((prev) =>
        prev.map((node) =>
          node.id === draggingNodeId
            ? {
                ...node,
                position: { x: x - dragOffset.x, y: y - dragOffset.y }
              }
            : node
        )
      );
      markDirty();
    }

    if (panning) {
      const dx = event.clientX - panStart.x;
      const dy = event.clientY - panStart.y;
      setOffset({ x: panStart.ox + dx, y: panStart.oy + dy });
    }
  };

  const handlePointerUp = () => {
    setDraggingNodeId(null);
    setPanning(false);
    if (connectingViaDrag) {
      setConnectingFrom(null);
      setConnectingViaDrag(false);
    }
  };

  const handleWheel = (event: React.WheelEvent<HTMLDivElement>) => {
    if (!event.ctrlKey && !event.metaKey) return;
    event.preventDefault();
    const next = Math.max(0.6, Math.min(1.6, scale - event.deltaY * 0.001));
    setScale(next);
  };

  const beginDragNode = (event: ReactPointerEvent, nodeId: string) => {
    event.stopPropagation();
    const rect = canvasRef.current?.getBoundingClientRect();
    if (!rect) return;
    const node = nodes.find((item) => item.id === nodeId);
    if (!node) return;
    const x = (event.clientX - rect.left - offset.x) / scale;
    const y = (event.clientY - rect.top - offset.y) / scale;
    setDraggingNodeId(nodeId);
    setDragOffset({ x: x - node.position.x, y: y - node.position.y });
    setSelectedNodeId(nodeId);
  };

  const beginConnectDrag = (event: ReactPointerEvent, nodeId: string) => {
    event.stopPropagation();
    setConnectingFrom(nodeId);
    setConnectingViaDrag(true);
  };

  const beginPan = (event: ReactPointerEvent) => {
    if ((event.target as HTMLElement).closest('[data-node]')) return;
    if (connectingFrom) {
      setConnectingFrom(null);
    }
    setPanning(true);
    setPanStart({ x: event.clientX, y: event.clientY, ox: offset.x, oy: offset.y });
  };

  const renderInspector = () => {
    if (!selectedNode) {
      return (
        <Text size="sm" c="dimmed">
          Select a node to edit its configuration.
        </Text>
      );
    }

    const config = selectedNode.config || defaultNodeConfig(selectedNode.type);
    const relatedEdges = edges.filter(
      (edge) => edge.source === selectedNode.id || edge.target === selectedNode.id
    );
    const outputFormat =
      selectedNode.type === 'agent'
        ? (config.output_format as string) || (config.output_schema ? 'json' : 'text')
        : null;

    const commonFields = (
        <Group gap="sm" grow>
          <TextInput
            label="Node ID"
            value={selectedNode.id}
            onChange={(event) => renameNode(selectedNode.id, event.currentTarget.value)}
          />
        <Select
          label="Type"
          data={NODE_PALETTE.map((item) => ({ value: item.type, label: item.label }))}
          value={selectedNode.type}
          onChange={(value) => {
            if (!value) return;
            updateNode(selectedNode.id, { type: value as NodeType, config: defaultNodeConfig(value as NodeType) });
          }}
        />
      </Group>
    );

    return (
      <Stack gap="sm">
        {commonFields}

        {selectedNode.type === 'start' && (
          <Stack gap="sm">
            <JsonEditor
              label="Defaults"
              value={config.defaults}
              onApply={(value) => updateNodeConfig(selectedNode.id, { defaults: value })}
              description="Initial values merged with runtime inputs."
            />
            <JsonEditor
              label="Variables Schema"
              value={variablesSchema}
              onApply={(value) => {
                setVariablesSchema(value || {});
                markDirty();
              }}
              description="JSON schema for input variables."
            />
          </Stack>
        )}

        {selectedNode.type === 'agent' && (
          <Stack gap="sm">
            <TemplateTextarea
              label="Instructions"
              value={config.instructions || ''}
              onChange={(next) => updateNodeConfig(selectedNode.id, { instructions: next })}
              variables={variableOptions}
              testId="agent-instructions"
            />
            <TemplateTextarea
              label="User Input"
              value={config.user_input || ''}
              onChange={(next) => updateNodeConfig(selectedNode.id, { user_input: next })}
              variables={variableOptions}
              testId="agent-user-input"
            />
            <Select
              label="Output format"
              data={OUTPUT_FORMAT_OPTIONS}
              value={outputFormat || 'text'}
              data-testid="agent-output-format"
              onChange={(value) => {
                const nextFormat = (value as string) || 'text';
                updateNodeConfig(selectedNode.id, { output_format: nextFormat });
              }}
            />
            {outputFormat === 'json' && (
              <>
                {config.output_schema ? (
                  <JsonEditor
                    label="Output schema"
                    value={config.output_schema || {}}
                    onApply={(value) => updateNodeConfig(selectedNode.id, { output_schema: value })}
                  />
                ) : (
                  <Button
                    size="xs"
                    variant="light"
                    onClick={() =>
                      updateNodeConfig(selectedNode.id, {
                        output_schema: { type: 'object', properties: {} }
                      })
                    }
                  >
                    Add schema
                  </Button>
                )}
              </>
            )}
            {outputFormat === 'widget' && (
              <Stack gap="xs">
                <Select
                  label="Widget template"
                  placeholder="Select widget"
                  data={WIDGET_TEMPLATES}
                  value={config.output_widget || null}
                  data-testid="agent-widget-template"
                  onChange={(value) => updateNodeConfig(selectedNode.id, { output_widget: value || '' })}
                />
                {config.output_widget && (
                  <Badge variant="light" color="violet" data-testid="agent-widget-selected">
                    {WIDGET_TEMPLATES.find((item) => item.value === config.output_widget)?.label ||
                      config.output_widget}
                  </Badge>
                )}
              </Stack>
            )}
            <TextInput
              label="Model"
              value={config.model || ''}
              onChange={(event) => updateNodeConfig(selectedNode.id, { model: event.currentTarget.value })}
              placeholder="gpt-5.2"
            />
            <TextInput
              label="Allowed tools"
              value={(config.allowed_tools || []).join(', ')}
              onChange={(event) =>
                updateNodeConfig(selectedNode.id, {
                  allowed_tools: event.currentTarget.value
                    .split(',')
                    .map((tool: string) => tool.trim())
                    .filter(Boolean)
                })
              }
            />
            <Group grow>
              <NumberInput
                label="Max retries"
                value={config.max_retries ?? 0}
                min={0}
                onChange={(value) => updateNodeConfig(selectedNode.id, { max_retries: toNumber(value, 0) })}
              />
              <NumberInput
                label="Timeout (s)"
                value={config.timeout_s ?? undefined}
                min={0}
                onChange={(value) => updateNodeConfig(selectedNode.id, { timeout_s: toNumber(value, null) })}
              />
            </Group>
            <Switch
              label="Emit partial outputs"
              checked={Boolean(config.emit_partial)}
              onChange={(event) => updateNodeConfig(selectedNode.id, { emit_partial: event.currentTarget.checked })}
            />
          </Stack>
        )}

        {selectedNode.type === 'mcp' && (
          <Stack gap="sm">
            <TextInput
              label="Server"
              value={config.server || ''}
              onChange={(event) => updateNodeConfig(selectedNode.id, { server: event.currentTarget.value })}
            />
            <TextInput
              label="Tool"
              value={config.tool || ''}
              onChange={(event) => updateNodeConfig(selectedNode.id, { tool: event.currentTarget.value })}
            />
            <NumberInput
              label="Timeout (s)"
              value={config.timeout_s ?? 30}
              min={1}
              onChange={(value) => updateNodeConfig(selectedNode.id, { timeout_s: toNumber(value, 30) })}
            />
            <TextInput
              label="Allowed tools"
              value={(config.allowed_tools || []).join(', ')}
              onChange={(event) =>
                updateNodeConfig(selectedNode.id, {
                  allowed_tools: event.currentTarget.value
                    .split(',')
                    .map((tool: string) => tool.trim())
                    .filter(Boolean)
                })
              }
            />
            <JsonEditor
              label="Arguments"
              value={config.arguments || {}}
              onApply={(value) => updateNodeConfig(selectedNode.id, { arguments: value })}
            />
          </Stack>
        )}

        {selectedNode.type === 'if_else' && (
          <Stack gap="sm">
            {(config.branches || []).map((branch: any, index: number) => (
              <Card key={`branch-${index}`} withBorder radius="md" padding="sm">
                <Stack gap="xs">
                  <TextInput
                    label={`Condition ${index + 1}`}
                    value={branch.condition || ''}
                    onChange={(event) => {
                      const next = [...(config.branches || [])];
                      next[index] = { ...next[index], condition: event.currentTarget.value };
                      updateNodeConfig(selectedNode.id, { branches: next });
                    }}
                  />
                  <TextInput
                    label="Target node"
                    value={branch.target || ''}
                    onChange={(event) => {
                      const next = [...(config.branches || [])];
                      next[index] = { ...next[index], target: event.currentTarget.value };
                      updateNodeConfig(selectedNode.id, { branches: next });
                    }}
                  />
                  <Button
                    size="xs"
                    variant="light"
                    color="red"
                    onClick={() => {
                      const next = [...(config.branches || [])];
                      next.splice(index, 1);
                      updateNodeConfig(selectedNode.id, { branches: next });
                    }}
                  >
                    Remove branch
                  </Button>
                </Stack>
              </Card>
            ))}
            <Button
              size="xs"
              variant="light"
              onClick={() => {
                const next = [...(config.branches || []), { condition: '', target: '' }];
                updateNodeConfig(selectedNode.id, { branches: next });
              }}
            >
              Add branch
            </Button>
            <TextInput
              label="Else target"
              value={config.else_target || ''}
              onChange={(event) => updateNodeConfig(selectedNode.id, { else_target: event.currentTarget.value })}
            />
          </Stack>
        )}

        {selectedNode.type === 'while' && (
          <Stack gap="sm">
            <TextInput
              label="Condition"
              value={config.condition || ''}
              onChange={(event) => updateNodeConfig(selectedNode.id, { condition: event.currentTarget.value })}
            />
            <NumberInput
              label="Max iterations"
              value={config.max_iterations ?? 1}
              min={1}
              onChange={(value) => updateNodeConfig(selectedNode.id, { max_iterations: toNumber(value, 1) })}
            />
            <TextInput
              label="Body target"
              value={config.body_target || ''}
              onChange={(event) => updateNodeConfig(selectedNode.id, { body_target: event.currentTarget.value })}
            />
            <TextInput
              label="Exit target"
              value={config.exit_target || ''}
              onChange={(event) => updateNodeConfig(selectedNode.id, { exit_target: event.currentTarget.value })}
            />
            <TextInput
              label="Loop back"
              value={config.loop_back || ''}
              onChange={(event) => updateNodeConfig(selectedNode.id, { loop_back: event.currentTarget.value })}
            />
          </Stack>
        )}

        {selectedNode.type === 'set_state' && (
          <Stack gap="sm">
            <TextInput
              label="Target"
              value={config.target || ''}
              onChange={(event) => updateNodeConfig(selectedNode.id, { target: event.currentTarget.value })}
            />
            <TextInput
              label="Expression"
              value={config.expression || ''}
              onChange={(event) => updateNodeConfig(selectedNode.id, { expression: event.currentTarget.value })}
            />
          </Stack>
        )}

        {(selectedNode.type === 'interaction' || selectedNode.type === 'approval') && (
          <Stack gap="sm">
            <TemplateTextarea
              label="Prompt"
              value={config.prompt || ''}
              onChange={(next) => updateNodeConfig(selectedNode.id, { prompt: next })}
              variables={variableOptions}
              testId="interaction-prompt"
            />
            <TextInput
              label="State target"
              value={config.state_target || ''}
              onChange={(event) => updateNodeConfig(selectedNode.id, { state_target: event.currentTarget.value })}
            />
            <Switch
              label="Allow file upload"
              checked={Boolean(config.allow_file_upload)}
              onChange={(event) => updateNodeConfig(selectedNode.id, { allow_file_upload: event.currentTarget.checked })}
            />
            {selectedNode.type === 'interaction' && (
              <JsonEditor
                label="Input schema"
                value={config.input_schema || {}}
                onApply={(value) => updateNodeConfig(selectedNode.id, { input_schema: value })}
              />
            )}
          </Stack>
        )}

        {selectedNode.type === 'output' && (
          <Stack gap="sm">
            <Select
              label="Mode"
              data={[
                { value: 'expression', label: 'Expression' },
                { value: 'value', label: 'Static value' }
              ]}
              value={config.expression ? 'expression' : 'value'}
              onChange={(value) => {
                if (value === 'expression') {
                  updateNodeConfig(selectedNode.id, { expression: config.expression || 'state' });
                } else {
                  updateNodeConfig(selectedNode.id, { expression: null });
                }
              }}
            />
            {config.expression ? (
              <TextInput
                label="Expression"
                value={config.expression || ''}
                onChange={(event) => updateNodeConfig(selectedNode.id, { expression: event.currentTarget.value })}
              />
            ) : (
              <JsonEditor
                label="Static value"
                value={config.value || {}}
                onApply={(value) => updateNodeConfig(selectedNode.id, { value })}
              />
            )}
          </Stack>
        )}

        <Divider />
        <Stack gap="xs">
          <Text size="sm" fw={600}>
            Connections
          </Text>
          {relatedEdges.length === 0 ? (
            <Text size="xs" c="dimmed">
              No edges connected.
            </Text>
          ) : (
            relatedEdges.map((edge) => (
              <Group key={edge.id} justify="space-between" wrap="nowrap">
                <Text size="xs" c="dimmed">
                  {edge.source} → {edge.target}
                </Text>
                <Button size="xs" variant="light" color="red" onClick={() => handleRemoveEdge(edge.id)}>
                  Remove
                </Button>
              </Group>
            ))
          )}
        </Stack>
        <Divider />
        <Group justify="space-between">
          <Button
            variant="light"
            color="red"
            size="xs"
            onClick={() => handleRemoveNode(selectedNode.id)}
          >
            Delete node
          </Button>
          <Text size="xs" c="dimmed">
            {selectedNode.type.toUpperCase()}
          </Text>
        </Group>
      </Stack>
    );
  };

  const edgePaths = useMemo(() => {
    return edges
      .map((edge) => {
        const source = nodes.find((node) => node.id === edge.source);
        const target = nodes.find((node) => node.id === edge.target);
        if (!source || !target) return null;
        const start = {
          x: source.position.x + NODE_DIMENSIONS.width,
          y: source.position.y + NODE_DIMENSIONS.height / 2
        };
        const end = {
          x: target.position.x,
          y: target.position.y + NODE_DIMENSIONS.height / 2
        };
        const dx = Math.max(80, Math.abs(end.x - start.x));
        const path = `M ${start.x} ${start.y} C ${start.x + dx} ${start.y}, ${end.x - dx} ${end.y}, ${end.x} ${end.y}`;
        return { id: edge.id, path };
      })
      .filter(Boolean) as Array<{ id: string; path: string }>;
  }, [edges, nodes]);

  return (
    <AppShell
      className="app-shell"
      header={{ height: 72 }}
      navbar={{ width: 300, breakpoint: 'sm' }}
      aside={{ width: 360, breakpoint: 'sm' }}
      padding="md"
    >
      <AppShell.Header>
        <Group h="100%" px="lg" justify="space-between" className="header">
          <Group gap="sm">
            <Badge color="brand" variant="filled">
              Builder
            </Badge>
            <Stack gap={0}>
              <Title order={4}>Workflow Studio</Title>
              <Text size="xs" c="dimmed">
                {workflowId ? `Workflow ${workflowId}` : 'No workflow loaded'}
              </Text>
            </Stack>
          </Group>
          <Group gap="xs">
            <Select
              placeholder="Select workflow"
              searchable
              clearable
              w={260}
              data={workflowList.map((item) => ({
                value: item.workflow_id,
                label: `${item.name} (${item.workflow_id})`
              }))}
              value={workflowId || undefined}
              onChange={(value) => {
                if (!value) return;
                setWorkflowInput(value);
                void loadWorkflowById(value);
              }}
              nothingFoundMessage={workflowListLoading ? 'Loading...' : 'No workflows'}
            />
            <Button variant="light" onClick={openList}>
              Browse
            </Button>
            <Button variant="outline" onClick={handleNewWorkflow} disabled={creatingWorkflow}>
              New
            </Button>
            <Divider orientation="vertical" />
            <Button variant="light" onClick={handleSaveDraft}>
              Save
            </Button>
            <Button variant="light" onClick={handleAutoLayout} data-testid="auto-layout">
              Auto layout
            </Button>
            <Button variant="filled" onClick={handlePublish}>
              Publish
            </Button>
            <Select
              value={runMode}
              onChange={(value) => setRunMode((value as 'live' | 'test') || 'live')}
              data={[
                { value: 'live', label: 'Live' },
                { value: 'test', label: 'Test' }
              ]}
              w={110}
            />
            <Button color="teal" variant="filled" onClick={handleRun}>
              Run
            </Button>
            <Button variant="light" onClick={handleOpenRunHistory}>
              History
            </Button>
            <Button
              variant="light"
              onClick={handleOpenChat}
              data-testid="open-chatkit"
              data-chatkit-url={chatkitUrl || undefined}
            >
              Open Chat
            </Button>
            <Menu
              shadow="md"
              width={220}
              position="bottom-end"
              keepMounted
              opened={moreMenuOpen}
              onChange={setMoreMenuOpen}
            >
              <Menu.Target>
                <Button variant="light" onClick={() => setMoreMenuOpen((prev) => !prev)}>
                  More
                </Button>
              </Menu.Target>
              <Menu.Dropdown>
                <Menu.Item
                  onClick={() => {
                    setMoreMenuOpen(false);
                    fetchWorkflows();
                  }}
                >
                  Refresh list
                </Menu.Item>
                <Menu.Item
                  onClick={() => {
                    setMoreMenuOpen(false);
                    handleAutoLayout();
                  }}
                  data-testid="auto-layout-menu"
                >
                  Auto layout
                </Menu.Item>
                <Menu.Item
                  onClick={() => {
                    setMoreMenuOpen(false);
                    handleExportWorkflow();
                  }}
                  data-testid="export-workflow"
                >
                  Export JSON
                </Menu.Item>
                <Menu.Item
                  onClick={() => {
                    setMoreMenuOpen(false);
                    handleImportClick();
                  }}
                  disabled={creatingWorkflow}
                  data-testid="import-workflow"
                >
                  Import JSON
                </Menu.Item>
                <Menu.Item
                  onClick={() => {
                    setMoreMenuOpen(false);
                    openIntegration();
                  }}
                  data-testid="open-integration-kit"
                >
                  Integration kit
                </Menu.Item>
                <Menu.Divider />
                <Menu.Item
                  onClick={() => {
                    setMoreMenuOpen(false);
                    handleRollback();
                  }}
                >
                  Rollback draft
                </Menu.Item>
              </Menu.Dropdown>
            </Menu>
            <input
              ref={importInputRef}
              type="file"
              accept="application/json,.json"
              onChange={handleImportFileChange}
              data-testid="import-workflow-input"
              style={{ display: 'none' }}
            />
          </Group>
        </Group>
      </AppShell.Header>

      <AppShell.Navbar p="md" className="panel">
        <Stack gap="md">
          <Group justify="space-between" align="center">
            <Text className="panel-title">Node palette</Text>
            <Badge color="brand" variant="light">
              {nodes.length} nodes
            </Badge>
          </Group>
          <ScrollArea h="calc(100vh - 180px)">
            <Stack gap="sm">
              {NODE_PALETTE.map((item) => (
                <Card
                  key={item.type}
                  shadow="sm"
                  radius="md"
                  withBorder
                  className={`palette-card tone-${item.tone}`}
                  onClick={() => handleAddNode(item.type)}
                >
                  <Text fw={600}>{item.label}</Text>
                  <Text size="sm" c="dimmed">
                    {item.description}
                  </Text>
                </Card>
              ))}
            </Stack>
          </ScrollArea>
        </Stack>
      </AppShell.Navbar>

      <AppShell.Aside p="md" className="panel">
        <Stack gap="sm">
          <Group justify="space-between" align="center">
            <Text className="panel-title">Autosave</Text>
            <Switch checked={autoSave} onChange={(event) => setAutoSave(event.currentTarget.checked)} />
          </Group>
          <Tabs defaultValue="inspector">
            <Tabs.List grow>
              <Tabs.Tab value="inspector">Inspector</Tabs.Tab>
              <Tabs.Tab value="validation">Validation</Tabs.Tab>
            </Tabs.List>
            <Tabs.Panel value="inspector" pt="md">
              <ScrollArea h="calc(100vh - 240px)">
                <Stack gap="md">{renderInspector()}</Stack>
              </ScrollArea>
            </Tabs.Panel>
            <Tabs.Panel value="validation" pt="md">
              <ScrollArea h="calc(100vh - 240px)">
                <Stack gap="sm">
                  <Group justify="space-between">
                    <Text fw={600}>Issues</Text>
                    <Badge color={issues.some((issue) => issue.level === 'error') ? 'red' : 'teal'}>
                      {issues.length}
                    </Badge>
                  </Group>
                  {issues.length === 0 ? (
                    <Text size="sm" c="dimmed">
                      Graph looks good.
                    </Text>
                  ) : (
                    issues.map((issue) => (
                      <Card key={issue.id} withBorder radius="md" className={`issue ${issue.level}`}>
                        <Text size="sm" fw={600}>
                          {issue.level === 'error' ? 'Error' : 'Warning'}
                        </Text>
                        <Text size="sm" c="dimmed">
                          {issue.message}
                        </Text>
                        {issue.nodeId && (
                          <Button
                            size="xs"
                            variant="light"
                            mt="xs"
                            onClick={() => setSelectedNodeId(issue.nodeId || null)}
                          >
                            Focus node
                          </Button>
                        )}
                      </Card>
                    ))
                  )}
                </Stack>
              </ScrollArea>
            </Tabs.Panel>
          </Tabs>
        </Stack>
      </AppShell.Aside>

      <AppShell.Main>
        <Stack gap="md">
          <Drawer
            opened={chatOpen}
            onClose={() => setChatOpen(false)}
            position="right"
            size={520}
            title="Test Chat"
            overlayProps={{ opacity: 0.2, blur: 2 }}
          >
            <Stack gap="xs" style={{ height: 'calc(100vh - 160px)' }}>
              <Group justify="space-between" align="center">
                <Text size="xs" c="dimmed">
                  Workflow {workflowId || '—'}
                </Text>
                <Button
                  size="xs"
                  variant="light"
                  onClick={() => window.open(chatkitUrl, '_blank', 'noopener')}
                  disabled={!chatkitUrl}
                >
                  Open in new tab
                </Button>
              </Group>
              {!CHATKIT_DOMAIN_KEY && (
                <Badge color="red" variant="light">
                  Set VITE_CHATKIT_DOMAIN_KEY to use ChatKit
                </Badge>
              )}
              <Box
                style={{
                  flex: 1,
                  minHeight: 0,
                  borderRadius: 16,
                  overflow: 'hidden',
                  border: '1px solid rgba(15, 23, 42, 0.12)'
                }}
              >
                {chatkitEmbedUrl ? (
                  <iframe
                    title="ChatKit"
                    src={chatkitEmbedUrl}
                    style={{ width: '100%', height: '100%', border: 'none' }}
                  />
                ) : (
                  <Box p="md">
                    <Text size="sm" c="dimmed">
                      Select a workflow to open chat.
                    </Text>
                  </Box>
                )}
              </Box>
            </Stack>
          </Drawer>
          <Group justify="space-between" align="flex-start">
            <Stack gap={6} style={{ maxWidth: 520 }}>
              <TextInput
                label="Workflow name"
                value={workflowName}
                placeholder="Untitled workflow"
                onChange={(event) => {
                  setWorkflowName(event.currentTarget.value);
                  setMetaDirty(true);
                }}
              />
              <Textarea
                label="Description"
                minRows={2}
                value={workflowDescription}
                placeholder="Define the run logic and publish."
                onChange={(event) => {
                  setWorkflowDescription(event.currentTarget.value);
                  setMetaDirty(true);
                }}
              />
            </Stack>
            <Group gap="xs">
              <Badge color={statusTone[status.tone]} variant="light">
                {status.label}
              </Badge>
              {status.detail && (
                <Badge color="gray" variant="outline">
                  {status.detail}
                </Badge>
              )}
              {dirty && <Badge color="orange" variant="light">Unsaved</Badge>}
              {activeVersionId && (
                <Badge color="teal" variant="light">
                  Published
                </Badge>
              )}
              <Badge color="gray" variant="light">
                Scale {Math.round(scale * 100)}%
              </Badge>
            </Group>
          </Group>
          {chatkitUrl && (
            <Group align="end" gap="xs">
              <TextInput
                label="Chat link"
                value={chatkitUrl}
                readOnly
                w={520}
                data-testid="chat-link"
                aria-label="Chat link"
              />
              <CopyButton value={chatkitUrl}>
                {({ copied, copy }) => (
                  <Button variant="light" size="sm" onClick={copy}>
                    {copied ? 'Copied' : 'Copy link'}
                  </Button>
                )}
              </CopyButton>
            </Group>
          )}
          <Box
            className="canvas"
            ref={canvasRef}
            onPointerMove={handlePointerMove}
            onPointerUp={handlePointerUp}
            onPointerLeave={handlePointerUp}
            onPointerDown={beginPan}
            onWheel={handleWheel}
          >
            <svg className="edge-layer" style={{ transform: `translate(${offset.x}px, ${offset.y}px) scale(${scale})` }}>
              {edgePaths.map((edge) => (
                <path key={edge.id} d={edge.path} />
              ))}
              {connectingFrom && cursor && (() => {
                const source = nodes.find((node) => node.id === connectingFrom);
                if (!source) return null;
                const start = {
                  x: source.position.x + NODE_DIMENSIONS.width,
                  y: source.position.y + NODE_DIMENSIONS.height / 2
                };
                const end = cursor;
                const dx = Math.max(80, Math.abs(end.x - start.x));
                const path = `M ${start.x} ${start.y} C ${start.x + dx} ${start.y}, ${end.x - dx} ${end.y}, ${end.x} ${end.y}`;
                return <path d={path} className="edge-preview" />;
              })()}
            </svg>

            <div
              className="canvas-inner"
              style={{ transform: `translate(${offset.x}px, ${offset.y}px) scale(${scale})` }}
            >
              {nodes.map((node) => (
                <div
                  key={node.id}
                  className={`node-card ${selectedNodeId === node.id ? 'selected' : ''}`}
                  style={{ left: node.position.x, top: node.position.y }}
                  data-node="true"
                  data-node-id={node.id}
                  onPointerDown={(event) => beginDragNode(event, node.id)}
                  onClick={(event) => {
                    event.stopPropagation();
                    setSelectedNodeId(node.id);
                  }}
                >
                  {node.type !== 'start' && (
                    <div
                      className={`node-port input ${connectingFrom && connectingFrom !== node.id ? 'can-connect' : ''}`}
                      onPointerDown={(event) => event.stopPropagation()}
                      onPointerUp={(event) => {
                        event.stopPropagation();
                        if (connectingFrom) {
                          handleAddEdge(connectingFrom, node.id);
                          setConnectingFrom(null);
                          setConnectingViaDrag(false);
                        }
                      }}
                      onClick={(event) => {
                        event.stopPropagation();
                        if (connectingFrom) {
                          handleAddEdge(connectingFrom, node.id);
                          setConnectingFrom(null);
                          setConnectingViaDrag(false);
                        }
                      }}
                    />
                  )}
                  {node.type !== 'end' && (
                    <div
                      className={`node-port output ${connectingFrom === node.id ? 'active' : ''}`}
                      onPointerDown={(event) => beginConnectDrag(event, node.id)}
                      onClick={(event) => {
                        event.stopPropagation();
                        setConnectingFrom(node.id);
                        setConnectingViaDrag(false);
                      }}
                    />
                  )}
                  <Group gap="xs" className="node-header">
                    <Badge variant="light">{node.type.replace('_', ' ')}</Badge>
                    <Text size="xs" c="dimmed">
                      {node.id}
                    </Text>
                  </Group>
                  <Text size="sm" fw={600} mt="xs">
                    {NODE_PALETTE.find((item) => item.type === node.type)?.description}
                  </Text>
                </div>
              ))}
            </div>
          </Box>
        </Stack>
      </AppShell.Main>

      <Modal opened={listOpen} onClose={closeList} title="Workflows" centered size="lg">
        <Stack gap="sm">
          <Group justify="space-between" align="center">
            <TextInput
              placeholder="Search by name or id"
              value={workflowQuery}
              onChange={(event) => setWorkflowQuery(event.currentTarget.value)}
              style={{ flex: 1 }}
            />
            <Button variant="light" loading={workflowListLoading} onClick={fetchWorkflows}>
              Refresh
            </Button>
          </Group>
          <ScrollArea h={360}>
            <Stack gap="sm">
              {workflowListLoading ? (
                <Text size="sm" c="dimmed">
                  Loading workflows...
                </Text>
              ) : filteredWorkflows.length === 0 ? (
                <Text size="sm" c="dimmed">
                  No workflows found.
                </Text>
              ) : (
                filteredWorkflows.map((item) => (
                  <Card
                    key={item.workflow_id}
                    withBorder
                    radius="md"
                    className="workflow-card"
                    onClick={() => {
                      setWorkflowInput(item.workflow_id);
                      void loadWorkflowById(item.workflow_id);
                      closeList();
                    }}
                  >
                    <Group justify="space-between" align="flex-start">
                      <Stack gap={2}>
                        <Text fw={600}>{item.name}</Text>
                        <Text size="xs" c="dimmed">
                          {item.workflow_id}
                        </Text>
                      </Stack>
                      <Stack gap={4} align="flex-end">
                        <Badge color={item.active_version_id ? 'teal' : 'gray'} variant="light">
                          {item.active_version_id ? 'Published' : 'Draft'}
                        </Badge>
                        {item.updated_at && (
                          <Text size="xs" c="dimmed">
                            Updated {formatTimestamp(item.updated_at)}
                          </Text>
                        )}
                      </Stack>
                    </Group>
                    {item.description && (
                      <Text size="sm" c="dimmed" mt="xs">
                        {item.description}
                      </Text>
                    )}
                  </Card>
                ))
              )}
            </Stack>
          </ScrollArea>
        </Stack>
      </Modal>

      <Modal
        opened={runHistoryOpen}
        onClose={handleCloseRunHistory}
        title="Execution history"
        centered
        size="lg"
      >
        <Stack gap="sm">
          <Group justify="space-between" align="center">
            <Text size="sm" c="dimmed">
              {workflowId ? `Workflow ${workflowId}` : 'No workflow selected'}
            </Text>
            <Button
              variant="light"
              loading={runHistoryLoading}
              onClick={() => void fetchRunHistory(workflowId)}
              disabled={!workflowId}
            >
              Refresh
            </Button>
          </Group>
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
                      onChange={(value) => setHistoryInputRateUsdPer1M(asUsdRate(value))}
                      min={0}
                      decimalScale={4}
                      fixedDecimalScale={false}
                      allowNegative={false}
                    />
                    <NumberInput
                      label="Output tokens rate"
                      value={historyOutputRateUsdPer1M}
                      onChange={(value) => setHistoryOutputRateUsdPer1M(asUsdRate(value))}
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
                  const isExpanded = runHistoryExpandedId === run.run_id;
                  return (
                    <Card key={run.run_id} withBorder radius="md">
                      <Group justify="space-between" align="flex-start">
                        <Stack gap={2}>
                          <Text fw={600}>{run.run_id}</Text>
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
                            onClick={() =>
                              setRunHistoryExpandedId((prev) => (prev === run.run_id ? null : run.run_id))
                            }
                          >
                            {isExpanded ? 'Hide details' : 'Show details'}
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
                        {tokenSummary && (
                          <Badge variant="light" color="indigo">
                            Tokens {tokenSummary.totalTokens}
                          </Badge>
                        )}
                        {tokenSummary && (
                          <Badge variant="light" color="green">
                            {formatUsd(runEstimatedCost)}
                          </Badge>
                        )}
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

                          {tokenSummary && (
                            <Group gap={8} wrap="wrap">
                              <Badge variant="outline" color="gray">
                                Input tokens {tokenSummary.inputTokens}
                              </Badge>
                              <Badge variant="outline" color="gray">
                                Output tokens {tokenSummary.outputTokens}
                              </Badge>
                              <Badge variant="light" color="indigo">
                                Total tokens {tokenSummary.totalTokens}
                              </Badge>
                              <Badge variant="light" color="green">
                                Est. cost {formatUsd(runEstimatedCost)}
                              </Badge>
                            </Group>
                          )}

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

      <Modal opened={integrationOpen} onClose={closeIntegration} title="Agent integration kit" centered size="lg">
        <Stack gap="sm">
          <Text size="sm" c="dimmed">
            Share this URL with external agents. It includes links to OpenAPI, API reference,
            workflow authoring guide, and JSON schemas.
          </Text>
          <Group align="flex-end" wrap="nowrap">
            <TextInput
              label="Shareable URL"
              value={integrationLinks.integrationKitMarkdown}
              readOnly
              style={{ flex: 1 }}
            />
            <CopyButton value={integrationLinks.integrationKitMarkdown}>
              {({ copied, copy }) => (
                <Button variant="light" onClick={copy}>
                  {copied ? 'Copied' : 'Copy'}
                </Button>
              )}
            </CopyButton>
            <Button
              component="a"
              href={integrationLinks.integrationKitMarkdown}
              target="_blank"
              rel="noopener noreferrer"
            >
              Open
            </Button>
          </Group>
          <Divider />
          <Stack gap={6}>
            <Text size="sm" fw={600}>
              Resources
            </Text>
            <Anchor href={integrationLinks.integrationKitJson} target="_blank" rel="noopener noreferrer">
              JSON bundle
            </Anchor>
            <Anchor href={integrationLinks.integrationTestUi} target="_blank" rel="noopener noreferrer">
              Integration test UI
            </Anchor>
            <Anchor href={integrationLinks.integrationTestJson} target="_blank" rel="noopener noreferrer">
              Integration test JSON report
            </Anchor>
            <Anchor href={integrationLinks.validateDraft} target="_blank" rel="noopener noreferrer">
              Draft validator endpoint
            </Anchor>
            <Anchor href={integrationLinks.openapi} target="_blank" rel="noopener noreferrer">
              OpenAPI contract
            </Anchor>
            <Anchor href={integrationLinks.apiReference} target="_blank" rel="noopener noreferrer">
              API reference
            </Anchor>
            <Anchor href={integrationLinks.workflowAuthoringGuide} target="_blank" rel="noopener noreferrer">
              Workflow authoring guide
            </Anchor>
            <Anchor href={integrationLinks.workflowDraftSchema} target="_blank" rel="noopener noreferrer">
              Workflow draft JSON schema
            </Anchor>
            <Anchor href={integrationLinks.workflowExportSchema} target="_blank" rel="noopener noreferrer">
              Workflow export JSON schema
            </Anchor>
          </Stack>
        </Stack>
      </Modal>

    </AppShell>
  );
}
