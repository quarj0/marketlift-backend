from __future__ import annotations

import os

from django.test.runner import DiscoverRunner


class MarketliftTestRunner(DiscoverRunner):
    """Reuse the test database by default.

    This removes destructive create/drop prompts after an interrupted local run
    and is required for dedicated Neon test branches, which should be treated as
    isolated environments rather than disposable SQL-created databases.
    Set MARKETLIFT_TEST_KEEPDB=false if you explicitly want Django to recreate a
    local test database.
    """

    def __init__(self, *args, keepdb: bool = False, **kwargs):
        configured = os.getenv("MARKETLIFT_TEST_KEEPDB", "true").strip().lower()
        if not keepdb and configured in {"1", "true", "yes", "on"}:
            keepdb = True
        super().__init__(*args, keepdb=keepdb, **kwargs)
