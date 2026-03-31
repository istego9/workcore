import { MantineProvider } from '@mantine/core';
import { render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import {
  NivoChart,
  SUPPORTED_NIVO_CHART_TYPES,
  inferChartTypeFromLegacyPayload,
  isLegacyRichChartAlias,
  normalizeNivoChartType
} from './NivoChart';

const withMeasuredResizeObserver = async (fn: () => Promise<void>) => {
  const originalResizeObserver = window.ResizeObserver;
  class MeasuredResizeObserver {
    private readonly callback: ResizeObserverCallback;

    constructor(callback: ResizeObserverCallback) {
      this.callback = callback;
    }

    observe(target: Element): void {
      this.callback(
        [
          {
            borderBoxSize: [] as ResizeObserverSize[],
            contentBoxSize: [] as ResizeObserverSize[],
            contentRect: {
              width: 640,
              height: 240,
              top: 0,
              left: 0,
              bottom: 240,
              right: 640,
              x: 0,
              y: 0,
              toJSON: () => ({})
            } as DOMRectReadOnly,
            devicePixelContentBoxSize: [] as ResizeObserverSize[],
            target
          }
        ] as ResizeObserverEntry[],
        this as unknown as ResizeObserver
      );
    }

    unobserve(): void {}
    disconnect(): void {}
  }

  (window as unknown as { ResizeObserver: typeof ResizeObserver }).ResizeObserver =
    MeasuredResizeObserver as unknown as typeof ResizeObserver;

  const rectSpy = vi
    .spyOn(HTMLElement.prototype, 'getBoundingClientRect')
    .mockImplementation(
      () =>
        ({
          width: 640,
          height: 240,
          top: 0,
          left: 0,
          bottom: 240,
          right: 640,
          x: 0,
          y: 0,
          toJSON: () => ({})
        }) as DOMRect
    );

  try {
    await fn();
  } finally {
    rectSpy.mockRestore();
    (window as unknown as { ResizeObserver: typeof ResizeObserver }).ResizeObserver = originalResizeObserver;
  }
};

describe('NivoChart', () => {
  it('exposes full supported nivo chart type list', () => {
    expect(SUPPORTED_NIVO_CHART_TYPES).toContain('bar');
    expect(SUPPORTED_NIVO_CHART_TYPES).toContain('radial-bar');
    expect(SUPPORTED_NIVO_CHART_TYPES).toContain('parallel-coordinates');
    expect(SUPPORTED_NIVO_CHART_TYPES).toContain('waffle');
  });

  it('normalizes common chart type aliases', () => {
    expect(normalizeNivoChartType('area_bump')).toBe('area-bump');
    expect(normalizeNivoChartType('parallel_coordinates')).toBe('parallel-coordinates');
    expect(normalizeNivoChartType('polar_bar')).toBe('polar-bar');
    expect(normalizeNivoChartType('unknown')).toBeNull();
  });

  it('infers legacy chart type from series payload', () => {
    expect(
      inferChartTypeFromLegacyPayload({
        type: 'RichChart',
        series: [{ type: 'bar', dataKey: 'value' }]
      })
    ).toBe('bar');

    expect(
      inferChartTypeFromLegacyPayload({
        type: 'RichChart',
        series: [{ type: 'line', dataKey: 'value' }]
      })
    ).toBe('line');
  });

  it('renders safe message when required chart payload is missing', () => {
    render(
      <MantineProvider>
        <NivoChart component={{ type: 'RichChart', chart_type: 'radar' }} />
      </MantineProvider>
    );

    expect(screen.getByText('RichChart(radar): data is required')).toBeInTheDocument();
  });

  it('accepts legacy custom Chart alias during migration', () => {
    render(
      <MantineProvider>
        <NivoChart component={{ type: 'Chart', chart_type: 'radar' }} />
      </MantineProvider>
    );

    expect(screen.getByText('RichChart(radar): data is required')).toBeInTheDocument();
  });

  it('does not treat stock ChatKit Chart payloads as RichChart aliases', () => {
    expect(
      isLegacyRichChartAlias({
        type: 'Chart',
        data: [{ month: 'Jan', value: 12 }],
        series: [{ type: 'line', dataKey: 'value', label: 'Value' }],
        xAxis: 'month'
      })
    ).toBe(false);
  });

  it('renders donut RichChart examples', async () => {
    await withMeasuredResizeObserver(async () => {
      const { container } = render(
        <MantineProvider>
          <NivoChart
            component={{
              type: 'RichChart',
              chart_type: 'pie',
              data: [
                { id: 'Needs', value: 55 },
                { id: 'Savings', value: 25 },
                { id: 'Wants', value: 20 }
              ],
              nivo_props: { height: 240, innerRadius: 0.6 }
            }}
          />
        </MantineProvider>
      );

      await waitFor(() => expect(container.querySelector('svg')).not.toBeNull());
    });
  });

  it('renders line RichChart examples', async () => {
    await withMeasuredResizeObserver(async () => {
      const { container } = render(
        <MantineProvider>
          <NivoChart
            component={{
              type: 'RichChart',
              chart_type: 'line',
              xAxis: 'month',
              data: [
                { month: 'Jan', actual: 1200, target: 1100 },
                { month: 'Feb', actual: 1350, target: 1200 },
                { month: 'Mar', actual: 1280, target: 1250 }
              ],
              series: [
                { type: 'line', dataKey: 'actual', label: 'Actual' },
                { type: 'line', dataKey: 'target', label: 'Target' }
              ],
              nivo_props: { height: 240 }
            }}
          />
        </MantineProvider>
      );

      await waitFor(() => expect(container.querySelector('svg')).not.toBeNull());
    });
  });
});
