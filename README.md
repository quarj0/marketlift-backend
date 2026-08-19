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
uv run python manage.py makemigrations accounts sellers
uv run python manage.py migrate
uv run python manage.py createsuperuser
uv run python manage.py runserver
```

The default local services are:

- Django: `http://127.0.0.1:8000`
- GraphQL: `http://127.0.0.1:8000/graphql/`
- REST health: `http://127.0.0.1:8000/api/v1/health/`
- REST readiness: `http://127.0.0.1:8000/api/v1/ready/`
- PostgreSQL: `127.0.0.1:5432`
- Redis: `127.0.0.1:6379`

## Account model

Marketlift has one customer account type. Selling is an optional capability on the same account and is represented by the presence of a `SellerProfile`.

Do not model buyer and seller as separate login/account roles.

## API direction

GraphQL is the primary application API for the marketplace and admin frontends. REST is reserved for HTTP-native concerns such as uploads, webhooks, exports/downloads, health checks, and external integrations.
