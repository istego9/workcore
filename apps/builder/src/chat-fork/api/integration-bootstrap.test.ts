import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { __testing, bootstrapIntegration } from './integration-bootstrap';

describe('integration-bootstrap', () => {
  const fetchMock = vi.fn();

  beforeEach(() => {
    vi.stubGlobal('fetch', fetchMock);
    __testing.capabilitiesCache.clear();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.resetAllMocks();
  });

  it('enforces pinned host policy and canonical /chat endpoint', async () => {
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
                  allowed_domains: ['api.runwcr.com']
                }
              },
              urls: {
                integration_capabilities: 'https://api.hq21.tech/integration-capabilities',
                integration_test_json: 'https://api.hq21.tech/agent-integration-test.json'
              }
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
                deprecated_alias_sunset: '2026-04-04T00:00:00Z'
              }
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
              checks: []
            }),
            { status: 200, headers: { 'content-type': 'application/json' } }
          )
        );
      }
      return Promise.resolve(new Response(null, { status: 404 }));
    });

    const result = await bootstrapIntegration({
      apiUrl: 'https://api.hq21.tech/chatkit',
      projectId: 'proj_1'
    });

    expect(result.integrationReady).toBe(true);
    expect(result.resolvedFromAlias).toBe(true);
    expect(result.resolvedApiUrl).toBe('https://api.runwcr.com/chat');
    expect(result.warnings).toContain('host_policy_enforced:pinned_runwcr');
  });

  it('marks integration as not ready when doctor has FAIL checks', async () => {
    fetchMock.mockImplementation((rawUrl: string | URL) => {
      const url = String(rawUrl);
      if (url.endsWith('/agent-integration-kit.json')) {
        return Promise.resolve(
          new Response(
            JSON.stringify({
              integration_manifest: {
                chat_api_url: 'https://api.workcore.build/chat',
                integration_capabilities_url: 'https://api.workcore.build/integration-capabilities',
                host_policy: {
                  mode: 'request_host',
                  enforcement: 'advisory'
                }
              },
              urls: {
                integration_test_json: 'https://api.workcore.build/agent-integration-test.json'
              }
            }),
            { status: 200, headers: { 'content-type': 'application/json' } }
          )
        );
      }
      if (url.endsWith('/integration-capabilities')) {
        return Promise.resolve(
          new Response(JSON.stringify({ chat: { canonical_endpoint: '/chat' } }), {
            status: 200,
            headers: { 'content-type': 'application/json' }
          })
        );
      }
      if (url.includes('/agent-integration-test.json')) {
        return Promise.resolve(
          new Response(
            JSON.stringify({
              summary: { status: 'FAIL' },
              checks: [{ id: 'host_policy_compliance', status: 'FAIL' }]
            }),
            { status: 200, headers: { 'content-type': 'application/json' } }
          )
        );
      }
      return Promise.resolve(new Response(null, { status: 404 }));
    });

    const result = await bootstrapIntegration({ apiUrl: 'https://api.workcore.build/chat' });

    expect(result.integrationReady).toBe(false);
    expect(result.doctorStatus).toBe('FAIL');
    expect(result.doctorFailChecks).toEqual(['host_policy_compliance']);
  });

  it('caches integration-capabilities response across bootstrap calls', async () => {
    fetchMock.mockImplementation((rawUrl: string | URL) => {
      const url = String(rawUrl);
      if (url.endsWith('/agent-integration-kit.json')) {
        return Promise.resolve(
          new Response(
            JSON.stringify({
              integration_manifest: {
                chat_api_url: 'https://api.workcore.build/chat',
                integration_capabilities_url: 'https://api.workcore.build/integration-capabilities'
              },
              urls: {
                integration_test_json: 'https://api.workcore.build/agent-integration-test.json'
              }
            }),
            { status: 200, headers: { 'content-type': 'application/json' } }
          )
        );
      }
      if (url.endsWith('/integration-capabilities')) {
        return Promise.resolve(
          new Response(JSON.stringify({ chat: { canonical_endpoint: '/chat' } }), {
            status: 200,
            headers: { 'content-type': 'application/json' }
          })
        );
      }
      if (url.includes('/agent-integration-test.json')) {
        return Promise.resolve(
          new Response(JSON.stringify({ summary: { status: 'PASS' }, checks: [] }), {
            status: 200,
            headers: { 'content-type': 'application/json' }
          })
        );
      }
      return Promise.resolve(new Response(null, { status: 404 }));
    });

    await bootstrapIntegration({ apiUrl: 'https://api.workcore.build/chat' });
    await bootstrapIntegration({ apiUrl: 'https://api.workcore.build/chat' });

    const capabilityCalls = fetchMock.mock.calls.filter((entry) => String(entry[0]).endsWith('/integration-capabilities'));
    expect(capabilityCalls).toHaveLength(1);
  });
});
