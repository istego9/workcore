export const RECENT_PROJECT_IDS_STORAGE_KEY = 'builder.recent_project_ids';
const DEFAULT_RECENT_PROJECTS_LIMIT = 20;

export const normalizeProjectId = (value: unknown): string => {
  if (typeof value !== 'string') return '';
  return value.trim();
};

export const parseRecentProjectIds = (value: string | null): string[] => {
  if (!value) return [];
  try {
    const parsed = JSON.parse(value);
    if (!Array.isArray(parsed)) return [];
    return mergeRecentProjectIds([], parsed);
  } catch {
    return [];
  }
};

export const mergeRecentProjectIds = (
  existing: string[],
  incoming: Array<unknown>,
  limit = DEFAULT_RECENT_PROJECTS_LIMIT
): string[] => {
  const normalizedLimit = Number.isFinite(limit) ? Math.max(1, Math.trunc(limit)) : DEFAULT_RECENT_PROJECTS_LIMIT;
  const next: string[] = [];
  const seen = new Set<string>();
  const pushUnique = (value: unknown) => {
    const projectId = normalizeProjectId(value);
    if (!projectId || seen.has(projectId)) return;
    seen.add(projectId);
    next.push(projectId);
  };

  incoming.forEach(pushUnique);
  existing.forEach(pushUnique);
  return next.slice(0, normalizedLimit);
};
