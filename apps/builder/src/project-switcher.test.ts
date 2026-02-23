import { describe, expect, it } from 'vitest';
import { normalizeProjectId } from './project-switcher';

describe('project switcher helpers', () => {
  it('normalizes project ids by trimming whitespace', () => {
    expect(normalizeProjectId('  proj_123  ')).toBe('proj_123');
    expect(normalizeProjectId('')).toBe('');
    expect(normalizeProjectId(null)).toBe('');
  });
});
