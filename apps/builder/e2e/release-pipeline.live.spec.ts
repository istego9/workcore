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
  let initialVersionId: string | null = null;
  const suffix = Date.now();
  const projectId = `proj_release_live_${suffix}`;
  const projectName = `Release Live ${suffix}`;
  const workflowName = `Release Workflow ${suffix}`;
  const draft = {
    nodes: [
      { id: 'start', type: 'start', config: { ui: { x: 80, y: 120 } } },
      { id: 'end', type: 'end', config: { ui: { x: 360, y: 120 } } }
    ],
    edges: [{ source: 'start', target: 'end' }],
    variables_schema: {}
  };

  try {
    console.log('[release-live] create project');
    const createProjectResponse = await request.post(`${apiBaseUrl}/projects`, {
      data: { project_id: projectId, project_name: projectName, settings: { orchestrator_enabled: true } },
      headers: apiAuthHeaders()
    });
    expect(createProjectResponse.ok()).toBeTruthy();

    console.log('[release-live] create workflow');
    const createWorkflowResponse = await request.post(`${apiBaseUrl}/workflows`, {
      data: { name: workflowName, description: 'Live release pipeline workflow', draft },
      headers: apiAuthHeaders(projectId)
    });
    expect(createWorkflowResponse.ok()).toBeTruthy();
    const workflow = await createWorkflowResponse.json();
    workflowId = workflow.workflow_id;
    expect(workflowId).toBeTruthy();

    console.log('[release-live] publish initial version');
    const publishResponse = await request.post(`${apiBaseUrl}/workflows/${workflowId}/publish`, {
      headers: apiAuthHeaders(projectId)
    });
    expect(publishResponse.ok()).toBeTruthy();
    initialVersionId = (await publishResponse.json()).version_id;
    expect(initialVersionId).toBeTruthy();

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

    console.log('[release-live] open builder');
    await primeOperatorAuth(page, projectId);
    await page.goto(`/?e2e=1&project_id=${projectId}`);
    await expect(page.getByRole('button', { name: 'Back to projects' })).toBeVisible({ timeout: 10_000 });
    await page.getByRole('button', { name: 'Back to projects' }).click();
    await expect(page.getByText(`Project ${projectId}`).first()).toBeVisible({ timeout: 10_000 });
    const workflowCard = page
      .getByText(workflowName)
      .first()
      .locator('xpath=ancestor::div[contains(@class,"mantine-Card-root")]')
      .first();
    await expect(workflowCard).toBeVisible({ timeout: 10_000 });
    const workflowSelected = await page.evaluate(
      ({ workflowName, workflowId }) => {
        const cards = Array.from(document.querySelectorAll('div.mantine-Card-root'));
        const card = cards.find((element) => {
          const text = element.textContent || '';
          return text.includes(workflowName) && text.includes(workflowId);
        });
        if (!card) return false;
        (card as HTMLElement).click();
        return true;
      },
      { workflowName, workflowId }
    );
    expect(workflowSelected).toBe(true);
    const openStudio = page.getByRole('button', { name: 'Open Studio' });
    if ((await openStudio.count()) > 0) {
      await openStudio.click();
    }
    await expect(page.getByText(`Workflow ${workflowId}`).first()).toBeVisible({ timeout: 10_000 });
    await expect(page.getByRole('button', { name: 'Back to projects' })).toBeVisible({ timeout: 10_000 });

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
        return activeVersionText.includes(initialVersionId || '') ? 'same' : activeVersionText;
      })
      .not.toBe('same');

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
