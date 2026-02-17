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
- optional Azure OpenAI settings (`AZURE_OPENAI_*`) for Agent executor and LLM router
- ChatKit auth token
- API auth token + inbound webhook secret
- CORS origins
- optional API alias host accepted by proxy: `PUBLIC_API_HOST_ALT`

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

## 7) Public API via Cloudflare (`api.runwcr.com`)
If you keep local host routing as `PUBLIC_API_HOST=api.workcore.build` but need external API on `api.runwcr.com`, use:

1. In `.env.docker` keep:
   - `PUBLIC_API_HOST=api.workcore.build`
   - `PUBLIC_API_HOST_ALT=api.runwcr.com`
2. In `~/.cloudflared/config.yml`, route `api.runwcr.com` to your local proxy port:
   - if `WORKCORE_HTTP_PORT=80`: `service: http://127.0.0.1:80`
   - if `WORKCORE_HTTP_PORT=8080`: `service: http://127.0.0.1:8080`
3. If you do not set `PUBLIC_API_HOST_ALT`, add host-header override:

```yaml
ingress:
  - hostname: api.runwcr.com
    service: http://127.0.0.1:80
    originRequest:
      httpHostHeader: api.workcore.build
  - service: http_status:404
```

Verify:

```bash
curl -sS https://api.runwcr.com/health
```

## 8) Autostart on macOS (`launchd`)
Install and load user LaunchAgents:

```bash
./scripts/workcore_autostart_install.sh
```

Before enabling autostart, run `./scripts/docker_up.sh` at least once so required `workcore-local-*` containers already exist.

What gets installed:
- `com.workcore.stack`: periodic ensure-up for existing `workcore-local-*` containers (every 5 minutes, plus RunAtLoad)
- `com.workcore.cloudflared`: persistent tunnel process with auto-restart

Runtime scripts are copied to `~/Library/Application Support/workcore/autostart` to avoid macOS background access issues for `~/Documents`.

Optional overrides:
- `WORKCORE_AUTOSTART_CONTAINERS` (space-separated docker container names)
- `WORKCORE_HTTP_PORT` (health probe port, default `80`)
- `WORKCORE_API_HOST_HEADER` (health probe host header, default `api.workcore.build`)

Inspect:

```bash
launchctl print gui/$(id -u)/com.workcore.stack | sed -n '1,40p'
launchctl print gui/$(id -u)/com.workcore.cloudflared | sed -n '1,40p'
```

Logs:
- `~/Library/Logs/workcore/stack.out.log`
- `~/Library/Logs/workcore/stack.err.log`
- `~/Library/Logs/workcore/cloudflared.out.log`
- `~/Library/Logs/workcore/cloudflared.err.log`

Uninstall:

```bash
./scripts/workcore_autostart_uninstall.sh
```

## Notes
- Host ports are controlled by:
  - `WORKCORE_HTTP_PORT` (default `8080`)
  - `WORKCORE_HTTPS_PORT` (default `8443`)
- `WORKCORE_API_AUTH_TOKEN` is required in the WorkCore runtime profile; API requests require `Authorization: Bearer <token>` (except health/spec/reference and inbound webhook endpoint).
- `WEBHOOK_DEFAULT_INBOUND_SECRET` is required for signed inbound webhooks.
- `CORS_ALLOW_ORIGINS` should be an explicit allowlist of real UI origins (no `*`).
- Temporary local bypass only: set `WORKCORE_ALLOW_INSECURE_DEV=1` to skip strict startup checks.
