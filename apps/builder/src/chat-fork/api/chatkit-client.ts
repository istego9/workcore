import { parseSseBuffer } from '../protocol/sse';
import type {
  ChatKitRequest,
  ChatKitStreamEvent,
  InputTranscribeRequest,
  TranscriptionResult
} from '../protocol/types';

export type ChatKitClientOptions = {
  apiUrl: string;
  authToken?: string;
  tenantId: string;
};

const buildHeaders = (opts: ChatKitClientOptions) => {
  const headers = new Headers({ 'Content-Type': 'application/json', 'X-Tenant-Id': opts.tenantId });
  if (opts.authToken) {
    headers.set('Authorization', `Bearer ${opts.authToken}`);
  }
  return headers;
};

const readErrorMessage = async (response: Response): Promise<string> => {
  try {
    const json = await response.json();
    if (typeof json?.error === 'string') return json.error;
    if (typeof json?.error?.message === 'string') return json.error.message;
    if (typeof json?.message === 'string') return json.message;
  } catch {
    // noop
  }
  return `${response.status} ${response.statusText}`;
};

export const streamRequest = async (
  req: ChatKitRequest,
  opts: ChatKitClientOptions,
  onEvent: (event: ChatKitStreamEvent) => void
): Promise<void> => {
  const response = await fetch(opts.apiUrl, {
    method: 'POST',
    headers: buildHeaders(opts),
    body: JSON.stringify(req)
  });
  if (!response.ok) {
    throw new Error(await readErrorMessage(response));
  }
  if (!response.body) {
    throw new Error('Empty stream response body');
  }

  const contentType = response.headers.get('content-type') || '';
  if (!contentType.includes('text/event-stream')) {
    const parsed = (await response.json()) as ChatKitStreamEvent;
    if (parsed?.type) {
      onEvent(parsed);
    }
    return;
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const parsed = parseSseBuffer(buffer);
    buffer = parsed.buffer;
    parsed.events.forEach(onEvent);
  }
};

export const transcribeInput = async (
  req: InputTranscribeRequest,
  opts: ChatKitClientOptions
): Promise<TranscriptionResult> => {
  const response = await fetch(opts.apiUrl, {
    method: 'POST',
    headers: buildHeaders(opts),
    body: JSON.stringify(req)
  });
  if (!response.ok) {
    throw new Error(await readErrorMessage(response));
  }
  return (await response.json()) as TranscriptionResult;
};
