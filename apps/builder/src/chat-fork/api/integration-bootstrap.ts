export type IntegrationAuthProfile = {
  type?: string;
  token_url?: string;
  scope?: string;
  audience?: string | null;
};

export type IntegrationHostPolicy = {
  policy_id?: string;
  mode?: 'request_host' | 'pinned' | string;
  enforcement?: 'advisory' | 'required' | string;
  canonical_base_url?: string;
  allowed_domains?: string[];
};

export type IntegrationManifest = {
  api_base_url?: string;
  chat_api_url?: string;
  integration_capabilities_url?: string;
  required_headers?: string[];
  optional_headers?: string[];
  auth_profile?: IntegrationAuthProfile;
  host_policy?: IntegrationHostPolicy;
  project_scope?: {
    default_chat_workflow_id?: string | null;
  };
};

export type IntegrationCapabilities = {
  chat?: {
    canonical_endpoint?: string;
    deprecated_alias?: string | null;
    deprecated_alias_sunset?: string | null;
    project_scoped_thread_create?: boolean;
    input_transcribe?: boolean;
    streaming_sse?: boolean;
  };
  runtime_features?: {
    document_payload?: {
      artifact_ref_default?: boolean;
    };
    projection_controls?: {
      state_exclude_paths?: boolean;
      output_include_paths?: boolean;
    };
    capability_registry?: boolean;
    workflow_version_pinning?: boolean;
  };
};

export type IntegrationDoctorReport = {
  summary?: {
    status?: 'PASS' | 'WARN' | 'FAIL' | string;
    failed?: number;
    warned?: number;
    passed?: number;
    total?: number;
  };
  checks?: Array<{
    id?: string;
    status?: 'PASS' | 'WARN' | 'FAIL' | string;
    code?: string;
    message?: string;
  }>;
};

export type AgentIntegrationKit = {
  urls?: {
    integration_capabilities?: string;
    integration_test_json?: string;
    chat_endpoint?: string;
  };
  integration_manifest?: IntegrationManifest;
};

export type IntegrationBootstrapResult = {
  resolvedApiUrl: string;
  resolvedFromAlias: boolean;
  integrationReady: boolean;
  doctorStatus: 'PASS' | 'WARN' | 'FAIL' | 'UNKNOWN';
  doctorFailChecks: string[];
  warnings: string[];
  manifest: IntegrationManifest | null;
  capabilities: IntegrationCapabilities | null;
  doctorReport: IntegrationDoctorReport | null;
};

const capabilitiesCache = new Map<string, Promise<IntegrationCapabilities | null>>();

const asUrl = (value: string | null | undefined): URL | null => {
  if (typeof value !== 'string' || !value.trim()) return null;
  try {
    return new URL(value.trim());
  } catch {
    return null;
  }
};

const trimTrailingSlash = (value: string): string => value.replace(/\/+$/, '');

const parseEndpointPath = (value: string | null | undefined): string | null => {
  const parsed = asUrl(value);
  if (!parsed) return null;
  return parsed.pathname || '/';
};

const resolveApiBase = (apiUrl: string): URL | null => {
  const parsed = asUrl(apiUrl);
  if (!parsed) return null;
  parsed.search = '';
  parsed.hash = '';
  if (/\/chatkit\/?$/i.test(parsed.pathname) || /\/chat\/?$/i.test(parsed.pathname)) {
    parsed.pathname = parsed.pathname.replace(/\/(chatkit|chat)\/?$/i, '/');
  }
  if (!parsed.pathname.endsWith('/')) {
    parsed.pathname = `${parsed.pathname}/`;
  }
  return parsed;
};

const resolveChatPath = (
  manifest: IntegrationManifest | null,
  capabilities: IntegrationCapabilities | null
): string => {
  const fromCapabilities = capabilities?.chat?.canonical_endpoint;
  if (typeof fromCapabilities === 'string' && fromCapabilities.trim()) {
    const normalized = fromCapabilities.trim();
    return normalized.startsWith('/') ? normalized : `/${normalized}`;
  }
  const fromManifest = parseEndpointPath(manifest?.chat_api_url);
  if (fromManifest) return fromManifest;
  return '/chat';
};

const buildCanonicalChatUrl = (
  initialApiUrl: string,
  manifest: IntegrationManifest | null,
  capabilities: IntegrationCapabilities | null,
  warnings: string[]
): { url: string; resolvedFromAlias: boolean } => {
  const initial = asUrl(initialApiUrl);
  if (!initial) {
    warnings.push('invalid_api_url');
    return { url: initialApiUrl, resolvedFromAlias: false };
  }

  const canonicalPath = resolveChatPath(manifest, capabilities);
  const aliasPath = capabilities?.chat?.deprecated_alias || '/chatkit';
  const aliasPathNormalized = aliasPath && aliasPath.startsWith('/') ? aliasPath : `/${aliasPath || 'chatkit'}`;

  const hostPolicy = manifest?.host_policy;
  const enforcePinned = hostPolicy?.mode === 'pinned' && hostPolicy?.enforcement === 'required';
  const canonicalBase = asUrl(hostPolicy?.canonical_base_url || manifest?.api_base_url || null);

  const target = new URL(initial.toString());
  if (enforcePinned && canonicalBase) {
    target.protocol = canonicalBase.protocol;
    target.username = canonicalBase.username;
    target.password = canonicalBase.password;
    target.hostname = canonicalBase.hostname;
    target.port = canonicalBase.port;
    warnings.push(`host_policy_enforced:${hostPolicy?.policy_id || 'pinned'}`);
  }
  target.pathname = canonicalPath;

  const initialPath = initial.pathname || '';
  const resolvedFromAlias = initialPath === aliasPathNormalized || initialPath.endsWith(`${aliasPathNormalized}/`);
  if (resolvedFromAlias) {
    warnings.push('legacy_chat_alias_rewritten');
  }

  if (hostPolicy?.allowed_domains?.length) {
    const allowed = new Set(hostPolicy.allowed_domains.map((item) => item.trim().toLowerCase()).filter(Boolean));
    if (allowed.size && !allowed.has(target.hostname.toLowerCase())) {
      warnings.push('host_policy_allowed_domain_mismatch');
    }
  }

  return { url: target.toString(), resolvedFromAlias };
};

const fetchJson = async <T>(url: string): Promise<T | null> => {
  try {
    const response = await fetch(url, {
      method: 'GET',
      headers: { Accept: 'application/json' }
    });
    if (!response.ok) return null;
    return (await response.json()) as T;
  } catch {
    return null;
  }
};

const fetchIntegrationCapabilities = async (url: string): Promise<IntegrationCapabilities | null> => {
  const key = trimTrailingSlash(url);
  const existing = capabilitiesCache.get(key);
  if (existing) return existing;
  const pending = fetchJson<IntegrationCapabilities>(key);
  capabilitiesCache.set(key, pending);
  return pending;
};

const doctorStatusFromReport = (report: IntegrationDoctorReport | null): 'PASS' | 'WARN' | 'FAIL' | 'UNKNOWN' => {
  if (!report) return 'UNKNOWN';
  const summaryStatus = report.summary?.status;
  if (summaryStatus === 'PASS' || summaryStatus === 'WARN' || summaryStatus === 'FAIL') {
    return summaryStatus;
  }
  const hasFailCheck = (report.checks || []).some((item) => item?.status === 'FAIL');
  if (hasFailCheck) return 'FAIL';
  return 'UNKNOWN';
};

const resolveDoctorFailChecks = (report: IntegrationDoctorReport | null): string[] => {
  if (!report) return [];
  return (report.checks || [])
    .filter((item) => item?.status === 'FAIL')
    .map((item) => item.id || item.code || item.message || 'unknown_fail');
};

const appendProjectScope = (url: string, projectId?: string): string => {
  if (!projectId || !projectId.trim()) return url;
  const parsed = asUrl(url);
  if (!parsed) return url;
  parsed.searchParams.set('project_id', projectId.trim());
  return parsed.toString();
};

export const bootstrapIntegration = async (params: {
  apiUrl: string;
  projectId?: string;
}): Promise<IntegrationBootstrapResult> => {
  const warnings: string[] = [];
  const apiBase = resolveApiBase(params.apiUrl);
  if (!apiBase) {
    return {
      resolvedApiUrl: params.apiUrl,
      resolvedFromAlias: false,
      integrationReady: true,
      doctorStatus: 'UNKNOWN',
      doctorFailChecks: [],
      warnings: ['invalid_api_url'],
      manifest: null,
      capabilities: null,
      doctorReport: null
    };
  }

  const kitUrl = new URL('agent-integration-kit.json', apiBase).toString();
  const kit = await fetchJson<AgentIntegrationKit>(kitUrl);
  const manifest = kit?.integration_manifest || null;

  if (!kit) {
    warnings.push('integration_manifest_unavailable');
  }

  const capabilitiesUrl =
    manifest?.integration_capabilities_url ||
    kit?.urls?.integration_capabilities ||
    new URL('integration-capabilities', apiBase).toString();
  const capabilities = await fetchIntegrationCapabilities(capabilitiesUrl);
  if (!capabilities) {
    warnings.push('integration_capabilities_unavailable');
  }

  const doctorUrlRaw = kit?.urls?.integration_test_json || new URL('agent-integration-test.json', apiBase).toString();
  const doctorUrl = appendProjectScope(doctorUrlRaw, params.projectId);
  const doctorReport = await fetchJson<IntegrationDoctorReport>(doctorUrl);
  if (!doctorReport) {
    warnings.push('integration_doctor_unavailable');
  }

  const { url: resolvedApiUrl, resolvedFromAlias } = buildCanonicalChatUrl(
    params.apiUrl,
    manifest,
    capabilities,
    warnings
  );

  const doctorStatus = doctorStatusFromReport(doctorReport);
  const doctorFailChecks = resolveDoctorFailChecks(doctorReport);
  const integrationReady = doctorStatus !== 'FAIL' && doctorFailChecks.length === 0;

  return {
    resolvedApiUrl,
    resolvedFromAlias,
    integrationReady,
    doctorStatus,
    doctorFailChecks,
    warnings,
    manifest,
    capabilities,
    doctorReport
  };
};

export const __testing = {
  resolveApiBase,
  resolveChatPath,
  buildCanonicalChatUrl,
  doctorStatusFromReport,
  resolveDoctorFailChecks,
  appendProjectScope,
  capabilitiesCache
};
