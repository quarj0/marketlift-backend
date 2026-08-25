# Test database isolation

`python manage.py test` must never treat the runtime Neon database as a disposable Django test database.

## Default: local PostGIS

Even when the normal `DB_*` values point to Neon, test runs default to the local PostGIS service in `docker-compose.yml`:

```bash
docker compose up -d postgres redis
uv run python manage.py test
```

Default test target:

```env
MARKETLIFT_TEST_DATABASE_MODE=local
TEST_DB_HOST=127.0.0.1
TEST_DB_PORT=5433
TEST_DB_NAME=marketlift_test
TEST_DB_USER=marketlift
TEST_DB_PASSWORD=marketlift
```

The custom test runner keeps/reuses the test database by default, so interrupted runs do not cause the `test_neondb already exists` prompt. Django still flushes test data according to its normal test-case semantics and applies pending migrations when the preserved test database is reused.

## Optional: dedicated Neon test branch

Create a separate Neon branch/database, preferably with a **direct** endpoint, then set:

```env
MARKETLIFT_TEST_DATABASE_MODE=remote
TEST_DB_ENGINE=django.contrib.gis.db.backends.postgis
TEST_DB_HOST=ep-your-test-branch.neon.tech
TEST_DB_PORT=5432
TEST_DB_NAME=neondb
TEST_DB_USER=...
TEST_DB_PASSWORD=...
TEST_DB_SSLMODE=require
```

The runner reuses that dedicated database and does not derive/create/drop `test_neondb`.

A safety guard refuses remote test configuration that points to the same host/database as the primary runtime database unless `MARKETLIFT_ALLOW_PRIMARY_DATABASE_TESTS=true` is deliberately supplied. Do not enable that override for normal development.
