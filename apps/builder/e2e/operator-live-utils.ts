import fs from 'node:fs';
import path from 'node:path';
import { expect, type APIRequestContext, type Download, type Page } from '@playwright/test';
import { apiAuthHeaders, e2eApiAuthToken, e2eTenantId, installApiAuthRoute } from './env';

const operatorArtifactsDir = (process.env.E2E_OPERATOR_ARTIFACTS_DIR || '').trim();

export const primeOperatorAuth = async (page: Page, projectId?: string): Promise<void> => {
  await installApiAuthRoute(page, projectId);
  await page.addInitScript(
    ({ token, tenant }) => {
      if (token) window.localStorage.setItem('workcore.api_auth_token', token);
      if (tenant) window.localStorage.setItem('workcore.tenant_id', tenant);
    },
    { token: e2eApiAuthToken, tenant: e2eTenantId }
  );
};

export const readDownloadedJson = async <T>(download: Download, prefix: string): Promise<T> => {
  const downloadPath = await download.path();
  expect(downloadPath).toBeTruthy();
  const raw = fs.readFileSync(downloadPath!, 'utf-8');
  if (operatorArtifactsDir) {
    fs.mkdirSync(operatorArtifactsDir, { recursive: true });
    const targetPath = path.join(operatorArtifactsDir, `${prefix}-${download.suggestedFilename()}`);
    fs.copyFileSync(downloadPath!, targetPath);
  }
  return JSON.parse(raw) as T;
};

export const waitForRunTerminal = async (
  request: APIRequestContext,
  baseUrl: string,
  projectId: string,
  runId: string,
  timeoutMs = 15_000
): Promise<any> => {
  const startedAt = Date.now();
  while (Date.now() - startedAt < timeoutMs) {
    const response = await request.get(`${baseUrl}/runs/${runId}`, {
      headers: apiAuthHeaders(projectId)
    });
    expect(response.ok()).toBeTruthy();
    const payload = await response.json();
    if (['COMPLETED', 'FAILED', 'CANCELLED', 'WAITING_FOR_INPUT'].includes(payload.status)) {
      return payload;
    }
    await new Promise((resolve) => setTimeout(resolve, 500));
  }
  throw new Error(`Run ${runId} did not reach terminal state within ${timeoutMs}ms`);
};
