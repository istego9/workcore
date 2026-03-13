import { expect, test } from '@playwright/test';

test('operator release pipeline validates, simulates, publishes, binds, smokes, and exports report', async ({
  page,
}) => {
  let activeVersionId = 'wfv_1';
  let projectDefaultChatWorkflowId: string | null = null;
  let simulationCalls = 0;
  let routingBindCalls = 0;
  let smokeStartCalls = 0;

  const workflowDraft = {
    nodes: [
      { id: 'start', type: 'start', config: {} },
      { id: 'end', type: 'end', config: {} },
    ],
    edges: [{ source: 'start', target: 'end' }],
    variables_schema: {},
  };

  const workflowRecord = () => ({
    workflow_id: 'wf_release_1',
    project_id: 'proj_release',
    name: 'Release Workflow',
    description: 'Release pipeline test workflow',
    draft: workflowDraft,
    active_version_id: activeVersionId,
    created_at: '2026-03-10T09:00:00Z',
    updated_at: '2026-03-10T09:00:00Z',
  });

  await page.route('**/*', async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    if (url.hostname !== 'api.localhost') {
      await route.continue();
      return;
    }
    const method = request.method();
    const path = url.pathname;
    const body = request.postData() ? JSON.parse(request.postData() || '{}') : null;
    const corsHeaders = {
      'access-control-allow-origin': '*',
      'access-control-allow-headers': '*',
      'access-control-allow-methods': 'GET,POST,PUT,PATCH,DELETE,OPTIONS',
    };
    const fulfillJson = async (status: number, payload: unknown) => {
      await route.fulfill({
        status,
        headers: {
          ...corsHeaders,
          'content-type': 'application/json',
        },
        body: JSON.stringify(payload),
      });
    };

    if (method === 'OPTIONS') {
      await route.fulfill({
        status: 204,
        headers: corsHeaders,
      });
      return;
    }

    if (path === '/projects' && method === 'GET') {
      await fulfillJson(200, {
        items: [
          {
            project_id: 'proj_release',
            project_name: 'Release Project',
            tenant_id: 'local',
            default_orchestrator_id: 'orc_default',
            settings: { default_chat_workflow_id: projectDefaultChatWorkflowId },
            created_at: '2026-03-10T09:00:00Z',
            updated_at: '2026-03-10T09:00:00Z',
          },
        ],
        next_cursor: null,
      });
      return;
    }

    if (path === '/projects/proj_release' && method === 'PATCH') {
      projectDefaultChatWorkflowId = body?.settings?.default_chat_workflow_id || null;
      await fulfillJson(200, {
        project_id: 'proj_release',
        project_name: 'Release Project',
        tenant_id: 'local',
        default_orchestrator_id: 'orc_default',
        settings: { default_chat_workflow_id: projectDefaultChatWorkflowId },
        created_at: '2026-03-10T09:00:00Z',
        updated_at: '2026-03-10T09:00:00Z',
      });
      return;
    }

    if (path === '/projects/proj_release/workflow-definitions' && method === 'POST') {
      routingBindCalls += 1;
      await fulfillJson(201, {
        project_id: 'proj_release',
        workflow_id: 'wf_release_1',
        name: 'Release Workflow',
        description: 'Release pipeline test workflow',
        tags: ['release-pipeline'],
        examples: ['start'],
        active: true,
        is_fallback: false,
        created_at: '2026-03-10T09:00:00Z',
        updated_at: '2026-03-10T09:00:00Z',
      });
      return;
    }

    if (path === '/workflows' && method === 'GET') {
      await fulfillJson(200, {
        items: [workflowRecord()],
        next_cursor: null,
      });
      return;
    }

    if (path === '/workflows' && method === 'POST') {
      await fulfillJson(200, workflowRecord());
      return;
    }

    if (path === '/workflows/wf_release_1/publish' && method === 'POST') {
      activeVersionId = 'wfv_2';
      await fulfillJson(200, {
        version_id: 'wfv_2',
        workflow_id: 'wf_release_1',
        version_number: 2,
        created_at: '2026-03-10T09:02:00Z',
      });
      return;
    }

    if (path === '/workflows/wf_release_1/versions' && method === 'GET') {
      await fulfillJson(200, {
        items: [
          {
            version_id: activeVersionId,
            workflow_id: 'wf_release_1',
            version_number: activeVersionId === 'wfv_1' ? 1 : 2,
            hash: 'hash_release',
            content: workflowDraft,
            created_at: '2026-03-10T09:00:00Z',
          },
        ],
        next_cursor: null,
      });
      return;
    }

    if (path === '/orchestrator/eval/replay' && method === 'POST') {
      simulationCalls += 1;
      await fulfillJson(200, {
        mode: 'offline_eval',
        project_id: 'proj_release',
        orchestrator_id: 'orc_default',
        session_id: 'release_pipeline_wf_release_1',
        user_id: 'release_operator',
        total_cases: 3,
        metrics: {
          cases_with_expected_action: 0,
          cases_with_expected_workflow: 3,
          cases_with_exact_expectations: 0,
          matched_action: 0,
          matched_workflow_id: 3,
          matched_exact: 0,
          action_accuracy: 0,
          workflow_accuracy: 1,
          exact_match_rate: 0,
          average_confidence: 0.92,
        },
        items: [
          {
            case_id: 'sample_start',
            message_text: 'start',
            expected_workflow_id: 'wf_release_1',
            chosen_action: 'START_WORKFLOW',
            chosen_workflow_id: 'wf_release_1',
            matched_workflow_id: true,
            matched_action: null,
            matched_exact: null,
            latency_ms: 13,
          },
          {
            case_id: 'sample_help',
            message_text: 'help me with this workflow',
            expected_workflow_id: 'wf_release_1',
            chosen_action: 'START_WORKFLOW',
            chosen_workflow_id: 'wf_release_1',
            matched_workflow_id: true,
            matched_action: null,
            matched_exact: null,
            latency_ms: 11,
          },
          {
            case_id: 'sample_continue',
            message_text: 'continue the current flow',
            expected_workflow_id: 'wf_release_1',
            chosen_action: 'CONTINUE',
            chosen_workflow_id: 'wf_release_1',
            matched_workflow_id: true,
            matched_action: null,
            matched_exact: null,
            latency_ms: 10,
          },
        ],
      });
      return;
    }

    if (path === '/workflows/wf_release_1/runs' && method === 'POST') {
      smokeStartCalls += 1;
      await fulfillJson(200, { run_id: 'run_smoke_1', status: 'RUNNING' });
      return;
    }

    if (path === '/runs' && method === 'GET') {
      await fulfillJson(200, {
        items: [
          {
            run_id: 'run_smoke_1',
            workflow_id: 'wf_release_1',
            version_id: activeVersionId,
            status: 'FAILED',
            project_id: 'proj_release',
            correlation_id: 'corr_smoke_1',
            created_at: '2026-03-10T09:03:00Z',
            updated_at: '2026-03-10T09:03:05Z',
            node_runs: [
              {
                node_id: 'agent_1',
                status: 'ERROR',
                last_error: 'smoke assertion failed',
              },
            ],
          },
        ],
        next_cursor: null,
      });
      return;
    }

    if (path === '/runs/run_smoke_1' && method === 'GET') {
      await fulfillJson(200, {
        run_id: 'run_smoke_1',
        workflow_id: 'wf_release_1',
        version_id: activeVersionId,
        status: 'FAILED',
        project_id: 'proj_release',
        correlation_id: 'corr_smoke_1',
        created_at: '2026-03-10T09:03:00Z',
        updated_at: '2026-03-10T09:03:05Z',
        node_runs: [
          {
            node_id: 'agent_1',
            status: 'ERROR',
            last_error: 'smoke assertion failed',
          },
        ],
      });
      return;
    }

    if (path === '/runs/run_smoke_1/ledger' && method === 'GET') {
      await fulfillJson(200, { items: [], next_cursor: null });
      return;
    }

    if (path === '/runs/run_smoke_1/rerun-node' && method === 'POST') {
      await fulfillJson(200, {
        run_id: 'run_smoke_1',
        workflow_id: 'wf_release_1',
        version_id: activeVersionId,
        status: 'RUNNING',
        project_id: 'proj_release',
      });
      return;
    }

    if (path === '/runs/run_smoke_1/cancel' && method === 'POST') {
      await fulfillJson(200, {
        run_id: 'run_smoke_1',
        workflow_id: 'wf_release_1',
        version_id: activeVersionId,
        status: 'CANCELLED',
        project_id: 'proj_release',
      });
      return;
    }

    await fulfillJson(404, {
      error: { code: 'NOT_FOUND', message: `${method} ${path}` },
    });
  });

  await page.goto('/?view=builder&e2e=1&project_id=proj_release');

  await page.getByRole('button', { name: 'New' }).click();
  await expect(page.getByText('Workflow wf_release_1').first()).toBeVisible();

  await page.getByTestId('open-release-pipeline').click();
  const releaseDrawer = page.getByRole('dialog', { name: 'Release Pipeline' });
  await expect(releaseDrawer).toBeVisible();

  await releaseDrawer.getByTestId('release-validate-rerun').click();
  await releaseDrawer.getByTestId('release-simulation-run').click();
  await expect.poll(() => simulationCalls).toBe(1);

  const publishButton = releaseDrawer.getByTestId('release-publish');
  await expect(publishButton).toBeEnabled();
  await publishButton.click();
  await expect(releaseDrawer.getByText('Active version: wfv_2')).toBeVisible();

  await releaseDrawer.getByTestId('release-bind-chat').click();
  await releaseDrawer.getByTestId('release-bind-routing').click();
  await expect.poll(() => routingBindCalls).toBeGreaterThan(0);

  await releaseDrawer.getByTestId('release-smoke-run').click();
  await expect.poll(() => smokeStartCalls).toBe(1);
  await expect(releaseDrawer.getByText('Run run_smoke_1')).toBeVisible();

  await releaseDrawer.getByTestId('release-open-run-debug').click();
  await expect(page.getByText('Run summary', { exact: true })).toBeVisible();

  const downloadPromise = page.waitForEvent('download');
  await releaseDrawer.getByTestId('release-report-export').click();
  const download = await downloadPromise;
  expect(download.suggestedFilename()).toContain('wf_release_1-release-report-');
});
