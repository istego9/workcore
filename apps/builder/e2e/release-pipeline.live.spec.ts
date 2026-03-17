import { expect, test } from '@playwright/test';
import { apiAuthHeaders, apiBaseUrl } from './env';
import { deleteProjectIfExists, deleteWorkflowIfExists } from './cleanup';
import { primeOperatorAuth, readDownloadedJson } from './operator-live-utils';

test.setTimeout(90_000);

test('@operator-live operator release pipeline uses live API state and exports a real release report', async ({
  page,
  request
}) => {
  let workflowId: string | null = null;
  const suffix = Date.now();
  const projectId = `proj_release_live_${suffix}`;
  const projectName = `Release Live ${suffix}`;
  let workflowName = '';

  try {
    console.log('[release-live] create project');
    const createProjectResponse = await request.post(`${apiBaseUrl}/projects`, {
      data: { project_id: projectId, project_name: projectName, settings: { orchestrator_enabled: true } },
      headers: apiAuthHeaders()
    });
    expect(createProjectResponse.ok()).toBeTruthy();

    console.log('[release-live] open builder');
    await primeOperatorAuth(page, projectId);
    await page.goto(`/?e2e=1&project_id=${projectId}`);
    await expect(page.getByRole('button', { name: 'Back to projects' })).toBeVisible({ timeout: 10_000 });
    await page.getByRole('button', { name: 'New' }).click();
    await expect
      .poll(async () => {
        const text = await page.locator('body').innerText();
        const match = text.match(/Workflow (wf_[a-z0-9]+)/);
        return match ? match[1] : '';
      })
      .not.toBe('');
    const bodyText = await page.locator('body').innerText();
    const workflowMatch = bodyText.match(/Workflow (wf_[a-z0-9]+)/);
    workflowId = workflowMatch?.[1] || workflowId;
    expect(workflowId).toBeTruthy();
    workflowName = workflowId!;

    console.log('[release-live] upsert orchestrator');
    const orchestratorResponse = await request.post(`${apiBaseUrl}/projects/${projectId}/orchestrators`, {
      data: {
        orchestrator_id: 'orc_default',
        name: 'Default orchestrator',
        routing_policy: {
          confidence_threshold: 0.1,
          switch_margin: 0.05,
          max_disambiguation_turns: 1,
          top_k_candidates: 10,
          allow_switch: true
        },
        fallback_workflow_id: workflowId,
        prompt_profile: 'default',
        set_as_default: true
      },
      headers: apiAuthHeaders()
    });
    expect(orchestratorResponse.ok()).toBeTruthy();

    console.log('[release-live] seed routing definition');
    const bindResponse = await request.post(`${apiBaseUrl}/projects/${projectId}/workflow-definitions`, {
      data: {
        workflow_id: workflowId,
        name: workflowName,
        description: 'Live release pipeline routing definition',
        tags: ['release', 'live'],
        examples: ['start', 'help me with this workflow', 'continue the current flow'],
        active: true,
        is_fallback: false
      },
      headers: apiAuthHeaders()
    });
    expect(bindResponse.ok()).toBeTruthy();

    console.log('[release-live] open release drawer');
    await expect(page.getByTestId('open-release-pipeline')).toBeVisible();
    await page.getByTestId('open-release-pipeline').click();
    let releaseDrawer = page.getByRole('dialog', { name: 'Release Pipeline' });
    await expect(releaseDrawer).toBeVisible();
    await expect(releaseDrawer.getByTestId('release-routing-readback-status')).toContainText('Routing definition bound');

    console.log('[release-live] run validation/simulation');
    await releaseDrawer.getByTestId('release-validate-rerun').click();
    await releaseDrawer.getByTestId('release-simulation-run').click();
    await expect(releaseDrawer.getByText('Route/action outcomes')).toBeVisible({ timeout: 15_000 });

    console.log('[release-live] publish candidate');
    await releaseDrawer.getByTestId('release-publish').click();
    await expect
      .poll(async () => {
        const activeVersionText = (await releaseDrawer.getByText(/Active version:/).textContent()) || '';
        return activeVersionText;
      })
      .toContain('wfv_');

    console.log('[release-live] bind chat + routing');
    await releaseDrawer.getByTestId('release-bind-chat').click();
    await expect(releaseDrawer.getByText('Default chat bound')).toBeVisible({ timeout: 10_000 });
    await releaseDrawer.getByTestId('release-bind-routing').click();
    await expect(releaseDrawer.getByTestId('release-routing-readback-status')).toContainText('Routing definition bound');

    console.log('[release-live] reopen drawer');
    await releaseDrawer.getByRole('button', { name: 'Close' }).click();
    await page.getByTestId('open-release-pipeline').click();
    releaseDrawer = page.getByRole('dialog', { name: 'Release Pipeline' });
    await expect(releaseDrawer.getByTestId('release-routing-readback-status')).toContainText('Routing definition bound');

    console.log('[release-live] smoke run');
    await releaseDrawer.getByTestId('release-smoke-run').click();
    await expect(releaseDrawer.getByText(/^Run run_/)).toBeVisible({ timeout: 15_000 });
    await expect(releaseDrawer.getByTestId('release-open-run-debug')).toBeEnabled();

    console.log('[release-live] export report');
    const reportDownloadPromise = page.waitForEvent('download');
    await releaseDrawer.getByTestId('release-report-export').click();
    const report = await readDownloadedJson<any>(await reportDownloadPromise, 'release-report');
    expect(report.validation_result).toEqual(expect.objectContaining({ passed: true }));
    expect(report.simulation_result).toEqual(expect.objectContaining({ status: 'passed' }));
    expect(report.bind_targets).toEqual(
      expect.objectContaining({
        project_default_chat_workflow_id: workflowId,
        routing_definition_registered: true
      })
    );
    expect(Array.isArray(report.run_ids)).toBe(true);
    expect(report.run_ids.length).toBeGreaterThan(0);
    expect(Array.isArray(report.correlation_ids)).toBe(true);
    expect(report.smoke_result).toEqual(expect.objectContaining({ run_id: report.run_ids[0] }));

    console.log('[release-live] open run debug');
    await releaseDrawer.getByTestId('release-open-run-debug').click();
    await expect(page.getByText('Run summary', { exact: true })).toBeVisible({ timeout: 10_000 });
  } finally {
    await deleteWorkflowIfExists(request, projectId, workflowId);
    await deleteProjectIfExists(request, projectId);
  }
});
