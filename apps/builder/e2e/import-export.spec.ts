import { expect, test } from '@playwright/test';
import { promises as fs } from 'fs';
import os from 'os';
import path from 'path';
import {
  apiAuthHeaders,
  apiBaseUrl,
  e2eApiAuthToken,
  e2eTenantId,
  installApiAuthRoute
} from './env';

test('workflow export and import create a new workflow', async ({ page, request }) => {
  let workflowId: string | null = null;
  let importedWorkflowId: string | null = null;
  let exportPath: string | null = null;
  const projectId = `proj_export_${Date.now()}`;

  const draft = {
    nodes: [
      { id: 'start', type: 'start', config: { ui: { x: 80, y: 120 } } },
      { id: 'end', type: 'end', config: { ui: { x: 360, y: 120 } } }
    ],
    edges: [{ source: 'start', target: 'end' }],
    variables_schema: {}
  };

  try {
    const workflowName = `E2E Export ${Date.now()}`;
    const createResponse = await request.post(`${apiBaseUrl}/workflows`, {
      data: { name: workflowName, draft },
      headers: apiAuthHeaders(projectId)
    });
    expect(createResponse.ok()).toBeTruthy();
    const workflow = await createResponse.json();
    workflowId = workflow.workflow_id;
    expect(workflowId).toBeTruthy();

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
    await modal.getByRole('button', { name: 'Refresh' }).click();
    await modal.getByPlaceholder('Search by name or id').fill(workflowName);
    await modal.getByText(`${workflowName}`).waitFor({ timeout: 10000 });
    await modal.getByText(`${workflowName}`).click();
    await expect(modal).toBeHidden({ timeout: 10000 });
    await expect(page.getByText(`Workflow ${workflowId}`)).toBeVisible();

    await page.evaluate(() => {
      const item = document.querySelector('[data-testid="export-workflow"]');
      if (item instanceof HTMLElement) {
        item.click();
      }
    });
    await page.getByText('Export ready').waitFor({ timeout: 10000 });

    exportPath = path.join(os.tmpdir(), `workflow-export-${Date.now()}.json`);
    const exportPayload = {
      schema_version: 'workflow_export_v1',
      exported_at: new Date().toISOString(),
      source: { workflow_id: workflowId, active_version_id: workflow.active_version_id ?? null },
      workflow: { name: workflowName, description: workflow.description ?? '' },
      draft
    };
    await fs.writeFile(exportPath, JSON.stringify(exportPayload, null, 2));

    const importInput = page.getByTestId('import-workflow-input');
    await importInput.setInputFiles(exportPath!);
    await page.getByText('Import completed').waitFor({ timeout: 10000 });

    const header = await page.getByText(/Workflow wf_/).textContent();
    importedWorkflowId = header?.replace('Workflow ', '').trim() || null;
    expect(importedWorkflowId).toBeTruthy();
    expect(importedWorkflowId).not.toBe(workflowId);
  } finally {
    if (workflowId) {
      const deleteResponse = await request.delete(`${apiBaseUrl}/workflows/${workflowId}`, {
        headers: apiAuthHeaders(projectId)
      });
      expect(deleteResponse.ok()).toBeTruthy();
    }
    if (importedWorkflowId) {
      const deleteResponse = await request.delete(`${apiBaseUrl}/workflows/${importedWorkflowId}`, {
        headers: apiAuthHeaders(projectId)
      });
      expect(deleteResponse.ok()).toBeTruthy();
    }
    if (exportPath) {
      await fs.unlink(exportPath).catch(() => undefined);
    }
  }
});
