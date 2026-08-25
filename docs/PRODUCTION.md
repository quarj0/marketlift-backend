# Production readiness and deployment

Marketlift is a multi-market classifieds platform. Country availability, the default market, payment provider selection, supported payment methods, identity-provider selection, and per-market plan/promotion pricing are **database/admin configuration**. Deployment secrets and infrastructure addresses remain environment configuration.

The administrator console exposes **Settings → Production readiness** and **Markets**. These are the operational source of truth before launch: a market cannot be newly enabled/defaulted through the admin API while its required launch configuration is blocked.

## What remains environment/secrets configuration

Keep these outside Git and configure them in Netcup/Coolify (or your future host/secret store):

- Django signing secret, production hosts and HTTPS/proxy settings.
- PostgreSQL/PostGIS connection.
- Redis for cache, Celery and Channels/WebSockets.
- SMTP credentials.
- Durable object-storage credentials when using R2/S3-compatible storage.
- Production geocoder URL/user-agent.
- Paystack and/or Mercado Pago credentials.
- External identity-verification adapter/plugin credentials.

Do **not** manage country enable/disable/default state through `.env` after the first migration. `MARKETLIFT_MARKET_CODE` is bootstrap-only.

## Frontend deployment variables

Marketplace:

```dotenv
NEXT_PUBLIC_SITE_URL=https://marketlift.com
NEXT_PUBLIC_MARKETLIFT_API_URL=https://api.marketlift.com
NEXT_PUBLIC_MARKETPLACE_URL=https://marketlift.com
NEXT_PUBLIC_ADMIN_URL=https://admin.marketlift.com
# Set only if public media is served from a separate CDN/storage origin.
NEXT_PUBLIC_MARKETLIFT_MEDIA_ORIGIN=https://assets.marketlift.com
```

Admin:

```dotenv
NEXT_PUBLIC_MARKETLIFT_API_URL=https://api.marketlift.com
NEXT_PUBLIC_MARKETPLACE_URL=https://marketlift.com
NEXT_PUBLIC_ADMIN_URL=https://admin.marketlift.com
NEXT_PUBLIC_MARKETLIFT_ENVIRONMENT=production
```

Payments and identity verification are no longer controlled by frontend build flags. The backend `/api/v1/market/` capabilities and admin-managed market configuration are authoritative, so turning a provider on after its backend setup does not require a special frontend feature build.

## Backend release commands

Run against the production deployment before routing traffic:

```bash
uv sync --frozen
uv run python manage.py check
uv run python manage.py check --deploy
uv run python manage.py makemigrations --check --dry-run
uv run python manage.py migrate --noinput
uv run python manage.py collectstatic --noinput
uv run python manage.py test
```

`rebuild_listing_search` is a maintenance/backfill command, **not** a normal startup command. Run it only when a release changes the search-document representation, after a bulk import, or during index recovery.

## Processes

Run separate long-lived processes for:

1. ASGI/Daphne web + WebSocket traffic.
2. Celery worker.
3. Celery beat.
4. PostgreSQL/PostGIS and Redis (managed or private services).

The proxy must forward WebSocket upgrade headers to the ASGI process.

## Market launch workflow

1. Open **Admin → Markets**.
2. Configure the country's provider and supported methods.
3. Add positive monthly/yearly prices for every paid seller plan offered in that market.
4. Add positive prices for every active promotion offered there.
5. Install/configure the external identity adapter if seller verification is required.
6. Open **Settings → Production readiness** and resolve all blockers.
7. Enable the market; then optionally make it the default.

A zero/missing list result is normal API behavior. Missing configuration required for a command (for example, purchasing a plan without a market price) remains a structured validation error rather than silently falling back across currencies.

## Payments

Marketlift payments are only for **seller subscriptions and listing promotions**. Buyer → seller transactions remain outside the platform.

### Paystack

Set at minimum:

```dotenv
MARKETLIFT_PAYMENTS_ENABLED=true
PAYSTACK_SECRET_KEY=...
PAYSTACK_CALLBACK_URL=https://marketlift.com/selling/payments
```

Configure Paystack webhooks to the backend Paystack webhook endpoint used by `payments/api` and test a real provider test-mode payment before enabling the market.

### Mercado Pago

Set:

```dotenv
MARKETLIFT_PAYMENTS_ENABLED=true
MERCADO_PAGO_ACCESS_TOKEN=...
MERCADO_PAGO_WEBHOOK_SECRET=...
```

Pix/boleto are supported by the current generalized checkout. Mercado Pago **card** should remain disabled in Admin → Markets until its client-side SDK/tokenization adapter is installed; the production-readiness check reports this as a blocker if card is enabled.

## Identity verification

The secure identity submission/storage/manual-review workflow is implemented. External country identity verification is deliberately adapter-driven. After installing and testing an adapter:

```dotenv
MARKETLIFT_IDENTITY_VERIFICATION_ENABLED=true
MARKETLIFT_IDENTITY_PROVIDER_READY=true
```

Then select that adapter key for the market in Admin → Markets. Never put provider secrets into the Market database or browser payload.

## Infrastructure and security

- Use PostgreSQL with PostGIS; keep it private where possible.
- Use shared Redis for cache/Celery/Channels in production.
- Use exact CORS, CSRF and WebSocket origins.
- Keep `DEBUG=false`, secure cookies on, GraphQL IDE/introspection disabled, admin MFA required, and HTTPS/HSTS correctly configured.
- Use four distinct durable storage buckets/areas for public, private, evidence and temporary data when using object storage.
- Use a contracted/self-hosted geocoder for production rather than relying on public Nominatim SLA.
- Configure logs, error monitoring, uptime checks, backup/restore and failed Celery-job alerts.
- Test database restore and retained-upload restore before launch.

The backend readiness endpoint and Admin readiness screen expose only status/hints, never secret values.
