import { expect, test } from '@playwright/test';
import {
  apiAuthHeaders,
  apiBaseUrl,
  e2eApiAuthToken,
  e2eTenantId,
  installApiAuthRoute
} from './env';
import { deleteProjectIfExists, deleteWorkflowIfExists } from './cleanup';

test('explorer shows tenant projects and opens workflow', async ({ page, request }) => {
  let workflowId: string | null = null;
  const projectId = `proj_selector_${Date.now()}`;
  const projectName = `Selector ${Date.now()}`;
  const workflowName = `Selector Workflow ${Date.now()}`;
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

    const createWorkflowResponse = await request.post(`${apiBaseUrl}/workflows`, {
      data: { name: workflowName, draft },
      headers: apiAuthHeaders(projectId)
    });
    expect(createWorkflowResponse.ok()).toBeTruthy();
    const workflow = await createWorkflowResponse.json();
    workflowId = workflow?.workflow_id || null;
    expect(workflowId).toBeTruthy();

    await installApiAuthRoute(page);
    await page.addInitScript(
      ({ token, tenant }) => {
        if (token) window.localStorage.setItem('workcore.api_auth_token', token);
        if (tenant) window.localStorage.setItem('workcore.tenant_id', tenant);
      },
      { token: e2eApiAuthToken, tenant: e2eTenantId }
    );
    await page.goto('/?e2e=1');

    await page.getByRole('button', { name: 'Back to projects' }).click();
    await expect(page.getByText('Scope Selection')).toBeVisible();
    await page.getByText(projectName).first().click();
    await expect(page.getByText(workflowName)).toBeVisible({ timeout: 10000 });
    await page.getByText(workflowName).first().click();
    await expect(page.getByText(`Workflow ${workflow.workflow_id}`).first()).toBeVisible({ timeout: 10000 });
  } finally {
    await deleteWorkflowIfExists(request, projectId, workflowId);
    await deleteProjectIfExists(request, projectId);
  }
});

test('explorer supports project edit and delete with confirmation', async ({ page, request }) => {
  const suffix = Date.now();
  const projectId = `proj_manage_${suffix}`;
  const projectName = `Manage Project ${suffix}`;
  const renamedProjectName = `Manage Project Renamed ${suffix}`;

  try {
    const createProjectResponse = await request.post(`${apiBaseUrl}/projects`, {
      data: { project_id: projectId, project_name: projectName, settings: { orchestrator_enabled: true } },
      headers: apiAuthHeaders()
    });
    expect(createProjectResponse.ok()).toBeTruthy();

    await installApiAuthRoute(page);
    await page.addInitScript(
      ({ token, tenant }) => {
        if (token) window.localStorage.setItem('workcore.api_auth_token', token);
        if (tenant) window.localStorage.setItem('workcore.tenant_id', tenant);
      },
      { token: e2eApiAuthToken, tenant: e2eTenantId }
    );
    await page.goto('/?e2e=1');
    await page.getByRole('button', { name: 'Back to projects' }).click();

    await expect(page.getByText(projectName).first()).toBeVisible({ timeout: 10000 });
    await page.getByTestId(`edit-project-${projectId}`).first().click();
    await page.getByTestId('edit-project-name-input').fill(renamedProjectName);
    await page.getByTestId('edit-project-confirm').click();
    await expect(page.getByText(renamedProjectName).first()).toBeVisible({ timeout: 10000 });

    await page.getByTestId(`delete-project-${projectId}`).first().click();
    await expect(page.getByRole('dialog', { name: 'Delete project?' })).toBeVisible();
    await page.getByRole('button', { name: 'Cancel' }).click();
    await expect(page.getByText(renamedProjectName).first()).toBeVisible();

    await page.getByTestId(`delete-project-${projectId}`).first().click();
    await page.getByTestId('delete-project-confirm').click();
    await expect(page.getByText(renamedProjectName).first()).not.toBeVisible({ timeout: 10000 });
  } finally {
    await deleteProjectIfExists(request, projectId);
  }
});

test('explorer configures and displays the project default chat workflow', async ({ page, request }) => {
  let workflowId: string | null = null;
  const suffix = Date.now();
  const projectId = `proj_chat_default_${suffix}`;
  const projectName = `Chat Default ${suffix}`;
  const workflowName = `Project Chat ${suffix}`;
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

    const createWorkflowResponse = await request.post(`${apiBaseUrl}/workflows`, {
      data: { name: workflowName, draft },
      headers: apiAuthHeaders(projectId)
    });
    expect(createWorkflowResponse.ok()).toBeTruthy();
    const workflow = await createWorkflowResponse.json();
    workflowId = workflow?.workflow_id || null;
    expect(workflowId).toBeTruthy();

    const publishResponse = await request.post(`${apiBaseUrl}/workflows/${workflowId}/publish`, {
      headers: apiAuthHeaders(projectId)
    });
    expect(publishResponse.ok()).toBeTruthy();

    await installApiAuthRoute(page);
    await page.addInitScript(
      ({ token, tenant }) => {
        if (token) window.localStorage.setItem('workcore.api_auth_token', token);
        if (tenant) window.localStorage.setItem('workcore.tenant_id', tenant);
      },
      { token: e2eApiAuthToken, tenant: e2eTenantId }
    );
    await page.goto('/?e2e=1');
    await page.getByRole('button', { name: 'Back to projects' }).click();

    await expect(page.getByText(projectName).first()).toBeVisible({ timeout: 10000 });
    await page.getByTestId(`edit-project-${projectId}`).first().click();
    await page.getByLabel('Default chat workflow').click();
    await page.getByRole('option', { name: `${workflowName} (${workflowId})` }).click();
    await page.getByTestId('edit-project-confirm').click();

    await expect(page.getByText(`Project chat: ${workflowName}`).first()).toBeVisible({ timeout: 10000 });
    await page.getByText(projectName).first().click();
    await expect(page.getByTestId(`project-chat-workflow-${workflowId}`).first()).toBeVisible({
      timeout: 10000
    });
  } finally {
    await deleteWorkflowIfExists(request, projectId, workflowId);
    await deleteProjectIfExists(request, projectId);
  }
});
