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
  listProjects,
  listRuns,
  listWorkflowsPage,
  publishWorkflow,
  rollbackWorkflow,
  startRun,
  deleteProject,
  deleteWorkflow,
  updateDraft,
  updateProject,
  updateWorkflowMeta
} from './api';
import type { ProjectRecord, RunRecord } from './api';
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
  WorkflowRecord,
  WorkflowSummary
} from './builder/types';
import {
  CANVAS_SCALE_STEP,
  CANVAS_WHEEL_ZOOM_SENSITIVITY,
  clampCanvasScale,
  computeZoomedOffset
} from './builder/viewport';
import { normalizeProjectId } from './project-switcher';
import { shouldAutoCreateWorkflow } from './workflow-auto-create';
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
type HistoryWorkflowScope = 'selected' | 'all';
type HistoryProjectScope = 'active' | 'all';
type ViewMode = 'builder' | 'scope';
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
const PROJECT_LIST_PAGE_LIMIT = 200;
const PROJECT_LIST_MAX_PAGES = 100;
const WORKFLOW_LIST_PAGE_LIMIT = 200;
const WORKFLOW_LIST_MAX_PAGES = 100;

const normalizeTenantId = (value: unknown): string => {
  if (typeof value !== 'string') return '';
  return value.trim();
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
  const [integrationOpen, { open: openIntegration, close: closeIntegration }] = useDisclosure(false);
  const [runHistoryOpen, { open: openRunHistory, close: closeRunHistory }] = useDisclosure(false);
  const [viewMode, setViewMode] = useState<ViewMode>(() => {
    if (typeof window === 'undefined') return 'builder';
    const params = new URLSearchParams(window.location.search);
    if (params.get('e2e') === '1') return 'builder';
    const queryValue = normalizeTenantId(params.get('view'));
    if (queryValue === 'builder' || queryValue === 'scope') {
      return queryValue;
    }
    if (window.location.pathname.startsWith('/scope')) {
      return 'scope';
    }
    if (window.location.pathname.startsWith('/studio')) {
      return 'builder';
    }
    return 'scope';
  });
  const [tenantId, setTenantId] = useState(() => {
    if (typeof window === 'undefined') return 'local';
    const fromQuery = normalizeTenantId(new URLSearchParams(window.location.search).get('tenant_id'));
    return fromQuery || 'local';
  });
  const [tenantInput, setTenantInput] = useState(() => {
    if (typeof window === 'undefined') return 'local';
    const fromQuery = normalizeTenantId(new URLSearchParams(window.location.search).get('tenant_id'));
    return fromQuery || 'local';
  });
  const [tenantSessionOptions, setTenantSessionOptions] = useState<string[]>(() => {
    if (typeof window === 'undefined') return ['local'];
    const fromQuery = normalizeTenantId(new URLSearchParams(window.location.search).get('tenant_id'));
    return fromQuery ? [fromQuery] : ['local'];
  });
  const [workflowId, setWorkflowId] = useState('');
  const [projectId, setProjectId] = useState(() => {
    if (typeof window === 'undefined') return '';
    return normalizeProjectId(new URLSearchParams(window.location.search).get('project_id'));
  });
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
  const scaleRef = useRef(scale);
  const offsetRef = useRef(offset);
  const [draggingNodeId, setDraggingNodeId] = useState<string | null>(null);
  const [dragOffset, setDragOffset] = useState({ x: 0, y: 0 });
  const [panning, setPanning] = useState(false);
  const [panStart, setPanStart] = useState({ x: 0, y: 0, ox: 0, oy: 0 });
  const [projectList, setProjectList] = useState<ProjectRecord[]>([]);
  const [projectListLoading, setProjectListLoading] = useState(false);
  const [projectEditTarget, setProjectEditTarget] = useState<ProjectRecord | null>(null);
  const [projectEditName, setProjectEditName] = useState('');
  const [projectEditLoading, setProjectEditLoading] = useState(false);
  const [projectDeleteTarget, setProjectDeleteTarget] = useState<ProjectRecord | null>(null);
  const [projectDeleteLoading, setProjectDeleteLoading] = useState(false);
  const [workflowList, setWorkflowList] = useState<WorkflowSummary[]>([]);
  const [workflowListLoading, setWorkflowListLoading] = useState(false);
  const [runHistoryRaw, setRunHistoryRaw] = useState<RunRecord[]>([]);
  const [runHistoryLoading, setRunHistoryLoading] = useState(false);
  const [runHistoryExpandedId, setRunHistoryExpandedId] = useState<string | null>(null);
  const [historyWorkflowScope, setHistoryWorkflowScope] = useState<HistoryWorkflowScope>('selected');
  const [historyProjectScope, setHistoryProjectScope] = useState<HistoryProjectScope>('active');
  const [historyInputRateUsdPer1M, setHistoryInputRateUsdPer1M] = useState(
    DEFAULT_INPUT_RATE_USD_PER_1M
  );
  const [historyOutputRateUsdPer1M, setHistoryOutputRateUsdPer1M] = useState(
    DEFAULT_OUTPUT_RATE_USD_PER_1M
  );

  const isTestEnv = typeof navigator !== 'undefined' && navigator.webdriver;
  const hasE2eQueryFlag =
    typeof window !== 'undefined' && new URLSearchParams(window.location.search).get('e2e') === '1';
  const skipAutoCreate = isTestEnv || hasE2eQueryFlag;
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
  const normalizedProjectId = normalizeProjectId(projectId);
  const projectDisplayNameById = useMemo(() => {
    const labels = new Map<string, string>();
    projectList.forEach((item) => {
      const normalized = normalizeProjectId(item.project_id);
      if (!normalized) return;
      labels.set(normalized, item.project_name?.trim() || normalized);
    });
    return labels;
  }, [projectList]);
  const activeProjectId = normalizedProjectId || undefined;
  const runHistory = useMemo(() => {
    let items = runHistoryRaw;

    if (historyWorkflowScope === 'selected') {
      const selectedWorkflowId = workflowId.trim();
      if (!selectedWorkflowId) {
        return [];
      }
      items = items.filter((item) => item.workflow_id === selectedWorkflowId);
    }

    if (historyProjectScope === 'active') {
      if (!activeProjectId) {
        return [];
      }
      items = items.filter((item) => normalizeProjectId(item.project_id) === activeProjectId);
    }

    return items;
  }, [runHistoryRaw, historyWorkflowScope, workflowId, historyProjectScope, activeProjectId]);
  const runHistoryProjectIds = useMemo(
    () =>
      Array.from(
        new Set(
          runHistoryRaw
            .map((item) => normalizeProjectId(item.project_id))
            .filter((value): value is string => !!value)
        )
      ).sort(),
    [runHistoryRaw]
  );
  const filteredOutRunCount = Math.max(runHistoryRaw.length - runHistory.length, 0);
  const workflowsForActiveProject = useMemo(
    () =>
      activeProjectId
        ? workflowList.filter((item) => normalizeProjectId(item.project_id) === activeProjectId)
        : workflowList,
    [workflowList, activeProjectId]
  );

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
    if (!activeProjectId) return;
    if (!shouldAutoCreateWorkflow(workflowId, autoCreatedRef.current, skipAutoCreate)) return;
    autoCreatedRef.current = true;
    void createNewWorkflow(undefined, { auto: true });
  }, [workflowId, skipAutoCreate, activeProjectId]);

  useEffect(() => {
    if (!isTestEnv || !autoCreatedWorkflowId) return;
    if (!activeProjectId) return;
    if (!workflowId || workflowId === autoCreatedWorkflowId) return;
    void deleteWorkflow(autoCreatedWorkflowId, activeProjectId);
    setAutoCreatedWorkflowId(null);
  }, [workflowId, autoCreatedWorkflowId, isTestEnv, activeProjectId]);

  useEffect(() => {
    return () => {
      if (isTestEnv && autoCreatedWorkflowId && activeProjectId) {
        void deleteWorkflow(autoCreatedWorkflowId, activeProjectId);
      }
    };
  }, [autoCreatedWorkflowId, isTestEnv, activeProjectId]);

  useEffect(() => {
    const initialTenant = normalizeTenantId(tenantId) || 'local';
    rememberTenantSession(initialTenant);
    updateUrlSearch({
      tenant_id: initialTenant,
      view: viewMode === 'scope' ? 'scope' : null
    }, viewMode === 'scope' ? '/scope' : '/');
  }, []);

  useEffect(() => {
    void fetchProjects();
  }, []);

  useEffect(() => {
    void fetchWorkflows();
  }, [activeProjectId, projectList]);

  useEffect(() => {
    if (!runHistoryOpen) return;
    void fetchRunHistory(workflowId);
  }, [runHistoryOpen, workflowId, historyWorkflowScope]);

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

  const getSetStateAssignments = (config: Record<string, any>) => {
    if (Array.isArray(config.assignments) && config.assignments.length > 0) {
      return config.assignments.map((assignment: any) => ({
        target: assignment?.target || '',
        expression: assignment?.expression || ''
      }));
    }
    return [{ target: config.target || '', expression: config.expression || '' }];
  };

  const updateSetStateAssignments = (
    nodeId: string,
    assignments: Array<{ target: string; expression: string }>
  ) => {
    const normalized = assignments.length > 0 ? assignments : [{ target: '', expression: '' }];
    const first = normalized[0];
    updateNodeConfig(nodeId, {
      assignments: normalized,
      target: first?.target || '',
      expression: first?.expression || ''
    });
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
    const projectScope = requireProjectId('Import workflow');
    if (!projectScope) return;
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
      const result = await createWorkflow(
        {
          name,
          description,
          draft
        },
        projectScope
      );
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
      setWorkflowName(workflow.name);
      setWorkflowDescription(workflow.description || '');
      setActiveVersionId(workflow.active_version_id || null);
      setRunHistoryRaw([]);
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
    const projectScope = requireProjectId('Create workflow');
    if (!projectScope) {
      autoCreatedRef.current = false;
      return;
    }
    setCreatingWorkflow(true);
    setStatus({ tone: 'working', label: 'Creating workflow...' });
    const name = (nameOverride || 'Untitled workflow').trim() || 'Untitled workflow';
    const draft = DEFAULT_DRAFT;
    const result = await createWorkflow(
      {
        name,
        description: '',
        draft
      },
      projectScope
    );
    if (result.error) {
      setStatus({ tone: 'error', label: 'Create failed', detail: result.error.message });
      setCreatingWorkflow(false);
      autoCreatedRef.current = false;
      return;
    }
    const workflow = result.data!;
    resetDraftToDefault();
    setWorkflowId(workflow.workflow_id);
    setWorkflowName(workflow.name);
    setWorkflowDescription(workflow.description || '');
    setActiveVersionId(workflow.active_version_id || null);
    setRunHistoryRaw([]);
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
    const projectScope = requireProjectId('Save workflow metadata');
    if (!projectScope) return;
    const name = workflowName.trim();
    if (!name) {
      setStatus({ tone: 'warn', label: 'Name is required' });
      return;
    }
    const result = await updateWorkflowMeta(
      workflowId,
      {
        name,
        description: workflowDescription || null
      },
      projectScope
    );
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

  const normalizeProjectsPayload = (items?: ProjectRecord[]): ProjectRecord[] =>
    (items || [])
      .map((item) => {
        const project_id = normalizeProjectId(item.project_id);
        if (!project_id) return null;
        const project_name =
          typeof item.project_name === 'string' && item.project_name.trim()
            ? item.project_name.trim()
            : project_id;
        return {
          ...item,
          project_id,
          project_name
        };
      })
      .filter((item): item is ProjectRecord => item !== null);

  const collectWorkflowLookupProjectScopes = async (
    preferredProjectScope?: string
  ): Promise<string[]> => {
    const seen = new Set<string>();
    const scopes: string[] = [];
    const pushScope = (value: unknown) => {
      const normalized = normalizeProjectId(value);
      if (!normalized || seen.has(normalized)) return;
      seen.add(normalized);
      scopes.push(normalized);
    };

    pushScope(preferredProjectScope);
    pushScope(activeProjectId);
    projectList.forEach((item) => pushScope(item.project_id));

    let cursor: string | undefined;
    for (let page = 0; page < PROJECT_LIST_MAX_PAGES; page += 1) {
      const projectsResult = await listProjects({
        limit: PROJECT_LIST_PAGE_LIMIT,
        cursor
      });
      if (projectsResult.error) {
        break;
      }
      const discoveredProjects = normalizeProjectsPayload(projectsResult.data?.items);
      discoveredProjects.forEach((item) => pushScope(item.project_id));
      const nextCursor = projectsResult.data?.next_cursor || undefined;
      if (!nextCursor) {
        break;
      }
      cursor = nextCursor;
    }

    return scopes;
  };

  const applyLoadedWorkflow = (workflow: WorkflowRecord) => {
    const parsed = parseDraft(workflow.draft || DEFAULT_DRAFT);
    setNodes(parsed.nodes);
    setEdges(parsed.edges);
    setVariablesSchema(parsed.variablesSchema);
    setSelectedNodeId(null);
    setWorkflowId(workflow.workflow_id);
    setWorkflowName(workflow.name);
    setWorkflowDescription(workflow.description || '');
    setActiveVersionId(workflow.active_version_id || null);
    setRunHistoryRaw([]);
    setDirty(false);
    void fetchRunHistory(workflow.workflow_id);
  };

  const loadWorkflowById = async (workflowIdToLoad: string, preferredProjectScope?: string) => {
    const targetWorkflowId = workflowIdToLoad.trim();
    if (!targetWorkflowId) {
      setStatus({ tone: 'warn', label: 'Enter workflow ID' });
      return;
    }

    setStatus({ tone: 'working', label: 'Loading workflow...' });
    const projectScopes = await collectWorkflowLookupProjectScopes(preferredProjectScope);
    if (!projectScopes.length) {
      setStatus({ tone: 'warn', label: 'No projects available' });
      return;
    }

    let lastErrorMessage = '';
    for (const projectScope of projectScopes) {
      const result = await getWorkflow(targetWorkflowId, projectScope);
      if (result.error) {
        lastErrorMessage = result.error.message || lastErrorMessage;
        continue;
      }

      const workflow = result.data!;
      const resolvedProjectScope = normalizeProjectId(workflow.project_id) || projectScope;
      if (resolvedProjectScope !== activeProjectId) {
        applyProjectId(resolvedProjectScope);
      }
      applyLoadedWorkflow(workflow);
      setStatus({ tone: 'ok', label: 'Workflow loaded' });
      return;
    }

    const fallbackMessage = `Workflow ${targetWorkflowId} was not found in ${projectScopes.length} project scopes`;
    setStatus({
      tone: 'error',
      label: 'Load failed',
      detail: lastErrorMessage || fallbackMessage
    });
  };

  const requireProjectId = (actionLabel: string): string | null => {
    if (activeProjectId) return activeProjectId;
    setStatus({ tone: 'warn', label: 'Select project first', detail: actionLabel });
    return null;
  };

  const updateUrlSearch = (updates: Record<string, string | null>, nextPath?: string) => {
    if (typeof window === 'undefined') return;
    const url = new URL(window.location.href);
    if (typeof nextPath === 'string' && nextPath.trim()) {
      url.pathname = nextPath;
    }
    Object.entries(updates).forEach(([key, value]) => {
      if (typeof value === 'string' && value.trim()) {
        url.searchParams.set(key, value.trim());
      } else {
        url.searchParams.delete(key);
      }
    });
    const search = url.searchParams.toString();
    const nextUrl = `${url.pathname}${search ? `?${search}` : ''}${url.hash}`;
    window.history.replaceState({}, '', nextUrl);
  };

  const rememberTenantSession = (value: string) => {
    setTenantSessionOptions((prev) => {
      const seen = new Set<string>();
      const next = [value, ...prev]
        .map((item) => normalizeTenantId(item))
        .filter((item) => !!item)
        .filter((item) => {
          if (seen.has(item)) return false;
          seen.add(item);
          return true;
        });
      return next;
    });
  };

  const applyViewMode = (next: ViewMode) => {
    setViewMode(next);
    updateUrlSearch(
      { view: next === 'scope' ? 'scope' : null },
      next === 'scope' ? '/scope' : '/'
    );
  };

  const applyTenantId = async (value: unknown) => {
    const normalized = normalizeTenantId(value);
    if (!normalized) {
      setStatus({ tone: 'warn', label: 'Tenant ID is required' });
      return;
    }
    const previous = tenantId;
    setTenantId(normalized);
    setTenantInput(normalized);
    rememberTenantSession(normalized);
    updateUrlSearch({ tenant_id: normalized });
    if (normalized === previous) {
      await fetchProjects();
      await fetchWorkflows();
      return;
    }
    setProjectId('');
    setProjectList([]);
    setWorkflowList([]);
    setWorkflowId('');
    setWorkflowName('');
    setWorkflowDescription('');
    setActiveVersionId(null);
    setRunHistoryRaw([]);
    resetDraftToDefault();
    setDirty(false);
    setMetaDirty(false);
    setStatus({ tone: 'working', label: `Tenant ${normalized}` });
    await fetchProjects();
  };

  const applyProjectId = (value: unknown) => {
    const normalized = normalizeProjectId(value);
    const previous = normalizedProjectId;
    const selectedProjectName = projectDisplayNameById.get(normalized);
    setProjectId(normalized);
    updateUrlSearch({ project_id: normalized || null });
    if (normalized !== previous) {
      setWorkflowId('');
      setWorkflowName('');
      setWorkflowDescription('');
      setActiveVersionId(null);
      setRunHistoryRaw([]);
      resetDraftToDefault();
      setMetaDirty(false);
      setStatus({
        tone: normalized ? 'ok' : 'warn',
        label: normalized ? selectedProjectName || 'Project selected' : 'Select project'
      });
    }
  };

  const openProjectEdit = (project: ProjectRecord) => {
    setProjectEditTarget(project);
    setProjectEditName(project.project_name || normalizeProjectId(project.project_id));
  };

  const closeProjectEdit = () => {
    setProjectEditTarget(null);
    setProjectEditName('');
  };

  const saveProjectEdit = async () => {
    if (!projectEditTarget) return;
    const projectScope = normalizeProjectId(projectEditTarget.project_id);
    const nextName = projectEditName.trim();
    if (!projectScope) {
      setStatus({ tone: 'warn', label: 'Project ID is required' });
      return;
    }
    if (!nextName) {
      setStatus({ tone: 'warn', label: 'Project name is required' });
      return;
    }
    setProjectEditLoading(true);
    const result = await updateProject(projectScope, { project_name: nextName });
    if (result.error) {
      setStatus({ tone: 'error', label: 'Project update failed', detail: result.error.message });
      setProjectEditLoading(false);
      return;
    }
    closeProjectEdit();
    await fetchProjects();
    setStatus({ tone: 'ok', label: 'Project updated', detail: projectScope });
    setProjectEditLoading(false);
  };

  const openProjectDelete = (project: ProjectRecord) => {
    setProjectDeleteTarget(project);
  };

  const closeProjectDelete = () => {
    setProjectDeleteTarget(null);
  };

  const confirmProjectDelete = async () => {
    if (!projectDeleteTarget) return;
    const projectScope = normalizeProjectId(projectDeleteTarget.project_id);
    if (!projectScope) {
      setStatus({ tone: 'warn', label: 'Project ID is required' });
      return;
    }

    setProjectDeleteLoading(true);
    const result = await deleteProject(projectScope);
    if (result.error) {
      const blockedByWorkflows =
        result.error.code === 'ERR_PROJECT_NOT_EMPTY' || /project has workflows/i.test(result.error.message || '');
      setStatus({
        tone: blockedByWorkflows ? 'warn' : 'error',
        label: blockedByWorkflows ? 'Delete blocked' : 'Project delete failed',
        detail: result.error.message
      });
      setProjectDeleteLoading(false);
      return;
    }

    if (activeProjectId === projectScope) {
      applyProjectId('');
    }
    closeProjectDelete();
    await fetchProjects();
    await fetchWorkflows();
    setStatus({ tone: 'ok', label: 'Project deleted', detail: projectScope });
    setProjectDeleteLoading(false);
  };

  const fetchProjects = async () => {
    setProjectListLoading(true);
    const allProjects: ProjectRecord[] = [];
    let cursor: string | undefined;

    for (let page = 0; page < PROJECT_LIST_MAX_PAGES; page += 1) {
      const result = await listProjects({
        limit: PROJECT_LIST_PAGE_LIMIT,
        cursor
      });
      if (result.error) {
        setProjectListLoading(false);
        setStatus({ tone: 'warn', label: 'Project list unavailable', detail: result.error.message });
        return;
      }

      allProjects.push(...normalizeProjectsPayload(result.data?.items));
      const nextCursor = result.data?.next_cursor || undefined;
      if (!nextCursor) {
        break;
      }
      cursor = nextCursor;
    }

    const projectsById = new Map<string, ProjectRecord>();
    allProjects.forEach((item) => {
      const projectScope = normalizeProjectId(item.project_id);
      if (!projectScope) return;
      projectsById.set(projectScope, {
        ...item,
        project_id: projectScope
      });
    });
    const projects = Array.from(projectsById.values()).sort((left, right) =>
      left.project_name.localeCompare(right.project_name)
    );

    setProjectList(projects);
    if (
      activeProjectId &&
      !projects.some((item) => normalizeProjectId(item.project_id) === activeProjectId)
    ) {
      applyProjectId('');
    }
    setProjectListLoading(false);
  };

  const listAllWorkflowsForProject = async (
    projectScope: string
  ): Promise<{ items: WorkflowSummary[]; errorMessage?: string }> => {
    const items: WorkflowSummary[] = [];
    let cursor: string | undefined;

    for (let page = 0; page < WORKFLOW_LIST_MAX_PAGES; page += 1) {
      const result = await listWorkflowsPage(
        {
          limit: WORKFLOW_LIST_PAGE_LIMIT,
          cursor
        },
        projectScope
      );
      if (result.error) {
        return {
          items,
          errorMessage: result.error.message || `Unable to load workflows for ${projectScope}`
        };
      }

      (result.data?.items || []).forEach((item) => {
        const workflowScope = normalizeProjectId(item.project_id) || projectScope;
        items.push({
          ...item,
          workflow_id: item.workflow_id.trim(),
          project_id: workflowScope
        });
      });

      const nextCursor = result.data?.next_cursor || undefined;
      if (!nextCursor) {
        break;
      }
      cursor = nextCursor;
    }

    return { items };
  };

  const fetchWorkflows = async () => {
    const seenScopes = new Set<string>();
    const projectScopes: string[] = [];
    const addScope = (value: unknown) => {
      const normalized = normalizeProjectId(value);
      if (!normalized || seenScopes.has(normalized)) return;
      seenScopes.add(normalized);
      projectScopes.push(normalized);
    };

    addScope(activeProjectId);
    projectList.forEach((item) => addScope(item.project_id));

    if (!projectScopes.length) {
      setWorkflowList([]);
      setWorkflowListLoading(false);
      return;
    }

    setWorkflowListLoading(true);
    const responses = await Promise.all(projectScopes.map((projectScope) => listAllWorkflowsForProject(projectScope)));

    const collected: WorkflowSummary[] = [];
    let firstErrorMessage = '';
    responses.forEach((response) => {
      if (response.errorMessage && !firstErrorMessage) {
        firstErrorMessage = response.errorMessage;
      }
      response.items.forEach((item) => {
        if (!item.workflow_id) return;
        collected.push(item);
      });
    });

    const workflowsById = new Map<string, WorkflowSummary>();
    collected.forEach((item) => {
      if (!item.workflow_id) return;
      const existing = workflowsById.get(item.workflow_id);
      if (!existing) {
        workflowsById.set(item.workflow_id, item);
        return;
      }
      const existingUpdatedAt = Date.parse(existing.updated_at || existing.created_at || '') || 0;
      const itemUpdatedAt = Date.parse(item.updated_at || item.created_at || '') || 0;
      if (itemUpdatedAt >= existingUpdatedAt) {
        workflowsById.set(item.workflow_id, item);
      }
    });

    const sorted = Array.from(workflowsById.values()).sort((left, right) => {
      const leftUpdatedAt = Date.parse(left.updated_at || left.created_at || '') || 0;
      const rightUpdatedAt = Date.parse(right.updated_at || right.created_at || '') || 0;
      if (rightUpdatedAt !== leftUpdatedAt) {
        return rightUpdatedAt - leftUpdatedAt;
      }
      return left.workflow_id.localeCompare(right.workflow_id);
    });

    if (!sorted.length && firstErrorMessage) {
      setStatus({ tone: 'error', label: 'List failed', detail: firstErrorMessage });
    } else if (firstErrorMessage) {
      setStatus({ tone: 'warn', label: 'Partial workflow list', detail: firstErrorMessage });
    }

    setWorkflowList(sorted);
    setWorkflowListLoading(false);
  };

  const fetchRunHistory = async (workflowIdToLoad?: string) => {
    const targetWorkflowId = (workflowIdToLoad || workflowId).trim();
    if (historyWorkflowScope === 'selected' && !targetWorkflowId) {
      setRunHistoryRaw([]);
      return;
    }
    setRunHistoryLoading(true);
    const result = await listRuns({
      workflowId: historyWorkflowScope === 'selected' ? targetWorkflowId : undefined,
      limit: historyWorkflowScope === 'selected' ? 100 : 200
    });
    if (result.error) {
      setStatus({ tone: 'error', label: 'Run history failed', detail: result.error.message });
      setRunHistoryLoading(false);
      return;
    }
    const historyItems = result.data?.items || [];
    setRunHistoryRaw(historyItems);
    setRunHistoryLoading(false);
  };

  const handleSaveDraft = async () => {
    if (!workflowId) return;
    const projectScope = requireProjectId('Save draft');
    if (!projectScope) return;
    setStatus({ tone: 'working', label: 'Saving draft...' });
    const draft = buildDraft(nodes, edges, variablesSchema);
    const result = await updateDraft(workflowId, draft, projectScope);
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
    const projectScope = requireProjectId('Publish workflow');
    if (!projectScope) return null;
    const errors = issues.filter((issue) => issue.level === 'error');
    if (errors.length) {
      setStatus({ tone: 'error', label: 'Fix validation errors before publishing' });
      return null;
    }
    if (dirty) {
      await handleSaveDraft();
    }
    setStatus({ tone: 'working', label: 'Publishing...' });
    const result = await publishWorkflow(workflowId, projectScope);
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
    const projectScope = requireProjectId('Rollback workflow');
    if (!projectScope) return;
    setStatus({ tone: 'working', label: 'Rolling back...' });
    const result = await rollbackWorkflow(workflowId, projectScope);
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
    const projectScope = requireProjectId('Start run');
    if (!projectScope) return;
    setStatus({ tone: 'working', label: 'Starting run...' });
    const result = await startRun(
      workflowId,
      {
        inputs: {},
        version_id: activeVersionId || undefined,
        mode: runMode
      },
      projectScope
    );
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
    if (!workflowId && !activeProjectId) {
      setStatus({ tone: 'warn', label: 'Select project or workflow first' });
      return;
    }
    if (!workflowId && historyWorkflowScope === 'selected') {
      setHistoryWorkflowScope('all');
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
    if (projectId.trim()) {
      url.searchParams.set('project_id', projectId.trim());
    }
    url.searchParams.set('auto', '1');
    url.searchParams.set('auto_start', '1');
    return url.toString();
  }, [workflowId, activeVersionId, projectId]);

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

  const setCanvasScale = (nextScale: number) => {
    scaleRef.current = nextScale;
    setScale(nextScale);
  };

  const setCanvasOffset = (nextOffset: { x: number; y: number }) => {
    offsetRef.current = nextOffset;
    setOffset(nextOffset);
  };

  const toCanvasPoint = (clientX: number, clientY: number) => {
    const rect = canvasRef.current?.getBoundingClientRect();
    if (!rect) return null;
    return { x: clientX - rect.left, y: clientY - rect.top };
  };

  const zoomCanvas = (nextScale: number, anchorClient?: { x: number; y: number }) => {
    const previousScale = scaleRef.current;
    const clampedScale = clampCanvasScale(nextScale);
    if (Math.abs(clampedScale - previousScale) < 0.0001) return;

    if (anchorClient) {
      const anchor = toCanvasPoint(anchorClient.x, anchorClient.y);
      if (anchor) {
        const nextOffset = computeZoomedOffset({
          anchor,
          offset: offsetRef.current,
          previousScale,
          nextScale: clampedScale
        });
        setCanvasOffset(nextOffset);
      }
    }

    setCanvasScale(clampedScale);
  };

  const zoomCanvasFromCenter = (nextScale: number) => {
    const rect = canvasRef.current?.getBoundingClientRect();
    if (!rect) {
      zoomCanvas(nextScale);
      return;
    }
    zoomCanvas(nextScale, { x: rect.left + rect.width / 2, y: rect.top + rect.height / 2 });
  };

  const handleZoomOut = () => {
    zoomCanvasFromCenter(scaleRef.current - CANVAS_SCALE_STEP);
  };

  const handleZoomIn = () => {
    zoomCanvasFromCenter(scaleRef.current + CANVAS_SCALE_STEP);
  };

  const handleZoomReset = () => {
    zoomCanvasFromCenter(1);
  };

  const handlePointerMove = (event: ReactPointerEvent<HTMLDivElement>) => {
    const rect = canvasRef.current?.getBoundingClientRect();
    if (!rect) return;
    const currentScale = scaleRef.current;
    const currentOffset = offsetRef.current;
    const x = (event.clientX - rect.left - currentOffset.x) / currentScale;
    const y = (event.clientY - rect.top - currentOffset.y) / currentScale;
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
      setCanvasOffset({ x: panStart.ox + dx, y: panStart.oy + dy });
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
    zoomCanvas(scaleRef.current - event.deltaY * CANVAS_WHEEL_ZOOM_SENSITIVITY, {
      x: event.clientX,
      y: event.clientY
    });
  };

  const beginDragNode = (event: ReactPointerEvent, nodeId: string) => {
    event.stopPropagation();
    const rect = canvasRef.current?.getBoundingClientRect();
    if (!rect) return;
    const node = nodes.find((item) => item.id === nodeId);
    if (!node) return;
    const currentScale = scaleRef.current;
    const currentOffset = offsetRef.current;
    const x = (event.clientX - rect.left - currentOffset.x) / currentScale;
    const y = (event.clientY - rect.top - currentOffset.y) / currentScale;
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
    if (selectedNodeId) {
      setSelectedNodeId(null);
    }
    setPanning(true);
    setPanStart({ x: event.clientX, y: event.clientY, ox: offsetRef.current.x, oy: offsetRef.current.y });
  };

  const renderInspector = () => {
    if (!selectedNode) {
      return (
        <Stack gap="sm">
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
          {chatkitUrl && (
            <Group align="end" gap="xs" wrap="nowrap">
              <TextInput
                label="Chat link"
                value={chatkitUrl}
                readOnly
                style={{ flex: 1 }}
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
          <Text size="xs" c="dimmed">
            Select a node to edit its configuration.
          </Text>
        </Stack>
      );
    }

    const config = selectedNode.config || defaultNodeConfig(selectedNode.type);
    const setStateAssignments = selectedNode.type === 'set_state' ? getSetStateAssignments(config) : [];
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
            <Text size="xs" c="dimmed">
              Assignments execute in order and can reference previous state updates.
            </Text>
            {setStateAssignments.map((assignment, index) => (
              <Card key={`set-assignment-${index}`} withBorder radius="md" padding="sm">
                <Stack gap="xs">
                  <TextInput
                    label={`Target ${index + 1}`}
                    value={assignment.target}
                    onChange={(event) => {
                      const next = [...setStateAssignments];
                      next[index] = { ...next[index], target: event.currentTarget.value };
                      updateSetStateAssignments(selectedNode.id, next);
                    }}
                  />
                  <TextInput
                    label={`Expression ${index + 1}`}
                    value={assignment.expression}
                    onChange={(event) => {
                      const next = [...setStateAssignments];
                      next[index] = { ...next[index], expression: event.currentTarget.value };
                      updateSetStateAssignments(selectedNode.id, next);
                    }}
                  />
                  <Group justify="flex-end">
                    <Button
                      size="xs"
                      variant="light"
                      color="red"
                      disabled={setStateAssignments.length <= 1}
                      onClick={() => {
                        const next = setStateAssignments.filter(
                          (_, assignmentIndex) => assignmentIndex !== index
                        );
                        updateSetStateAssignments(selectedNode.id, next);
                      }}
                    >
                      Remove assignment
                    </Button>
                  </Group>
                </Stack>
              </Card>
            ))}
            <Button
              size="xs"
              variant="light"
              onClick={() => {
                const next = [...setStateAssignments, { target: '', expression: '' }];
                updateSetStateAssignments(selectedNode.id, next);
              }}
            >
              Add assignment
            </Button>
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
      header={{ height: 86 }}
      navbar={viewMode === 'builder' ? { width: 300, breakpoint: 'sm' } : undefined}
      aside={viewMode === 'builder' ? { width: 360, breakpoint: 'sm' } : undefined}
      padding="md"
    >
      <AppShell.Header className="header-shell">
        <Group h="100%" px="lg" justify="space-between" wrap="nowrap" className="header">
          <Group gap="sm" wrap="nowrap" className="header-brand">
            <Badge color="brand" variant="filled">
              {viewMode === 'builder' ? 'Builder' : 'Explorer'}
            </Badge>
            <Stack gap={0}>
              <Title order={4}>{viewMode === 'builder' ? 'Workflow Studio' : 'Tenant Explorer'}</Title>
              <Text size="xs" c="dimmed">
                {viewMode === 'builder'
                  ? workflowId
                    ? `Workflow ${workflowId}`
                    : 'No workflow loaded'
                  : `Tenant ${tenantId}`}
              </Text>
            </Stack>
          </Group>
          {viewMode === 'builder' ? (
            <Box className="header-controls-wrap">
              <Group gap="xs" wrap="nowrap" className="header-controls">
                <Badge variant="outline">Project {activeProjectId || '-'}</Badge>
                <Badge variant="outline">Workflow {workflowId || '-'}</Badge>
                <Button variant="default" size="sm" onClick={() => applyViewMode('scope')}>
                  Back to projects
                </Button>
                <Button variant="outline" size="sm" onClick={handleNewWorkflow} disabled={creatingWorkflow}>
                  New
                </Button>
                <Divider orientation="vertical" />
                <Button variant="default" size="sm" onClick={handleSaveDraft}>
                  Save
                </Button>
                <Button variant="default" size="sm" onClick={handleAutoLayout} data-testid="auto-layout">
                  Auto layout
                </Button>
                <Button variant="filled" size="sm" onClick={handlePublish}>
                  Publish
                </Button>
                <Select
                  className="header-runmode-select"
                  value={runMode}
                  onChange={(value) => setRunMode((value as 'live' | 'test') || 'live')}
                  data={[
                    { value: 'live', label: 'Live' },
                    { value: 'test', label: 'Test' }
                  ]}
                  size="sm"
                  w={112}
                />
                <Button color="teal" variant="filled" size="sm" onClick={handleRun}>
                  Run
                </Button>
                <Button variant="default" size="sm" onClick={handleOpenRunHistory}>
                  History
                </Button>
                <Button
                  variant="default"
                  size="sm"
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
                    <Button variant="default" size="sm" onClick={() => setMoreMenuOpen((prev) => !prev)}>
                      More
                    </Button>
                  </Menu.Target>
                  <Menu.Dropdown>
                    <Menu.Item
                      onClick={() => {
                        setMoreMenuOpen(false);
                        void fetchProjects();
                        void fetchWorkflows();
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
            </Box>
          ) : (
            <Group gap="xs" wrap="nowrap">
              <Badge variant="outline">Project {activeProjectId || '-'}</Badge>
              <Badge variant="outline">Workflow {workflowId || '-'}</Badge>
              <Button
                variant="default"
                size="sm"
                onClick={() => {
                  void fetchProjects();
                  void fetchWorkflows();
                }}
              >
                Refresh
              </Button>
              <Button variant="filled" size="sm" onClick={() => applyViewMode('builder')}>
                Open Studio
              </Button>
            </Group>
          )}
        </Group>
      </AppShell.Header>

      {viewMode === 'builder' && (
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
      )}

      {viewMode === 'builder' && (
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
      )}

      <AppShell.Main>
        {viewMode === 'builder' ? (
          <Stack gap="md">
          <Drawer
            opened={chatOpen}
            onClose={() => setChatOpen(false)}
            position="right"
            size={520}
            title="Chat"
            overlayProps={{ opacity: 0.2, blur: 2 }}
          >
            <Stack gap="xs" style={{ height: 'calc(100vh - 160px)' }}>
              <Group justify="space-between" align="center">
                <Text size="xs" c="dimmed">
                  Workflow {workflowId || '—'}
                </Text>
                <Text size="xs" c="dimmed">
                  Project {projectId.trim() || '—'}
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
          <Group justify="flex-end" align="center" gap="xs">
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
          <Box
            className="canvas"
            ref={canvasRef}
            onPointerMove={handlePointerMove}
            onPointerUp={handlePointerUp}
            onPointerLeave={handlePointerUp}
            onPointerDown={beginPan}
            onWheel={handleWheel}
          >
            <Box className="canvas-zoom-controls" onPointerDown={(event) => event.stopPropagation()}>
              <Group gap={6} wrap="nowrap">
                <ActionIcon size="sm" radius="xl" variant="light" aria-label="Zoom out" onClick={handleZoomOut}>
                  -
                </ActionIcon>
                <Text size="xs" fw={600} className="canvas-zoom-value">
                  {Math.round(scale * 100)}%
                </Text>
                <ActionIcon size="sm" radius="xl" variant="light" aria-label="Zoom in" onClick={handleZoomIn}>
                  +
                </ActionIcon>
                <Button size="xs" variant="light" onClick={handleZoomReset}>
                  Reset
                </Button>
              </Group>
            </Box>
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
        ) : (
          <Stack gap="md">
            <Card withBorder radius="md">
              <Group justify="space-between" align="flex-start" wrap="wrap">
                <Stack gap={2}>
                  <Text fw={600}>Scope Selection</Text>
                  <Text size="sm" c="dimmed">
                    Select tenant, project, and workflow before opening Workflow Studio.
                  </Text>
                </Stack>
                <Group gap="xs" wrap="wrap">
                  <Badge variant="outline">Tenant {tenantId}</Badge>
                  <Badge variant="outline">Project {activeProjectId || '-'}</Badge>
                  <Badge variant="outline">Workflow {workflowId || '-'}</Badge>
                </Group>
              </Group>
            </Card>

            <SimpleGrid cols={{ base: 1, md: 3 }} spacing="md">
              <Card withBorder radius="md" padding="md">
                <Stack gap="sm">
                  <Text fw={600}>Tenant</Text>
                  <TextInput
                    label="Tenant ID"
                    placeholder="local"
                    value={tenantInput}
                    onChange={(event) => setTenantInput(event.currentTarget.value)}
                    onKeyDown={(event) => {
                      if (event.key === 'Enter') {
                        void applyTenantId(tenantInput);
                      }
                    }}
                  />
                  <Group gap="xs" wrap="wrap">
                    <Button size="sm" onClick={() => void applyTenantId(tenantInput)}>
                      Load tenant
                    </Button>
                    <Button
                      size="sm"
                      variant="light"
                      onClick={() => {
                        void fetchProjects();
                        void fetchWorkflows();
                      }}
                    >
                      Refresh
                    </Button>
                  </Group>
                  <Stack gap={6}>
                    <Text size="xs" c="dimmed">
                      Session tenants
                    </Text>
                    <Group gap={6} wrap="wrap">
                      {tenantSessionOptions.map((item) => (
                        <Badge
                          key={item}
                          variant={item === tenantId ? 'filled' : 'light'}
                          style={{ cursor: 'pointer' }}
                          onClick={() => {
                            void applyTenantId(item);
                          }}
                        >
                          {item}
                        </Badge>
                      ))}
                    </Group>
                  </Stack>
                </Stack>
              </Card>

              <Card withBorder radius="md" padding="md">
                <Stack gap="sm">
                  <Group justify="space-between" align="center">
                    <Text fw={600}>Projects</Text>
                    <Badge color="gray" variant="light">
                      {projectList.length}
                    </Badge>
                  </Group>
                  <ScrollArea h={420}>
                    <Stack gap="xs">
                      {projectListLoading ? (
                        <Text size="sm" c="dimmed">
                          Loading projects...
                        </Text>
                      ) : projectList.length === 0 ? (
                        <Text size="sm" c="dimmed">
                          No projects in tenant.
                        </Text>
                      ) : (
                        projectList.map((item) => {
                          const projectScope = normalizeProjectId(item.project_id);
                          const selected = projectScope === activeProjectId;
                          return (
                            <Card
                              key={projectScope}
                              withBorder
                              radius="sm"
                              padding="sm"
                              style={{ cursor: 'pointer' }}
                              onClick={() => applyProjectId(projectScope)}
                            >
                              <Group justify="space-between" align="flex-start" wrap="nowrap">
                                <Stack gap={0} style={{ flex: 1 }}>
                                  <Text fw={selected ? 700 : 600}>{item.project_name}</Text>
                                  <Text size="xs" c="dimmed">
                                    {projectScope}
                                  </Text>
                                </Stack>
                                <Stack gap={6} align="flex-end">
                                  {selected && <Badge color="teal">Selected</Badge>}
                                  <Group gap={6} wrap="nowrap">
                                    <Button
                                      size="xs"
                                      variant="light"
                                      onClick={(event) => {
                                        event.stopPropagation();
                                        openProjectEdit(item);
                                      }}
                                      data-testid={`edit-project-${projectScope}`}
                                    >
                                      Edit
                                    </Button>
                                    <Button
                                      size="xs"
                                      variant="light"
                                      color="red"
                                      onClick={(event) => {
                                        event.stopPropagation();
                                        openProjectDelete(item);
                                      }}
                                      data-testid={`delete-project-${projectScope}`}
                                    >
                                      Delete
                                    </Button>
                                  </Group>
                                </Stack>
                              </Group>
                            </Card>
                          );
                        })
                      )}
                    </Stack>
                  </ScrollArea>
                </Stack>
              </Card>

              <Card withBorder radius="md" padding="md">
                <Stack gap="sm">
                  <Group justify="space-between" align="center">
                    <Text fw={600}>Workflows</Text>
                    <Badge color="gray" variant="light">
                      {workflowsForActiveProject.length}
                    </Badge>
                  </Group>
                  <ScrollArea h={420}>
                    <Stack gap="xs">
                      {workflowListLoading ? (
                        <Text size="sm" c="dimmed">
                          Loading workflows...
                        </Text>
                      ) : workflowsForActiveProject.length === 0 ? (
                        <Text size="sm" c="dimmed">
                          {activeProjectId ? 'No workflows in project.' : 'Select a project first.'}
                        </Text>
                      ) : (
                        workflowsForActiveProject.map((item) => {
                          const workflowScope = normalizeProjectId(item.project_id);
                          const selected = item.workflow_id === workflowId;
                          return (
                            <Card
                              key={item.workflow_id}
                              withBorder
                              radius="sm"
                              padding="sm"
                              style={{ cursor: 'pointer' }}
                              onClick={() => {
                                void loadWorkflowById(item.workflow_id, workflowScope);
                                applyViewMode('builder');
                              }}
                            >
                              <Stack gap={2}>
                                <Text fw={selected ? 700 : 600}>{item.name}</Text>
                                <Text size="xs" c="dimmed">
                                  {item.workflow_id}
                                </Text>
                                <Text size="xs" c="dimmed">
                                  Project {workflowScope || '-'}
                                </Text>
                              </Stack>
                            </Card>
                          );
                        })
                      )}
                    </Stack>
                  </ScrollArea>
                </Stack>
              </Card>
            </SimpleGrid>
          </Stack>
        )}
      </AppShell.Main>

      <Modal opened={!!projectEditTarget} onClose={closeProjectEdit} title="Edit project" centered size="sm">
        <Stack gap="sm">
          <TextInput
            label="Project name"
            value={projectEditName}
            onChange={(event) => setProjectEditName(event.currentTarget.value)}
            data-testid="edit-project-name-input"
          />
          <Group justify="flex-end" gap="xs">
            <Button variant="default" onClick={closeProjectEdit} disabled={projectEditLoading}>
              Cancel
            </Button>
            <Button
              onClick={() => {
                void saveProjectEdit();
              }}
              loading={projectEditLoading}
              data-testid="edit-project-confirm"
            >
              Save
            </Button>
          </Group>
        </Stack>
      </Modal>

      <Modal
        opened={!!projectDeleteTarget}
        onClose={closeProjectDelete}
        title="Delete project?"
        centered
        size="sm"
      >
        <Stack gap="sm">
          <Text size="sm">
            Delete project <b>{projectDeleteTarget?.project_name || projectDeleteTarget?.project_id}</b>?
          </Text>
          <Text size="sm" c="dimmed">
            This action cannot be undone. Project with workflows cannot be deleted.
          </Text>
          <Group justify="flex-end" gap="xs">
            <Button variant="default" onClick={closeProjectDelete} disabled={projectDeleteLoading}>
              Cancel
            </Button>
            <Button
              color="red"
              onClick={() => {
                void confirmProjectDelete();
              }}
              loading={projectDeleteLoading}
              data-testid="delete-project-confirm"
            >
              Delete
            </Button>
          </Group>
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
              onClick={() => void fetchRunHistory(workflowId)}
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
                  onChange={(value) => setHistoryWorkflowScope((value as HistoryWorkflowScope) || 'selected')}
                />
                <Select
                  label="Project scope"
                  value={historyProjectScope}
                  data={[
                    { value: 'active', label: 'Active project' },
                    { value: 'all', label: 'All projects' }
                  ]}
                  allowDeselect={false}
                  onChange={(value) => setHistoryProjectScope((value as HistoryProjectScope) || 'active')}
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
