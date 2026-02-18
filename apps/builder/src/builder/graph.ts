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
      return {
        target: '',
        expression: '',
        assignments: [{ target: '', expression: '' }]
      };
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

const SUPPORTED_NODE_TYPES = new Set<NodeType>(NODE_PALETTE.map((item) => item.type));

const isObjectRecord = (value: unknown): value is Record<string, any> =>
  !!value && typeof value === 'object' && !Array.isArray(value);

const isNonEmptyString = (value: unknown): value is string =>
  typeof value === 'string' && value.trim().length > 0;

const isSupportedNodeType = (value: unknown): value is NodeType =>
  typeof value === 'string' && SUPPORTED_NODE_TYPES.has(value as NodeType);

export const validateImportedDraft = (draft: WorkflowDraft): string[] => {
  const errors: string[] = [];
  if (!isObjectRecord(draft)) {
    return ['Draft must be an object.'];
  }
  if (!Array.isArray(draft.nodes) || draft.nodes.length === 0) {
    errors.push('Draft must contain at least one node.');
  }
  if (!Array.isArray(draft.edges)) {
    errors.push('Draft edges must be an array.');
  }
  if (draft.variables_schema !== undefined && !isObjectRecord(draft.variables_schema)) {
    errors.push('Draft variables_schema must be an object.');
  }
  if (errors.length > 0 || !Array.isArray(draft.nodes) || !Array.isArray(draft.edges)) {
    return errors;
  }

  const nodes: BuilderNode[] = [];
  const edges: BuilderEdge[] = [];
  const seenNodeIds = new Set<string>();

  draft.nodes.forEach((rawNode, index) => {
    if (!isObjectRecord(rawNode)) {
      errors.push(`Node #${index + 1} must be an object.`);
      return;
    }
    const nodeId = typeof rawNode.id === 'string' ? rawNode.id.trim() : '';
    if (!nodeId) {
      errors.push(`Node #${index + 1} is missing id.`);
    } else if (seenNodeIds.has(nodeId)) {
      errors.push(`Duplicate node id: ${nodeId}.`);
    } else {
      seenNodeIds.add(nodeId);
    }

    if (!isSupportedNodeType(rawNode.type)) {
      const rawType = rawNode.type === undefined ? 'undefined' : String(rawNode.type);
      errors.push(`Node ${nodeId || `#${index + 1}`} has unsupported type: ${rawType}.`);
    }

    if (rawNode.config !== undefined && !isObjectRecord(rawNode.config)) {
      errors.push(`Node ${nodeId || `#${index + 1}`} has invalid config (must be an object).`);
    }

    nodes.push({
      id: nodeId || `invalid_node_${index}`,
      type: isSupportedNodeType(rawNode.type) ? rawNode.type : 'start',
      position: { x: 0, y: 0 },
      config: isObjectRecord(rawNode.config) ? rawNode.config : {}
    });
  });

  draft.edges.forEach((rawEdge, index) => {
    if (!isObjectRecord(rawEdge)) {
      errors.push(`Edge #${index + 1} must be an object.`);
      return;
    }
    const source = typeof rawEdge.source === 'string' ? rawEdge.source.trim() : '';
    const target = typeof rawEdge.target === 'string' ? rawEdge.target.trim() : '';
    if (!source || !target) {
      errors.push(`Edge #${index + 1} must contain non-empty source and target.`);
      return;
    }
    edges.push({
      id: createEdgeId(source, target),
      source,
      target
    });
  });

  if (errors.length > 0) {
    return errors;
  }

  const graphErrors = validateGraph(nodes, edges)
    .filter((issue) => issue.level === 'error')
    .map((issue) => issue.message);
  return graphErrors;
};

const AUTO_LAYOUT_MARGIN_X = 80;
const AUTO_LAYOUT_MARGIN_Y = 80;
const AUTO_LAYOUT_HORIZONTAL_GAP = 140;
const AUTO_LAYOUT_VERTICAL_GAP = 56;
const AUTO_LAYOUT_COMPONENT_GAP_Y = 140;

const sortNodeIdsByCanvasPosition = (nodeById: Map<string, BuilderNode>) => (left: string, right: string) => {
  const leftNode = nodeById.get(left);
  const rightNode = nodeById.get(right);
  if (!leftNode || !rightNode) return left.localeCompare(right);
  if (leftNode.position.y !== rightNode.position.y) {
    return leftNode.position.y - rightNode.position.y;
  }
  if (leftNode.position.x !== rightNode.position.x) {
    return leftNode.position.x - rightNode.position.x;
  }
  return left.localeCompare(right);
};

export const autoLayoutNodes = (nodes: BuilderNode[], edges: BuilderEdge[]): BuilderNode[] => {
  if (nodes.length === 0) return [];

  const nodeById = new Map(nodes.map((node) => [node.id, node]));
  const outgoing = new Map<string, string[]>();
  const incoming = new Map<string, string[]>();
  const undirected = new Map<string, Set<string>>();

  nodes.forEach((node) => {
    outgoing.set(node.id, []);
    incoming.set(node.id, []);
    undirected.set(node.id, new Set<string>());
  });

  edges.forEach((edge) => {
    if (!nodeById.has(edge.source) || !nodeById.has(edge.target)) return;
    outgoing.get(edge.source)?.push(edge.target);
    incoming.get(edge.target)?.push(edge.source);
    undirected.get(edge.source)?.add(edge.target);
    undirected.get(edge.target)?.add(edge.source);
  });

  const compareNodeIds = sortNodeIdsByCanvasPosition(nodeById);
  const sortedNodeIds = [...nodeById.keys()].sort(compareNodeIds);

  const components: string[][] = [];
  const visited = new Set<string>();
  sortedNodeIds.forEach((seedId) => {
    if (visited.has(seedId)) return;
    const queue = [seedId];
    const component: string[] = [];
    visited.add(seedId);
    while (queue.length > 0) {
      const current = queue.shift();
      if (!current) continue;
      component.push(current);
      (undirected.get(current) || []).forEach((next) => {
        if (visited.has(next)) return;
        visited.add(next);
        queue.push(next);
      });
    }
    component.sort(compareNodeIds);
    components.push(component);
  });

  const nextDepthMap = (ids: string[]) => {
    const idSet = new Set(ids);
    const depth = new Map<string, number>();
    const startRoots = ids.filter((id) => nodeById.get(id)?.type === 'start');
    let roots = startRoots;
    if (roots.length === 0) {
      roots = ids.filter((id) => {
        const parentCount = (incoming.get(id) || []).filter((from) => idSet.has(from)).length;
        return parentCount === 0;
      });
    }
    if (roots.length === 0 && ids.length > 0) {
      roots = [ids[0]];
    }

    roots = [...new Set(roots)].sort(compareNodeIds);
    const queue: string[] = [];
    roots.forEach((root) => {
      depth.set(root, 0);
      queue.push(root);
    });

    let maxDepth = roots.length > 0 ? 0 : -1;
    while (queue.length > 0) {
      const current = queue.shift();
      if (!current) continue;
      const currentDepth = depth.get(current) ?? 0;
      (outgoing.get(current) || []).forEach((next) => {
        if (!idSet.has(next)) return;
        const candidate = currentDepth + 1;
        const existing = depth.get(next);
        if (existing === undefined || candidate < existing) {
          depth.set(next, candidate);
          queue.push(next);
          if (candidate > maxDepth) maxDepth = candidate;
        }
      });
    }

    const unresolved = new Set(ids.filter((id) => !depth.has(id)));
    while (unresolved.size > 0) {
      const unresolvedIds = [...unresolved];
      unresolvedIds.sort((left, right) => {
        const leftParents = (incoming.get(left) || []).filter((id) => unresolved.has(id)).length;
        const rightParents = (incoming.get(right) || []).filter((id) => unresolved.has(id)).length;
        if (leftParents !== rightParents) return leftParents - rightParents;
        return compareNodeIds(left, right);
      });
      const seed = unresolvedIds[0];
      if (!seed) break;
      const seedDepth = maxDepth + 1;
      depth.set(seed, seedDepth);
      maxDepth = Math.max(maxDepth, seedDepth);
      unresolved.delete(seed);

      const localQueue = [seed];
      while (localQueue.length > 0) {
        const current = localQueue.shift();
        if (!current) continue;
        const currentDepth = depth.get(current) ?? seedDepth;
        (outgoing.get(current) || []).forEach((next) => {
          if (!unresolved.has(next)) return;
          const nextDepth = currentDepth + 1;
          depth.set(next, nextDepth);
          unresolved.delete(next);
          localQueue.push(next);
          maxDepth = Math.max(maxDepth, nextDepth);
        });
      }
    }

    return depth;
  };

  const positions = new Map<string, NodePosition>();
  let top = AUTO_LAYOUT_MARGIN_Y;

  components.forEach((component) => {
    const depth = nextDepthMap(component);
    const layers = new Map<number, string[]>();
    component.forEach((id) => {
      const layer = depth.get(id) ?? 0;
      const group = layers.get(layer) || [];
      group.push(id);
      layers.set(layer, group);
    });

    const sortedLayers = [...layers.keys()].sort((left, right) => left - right);
    let componentBottom = top;

    sortedLayers.forEach((layer) => {
      const layerIds = (layers.get(layer) || []).sort(compareNodeIds);
      layerIds.forEach((id, index) => {
        const x = AUTO_LAYOUT_MARGIN_X + layer * (NODE_DIMENSIONS.width + AUTO_LAYOUT_HORIZONTAL_GAP);
        const y = top + index * (NODE_DIMENSIONS.height + AUTO_LAYOUT_VERTICAL_GAP);
        positions.set(id, { x, y });
        componentBottom = Math.max(componentBottom, y + NODE_DIMENSIONS.height);
      });
    });

    top = componentBottom + AUTO_LAYOUT_COMPONENT_GAP_Y;
  });

  return nodes.map((node) => ({
    ...node,
    position: positions.get(node.id) || node.position
  }));
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
      const assignments = Array.isArray(node.config?.assignments) ? node.config.assignments : [];
      const hasLegacy = isNonEmptyString(node.config?.target) && isNonEmptyString(node.config?.expression);
      const hasAssignments = assignments.length > 0;
      const assignmentsValid =
        hasAssignments &&
        assignments.every(
          (assignment) =>
            isObjectRecord(assignment) &&
            isNonEmptyString(assignment.target) &&
            isNonEmptyString(assignment.expression)
        );

      if (!hasLegacy && !hasAssignments) {
        issues.push({
          id: `set-state-${node.id}`,
          level: 'error',
          message: 'Set State needs target + expression or non-empty assignments.',
          nodeId: node.id
        });
      } else if (hasAssignments && !assignmentsValid) {
        issues.push({
          id: `set-state-${node.id}`,
          level: 'error',
          message: 'Set State assignments must contain target and expression in every item.',
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
