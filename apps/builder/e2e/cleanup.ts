import { expect, type APIRequestContext } from '@playwright/test';

import { apiAuthHeaders, apiBaseUrl } from './env';

export const deleteWorkflowIfExists = async (
  request: APIRequestContext,
  projectId: string,
  workflowId: string | null | undefined
): Promise<void> => {
  if (!workflowId) return;
  const response = await request.delete(`${apiBaseUrl}/workflows/${workflowId}`, {
    headers: apiAuthHeaders(projectId)
  });
  expect([200, 204, 404]).toContain(response.status());
};

export const deleteProjectIfExists = async (
  request: APIRequestContext,
  projectId: string | null | undefined
): Promise<void> => {
  if (!projectId) return;
  const response = await request.delete(`${apiBaseUrl}/projects/${projectId}`, {
    headers: apiAuthHeaders()
  });
  expect([200, 204, 404]).toContain(response.status());
};
