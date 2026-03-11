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
    created_at: '2026-03-01T10:00:00Z',
    updated_at: '2026-03-01T10:05:00Z',
    node_runs: [
      {
        node_id: 'extract',
        status: 'ERROR',
        attempt: 1,
        output: null,
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
      payload: {},
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
      payload: { error: 'timeout' },
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

  await page.route('**/projects**', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
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
      })
    });
  });

  await page.route('**/workflows**', async (route) => {
    if (route.request().method() !== 'GET') {
      await route.continue();
      return;
    }
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ items: [], next_cursor: null })
    });
  });

  await page.route('**/runs?**', async (route) => {
    if (route.request().method() !== 'GET') {
      await route.continue();
      return;
    }
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ items: [runBase], next_cursor: null })
    });
  });

  await page.route('**/runs/run_1/ledger**', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ items: ledgerItems, next_cursor: null })
    });
  });

  await page.route('**/runs/run_1/rerun-node', async (route) => {
    rerunCalls += 1;
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
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
      })
    });
  });

  await page.route('**/runs/run_1/cancel', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ ...runBase, status: 'CANCELLED' })
    });
  });

  await page.route('**/runs/run_1', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(runBase)
    });
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

  const rerunButton = page.getByRole('button', { name: 'Rerun node' }).first();
  await rerunButton.click();
  await expect.poll(() => rerunCalls).toBeGreaterThan(0);

  const downloadPromise = page.waitForEvent('download');
  await page.getByRole('button', { name: 'Export support bundle' }).click();
  const download = await downloadPromise;
  expect(download.suggestedFilename()).toContain('run-run_1-support-bundle.json');
});
