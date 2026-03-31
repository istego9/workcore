const DEFAULT_RETRY_ATTEMPTS = 2;

const trim = (value) => (typeof value === 'string' ? value.trim() : '');

const toStringList = (value) => {
  if (!Array.isArray(value)) return null;
  const next = value.map((item) => String(item)).map((item) => item.trim()).filter(Boolean);
  return next.length ? next : null;
};

const asUrl = (value) => {
  if (typeof value !== 'string' || !value.trim()) return null;
  try {
    return new URL(value.trim());
  } catch {
    return null;
  }
};

const trimTrailingSlash = (value) => value.replace(/\/+$/, '');

const parseEndpointPath = (value) => {
  const parsed = asUrl(value);
  if (!parsed) return null;
  return parsed.pathname || '/';
};

const capabilitiesCache = new Map();

export class ChatKitPageHttpError extends Error {
  constructor(params) {
    super(formatChatErrorMessage(params));
    this.name = 'ChatKitPageHttpError';
    this.status = params.status;
    this.endpoint = params.endpoint;
    this.correlationId = params.correlationId;
    this.traceId = params.traceId;
    this.typedError = params.typedError;
    this.retryAfterSeconds = params.retryAfterSeconds;
  }
}

export const createRequestId = (prefix, factory) => {
  const generated = trim(factory?.());
  if (generated) return generated;
  if (globalThis.crypto && typeof globalThis.crypto.randomUUID === 'function') {
    return `${prefix}_${globalThis.crypto.randomUUID()}`;
  }
  return `${prefix}_${Math.random().toString(36).slice(2, 12)}`;
};

export const normalizeChatApiUrl = (rawUrl) => {
  try {
    const parsed = new URL(rawUrl);
    const aliasPattern = /\/chatkit\/?$/i;
    if (!aliasPattern.test(parsed.pathname)) {
      return { url: parsed.toString(), rewritten: false };
    }
    parsed.pathname = parsed.pathname.replace(aliasPattern, '/chat');
    return { url: parsed.toString(), rewritten: true };
  } catch {
    const normalized = String(rawUrl || '').replace(/\/chatkit\/?$/i, '/chat');
    return { url: normalized, rewritten: normalized !== rawUrl };
  }
};

export const parseRetryAfterHeader = (value) => {
  if (!value) return null;
  const numeric = Number(value);
  if (Number.isFinite(numeric) && numeric >= 0) return numeric;
  const target = Date.parse(value);
  if (Number.isNaN(target)) return null;
  const deltaMs = target - Date.now();
  if (deltaMs <= 0) return 0;
  return Math.ceil(deltaMs / 1000);
};

const sleep = async (ms) => {
  if (ms <= 0) return;
  await new Promise((resolve) => {
    setTimeout(resolve, ms);
  });
};

const fetchJson = async (url) => {
  try {
    const response = await fetch(url, {
      method: 'GET',
      headers: { Accept: 'application/json' },
    });
    if (!response.ok) return null;
    return await response.json();
  } catch {
    return null;
  }
};

const fetchIntegrationCapabilities = async (url) => {
  const key = trimTrailingSlash(url);
  const existing = capabilitiesCache.get(key);
  if (existing) return existing;
  const pending = fetchJson(key);
  capabilitiesCache.set(key, pending);
  return pending;
};

const resolveApiBase = (apiUrl) => {
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

const resolveChatPath = (manifest, capabilities) => {
  const fromCapabilities = capabilities?.chat?.canonical_endpoint;
  if (typeof fromCapabilities === 'string' && fromCapabilities.trim()) {
    const normalized = fromCapabilities.trim();
    return normalized.startsWith('/') ? normalized : `/${normalized}`;
  }
  const fromManifest = parseEndpointPath(manifest?.chat_api_url);
  if (fromManifest) return fromManifest;
  return '/chat';
};

const buildCanonicalChatUrl = (initialApiUrl, manifest, capabilities, warnings) => {
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

const appendProjectScope = (url, projectId) => {
  if (!projectId || !projectId.trim()) return url;
  const parsed = asUrl(url);
  if (!parsed) return url;
  parsed.searchParams.set('project_id', projectId.trim());
  return parsed.toString();
};

export const bootstrapIntegration = async ({ apiUrl, projectId }) => {
  const warnings = [];
  const apiBase = resolveApiBase(apiUrl);
  if (!apiBase) {
    return {
      resolvedApiUrl: apiUrl,
      resolvedFromAlias: false,
      integrationReady: true,
      doctorStatus: 'UNKNOWN',
      doctorFailChecks: [],
      warnings: ['invalid_api_url'],
      capabilities: null,
      manifest: null,
      doctorReport: null,
    };
  }

  const kitUrl = new URL('agent-integration-kit.json', apiBase).toString();
  const kit = await fetchJson(kitUrl);
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
  const doctorUrl = appendProjectScope(doctorUrlRaw, projectId);
  const doctorReport = await fetchJson(doctorUrl);
  if (!doctorReport) {
    warnings.push('integration_doctor_unavailable');
  }

  const { url: resolvedApiUrl, resolvedFromAlias } = buildCanonicalChatUrl(apiUrl, manifest, capabilities, warnings);

  const summaryStatus = doctorReport?.summary?.status;
  const checks = Array.isArray(doctorReport?.checks) ? doctorReport.checks : [];
  const doctorFailChecks = checks
    .filter((item) => item?.status === 'FAIL')
    .map((item) => item?.id || item?.code || item?.message || 'doctor_fail');

  let doctorStatus = 'UNKNOWN';
  if (summaryStatus === 'PASS' || summaryStatus === 'WARN' || summaryStatus === 'FAIL') {
    doctorStatus = summaryStatus;
  } else if (doctorFailChecks.length) {
    doctorStatus = 'FAIL';
  }

  return {
    resolvedApiUrl,
    resolvedFromAlias,
    integrationReady: doctorStatus !== 'FAIL' && doctorFailChecks.length === 0,
    doctorStatus,
    doctorFailChecks,
    warnings,
    capabilities,
    manifest,
    doctorReport,
  };
};

const buildHeaders = ({ authToken, tenantId, projectId, correlationId, traceId, headers }) => {
  const nextHeaders = new Headers(headers || {});
  if (!nextHeaders.has('Content-Type')) {
    nextHeaders.set('Content-Type', 'application/json');
  }
  nextHeaders.set('X-Tenant-Id', trim(tenantId) || 'local');
  nextHeaders.set('X-Correlation-Id', correlationId);
  nextHeaders.set('X-Trace-Id', traceId);
  const normalizedProjectId = trim(projectId);
  if (normalizedProjectId) {
    nextHeaders.set('X-Project-Id', normalizedProjectId);
  }
  const normalizedToken = trim(authToken);
  if (normalizedToken) {
    nextHeaders.set('Authorization', `Bearer ${normalizedToken}`);
  }
  return nextHeaders;
};

const appendRequestMetadata = (body, { workflowId, workflowVersionId, projectId }) => {
  if (typeof body !== 'string') return body;
  try {
    const parsed = JSON.parse(body);
    if (!parsed || typeof parsed !== 'object' || typeof parsed.type !== 'string') {
      return body;
    }
    parsed.metadata = parsed.metadata || {};
    if (trim(workflowId)) parsed.metadata.workflow_id = trim(workflowId);
    if (trim(workflowVersionId)) parsed.metadata.workflow_version_id = trim(workflowVersionId);
    if (trim(projectId)) parsed.metadata.project_id = trim(projectId);
    parsed.metadata.client_capabilities = {
      widget_extensions: {
        RichChart: {
          spec_versions: ['1'],
        },
      },
    };
    return JSON.stringify(parsed);
  } catch {
    return body;
  }
};

const parseErrorEnvelope = async (response, fallbackCorrelationId, endpoint, traceId) => {
  let payload = null;
  try {
    payload = await response.clone().json();
  } catch {
    payload = null;
  }

  const nested = payload?.error && typeof payload.error === 'object' ? payload.error : {};
  const retryAfterFromBody =
    typeof nested?.retry_after_s === 'number' && Number.isFinite(nested.retry_after_s) ? nested.retry_after_s : null;
  const retryAfterFromHeader = parseRetryAfterHeader(response.headers.get('Retry-After'));
  const retryAfterSeconds = retryAfterFromBody ?? retryAfterFromHeader;

  const typedError = {
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
      typeof nested?.unsupported_feature === 'string' && nested.unsupported_feature.trim()
        ? nested.unsupported_feature.trim()
        : null,
    docs_ref: typeof nested?.docs_ref === 'string' && nested.docs_ref.trim() ? nested.docs_ref.trim() : null,
    correlation_id:
      (typeof nested?.correlation_id === 'string' && nested.correlation_id) ||
      (typeof payload?.correlation_id === 'string' && payload.correlation_id) ||
      response.headers.get('X-Correlation-Id') ||
      fallbackCorrelationId,
  };

  return {
    status: response.status,
    endpoint,
    correlationId: typedError.correlation_id || null,
    traceId,
    typedError,
    retryAfterSeconds,
  };
};

export const formatChatErrorMessage = (errorLike) => {
  const envelope = errorLike?.typedError || errorLike?.error || errorLike || {};
  const code = trim(envelope.code);
  const message = trim(envelope.message) || trim(errorLike?.message) || 'Request failed';
  const fragments = [];

  const badFields = toStringList(envelope.bad_fields);
  if (badFields?.length) {
    fragments.push(badFields.join(', '));
  }

  const unsupportedFeature =
    typeof envelope.unsupported_feature === 'string' && envelope.unsupported_feature.trim()
      ? envelope.unsupported_feature.trim()
      : '';
  if (unsupportedFeature) {
    fragments.push(`unsupported feature: ${unsupportedFeature}`);
  }

  const docsRef = trim(envelope.docs_ref);
  if (docsRef) {
    fragments.push(`docs: ${docsRef}`);
  }

  const suffix = fragments.length ? ` (${fragments.join('; ')})` : '';
  return code ? `[${code}] ${message}${suffix}` : `${message}${suffix}`;
};

const emitLegacyAliasAlert = (apiUrl, resolvedUrl, logger) => {
  if (globalThis.window && typeof globalThis.window.dispatchEvent === 'function') {
    globalThis.window.dispatchEvent(
      new CustomEvent('workcore.integration.legacy_chat_alias_used', {
        detail: {
          original_url: apiUrl,
          resolved_url: resolvedUrl,
          observed_at: new Date().toISOString(),
        },
      })
    );
  }
  logger?.warn?.('[chatkit.html] legacy /chatkit alias rewritten', {
    original_url: apiUrl,
    resolved_url: resolvedUrl,
  });
};

export const createChatkitFetch = ({
  apiUrl,
  authToken,
  workflowId,
  workflowVersionId,
  projectId,
  tenantId,
  requestIdFactory,
  logger = console,
}) => {
  return async (_input, init = {}) => {
    const normalized = normalizeChatApiUrl(apiUrl);
    if (normalized.rewritten) {
      emitLegacyAliasAlert(apiUrl, normalized.url, logger);
    }

    let lastError = null;
    for (let attempt = 1; attempt <= DEFAULT_RETRY_ATTEMPTS; attempt += 1) {
      const correlationId = createRequestId('corr', requestIdFactory);
      const traceId = createRequestId('trace', requestIdFactory);
      const headers = buildHeaders({
        authToken,
        tenantId,
        projectId,
        correlationId,
        traceId,
        headers: init.headers,
      });
      const body = appendRequestMetadata(init.body, { workflowId, workflowVersionId, projectId });

      logger?.info?.('[chatkit.html] WorkCore request', {
        endpoint: normalized.url,
        correlation_id: correlationId,
        trace_id: traceId,
        attempt,
      });

      let response;
      try {
        response = await fetch(normalized.url, { ...init, headers, body });
      } catch (error) {
        lastError = error;
        break;
      }

      if (response.ok) {
        return response;
      }

      const parsedError = await parseErrorEnvelope(response, correlationId, normalized.url, traceId);
      logger?.warn?.('[chatkit.html] WorkCore request failed', {
        endpoint: parsedError.endpoint,
        status: parsedError.status,
        correlation_id: parsedError.correlationId,
        trace_id: parsedError.traceId,
        error_code: parsedError.typedError.code,
        error_category: parsedError.typedError.category,
        retryable: parsedError.typedError.retryable,
        retry_after_s: parsedError.retryAfterSeconds,
      });

      const shouldRetry = parsedError.typedError.retryable === true && attempt < DEFAULT_RETRY_ATTEMPTS;
      if (!shouldRetry) {
        throw new ChatKitPageHttpError(parsedError);
      }

      const waitMs = Math.max(0, Math.floor((parsedError.retryAfterSeconds || 0) * 1000));
      await sleep(waitMs);
      lastError = new ChatKitPageHttpError(parsedError);
    }

    if (lastError instanceof Error) {
      throw lastError;
    }
    throw new Error('Network request failed');
  };
};

export const __testing = {
  appendRequestMetadata,
  buildCanonicalChatUrl,
  capabilitiesCache,
  parseErrorEnvelope,
  resolveApiBase,
  resolveChatPath,
};
