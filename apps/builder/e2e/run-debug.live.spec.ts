import { expect, test } from '@playwright/test';
import { apiAuthHeaders, apiBaseUrl } from './env';
import { deleteProjectIfExists, deleteWorkflowIfExists } from './cleanup';
import { primeOperatorAuth, readDownloadedJson, waitForRunTerminal } from './operator-live-utils';

test.setTimeout(90_000);

test('@operator-live run debug exports a live redacted support bundle with completeness markers', async ({
  page,
  request
}) => {
  let workflowId: string | null = null;
  let runId: string | null = null;
  const suffix = Date.now();
  const projectId = `proj_run_debug_live_${suffix}`;
  const projectName = `Run Debug ${suffix}`;
  let workflowName = '';
  let versionId: string | null = null;

  try {
    console.log('[run-debug-live] create project');
    const createProjectResponse = await request.post(`${apiBaseUrl}/projects`, {
      data: { project_id: projectId, project_name: projectName, settings: { orchestrator_enabled: true } },
      headers: apiAuthHeaders()
    });
    expect(createProjectResponse.ok()).toBeTruthy();

    console.log('[run-debug-live] open builder');
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
    const workflowMatch = (await page.locator('body').innerText()).match(/Workflow (wf_[a-z0-9]+)/);
    workflowId = workflowMatch?.[1] || null;
    expect(workflowId).toBeTruthy();
    workflowName = workflowId!;

    console.log('[run-debug-live] publish version');
    const publishResponse = await request.post(`${apiBaseUrl}/workflows/${workflowId}/publish`, {
      headers: apiAuthHeaders(projectId)
    });
    expect(publishResponse.ok()).toBeTruthy();
    versionId = (await publishResponse.json()).version_id;
    expect(versionId).toBeTruthy();

    console.log('[run-debug-live] start run');
    const runResponse = await request.post(`${apiBaseUrl}/workflows/${workflowId}/runs`, {
      data: {
        inputs: {
          auth_token: 'secret-token',
          documents: [
            {
              doc_id: 'doc_1',
              pages: [{ content: 'raw-inline-content' }]
            }
          ]
        },
        version_id: versionId,
        mode: 'test'
      },
      headers: apiAuthHeaders(projectId)
    });
    expect(runResponse.ok()).toBeTruthy();
    runId = (await runResponse.json()).run_id;
    expect(runId).toBeTruthy();

    console.log('[run-debug-live] wait for terminal');
    await waitForRunTerminal(request, apiBaseUrl, projectId, runId!);

    console.log('[run-debug-live] open history');
    const historyButton = page.getByRole('button', { name: 'History' });
    await expect(historyButton).toBeVisible();
    await historyButton.click();
    const historyModal = page.getByRole('dialog', { name: 'Execution history' });
    await expect(historyModal).toBeVisible();
    await expect(historyModal.getByText(runId!)).toBeVisible({ timeout: 10_000 });

    console.log('[run-debug-live] open run debug');
    await historyModal.getByTestId(`open-run-debug-${runId}`).click();
    await expect(page.getByText('Run summary', { exact: true })).toBeVisible({ timeout: 10_000 });
    await expect(page.getByText('Support bundle export', { exact: true })).toBeVisible();

    console.log('[run-debug-live] export support bundle');
    const downloadPromise = page.waitForEvent('download');
    await page.getByRole('button', { name: 'Export support bundle' }).click();
    const bundle = await readDownloadedJson<any>(await downloadPromise, 'support-bundle');

    expect(bundle.bundle_type).toBe('run_support_bundle');
    expect(bundle.docs_links).toEqual([
      `${apiBaseUrl}/openapi.yaml`,
      `${apiBaseUrl}/workflow-authoring-guide`
    ]);
    expect(bundle.run_summary.run_id).toBe(runId);
    expect(bundle.run_summary.project_id).toBe(projectId);
    expect(bundle).toEqual(
      expect.objectContaining({
        ledger_truncated: expect.any(Boolean),
        ledger_entries_included: expect.any(Number),
        ledger_entries_available: expect.any(Number),
        ledger_entries_available_exact: expect.any(Boolean)
      })
    );

    const bundleJson = JSON.stringify(bundle);
    expect(bundleJson).not.toContain('secret-token');
    expect(bundleJson).not.toContain('raw-inline-content');
    expect(bundleJson).toContain('[REDACTED_SECRET]');
  } finally {
    await deleteWorkflowIfExists(request, projectId, workflowId);
    await deleteProjectIfExists(request, projectId);
  }
});
