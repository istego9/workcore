import { describe, expect, it } from 'vitest';
import { buildIntegrationKitLinks } from './integration-kit';

describe('buildIntegrationKitLinks', () => {
  it('builds links from absolute API base URL', () => {
    const links = buildIntegrationKitLinks('https://api.workcore.build', 'https://builder.workcore.build');
    expect(links.integrationKitMarkdown).toBe('https://api.workcore.build/agent-integration-kit');
    expect(links.integrationTestUi).toBe('https://api.workcore.build/agent-integration-test');
    expect(links.integrationTestJson).toBe('https://api.workcore.build/agent-integration-test.json');
    expect(links.validateDraft).toBe('https://api.workcore.build/agent-integration-test/validate-draft');
    expect(links.workflowDraftSchema).toBe('https://api.workcore.build/schemas/workflow-draft.schema.json');
    expect(links.workflowExportSchema).toBe('https://api.workcore.build/schemas/workflow-export-v1.schema.json');
  });

  it('builds links from relative API base URL with path prefix', () => {
    const links = buildIntegrationKitLinks('/api', 'https://builder.workcore.build');
    expect(links.integrationKitJson).toBe('https://builder.workcore.build/api/agent-integration-kit.json');
    expect(links.integrationTestUi).toBe('https://builder.workcore.build/api/agent-integration-test');
    expect(links.validateDraft).toBe('https://builder.workcore.build/api/agent-integration-test/validate-draft');
    expect(links.openapi).toBe('https://builder.workcore.build/api/openapi.yaml');
    expect(links.apiReference).toBe('https://builder.workcore.build/api/api-reference');
  });
});
