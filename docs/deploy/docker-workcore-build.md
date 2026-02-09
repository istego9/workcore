# WorkCore Local Domain via Docker (`workcore.build`)

This guide runs WorkCore as an isolated Docker stack with domain-based routing:
- `workcore.build` -> Builder UI
- `api.workcore.build` -> Orchestrator API
- `chatkit.workcore.build` -> ChatKit API

TLS is supported on local HTTPS (default host port `8443`).

For deployment readiness gates and temporary public exposure via Cloudflare Tunnel, see:
- `docs/deploy/deployment-e2e-cloudflare-plan.md`

## 1) Prepare environment
```bash
cp .env.docker.example .env.docker
```

Adjust `.env.docker` if needed:
- ports/domain hostnames
- OpenAI settings
- ChatKit auth token
- API auth token + inbound webhook secret
- CORS origins

Recommended dev defaults:
- `WORKCORE_HTTP_PORT=8080`
- `WORKCORE_HTTPS_PORT=8443`

## 2) Add local DNS mapping
Add to `/etc/hosts`:

```txt
127.0.0.1 workcore.build api.workcore.build chatkit.workcore.build
```

Or run helper:
```bash
./scripts/docker_hosts.sh
```

Single-command helper (hosts + mkcert trust):
```bash
./scripts/docker_trust.sh
```

## 3) Start stack
```bash
./scripts/docker_up.sh
```

`docker_up.sh` automatically generates local certs via `scripts/docker_certs.sh`:
- Preferred: `mkcert` (trusted locally)
- Fallback: self-signed `openssl` certificate
- Existing certificate is reused if still valid, matches configured domains, and matches private key.
- Regeneration happens only when cert/key are missing, expired/near-expiry, key mismatch, SAN mismatch, or `--force` is passed.

If HTTPS is still untrusted in your browser/CLI, run once:
```bash
mkcert -install
```
On macOS this may ask for an admin password to add the local CA into trust store.

Or directly:
```bash
docker compose --env-file .env.docker -f docker-compose.workcore.yml up -d --build
```

### 3.1) Coexist with HQ21 on the same machine
Default local profile already uses `8080/8443`. If needed, override with:

```bash
./scripts/docker_up_with_hq21.sh
```

If your HQ21 edge proxy routes `workcore.build` domains to WorkCore (`host.docker.internal:8080`), keep using:
- `https://workcore.build`
- `https://api.workcore.build`
- `https://chatkit.workcore.build`

Without edge routing, use explicit ports:
- `http://workcore.build:8080`
- `https://workcore.build:8443`

## 4) Verify
```bash
curl -sS https://api.workcore.build/health
curl -sS https://chatkit.workcore.build/health
```

Open in browser:
- `http://workcore.build`
- `https://workcore.build`
- `http://api.workcore.build/openapi.yaml`
- `https://api.workcore.build/openapi.yaml`
- `http://api.workcore.build/api-reference`
- `https://api.workcore.build/api-reference`

If your local CA is not trusted yet, test HTTPS with:
```bash
curl -ksS https://api.workcore.build/health
```

## 5) Stop stack
```bash
./scripts/docker_down.sh
```

## 6) Run E2E suite
From repo root:
```bash
./scripts/e2e_suite.sh
```

This runs:
- backend run-mode E2E
- ChatKit interrupt/resume E2E
- builder Playwright E2E

## Notes
- Host ports are controlled by:
  - `WORKCORE_HTTP_PORT` (default `8080`)
  - `WORKCORE_HTTPS_PORT` (default `8443`)
- `WORKCORE_API_AUTH_TOKEN` is required in the WorkCore runtime profile; API requests require `Authorization: Bearer <token>` (except health/spec/reference and inbound webhook endpoint).
- `WEBHOOK_DEFAULT_INBOUND_SECRET` is required for signed inbound webhooks.
- `CORS_ALLOW_ORIGINS` should be an explicit allowlist of real UI origins (no `*`).
- Temporary local bypass only: set `WORKCORE_ALLOW_INSECURE_DEV=1` to skip strict startup checks.
