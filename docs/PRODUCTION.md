# Production readiness and deployment

For the GitHub Actions deployment path to a Contabo VPS, including initial
server setup, secrets, TLS and rollback behavior, see
[Contabo continuous deployment](CONTABO_DEPLOYMENT.md).

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
- Stripe Connect credentials for buyer/seller marketplace commerce.
- Paystack and/or Mercado Pago credentials if retained for platform service payments.
- External identity-verification adapter/plugin credentials.

Do **not** manage country enable/disable/default state through `.env` after the first migration. `MARKETLIFT_MARKET_CODE` is bootstrap-only.

## Frontend deployment variables

Marketplace:

```dotenv
NEXT_PUBLIC_SITE_URL=https://marketlift.com
NEXT_PUBLIC_MARKETLIFT_API_URL=https://api.marketlift.com
NEXT_PUBLIC_MARKETPLACE_URL=https://marketlift.com
NEXT_PUBLIC_ADMIN_URL=https://dash.marketlift.com.br
# Set only if public media is served from a separate CDN/storage origin.
NEXT_PUBLIC_MARKETLIFT_MEDIA_ORIGIN=https://assets.marketlift.com
```

Admin:

```dotenv
NEXT_PUBLIC_MARKETLIFT_API_URL=https://api.marketlift.com
NEXT_PUBLIC_MARKETPLACE_URL=https://marketlift.com
NEXT_PUBLIC_ADMIN_URL=https://dash.marketlift.com.br
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

### Buyer → seller marketplace commerce: Stripe Connect

Buyer checkout and seller settlement use Stripe Connect. Marketlift creates the buyer
charge on the **platform account** and keeps the seller portion on the platform until
delivery confirmation plus the buyer-protection window. When the settlement becomes
available, Marketlift creates a separate Stripe Transfer for the seller proceeds. This
is intentionally **Separate Charges and Transfers**, not a Destination Charge: a
Destination Charge would transfer the seller share immediately and would weaken the
existing Marketlift protected-delivery flow. Do not describe Marketlift as a legal
escrow service.

Marketlift uses the official Stripe Python SDK and one `StripeClient` for all Stripe
requests. The SDK pins its Stripe API version automatically; do not configure a
`Stripe-Version` override.

Set at minimum:

```dotenv
MARKETLIFT_COMMERCE_PROVIDER=stripe
STRIPE_SECRET_KEY=...
STRIPE_WEBHOOK_SECRET=...
STRIPE_CONNECT_WEBHOOK_SECRET=...
MARKETLIFT_COMMERCE_FEE_BPS=500
MARKETLIFT_BUYER_PROTECTION_HOURS=48
```

Configure **two** Stripe event destinations:

1. Snapshot payment events → `https://api.marketlift.com.br/api/v1/webhooks/stripe/`
   for Checkout Session, PaymentIntent, charge/refund/dispute and transfer events used
   by `commerce/stripe_webhooks.py`.
2. Connected-account **Thin** events →
   `https://api.marketlift.com.br/api/v1/webhooks/stripe/connect/`.
   Select **Connected accounts**, advanced options → **Thin**, then subscribe to:
   - `v2.core.account[requirements].updated`
   - `v2.core.account[configuration.recipient].capability_status_updated`

Each event destination has its own signing secret. Keep both secrets backend-only.

Seller onboarding uses Accounts v2 with the `recipient` configuration and Stripe
Account Links. The seller-to-Stripe account ID mapping is stored in
`SellerPaymentAccount`, but the seller payments page refreshes the live
`configuration.recipient.capabilities.stripe_balance.stripe_transfers` and
`requirements` state directly from Stripe. Stripe collects CPF/CNPJ, identity and
banking requirements in its hosted flow.

A seller is commerce-ready when the Stripe transfer capability is active and there is
no currently-due or past-due onboarding requirement. That successful Stripe KYC can
satisfy Marketlift verification for commerce-enabled sellers. Classified-only sellers
who never enable online checkout can continue through Marketlift's independent seller
verification workflow.

Buyer card/Pix details are collected by Stripe-hosted Checkout; the marketplace
frontend does not need a Stripe publishable or secret key for the current hosted flow.
Pix must also be enabled for the Marketlift Stripe account before it is shown in
production.

Marketlift listings remain the marketplace product catalog and source of truth. We do
not mirror every listing into Stripe Products because that would create a second
catalog and synchronization burden. Checkout uses the selected Marketlift listing's
current server-side price to build Stripe Checkout line items.

### Platform service payments

Seller subscriptions and listing promotions remain on the generalized Marketlift service-payment provider layer and are separate from buyer → seller Stripe commerce.

#### Paystack

Set at minimum:

```dotenv
MARKETLIFT_PAYMENTS_ENABLED=true
PAYSTACK_SECRET_KEY=...
PAYSTACK_CALLBACK_URL=https://marketlift.com/selling/payments
```

Configure Paystack webhooks to the backend Paystack webhook endpoint used by `payments/api` and test a real provider test-mode payment before enabling the market.

#### Mercado Pago

Set:

```dotenv
MARKETLIFT_PAYMENTS_ENABLED=true
MERCADO_PAGO_ACCESS_TOKEN=...
MERCADO_PAGO_WEBHOOK_SECRET=...
```

Pix/boleto are supported by the generalized service-payment checkout. Mercado Pago card should remain disabled in Admin → Markets until its client-side SDK/tokenization adapter is installed.

## Identity verification

The secure identity submission/storage/manual-review workflow remains available for sellers who do not use Stripe Connect. External country identity verification is adapter-driven. For a market that requires that separate provider, install and test the adapter before enabling it:

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
