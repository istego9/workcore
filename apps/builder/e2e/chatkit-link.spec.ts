import { expect, test } from '@playwright/test';
import {
  apiAuthHeaders,
  apiBaseUrl,
  chatApiUrl,
  e2eApiAuthToken,
  e2eTenantId,
  installApiAuthRoute,
  resolveUrl
} from './env';
import { deleteProjectIfExists, deleteWorkflowIfExists } from './cleanup';

test('open chat button builds chatkit url', async ({ page, request }) => {
  let workflowId: string | null = null;
  let versionId: string | null = null;
  const projectId = `proj_e2e_${Date.now()}`;
  const projectName = `E2E Project ${Date.now()}`;
  const workflowName = `E2E Chat ${Date.now()}`;
  const draft = {
    nodes: [
      { id: 'start', type: 'start', config: { ui: { x: 80, y: 120 } } },
      { id: 'end', type: 'end', config: { ui: { x: 360, y: 120 } } }
    ],
    edges: [{ source: 'start', target: 'end' }],
    variables_schema: {}
  };

  try {
    const createProjectResponse = await request.post(`${apiBaseUrl}/projects`, {
      data: { project_id: projectId, project_name: projectName, settings: { orchestrator_enabled: true } },
      headers: apiAuthHeaders()
    });
    expect(createProjectResponse.ok()).toBeTruthy();

    const createResponse = await request.post(`${apiBaseUrl}/workflows`, {
      data: { name: workflowName, draft },
      headers: apiAuthHeaders(projectId)
    });
    expect(createResponse.ok()).toBeTruthy();
    const workflow = await createResponse.json();
    workflowId = workflow.workflow_id;
    expect(workflowId).toBeTruthy();

    const publishResponse = await request.post(`${apiBaseUrl}/workflows/${workflowId}/publish`, {
      headers: apiAuthHeaders(projectId)
    });
    expect(publishResponse.ok()).toBeTruthy();
    const version = await publishResponse.json();
    versionId = version.version_id;

    await installApiAuthRoute(page, projectId);
    await page.addInitScript(
      ({ token, tenant }) => {
        if (token) window.localStorage.setItem('workcore.api_auth_token', token);
        if (tenant) window.localStorage.setItem('workcore.tenant_id', tenant);
      },
      { token: e2eApiAuthToken, tenant: e2eTenantId }
    );
    await page.goto('/?e2e=1');
    await page.getByRole('button', { name: 'Back to projects' }).click();
    await page.getByText(projectName).first().click();
    await page.getByText(workflowName).first().click();
    await expect(page.getByText(`Workflow ${workflowId}`).first()).toBeVisible();

    const openChatButton = page.getByTestId('open-chatkit');
    const dataUrl = await openChatButton.getAttribute('data-chatkit-url');
    expect(dataUrl).toBeTruthy();
    await expect(page.getByTestId('chat-link')).toHaveValue(dataUrl!);
    const url = new URL(dataUrl!);
    expect(url.pathname.endsWith('/chatkit.html')).toBeTruthy();
    expect(url.searchParams.get('workflow_id')).toBe(workflowId);
    expect(url.searchParams.get('workflow_version_id')).toBe(versionId);
    expect(url.searchParams.get('project_id')).toBe(projectId);
    const apiUrlParam = url.searchParams.get('api_url');
    expect(apiUrlParam).toBeTruthy();
    const expectedChatApi = resolveUrl(chatApiUrl);
    const actualChatApi = new URL(apiUrlParam!, url.origin);
    expect(actualChatApi.host).toBe(expectedChatApi.host);
    expect(actualChatApi.pathname).toBe(expectedChatApi.pathname);
  } finally {
    await deleteWorkflowIfExists(request, projectId, workflowId);
    await deleteProjectIfExists(request, projectId);
  }
});
