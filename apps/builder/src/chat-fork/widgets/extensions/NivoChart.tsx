import { Box, Text } from '@mantine/core';
import { ResponsiveBar } from '@nivo/bar';
import { ResponsiveLine } from '@nivo/line';
import type { WidgetComponent } from '../../protocol/types';

type NivoChartProps = {
  component: WidgetComponent;
};

type ChartRow = Record<string, string | number>;

type ChartSeries = {
  type?: string;
  dataKey?: string;
  label?: string;
};

const asRows = (value: unknown): ChartRow[] => {
  if (!Array.isArray(value)) return [];
  return value.filter((item) => typeof item === 'object' && item !== null) as ChartRow[];
};

const asSeries = (value: unknown): ChartSeries[] => {
  if (!Array.isArray(value)) return [];
  return value.filter((item) => typeof item === 'object' && item !== null) as ChartSeries[];
};

const resolveXAxisKey = (xAxis: unknown): string => {
  if (typeof xAxis === 'string' && xAxis) return xAxis;
  if (typeof xAxis === 'object' && xAxis && typeof (xAxis as Record<string, unknown>).dataKey === 'string') {
    return (xAxis as Record<string, unknown>).dataKey as string;
  }
  return 'x';
};

export function NivoChart({ component }: NivoChartProps) {
  const rows = asRows(component.data);
  const series = asSeries(component.series);

  if (!rows.length || !series.length) {
    return (
      <Text c="dimmed" size="sm">
        Chart: data or series is missing
      </Text>
    );
  }

  const xAxisKey = resolveXAxisKey(component.xAxis);
  const barSeries = series.filter((item) => (item.type || 'bar') === 'bar');
  const lineLikeSeries = series.filter((item) => {
    const kind = (item.type || 'line').toLowerCase();
    return kind === 'line' || kind === 'area';
  });

  if (barSeries.length && lineLikeSeries.length === 0) {
    const keys = barSeries.map((item) => item.dataKey).filter((item): item is string => Boolean(item));
    return (
      <Box h={260}>
        <ResponsiveBar
          data={rows}
          keys={keys}
          indexBy={xAxisKey}
          margin={{ top: 20, right: 16, bottom: 40, left: 56 }}
          padding={0.25}
          axisBottom={{ tickRotation: 0 }}
          enableLabel={false}
        />
      </Box>
    );
  }

  const hasArea = lineLikeSeries.some((item) => (item.type || '').toLowerCase() === 'area');
  const lineData = lineLikeSeries
    .map((item) => {
      const dataKey = item.dataKey;
      if (!dataKey) return null;
      return {
        id: item.label || dataKey,
        data: rows.map((row) => ({ x: row[xAxisKey], y: Number(row[dataKey] || 0) }))
      };
    })
    .filter((item): item is { id: string; data: Array<{ x: string | number; y: number }> } => item !== null);

  if (!lineData.length) {
    return (
      <Text c="dimmed" size="sm">
        Chart: unsupported series configuration
      </Text>
    );
  }

  return (
    <Box h={260}>
      <ResponsiveLine
        data={lineData}
        margin={{ top: 20, right: 16, bottom: 40, left: 56 }}
        xScale={{ type: 'point' }}
        yScale={{ type: 'linear', min: 'auto', max: 'auto', stacked: false, reverse: false }}
        curve="monotoneX"
        enableArea={hasArea}
        useMesh
      />
    </Box>
  );
}
