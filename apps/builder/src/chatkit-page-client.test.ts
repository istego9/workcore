import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import {
  ChatKitPageHttpError,
  __testing,
  bootstrapIntegration,
  createChatkitFetch,
  formatChatErrorMessage,
} from '../public/chatkit-client.js';

describe('chatkit page client', () => {
  const fetchMock = vi.fn();

  beforeEach(() => {
    vi.stubGlobal('fetch', fetchMock);
    __testing.capabilitiesCache.clear();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.resetAllMocks();
  });

  it('rewrites legacy /chatkit endpoint and injects metadata + headers', async () => {
    const eventSpy = vi.fn();
    window.addEventListener('workcore.integration.legacy_chat_alias_used', eventSpy as EventListener);

    fetchMock.mockResolvedValue(
      new Response(JSON.stringify({ ok: true }), {
        status: 200,
        headers: { 'content-type': 'application/json' },
      })
    );

    const request = createChatkitFetch({
      apiUrl: 'https://api.example.com/chatkit',
      authToken: 'token_1',
      workflowId: 'wf_1',
      workflowVersionId: 'v2',
      projectId: 'proj_1',
      tenantId: 'tenant_1',
      requestIdFactory: () => 'req_fixed',
      logger: { info: vi.fn(), warn: vi.fn() },
    });

    await request('ignored', {
      method: 'POST',
      body: JSON.stringify({
        type: 'threads.create',
        metadata: {},
        params: { input: { content: [], attachments: [] } },
      }),
    });

    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock).toHaveBeenCalledWith(
      'https://api.example.com/chat',
      expect.objectContaining({
        method: 'POST',
        headers: expect.any(Headers),
      })
    );

    const init = fetchMock.mock.calls[0]?.[1] as RequestInit;
    const headers = init.headers as Headers;
    const body = JSON.parse(String(init.body));
    expect(headers.get('Authorization')).toBe('Bearer token_1');
    expect(headers.get('X-Tenant-Id')).toBe('tenant_1');
    expect(headers.get('X-Project-Id')).toBe('proj_1');
    expect(headers.get('X-Correlation-Id')).toBe('req_fixed');
    expect(headers.get('X-Trace-Id')).toBe('req_fixed');
    expect(body.metadata).toMatchObject({
      workflow_id: 'wf_1',
      workflow_version_id: 'v2',
      project_id: 'proj_1',
    });
    expect(eventSpy).toHaveBeenCalledTimes(1);

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
              retry_after_s: 0,
            },
            correlation_id: 'corr_1',
          }),
          { status: 503, headers: { 'content-type': 'application/json' } }
        )
      )
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ ok: true }), {
          status: 200,
          headers: { 'content-type': 'application/json' },
        })
      );

    const request = createChatkitFetch({
      apiUrl: 'https://api.example.com/chat',
      tenantId: 'tenant_1',
      requestIdFactory: () => 'retry_case',
      logger: { info: vi.fn(), warn: vi.fn() },
    });

    await request('ignored', {
      method: 'POST',
      body: JSON.stringify({ type: 'input.transcribe', metadata: {}, params: {} }),
    });

    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it('throws typed validation errors with surfaced bad fields', async () => {
    fetchMock.mockResolvedValue(
      new Response(
        JSON.stringify({
          error: {
            code: 'INVALID_ARGUMENT',
            message: 'validation failed',
            category: 'validation',
            retryable: false,
            bad_fields: ['metadata.project_id'],
            docs_ref: '/docs/errors#invalid-argument',
          },
          correlation_id: 'corr_validation',
        }),
        {
          status: 422,
          headers: { 'content-type': 'application/json', 'Retry-After': '5' },
        }
      )
    );

    const request = createChatkitFetch({
      apiUrl: 'https://api.example.com/chat',
      tenantId: 'tenant_1',
      requestIdFactory: () => 'validation_case',
      logger: { info: vi.fn(), warn: vi.fn() },
    });

    let thrown: ChatKitPageHttpError | null = null;
    try {
      await request('ignored', {
        method: 'POST',
        body: JSON.stringify({ type: 'input.transcribe', metadata: {}, params: {} }),
      });
    } catch (error) {
      thrown = error as ChatKitPageHttpError;
    }

    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(thrown).toBeInstanceOf(ChatKitPageHttpError);
    expect(thrown?.typedError.code).toBe('INVALID_ARGUMENT');
    expect(thrown?.typedError.category).toBe('validation');
    expect(thrown?.typedError.bad_fields).toEqual(['metadata.project_id']);
    expect(thrown?.retryAfterSeconds).toBe(5);
    expect(formatChatErrorMessage(thrown)).toBe(
      '[INVALID_ARGUMENT] validation failed (metadata.project_id; docs: /docs/errors#invalid-argument)'
    );
  });

  it('bootstraps canonical host policy, doctor scope, and cached capabilities', async () => {
    fetchMock.mockImplementation((rawUrl: string | URL) => {
      const url = String(rawUrl);
      if (url.endsWith('/agent-integration-kit.json')) {
        return Promise.resolve(
          new Response(
            JSON.stringify({
              integration_manifest: {
                api_base_url: 'https://api.hq21.tech',
                chat_api_url: 'https://api.hq21.tech/chat',
                integration_capabilities_url: 'https://api.hq21.tech/integration-capabilities',
                host_policy: {
                  policy_id: 'pinned_runwcr',
                  mode: 'pinned',
                  enforcement: 'required',
                  canonical_base_url: 'https://api.runwcr.com',
                  allowed_domains: ['api.runwcr.com'],
                },
              },
              urls: {
                integration_capabilities: 'https://api.hq21.tech/integration-capabilities',
                integration_test_json: 'https://api.hq21.tech/agent-integration-test.json',
              },
            }),
            { status: 200, headers: { 'content-type': 'application/json' } }
          )
        );
      }
      if (url.endsWith('/integration-capabilities')) {
        return Promise.resolve(
          new Response(
            JSON.stringify({
              chat: {
                canonical_endpoint: '/chat',
                deprecated_alias: '/chatkit',
              },
            }),
            { status: 200, headers: { 'content-type': 'application/json' } }
          )
        );
      }
      if (url.includes('/agent-integration-test.json')) {
        return Promise.resolve(
          new Response(
            JSON.stringify({
              summary: { status: 'PASS' },
              checks: [],
            }),
            { status: 200, headers: { 'content-type': 'application/json' } }
          )
        );
      }
      return Promise.resolve(new Response(null, { status: 404 }));
    });

    const first = await bootstrapIntegration({
      apiUrl: 'https://api.hq21.tech/chatkit',
      projectId: 'proj_1',
    });
    const second = await bootstrapIntegration({
      apiUrl: 'https://api.hq21.tech/chatkit',
      projectId: 'proj_1',
    });

    expect(first.integrationReady).toBe(true);
    expect(first.resolvedApiUrl).toBe('https://api.runwcr.com/chat');
    expect(first.warnings).toContain('host_policy_enforced:pinned_runwcr');
    expect(second.resolvedApiUrl).toBe('https://api.runwcr.com/chat');

    const capabilityCalls = fetchMock.mock.calls.filter((entry) => String(entry[0]).endsWith('/integration-capabilities'));
    const doctorCalls = fetchMock.mock.calls.filter((entry) => String(entry[0]).includes('/agent-integration-test.json'));
    expect(capabilityCalls).toHaveLength(1);
    expect(doctorCalls[0]?.[0]).toContain('project_id=proj_1');
  });
});
