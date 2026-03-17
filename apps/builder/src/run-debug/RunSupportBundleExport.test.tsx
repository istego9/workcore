import { MantineProvider } from '@mantine/core';
import { fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { RunLedgerRecord, RunRecord } from '../api';
import { normalizeRunDebugData } from './model';
import { RunSupportBundleExport } from './RunSupportBundleExport';

vi.mock('../api', async () => {
  const actual = await vi.importActual<typeof import('../api')>('../api');
  return {
    ...actual,
    API_BASE: 'http://api.localhost',
  };
});

const originalCreateObjectURL = URL.createObjectURL;
const originalRevokeObjectURL = URL.revokeObjectURL;

const runFixture: RunRecord = {
  run_id: 'run_1',
  workflow_id: 'wf_1',
  version_id: 'ver_1',
  status: 'FAILED',
  mode: 'live',
  inputs: {
    auth_token: 'secret-token',
    documents: [
      {
        doc_id: 'doc_1',
        pages: [{ content: 'raw-inline-content' }],
      },
    ],
  },
  outputs: null,
  metadata: {
    tenant_id: 'tenant_1',
    project_id: 'proj_1',
    correlation_id: 'corr_1',
    webhook_signature: 'signature-secret',
  },
  created_at: '2026-03-01T10:00:00Z',
  updated_at: '2026-03-01T10:05:00Z',
  node_runs: [
    {
      node_id: 'extract',
      status: 'ERROR',
      attempt: 1,
      output: { artifact_ref: 'art_1', content: 'raw-node-output' },
      last_error: 'timeout',
      usage: { total_tokens: 6 },
      trace_id: 'trace_extract',
    },
  ],
};

const ledgerFixture: RunLedgerRecord[] = [
  {
    ledger_id: 'led_1',
    run_id: 'run_1',
    workflow_id: 'wf_1',
    version_id: 'ver_1',
    status: 'RUNNING',
    event_type: 'run_started',
    payload: {},
    artifacts: [],
    timestamp: '2026-03-01T10:00:01Z',
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
    timestamp: '2026-03-01T10:00:02Z',
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
    payload: { body: 'raw-inline-body' },
    artifacts: [],
    timestamp: '2026-03-01T10:00:03Z',
  },
];

describe('RunSupportBundleExport', () => {
  beforeEach(() => {
    URL.createObjectURL = vi.fn(() => 'blob:run-support-bundle');
    URL.revokeObjectURL = vi.fn();
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => undefined);
  });

  afterEach(() => {
    URL.createObjectURL = originalCreateObjectURL;
    URL.revokeObjectURL = originalRevokeObjectURL;
    vi.restoreAllMocks();
  });

  it('exports explicit truncation metadata with absolute docs links and redaction', () => {
    const model = normalizeRunDebugData(runFixture, ledgerFixture);
    const onExported = vi.fn();

    render(
      <MantineProvider>
        <RunSupportBundleExport
          run={runFixture}
          ledgerEntries={ledgerFixture}
          model={model}
          ledgerSummary={{
            ledger_entries_available: 3,
            ledger_entries_available_exact: true,
            ledger_truncated: false,
            ledger_source_truncated: false,
          }}
          ledgerLimit={2}
          onExported={onExported}
        />
      </MantineProvider>
    );

    expect(screen.getByText('Entries in bundle ledger: 2 / 3')).toBeInTheDocument();
    expect(
      screen.getByText(
        'Export is truncated. Use `ledger_truncated`, `ledger_entries_included`, and `ledger_entries_available` fields inside the bundle for support escalation context.'
      )
    ).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Export support bundle' }));

    expect(onExported).toHaveBeenCalledTimes(1);
    const bundle = onExported.mock.calls[0][0];
    const json = JSON.stringify(bundle);

    expect(bundle.docs_links).toEqual([
      'http://api.localhost/openapi.yaml',
      'http://api.localhost/workflow-authoring-guide',
    ]);
    expect(bundle.ledger_truncated).toBe(true);
    expect(bundle.ledger_entries_included).toBe(2);
    expect(bundle.ledger_entries_available).toBe(3);
    expect(bundle.export_metadata).toEqual(
      expect.objectContaining({
        bundle_schema: 'run_support_bundle',
        bundle_version: 'run_debug_bundle_v1',
        ledger_truncated: true,
        ledger_source_truncated: false,
        ledger_export_truncated: true,
        ledger_entries_included: 2,
        ledger_entries_available: 3,
        ledger_entries_available_exact: true,
      })
    );
    expect(bundle.ledger).toEqual(
      expect.objectContaining({
        included_entries: 2,
        total_available: 3,
        truncated: true,
        export_truncated: true,
        source_truncated: false,
      })
    );
    expect(json).not.toContain('secret-token');
    expect(json).not.toContain('signature-secret');
    expect(json).not.toContain('token-should-redact');
    expect(json).not.toContain('raw-inline-content');
    expect(json).not.toContain('raw-inline-body');
    expect(json).not.toContain('raw-node-output');
    expect(json).toContain('[REDACTED_SECRET]');
    expect(json).toContain('[REDACTED_ARTIFACT_BODY]');
    expect(json).toContain('art_1');
  });
});
