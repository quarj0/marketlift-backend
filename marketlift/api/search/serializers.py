from __future__ import annotations

from django.utils import timezone


def _promotion_codes(listing) -> set[str]:
    now = timezone.now()
    return {
        promotion.product.code
        for promotion in listing.promotions.all()
        if promotion.cancelled_at is None
        and promotion.starts_at <= now < promotion.ends_at
    }


def serialize_search_listing(listing) -> dict:
    """Serialize the compact public listing shape used by marketplace cards.

    Search intentionally returns a summary, not the full listing-detail payload.
    The first image is enough for grid/list cards and keeps result pages small.
    """
    codes = _promotion_codes(listing)
    primary = next((item for item in listing.media.all() if item.is_primary), None)
    if primary is None:
        primary = next(iter(listing.media.all()), None)

    seller = listing.seller
    seller_name = seller.display_name or seller.user.full_name or "Seller"
    image = primary.content_url if primary is not None else None

    return {
        "id": str(listing.id),
        "slug": listing.slug,
        "title": listing.title,
        "description": (listing.description or "")[:500],
        "price": float(listing.price) if listing.price is not None else None,
        "category": listing.category_slug,
        "categoryName": listing.category_name,
        "condition": listing.condition or None,
        "location": {
            "countryCode": listing.country_code or None,
            "state": listing.state,
            "stateCode": listing.state_code,
            "city": listing.city,
            "district": listing.district or None,
        },
        "images": [image] if image else [],
        "sellerId": str(seller.id),
        "seller": {
            "id": str(seller.id),
            "name": seller_name,
            "type": seller.seller_type,
            "verified": seller.verified,
        },
        "createdAt": listing.created_at.isoformat(),
        "publishedAt": (
            listing.published_at.isoformat() if listing.published_at else None
        ),
        "views": int(listing.views),
        "negotiable": bool(listing.negotiable),
        "featured": "featured" in codes,
        "topSearch": "top_search" in codes,
        "urgent": "urgent" in codes,
        "distanceKm": getattr(listing, "search_distance_km", None),
    }
