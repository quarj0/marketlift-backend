"""Run inside the Railway service with its actual environment; never prints credentials."""

import json
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.db.models import Count, Min, Q
from django.utils import timezone
from rest_framework.test import APIRequestFactory
from marketlift.api.views import readiness


class Command(BaseCommand):
    help = "Read-only database, migrations, Redis, channel layer and worker checks."

    def handle(self, *args, **options):
        db = settings.DATABASES["default"]
        self.stdout.write(
            json.dumps(
                {
                    "environment": settings.MARKETLIFT_ENV,
                    "databaseHost": db.get("HOST"),
                    "databaseName": db.get("NAME"),
                },
                default=str,
            )
        )
        executor = MigrationExecutor(connection)
        pending = [
            f"{migration.app_label}.{migration.name}"
            for migration, backwards in executor.migration_plan(
                executor.loader.graph.leaf_nodes()
            )
            if not backwards
        ]
        response = readiness(APIRequestFactory().get("/api/v1/ready/"))
        self.stdout.write(json.dumps({"pendingMigrations": pending, **response.data}))
        if pending or response.status_code != 200:
            raise CommandError(
                "Deployment checks failed. Review the reported checks and service logs."
            )
        from notifications.models import Notification, WebPushDelivery, WebPushSubscription
        from notifications.web_push import web_push_configured
        from uploads.models import UploadAsset

        notifications = Notification.objects.filter(
            email_sent_at__isnull=True
        ).aggregate(
            pending=Count("pk", filter=Q(delivery_attempts__lt=5)),
            exhausted=Count("pk", filter=Q(delivery_attempts__gte=5)),
            oldest=Min("created_at", filter=Q(delivery_attempts__lt=5)),
        )
        oldest = notifications.pop("oldest")
        notifications["oldestPendingSeconds"] = (
            max(0, int((timezone.now() - oldest).total_seconds())) if oldest else 0
        )
        uploads = UploadAsset.objects.filter(
            status__in=[UploadAsset.Status.READY, UploadAsset.Status.ATTACHED],
            processed_at__isnull=True,
        ).aggregate(
            pending=Count("pk", filter=Q(processing_error="")),
            failed=Count("pk", filter=~Q(processing_error="")),
        )
        push = {
            "configured": web_push_configured(),
            "activeSubscriptions": WebPushSubscription.objects.filter(
                disabled_at__isnull=True
            ).count(),
            "subscriptionsWithErrors": WebPushSubscription.objects.filter(
                disabled_at__isnull=True
            ).exclude(last_error="").count(),
            "pendingDeliveries": WebPushDelivery.objects.filter(
                sent_at__isnull=True,
                subscription__disabled_at__isnull=True,
            ).count(),
        }
        email = {
            "backend": settings.EMAIL_BACKEND,
            "configured": bool(settings.ANYMAIL.get("RESEND_API_KEY")),
            "from": settings.DEFAULT_FROM_EMAIL,
        }
        self.stdout.write(
            json.dumps(
                {
                    "notificationDelivery": notifications,
                    "notificationChannels": {
                        "email": email,
                        "webPush": push,
                    },
                    "uploadProcessing": uploads,
                }
            )
        )
