import { describe, expect, it } from 'vitest';
import { parseSseBuffer } from './sse';

describe('parseSseBuffer', () => {
  it('parses multiple data frames and returns leftover buffer', () => {
    const input = [
      'data: {"type":"thread.created","thread":{"id":"thr_1"}}',
      '',
      'data: {"type":"progress_update","text":"Run started"}',
      '',
      'data: {"type":"thread.item.done"}'
    ].join('\n');

    const parsed = parseSseBuffer(input);
    expect(parsed.events).toHaveLength(2);
    expect(parsed.events[0].type).toBe('thread.created');
    expect(parsed.events[1].type).toBe('progress_update');
    expect(parsed.buffer).toContain('thread.item.done');
  });

  it('ignores malformed payloads', () => {
    const parsed = parseSseBuffer('data: {bad json}\n\n');
    expect(parsed.events).toHaveLength(0);
  });
});
