import { MantineProvider } from '@mantine/core';
import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { NivoChart, SUPPORTED_NIVO_CHART_TYPES, inferChartTypeFromLegacyPayload, normalizeNivoChartType } from './NivoChart';

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
        type: 'Chart',
        series: [{ type: 'bar', dataKey: 'value' }]
      })
    ).toBe('bar');

    expect(
      inferChartTypeFromLegacyPayload({
        type: 'Chart',
        series: [{ type: 'line', dataKey: 'value' }]
      })
    ).toBe('line');
  });

  it('renders safe message when required chart payload is missing', () => {
    render(
      <MantineProvider>
        <NivoChart component={{ type: 'Chart', chart_type: 'radar' }} />
      </MantineProvider>
    );

    expect(screen.getByText('Chart(radar): data is required')).toBeInTheDocument();
  });
});
