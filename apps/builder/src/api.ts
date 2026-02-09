import type { WorkflowDraft, WorkflowRecord, WorkflowSummary, WorkflowVersion } from './builder/types';

const inferRootHost = (hostname: string) => {
  if (hostname === 'localhost' || hostname === '127.0.0.1' || hostname === '::1') {
    return 'localhost';
  }
  if (hostname.startsWith('builder.')) return hostname.slice('builder.'.length);
  if (hostname.startsWith('api.')) return hostname.slice('api.'.length);
  if (hostname.startsWith('chatkit.')) return hostname.slice('chatkit.'.length);
  return hostname;
};

const inferApiBase = () => {
  if (typeof window === 'undefined') {
    return 'http://localhost:8000';
  }
  const { protocol, hostname, port } = window.location;
  const rootHost = inferRootHost(hostname);
  const apiHost = rootHost === 'localhost' ? 'api.localhost' : `api.${rootHost}`;
  return `${protocol}//${apiHost}${port ? `:${port}` : ''}`;
};

export const API_BASE = import.meta.env.VITE_API_BASE_URL || inferApiBase();
const API_AUTH_TOKEN = import.meta.env.VITE_API_AUTH_TOKEN || '';

type ApiError = {
  code: string;
  message: string;
  details?: any;
};

type ApiResult<T> = { data?: T; error?: ApiError };

export type RunRecord = {
  run_id: string;
  workflow_id: string;
  version_id: string;
  status: string;
  mode?: string;
  inputs?: Record<string, any>;
  state?: Record<string, any>;
  outputs?: Record<string, any> | null;
  metadata?: Record<string, any>;
  correlation_id?: string;
  trace_id?: string;
  tenant_id?: string;
  project_id?: string;
  import_run_id?: string;
  created_at?: string;
  updated_at?: string;
  node_runs?: Array<{
    node_id: string;
    status: string;
    attempt?: number;
    output?: any;
    last_error?: string | null;
    trace_id?: string | null;
    usage?: Record<string, any> | null;
  }>;
};

const request = async <T>(path: string, options?: RequestInit): Promise<ApiResult<T>> => {
  let response: Response;
  try {
    response = await fetch(`${API_BASE}${path}`, {
      headers: {
        'Content-Type': 'application/json',
        ...(API_AUTH_TOKEN ? { Authorization: `Bearer ${API_AUTH_TOKEN}` } : {}),
        ...(options?.headers || {})
      },
      ...options
    });
  } catch (error: any) {
    return {
      error: {
        code: 'NETWORK_ERROR',
        message: error?.message || 'Network request failed'
      }
    };
  }

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

export const listRuns = async (params?: {
  workflowId?: string;
  status?: string;
  limit?: number;
  cursor?: string;
}): Promise<ApiResult<{ items: RunRecord[]; next_cursor?: string | null }>> => {
  const query = new URLSearchParams();
  if (params?.workflowId) {
    query.set('workflow_id', params.workflowId);
  }
  if (params?.status) {
    query.set('status', params.status);
  }
  if (typeof params?.limit === 'number') {
    query.set('limit', String(params.limit));
  }
  if (params?.cursor) {
    query.set('cursor', params.cursor);
  }
  const suffix = query.toString();
  return request(`/runs${suffix ? `?${suffix}` : ''}`);
};
