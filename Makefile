.PHONY: infra-up infra-down infra-logs migrate migrations superuser dev worker beat test check

infra-up:
	docker compose up -d postgres redis

infra-down:
	docker compose down

infra-logs:
	docker compose logs -f postgres redis

migrations:
	uv run python manage.py makemigrations

migrate:
	uv run python manage.py migrate

superuser:
	uv run python manage.py createsuperuser

dev:
	uv run python manage.py runserver

worker:
	uv run celery -A marketlift worker -l info

beat:
	uv run celery -A marketlift beat -l info

test:
	uv run python manage.py test

check:
	uv run python manage.py check
