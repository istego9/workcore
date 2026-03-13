export type ReleasePipelineLogContext = {
  tenant_id: string | null;
  project_id: string | null;
  workflow_id: string | null;
  candidate_version_id: string | null;
  published_version_id: string | null;
  correlation_id?: string | null;
};

type Primitive = string | number | boolean | null;

const isPrimitive = (value: unknown): value is Primitive =>
  value === null || typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean';

const sanitizeDetails = (details?: Record<string, unknown>) => {
  if (!details) return {};
  const sanitized: Record<string, Primitive | Primitive[]> = {};
  Object.entries(details).forEach(([key, value]) => {
    if (isPrimitive(value)) {
      sanitized[key] = value;
      return;
    }
    if (Array.isArray(value) && value.every((item) => isPrimitive(item))) {
      sanitized[key] = value as Primitive[];
    }
  });
  return sanitized;
};

export const emitReleasePipelineLog = (
  eventType:
    | 'release_pipeline_opened'
    | 'validation_rerun'
    | 'simulation_started'
    | 'simulation_completed'
    | 'publish_initiated'
    | 'publish_completed'
    | 'bind_updated'
    | 'smoke_started'
    | 'smoke_completed'
    | 'release_report_exported',
  context: ReleasePipelineLogContext,
  details?: Record<string, unknown>
) => {
  const payload = {
    event: 'release_pipeline',
    event_type: eventType,
    tenant_id: context.tenant_id,
    project_id: context.project_id,
    workflow_id: context.workflow_id,
    candidate_version_id: context.candidate_version_id,
    published_version_id: context.published_version_id,
    correlation_id: context.correlation_id || null,
    timestamp: new Date().toISOString(),
    ...sanitizeDetails(details),
  };
  // Keep release logs structured and free of draft inputs or sensitive payloads.
  console.info('[release-pipeline]', payload);
};
