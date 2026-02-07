# WorkCore Local Domain via Docker (`workcore.build`)

This guide runs WorkCore as an isolated Docker stack with domain-based routing:
- `workcore.build` -> Builder UI
- `api.workcore.build` -> Orchestrator API
- `chatkit.workcore.build` -> ChatKit API

TLS is supported on local HTTPS (default host port `443`).

## 1) Prepare environment
```bash
cp .env.docker.example .env.docker
```

Adjust `.env.docker` if needed:
- ports/domain hostnames
- OpenAI settings
- ChatKit auth token
- CORS origins

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
- To avoid conflicts with other projects, set custom host ports via:
  - `WORKCORE_HTTP_PORT`
  - `WORKCORE_HTTPS_PORT`
- If `WORKCORE_API_AUTH_TOKEN` is set, API requests require `Authorization: Bearer <token>` (except health/spec/reference and inbound webhook endpoint).
