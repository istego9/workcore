import type { BuilderEdge, BuilderNode, NodePosition, NodeType, ValidationIssue, WorkflowDraft } from './types';

export const NODE_DIMENSIONS = {
  width: 200,
  height: 92
};

export const NODE_PALETTE: Array<{ type: NodeType; label: string; description: string; tone: string }> = [
  { type: 'start', label: 'Start', description: 'Inputs and schema', tone: 'slate' },
  { type: 'agent', label: 'Agent', description: 'LLM task with tools', tone: 'indigo' },
  { type: 'mcp', label: 'MCP', description: 'Call MCP tool', tone: 'violet' },
  { type: 'if_else', label: 'If / Else', description: 'Conditional routing', tone: 'amber' },
  { type: 'while', label: 'While', description: 'Loop with max iterations', tone: 'orange' },
  { type: 'set_state', label: 'Set State', description: 'Assign variables', tone: 'cyan' },
  { type: 'interaction', label: 'Interaction', description: 'Ask user or upload', tone: 'emerald' },
  { type: 'approval', label: 'Approval', description: 'Approve or reject', tone: 'teal' },
  { type: 'output', label: 'Output', description: 'Final payload', tone: 'blue' },
  { type: 'end', label: 'End', description: 'Stop execution', tone: 'gray' }
];

export const DEFAULT_DRAFT: WorkflowDraft = {
  nodes: [
    { id: 'start', type: 'start', config: { defaults: {} } },
    { id: 'end', type: 'end', config: {} }
  ],
  edges: [{ source: 'start', target: 'end' }],
  variables_schema: {}
};

const fallbackId = () => `node_${Math.random().toString(16).slice(2, 8)}`;

export const createNodeId = (prefix: string) => {
  if (typeof crypto !== 'undefined' && 'randomUUID' in crypto) {
    return `${prefix}_${crypto.randomUUID().slice(0, 8)}`;
  }
  return `${prefix}_${fallbackId()}`;
};

export const createEdgeId = (source: string, target: string) => `${source}__${target}`;

export const defaultNodeConfig = (type: NodeType): Record<string, any> => {
  switch (type) {
    case 'start':
      return { defaults: {} };
    case 'agent':
      return {
        instructions: '',
        model: '',
        user_input: '',
        allowed_tools: [],
        output_format: 'text',
        emit_partial: true,
        output_schema: null,
        output_widget: '',
        max_retries: 0,
        timeout_s: null
      };
    case 'mcp':
      return {
        server: '',
        tool: '',
        arguments: {},
        timeout_s: 30,
        allowed_tools: []
      };
    case 'if_else':
      return {
        branches: [],
        else_target: ''
      };
    case 'while':
      return {
        condition: '',
        max_iterations: 1,
        body_target: '',
        exit_target: '',
        loop_back: ''
      };
    case 'set_state':
      return { target: '', expression: '' };
    case 'interaction':
      return { prompt: '', allow_file_upload: false, input_schema: {}, state_target: '' };
    case 'approval':
      return { prompt: '', allow_file_upload: false, state_target: '' };
    case 'output':
      return { expression: null, value: {} };
    case 'end':
    default:
      return {};
  }
};

export const createNode = (type: NodeType, position: NodePosition): BuilderNode => {
  return {
    id: createNodeId(type),
    type,
    position,
    config: defaultNodeConfig(type)
  };
};

export const buildDraft = (
  nodes: BuilderNode[],
  edges: BuilderEdge[],
  variablesSchema: Record<string, any>
): WorkflowDraft => {
  return {
    nodes: nodes.map((node) => ({
      id: node.id,
      type: node.type,
      config: {
        ...node.config,
        ui: node.position
      }
    })),
    edges: edges.map((edge) => ({ source: edge.source, target: edge.target })),
    variables_schema: variablesSchema
  };
};

export const parseDraft = (draft: WorkflowDraft): {
  nodes: BuilderNode[];
  edges: BuilderEdge[];
  variablesSchema: Record<string, any>;
} => {
  const nodes = (draft.nodes || []).map((node, index) => {
    const ui = node.config?.ui as NodePosition | undefined;
    const position = ui || {
      x: 120 + index * 40,
      y: 120 + index * 20
    };
    const config = { ...(node.config || {}) };
    delete config.ui;
    return {
      id: node.id,
      type: (node.type || 'start') as NodeType,
      position,
      config
    } as BuilderNode;
  });

  const edges = (draft.edges || []).map((edge) => ({
    id: createEdgeId(edge.source, edge.target),
    source: edge.source,
    target: edge.target
  }));

  return {
    nodes,
    edges,
    variablesSchema: draft.variables_schema || {}
  };
};

export const validateGraph = (nodes: BuilderNode[], edges: BuilderEdge[]): ValidationIssue[] => {
  const issues: ValidationIssue[] = [];
  const nodeIds = new Set<string>();
  const startNodes = nodes.filter((node) => node.type === 'start');
  const endNodes = nodes.filter((node) => node.type === 'end');

  if (startNodes.length === 0) {
    issues.push({ id: 'missing-start', level: 'error', message: 'Add a Start node to begin the workflow.' });
  }
  if (startNodes.length > 1) {
    issues.push({ id: 'multi-start', level: 'error', message: 'Only one Start node is allowed.' });
  }
  if (endNodes.length === 0) {
    issues.push({ id: 'missing-end', level: 'error', message: 'Add an End node to finish the workflow.' });
  }

  nodes.forEach((node) => {
    if (!node.id) {
      issues.push({ id: `node-missing-id-${node.type}`, level: 'error', message: 'Node id is required.' });
      return;
    }
    if (nodeIds.has(node.id)) {
      issues.push({ id: `dup-${node.id}`, level: 'error', message: `Duplicate node id: ${node.id}` });
    }
    nodeIds.add(node.id);
  });

  edges.forEach((edge, index) => {
    if (!nodeIds.has(edge.source) || !nodeIds.has(edge.target)) {
      issues.push({
        id: `edge-${index}`,
        level: 'error',
        message: `Edge ${edge.source} → ${edge.target} references a missing node.`
      });
    }
  });

  if (startNodes.length === 1 && endNodes.length > 0) {
    const adjacency = new Map<string, string[]>();
    const reverse = new Map<string, string[]>();
    nodeIds.forEach((id) => {
      adjacency.set(id, []);
      reverse.set(id, []);
    });
    edges.forEach((edge) => {
      adjacency.get(edge.source)?.push(edge.target);
      reverse.get(edge.target)?.push(edge.source);
    });

    const reachable = new Set<string>();
    const queue = [startNodes[0].id];
    while (queue.length) {
      const current = queue.shift();
      if (!current || reachable.has(current)) continue;
      reachable.add(current);
      (adjacency.get(current) || []).forEach((next) => {
        if (!reachable.has(next)) queue.push(next);
      });
    }

    const endIdSet = new Set(endNodes.map((node) => node.id));
    const reachesEnd = new Set<string>();
    const reverseQueue = endNodes.map((node) => node.id);
    while (reverseQueue.length) {
      const current = reverseQueue.shift();
      if (!current || reachesEnd.has(current)) continue;
      reachesEnd.add(current);
      (reverse.get(current) || []).forEach((prev) => {
        if (!reachesEnd.has(prev)) reverseQueue.push(prev);
      });
    }

    if (![...endIdSet].some((id) => reachable.has(id))) {
      issues.push({
        id: 'no-path',
        level: 'error',
        message: 'No path from Start to End. Connect the graph before publishing.'
      });
    }

    nodes.forEach((node) => {
      if (!reachable.has(node.id)) {
        issues.push({
          id: `unreachable-${node.id}`,
          level: 'error',
          message: `Node ${node.id} is not reachable from Start.`,
          nodeId: node.id
        });
      }
      if (!reachesEnd.has(node.id)) {
        issues.push({
          id: `no-end-${node.id}`,
          level: 'warning',
          message: `Node ${node.id} does not reach End.`,
          nodeId: node.id
        });
      }
    });
  }

  nodes.forEach((node) => {
    if (node.type === 'while') {
      const { condition, max_iterations, body_target, exit_target, loop_back } = node.config || {};
      if (!condition) {
        issues.push({ id: `while-cond-${node.id}`, level: 'error', message: 'While needs a condition.', nodeId: node.id });
      }
      if (!max_iterations) {
        issues.push({
          id: `while-iter-${node.id}`,
          level: 'error',
          message: 'While needs max_iterations.',
          nodeId: node.id
        });
      }
      if (!body_target || !exit_target || !loop_back) {
        issues.push({
          id: `while-targets-${node.id}`,
          level: 'error',
          message: 'While needs body_target, exit_target, and loop_back.',
          nodeId: node.id
        });
      }
    }
    if (node.type === 'if_else') {
      const branches = node.config?.branches || [];
      if (!Array.isArray(branches) || branches.length === 0) {
        issues.push({
          id: `if-branches-${node.id}`,
          level: 'error',
          message: 'If/Else needs at least one branch.',
          nodeId: node.id
        });
      }
    }
    if (node.type === 'set_state') {
      if (!node.config?.target || !node.config?.expression) {
        issues.push({
          id: `set-state-${node.id}`,
          level: 'error',
          message: 'Set State needs target and expression.',
          nodeId: node.id
        });
      }
    }
    if (node.type === 'interaction' || node.type === 'approval') {
      if (!node.config?.prompt) {
        issues.push({
          id: `prompt-${node.id}`,
          level: 'warning',
          message: 'Interaction prompt is empty.',
          nodeId: node.id
        });
      }
    }
    if (node.type === 'agent') {
      if (!node.config?.instructions) {
        issues.push({
          id: `agent-instructions-${node.id}`,
          level: 'warning',
          message: 'Agent instructions are empty.',
          nodeId: node.id
        });
      }
    }
    if (node.type === 'mcp') {
      if (!node.config?.server || !node.config?.tool) {
        issues.push({
          id: `mcp-${node.id}`,
          level: 'warning',
          message: 'MCP needs server and tool.',
          nodeId: node.id
        });
      }
    }
  });

  return issues;
};
