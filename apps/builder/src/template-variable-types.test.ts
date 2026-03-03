import { describe, expect, it } from 'vitest';
import { normalizeSchemaTypeLabel } from './template-variable-types';

describe('normalizeSchemaTypeLabel', () => {
  it('keeps plain string schema types', () => {
    expect(normalizeSchemaTypeLabel('string')).toBe('string');
    expect(normalizeSchemaTypeLabel('  number  ')).toBe('number');
  });

  it('joins union schema types from arrays', () => {
    expect(normalizeSchemaTypeLabel(['string', 'null'])).toBe('string | null');
    expect(normalizeSchemaTypeLabel(['  integer  ', 7, null, 'null'])).toBe('integer | null');
  });

  it('returns undefined for unsupported values', () => {
    expect(normalizeSchemaTypeLabel(undefined)).toBeUndefined();
    expect(normalizeSchemaTypeLabel(null)).toBeUndefined();
    expect(normalizeSchemaTypeLabel({ type: 'string' })).toBeUndefined();
    expect(normalizeSchemaTypeLabel([1, true, null])).toBeUndefined();
    expect(normalizeSchemaTypeLabel(['   '])).toBeUndefined();
  });
});
