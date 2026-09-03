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

`.github/workflows/cd.yml` is manual-only. To deploy, open **Actions → CD → Run workflow** and select `main`. The deploy job has an explicit `github.actor == 'JackyLN'` guard; GitHub also limits manual workflow dispatch to users with repository write access. Public visitors with read access cannot trigger it.

Create a GitHub environment named `production` and configure:

Repository/environment variable:

- `DEPLOYMENT_URL=https://knoveleng.demo.jackylenghia.com`

Environment secrets:

- `VPS_HOST` — `187.127.220.131`
- `VPS_USER` — the SSH deployment user
- `VPS_SSH_PRIVATE_KEY` — its private SSH key
- `VPS_KNOWN_HOSTS` — the pinned output of `ssh-keyscan -H 187.127.220.131`, verified against the server fingerprint

The server must have Docker Compose and `rsync`, and the deployment user must be able to write `/opt/stayflow` and run Docker. Provision `.env.production` and `.env.caddy` once on the server; CD explicitly preserves both and never transfers them through GitHub Actions.

For defense in depth, configure the `production` environment with `JackyLN` as a required reviewer. If your repository has other administrators, disable administrator bypass where GitHub offers that setting. Do not enable “prevent self-review” when you are the only permitted deployer, because that would prevent you from approving your own deployment.

Each deployment validates Compose, rebuilds the app image, recreates changed services, and waits for the application's internal health check. It then requires an unauthenticated public `/health` request to return `401`, confirming DNS, HTTPS, Caddy, and access protection without storing demo credentials in GitHub. A successful deployment is recorded in `/opt/stayflow/.deployed-sha`. The workflow uses a concurrency lock so deployments cannot overlap.
