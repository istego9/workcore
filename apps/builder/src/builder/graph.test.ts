import { describe, expect, it } from 'vitest';
import { NODE_DIMENSIONS, autoLayoutNodes, createNode, validateGraph, validateImportedDraft } from './graph';
import type { BuilderEdge, BuilderNode, NodeType } from './types';

const edge = (source: string, target: string): BuilderEdge => ({ id: `${source}__${target}`, source, target });
const node = (id: string, type: NodeType, x: number, y: number): BuilderNode => ({
  ...createNode(type, { x, y }),
  id
});

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

  it('accepts set_state batch assignments without legacy target/expression', () => {
    const start = { ...createNode('start', { x: 0, y: 0 }), id: 'start' };
    const setter = {
      ...createNode('set_state', { x: 120, y: 0 }),
      id: 'set',
      config: {
        assignments: [{ target: 'budget.total', expression: "inputs['amount']" }]
      }
    };
    const end = { ...createNode('end', { x: 240, y: 0 }), id: 'end' };
    const issues = validateGraph([start, setter, end], [edge('start', 'set'), edge('set', 'end')]);
    expect(issues.some((issue) => issue.nodeId === 'set' && issue.level === 'error')).toBe(false);
  });

  it('flags set_state when assignments contain incomplete items', () => {
    const start = { ...createNode('start', { x: 0, y: 0 }), id: 'start' };
    const setter = {
      ...createNode('set_state', { x: 120, y: 0 }),
      id: 'set',
      config: {
        assignments: [{ target: 'budget.total', expression: '' }]
      }
    };
    const end = { ...createNode('end', { x: 240, y: 0 }), id: 'end' };
    const issues = validateGraph([start, setter, end], [edge('start', 'set'), edge('set', 'end')]);
    expect(issues.some((issue) => issue.message.includes('assignments'))).toBe(true);
  });
});

describe('autoLayoutNodes', () => {
  it('places linear graph from left to right', () => {
    const nodes = [
      node('start', 'start', 500, 380),
      node('agent_1', 'agent', 120, 60),
      node('end', 'end', 20, 20)
    ];
    const edges = [edge('start', 'agent_1'), edge('agent_1', 'end')];
    const laidOut = autoLayoutNodes(nodes, edges);
    const byId = new Map(laidOut.map((item) => [item.id, item]));

    const start = byId.get('start');
    const agent = byId.get('agent_1');
    const end = byId.get('end');
    expect(start?.position.x).toBeLessThan(agent?.position.x ?? 0);
    expect(agent?.position.x).toBeLessThan(end?.position.x ?? 0);
    expect(start?.position.y).toBe(agent?.position.y);
    expect(agent?.position.y).toBe(end?.position.y);
  });

  it('stacks branch nodes in one layer without overlap', () => {
    const nodes = [
      node('start', 'start', 0, 400),
      node('a', 'agent', 100, 0),
      node('b', 'agent', 200, 150),
      node('end', 'end', 50, 600)
    ];
    const edges = [edge('start', 'a'), edge('start', 'b'), edge('a', 'end'), edge('b', 'end')];
    const laidOut = autoLayoutNodes(nodes, edges);
    const byId = new Map(laidOut.map((item) => [item.id, item]));

    const branchA = byId.get('a');
    const branchB = byId.get('b');
    const end = byId.get('end');
    expect(branchA?.position.x).toBe(branchB?.position.x);
    expect(Math.abs((branchA?.position.y || 0) - (branchB?.position.y || 0))).toBeGreaterThanOrEqual(
      NODE_DIMENSIONS.height
    );
    expect(end?.position.x).toBeGreaterThan(branchA?.position.x ?? 0);
  });

  it('separates disconnected components vertically', () => {
    const nodes = [
      node('start', 'start', 20, 20),
      node('end', 'end', 220, 20),
      node('orphan', 'agent', 60, 900)
    ];
    const edges = [edge('start', 'end')];
    const laidOut = autoLayoutNodes(nodes, edges);
    const byId = new Map(laidOut.map((item) => [item.id, item]));

    expect(byId.get('orphan')?.position.y).toBeGreaterThan(byId.get('end')?.position.y ?? 0);
  });
});

describe('validateImportedDraft', () => {
  it('rejects draft with unsupported node type', () => {
    const errors = validateImportedDraft({
      nodes: [{ id: 'x', type: 'unknown', config: {} }],
      edges: [],
      variables_schema: {}
    } as any);

    expect(errors.some((message) => message.includes('unsupported type'))).toBe(true);
  });

  it('rejects draft without start-end path', () => {
    const errors = validateImportedDraft({
      nodes: [
        { id: 'a', type: 'agent', config: {} },
        { id: 'e', type: 'end', config: {} }
      ],
      edges: [{ source: 'a', target: 'e' }],
      variables_schema: {}
    } as any);

    expect(errors.some((message) => message.includes('Start'))).toBe(true);
  });

  it('accepts minimal valid draft', () => {
    const errors = validateImportedDraft({
      nodes: [
        { id: 'start', type: 'start', config: { defaults: {} } },
        { id: 'end', type: 'end', config: {} }
      ],
      edges: [{ source: 'start', target: 'end' }],
      variables_schema: {}
    } as any);

    expect(errors).toHaveLength(0);
  });
});
