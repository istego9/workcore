import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { API_BASE, deleteProject, listProjects, listRuns, listWorkflows, updateProject } from './api';

describe('api listRuns', () => {
  const fetchMock = vi.fn();
  const clearStorage = () => {
    const storage: any = (window as any).localStorage;
    if (!storage) return;
    if (typeof storage.removeItem === 'function') {
      storage.removeItem('workcore.api_auth_token');
      storage.removeItem('workcore.tenant_id');
      return;
    }
    delete storage['workcore.api_auth_token'];
    delete storage['workcore.tenant_id'];
  };

  beforeEach(() => {
    vi.stubGlobal('fetch', fetchMock);
    clearStorage();
    window.history.replaceState({}, '', '/');
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.resetAllMocks();
  });

  it('builds /runs query params for execution history', async () => {
    fetchMock.mockResolvedValue({
      ok: true,
      json: async () => ({ items: [], next_cursor: null })
    } as Response);

    await listRuns({
      workflowId: 'wf_1',
      status: 'COMPLETED',
      limit: 25,
      cursor: 'cursor_1'
    });

    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock).toHaveBeenCalledWith(
      `${API_BASE}/runs?workflow_id=wf_1&status=COMPLETED&limit=25&cursor=cursor_1`,
      expect.objectContaining({
        headers: expect.objectContaining({
          'Content-Type': 'application/json'
        })
      })
    );
  });

  it('builds /projects query params for project dropdown', async () => {
    fetchMock.mockResolvedValue({
      ok: true,
      json: async () => ({ items: [], next_cursor: null })
    } as Response);

    await listProjects({ limit: 200, cursor: 'cursor_projects_1' });

    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock).toHaveBeenCalledWith(
      `${API_BASE}/projects?limit=200&cursor=cursor_projects_1`,
      expect.objectContaining({
        headers: expect.objectContaining({
          'Content-Type': 'application/json'
        })
      })
    );
  });

  it('returns parsed API error for run history request', async () => {
    fetchMock.mockResolvedValue({
      ok: false,
      statusText: 'Not Found',
      json: async () => ({ error: { code: 'NOT_FOUND', message: 'run not found' } })
    } as Response);

    const result = await listRuns({ workflowId: 'wf_missing' });
    expect(result.error).toEqual({ code: 'NOT_FOUND', message: 'run not found' });
  });

  it('returns NETWORK_ERROR when fetch throws', async () => {
    fetchMock.mockRejectedValue(new TypeError('Failed to fetch'));

    const result = await listWorkflows();
    expect(result.error).toEqual({ code: 'NETWORK_ERROR', message: 'Failed to fetch' });
  });

  it('merges auth/tenant headers with project scope headers', async () => {
    fetchMock.mockResolvedValue({
      ok: true,
      json: async () => ({ items: [], next_cursor: null })
    } as Response);

    window.history.replaceState({}, '', '/?api_token=token_local&tenant_id=tenant_local');

    await listWorkflows(50, 'proj_merge');

    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock).toHaveBeenCalledWith(
      `${API_BASE}/workflows?limit=50`,
      expect.objectContaining({
        headers: expect.objectContaining({
          'Content-Type': 'application/json',
          Authorization: 'Bearer token_local',
          'X-Tenant-Id': 'tenant_local',
          'X-Project-Id': 'proj_merge'
        })
      })
    );
  });

  it('sends auth/tenant headers for project list requests', async () => {
    fetchMock.mockResolvedValue({
      ok: true,
      json: async () => ({ items: [], next_cursor: null })
    } as Response);

    window.history.replaceState({}, '', '/?api_token=token_local&tenant_id=tenant_local');

    await listProjects({ limit: 50 });

    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock).toHaveBeenCalledWith(
      `${API_BASE}/projects?limit=50`,
      expect.objectContaining({
        headers: expect.objectContaining({
          'Content-Type': 'application/json',
          Authorization: 'Bearer token_local',
          'X-Tenant-Id': 'tenant_local'
        })
      })
    );
  });

  it('calls PATCH /projects/{project_id} for project edit', async () => {
    fetchMock.mockResolvedValue({
      ok: true,
      json: async () => ({ project_id: 'proj_1', project_name: 'Renamed' })
    } as Response);

    await updateProject('proj_1', { project_name: 'Renamed' });

    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock).toHaveBeenCalledWith(
      `${API_BASE}/projects/proj_1`,
      expect.objectContaining({
        method: 'PATCH',
        body: JSON.stringify({ project_name: 'Renamed' })
      })
    );
  });

  it('calls PATCH /projects/{project_id} with settings updates for project chat defaults', async () => {
    fetchMock.mockResolvedValue({
      ok: true,
      json: async () => ({
        project_id: 'proj_1',
        project_name: 'Renamed',
        settings: { default_chat_workflow_id: 'wf_chat' }
      })
    } as Response);

    await updateProject('proj_1', {
      settings: { default_chat_workflow_id: 'wf_chat' }
    });

    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock).toHaveBeenCalledWith(
      `${API_BASE}/projects/proj_1`,
      expect.objectContaining({
        method: 'PATCH',
        body: JSON.stringify({ settings: { default_chat_workflow_id: 'wf_chat' } })
      })
    );
  });

  it('calls DELETE /projects/{project_id} for project deletion', async () => {
    fetchMock.mockResolvedValue({
      ok: true,
      json: async () => null
    } as Response);

    await deleteProject('proj_1');

    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock).toHaveBeenCalledWith(
      `${API_BASE}/projects/proj_1`,
      expect.objectContaining({
        method: 'DELETE'
      })
    );
  });
});
