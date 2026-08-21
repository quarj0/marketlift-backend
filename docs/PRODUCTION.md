# Production release

The initial production surface is the marketplace, account/authentication,
selling/listings, search/location, messaging, saved items, reviews, reports,
support, moderation, notifications and the administrator console.

Payments, paid subscriptions, listing promotions and CPF/provider-backed seller
verification are intentionally dormant. Keep these values aligned across all
three deployments:

```dotenv
MARKETLIFT_PAYMENTS_ENABLED=false
MARKETLIFT_CPF_VERIFICATION_ENABLED=false
NEXT_PUBLIC_MARKETLIFT_PAYMENTS_ENABLED=false
NEXT_PUBLIC_MARKETLIFT_CPF_VERIFICATION_ENABLED=false
```

The backend flags are authoritative: payment creation, provider refresh/webhook
processing, reconciliation and CPF verification mutations reject requests while
disabled. Frontend flags remove those workflows and show **Upcoming** states.

## Deployment surfaces

- Marketplace: `https://marketlift.com.br`
- Admin: `https://admin.marketlift.com.br`
- API and WebSocket origin: `https://api.marketlift.com.br`

Start with `.env.production.example`. Replace every `replace-me` value in the
deployment secret store; never commit the resulting environment.

## Required release gates

1. Provision PostgreSQL 17 with PostGIS, a shared Redis-compatible service,
   four distinct durable object-storage buckets, and a transactional SMTP
   provider with SPF, DKIM and DMARC.
2. Apply migrations and collect static assets before routing traffic:

   ```bash
   uv run python manage.py migrate --noinput
   uv run python manage.py collectstatic --noinput
   uv run python manage.py check --deploy
   ```

3. Run the ASGI web process with `daphne -b 0.0.0.0 -p "$PORT"
   marketlift.asgi:application`; run separate Celery worker and beat processes.
4. Configure health checks: `/api/v1/health/` for liveness and
   `/api/v1/ready/` for readiness. Readiness must be healthy before traffic.
5. Deploy marketplace and admin production builds with their respective
   `.env.production.example` values.
6. Verify registration, email verification, password reset, login/logout,
   listing publication and image upload, search, messaging/WebSocket fallback,
   report/support workflows, admin MFA, backups/restore, alerting and rollback
   in the production environment.

Only enable a dormant provider capability after its frontend and backend flags,
webhooks, secrets, reconciliation/operations, security review and provider
certification have passed together.

## Infrastructure and security checklist

Marketlift is provider-neutral. Production can use any compatible PostgreSQL
host, Redis-compatible cache/broker, and storage adapter implementing the upload
storage interface.

1. Set `MARKETLIFT_ENV=production`, a strong `DJANGO_SECRET_KEY`, explicit
   `DJANGO_ALLOWED_HOSTS`, exact production CORS/CSRF origins and all provider
   credentials.
2. Terminate HTTPS at a trusted proxy/load balancer. Enable proxy-header trust
   only when requests can reach Django exclusively through a proxy you control.
3. Treat every Marketlift `E...` deploy check as a release blocker and review
   all framework warnings rather than suppressing them.
4. Back up PostgreSQL and retained user uploads, then test restoring both.
5. Keep Redis and PostgreSQL off the public internet unless a provider requires
   a protected TLS/authenticated endpoint.
6. Configure logs, error monitoring, uptime checks and failed Celery-job alerts.
7. Enable HSTS/preload only after HTTPS works across the root domain and every
   affected subdomain.
8. Use distinct public, private, evidence and temporary storage buckets; keep
   private/evidence/temp non-public and add a lifecycle rule to temporary data.
9. Use a production-appropriate geocoder or self-hosted endpoint. The public
   Nominatim endpoint is not the production SLA.

## Release commands

```bash
uv run python manage.py check
uv run python manage.py check --deploy
uv run python manage.py migrate --check
uv run python manage.py makemigrations --check --dry-run
uv run python manage.py test
uv run python manage.py collectstatic --noinput
```

## R2 / S3-compatible object storage

The generic S3-compatible adapter is enabled when its access key, secret,
endpoint (or account ID), and all four bucket names are present. Use
`R2_PRIVATE_BUCKET`; `R2_MEDIA_BUCKET` is only a compatibility alias. A custom
public asset domain can be configured through `R2_PUBLIC_BASE_URL`.

Production checks reject partial R2 configuration, reused bucket names and an
insecure object-storage endpoint.

## Provider changes

Changing PostgreSQL hosts should require `DB_*` environment changes only.
Changing media/object storage should require selecting and configuring a storage
adapter only. Domain applications must not import a vendor SDK directly.

## Realtime / WebSockets

- Run Django with an ASGI server capable of WebSockets.
- Configure `CHANNEL_REDIS_URL` to a durable shared service for multi-instance
  deployments.
- Set `MARKETLIFT_WEBSOCKET_ALLOWED_ORIGINS` to the exact HTTPS marketplace and
  admin origins.
- Forward WebSocket upgrade headers and permit long-lived connections.
- Keep GraphQL history/unread queries as reconnect recovery; WebSocket delivery
  is not the durable source of truth.

See `docs/REALTIME.md`.
