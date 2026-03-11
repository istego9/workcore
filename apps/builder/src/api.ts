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
const API_TENANT_ID = import.meta.env.VITE_TENANT_ID || '';

type ApiError = {
  code: string;
  message: string;
  details?: any;
};

type ApiResult<T> = { data?: T; error?: ApiError };

export type ProjectRecord = {
  project_id: string;
  project_name: string;
  tenant_id: string;
  default_orchestrator_id?: string | null;
  settings: Record<string, any>;
  created_at: string;
  updated_at: string;
};

const readStorageValue = (key: string): string => {
  if (typeof window === 'undefined') return '';
  try {
    const value = window.localStorage.getItem(key);
    return typeof value === 'string' ? value.trim() : '';
  } catch {
    return '';
  }
};

const readQueryValue = (key: string): string => {
  if (typeof window === 'undefined') return '';
  try {
    const value = new URLSearchParams(window.location.search).get(key);
    return typeof value === 'string' ? value.trim() : '';
  } catch {
    return '';
  }
};

const resolveAuthToken = (): string =>
  API_AUTH_TOKEN || readQueryValue('api_token') || readStorageValue('workcore.api_auth_token');

const resolveTenantId = (): string =>
  API_TENANT_ID || readQueryValue('tenant_id') || readStorageValue('workcore.tenant_id');

const projectHeaders = (projectId?: string): Record<string, string> => {
  if (typeof projectId !== 'string') return {};
  const normalized = projectId.trim();
  if (!normalized) return {};
  return { 'X-Project-Id': normalized };
};

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
  const authToken = resolveAuthToken();
  const tenantId = resolveTenantId();
  const requestHeaders = {
    'Content-Type': 'application/json',
    ...(authToken ? { Authorization: `Bearer ${authToken}` } : {}),
    ...(tenantId ? { 'X-Tenant-Id': tenantId } : {}),
    ...(options?.headers || {})
  };
  let response: Response;
  try {
    response = await fetch(`${API_BASE}${path}`, {
      ...options,
      headers: requestHeaders
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
}, projectId?: string): Promise<ApiResult<WorkflowRecord>> => {
  return request('/workflows', {
    method: 'POST',
    headers: projectHeaders(projectId),
    body: JSON.stringify(payload)
  });
};

export const getWorkflow = async (workflowId: string, projectId?: string): Promise<ApiResult<WorkflowRecord>> => {
  return request(`/workflows/${workflowId}`, { headers: projectHeaders(projectId) });
};

export const listWorkflows = async (
  limit = 50,
  projectId?: string
): Promise<ApiResult<{ items: WorkflowSummary[]; next_cursor?: string | null }>> => {
  return listWorkflowsPage({ limit }, projectId);
};

export const listWorkflowsPage = async (
  params?: { limit?: number; cursor?: string },
  projectId?: string
): Promise<ApiResult<{ items: WorkflowSummary[]; next_cursor?: string | null }>> => {
  const query = new URLSearchParams();
  if (typeof params?.limit === 'number') {
    query.set('limit', String(params.limit));
  }
  if (params?.cursor) {
    query.set('cursor', params.cursor);
  }
  const suffix = query.toString();
  return request(`/workflows${suffix ? `?${suffix}` : ''}`, { headers: projectHeaders(projectId) });
};

export const updateWorkflowMeta = async (
  workflowId: string,
  payload: { name?: string; description?: string | null },
  projectId?: string
): Promise<ApiResult<WorkflowRecord>> => {
  return request(`/workflows/${workflowId}`, {
    method: 'PATCH',
    headers: projectHeaders(projectId),
    body: JSON.stringify(payload)
  });
};

export const updateDraft = async (
  workflowId: string,
  draft: WorkflowDraft,
  projectId?: string
): Promise<ApiResult<WorkflowRecord>> => {
  return request(`/workflows/${workflowId}/draft`, {
    method: 'PUT',
    headers: projectHeaders(projectId),
    body: JSON.stringify(draft)
  });
};

export const publishWorkflow = async (
  workflowId: string,
  projectId?: string
): Promise<ApiResult<WorkflowVersion>> => {
  return request(`/workflows/${workflowId}/publish`, {
    method: 'POST',
    headers: projectHeaders(projectId)
  });
};

export const rollbackWorkflow = async (
  workflowId: string,
  projectId?: string
): Promise<ApiResult<WorkflowRecord>> => {
  return request(`/workflows/${workflowId}/rollback`, {
    method: 'POST',
    headers: projectHeaders(projectId)
  });
};

export const deleteWorkflow = async (
  workflowId: string,
  projectId?: string
): Promise<ApiResult<null>> => {
  return request(`/workflows/${workflowId}`, {
    method: 'DELETE',
    headers: projectHeaders(projectId)
  });
};

export const startRun = async (
  workflowId: string,
  payload: { inputs?: Record<string, any>; version_id?: string; mode?: string },
  projectId?: string
): Promise<ApiResult<{ run_id: string; status: string }>> => {
  return request(`/workflows/${workflowId}/runs`, {
    method: 'POST',
    headers: projectHeaders(projectId),
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

export const listProjects = async (params?: {
  limit?: number;
  cursor?: string;
}): Promise<ApiResult<{ items: ProjectRecord[]; next_cursor?: string | null }>> => {
  const query = new URLSearchParams();
  if (typeof params?.limit === 'number') {
    query.set('limit', String(params.limit));
  }
  if (params?.cursor) {
    query.set('cursor', params.cursor);
  }
  const suffix = query.toString();
  return request(`/projects${suffix ? `?${suffix}` : ''}`);
};

export const updateProject = async (
  projectId: string,
  payload: { project_name?: string; settings?: Record<string, any> }
): Promise<ApiResult<ProjectRecord>> => {
  return request(`/projects/${projectId}`, {
    method: 'PATCH',
    body: JSON.stringify(payload)
  });
};

export const deleteProject = async (projectId: string): Promise<ApiResult<null>> => {
  return request(`/projects/${projectId}`, {
    method: 'DELETE'
  });
};
