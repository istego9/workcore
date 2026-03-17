import { expect, test } from '@playwright/test';

test('open run debug from execution history, rerun node, and export support bundle', async ({ page }) => {
  const runBase = {
    run_id: 'run_1',
    workflow_id: 'wf_1',
    version_id: 'ver_1',
    status: 'FAILED',
    mode: 'live',
    project_id: 'proj_ops',
    correlation_id: 'corr_1',
    inputs: {
      auth_token: 'secret-token',
      documents: [
        {
          doc_id: 'doc_1',
          pages: [{ content: 'raw-inline-content' }],
        },
      ],
    },
    metadata: {
      project_id: 'proj_ops',
      webhook_signature: 'signature-secret',
    },
    created_at: '2026-03-01T10:00:00Z',
    updated_at: '2026-03-01T10:05:00Z',
    node_runs: [
      {
        node_id: 'extract',
        status: 'ERROR',
        attempt: 1,
        output: {
          artifact_ref: 'art_1',
          content: 'raw-node-output',
        },
        last_error: 'timeout',
        trace_id: 'trace_extract',
        usage: { input_tokens: 4, output_tokens: 2, total_tokens: 6 }
      }
    ]
  };

  const ledgerItems = [
    {
      ledger_id: 'led_1',
      run_id: 'run_1',
      workflow_id: 'wf_1',
      version_id: 'ver_1',
      status: 'RUNNING',
      event_type: 'run_started',
      payload: {},
      artifacts: [],
      timestamp: '2026-03-01T10:00:01Z'
    },
    {
      ledger_id: 'led_2',
      run_id: 'run_1',
      workflow_id: 'wf_1',
      version_id: 'ver_1',
      status: 'IN_PROGRESS',
      event_type: 'node_started',
      node_id: 'extract',
      step_id: 'extract',
      payload: { access_token: 'token-should-redact' },
      artifacts: [],
      timestamp: '2026-03-01T10:00:02Z'
    },
    {
      ledger_id: 'led_3',
      run_id: 'run_1',
      workflow_id: 'wf_1',
      version_id: 'ver_1',
      status: 'ERROR',
      event_type: 'node_failed',
      node_id: 'extract',
      step_id: 'extract',
      payload: { error: 'timeout', body: 'raw-inline-body' },
      artifacts: [],
      timestamp: '2026-03-01T10:00:03Z'
    },
    {
      ledger_id: 'led_4',
      run_id: 'run_1',
      workflow_id: 'wf_1',
      version_id: 'ver_1',
      status: 'FAILED',
      event_type: 'run_failed',
      node_id: 'extract',
      step_id: 'extract',
      payload: { error: 'timeout', node_id: 'extract' },
      artifacts: [],
      timestamp: '2026-03-01T10:00:04Z'
    }
  ];

  let rerunCalls = 0;

  await page.route('**/*', async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    if (url.hostname !== 'api.localhost') {
      await route.continue();
      return;
    }

    const corsHeaders = {
      'access-control-allow-origin': '*',
      'access-control-allow-headers': '*',
      'access-control-allow-methods': 'GET,POST,PUT,PATCH,DELETE,OPTIONS'
    };
    const fulfillJson = async (status: number, payload: unknown) => {
      await route.fulfill({
        status,
        headers: {
          ...corsHeaders,
          'content-type': 'application/json'
        },
        body: JSON.stringify(payload)
      });
    };

    if (request.method() === 'OPTIONS') {
      await route.fulfill({
        status: 204,
        headers: corsHeaders
      });
      return;
    }

    if (url.pathname === '/projects' && request.method() === 'GET') {
      await fulfillJson(200, {
        items: [
          {
            project_id: 'proj_ops',
            project_name: 'Ops',
            tenant_id: 'tenant_1',
            settings: {},
            created_at: '2026-03-01T10:00:00Z',
            updated_at: '2026-03-01T10:00:00Z'
          }
        ],
        next_cursor: null
      });
      return;
    }

    if (url.pathname === '/workflows' && request.method() === 'GET') {
      await fulfillJson(200, { items: [], next_cursor: null });
      return;
    }

    if (url.pathname === '/runs' && request.method() === 'GET') {
      await fulfillJson(200, { items: [runBase], next_cursor: null });
      return;
    }

    if (url.pathname === '/runs/run_1/ledger' && request.method() === 'GET') {
      await fulfillJson(200, { items: ledgerItems, next_cursor: null });
      return;
    }

    if (url.pathname === '/runs/run_1/rerun-node' && request.method() === 'POST') {
      rerunCalls += 1;
      await fulfillJson(200, {
        ...runBase,
        status: 'RUNNING',
        node_runs: [
          {
            node_id: 'extract',
            status: 'IN_PROGRESS',
            attempt: 1,
            output: null,
            last_error: null,
            trace_id: 'trace_extract',
            usage: { input_tokens: 4, output_tokens: 2, total_tokens: 6 }
          }
        ]
      });
      return;
    }

    if (url.pathname === '/runs/run_1/cancel' && request.method() === 'POST') {
      await fulfillJson(200, { ...runBase, status: 'CANCELLED' });
      return;
    }

    if (url.pathname === '/runs/run_1' && request.method() === 'GET') {
      await fulfillJson(200, runBase);
      return;
    }

    await route.continue();
  });

  await page.goto('/?view=builder&e2e=1&project_id=proj_ops');

  const historyButton = page.getByRole('button', { name: 'History' });
  if ((await historyButton.count()) === 0) {
    const openStudio = page.getByRole('button', { name: 'Open Studio' });
    if ((await openStudio.count()) > 0) {
      await openStudio.click();
    }
  }
  await expect(historyButton).toBeVisible();
  await historyButton.click();
  const historyModal = page.getByRole('dialog', { name: 'Execution history' });
  await expect(historyModal).toBeVisible();

  await expect(historyModal.getByText('run_1')).toBeVisible();
  await historyModal.getByTestId('open-run-debug-run_1').click();

  await expect(page.getByText('Run summary', { exact: true })).toBeVisible();
  await expect(page.getByText('Timeline', { exact: true })).toBeVisible();
  await expect(page.getByText('Node attempts', { exact: true })).toBeVisible();
  await expect(page.getByText('Support bundle export', { exact: true })).toBeVisible();

  const downloadPromise = page.waitForEvent('download');
  await page.getByRole('button', { name: 'Export support bundle' }).click();
  const download = await downloadPromise;
  expect(download.suggestedFilename()).toContain('run-run_1-support-bundle.json');

  const rerunButton = page.getByRole('button', { name: 'Rerun node' }).first();
  await rerunButton.click();
  await expect.poll(() => rerunCalls).toBeGreaterThan(0);
});
