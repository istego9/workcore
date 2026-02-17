import { describe, expect, it } from 'vitest';
import {
  mergeRecentProjectIds,
  normalizeProjectId,
  parseRecentProjectIds
} from './project-switcher';

describe('project switcher helpers', () => {
  it('normalizes project ids by trimming whitespace', () => {
    expect(normalizeProjectId('  proj_123  ')).toBe('proj_123');
    expect(normalizeProjectId('')).toBe('');
    expect(normalizeProjectId(null)).toBe('');
  });

  it('merges incoming ids before existing and removes duplicates', () => {
    const result = mergeRecentProjectIds(['proj_2', 'proj_1'], ['proj_3', '  proj_1  ', '', 'proj_2']);
    expect(result).toEqual(['proj_3', 'proj_1', 'proj_2']);
  });

  it('applies the recents limit', () => {
    const result = mergeRecentProjectIds([], ['proj_1', 'proj_2', 'proj_3'], 2);
    expect(result).toEqual(['proj_1', 'proj_2']);
  });

  it('parses stored recent ids and skips invalid payloads', () => {
    expect(parseRecentProjectIds('["proj_1"," proj_2 ","","proj_1"]')).toEqual(['proj_1', 'proj_2']);
    expect(parseRecentProjectIds('{"nope":1}')).toEqual([]);
    expect(parseRecentProjectIds('bad json')).toEqual([]);
    expect(parseRecentProjectIds(null)).toEqual([]);
  });
});
