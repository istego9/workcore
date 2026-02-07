export type IntegrationKitLinks = {
  integrationKitMarkdown: string;
  integrationKitJson: string;
  integrationTestUi: string;
  integrationTestJson: string;
  validateDraft: string;
  openapi: string;
  apiReference: string;
  workflowAuthoringGuide: string;
  workflowDraftSchema: string;
  workflowExportSchema: string;
};

const buildBaseUrl = (apiBase: string, origin: string) => {
  const base = new URL(apiBase, origin);
  base.search = '';
  base.hash = '';
  if (!base.pathname.endsWith('/')) {
    base.pathname = `${base.pathname}/`;
  }
  return base;
};

export const buildIntegrationKitLinks = (apiBase: string, origin: string): IntegrationKitLinks => {
  const base = buildBaseUrl(apiBase, origin);
  const resolve = (path: string) => new URL(path, base).toString();
  return {
    integrationKitMarkdown: resolve('agent-integration-kit'),
    integrationKitJson: resolve('agent-integration-kit.json'),
    integrationTestUi: resolve('agent-integration-test'),
    integrationTestJson: resolve('agent-integration-test.json'),
    validateDraft: resolve('agent-integration-test/validate-draft'),
    openapi: resolve('openapi.yaml'),
    apiReference: resolve('api-reference'),
    workflowAuthoringGuide: resolve('workflow-authoring-guide'),
    workflowDraftSchema: resolve('schemas/workflow-draft.schema.json'),
    workflowExportSchema: resolve('schemas/workflow-export-v1.schema.json')
  };
};
