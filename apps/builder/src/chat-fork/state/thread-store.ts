import type { ChatKitStreamEvent, ThreadItem } from '../protocol/types';

export type ThreadState = {
  threadId: string;
  items: ThreadItem[];
  progress: string[];
  notices: string[];
  errors: string[];
};

export const createEmptyThreadState = (): ThreadState => ({
  threadId: '',
  items: [],
  progress: [],
  notices: [],
  errors: []
});

const upsertItem = (items: ThreadItem[], item: ThreadItem): ThreadItem[] => {
  const idx = items.findIndex((current) => current.id === item.id);
  if (idx === -1) return [...items, item];
  const next = items.slice();
  next[idx] = { ...next[idx], ...item };
  return next;
};

const applyWidgetUpdate = (item: ThreadItem, update: Record<string, unknown>): ThreadItem => {
  const updateType = String(update.type || '');
  if (updateType === 'widget.root.updated' && typeof update.widget === 'object' && update.widget) {
    return {
      ...item,
      widget: update.widget as ThreadItem['widget']
    };
  }
  return item;
};

export const applyStreamEvent = (state: ThreadState, event: ChatKitStreamEvent): ThreadState => {
  if (event.type === 'thread.created' && event.thread?.id) {
    return {
      ...state,
      threadId: event.thread.id
    };
  }

  if (event.type === 'thread.item.done' && event.item) {
    const items = upsertItem(state.items, event.item);
    return { ...state, items };
  }

  if (event.type === 'thread.item.added' && event.item) {
    const items = upsertItem(state.items, event.item);
    return { ...state, items };
  }

  if (event.type === 'thread.item.updated' && event.item_id && event.update) {
    const items = state.items.map((item) => {
      if (item.id !== event.item_id) return item;
      return applyWidgetUpdate(item, event.update || {});
    });
    return { ...state, items };
  }

  if (event.type === 'progress_update' && typeof event.text === 'string') {
    return { ...state, progress: [...state.progress, event.text] };
  }

  if (event.type === 'notice' && typeof event.message === 'string') {
    return { ...state, notices: [...state.notices, event.message] };
  }

  if (event.type === 'error') {
    const text = typeof event.message === 'string' ? event.message : 'Unknown stream error';
    return { ...state, errors: [...state.errors, text] };
  }

  return state;
};
