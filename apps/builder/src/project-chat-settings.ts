import type { ProjectRecord } from './api';
import type { WorkflowSummary } from './builder/types';
import { normalizeProjectId } from './project-switcher';

export const getProjectDefaultChatWorkflowId = (project?: ProjectRecord | null): string => {
  const raw = project?.settings?.default_chat_workflow_id;
  return typeof raw === 'string' ? raw.trim() : '';
};

export const getProjectChatWorkflowLabel = (
  project: ProjectRecord | null | undefined,
  workflows: WorkflowSummary[]
): string => {
  const workflowId = getProjectDefaultChatWorkflowId(project);
  if (!workflowId) return '';
  const match = workflows.find((item) => item.workflow_id === workflowId);
  if (!match) return workflowId;
  return match.name?.trim() || workflowId;
};

export const buildProjectChatWorkflowOptions = (
  projectId: string,
  workflows: WorkflowSummary[],
  currentWorkflowId = ''
): Array<{ value: string; label: string }> => {
  const normalizedProjectId = normalizeProjectId(projectId);
  const options = workflows
    .filter((item) => normalizeProjectId(item.project_id) === normalizedProjectId)
    .filter((item) => Boolean(item.active_version_id))
    .sort((left, right) => left.name.localeCompare(right.name))
    .map((item) => ({
      value: item.workflow_id,
      label: `${item.name} (${item.workflow_id})`
    }));

  if (currentWorkflowId && !options.some((item) => item.value === currentWorkflowId)) {
    options.unshift({
      value: currentWorkflowId,
      label: `${currentWorkflowId} (unavailable)`
    });
  }
  return options;
};
