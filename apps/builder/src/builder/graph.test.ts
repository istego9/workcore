import { describe, expect, it } from 'vitest';
import { createNode, validateGraph } from './graph';
import type { BuilderEdge } from './types';

const edge = (source: string, target: string): BuilderEdge => ({ id: `${source}__${target}`, source, target });

describe('validateGraph', () => {
  it('flags missing start/end', () => {
    const nodes = [createNode('agent', { x: 0, y: 0 })];
    const issues = validateGraph(nodes, []);
    expect(issues.some((issue) => issue.message.includes('Start'))).toBe(true);
    expect(issues.some((issue) => issue.message.includes('End'))).toBe(true);
  });

  it('flags while missing config', () => {
    const start = createNode('start', { x: 0, y: 0 });
    const loop = createNode('while', { x: 100, y: 0 });
    const end = createNode('end', { x: 200, y: 0 });
    const edges = [edge(start.id, loop.id), edge(loop.id, end.id)];
    const issues = validateGraph([start, loop, end], edges);
    expect(issues.some((issue) => issue.message.includes('While'))).toBe(true);
  });
});
