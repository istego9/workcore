import { parseSseBuffer } from '../protocol/sse';
import type {
  ChatKitRequest,
  ChatKitStreamEvent,
  InputTranscribeRequest,
  TranscriptionResult
} from '../protocol/types';

export type TypedPlatformError = {
  code: string;
  message: string;
  category: string;
  retryable?: boolean | null;
  retry_after_s?: number | null;
  bad_fields?: string[] | null;
  unsupported_feature?: string | null;
  docs_ref?: string | null;
  correlation_id?: string | null;
};

export class ChatKitHttpError extends Error {
  status: number;
  endpoint: string;
  correlationId: string | null;
  traceId: string;
  typedError: TypedPlatformError;
  retryAfterSeconds: number | null;

  constructor(params: {
    status: number;
    endpoint: string;
    correlationId: string | null;
    traceId: string;
    typedError: TypedPlatformError;
    retryAfterSeconds: number | null;
  }) {
    super(params.typedError.message || `${params.status} request failed`);
    this.name = 'ChatKitHttpError';
    this.status = params.status;
    this.endpoint = params.endpoint;
    this.correlationId = params.correlationId;
    this.traceId = params.traceId;
    this.typedError = params.typedError;
    this.retryAfterSeconds = params.retryAfterSeconds;
  }
}

export type ChatKitClientOptions = {
  apiUrl: string;
  authToken?: string;
  tenantId: string;
  projectId?: string;
  onLegacyAliasUsed?: (payload: { originalUrl: string; resolvedUrl: string }) => void;
  requestIdFactory?: () => string;
  logger?: Pick<Console, 'info' | 'warn'>;
};

const DEFAULT_RETRY_ATTEMPTS = 2;

const toStringList = (value: unknown): string[] | null => {
  if (!Array.isArray(value)) return null;
  const next = value.map((item) => String(item)).map((item) => item.trim()).filter(Boolean);
  return next.length ? next : null;
};

const trim = (value: string | null | undefined): string => (typeof value === 'string' ? value.trim() : '');

const createRequestId = (prefix: string, factory?: () => string): string => {
  const generated = trim(factory?.());
  if (generated) return generated;
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return `${prefix}_${crypto.randomUUID()}`;
  }
  return `${prefix}_${Math.random().toString(36).slice(2, 12)}`;
};

const parseRetryAfterHeader = (value: string | null): number | null => {
  if (!value) return null;
  const numeric = Number(value);
  if (Number.isFinite(numeric) && numeric >= 0) return numeric;
  const target = Date.parse(value);
  if (Number.isNaN(target)) return null;
  const deltaMs = target - Date.now();
  if (deltaMs <= 0) return 0;
  return Math.ceil(deltaMs / 1000);
};

const normalizeChatApiUrl = (apiUrl: string): { url: string; resolvedFromAlias: boolean } => {
  try {
    const parsed = new URL(apiUrl);
    const aliasPattern = /\/chatkit\/?$/i;
    if (!aliasPattern.test(parsed.pathname)) {
      return { url: parsed.toString(), resolvedFromAlias: false };
    }
    parsed.pathname = parsed.pathname.replace(aliasPattern, '/chat');
    return { url: parsed.toString(), resolvedFromAlias: true };
  } catch {
    const normalized = apiUrl.replace(/\/chatkit\/?$/i, '/chat');
    return { url: normalized, resolvedFromAlias: normalized !== apiUrl };
  }
};

const emitLegacyAliasAlert = (originalUrl: string, resolvedUrl: string, opts: ChatKitClientOptions) => {
  opts.onLegacyAliasUsed?.({ originalUrl, resolvedUrl });
  if (typeof window !== 'undefined' && typeof window.dispatchEvent === 'function') {
    window.dispatchEvent(
      new CustomEvent('workcore.integration.legacy_chat_alias_used', {
        detail: {
          original_url: originalUrl,
          resolved_url: resolvedUrl,
          observed_at: new Date().toISOString()
        }
      })
    );
  }
};

const buildHeaders = (
  opts: ChatKitClientOptions,
  correlationId: string,
  traceId: string
): Headers => {
  const headers = new Headers({
    'Content-Type': 'application/json',
    'X-Tenant-Id': trim(opts.tenantId) || 'local',
    'X-Correlation-Id': correlationId,
    'X-Trace-Id': traceId
  });
  const projectId = trim(opts.projectId);
  if (projectId) {
    headers.set('X-Project-Id', projectId);
  }
  const authToken = trim(opts.authToken);
  if (authToken) {
    headers.set('Authorization', `Bearer ${authToken}`);
  }
  return headers;
};

const parseErrorEnvelope = async (
  response: Response,
  fallbackCorrelationId: string,
  endpoint: string,
  traceId: string
): Promise<ChatKitHttpError> => {
  let payload: any = null;
  try {
    payload = await response.json();
  } catch {
    payload = null;
  }

  const nested = payload?.error && typeof payload.error === 'object' ? payload.error : {};

  const retryAfterFromBody =
    typeof nested?.retry_after_s === 'number' && Number.isFinite(nested.retry_after_s)
      ? nested.retry_after_s
      : null;
  const retryAfterFromHeader = parseRetryAfterHeader(response.headers.get('Retry-After'));
  const retryAfterSeconds = retryAfterFromBody ?? retryAfterFromHeader;

  const typedError: TypedPlatformError = {
    code:
      typeof nested?.code === 'string' && nested.code.trim()
        ? nested.code.trim()
        : `HTTP_${response.status || 'UNKNOWN'}`,
    message:
      typeof nested?.message === 'string' && nested.message.trim()
        ? nested.message.trim()
        : `${response.status} ${response.statusText || 'Request failed'}`,
    category:
      typeof nested?.category === 'string' && nested.category.trim() ? nested.category.trim() : 'internal',
    retryable: typeof nested?.retryable === 'boolean' ? nested.retryable : null,
    retry_after_s: retryAfterSeconds,
    bad_fields: toStringList(nested?.bad_fields),
    unsupported_feature:
      typeof nested?.unsupported_feature === 'string' ? nested.unsupported_feature : null,
    docs_ref: typeof nested?.docs_ref === 'string' ? nested.docs_ref : null,
    correlation_id:
      (typeof nested?.correlation_id === 'string' && nested.correlation_id) ||
      (typeof payload?.correlation_id === 'string' && payload.correlation_id) ||
      response.headers.get('X-Correlation-Id') ||
      fallbackCorrelationId
  };

  return new ChatKitHttpError({
    status: response.status,
    endpoint,
    correlationId: typedError.correlation_id || null,
    traceId,
    typedError,
    retryAfterSeconds
  });
};

const sleep = async (ms: number): Promise<void> => {
  if (ms <= 0) return;
  await new Promise((resolve) => {
    setTimeout(resolve, ms);
  });
};

const executeRequest = async (
  req: ChatKitRequest,
  opts: ChatKitClientOptions
): Promise<Response> => {
  const logger = opts.logger || console;
  const normalized = normalizeChatApiUrl(opts.apiUrl);
  if (normalized.resolvedFromAlias) {
    emitLegacyAliasAlert(opts.apiUrl, normalized.url, opts);
    logger.warn('[chat-fork] Legacy /chatkit endpoint used; rewritten to /chat', {
      endpoint: normalized.url
    });
  }

  let lastError: unknown = null;
  for (let attempt = 1; attempt <= DEFAULT_RETRY_ATTEMPTS; attempt += 1) {
    const correlationId = createRequestId('corr', opts.requestIdFactory);
    const traceId = createRequestId('trace', opts.requestIdFactory);
    const headers = buildHeaders(opts, correlationId, traceId);

    logger.info('[chat-fork] WorkCore request', {
      endpoint: normalized.url,
      request_type: req.type,
      correlation_id: correlationId,
      trace_id: traceId,
      attempt
    });

    let response: Response;
    try {
      response = await fetch(normalized.url, {
        method: 'POST',
        headers,
        body: JSON.stringify(req)
      });
    } catch (error) {
      lastError = error;
      break;
    }

    if (response.ok) {
      return response;
    }

    const typedError = await parseErrorEnvelope(response, correlationId, normalized.url, traceId);
    logger.warn('[chat-fork] WorkCore request failed', {
      endpoint: typedError.endpoint,
      status: typedError.status,
      correlation_id: typedError.correlationId,
      trace_id: typedError.traceId,
      error_code: typedError.typedError.code,
      error_category: typedError.typedError.category,
      retryable: typedError.typedError.retryable,
      retry_after_s: typedError.retryAfterSeconds
    });

    const shouldRetry = typedError.typedError.retryable === true && attempt < DEFAULT_RETRY_ATTEMPTS;
    if (!shouldRetry) {
      throw typedError;
    }

    const waitMs = Math.max(0, Math.floor((typedError.retryAfterSeconds || 0) * 1000));
    await sleep(waitMs);
    lastError = typedError;
  }

  if (lastError instanceof Error) {
    throw lastError;
  }
  throw new Error('Network request failed');
};

export const streamRequest = async (
  req: ChatKitRequest,
  opts: ChatKitClientOptions,
  onEvent: (event: ChatKitStreamEvent) => void
): Promise<void> => {
  const response = await executeRequest(req, opts);

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
  const response = await executeRequest(req, opts);
  return (await response.json()) as TranscriptionResult;
};

export const __testing = {
  normalizeChatApiUrl,
  parseRetryAfterHeader,
  buildHeaders,
  createRequestId,
  parseErrorEnvelope,
  sleep
};
