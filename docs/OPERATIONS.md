# Operations and Background Jobs

## Provider-neutral deployment

Application code does not assume a specific PostgreSQL host or object-storage vendor. Database connection values are environment driven. Storage uses the `StorageBackend` interface.

## Periodic Celery jobs

The default beat schedule includes:

- expire/renew due listings
- expire due seller subscriptions
- notify sellers about ended promotions
- clean abandoned uploads
- process saved-search alerts
- deliver notification emails
- reconcile pending service payments

Image processing can also run asynchronously through Celery.

## Health

- `/api/v1/health/` proves the Django process is alive.
- `/api/v1/ready/` checks database and cache availability.

## Backups

Backups are a deployment concern. Whichever PostgreSQL provider is selected should have automated backups/PITR appropriate to the production plan. Uploaded media should have an intentional retention/versioning strategy where the chosen storage system supports it.

## Logging

Logs are written to stdout/stderr using Django logging so the deployment platform can collect them. Control verbosity with `DJANGO_LOG_LEVEL` and `DJANGO_REQUEST_LOG_LEVEL`.
