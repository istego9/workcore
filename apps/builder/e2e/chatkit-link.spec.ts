import { expect, test } from '@playwright/test';
import { apiAuthHeaders, apiBaseUrl, chatkitApiUrl, resolveUrl } from './env';

test('open chat button builds chatkit url', async ({ page, request }) => {
  let workflowId: string | null = null;
  let versionId: string | null = null;
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
    const version = await publishResponse.json();
    versionId = version.version_id;

    await page.goto('/?e2e=1');
    await page.getByRole('button', { name: 'Browse' }).click();
    const modal = page.getByRole('dialog', { name: 'Workflows' });
    await modal.getByRole('button', { name: 'Refresh' }).click();
    await modal.getByPlaceholder('Search by name or id').fill(workflowName);
    await modal.getByText(`${workflowName}`).waitFor({ timeout: 10000 });
    await modal.getByText(`${workflowName}`).click();
    await expect(modal).toBeHidden({ timeout: 10000 });

    await expect(page.getByText(`Workflow ${workflowId}`)).toBeVisible();

    const openChatButton = page.getByTestId('open-chatkit');
    const dataUrl = await openChatButton.getAttribute('data-chatkit-url');
    expect(dataUrl).toBeTruthy();
    await expect(page.getByTestId('chat-link')).toHaveValue(dataUrl!);
    const url = new URL(dataUrl!);
    expect(url.pathname.endsWith('/chatkit.html')).toBeTruthy();
    expect(url.searchParams.get('workflow_id')).toBe(workflowId);
    expect(url.searchParams.get('workflow_version_id')).toBe(versionId);
    const apiUrlParam = url.searchParams.get('api_url');
    expect(apiUrlParam).toBeTruthy();
    const expectedChatkitApi = resolveUrl(chatkitApiUrl);
    const actualChatkitApi = new URL(apiUrlParam!, url.origin);
    expect(actualChatkitApi.host).toBe(expectedChatkitApi.host);
    expect(actualChatkitApi.pathname).toBe(expectedChatkitApi.pathname);
  } finally {
    if (workflowId) {
      const deleteResponse = await request.delete(`${apiBaseUrl}/workflows/${workflowId}`, {
        headers: apiAuthHeaders()
      });
      expect(deleteResponse.ok()).toBeTruthy();
    }
  }
});
