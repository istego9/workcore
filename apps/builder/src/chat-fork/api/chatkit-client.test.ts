import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ChatKitHttpError, streamRequest, transcribeInput } from './chatkit-client';
import type { ChatKitRequest } from '../protocol/types';

const threadCreateRequest: ChatKitRequest = {
  type: 'threads.create',
  metadata: { project_id: 'proj_1' },
  params: {
    input: {
      content: [{ type: 'input_text', text: 'hello' }],
      attachments: []
    }
  }
};

describe('chatkit-client', () => {
  const fetchMock = vi.fn();

  beforeEach(() => {
    vi.stubGlobal('fetch', fetchMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.resetAllMocks();
  });

  it('rewrites legacy /chatkit endpoint and sends required headers', async () => {
    const eventSpy = vi.fn();
    window.addEventListener('workcore.integration.legacy_chat_alias_used', eventSpy as EventListener);
    fetchMock.mockResolvedValue(
      new Response(JSON.stringify({ type: 'notice', message: 'ok' }), {
        status: 200,
        headers: { 'content-type': 'application/json' }
      })
    );

    const onEvent = vi.fn();
    await streamRequest(
      threadCreateRequest,
      {
        apiUrl: 'https://api.example.com/chatkit',
        authToken: 'token_1',
        tenantId: 'tenant_1',
        projectId: 'proj_1',
        requestIdFactory: () => 'req_fixed'
      },
      onEvent
    );

    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock).toHaveBeenCalledWith(
      'https://api.example.com/chat',
      expect.objectContaining({
        method: 'POST',
        headers: expect.any(Headers)
      })
    );
    const headers = (fetchMock.mock.calls[0]?.[1] as RequestInit)?.headers as Headers;
    expect(headers.get('Authorization')).toBe('Bearer token_1');
    expect(headers.get('X-Tenant-Id')).toBe('tenant_1');
    expect(headers.get('X-Project-Id')).toBe('proj_1');
    expect(headers.get('X-Correlation-Id')).toBe('req_fixed');
    expect(headers.get('X-Trace-Id')).toBe('req_fixed');
    expect(onEvent).toHaveBeenCalledWith({ type: 'notice', message: 'ok' });

    window.removeEventListener('workcore.integration.legacy_chat_alias_used', eventSpy as EventListener);
  });

  it('retries only when typed error is retryable', async () => {
    fetchMock
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            error: {
              code: 'ERR_WORKFLOW_ENGINE_UNAVAILABLE',
              message: 'temporary',
              category: 'transient',
              retryable: true,
              retry_after_s: 0
            },
            correlation_id: 'corr_1'
          }),
          { status: 503, headers: { 'content-type': 'application/json' } }
        )
      )
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ text: 'ok' }), {
          status: 200,
          headers: { 'content-type': 'application/json' }
        })
      );

    const result = await transcribeInput(
      {
        type: 'input.transcribe',
        metadata: { project_id: 'proj_1' },
        params: {
          audio_base64: 'abc',
          mime_type: 'audio/wav'
        }
      },
      {
        apiUrl: 'https://api.example.com/chat',
        tenantId: 'tenant_1',
        requestIdFactory: () => 'retry_case'
      }
    );

    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(result.text).toBe('ok');
  });

  it('does not retry when retryable=false and surfaces typed error fields', async () => {
    fetchMock.mockResolvedValue(
      new Response(
        JSON.stringify({
          error: {
            code: 'INVALID_ARGUMENT',
            message: 'validation failed',
            category: 'validation',
            retryable: false,
            bad_fields: ['metadata.project_id'],
            unsupported_feature: null
          },
          correlation_id: 'corr_validation'
        }),
        { status: 422, headers: { 'content-type': 'application/json', 'Retry-After': '5' } }
      )
    );

    let thrown: ChatKitHttpError | null = null;
    try {
      await transcribeInput(
        {
          type: 'input.transcribe',
          metadata: {},
          params: {
            audio_base64: 'abc',
            mime_type: 'audio/wav'
          }
        },
        {
          apiUrl: 'https://api.example.com/chat',
          tenantId: 'tenant_1',
          requestIdFactory: () => 'validation_case'
        }
      );
    } catch (error) {
      thrown = error as ChatKitHttpError;
    }

    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(thrown).toBeInstanceOf(ChatKitHttpError);
    expect(thrown?.typedError.code).toBe('INVALID_ARGUMENT');
    expect(thrown?.typedError.category).toBe('validation');
    expect(thrown?.typedError.bad_fields).toEqual(['metadata.project_id']);
    expect(thrown?.retryAfterSeconds).toBe(5);
  });
});
