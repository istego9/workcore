import { Box, Text } from '@mantine/core';
import { useEffect, useMemo, useState, type ComponentType, type ReactNode } from 'react';
import type { WidgetComponent } from '../../protocol/types';

export const SUPPORTED_NIVO_CHART_TYPES = [
  'bar',
  'line',
  'pie',
  'area-bump',
  'bump',
  'boxplot',
  'bullet',
  'calendar',
  'chord',
  'circle-packing',
  'funnel',
  'geo',
  'heatmap',
  'icicle',
  'marimekko',
  'network',
  'parallel-coordinates',
  'polar-bar',
  'radar',
  'radial-bar',
  'sankey',
  'scatterplot',
  'stream',
  'sunburst',
  'swarmplot',
  'tree',
  'treemap',
  'waffle'
] as const;

export type SupportedNivoChartType = (typeof SUPPORTED_NIVO_CHART_TYPES)[number];

type NivoChartProps = {
  component: WidgetComponent;
};

type LegacyRow = Record<string, string | number>;

type LegacySeries = {
  type?: string;
  dataKey?: string;
  label?: string;
  id?: string;
  key?: string;
};

const DEFAULT_HEIGHT = 280;
const DEFAULT_MARGIN = { top: 20, right: 24, bottom: 44, left: 56 };
const CHART_TYPE_SET = new Set<string>(SUPPORTED_NIVO_CHART_TYPES);

const CHART_TYPE_ALIASES: Record<string, SupportedNivoChartType> = {
  area: 'line',
  area_bump: 'area-bump',
  areabump: 'area-bump',
  box_plot: 'boxplot',
  boxplot: 'boxplot',
  bullet: 'bullet',
  circlepacking: 'circle-packing',
  circle_packing: 'circle-packing',
  funnel: 'funnel',
  geo: 'geo',
  heat_map: 'heatmap',
  heatmap: 'heatmap',
  icicle: 'icicle',
  line: 'line',
  marimekko: 'marimekko',
  network: 'network',
  parallel_coordinates: 'parallel-coordinates',
  parallelcoordinates: 'parallel-coordinates',
  pie: 'pie',
  polar_bar: 'polar-bar',
  polarbar: 'polar-bar',
  radar: 'radar',
  radial_bar: 'radial-bar',
  radialbar: 'radial-bar',
  sankey: 'sankey',
  scatter_plot: 'scatterplot',
  scatterplot: 'scatterplot',
  stream: 'stream',
  sunburst: 'sunburst',
  swarm_plot: 'swarmplot',
  swarmplot: 'swarmplot',
  tree: 'tree',
  treemap: 'treemap',
  waffle: 'waffle',
  bar: 'bar',
  bump: 'bump',
  calendar: 'calendar',
  chord: 'chord'
};

type ChartComponentLoader = () => Promise<ComponentType<any>>;

const CHART_COMPONENT_LOADERS: Record<SupportedNivoChartType, ChartComponentLoader> = {
  bar: () => import('@nivo/bar').then((mod) => mod.ResponsiveBar as ComponentType<any>),
  line: () => import('@nivo/line').then((mod) => mod.ResponsiveLine as ComponentType<any>),
  pie: () => import('@nivo/pie').then((mod) => mod.ResponsivePie as ComponentType<any>),
  'area-bump': () => import('@nivo/bump').then((mod) => mod.ResponsiveAreaBump as ComponentType<any>),
  bump: () => import('@nivo/bump').then((mod) => mod.ResponsiveBump as ComponentType<any>),
  boxplot: () => import('@nivo/boxplot').then((mod) => mod.ResponsiveBoxPlot as ComponentType<any>),
  bullet: () => import('@nivo/bullet').then((mod) => mod.ResponsiveBullet as ComponentType<any>),
  calendar: () => import('@nivo/calendar').then((mod) => mod.ResponsiveCalendar as ComponentType<any>),
  chord: () => import('@nivo/chord').then((mod) => mod.ResponsiveChord as ComponentType<any>),
  'circle-packing': () =>
    import('@nivo/circle-packing').then((mod) => mod.ResponsiveCirclePacking as ComponentType<any>),
  funnel: () => import('@nivo/funnel').then((mod) => mod.ResponsiveFunnel as ComponentType<any>),
  geo: () => import('@nivo/geo').then((mod) => mod.ResponsiveGeoMap as ComponentType<any>),
  heatmap: () => import('@nivo/heatmap').then((mod) => mod.ResponsiveHeatMap as ComponentType<any>),
  icicle: () => import('@nivo/icicle').then((mod) => mod.ResponsiveIcicle as ComponentType<any>),
  marimekko: () => import('@nivo/marimekko').then((mod) => mod.ResponsiveMarimekko as ComponentType<any>),
  network: () => import('@nivo/network').then((mod) => mod.ResponsiveNetwork as ComponentType<any>),
  'parallel-coordinates': () =>
    import('@nivo/parallel-coordinates').then((mod) => mod.ResponsiveParallelCoordinates as ComponentType<any>),
  'polar-bar': () => import('@nivo/polar-bar').then((mod) => mod.ResponsivePolarBar as ComponentType<any>),
  radar: () => import('@nivo/radar').then((mod) => mod.ResponsiveRadar as ComponentType<any>),
  'radial-bar': () => import('@nivo/radial-bar').then((mod) => mod.ResponsiveRadialBar as ComponentType<any>),
  sankey: () => import('@nivo/sankey').then((mod) => mod.ResponsiveSankey as ComponentType<any>),
  scatterplot: () =>
    import('@nivo/scatterplot').then((mod) => mod.ResponsiveScatterPlot as ComponentType<any>),
  stream: () => import('@nivo/stream').then((mod) => mod.ResponsiveStream as ComponentType<any>),
  sunburst: () => import('@nivo/sunburst').then((mod) => mod.ResponsiveSunburst as ComponentType<any>),
  swarmplot: () => import('@nivo/swarmplot').then((mod) => mod.ResponsiveSwarmPlot as ComponentType<any>),
  tree: () => import('@nivo/tree').then((mod) => mod.ResponsiveTree as ComponentType<any>),
  treemap: () => import('@nivo/treemap').then((mod) => mod.ResponsiveTreeMap as ComponentType<any>),
  waffle: () => import('@nivo/waffle').then((mod) => mod.ResponsiveWaffle as ComponentType<any>)
};

const asRecord = (value: unknown): Record<string, unknown> =>
  value && typeof value === 'object' && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};

const asArrayRecord = (value: unknown): Record<string, unknown>[] =>
  Array.isArray(value)
    ? value.filter((item) => item && typeof item === 'object') as Record<string, unknown>[]
    : [];

const asLegacyRows = (value: unknown): LegacyRow[] =>
  Array.isArray(value) ? (value.filter((item) => item && typeof item === 'object') as LegacyRow[]) : [];

const asLegacySeries = (value: unknown): LegacySeries[] =>
  Array.isArray(value) ? (value.filter((item) => item && typeof item === 'object') as LegacySeries[]) : [];

const asStringArray = (value: unknown): string[] =>
  Array.isArray(value)
    ? value.filter((item) => typeof item === 'string').map((item) => item.trim()).filter(Boolean)
    : [];

const resolveHeight = (props: Record<string, unknown>): number => {
  const heightRaw = props.height;
  if (typeof heightRaw === 'number' && Number.isFinite(heightRaw) && heightRaw > 0) {
    return heightRaw;
  }
  return DEFAULT_HEIGHT;
};

const resolveXAxisKey = (xAxis: unknown): string => {
  if (typeof xAxis === 'string' && xAxis.trim()) return xAxis.trim();
  if (xAxis && typeof xAxis === 'object') {
    const dataKey = (xAxis as Record<string, unknown>).dataKey;
    if (typeof dataKey === 'string' && dataKey.trim()) return dataKey.trim();
  }
  return 'x';
};

const inferNumericKeys = (rows: LegacyRow[], indexBy: string): string[] => {
  const first = rows[0];
  if (!first) return [];
  return Object.keys(first).filter((key) => key !== indexBy && typeof first[key] === 'number');
};

const toLineSeriesFromLegacy = (
  rows: LegacyRow[],
  series: LegacySeries[],
  xAxisKey: string
): Array<{ id: string; data: Array<{ x: string | number; y: number }> }> => {
  const scoped = series
    .map((item) => {
      const dataKey = typeof item.dataKey === 'string' ? item.dataKey : undefined;
      if (!dataKey) return null;
      return {
        id: item.label || item.id || item.key || dataKey,
        dataKey
      };
    })
    .filter((item): item is { id: string; dataKey: string } => item !== null);

  return scoped.map((item) => ({
    id: item.id,
    data: rows.map((row) => ({ x: row[xAxisKey], y: Number(row[item.dataKey] ?? 0) }))
  }));
};

export const normalizeNivoChartType = (value: unknown): SupportedNivoChartType | null => {
  if (typeof value !== 'string') return null;
  const normalized = value.trim().toLowerCase();
  if (!normalized) return null;
  if (CHART_TYPE_SET.has(normalized)) {
    return normalized as SupportedNivoChartType;
  }
  const compact = normalized.replace(/[\s_]+/g, '-');
  if (CHART_TYPE_SET.has(compact)) {
    return compact as SupportedNivoChartType;
  }
  const alias = CHART_TYPE_ALIASES[normalized] || CHART_TYPE_ALIASES[compact] || CHART_TYPE_ALIASES[normalized.replace(/-/g, '')];
  return alias || null;
};

export const inferChartTypeFromLegacyPayload = (component: WidgetComponent): SupportedNivoChartType => {
  const series = asLegacySeries(component.series);
  const hasAreaBump = series.some((item) => String(item.type || '').toLowerCase() === 'area-bump');
  if (hasAreaBump) return 'area-bump';
  const hasBump = series.some((item) => String(item.type || '').toLowerCase() === 'bump');
  if (hasBump) return 'bump';
  const hasBar = series.some((item) => String(item.type || '').toLowerCase() === 'bar');
  if (hasBar) return 'bar';
  const hasLine = series.some((item) => {
    const type = String(item.type || '').toLowerCase();
    return type === 'line' || type === 'area';
  });
  if (hasLine) return 'line';

  const data = asArrayRecord(component.data);
  const hasPieShape = data.some((entry) => (typeof entry.id === 'string' || typeof entry.label === 'string') && typeof entry.value === 'number');
  if (hasPieShape) return 'pie';
  return 'bar';
};

const chartBox = (height: number, node: ReactNode) => <Box h={height}>{node}</Box>;

const unsupported = (message: string) => (
  <Text c="dimmed" size="sm">
    {message}
  </Text>
);

const useNivoChartComponent = (chartType: SupportedNivoChartType) => {
  const loader = useMemo(() => CHART_COMPONENT_LOADERS[chartType], [chartType]);
  const [chartComponent, setChartComponent] = useState<ComponentType<any> | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setChartComponent(null);
    setLoadError(null);
    loader()
      .then((nextComponent) => {
        if (!cancelled) {
          setChartComponent(() => nextComponent);
        }
      })
      .catch((error) => {
        if (!cancelled) {
          setLoadError(error instanceof Error ? error.message : 'unknown loader error');
        }
      });
    return () => {
      cancelled = true;
    };
  }, [loader]);

  return { chartComponent, loadError };
};

const renderResolvedChart = (
  chartComponent: ComponentType<any> | null,
  chartType: SupportedNivoChartType,
  height: number,
  props: Record<string, unknown>,
  loadError: string | null
): ReactNode => {
  if (loadError) {
    return unsupported(`Chart(${chartType}): failed to load renderer`);
  }
  if (!chartComponent) {
    return unsupported(`Chart(${chartType}): loading renderer...`);
  }
  const ChartComponent = chartComponent;
  return chartBox(height, <ChartComponent {...props} />);
};

export function NivoChart({ component }: NivoChartProps) {
  const chartType =
    normalizeNivoChartType(component.chart_type) ||
    normalizeNivoChartType(component.chartType) ||
    inferChartTypeFromLegacyPayload(component);
  const chartTypeForLoader: SupportedNivoChartType = chartType || 'bar';
  const { chartComponent, loadError } = useNivoChartComponent(chartTypeForLoader);

  const nivoProps = asRecord(component.nivo_props || component.nivoProps);
  const rows = asLegacyRows(component.data);
  const series = asLegacySeries(component.series);
  const xAxisKey = resolveXAxisKey(component.xAxis);
  const height = resolveHeight(nivoProps);

  if (!chartType) {
    return unsupported('Chart: chart_type is required');
  }

  if (chartType === 'bar') {
    const data = asLegacyRows(nivoProps.data).length ? asLegacyRows(nivoProps.data) : rows;
    if (!data.length) return unsupported('Chart(bar): data is required');
    const keys = asStringArray(nivoProps.keys).length
      ? asStringArray(nivoProps.keys)
      : series
          .map((item) => (typeof item.dataKey === 'string' ? item.dataKey : ''))
          .filter(Boolean);
    const finalKeys = keys.length ? keys : inferNumericKeys(data, xAxisKey);
    if (!finalKeys.length) return unsupported('Chart(bar): keys are required');
    return renderResolvedChart(chartComponent, chartType, height, {
      margin: DEFAULT_MARGIN,
      indexBy: typeof nivoProps.indexBy === 'string' ? nivoProps.indexBy : xAxisKey,
      padding: 0.25,
      enableLabel: false,
      ...nivoProps,
      data,
      keys: finalKeys
    }, loadError);
  }

  if (chartType === 'line') {
    const externalData = Array.isArray(nivoProps.data) ? (nivoProps.data as unknown[]) : [];
    const data =
      externalData.length > 0
        ? externalData
        : toLineSeriesFromLegacy(rows, series, xAxisKey);
    if (!data.length) return unsupported('Chart(line): data is required');
    const hasAreaSeries = series.some((item) => String(item.type || '').toLowerCase() === 'area');
    return renderResolvedChart(chartComponent, chartType, height, {
      margin: DEFAULT_MARGIN,
      xScale: { type: 'point' },
      yScale: { type: 'linear', min: 'auto', max: 'auto', stacked: false, reverse: false },
      curve: 'monotoneX',
      useMesh: true,
      ...nivoProps,
      data,
      enableArea: Boolean(nivoProps.enableArea) || hasAreaSeries
    }, loadError);
  }

  if (chartType === 'pie') {
    const data = asArrayRecord(nivoProps.data).length ? asArrayRecord(nivoProps.data) : asArrayRecord(component.data);
    if (!data.length) return unsupported('Chart(pie): data is required');
    return renderResolvedChart(chartComponent, chartType, height, {
      margin: DEFAULT_MARGIN,
      ...nivoProps,
      data,
      id: typeof nivoProps.id === 'string' ? nivoProps.id : 'id',
      value: typeof nivoProps.value === 'string' ? nivoProps.value : 'value'
    }, loadError);
  }

  if (chartType === 'area-bump') {
    const data = Array.isArray(nivoProps.data) ? nivoProps.data : component.series;
    if (!Array.isArray(data) || !data.length) return unsupported('Chart(area-bump): data is required');
    return renderResolvedChart(chartComponent, chartType, height, {
      margin: DEFAULT_MARGIN,
      ...nivoProps,
      data
    }, loadError);
  }

  if (chartType === 'bump') {
    const data = Array.isArray(nivoProps.data) ? nivoProps.data : component.series;
    if (!Array.isArray(data) || !data.length) return unsupported('Chart(bump): data is required');
    return renderResolvedChart(chartComponent, chartType, height, {
      margin: DEFAULT_MARGIN,
      ...nivoProps,
      data
    }, loadError);
  }

  if (chartType === 'boxplot') {
    const data = asArrayRecord(nivoProps.data).length ? asArrayRecord(nivoProps.data) : rows;
    if (!data.length) return unsupported('Chart(boxplot): data is required');
    return renderResolvedChart(chartComponent, chartType, height, {
      margin: DEFAULT_MARGIN,
      ...nivoProps,
      data
    }, loadError);
  }

  if (chartType === 'bullet') {
    const data = Array.isArray(nivoProps.data) ? nivoProps.data : component.data;
    if (!Array.isArray(data) || !data.length) return unsupported('Chart(bullet): data is required');
    return renderResolvedChart(chartComponent, chartType, height, {
      ...nivoProps,
      data
    }, loadError);
  }

  if (chartType === 'calendar') {
    const data = Array.isArray(nivoProps.data) ? nivoProps.data : component.data;
    if (!Array.isArray(data) || !data.length) return unsupported('Chart(calendar): data is required');
    return renderResolvedChart(chartComponent, chartType, height, {
      ...nivoProps,
      data
    }, loadError);
  }

  if (chartType === 'chord') {
    const data = Array.isArray(nivoProps.data) ? nivoProps.data : component.data;
    if (!Array.isArray(data) || !data.length) return unsupported('Chart(chord): data matrix is required');
    return renderResolvedChart(chartComponent, chartType, height, {
      margin: DEFAULT_MARGIN,
      ...nivoProps,
      data
    }, loadError);
  }

  if (chartType === 'circle-packing') {
    const data = asRecord(nivoProps.data).children ? asRecord(nivoProps.data) : asRecord(component.data);
    if (!Object.keys(data).length) return unsupported('Chart(circle-packing): hierarchy data is required');
    return renderResolvedChart(chartComponent, chartType, height, {
      ...nivoProps,
      data
    }, loadError);
  }

  if (chartType === 'funnel') {
    const data = asArrayRecord(nivoProps.data).length ? asArrayRecord(nivoProps.data) : rows;
    if (!data.length) return unsupported('Chart(funnel): data is required');
    return renderResolvedChart(chartComponent, chartType, height, {
      margin: DEFAULT_MARGIN,
      ...nivoProps,
      data
    }, loadError);
  }

  if (chartType === 'geo') {
    const features = Array.isArray(nivoProps.features) ? nivoProps.features : (component.features as unknown[] | undefined);
    if (!Array.isArray(features) || !features.length) return unsupported('Chart(geo): features are required in nivo_props.features');
    return renderResolvedChart(chartComponent, chartType, height, {
      margin: DEFAULT_MARGIN,
      projectionScale: 110,
      ...nivoProps,
      features
    }, loadError);
  }

  if (chartType === 'heatmap') {
    const data = asArrayRecord(nivoProps.data).length ? asArrayRecord(nivoProps.data) : rows;
    if (!data.length) return unsupported('Chart(heatmap): data is required');
    return renderResolvedChart(chartComponent, chartType, height, {
      margin: DEFAULT_MARGIN,
      ...nivoProps,
      data
    }, loadError);
  }

  if (chartType === 'icicle') {
    const data = asRecord(nivoProps.data).children ? asRecord(nivoProps.data) : asRecord(component.data);
    if (!Object.keys(data).length) return unsupported('Chart(icicle): hierarchy data is required');
    return renderResolvedChart(chartComponent, chartType, height, {
      ...nivoProps,
      data
    }, loadError);
  }

  if (chartType === 'marimekko') {
    const data = asArrayRecord(nivoProps.data).length ? asArrayRecord(nivoProps.data) : rows;
    if (!data.length) return unsupported('Chart(marimekko): data is required');
    return renderResolvedChart(chartComponent, chartType, height, {
      margin: DEFAULT_MARGIN,
      ...nivoProps,
      data
    }, loadError);
  }

  if (chartType === 'network') {
    const data = asRecord(nivoProps.data).nodes ? asRecord(nivoProps.data) : asRecord(component.data);
    if (!Object.keys(data).length) return unsupported('Chart(network): graph data is required');
    return renderResolvedChart(chartComponent, chartType, height, {
      margin: DEFAULT_MARGIN,
      ...nivoProps,
      data
    }, loadError);
  }

  if (chartType === 'parallel-coordinates') {
    const data = asArrayRecord(nivoProps.data).length ? asArrayRecord(nivoProps.data) : rows;
    if (!data.length) return unsupported('Chart(parallel-coordinates): data is required');
    return renderResolvedChart(chartComponent, chartType, height, {
      margin: DEFAULT_MARGIN,
      ...nivoProps,
      data
    }, loadError);
  }

  if (chartType === 'polar-bar') {
    const data = asArrayRecord(nivoProps.data).length ? asArrayRecord(nivoProps.data) : rows;
    if (!data.length) return unsupported('Chart(polar-bar): data is required');
    const keys = asStringArray(nivoProps.keys);
    const finalKeys = keys.length ? keys : inferNumericKeys(data as LegacyRow[], xAxisKey);
    if (!finalKeys.length) return unsupported('Chart(polar-bar): keys are required');
    return renderResolvedChart(chartComponent, chartType, height, {
      margin: DEFAULT_MARGIN,
      ...nivoProps,
      data,
      keys: finalKeys,
      indexBy: typeof nivoProps.indexBy === 'string' ? nivoProps.indexBy : xAxisKey
    }, loadError);
  }

  if (chartType === 'radar') {
    const data = asArrayRecord(nivoProps.data).length ? asArrayRecord(nivoProps.data) : rows;
    if (!data.length) return unsupported('Chart(radar): data is required');
    const keys = asStringArray(nivoProps.keys);
    const finalKeys = keys.length ? keys : inferNumericKeys(data as LegacyRow[], xAxisKey);
    if (!finalKeys.length) return unsupported('Chart(radar): keys are required');
    return renderResolvedChart(chartComponent, chartType, height, {
      margin: DEFAULT_MARGIN,
      ...nivoProps,
      data,
      keys: finalKeys,
      indexBy: typeof nivoProps.indexBy === 'string' ? nivoProps.indexBy : xAxisKey
    }, loadError);
  }

  if (chartType === 'radial-bar') {
    const data = Array.isArray(nivoProps.data) ? nivoProps.data : component.data;
    if (!Array.isArray(data) || !data.length) return unsupported('Chart(radial-bar): data is required');
    return renderResolvedChart(chartComponent, chartType, height, {
      margin: DEFAULT_MARGIN,
      ...nivoProps,
      data
    }, loadError);
  }

  if (chartType === 'sankey') {
    const data = asRecord(nivoProps.data).nodes ? asRecord(nivoProps.data) : asRecord(component.data);
    if (!Object.keys(data).length) return unsupported('Chart(sankey): data is required');
    return renderResolvedChart(chartComponent, chartType, height, {
      margin: DEFAULT_MARGIN,
      ...nivoProps,
      data
    }, loadError);
  }

  if (chartType === 'scatterplot') {
    const data = Array.isArray(nivoProps.data) ? nivoProps.data : component.series;
    if (!Array.isArray(data) || !data.length) return unsupported('Chart(scatterplot): data is required');
    return renderResolvedChart(chartComponent, chartType, height, {
      margin: DEFAULT_MARGIN,
      ...nivoProps,
      data
    }, loadError);
  }

  if (chartType === 'stream') {
    const data = asArrayRecord(nivoProps.data).length ? asArrayRecord(nivoProps.data) : rows;
    if (!data.length) return unsupported('Chart(stream): data is required');
    const keys = asStringArray(nivoProps.keys);
    const finalKeys = keys.length ? keys : inferNumericKeys(data as LegacyRow[], xAxisKey);
    if (!finalKeys.length) return unsupported('Chart(stream): keys are required');
    return renderResolvedChart(chartComponent, chartType, height, {
      margin: DEFAULT_MARGIN,
      ...nivoProps,
      data,
      keys: finalKeys,
      indexBy: typeof nivoProps.indexBy === 'string' ? nivoProps.indexBy : xAxisKey
    }, loadError);
  }

  if (chartType === 'sunburst') {
    const data = asRecord(nivoProps.data).children ? asRecord(nivoProps.data) : asRecord(component.data);
    if (!Object.keys(data).length) return unsupported('Chart(sunburst): hierarchy data is required');
    return renderResolvedChart(chartComponent, chartType, height, {
      ...nivoProps,
      data
    }, loadError);
  }

  if (chartType === 'swarmplot') {
    const data = asArrayRecord(nivoProps.data).length ? asArrayRecord(nivoProps.data) : rows;
    if (!data.length) return unsupported('Chart(swarmplot): data is required');
    return renderResolvedChart(chartComponent, chartType, height, {
      margin: DEFAULT_MARGIN,
      ...nivoProps,
      data
    }, loadError);
  }

  if (chartType === 'tree') {
    const data = asRecord(nivoProps.data).children ? asRecord(nivoProps.data) : asRecord(component.data);
    if (!Object.keys(data).length) return unsupported('Chart(tree): hierarchy data is required');
    return renderResolvedChart(chartComponent, chartType, height, {
      ...nivoProps,
      data
    }, loadError);
  }

  if (chartType === 'treemap') {
    const data = asRecord(nivoProps.data).children ? asRecord(nivoProps.data) : asRecord(component.data);
    if (!Object.keys(data).length) return unsupported('Chart(treemap): hierarchy data is required');
    return renderResolvedChart(chartComponent, chartType, height, {
      ...nivoProps,
      data
    }, loadError);
  }

  if (chartType === 'waffle') {
    const data = asArrayRecord(nivoProps.data).length ? asArrayRecord(nivoProps.data) : rows;
    if (!data.length) return unsupported('Chart(waffle): data is required');
    return renderResolvedChart(chartComponent, chartType, height, {
      ...nivoProps,
      data
    }, loadError);
  }

  return unsupported(`Chart: unsupported chart_type '${chartType}'`);
}
