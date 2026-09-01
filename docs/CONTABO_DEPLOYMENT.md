# Contabo continuous deployment

Marketlift deploys to Contabo only after the `CI` workflow succeeds for a push to `master`. The CD workflow builds the verified commit into an immutable GHCR image, transfers the versioned deployment manifests over SSH, and runs the release on the server. Application secrets never pass through the workflow or repository.

## 1. Prepare the server

Provision a current Ubuntu LTS VPS and install:

- Docker Engine with the Compose plugin
- Nginx
- Certbot with the Nginx plugin
- `flock` (provided by `util-linux` on Ubuntu)

Create a non-root deployment user that can run Docker, and create the deployment directory:

```bash
sudo install -d -o deploy -g deploy -m 750 /opt/marketlift
```

If the GHCR package is private, authenticate once as that deployment user using a classic GitHub PAT with `read:packages`:

```bash
printf '%s' "$GHCR_READ_TOKEN" | docker login ghcr.io -u YOUR_GITHUB_USER --password-stdin
```

Prefer making the package public when the source repository is public. Do not save a GitHub token in `.env.production`.

## 2. Configure production secrets on Contabo

Copy `.env.production.example` to `/opt/marketlift/.env.production`, restrict it to the deployment user, and replace every placeholder:

```bash
install -m 600 .env.production.example /opt/marketlift/.env.production
```

For the bundled private PostGIS and Redis services, use these connection coordinates:

```dotenv
DB_HOST=postgres
DB_PORT=5432
DB_SSLMODE=
REDIS_PASSWORD=replace-with-a-long-random-value
REDIS_URL=redis://:replace-with-the-same-value@redis:6379/0
CELERY_BROKER_URL=redis://:replace-with-the-same-value@redis:6379/1
CELERY_RESULT_BACKEND=redis://:replace-with-the-same-value@redis:6379/2
CHANNEL_REDIS_URL=redis://:replace-with-the-same-value@redis:6379/3
MARKETLIFT_APP_PORT=8000
CELERY_WORKER_CONCURRENCY=2
```

Keep port 8000 bound to loopback. Do not expose Postgres or Redis through the VPS firewall. Size Celery concurrency for the VPS memory available.

## 3. Configure Nginx and TLS

Copy `deploy/nginx-marketlift.conf.example` to `/etc/nginx/sites-available/marketlift`, adjust the API hostname, enable it, and issue a certificate:

```bash
sudo ln -s /etc/nginx/sites-available/marketlift /etc/nginx/sites-enabled/marketlift
sudo nginx -t
sudo systemctl reload nginx
sudo certbot --nginx -d api.marketlift.com.br
```

The proxy configuration forwards WebSocket upgrade headers for `/ws/realtime/` and the standard forwarded headers Django uses for HTTPS enforcement.

## 4. Configure GitHub

Create a protected GitHub Environment named `production`, then add these environment secrets:

| Secret | Value |
| --- | --- |
| `CONTABO_HOST` | VPS IP address or verified hostname |
| `CONTABO_PORT` | SSH port, normally `22` |
| `CONTABO_USER` | Non-root deployment user |
| `CONTABO_SSH_PRIVATE_KEY` | Dedicated private deployment key |
| `CONTABO_KNOWN_HOSTS` | Verified `known_hosts` line for the VPS |
| `CONTABO_DEPLOY_PATH` | `/opt/marketlift` |

Obtain the host-key line from a trusted machine and compare its fingerprint with the Contabo console before saving it. The workflow deliberately does not run `ssh-keyscan`, because accepting a key during deployment would remove host identity verification.

Give Actions read/write package permission under **Settings → Actions → General → Workflow permissions**. Add required reviewers to the `production` environment if deployments need manual approval after CI.

## 5. First and subsequent releases

Before the first release, confirm DNS resolves to the VPS and `/opt/marketlift/.env.production` exists. Merge to `master`; successful CI automatically starts `CD - Contabo`.

Each release:

1. pulls the immutable commit image;
2. runs Django production checks;
3. applies migrations;
4. collects static assets;
5. rolls web, worker and beat;
6. verifies container health and the full readiness endpoint.

If application startup or readiness fails, the script restores the previous application image. Database migrations are not automatically reversed; every production migration must therefore remain compatible with the previous application version during the deployment window.

## Operations

Inspect the release:

```bash
cd /opt/marketlift
docker compose --env-file .env.production -f compose.contabo.yml ps
docker compose --env-file .env.production -f compose.contabo.yml logs --tail=200 web worker beat
```

Back up the `marketlift_postgres_data` volume and test restores regularly. Also back up durable object storage independently. A Docker volume is persistence, not a backup.

