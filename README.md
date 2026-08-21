# Marketlift Backend

Shared Django backend for the Marketlift marketplace and platform-admin applications.

## Stack

- Django
- Strawberry GraphQL / strawberry-graphql-django
- Django REST Framework
- PostgreSQL-compatible database
- Redis-compatible cache/broker for the current local/Celery setup
- Celery

The application is deliberately provider-neutral for production database and object storage. Local Docker services are development infrastructure, not a requirement to use the same vendors in production.

## Start locally

```bash
cp .env.example .env
docker compose up -d postgres redis
uv sync
uv run python manage.py migrate
uv run python manage.py seed_marketplace_domain
uv run python manage.py createsuperuser
uv run python manage.py runserver
```

Default local endpoints:

- Django: `http://127.0.0.1:8000`
- GraphQL: `http://127.0.0.1:8000/graphql/`
- Health: `http://127.0.0.1:8000/api/v1/health/`
- Readiness: `http://127.0.0.1:8000/api/v1/ready/`
- PostgreSQL host port: `5433` (`5432` inside Docker)
- Redis: `6379`

## Account model

Marketlift has one customer account type. Selling is an optional capability represented by `SellerProfile`; buyer and seller are not separate login roles.

## Implemented domains

- account registration, email verification, login, password reset and preferences
- seller profile/settings, dormant plans/subscriptions, and reputation
- categories with versioned dynamic fields
- listings, search/filtering/pagination, media, saved and recently viewed listings
- saved searches and alerts
- dormant listing promotions and Marketlift service payments (**Upcoming**)
- dormant CPF/provider-backed seller identity verification (**Upcoming**)
- moderation, reports and immutable audit events
- notifications
- provider-neutral uploads with image validation/variants
- buyer/seller messaging, blocking and message reports
- seller reviews/replies
- support tickets/messages
- platform settings
- admin dashboard and analytics aggregates

## Seeded marketplace domain

```bash
uv run python manage.py seed_marketplace_domain
```

The seed is idempotent and mirrors the current frontend category/plan/promotion configuration.

## Documentation

- [API overview](docs/API.md)
- [Authentication](docs/AUTH.md)
- [GraphQL design](docs/GRAPHQL.md)
- [Uploads/media](docs/UPLOADS.md)
- [State transitions](docs/STATE_TRANSITIONS.md)
- [Security](docs/SECURITY.md)
- [Transactional email](docs/EMAIL.md)
- [Operations](docs/OPERATIONS.md)
- [Production release](docs/PRODUCTION.md)

Export the exact GraphQL SDL with:

```bash
uv run python manage.py export_graphql_schema
```
