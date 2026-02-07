import type { WorkflowDraft, WorkflowRecord, WorkflowSummary, WorkflowVersion } from './builder/types';

export const API_BASE = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000';

type ApiError = {
  code: string;
  message: string;
  details?: any;
};

type ApiResult<T> = { data?: T; error?: ApiError };

const request = async <T>(path: string, options?: RequestInit): Promise<ApiResult<T>> => {
  const response = await fetch(`${API_BASE}${path}`, {
    headers: {
      'Content-Type': 'application/json',
      ...(options?.headers || {})
    },
    ...options
  });

  let payload: any = null;
  try {
    payload = await response.json();
  } catch {
    payload = null;
  }

  if (!response.ok) {
    return { error: payload?.error || { code: 'UNKNOWN', message: response.statusText } };
  }
  return { data: payload };
};

export const createWorkflow = async (payload: {
  name: string;
  description?: string;
  draft: WorkflowDraft;
}): Promise<ApiResult<WorkflowRecord>> => {
  return request('/workflows', { method: 'POST', body: JSON.stringify(payload) });
};

export const getWorkflow = async (workflowId: string): Promise<ApiResult<WorkflowRecord>> => {
  return request(`/workflows/${workflowId}`);
};

export const listWorkflows = async (
  limit = 50
): Promise<ApiResult<{ items: WorkflowSummary[]; next_cursor?: string | null }>> => {
  return request(`/workflows?limit=${limit}`);
};

export const updateWorkflowMeta = async (
  workflowId: string,
  payload: { name?: string; description?: string | null }
): Promise<ApiResult<WorkflowRecord>> => {
  return request(`/workflows/${workflowId}`, {
    method: 'PATCH',
    body: JSON.stringify(payload)
  });
};

export const updateDraft = async (
  workflowId: string,
  draft: WorkflowDraft
): Promise<ApiResult<WorkflowRecord>> => {
  return request(`/workflows/${workflowId}/draft`, {
    method: 'PUT',
    body: JSON.stringify(draft)
  });
};

export const publishWorkflow = async (workflowId: string): Promise<ApiResult<WorkflowVersion>> => {
  return request(`/workflows/${workflowId}/publish`, { method: 'POST' });
};

export const rollbackWorkflow = async (workflowId: string): Promise<ApiResult<WorkflowRecord>> => {
  return request(`/workflows/${workflowId}/rollback`, { method: 'POST' });
};

export const deleteWorkflow = async (workflowId: string): Promise<ApiResult<null>> => {
  return request(`/workflows/${workflowId}`, { method: 'DELETE' });
};

export const startRun = async (
  workflowId: string,
  payload: { inputs?: Record<string, any>; version_id?: string; mode?: string }
): Promise<ApiResult<{ run_id: string; status: string }>> => {
  return request(`/workflows/${workflowId}/runs`, {
    method: 'POST',
    body: JSON.stringify(payload)
  });
};
