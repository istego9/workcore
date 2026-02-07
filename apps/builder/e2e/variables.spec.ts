import { expect, test } from '@playwright/test';
import { apiAuthHeaders, apiBaseUrl } from './env';

test('variable picker supports nested schema and node outputs', async ({ page, request }) => {
  let workflowId: string | null = null;
  const workflowName = `E2E Vars ${Date.now()}`;
  const draft = {
    nodes: [
      { id: 'start', type: 'start', config: { ui: { x: 80, y: 120 } } },
      {
        id: 'agent',
        type: 'agent',
        config: {
          instructions: 'Hello',
          output_schema: {
            type: 'object',
            properties: {
              summary: { type: 'string' },
              details: { type: 'object', properties: { title: { type: 'string' } } }
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
    variables_schema: {
      type: 'object',
      properties: {
        user: { type: 'object', properties: { name: { type: 'string' } } },
        order_id: { type: 'string' }
      }
    }
  };

  try {
    const createResponse = await request.post(`${apiBaseUrl}/workflows`, {
      data: { name: workflowName, draft },
      headers: apiAuthHeaders()
    });
    expect(createResponse.ok()).toBeTruthy();
    const workflow = await createResponse.json();
    workflowId = workflow.workflow_id;
    expect(workflowId).toBeTruthy();

    const publishResponse = await request.post(`${apiBaseUrl}/workflows/${workflowId}/publish`, {
      headers: apiAuthHeaders()
    });
    expect(publishResponse.ok()).toBeTruthy();

    await page.goto('/');

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
    await expect(page.getByText('Instructions')).toBeVisible({ timeout: 5000 });
    const picker = page.getByTestId('agent-instructions-picker');
    await picker.evaluate((node) => {
      node.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true }));
    });

    const search = page.getByPlaceholder('Search variables');
    await search.fill('user.name');
    await page.locator("[data-var-value=\"inputs['user']['name']\"]").click();

    const value = await page.getByTestId('agent-instructions-input').inputValue();
    expect(value).toContain("{{inputs['user']['name']}}");

    const highlight = await page.getByTestId('agent-instructions-highlight').innerHTML();
    expect(highlight).toContain('template-token');

    await page.getByTestId('agent-instructions-picker').click();
    await search.fill('agent.summary');
    await page.locator("[data-var-value=\"node_outputs['agent']['summary']\"]").click();

    const value2 = await page.getByTestId('agent-instructions-input').inputValue();
    expect(value2).toContain("{{node_outputs['agent']['summary']}}");
  } finally {
    if (workflowId) {
      const deleteResponse = await request.delete(`${apiBaseUrl}/workflows/${workflowId}`, {
        headers: apiAuthHeaders()
      });
      expect(deleteResponse.ok()).toBeTruthy();
    }
  }
});
