import { expect, test } from '@playwright/test';
import {
  apiAuthHeaders,
  apiBaseUrl,
  e2eApiAuthToken,
  e2eTenantId,
  installApiAuthRoute
} from './env';

test('agent output format shows json and widget controls', async ({ page, request }) => {
  let workflowId: string | null = null;
  const projectId = `proj_output_${Date.now()}`;
  const workflowName = `E2E Output ${Date.now()}`;
  const draft = {
    nodes: [
      { id: 'start', type: 'start', config: { ui: { x: 80, y: 120 } } },
      {
        id: 'agent',
        type: 'agent',
        config: {
          instructions: 'Hello',
          output_format: 'json',
          output_schema: {
            type: 'object',
            properties: {
              title: { type: 'string' }
            }
          },
          ui: { x: 360, y: 120 }
        }
      },
      { id: 'end', type: 'end', config: { ui: { x: 640, y: 120 } } }
    ],
    edges: [
      { source: 'start', target: 'agent' },
      { source: 'agent', target: 'end' }
    ],
    variables_schema: {}
  };

  try {
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

    await installApiAuthRoute(page, projectId);
    await page.addInitScript(
      ({ token, tenant }) => {
        if (token) window.localStorage.setItem('workcore.api_auth_token', token);
        if (tenant) window.localStorage.setItem('workcore.tenant_id', tenant);
      },
      { token: e2eApiAuthToken, tenant: e2eTenantId }
    );
    await page.goto('/?e2e=1');
    await page.getByTestId('project-selector').fill(projectId);

    await page.getByRole('button', { name: 'Browse' }).click();
    const modal = page.getByRole('dialog', { name: 'Workflows' });
    const refresh = modal.getByRole('button', { name: 'Refresh' });
    await expect(refresh).toBeEnabled({ timeout: 10000 });
    await refresh.click();
    await modal.getByPlaceholder('Search by name or id').fill(workflowName);
    await modal.getByText(`${workflowName}`).waitFor({ timeout: 10000 });
    await modal.getByText(`${workflowName}`).click();

    await expect(page.getByText(`Workflow ${workflowId}`)).toBeVisible();

    const agentNode = page.locator('[data-node-id="agent"]');
    await expect(agentNode).toBeVisible({ timeout: 10000 });
    await agentNode.evaluate((node) => {
      node.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true }));
    });
    await expect(page.getByLabel('Node ID')).toHaveValue('agent');

    const outputFormat = page.getByTestId('agent-output-format');
    await expect(outputFormat).toHaveValue(/json/i);
    await expect(page.getByText('Output schema')).toBeVisible();

    await outputFormat.click();
    await page.getByRole('option', { name: 'Widget' }).click();
    await expect(page.getByTestId('agent-widget-template')).toBeVisible();

    await page.getByTestId('agent-widget-template').click();
    await page.getByRole('option', { name: 'UX Presentations' }).click();
    await expect(page.getByTestId('agent-widget-selected')).toHaveText('UX Presentations');

    await outputFormat.click();
    await page.getByRole('option', { name: 'Text' }).click();
    await expect(page.locator('text=Output schema')).toHaveCount(0);
    await expect(page.getByTestId('agent-widget-template')).toHaveCount(0);
  } finally {
    if (workflowId) {
      const deleteResponse = await request.delete(`${apiBaseUrl}/workflows/${workflowId}`, {
        headers: apiAuthHeaders(projectId)
      });
      expect(deleteResponse.ok()).toBeTruthy();
    }
  }
});
