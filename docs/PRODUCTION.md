# Marketlift production checklist

Marketlift is deliberately provider-neutral. Production can use any compatible PostgreSQL host, Redis-compatible cache/broker, and any storage adapter implementing the upload storage interface.

Before deploying:

1. Set `MARKETLIFT_ENV=production`, a strong `DJANGO_SECRET_KEY`, explicit `DJANGO_ALLOWED_HOSTS`, production CORS/CSRF origins, database/cache credentials, email delivery, payment provider credentials, and a durable upload storage backend.
2. Terminate HTTPS at a trusted proxy/load balancer and enable secure session/CSRF cookies. Set `MARKETLIFT_TRUST_PROXY_HEADERS=true` and `SECURE_PROXY_SSL_HEADER_ENABLED=true` only when requests can reach Django exclusively through a proxy you control.
3. Run `python manage.py check --deploy` and treat Marketlift `E...` checks as release blockers. Review warnings rather than blindly suppressing them.
4. Run `python manage.py migrate`, `python manage.py collectstatic --noinput`, and the full test suite before release.
5. Do not use Django `runserver` in production. Run an ASGI/WSGI production server behind HTTPS.
6. Back up PostgreSQL and retained user uploads. Test restoring those backups before launch.
7. Keep Redis/cache/broker and PostgreSQL inaccessible from the public internet unless the provider requires a protected public endpoint with TLS/authentication.
8. Configure logs/error monitoring, uptime checks for `/api/v1/health/` and `/api/v1/ready/`, and alerts for failed Celery jobs/payment reconciliation.
9. Start HSTS only after HTTPS and subdomains are confirmed. Increase `SECURE_HSTS_SECONDS` deliberately.
10. Disable mock payments. The production deploy check rejects `MARKETLIFT_PAYMENT_PROVIDER=mock` or auto-approved mock payments.
11. Configure durable object storage. For the built-in S3-compatible/R2 adapter, use distinct public, private, evidence and temp buckets; scope credentials to those buckets only; keep private/evidence/temp non-public; and add an object-lifecycle rule to the temp bucket.
12. Configure a production-appropriate geocoder/self-hosted endpoint before requiring resolved listing locations. The public Nominatim service is suitable only for low-volume development/testing under its usage policy.

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

Marketlift enables the generic S3-compatible adapter when `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, `R2_ENDPOINT_URL` (or `R2_ACCOUNT_ID`), and all four bucket names are present. Use `R2_PRIVATE_BUCKET`; `R2_MEDIA_BUCKET` exists only as compatibility for older environment files. A custom public asset domain is optional and can be added later through `R2_PUBLIC_BASE_URL`.

Run `python manage.py check --deploy` after setting the storage environment. Production checks reject partial R2 configuration, reused bucket names, an insecure object-storage endpoint, or a missing S3 client dependency.

## Provider changes

Changing PostgreSQL hosts should require environment changes only (`DB_*`). Changing media/object storage should require selecting/configuring a storage adapter only. Domain apps must not import a vendor SDK directly.

## Realtime / WebSockets

- Run the Django application with an ASGI server capable of WebSockets.
- Configure `CHANNEL_REDIS_URL` to a durable shared Redis-compatible service when running more than one application process/instance.
- Set `MARKETLIFT_WEBSOCKET_ALLOWED_ORIGINS` to the exact HTTPS marketplace/admin frontend origins.
- Ensure the reverse proxy/load balancer forwards WebSocket upgrade headers and permits long-lived connections.
- Keep GraphQL history/unread queries enabled as reconnect recovery; WebSocket delivery is not the durable source of truth.

See `docs/REALTIME.md`.
