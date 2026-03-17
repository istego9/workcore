import { MantineProvider } from '@mantine/core';
import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { WorkflowBindingPanel } from './WorkflowBindingPanel';

describe('WorkflowBindingPanel', () => {
  it('renders authoritative routing readback states and keeps direct runs diagnostic-only', () => {
    render(
      <MantineProvider>
        <WorkflowBindingPanel
          projectId="proj_1"
          projectName="Project 1"
          chatBound={false}
          routingBound={false}
          routingReadbackStatus="not_bound"
          routingDefinitionUpdatedAt={null}
          observedDirectRuns={3}
          projectsUsingWorkflow={[]}
          projectsUsageLoading={false}
          loadingChatBind={false}
          loadingRoutingBind={false}
          onBindChat={vi.fn()}
          onBindRouting={vi.fn()}
        />
      </MantineProvider>
    );

    expect(screen.getByTestId('release-routing-readback-status')).toHaveTextContent('Routing definition not bound');
    expect(
      screen.getByText('Direct runs were observed, but Bind remains open until workflow-definition readback succeeds.')
    ).toBeInTheDocument();
  });

  it('renders readback failure as an explicit operator-visible state', () => {
    render(
      <MantineProvider>
        <WorkflowBindingPanel
          projectId="proj_1"
          projectName="Project 1"
          chatBound={false}
          routingBound={false}
          routingReadbackStatus="readback_failed"
          routingDefinitionUpdatedAt={null}
          observedDirectRuns={0}
          projectsUsingWorkflow={[]}
          projectsUsageLoading={false}
          loadingChatBind={false}
          loadingRoutingBind={false}
          onBindChat={vi.fn()}
          onBindRouting={vi.fn()}
        />
      </MantineProvider>
    );

    expect(screen.getByTestId('release-routing-readback-status')).toHaveTextContent('Routing readback failed');
    expect(
      screen.getByText(
        'Builder could not confirm routing state from the API. Observed direct runs remain diagnostic only and do not close the Bind stage.'
      )
    ).toBeInTheDocument();
  });
});
