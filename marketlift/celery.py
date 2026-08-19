import os

from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "marketlift.settings")

app = Celery("marketlift")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()
