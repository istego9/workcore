export const normalizeProjectId = (value: unknown): string => {
  if (typeof value !== 'string') return '';
  return value.trim();
};
