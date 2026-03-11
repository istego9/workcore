import { MantineProvider } from '@mantine/core';
import { render, screen, waitFor } from '@testing-library/react';
import type { ComponentProps } from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { RunLedgerRecord, RunRecord } from '../api';
import { RunDebugPanel } from './RunDebugPanel';

const getRunMock = vi.fn();
const getRunLedgerMock = vi.fn();
const rerunNodeMock = vi.fn();
const cancelRunMock = vi.fn();

vi.mock('../api', () => ({
  API_BASE: 'http://api.localhost',
  getRun: (...args: unknown[]) => getRunMock(...args),
  getRunLedger: (...args: unknown[]) => getRunLedgerMock(...args),
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
    getRunLedgerMock.mockReset();
    rerunNodeMock.mockReset();
    cancelRunMock.mockReset();
    consoleInfoSpy = vi.spyOn(console, 'info').mockImplementation(() => undefined);
  });

  afterEach(() => {
    consoleInfoSpy.mockRestore();
  });

  it('renders empty state when no run is selected', () => {
    renderPanel({ runId: null });
    expect(screen.getByText('Select a run from execution history.')).toBeInTheDocument();
  });

  it('renders loading state while inspector data is fetching', () => {
    getRunMock.mockImplementation(() => new Promise(() => undefined));
    getRunLedgerMock.mockImplementation(() => new Promise(() => undefined));

    renderPanel();

    expect(screen.getByText('Loading run inspector…')).toBeInTheDocument();
  });

  it('renders run summary and empty attempt/last-good states', async () => {
    getRunMock.mockResolvedValue({ data: runFixture });
    getRunLedgerMock.mockResolvedValue({ data: { items: ledgerFixture } });

    renderPanel();

    await waitFor(() => expect(getRunMock).toHaveBeenCalledWith('run_1'));

    expect(screen.getByText('Run summary')).toBeInTheDocument();
    expect(screen.getByText('Node attempts')).toBeInTheDocument();
    expect(screen.getByText('No node attempts found for this run.')).toBeInTheDocument();
    expect(screen.getByText('No last known good output was found.')).toBeInTheDocument();
  });
});
