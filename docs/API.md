# Marketlift API Overview

Marketlift exposes one shared backend to the marketplace and platform-admin frontends.

## API split

- **GraphQL** is the primary application API for marketplace/admin reads and domain mutations.
- **REST** is used for browser/session authentication, upload transfer, health/readiness, and external webhooks.
- Business rules live in domain services. GraphQL and REST must not duplicate domain logic.

## Base routes

| Route | Purpose |
| --- | --- |
| `/graphql/` | Strawberry GraphQL endpoint |
| `/api/v1/health/` | Process liveness |
| `/api/v1/ready/` | Database/cache readiness |
| `/api/v1/auth/` | Session/authentication lifecycle |
| `/api/v1/uploads/` | Provider-neutral upload lifecycle |
| `/api/v1/webhooks/` | External payment callbacks |
| `/admin/` | Django administration |

## Authentication

Browser clients use Django sessions. Fetch a CSRF cookie first and send `X-CSRFToken` on unsafe REST/GraphQL requests.

See [AUTH.md](AUTH.md).

## GraphQL domains

The root schema only composes domain query/mutation classes. Domain API modules remain separated under each app's `graphql/` package.

Current domains include:

- accounts / profile / preferences
- sellers / seller settings / reputation
- categories and dynamic category fields
- listings / search / recently viewed / saved listings
- subscriptions / seller plans
- promotions
- Marketlift service payments
- seller verification
- moderation and reports
- notifications and audit events
- uploads/media references
- messaging
- reviews
- saved searches/search alerts
- support
- platform configuration
- admin dashboard/analytics

Export the exact current SDL after dependencies are installed:

```bash
uv run python manage.py export_graphql_schema
```

## REST authentication routes

```text
GET  /api/v1/auth/csrf/
GET  /api/v1/auth/session/
POST /api/v1/auth/register/
POST /api/v1/auth/verify-email/
POST /api/v1/auth/resend-verification/
POST /api/v1/auth/login/
POST /api/v1/auth/admin-login/
POST /api/v1/auth/logout/
POST /api/v1/auth/password-reset/request/
POST /api/v1/auth/password-reset/confirm/
```

## Upload routes

```text
POST   /api/v1/uploads/prepare/
PUT    /api/v1/uploads/<upload-id>/content/
POST   /api/v1/uploads/<upload-id>/complete/
GET    /api/v1/uploads/<upload-id>/content/
GET    /api/v1/uploads/<upload-id>/variants/<kind>/
DELETE /api/v1/uploads/<upload-id>/
```

See [UPLOADS.md](UPLOADS.md).

## Payment webhook

```text
POST /api/v1/webhooks/mercado-pago/
```

The payment-provider abstraction is separate from marketplace domain code. Marketlift V1 only processes Marketlift service payments (plans and listing promotions), not buyer-to-seller product payments.
