import { MantineProvider } from '@mantine/core';
import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { WidgetRenderer } from './WidgetRenderer';

describe('WidgetRenderer', () => {
  it('submits form payload for interaction widget', () => {
    const onAction = vi.fn();
    render(
      <MantineProvider>
        <WidgetRenderer
          widget={{
            type: 'Card',
            children: [
              {
                type: 'Form',
                onSubmitAction: { type: 'interrupt.submit', payload: { run_id: 'run_1' } },
                children: [
                  { type: 'Input', name: 'response', placeholder: 'response' },
                  { type: 'Button', label: 'Submit', submit: true }
                ]
              }
            ]
          }}
          onAction={onAction}
        />
      </MantineProvider>
    );

    fireEvent.change(screen.getByPlaceholderText('response'), { target: { value: 'hello' } });
    fireEvent.click(screen.getByRole('button', { name: 'Submit' }));

    expect(onAction).toHaveBeenCalledTimes(1);
    expect(onAction.mock.calls[0][0].type).toBe('interrupt.submit');
    expect(onAction.mock.calls[0][1]).toEqual({ input: { response: 'hello' } });
  });

  it('renders datatable extension', () => {
    render(
      <MantineProvider>
        <WidgetRenderer
          widget={{
            type: 'Card',
            children: [
              {
                type: 'DataTable',
                columns: [
                  { key: 'name', label: 'Name' },
                  { key: 'score', label: 'Score', align: 'right' }
                ],
                rows: [
                  { name: 'A', score: 10 },
                  { name: 'B', score: 20 }
                ]
              }
            ]
          }}
          onAction={() => undefined}
        />
      </MantineProvider>
    );

    expect(screen.getByText('Name')).toBeInTheDocument();
    expect(screen.getByText('A')).toBeInTheDocument();
    expect(screen.getByText('20')).toBeInTheDocument();
  });
});
