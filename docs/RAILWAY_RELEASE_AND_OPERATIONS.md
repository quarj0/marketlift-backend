# Railway release and operations

The previous checkout Neon URL is obsolete. Run the following inside the Railway backend service environment. No production migrations were run from the development checkout. Payments and identity-provider setup remain excluded.

## Release

1. Confirm the deployed revision and environment. `python manage.py deployment_diagnostics` prints the loaded database host/name, pending migration names and readiness results without credentials. When those checks pass it also reports pending/exhausted notification counts, oldest pending notification age and upload-processing backlog counts. Pending migrations make this command exit nonzero; inspect the output before proceeding.
2. In Railway: `python manage.py showmigrations --plan`, then `python manage.py migrate --plan`. Confirm the database matches the intended Neon branch and that a recovery point exists.
3. Run `python manage.py migrate --noinput` as the Railway pre-deploy command. Run migrations once per release, ahead of new web/worker processes. Never run them concurrently from replicas.
4. Run `python manage.py deployment_diagnostics` again. If search documents need rebuilding after an inventory import, use `python manage.py rebuild_listing_search --help` and its bounded batch options.
5. Deploy the backend before the marketplace/admin frontends: the new clients require `adminRecordPage`, support message paging, conversation paging, geographic search metadata and sitemap endpoints.
6. Check `/api/v1/ready/`, an anonymous search, support creation/reply and authenticated admin pagination. Save the revision and check output with the release record.

## Service topology and jobs

Use separate Railway services from the same backend revision and database/Redis environment:

- Web: `daphne -b 0.0.0.0 -p ${PORT:-8000} marketlift.asgi:application`.
- Worker: `celery -A marketlift worker --loglevel=info --concurrency=2`. Tune concurrency only after measuring memory/DB connections and job latency.
- One beat instance: `celery -A marketlift beat --loglevel=info`. Do not scale beat horizontally.

The scheduled heartbeat runs every 60 seconds and expires after 180 seconds. Once the worker and beat are running, set `MARKETLIFT_REQUIRE_WORKER_HEARTBEAT=true` on the web service. Readiness then fails when jobs stop making progress. Enable asynchronous upload processing only after verifying the worker consumes the configured queue and a test image reaches its final variant state; see `MARKETLIFT_PROCESS_UPLOADS_ASYNC` in settings.

Notification delivery locks each row while sending, and other workers skip it. Email calls have a 15-second timeout and existing five-attempt limits. A process crash after provider acceptance but before the database commit can still cause a retry duplicate: this is at-least-once delivery. Provider idempotency would be required to remove that remaining ambiguity.

## Realtime diagnosis

`REDIS_URL` configures cache and Celery databases; `CHANNEL_REDIS_URL` can configure a dedicated channel endpoint. Ensure the Redis service permits the selected databases and is reachable from every web/worker replica. Do not expose Redis publicly just to bypass Railway networking.

The readiness probe tests an actual channel send/receive with a deadline; failures log their exception type without connection credentials. Check `readiness check=realtime` in the web logs, the Redis service status, channel-prefix consistency, websocket allowed origins, and the public proxy websocket upgrade path. A passing Redis cache check alone does not prove the channel layer works. Browser messaging refreshes every 30 seconds while disconnected and reconciles messages, conversations and notifications after reconnecting.

## Monitoring and capacity

Alert on: readiness failure for 3 consecutive probes, worker heartbeat missing, HTTP 5xx above 1% for 5 minutes, rising request p95, exhausted notification retries, upload-processing failures, Redis memory/evictions, and database connection saturation. These are initial alert thresholds to tune with traffic, not measured service-level guarantees.

HTTP logs include request ID, route pattern, response status and elapsed milliseconds. Queries, credentials and request bodies are not logged by this middleware. Browser web vitals are sampled at 10% on production pages and record only metric name, normalized route and value. Treat client metrics as untrusted diagnostics. Restrict operator log access and define log retention in Railway.

Run `python scripts/measure_capacity.py --base-url http://127.0.0.1:8000 --requests 100 --concurrency 4 --output /tmp/capacity.json` against an isolated seeded environment. Repeat with realistic inventory at increasing concurrency, recording p95/error rates, DB query plans, DB connection usage, CPU, memory and worker backlog. Remote targets require `--allow-remote` and an operator-selected test window. The script reports throttling separately by HTTP status; a rate-limited run is not a successful capacity result.

Keep web connection use below the Neon/Railway connection budget after reserving headroom for workers and migrations. Use the provider's appropriate pooled endpoint for web traffic and a migration-compatible endpoint for schema changes. Confirm session/transaction pooling support for the installed Django/psycopg configuration. Cache public data at the edge; do not cache authenticated responses or exact-coordinate searches. Keep proxy-header trust disabled unless the trusted ingress overwrites forwarded addresses and direct origin access is blocked.

## Recovery drill

Verify that the actual Neon project/branch has a suitable recovery window or scheduled logical backups, and that retained R2 objects cover listings and private attachments. Credentials and dumps belong in protected storage, never Git or build artifacts.

Restore a backup to an isolated database branch, point an isolated Railway service at it, disable outgoing email/tasks, and run migration diagnostics, representative record counts, support/message ownership checks, search and upload retrieval. Record restoration duration, backup age, object availability and who validated the restored service. Test the rollback procedure against that branch before using it in an incident.

Production backup configuration, alert creation, sustained load measurements, worker rollout and a completed restore drill remain operator deployment tasks; repository checks do not establish these outcomes.
