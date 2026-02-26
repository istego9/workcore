import type { ChatKitStreamEvent } from './types';

export type SseParseResult = {
  buffer: string;
  events: ChatKitStreamEvent[];
};

export const parseSseBuffer = (input: string): SseParseResult => {
  const frames = input.split('\n\n');
  const nextBuffer = frames.pop() || '';
  const events: ChatKitStreamEvent[] = [];

  frames.forEach((frame) => {
    const lines = frame
      .split('\n')
      .map((line) => line.trim())
      .filter((line) => line.startsWith('data:'));
    if (!lines.length) return;
    const payload = lines.map((line) => line.slice('data:'.length).trim()).join('\n');
    if (!payload) return;
    try {
      const parsed = JSON.parse(payload) as ChatKitStreamEvent;
      events.push(parsed);
    } catch {
      // Ignore malformed event payloads; caller should report stream parse errors separately.
    }
  });

  return { buffer: nextBuffer, events };
};
