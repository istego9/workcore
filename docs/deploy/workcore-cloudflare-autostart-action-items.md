# WorkCore Cloudflare Routing + Autostart Action Items

## Task classification
- Type: `E` (external integration behavior change: Cloudflare Tunnel ingress + local startup automation)

## 1) Goal and scope
- Goal: eliminate public `502` on `api.runwcr.com` and make WorkCore + tunnel auto-start reliably on user login.
- Scope:
  - Cloudflare ingress reliability for `api.runwcr.com`.
  - Launchd-based autostart for WorkCore Docker profile and `cloudflared`.
  - Deployment docs update for setup/operations.

## 2) Spec files to update (exact paths)
- `docs/deploy/docker-workcore-build.md`
- `docs/deploy/deployment-e2e-cloudflare-plan.md`
- `docs/deploy/workcore-cloudflare-autostart-action-items.md` (this file)

## 3) Compatibility strategy
- Additive/non-breaking:
  - Existing manual startup flow remains valid.
  - New autostart scripts are opt-in.
  - Tunnel config improvements do not change API contract.

## 4) Implementation files
- `deploy/docker/Caddyfile.workcore`
- `docker-compose.workcore.yml`
- `.env.docker.example`
- `scripts/workcore_autostart_boot.sh` (new)
- `scripts/workcore_autostart_cloudflared.sh` (new)
- `scripts/workcore_autostart_install.sh` (new)
- `scripts/workcore_autostart_uninstall.sh` (new)
- `deploy/launchd/com.workcore.stack.plist` (new)
- `deploy/launchd/com.workcore.cloudflared.plist` (new)

## 5) Tests and validation
- Shell syntax checks for new scripts.
- Local launchd load/unload verification.
- Health checks:
  - local `http://127.0.0.1/health` with `Host: api.workcore.build`
  - public `https://api.runwcr.com/health`

## 6) Observability/security impacts
- launchd logs redirected to `~/Library/Logs/workcore/*.log`.
- No secrets embedded in plist files.
- Existing token/secret checks in `scripts/docker_up.sh` remain enforced.

## 7) Rollout/rollback notes
- Rollout:
  - install launch agents,
  - load services with `launchctl bootstrap`,
  - confirm public health endpoint.
- Rollback:
  - run uninstall script,
  - restore previous `~/.cloudflared/config.yml` backup.

## 8) Outstanding TODOs/questions
- TODO: If production requires builder/chatkit public hostnames on `*.runwcr.com`, add explicit DNS + ingress entries and align Caddy host routing domains accordingly.
