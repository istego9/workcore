import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { API_BASE, listRuns, listWorkflows } from './api';

describe('api listRuns', () => {
  const fetchMock = vi.fn();

  beforeEach(() => {
    vi.stubGlobal('fetch', fetchMock);
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
});
