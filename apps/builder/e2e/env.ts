import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import type { Page } from '@playwright/test';

const DEFAULT_BASE_URL = 'http://workcore.build';

const stripTrailingSlash = (value: string) => value.replace(/\/+$/, '');

const baseUrlRaw = stripTrailingSlash(process.env.E2E_BASE_URL || DEFAULT_BASE_URL);
const baseUrl = new URL(baseUrlRaw);
const basePort = baseUrl.port ? `:${baseUrl.port}` : '';

const rootHost = baseUrl.hostname.startsWith('builder.')
  ? baseUrl.hostname.slice('builder.'.length)
  : baseUrl.hostname;

const inferredApiHost = rootHost === 'localhost' ? 'api.localhost' : `api.${rootHost}`;

export const e2eBaseUrl = baseUrlRaw;
export const apiBaseUrl = stripTrailingSlash(
  process.env.E2E_API_BASE_URL || `${baseUrl.protocol}//${inferredApiHost}${basePort}`
);
// `E2E_CHATKIT_API_URL` remains as a deprecated compatibility alias during migration.
export const chatApiUrl = stripTrailingSlash(
  process.env.E2E_CHAT_API_URL || process.env.E2E_CHATKIT_API_URL || `${apiBaseUrl}/chat`
);

const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..', '..');

const readTokenFromEnvFile = (filename: string): string => {
  const filePath = path.join(repoRoot, filename);
  if (!fs.existsSync(filePath)) {
    return '';
  }
  const content = fs.readFileSync(filePath, 'utf-8');
  for (const rawLine of content.split(/\r?\n/)) {
    const line = rawLine.trim();
    if (!line || line.startsWith('#')) {
      continue;
    }
    const [key, ...rest] = line.split('=');
    if (key === 'WORKCORE_API_AUTH_TOKEN') {
      return rest.join('=').trim();
    }
  }
  return '';
};

const resolvedApiAuthToken =
  process.env.E2E_API_AUTH_TOKEN ||
  process.env.WORKCORE_API_AUTH_TOKEN ||
  readTokenFromEnvFile('.env.docker') ||
  readTokenFromEnvFile('.env.docker.example');

const resolvedTenantId = (process.env.E2E_TENANT_ID || 'local').trim();
export const e2eApiAuthToken = resolvedApiAuthToken;
export const e2eTenantId = resolvedTenantId;

export const apiAuthHeaders = (projectId?: string): Record<string, string> => {
  const headers: Record<string, string> = {};
  if (resolvedApiAuthToken) {
    headers.Authorization = `Bearer ${resolvedApiAuthToken}`;
  }
  if (resolvedTenantId) {
    headers['X-Tenant-Id'] = resolvedTenantId;
  }
  if (projectId && projectId.trim()) {
    headers['X-Project-Id'] = projectId.trim();
  }
  return headers;
};

export const installApiAuthRoute = async (page: Page, projectId?: string): Promise<void> => {
  const base = apiBaseUrl.replace(/\/+$/, '');
  await page.route(`${base}/**`, async (route) => {
    const request = route.request();
    const headers = {
      ...request.headers(),
      ...apiAuthHeaders(projectId)
    };
    await route.continue({ headers });
  });
};

export const resolveUrl = (value: string): URL => {
  return new URL(value, `${baseUrl.protocol}//${baseUrl.host}`);
};
