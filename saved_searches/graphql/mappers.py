from .types import SavedSearchType


def saved_search_to_type(x):
    return SavedSearchType(
        id=str(x.id),
        name=x.name,
        criteria=x.criteria,
        alerts_enabled=x.alerts_enabled,
        active=x.active,
        created_at=x.created_at,
        last_checked_at=x.last_checked_at,
        last_notified_at=x.last_notified_at,
    )
