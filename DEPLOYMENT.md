# Ubuntu VPS deployment

## Prerequisites

- Ubuntu VPS with DNS `A`/`AAAA` records pointing to it
- Docker Engine with the Compose plugin
- Firewall allowing SSH, TCP 80, TCP/UDP 443; port 8000 must remain closed
- A non-root deploy user in the `docker` group

## First deployment

```bash
git clone <repository-url> agentic-feedback
cd agentic-feedback
cp .env.production.example .env.production
cp .env.caddy.example .env.caddy
chmod 600 .env.production .env.caddy
docker run --rm caddy:2-alpine caddy hash-password --plaintext 'choose-a-long-password'
```

Edit `.env.production` on the server:

- Set `LLM_PROVIDER=openai` and `OPENAI_API_KEY` only when live OpenAI calls are wanted.
- Keep `ANALYSIS_RATE_LIMIT_REQUESTS` conservative; it is a global per-process budget guard.

Edit `.env.caddy` separately:

- Set `DOMAIN=feedback.example.com` for automatic Caddy HTTPS.
- Replace `DEMO_PASSWORD_HASH` with the generated hash.
- Set the demo username. This file never contains the OpenAI key.

Validate and start:

```bash
docker compose -f docker-compose.prod.yml config
docker compose -f docker-compose.prod.yml build
docker compose -f docker-compose.prod.yml up -d
docker compose -f docker-compose.prod.yml ps
curl -u reviewer:'your-password' https://feedback.example.com/health
```

The OpenAI key stays in the server-only `.env.production`, is supplied only to the app container, and is never sent to the browser or Caddy.

## Updating

Record the currently deployed Git commit or image tag before changing it:

```bash
git rev-parse HEAD
git pull --ff-only
docker compose -f docker-compose.prod.yml build
docker compose -f docker-compose.prod.yml up -d
```

If CI registry push is enabled, export `APP_IMAGE=ghcr.io/owner/repository:<commit-sha>`, run `docker compose pull`, then `up -d --no-build`. Authenticate the VPS to GHCR separately with a read-only package token. `APP_IMAGE` is a Compose selection variable, not an application secret.

## Rollback

Source-build rollback:

```bash
git checkout <previous-known-good-commit>
docker compose -f docker-compose.prod.yml build app
docker compose -f docker-compose.prod.yml up -d
```

Immutable-image rollback:

```bash
export APP_IMAGE=ghcr.io/owner/repository:<previous-sha>
docker compose -f docker-compose.prod.yml pull app
docker compose -f docker-compose.prod.yml up -d --no-build app
```

Caddy certificate state remains in named volumes and is unaffected by app rollback.

## Operations

```bash
docker compose -f docker-compose.prod.yml ps
docker compose -f docker-compose.prod.yml logs --tail=200 app
docker compose -f docker-compose.prod.yml logs --tail=200 caddy
docker compose -f docker-compose.prod.yml logs -f --since=10m
docker inspect --format '{{json .State.Health}}' agentic-feedback-app-1
docker compose -f docker-compose.prod.yml restart app
```

Use `docker compose down` without `-v`; deleting volumes removes Caddy certificate state. Back up `.env.production` and `.env.caddy` through an encrypted secret-management process, not source control.

## CI/CD

Pull requests and `main` validate dependencies, lint, types, tests, evaluation, and the production image. Setting repository variable `ENABLE_REGISTRY_PUSH=true` enables the optional immutable GHCR push on `main`.

After CI succeeds for a push to `main`, `.github/workflows/cd.yml` deploys that exact commit to `/opt/stayflow`. It may also be started manually from the Actions page. Create a GitHub environment named `production` and configure:

Repository/environment variable:

- `DEPLOYMENT_URL=https://knoveleng.demo.jackylenghia.com`

Environment secrets:

- `VPS_HOST` — `187.127.220.131`
- `VPS_USER` — the SSH deployment user
- `VPS_SSH_PRIVATE_KEY` — its private SSH key
- `VPS_KNOWN_HOSTS` — the pinned output of `ssh-keyscan -H 187.127.220.131`, verified against the server fingerprint
- `DEMO_USERNAME` and `DEMO_PASSWORD` — Caddy Basic Auth credentials used only for HTTPS smoke tests

The server must have Docker Compose and `rsync`, and the deployment user must be able to write `/opt/stayflow` and run Docker. Provision `.env.production` and `.env.caddy` once on the server; CD explicitly preserves both and never transfers them through GitHub Actions.

Each deployment validates Compose, rebuilds the app image, recreates changed services, waits for application health, checks public `/health` and `/docs` over HTTPS, and records the successful commit in `/opt/stayflow/.deployed-sha`. The workflow uses a concurrency lock so deployments cannot overlap. Optional environment protection rules can require approval before the `production` job starts.
