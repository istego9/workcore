import {
  Anchor,
  Badge,
  Button,
  Card,
  Divider,
  Drawer,
  Group,
  ScrollArea,
  SimpleGrid,
  Stack,
  Text,
} from '@mantine/core';
import { useEffect, useMemo, useState } from 'react';
import {
  API_BASE,
  getProjectWorkflowDefinition,
  getRun,
  listProjects,
  listRuns,
  listWorkflowVersions,
  orchestratorEvalReplay,
  startRun,
  updateProject,
  upsertProjectWorkflowDefinition,
  type OrchestratorEvalReplayCase,
  type ProjectRecord,
  type ProjectWorkflowDefinitionRecord,
  type RunRecord,
} from '../api';
import type { ValidationIssue, WorkflowDraft, WorkflowVersion } from '../builder/types';
import { getProjectDefaultChatWorkflowId } from '../project-chat-settings';
import { emitReleasePipelineLog } from './logging';
import {
  buildReleaseReport,
  buildReleaseReportFilename,
  computeDraftFingerprint,
  evaluatePublishGates,
  normalizeSimulationResult,
  normalizeSmokeResult,
  resolveReleaseStageStates,
  summarizeFailureTrend,
  summarizeValidation,
  summarizeWorkflowDiff,
  type ReleaseReport,
  type SimulationExecutionResult,
  type SmokeResultSummary,
} from './model';
import { WorkflowBindingPanel } from './WorkflowBindingPanel';
import { WorkflowReleaseReport } from './WorkflowReleaseReport';
import { WorkflowSimulationPanel } from './WorkflowSimulationPanel';
import { WorkflowSmokeRunner } from './WorkflowSmokeRunner';
import { WorkflowValidationGate } from './WorkflowValidationGate';
import { WorkflowVersionDiff } from './WorkflowVersionDiff';

type StatusTone = 'idle' | 'ok' | 'warn' | 'error' | 'working';

type StatusUpdate = {
  tone: StatusTone;
  label: string;
  detail?: string;
};

type WorkflowReleasePipelineProps = {
  opened: boolean;
  onClose: () => void;
  tenantId: string;
  projectId: string;
  workflowId: string;
  workflowName: string;
  workflowDescription: string;
  activeVersionId: string | null;
  draft: WorkflowDraft;
  validationIssues: ValidationIssue[];
  activeProject: ProjectRecord | null;
  onFocusNode: (nodeId: string) => void;
  onPublish: () => Promise<string | null>;
  onProjectsRefreshed: () => Promise<void>;
  onWorkflowsRefreshed: () => Promise<void>;
  onStatus: (status: StatusUpdate) => void;
  onOpenRunDebug: (runId: string) => void;
};

type SimulationSource = 'canned' | 'last_good' | 'manual';

type LastSuccessfulReleasePath = {
  timestamp: string;
  candidate_version_id: string;
  published_version_id: string | null;
  smoke_run_id: string | null;
};

type RoutingReadbackStatus = 'checking' | 'bound' | 'not_bound' | 'readback_failed';

type BoundProjectUsage = {
  project_id: string;
  project_name: string;
};

const FINAL_RUN_STATUSES = new Set(['COMPLETED', 'FAILED', 'CANCELLED']);
const LAST_SUCCESS_KEY_PREFIX = 'workcore.release_pipeline.last_success';

const wait = async (ms: number) =>
  new Promise<void>((resolve) => {
    window.setTimeout(() => resolve(), ms);
  });

const asRecord = (value: unknown): Record<string, any> =>
  typeof value === 'object' && value !== null && !Array.isArray(value) ? (value as Record<string, any>) : {};

const runStatusBadgeColor = (status: string) => {
  if (status === 'COMPLETED') return 'teal';
  if (status === 'FAILED') return 'red';
  if (status === 'CANCELLED') return 'gray';
  if (status === 'WAITING_FOR_INPUT') return 'yellow';
  return 'blue';
};

const formatPercent = (value: number) => `${Math.round(value * 100)}%`;

const formatDate = (value: string | undefined | null) => {
  if (!value) return '';
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toLocaleString();
};

const buildCannedCases = (workflowId: string): OrchestratorEvalReplayCase[] => {
  const target = workflowId.trim();
  if (!target) return [];
  return [
    {
      case_id: 'sample_start',
      message_text: 'start',
      expected_workflow_id: target,
    },
    {
      case_id: 'sample_help',
      message_text: 'help me with this workflow',
      expected_workflow_id: target,
    },
    {
      case_id: 'sample_continue',
      message_text: 'continue the current flow',
      expected_workflow_id: target,
      active_workflow_id: target,
    },
  ];
};

const extractRunMessageText = (run: RunRecord): string => {
  const metadata = asRecord(run.metadata);
  const metadataMessage = metadata.message;
  const metadataMessageText =
    typeof metadata.message_text === 'string'
      ? metadata.message_text
      : typeof metadataMessage === 'string'
        ? metadataMessage
        : typeof asRecord(metadataMessage).text === 'string'
          ? String(asRecord(metadataMessage).text)
          : '';
  if (metadataMessageText.trim()) return metadataMessageText.trim();

  const inputs = asRecord(run.inputs);
  const inputCandidates = [inputs.message_text, inputs.message, inputs.prompt, inputs.text];
  for (const candidate of inputCandidates) {
    if (typeof candidate === 'string' && candidate.trim()) {
      return candidate.trim();
    }
  }
  return '';
};

const buildLastKnownGoodCases = (runs: RunRecord[], workflowId: string): OrchestratorEvalReplayCase[] => {
  const seen = new Set<string>();
  const cases: OrchestratorEvalReplayCase[] = [];
  runs
    .filter((run) => run.status === 'COMPLETED')
    .forEach((run) => {
      const text = extractRunMessageText(run);
      if (!text || seen.has(text)) return;
      seen.add(text);
      cases.push({
        case_id: `last_good_${cases.length + 1}`,
        message_text: text,
        expected_workflow_id: workflowId,
      });
    });
  return cases.slice(0, 12);
};

const parseManualCases = (raw: string): { cases: OrchestratorEvalReplayCase[]; error: string | null } => {
  try {
    const parsed = JSON.parse(raw);
    const rawCases = Array.isArray(parsed) ? parsed : Array.isArray(parsed?.cases) ? parsed.cases : null;
    if (!rawCases) {
      return { cases: [], error: 'Manual payload must be an array or { "cases": [] }' };
    }
    const cases = rawCases
      .map((item) => asRecord(item))
      .map((item, index) => ({
        case_id:
          typeof item.case_id === 'string' && item.case_id.trim()
            ? item.case_id.trim()
            : `manual_${index + 1}`,
        message_text:
          typeof item.message_text === 'string' && item.message_text.trim() ? item.message_text.trim() : '',
        active_workflow_id:
          typeof item.active_workflow_id === 'string' ? item.active_workflow_id.trim() : undefined,
        expected_action: typeof item.expected_action === 'string' ? item.expected_action.trim() : undefined,
        expected_workflow_id:
          typeof item.expected_workflow_id === 'string' ? item.expected_workflow_id.trim() : undefined,
      }))
      .filter((item) => item.message_text);
    if (!cases.length) {
      return { cases: [], error: 'Manual cases are empty or missing message_text' };
    }
    return { cases, error: null };
  } catch (error: any) {
    return { cases: [], error: error?.message || 'Invalid JSON' };
  }
};

const localStorageKey = (tenantId: string, projectId: string, workflowId: string) =>
  `${LAST_SUCCESS_KEY_PREFIX}.${tenantId}.${projectId}.${workflowId}`;

const downloadJson = (payload: unknown, filename: string) => {
  const blob = new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json' });
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
};

export function WorkflowReleasePipeline({
  opened,
  onClose,
  tenantId,
  projectId,
  workflowId,
  workflowName,
  workflowDescription,
  activeVersionId,
  draft,
  validationIssues,
  activeProject,
  onFocusNode,
  onPublish,
  onProjectsRefreshed,
  onWorkflowsRefreshed,
  onStatus,
  onOpenRunDebug,
}: WorkflowReleasePipelineProps) {
  const [versionsLoading, setVersionsLoading] = useState(false);
  const [versions, setVersions] = useState<WorkflowVersion[]>([]);
  const [runsLoading, setRunsLoading] = useState(false);
  const [recentRuns, setRecentRuns] = useState<RunRecord[]>([]);
  const [validationRunAt, setValidationRunAt] = useState<string | null>(null);
  const [simulationSource, setSimulationSource] = useState<SimulationSource>('canned');
  const [manualCasesJson, setManualCasesJson] = useState<string>('[]');
  const [simulationRunning, setSimulationRunning] = useState(false);
  const [simulationResult, setSimulationResult] = useState<SimulationExecutionResult | null>(null);
  const [simulationError, setSimulationError] = useState<string | null>(null);
  const [publishedInCycleVersionId, setPublishedInCycleVersionId] = useState<string | null>(null);
  const [chatBindLoading, setChatBindLoading] = useState(false);
  const [routingBindLoading, setRoutingBindLoading] = useState(false);
  const [routingReadbackStatus, setRoutingReadbackStatus] = useState<RoutingReadbackStatus>('checking');
  const [routingDefinitionRecord, setRoutingDefinitionRecord] = useState<ProjectWorkflowDefinitionRecord | null>(null);
  const [smokeRunning, setSmokeRunning] = useState(false);
  const [smokeResult, setSmokeResult] = useState<SmokeResultSummary | null>(null);
  const [smokeRun, setSmokeRun] = useState<RunRecord | null>(null);
  const [openedAt, setOpenedAt] = useState<string | null>(null);
  const [stageTimestamps, setStageTimestamps] = useState<Record<string, string>>({});
  const [lastSuccessPath, setLastSuccessPath] = useState<LastSuccessfulReleasePath | null>(null);
  const [projectsUsageLoading, setProjectsUsageLoading] = useState(false);
  const [projectsUsingWorkflow, setProjectsUsingWorkflow] = useState<BoundProjectUsage[]>([]);

  const validation = useMemo(() => summarizeValidation(validationIssues), [validationIssues]);
  const cannedCases = useMemo(() => buildCannedCases(workflowId), [workflowId]);
  const lastGoodCases = useMemo(
    () => buildLastKnownGoodCases(recentRuns, workflowId),
    [recentRuns, workflowId]
  );
  const manualParse = useMemo(() => parseManualCases(manualCasesJson), [manualCasesJson]);
  const selectedCases = useMemo(() => {
    if (simulationSource === 'manual') return manualParse.cases;
    if (simulationSource === 'last_good') return lastGoodCases.length ? lastGoodCases : cannedCases;
    return cannedCases;
  }, [cannedCases, lastGoodCases, manualParse.cases, simulationSource]);

  const publishedVersion = useMemo(
    () => versions.find((version) => version.version_id === activeVersionId) || null,
    [versions, activeVersionId]
  );
  const diffSummary = useMemo(
    () =>
      summarizeWorkflowDiff(
        draft,
        publishedVersion?.content || null,
        publishedVersion?.version_id || null
      ),
    [draft, publishedVersion]
  );
  const candidateVersionId = useMemo(
    () => `draft_${computeDraftFingerprint(draft)}`,
    [draft]
  );
  const releasePublishedVersionId = publishedInCycleVersionId || activeVersionId || null;
  const publishStagePassed =
    Boolean(publishedInCycleVersionId) ||
    (Boolean(activeVersionId) && Boolean(diffSummary) && !diffSummary.has_changes);
  const chatBound = getProjectDefaultChatWorkflowId(activeProject) === workflowId;
  const observedDirectRuns = useMemo(
    () =>
      recentRuns.filter(
        (run) => run.workflow_id === workflowId && (run.project_id || '') === projectId
      ).length,
    [recentRuns, workflowId, projectId]
  );
  const routingBound = routingReadbackStatus === 'bound';
  const bindCompleted = chatBound || routingBound;
  const publishGates = useMemo(
    () => evaluatePublishGates({ validation, simulation: simulationResult, diff: diffSummary }),
    [validation, simulationResult, diffSummary]
  );
  const stageStates = useMemo(
    () =>
      resolveReleaseStageStates({
        validation,
        simulation: simulationResult,
        diff: diffSummary,
        published: publishStagePassed,
        bind_completed: bindCompleted,
        smoke: smokeResult,
      }),
    [validation, simulationResult, diffSummary, publishStagePassed, bindCompleted, smokeResult]
  );

  const releaseVersionRuns = useMemo(() => {
    if (!releasePublishedVersionId) return [];
    return recentRuns
      .filter(
        (run) =>
          run.version_id === releasePublishedVersionId && (run.project_id || '') === projectId
      )
      .slice(0, 12);
  }, [recentRuns, releasePublishedVersionId, projectId]);
  const failureTrend = useMemo(() => summarizeFailureTrend(releaseVersionRuns), [releaseVersionRuns]);
  const runDetailsUrl = smokeResult?.run_id
    ? `${API_BASE}/runs/${encodeURIComponent(smokeResult.run_id)}`
    : null;
  const integrationLogsUrl = smokeResult?.run_id
    ? `${API_BASE}/runs/${encodeURIComponent(smokeResult.run_id)}/ledger`
    : null;

  const reportBase = useMemo<ReleaseReport>(
    () =>
      buildReleaseReport({
        workflow_id: workflowId,
        tenant_id: tenantId || null,
        project_id: projectId || null,
        candidate_version_id: publishedInCycleVersionId || candidateVersionId,
        published_version_id: releasePublishedVersionId,
        validation,
        simulation: simulationResult,
        diff: diffSummary,
        bind_targets: {
          project_default_chat_workflow_id: chatBound ? workflowId : null,
          routing_definition_registered: routingBound,
          observed_direct_runs: observedDirectRuns,
        },
        smoke: smokeResult,
        operator_timestamps: {
          opened_at: openedAt || '',
          ...stageTimestamps,
        },
      }),
    [
      workflowId,
      tenantId,
      projectId,
      publishedInCycleVersionId,
      candidateVersionId,
      releasePublishedVersionId,
      validation,
      simulationResult,
      diffSummary,
      chatBound,
      routingBound,
      observedDirectRuns,
      smokeResult,
      openedAt,
      stageTimestamps,
    ]
  );

  const updateStageTimestamp = (stage: string) => {
    const timestamp = new Date().toISOString();
    setStageTimestamps((previous) => ({ ...previous, [stage]: timestamp }));
  };

  const emitWithContext = (
    eventType:
      | 'release_pipeline_opened'
      | 'validation_rerun'
      | 'simulation_started'
      | 'simulation_completed'
      | 'publish_initiated'
      | 'publish_completed'
      | 'bind_updated'
      | 'smoke_started'
      | 'smoke_completed'
      | 'release_report_exported',
    details?: Record<string, unknown>
  ) => {
    emitReleasePipelineLog(
      eventType,
      {
        tenant_id: tenantId || null,
        project_id: projectId || null,
        workflow_id: workflowId || null,
        candidate_version_id: publishedInCycleVersionId || candidateVersionId,
        published_version_id: releasePublishedVersionId,
        correlation_id: smokeResult?.correlation_id || null,
      },
      details
    );
  };

  const fetchVersions = async () => {
    if (!workflowId || !projectId) {
      setVersions([]);
      return;
    }
    setVersionsLoading(true);
    const result = await listWorkflowVersions(workflowId, { limit: 50 }, projectId);
    if (result.error) {
      onStatus({ tone: 'warn', label: 'Version list unavailable', detail: result.error.message });
      setVersionsLoading(false);
      return;
    }
    setVersions(result.data?.items || []);
    setVersionsLoading(false);
  };

  const fetchRoutingReadback = async (options?: { silent?: boolean }): Promise<RoutingReadbackStatus> => {
    if (!workflowId || !projectId) {
      setRoutingDefinitionRecord(null);
      setRoutingReadbackStatus('not_bound');
      return 'not_bound';
    }
    setRoutingReadbackStatus('checking');
    const result = await getProjectWorkflowDefinition(projectId, workflowId);
    if (result.error) {
      if (result.error.code === 'ERR_WORKFLOW_DEFINITION_NOT_FOUND') {
        setRoutingDefinitionRecord(null);
        setRoutingReadbackStatus('not_bound');
        return 'not_bound';
      }
      setRoutingDefinitionRecord(null);
      setRoutingReadbackStatus('readback_failed');
      if (!options?.silent) {
        onStatus({
          tone: 'warn',
          label: 'Routing readback unavailable',
          detail: result.error.message,
        });
      }
      return 'readback_failed';
    }
    setRoutingDefinitionRecord(result.data || null);
    setRoutingReadbackStatus('bound');
    return 'bound';
  };

  const fetchRuns = async () => {
    if (!workflowId) {
      setRecentRuns([]);
      return;
    }
    setRunsLoading(true);
    const result = await listRuns({ workflowId, limit: 120 });
    if (result.error) {
      onStatus({ tone: 'warn', label: 'Run list unavailable', detail: result.error.message });
      setRunsLoading(false);
      return;
    }
    const items = (result.data?.items || [])
      .filter((run) => !projectId || (run.project_id || '') === projectId)
      .sort((left, right) => {
        const leftTimestamp = Date.parse(left.created_at || left.updated_at || '') || 0;
        const rightTimestamp = Date.parse(right.created_at || right.updated_at || '') || 0;
        return rightTimestamp - leftTimestamp;
      });
    setRecentRuns(items);
    setRunsLoading(false);
  };

  const fetchBoundProjects = async () => {
    if (!workflowId) {
      setProjectsUsageLoading(false);
      setProjectsUsingWorkflow([]);
      return;
    }
    setProjectsUsageLoading(true);
    const matched: BoundProjectUsage[] = [];
    let cursor: string | undefined;
    for (let page = 0; page < 20; page += 1) {
      const result = await listProjects({ limit: 200, cursor });
      if (result.error) {
        onStatus({
          tone: 'warn',
          label: 'Project binding visibility unavailable',
          detail: result.error.message,
        });
        setProjectsUsageLoading(false);
        return;
      }
      const items = result.data?.items || [];
      items.forEach((project) => {
        if (getProjectDefaultChatWorkflowId(project) !== workflowId) return;
        matched.push({
          project_id: project.project_id,
          project_name: project.project_name || project.project_id,
        });
      });
      const nextCursor = result.data?.next_cursor || undefined;
      if (!nextCursor) break;
      cursor = nextCursor;
    }
    const deduped = Array.from(
      new Map(matched.map((item) => [item.project_id, item])).values()
    ).sort((left, right) => left.project_id.localeCompare(right.project_id));
    setProjectsUsingWorkflow(deduped);
    setProjectsUsageLoading(false);
  };

  useEffect(() => {
    if (!opened) return;
    setOpenedAt(new Date().toISOString());
    setValidationRunAt(new Date().toISOString());
    setSimulationError(null);
    setSimulationResult(null);
    setSmokeResult(null);
    setSmokeRun(null);
    setStageTimestamps({});
    setPublishedInCycleVersionId(null);
    setRoutingDefinitionRecord(null);
    setRoutingReadbackStatus('checking');
    setProjectsUsingWorkflow([]);
    setManualCasesJson(JSON.stringify(buildCannedCases(workflowId), null, 2));
    setSimulationSource('canned');
    void fetchVersions();
    void fetchRuns();
    void fetchRoutingReadback({ silent: true });
    void fetchBoundProjects();
    const key = localStorageKey(tenantId, projectId, workflowId);
    try {
      const raw = window.localStorage.getItem(key);
      if (raw) {
        setLastSuccessPath(JSON.parse(raw));
      } else {
        setLastSuccessPath(null);
      }
    } catch {
      setLastSuccessPath(null);
    }
    emitWithContext('release_pipeline_opened');
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [opened, tenantId, projectId, workflowId]);

  const handleValidationRerun = () => {
    setValidationRunAt(new Date().toISOString());
    updateStageTimestamp('validate_at');
    emitWithContext('validation_rerun', {
      blocking_issues: validation.blocking_issues.length,
      warnings: validation.warnings.length,
    });
  };

  const handleRunSimulation = async () => {
    if (!workflowId || !projectId) {
      onStatus({ tone: 'warn', label: 'Workflow and project are required for simulation' });
      return;
    }
    if (!selectedCases.length) {
      onStatus({ tone: 'warn', label: 'No simulation cases selected' });
      return;
    }
    if (simulationSource === 'manual' && manualParse.error) {
      onStatus({ tone: 'warn', label: 'Fix manual simulation JSON first' });
      return;
    }
    setSimulationRunning(true);
    setSimulationError(null);
    emitWithContext('simulation_started', { cases: selectedCases.length, source: simulationSource });
    const replayResult = await orchestratorEvalReplay({
      project_id: projectId,
      orchestrator_id: activeProject?.default_orchestrator_id || undefined,
      session_id: `release_pipeline_${workflowId}`,
      user_id: 'release_operator',
      cases: selectedCases,
    });
    if (replayResult.error) {
      setSimulationError(replayResult.error.message);
      setSimulationResult({
        status: 'failed',
        total_cases: selectedCases.length,
        passed_cases: 0,
        failed_cases: selectedCases.length,
        typed_failures: [replayResult.error.message],
        metrics: {
          action_accuracy: 0,
          workflow_accuracy: 0,
          exact_match_rate: 0,
          average_confidence: 0,
        },
        outcomes: [],
      });
      onStatus({ tone: 'error', label: 'Simulation failed', detail: replayResult.error.message });
      emitWithContext('simulation_completed', {
        status: 'failed',
        cases: selectedCases.length,
      });
      setSimulationRunning(false);
      return;
    }
    const normalized = normalizeSimulationResult(replayResult.data, workflowId);
    setSimulationResult(normalized);
    updateStageTimestamp('simulate_at');
    emitWithContext('simulation_completed', {
      status: normalized.status,
      cases: normalized.total_cases,
      failed_cases: normalized.failed_cases,
    });
    onStatus({
      tone: normalized.status === 'passed' ? 'ok' : 'warn',
      label: normalized.status === 'passed' ? 'Simulation passed' : 'Simulation has failures',
      detail: `${normalized.passed_cases}/${normalized.total_cases} passing`,
    });
    setSimulationRunning(false);
  };

  const handlePublish = async () => {
    if (!publishGates.can_publish) {
      onStatus({ tone: 'warn', label: 'Publish blocked by release gates' });
      return;
    }
    emitWithContext('publish_initiated');
    const versionId = await onPublish();
    if (!versionId) {
      onStatus({ tone: 'error', label: 'Publish did not produce a version' });
      return;
    }
    setPublishedInCycleVersionId(versionId);
    updateStageTimestamp('publish_at');
    emitWithContext('publish_completed', { version_id: versionId });
    await Promise.all([fetchVersions(), fetchRuns(), onProjectsRefreshed(), onWorkflowsRefreshed()]);
    onStatus({ tone: 'ok', label: 'Release candidate published', detail: versionId });
  };

  const handleBindChat = async () => {
    if (!projectId || !workflowId) return;
    setChatBindLoading(true);
    const result = await updateProject(projectId, {
      settings: {
        default_chat_workflow_id: workflowId,
      },
    });
    if (result.error) {
      onStatus({ tone: 'error', label: 'Bind failed', detail: result.error.message });
      setChatBindLoading(false);
      return;
    }
    updateStageTimestamp('bind_at');
    emitWithContext('bind_updated', {
      binding_scope: 'project_default_chat_workflow',
      project_default_chat_workflow_id: workflowId,
    });
    await onProjectsRefreshed();
    await fetchBoundProjects();
    onStatus({ tone: 'ok', label: 'Project chat binding updated', detail: workflowId });
    setChatBindLoading(false);
  };

  const handleBindRouting = async () => {
    if (!projectId || !workflowId) return;
    setRoutingBindLoading(true);
    const result = await upsertProjectWorkflowDefinition(projectId, {
      workflow_id: workflowId,
      name: workflowName.trim() || workflowId,
      description:
        workflowDescription.trim() || `Release pipeline binding for ${workflowId}`,
      tags: ['release-pipeline'],
      examples: ['start'],
      active: true,
      is_fallback: false,
    });
    if (result.error) {
      onStatus({ tone: 'error', label: 'Routing bind failed', detail: result.error.message });
      setRoutingBindLoading(false);
      return;
    }
    const readbackStatus = await fetchRoutingReadback({ silent: true });
    updateStageTimestamp('bind_at');
    emitWithContext('bind_updated', {
      binding_scope: 'project_workflow_definition',
      workflow_id: workflowId,
    });
    if (readbackStatus === 'bound') {
      onStatus({ tone: 'ok', label: 'Routing definition confirmed', detail: workflowId });
    } else {
      onStatus({
        tone: 'warn',
        label: 'Routing definition updated but not confirmed',
        detail: workflowId,
      });
    }
    setRoutingBindLoading(false);
  };

  const handleRunSmoke = async () => {
    if (!workflowId || !projectId) {
      onStatus({ tone: 'warn', label: 'Workflow and project are required for smoke' });
      return;
    }
    if (!bindCompleted) {
      onStatus({ tone: 'warn', label: 'Bind stage must pass before smoke' });
      return;
    }
    if (!releasePublishedVersionId) {
      onStatus({ tone: 'warn', label: 'Publish a version before smoke' });
      return;
    }
    setSmokeRunning(true);
    setSmokeResult(null);
    setSmokeRun(null);
    emitWithContext('smoke_started', { version_id: releasePublishedVersionId });

    const startResult = await startRun(
      workflowId,
      {
        inputs: { release_smoke: true },
        version_id: releasePublishedVersionId,
        mode: 'test',
      },
      projectId
    );
    if (startResult.error) {
      const normalized = normalizeSmokeResult({
        run: null,
        requestError: startResult.error.message,
      });
      setSmokeResult(normalized);
      emitWithContext('smoke_completed', { status: normalized.status });
      onStatus({ tone: 'error', label: 'Smoke failed to start', detail: startResult.error.message });
      setSmokeRunning(false);
      return;
    }

    const runId = startResult.data?.run_id || null;
    let latestRun: RunRecord | null = null;
    if (runId) {
      for (let attempt = 0; attempt < 8; attempt += 1) {
        const runResult = await getRun(runId);
        if (runResult.data) {
          latestRun = runResult.data;
          if (FINAL_RUN_STATUSES.has(latestRun.status)) {
            break;
          }
        }
        await wait(700);
      }
    }
    const timedOut = !latestRun || !FINAL_RUN_STATUSES.has(latestRun.status);
    const normalized = normalizeSmokeResult({
      run: latestRun,
      fallbackRunId: runId,
      timedOut,
    });
    setSmokeResult(normalized);
    if (latestRun) {
      setSmokeRun(latestRun);
    }
    updateStageTimestamp('smoke_at');
    updateStageTimestamp('observe_at');
    emitWithContext('smoke_completed', {
      status: normalized.status,
      run_id: normalized.run_id,
    });
    await fetchRuns();

    if (normalized.status === 'success') {
      const pathPayload: LastSuccessfulReleasePath = {
        timestamp: new Date().toISOString(),
        candidate_version_id: publishedInCycleVersionId || candidateVersionId,
        published_version_id: releasePublishedVersionId,
        smoke_run_id: normalized.run_id,
      };
      setLastSuccessPath(pathPayload);
      try {
        window.localStorage.setItem(
          localStorageKey(tenantId, projectId, workflowId),
          JSON.stringify(pathPayload)
        );
      } catch {
        // Ignore local storage errors.
      }
    }

    onStatus({
      tone: normalized.status === 'success' ? 'ok' : 'warn',
      label: normalized.status === 'success' ? 'Smoke passed' : 'Smoke completed with issues',
      detail: normalized.run_id || undefined,
    });
    setSmokeRunning(false);
  };

  const handleExportReport = () => {
    const exportedAt = new Date().toISOString();
    const report = buildReleaseReport({
      workflow_id: reportBase.workflow_id,
      tenant_id: reportBase.tenant_id,
      project_id: reportBase.project_id,
      candidate_version_id: reportBase.candidate_version_id,
      published_version_id: reportBase.published_version_id,
      validation,
      simulation: simulationResult,
      diff: diffSummary,
      bind_targets: reportBase.bind_targets,
      smoke: smokeResult,
      operator_timestamps: {
        ...reportBase.operator_timestamps,
        report_exported_at: exportedAt,
      },
      exported_at: exportedAt,
    });
    const filename = buildReleaseReportFilename(workflowId || 'workflow', exportedAt);
    downloadJson(report, filename);
    emitWithContext('release_report_exported', {
      exported_at: exportedAt,
      run_ids: report.run_ids.length,
      correlation_ids: report.correlation_ids.length,
    });
    onStatus({ tone: 'ok', label: 'Release report exported', detail: filename });
  };

  return (
    <Drawer
      opened={opened}
      onClose={onClose}
      position="right"
      size={700}
      title="Release Pipeline"
      data-testid="release-pipeline-drawer"
    >
      <Stack gap="md" style={{ height: 'calc(100vh - 120px)' }}>
        <Card withBorder radius="md">
          <Stack gap="xs">
            <Group justify="space-between" align="center">
              <Stack gap={2}>
                <Text fw={600}>{workflowName || workflowId || 'Workflow release pipeline'}</Text>
                <Text size="xs" c="dimmed">
                  Workflow {workflowId || '—'} · Project {projectId || '—'}
                </Text>
              </Stack>
              <Badge variant="outline" color="gray">
                Candidate {publishedInCycleVersionId || candidateVersionId}
              </Badge>
            </Group>
            <SimpleGrid cols={{ base: 2, sm: 4 }} spacing="xs">
              {stageStates.map((stage) => (
                <Badge
                  key={stage.stage}
                  variant="light"
                  color={
                    stage.status === 'passed'
                      ? 'teal'
                      : stage.status === 'failed'
                        ? 'red'
                        : stage.status === 'blocked'
                          ? 'yellow'
                          : 'gray'
                  }
                >
                  {stage.stage}: {stage.status}
                </Badge>
              ))}
            </SimpleGrid>
            {lastSuccessPath && (
              <Text size="xs" c="dimmed">
                Latest successful release path: {lastSuccessPath.candidate_version_id} →{' '}
                {lastSuccessPath.published_version_id || 'none'} · smoke {lastSuccessPath.smoke_run_id || 'n/a'} ·{' '}
                {formatDate(lastSuccessPath.timestamp)}
              </Text>
            )}
          </Stack>
        </Card>

        <ScrollArea style={{ flex: 1, minHeight: 0 }}>
          <Stack gap="md" pb="md">
            <WorkflowValidationGate
              summary={validation}
              lastRunAt={validationRunAt}
              onRerun={handleValidationRerun}
              onFocusNode={onFocusNode}
            />

            <WorkflowSimulationPanel
              source={simulationSource}
              onSourceChange={setSimulationSource}
              manualCasesJson={manualCasesJson}
              onManualCasesJsonChange={setManualCasesJson}
              manualJsonError={simulationSource === 'manual' ? manualParse.error : null}
              selectedCasesCount={selectedCases.length}
              running={simulationRunning}
              result={simulationResult}
              errorMessage={simulationError}
              hasLastGoodCases={lastGoodCases.length > 0}
              onRun={handleRunSimulation}
            />

            <WorkflowVersionDiff diff={diffSummary} loading={versionsLoading} />

            <Card withBorder radius="md" data-testid="release-stage-publish">
              <Stack gap="sm">
                <Group justify="space-between" align="center">
                  <Text fw={600}>Publish</Text>
                  <Badge color={publishStagePassed ? 'teal' : 'gray'} variant="light">
                    {publishStagePassed ? 'Published' : 'Pending'}
                  </Badge>
                </Group>
                <Stack gap={6}>
                  {publishGates.gates.map((gate) => (
                    <Group key={gate.id} justify="space-between" align="center">
                      <Text size="sm">
                        {gate.label}: {gate.detail}
                      </Text>
                      <Badge variant={gate.passed ? 'light' : 'outline'} color={gate.passed ? 'teal' : 'yellow'}>
                        {gate.passed ? 'pass' : 'blocked'}
                      </Badge>
                    </Group>
                  ))}
                </Stack>
                <Button
                  size="xs"
                  onClick={handlePublish}
                  disabled={!publishGates.can_publish}
                  data-testid="release-publish"
                >
                  Publish candidate
                </Button>
                <Text size="xs" c="dimmed">
                  Active version: {releasePublishedVersionId || 'none'}
                </Text>
              </Stack>
            </Card>

            <WorkflowBindingPanel
              projectId={projectId}
              projectName={activeProject?.project_name || projectId || 'unknown'}
              chatBound={chatBound}
              routingBound={routingBound}
              routingReadbackStatus={routingReadbackStatus}
              routingDefinitionUpdatedAt={routingDefinitionRecord?.updated_at ? formatDate(routingDefinitionRecord.updated_at) : null}
              observedDirectRuns={observedDirectRuns}
              projectsUsingWorkflow={projectsUsingWorkflow}
              projectsUsageLoading={projectsUsageLoading}
              loadingChatBind={chatBindLoading}
              loadingRoutingBind={routingBindLoading}
              onBindChat={handleBindChat}
              onBindRouting={handleBindRouting}
            />

            <WorkflowSmokeRunner
              smoke={smokeResult}
              loading={smokeRunning}
              runDetailsUrl={runDetailsUrl}
              integrationLogsUrl={integrationLogsUrl}
              onRunSmoke={handleRunSmoke}
              onOpenRunDebug={() => {
                if (smokeResult?.run_id) {
                  onOpenRunDebug(smokeResult.run_id);
                }
              }}
            />

            <Card withBorder radius="md" data-testid="release-stage-observe">
              <Stack gap="sm">
                <Group justify="space-between" align="center">
                  <Text fw={600}>Observe</Text>
                  <Badge variant="light" color={runsLoading ? 'blue' : 'gray'}>
                    {runsLoading ? 'Loading runs' : `${releaseVersionRuns.length} recent runs`}
                  </Badge>
                </Group>
                <Group gap="xs" wrap="wrap">
                  <Badge variant="outline" color="gray">
                    Failure trend{' '}
                    {failureTrend.signal === 'increasing_failures'
                      ? 'increasing'
                      : failureTrend.signal === 'stable'
                        ? 'stable'
                        : 'insufficient'}
                  </Badge>
                  {failureTrend.signal !== 'insufficient_data' && (
                    <Badge variant="outline" color="gray">
                      {formatPercent(failureTrend.previous_failure_rate)} →{' '}
                      {formatPercent(failureTrend.recent_failure_rate)}
                    </Badge>
                  )}
                  <Button size="xs" variant="light" onClick={() => void fetchRuns()}>
                    Refresh observe data
                  </Button>
                </Group>
                {(runDetailsUrl || integrationLogsUrl || smokeResult?.run_id) && (
                  <Group gap="xs" wrap="wrap">
                    {smokeResult?.run_id && (
                      <Button
                        size="xs"
                        variant="subtle"
                        onClick={() => onOpenRunDebug(smokeResult.run_id)}
                      >
                        Open smoke run debug
                      </Button>
                    )}
                    {runDetailsUrl && (
                      <Anchor href={runDetailsUrl} target="_blank" rel="noopener noreferrer" size="xs">
                        Open run details
                      </Anchor>
                    )}
                    {integrationLogsUrl && (
                      <Anchor href={integrationLogsUrl} target="_blank" rel="noopener noreferrer" size="xs">
                        Open integration logs
                      </Anchor>
                    )}
                  </Group>
                )}
                {releaseVersionRuns.length === 0 ? (
                  <Text size="sm" c="dimmed">
                    No runs for the selected published version yet.
                  </Text>
                ) : (
                  <Stack gap="xs">
                    {releaseVersionRuns.slice(0, 8).map((run) => (
                      <Card key={run.run_id} withBorder radius="sm" padding="sm">
                        <Group justify="space-between" align="center">
                          <Stack gap={2}>
                            <Text size="sm" fw={600}>
                              {run.run_id}
                            </Text>
                            <Text size="xs" c="dimmed">
                              {formatDate(run.created_at || run.updated_at)}
                            </Text>
                          </Stack>
                          <Group gap="xs">
                            <Badge color={runStatusBadgeColor(run.status)} variant="light">
                              {run.status}
                            </Badge>
                            <Button
                              size="xs"
                              variant="subtle"
                              onClick={() => onOpenRunDebug(run.run_id)}
                            >
                              Run Debug
                            </Button>
                          </Group>
                        </Group>
                      </Card>
                    ))}
                  </Stack>
                )}
              </Stack>
            </Card>

            <Divider />
            <WorkflowReleaseReport report={reportBase} onExport={handleExportReport} />
          </Stack>
        </ScrollArea>
      </Stack>
    </Drawer>
  );
}
