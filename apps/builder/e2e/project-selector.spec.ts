import { expect, test } from '@playwright/test';
import {
  apiAuthHeaders,
  apiBaseUrl,
  e2eApiAuthToken,
  e2eTenantId,
  installApiAuthRoute
} from './env';

test('project selector dropdown shows tenant projects', async ({ page, request }) => {
  const projectId = `proj_selector_${Date.now()}`;
  const projectName = `Selector ${Date.now()}`;

  const createProjectResponse = await request.post(`${apiBaseUrl}/projects`, {
    data: { project_id: projectId, project_name: projectName, settings: { orchestrator_enabled: true } },
    headers: apiAuthHeaders()
  });
  expect(createProjectResponse.ok()).toBeTruthy();
  const createProjectPayload = await createProjectResponse.json();
  const expectedProjectOptionLabel =
    typeof createProjectPayload?.project_name === 'string' && createProjectPayload.project_name.trim()
      ? createProjectPayload.project_name.trim()
      : projectId;

  await installApiAuthRoute(page);
  await page.addInitScript(
    ({ token, tenant }) => {
      if (token) window.localStorage.setItem('workcore.api_auth_token', token);
      if (tenant) window.localStorage.setItem('workcore.tenant_id', tenant);
    },
    { token: e2eApiAuthToken, tenant: e2eTenantId }
  );
  await page.goto('/?e2e=1');

  const projectSelector = page.getByTestId('project-selector');
  await projectSelector.click();
  const projectNameOption = page.getByRole('option', { name: new RegExp(expectedProjectOptionLabel) });
  await expect(projectNameOption).toBeVisible({ timeout: 10000 });

  await projectNameOption.click();
  await expect(projectSelector).toHaveValue(projectId);
});
