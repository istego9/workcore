export const normalizeSchemaTypeLabel = (schemaType: unknown): string | undefined => {
  if (typeof schemaType === 'string') {
    const normalized = schemaType.trim();
    return normalized || undefined;
  }
  if (!Array.isArray(schemaType)) {
    return undefined;
  }
  const normalized = schemaType
    .filter((item): item is string => typeof item === 'string')
    .map((item) => item.trim())
    .filter((item) => item.length > 0);
  if (normalized.length === 0) {
    return undefined;
  }
  return normalized.join(' | ');
};
