export type NodeType =
  | 'start'
  | 'agent'
  | 'mcp'
  | 'if_else'
  | 'while'
  | 'set_state'
  | 'interaction'
  | 'approval'
  | 'output'
  | 'end';

export type NodePosition = {
  x: number;
  y: number;
};

export type BuilderNode = {
  id: string;
  type: NodeType;
  position: NodePosition;
  config: Record<string, any>;
};

export type BuilderEdge = {
  id: string;
  source: string;
  target: string;
};

export type WorkflowDraft = {
  nodes: Array<{ id: string; type: string; config: Record<string, any> }>;
  edges: Array<{ source: string; target: string }>;
  variables_schema?: Record<string, any>;
};

export type WorkflowExport = {
  schema_version: 'workflow_export_v1';
  exported_at: string;
  source?: {
    workflow_id?: string | null;
    active_version_id?: string | null;
  };
  workflow: {
    name: string;
    description?: string | null;
  };
  draft: WorkflowDraft;
};

export type WorkflowRecord = {
  workflow_id: string;
  name: string;
  description?: string | null;
  draft: WorkflowDraft;
  active_version_id?: string | null;
};

export type WorkflowSummary = {
  workflow_id: string;
  name: string;
  description?: string | null;
  active_version_id?: string | null;
  created_at?: string;
  updated_at?: string;
};

export type WorkflowVersion = {
  version_id: string;
  workflow_id: string;
  version_number: number;
};

export type ValidationIssue = {
  id: string;
  level: 'error' | 'warning';
  message: string;
  nodeId?: string;
};
