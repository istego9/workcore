const DEFAULT_BASE_URL = 'http://workcore.build';

const stripTrailingSlash = (value: string) => value.replace(/\/+$/, '');

const baseUrlRaw = stripTrailingSlash(process.env.E2E_BASE_URL || DEFAULT_BASE_URL);
const baseUrl = new URL(baseUrlRaw);
const basePort = baseUrl.port ? `:${baseUrl.port}` : '';

const rootHost = baseUrl.hostname.startsWith('builder.')
  ? baseUrl.hostname.slice('builder.'.length)
  : baseUrl.hostname;

const inferredApiHost = rootHost === 'localhost' ? 'api.localhost' : `api.${rootHost}`;
const inferredChatkitHost = rootHost === 'localhost' ? 'chatkit.localhost' : `chatkit.${rootHost}`;

export const e2eBaseUrl = baseUrlRaw;
export const apiBaseUrl = stripTrailingSlash(
  process.env.E2E_API_BASE_URL || `${baseUrl.protocol}//${inferredApiHost}${basePort}`
);
export const chatkitApiUrl =
  process.env.E2E_CHATKIT_API_URL || `${baseUrl.protocol}//${inferredChatkitHost}${basePort}/chatkit`;

export const apiAuthHeaders = (): Record<string, string> => {
  const token = process.env.E2E_API_AUTH_TOKEN;
  if (!token) return {};
  return { Authorization: `Bearer ${token}` };
};

export const resolveUrl = (value: string): URL => {
  return new URL(value, `${baseUrl.protocol}//${baseUrl.host}`);
};
