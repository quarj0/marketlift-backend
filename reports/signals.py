from django.db import transaction
from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import Report


@receiver(post_save, sender=Report)
def evaluate_listing_risk_after_report(sender, instance, created, **kwargs):
    if not created or not instance.listing_id:
        return

    listing_id = instance.listing_id

    def _evaluate():
        from moderation.risk import evaluate_listing_report_risk

        evaluate_listing_report_risk(listing_id=listing_id)

    transaction.on_commit(_evaluate, robust=True)
