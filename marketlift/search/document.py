from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from django.contrib.postgres.search import SearchVector
from django.db.models import Value
from django.utils import timezone

from .normalization import attribute_unit_tokens, normalize_text, tokenize


@dataclass(frozen=True)
class BuiltSearchDocument:
    text: str
    tokens: list[str]


def _append(parts: list[str], tokens: list[str], value: object) -> None:
    if value in (None, ""):
        return
    normalized = normalize_text(str(value))
    if normalized:
        parts.append(normalized)
        for token in tokenize(str(value)):
            if token and token not in tokens:
                tokens.append(token)


def build_listing_search_document(
    listing, attributes: Iterable | None = None
) -> BuiltSearchDocument:
    parts: list[str] = []
    tokens: list[str] = []

    for value in (
        listing.title,
        (listing.description or "")[:4000],
        listing.category_name,
        listing.category_slug,
        listing.country_code,
        listing.state,
        listing.state_code,
        listing.city,
        listing.district,
        listing.condition,
    ):
        _append(parts, tokens, value)

    attrs = (
        attributes
        if attributes is not None
        else listing.attribute_values.select_related("field").all()
    )
    for attribute in attrs:
        _append(parts, tokens, attribute.key.replace("_", " "))
        _append(parts, tokens, attribute.label_snapshot)
        value = attribute.value
        _append(parts, tokens, value)
        field = getattr(attribute, "field", None)
        unit = getattr(field, "unit", "") if field is not None else ""
        for compact in attribute_unit_tokens(value, unit):
            _append(parts, tokens, compact)

    # Padded, normalized text is friendly to both FTS and trigram matching.
    text = " ".join(part for part in parts if part)
    return BuiltSearchDocument(text=text[:10000], tokens=tokens[:600])


def rebuild_listing_search_document(listing_id) -> None:
    from django.db import connection
    from listings.models import Listing, ListingSearchDocument

    try:
        listing = Listing.objects.select_related("seller", "category").get(
            pk=listing_id
        )
    except Listing.DoesNotExist:
        ListingSearchDocument.objects.filter(listing_id=listing_id).delete()
        return

    attrs = list(listing.attribute_values.select_related("field").all())
    document = build_listing_search_document(listing, attrs)
    ListingSearchDocument.objects.update_or_create(
        listing_id=listing_id,
        defaults={
            "search_text": document.text,
            "search_tokens": document.tokens,
        },
    )

    # SearchVectorField is PostgreSQL-specific; Marketlift's primary database is
    # PostgreSQL, but this guard keeps local tooling and static analysis safer.
    if connection.vendor == "postgresql":
        ListingSearchDocument.objects.filter(listing_id=listing_id).update(
            search_vector=SearchVector(Value(document.text), config="simple"),
            updated_at=timezone.now(),
        )
