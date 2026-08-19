from celery import shared_task
from .models import SavedSearch
from .services import process_saved_search


@shared_task
def process_saved_search_alerts():
    total = 0
    for item in SavedSearch.objects.filter(
        active=True, alerts_enabled=True
    ).select_related("user")[:1000]:
        total += process_saved_search(item)
    return total
