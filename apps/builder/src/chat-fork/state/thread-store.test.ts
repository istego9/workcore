import { describe, expect, it } from 'vitest';
import { applyStreamEvent, createEmptyThreadState } from './thread-store';

describe('thread-store', () => {
  it('stores thread id from thread.created', () => {
    const next = applyStreamEvent(createEmptyThreadState(), {
      type: 'thread.created',
      thread: { id: 'thr_1' }
    });
    expect(next.threadId).toBe('thr_1');
  });

  it('upserts items and progress/errors', () => {
    let state = createEmptyThreadState();
    state = applyStreamEvent(state, {
      type: 'thread.item.done',
      item: { id: 'itm_1', type: 'assistant_message', content: [{ text: 'hello' }] }
    });
    state = applyStreamEvent(state, {
      type: 'progress_update',
      text: 'Run started'
    });
    state = applyStreamEvent(state, {
      type: 'error',
      message: 'boom'
    });

    expect(state.items).toHaveLength(1);
    expect(state.progress[state.progress.length - 1]).toBe('Run started');
    expect(state.errors[state.errors.length - 1]).toBe('boom');
  });

  it('applies widget root update event', () => {
    let state = createEmptyThreadState();
    state = applyStreamEvent(state, {
      type: 'thread.item.done',
      item: {
        id: 'w_1',
        type: 'widget',
        widget: { type: 'Card', children: [{ type: 'Text', value: 'before' }] }
      }
    });

    state = applyStreamEvent(state, {
      type: 'thread.item.updated',
      item_id: 'w_1',
      update: {
        type: 'widget.root.updated',
        widget: { type: 'Card', children: [{ type: 'Text', value: 'after' }] }
      }
    });

    expect((state.items[0].widget?.children || [])[0]?.value).toBe('after');
  });
});
