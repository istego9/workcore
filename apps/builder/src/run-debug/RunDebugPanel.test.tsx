import { MantineProvider } from '@mantine/core';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import type { ComponentProps } from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { RunLedgerRecord, RunRecord } from '../api';
import { RunDebugPanel } from './RunDebugPanel';

const getRunMock = vi.fn();
const collectRunLedgerMock = vi.fn();
const rerunNodeMock = vi.fn();
const cancelRunMock = vi.fn();
const originalCreateObjectURL = URL.createObjectURL;
const originalRevokeObjectURL = URL.revokeObjectURL;

vi.mock('../api', () => ({
  API_BASE: 'http://api.localhost',
  getRun: (...args: unknown[]) => getRunMock(...args),
  collectRunLedger: (...args: unknown[]) => collectRunLedgerMock(...args),
  rerunNode: (...args: unknown[]) => rerunNodeMock(...args),
  cancelRun: (...args: unknown[]) => cancelRunMock(...args)
}));

const renderPanel = (props: Partial<ComponentProps<typeof RunDebugPanel>> = {}) => {
  return render(
    <MantineProvider>
      <RunDebugPanel
        opened
        runId="run_1"
        inputRateUsdPer1M={0}
        outputRateUsdPer1M={0}
        onClose={() => undefined}
        {...props}
      />
    </MantineProvider>
  );
};

const runFixture: RunRecord = {
  run_id: 'run_1',
  workflow_id: 'wf_1',
  version_id: 'ver_1',
  status: 'FAILED',
  mode: 'live',
  outputs: null,
  metadata: { correlation_id: 'corr_1', tenant_id: 'tenant_1', project_id: 'proj_1' },
  created_at: '2026-03-01T10:00:00Z',
  updated_at: '2026-03-01T10:05:00Z',
  node_runs: []
};

const ledgerFixture: RunLedgerRecord[] = [
  {
    ledger_id: 'led_1',
    run_id: 'run_1',
    workflow_id: 'wf_1',
    version_id: 'ver_1',
    status: 'RUNNING',
    event_type: 'run_started',
    artifacts: [],
    payload: {},
    timestamp: '2026-03-01T10:00:01Z'
  }
];

describe('RunDebugPanel', () => {
  let consoleInfoSpy: ReturnType<typeof vi.spyOn>;

  beforeEach(() => {
    getRunMock.mockReset();
    collectRunLedgerMock.mockReset();
    rerunNodeMock.mockReset();
    cancelRunMock.mockReset();
    consoleInfoSpy = vi.spyOn(console, 'info').mockImplementation(() => undefined);
    URL.createObjectURL = vi.fn(() => 'blob:run-support-bundle');
    URL.revokeObjectURL = vi.fn();
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => undefined);
  });

  afterEach(() => {
    URL.createObjectURL = originalCreateObjectURL;
    URL.revokeObjectURL = originalRevokeObjectURL;
    consoleInfoSpy.mockRestore();
    vi.restoreAllMocks();
  });

  it('renders empty state when no run is selected', () => {
    renderPanel({ runId: null });
    expect(screen.getByText('Select a run from execution history.')).toBeInTheDocument();
  });

  it('renders loading state while inspector data is fetching', () => {
    getRunMock.mockImplementation(() => new Promise(() => undefined));
    collectRunLedgerMock.mockImplementation(() => new Promise(() => undefined));

    renderPanel();

    expect(screen.getByText('Loading run inspector…')).toBeInTheDocument();
  });

  it('renders run summary and empty attempt/last-good states', async () => {
    getRunMock.mockResolvedValue({ data: runFixture });
    collectRunLedgerMock.mockResolvedValue({
      data: {
        items: ledgerFixture,
        ledger_entries_available: ledgerFixture.length,
        ledger_entries_available_exact: true,
        ledger_truncated: false,
        ledger_source_truncated: false,
        pages_fetched: 1,
        page_limit: 1000
      }
    });

    renderPanel();

    await waitFor(() => expect(getRunMock).toHaveBeenCalledWith('run_1'));

    expect(screen.getByText('Run summary')).toBeInTheDocument();
    expect(screen.getByText('Node attempts')).toBeInTheDocument();
    expect(screen.getByText('No node attempts found for this run.')).toBeInTheDocument();
    expect(screen.getByText('No last known good output was found.')).toBeInTheDocument();
  });

  it('logs exported bundle truncation metadata from the built bundle', async () => {
    getRunMock.mockResolvedValue({ data: runFixture });
    collectRunLedgerMock.mockResolvedValue({
      data: {
        items: ledgerFixture,
        ledger_entries_available: 3,
        ledger_entries_available_exact: false,
        ledger_truncated: false,
        ledger_source_truncated: false,
        pages_fetched: 1,
        page_limit: 1000
      }
    });

    renderPanel();

    await waitFor(() => expect(screen.getByText('Support bundle export')).toBeInTheDocument());

    fireEvent.click(screen.getByRole('button', { name: 'Export support bundle' }));

    const exportLog = consoleInfoSpy.mock.calls.find(
      (call) => (call[1] as Record<string, unknown> | undefined)?.event_type === 'support_bundle_exported'
    );

    expect(exportLog).toBeDefined();
    expect(exportLog?.[1]).toEqual(
      expect.objectContaining({
        bundle_version: 'run_debug_bundle_v1',
        ledger_entries_included: 1,
        ledger_entries_available: 3,
        ledger_entries_available_exact: false,
        ledger_truncated: true,
        ledger_source_truncated: false,
        ledger_export_truncated: true
      })
    );
  });
});
