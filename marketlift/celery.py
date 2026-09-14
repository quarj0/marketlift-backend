import os

from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "marketlift.settings")

app = Celery("marketlift")
app.config_from_object("django.conf:settings", namespace="CELERY")

# Register the commerce release task on the Celery app itself so a standalone
# beat process always receives it, even before the commerce package is imported
# by GraphQL or webhook code.
app.conf.beat_schedule = {
    **(app.conf.beat_schedule or {}),
    "release-due-commerce-settlements": {
        "task": "payments.tasks.release_due_commerce_settlements",
        "schedule": 300.0,
    },
}

app.autodiscover_tasks()
