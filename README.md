# Marketlift Backend

Django backend shared by the Marketlift marketplace and platform admin.

## Stack

- Django
- Strawberry GraphQL / strawberry-graphql-django
- Django REST Framework
- PostgreSQL
- Redis
- Celery

## Local infrastructure

PostgreSQL and Redis run in Docker while Django runs from the local `uv` environment.

```bash
cp .env.example .env
make infra-up
uv sync
uv run python manage.py migrate
uv run python manage.py seed_marketplace_domain
uv run python manage.py createsuperuser
uv run python manage.py runserver
```

The default local services are:

- Django: `http://127.0.0.1:8000`
- GraphQL: `http://127.0.0.1:8000/graphql/`
- REST health: `http://127.0.0.1:8000/api/v1/health/`
- REST readiness: `http://127.0.0.1:8000/api/v1/ready/`
- PostgreSQL host port: `127.0.0.1:5433` (`5432` inside Docker)
- Redis: `127.0.0.1:6379`

## Account model

Marketlift has one customer account type. Selling is an optional capability on the same account and is represented by the presence of a `SellerProfile`.

Do not model buyer and seller as separate login/account roles.

## Marketplace domain

The current backend domain includes:

- hierarchical categories with versioned dynamic field definitions
- category-specific pricing and condition requirements
- listings with draft/published/paused/sold/expired/under-review/rejected/removed states
- listing media and typed category attributes
- saved listings
- seller plans and subscriptions
- promotion products and listing promotion activations

The seed command mirrors the current marketplace frontend domain:

```bash
uv run python manage.py seed_marketplace_domain
```

It is idempotent and currently seeds 13 categories, 99 category fields, 4 seller plans, and 4 promotion products.

## API direction

GraphQL is the primary application API for the marketplace and admin frontends. REST is reserved for HTTP-native concerns such as uploads, webhooks, exports/downloads, health checks, and external integrations.

Public GraphQL reads include categories, listings, featured listings, seller plans, and promotion products. Authenticated seller mutations support activating selling, creating/updating/publishing/pausing/marking listings sold, and saved listings. Staff-only category operations include activation/deactivation and real deletion.
