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
  const projectName = `Export Project ${Date.now()}`;

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
    await page.getByRole('button', { name: 'Back to projects' }).click();
    await page.getByText(projectName).first().click();
    await page.getByText(workflowName).first().click();
    await expect(page.getByText(`Workflow ${workflowId}`).first()).toBeVisible();

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

    const header = await page.getByText(/Workflow wf_/).first().textContent();
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
