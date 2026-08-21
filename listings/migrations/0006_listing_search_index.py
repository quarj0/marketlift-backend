from __future__ import annotations

import re
import unicodedata
from decimal import Decimal

import django.contrib.postgres.indexes
import django.contrib.postgres.search
import django.db.models.deletion
from django.contrib.postgres.operations import AddIndexConcurrently, TrigramExtension
from django.db import migrations, models
from django.utils import timezone


def _normalize(value):
    value = unicodedata.normalize("NFKD", str(value or ""))
    value = "".join(char for char in value if not unicodedata.combining(char)).casefold()
    value = value.replace("_", " ")
    value = re.sub(r"[^a-z0-9%+]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def _compact(value):
    try:
        number = Decimal(str(value))
        if number == number.to_integral():
            return str(number.quantize(Decimal("1")))
        return format(number.normalize(), "f")
    except Exception:
        return _normalize(value).replace(" ", "")


def _normalized_unit(value):
    raw = str(value or "").strip().casefold()
    aliases = {
        "m²": "m2",
        "inch": "in",
        "polegadas": "in",
    }
    return aliases.get(raw, _normalize(raw).replace(" ", ""))


def backfill_search_documents(apps, schema_editor):
    Listing = apps.get_model("listings", "Listing")
    ListingAttribute = apps.get_model("listings", "ListingAttribute")
    SearchDocument = apps.get_model("listings", "ListingSearchDocument")
    db = schema_editor.connection.alias

    # Backfill in bounded batches. Do not accumulate every listing attribute in
    # process memory: production migrations must remain safe as the catalogue grows.
    last_pk = None
    while True:
        listing_qs = Listing.objects.using(db).order_by("pk")
        if last_pk is not None:
            listing_qs = listing_qs.filter(pk__gt=last_pk)
        listings = list(listing_qs.select_related("category")[:500])
        if not listings:
            break

        listing_ids = [listing.pk for listing in listings]
        attributes_by_listing = {}
        for attr in (
            ListingAttribute.objects.using(db)
            .filter(listing_id__in=listing_ids)
            .select_related("field")
            .iterator(chunk_size=2000)
        ):
            attributes_by_listing.setdefault(attr.listing_id, []).append(attr)

        now = timezone.now()
        documents = []
        for listing in listings:
            parts = []
            tokens = []

            def add(value):
                normalized = _normalize(value)
                if not normalized:
                    return
                parts.append(normalized)
                for token in normalized.split():
                    if token not in tokens:
                        tokens.append(token)
                    if token.endswith("+") and len(token) > 1 and token[:-1] not in tokens:
                        tokens.append(token[:-1])

            category_name = (
                listing.category.name
                if listing.category_id
                else listing.category_name_snapshot
            )
            category_slug = (
                listing.category.slug
                if listing.category_id
                else listing.category_slug_snapshot
            )
            for value in (
                listing.title,
                (listing.description or "")[:4000],
                category_name,
                category_slug,
                listing.state,
                listing.state_code,
                listing.city,
                listing.district,
                listing.condition,
            ):
                add(value)

            for attr in attributes_by_listing.get(listing.id, []):
                add(attr.key.replace("_", " "))
                add(attr.label_snapshot)
                if attr.field_type_snapshot == "boolean":
                    value = attr.boolean_value
                elif attr.field_type_snapshot == "number":
                    value = attr.number_value
                else:
                    value = attr.text_value
                add(value)

                field = getattr(attr, "field", None)
                unit = _normalized_unit(getattr(field, "unit", "")) if field else ""
                supported_units = {
                    "gb",
                    "tb",
                    "mb",
                    "km",
                    "kg",
                    "m2",
                    "cm",
                    "mm",
                    "in",
                    "%",
                }
                if value not in (None, "") and unit in supported_units:
                    compact = f"{_compact(value)}{unit}"
                    add(compact)
                    if unit == "gb":
                        try:
                            gb = Decimal(str(value))
                            if gb >= 1024 and gb % 1024 == 0:
                                add(f"{_compact(gb / 1024)}tb")
                        except Exception:
                            pass

            documents.append(
                SearchDocument(
                    listing_id=listing.id,
                    search_text=" ".join(parts)[:10000],
                    search_tokens=tokens[:600],
                    updated_at=now,
                )
            )

        SearchDocument.objects.using(db).bulk_create(documents, batch_size=500)
        last_pk = listings[-1].pk

    if schema_editor.connection.vendor == "postgresql":
        table = schema_editor.quote_name(SearchDocument._meta.db_table)
        schema_editor.execute(
            f"UPDATE {table} "
            "SET search_vector = to_tsvector('simple', COALESCE(search_text, ''))"
        )


def clear_search_documents(apps, schema_editor):
    SearchDocument = apps.get_model("listings", "ListingSearchDocument")
    SearchDocument.objects.using(schema_editor.connection.alias).all().delete()


class Migration(migrations.Migration):
    # The search projection can be large on an established marketplace. Build
    # its GIN indexes concurrently so deploying search does not take a long
    # exclusive table lock.
    atomic = False

    dependencies = [
        ("listings", "0005_listing_seller_delete_reason_and_more"),
    ]

    operations = [
        TrigramExtension(),
        migrations.CreateModel(
            name="ListingSearchDocument",
            fields=[
                (
                    "listing",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        primary_key=True,
                        related_name="search_document",
                        serialize=False,
                        to="listings.listing",
                    ),
                ),
                ("search_text", models.TextField(blank=True, editable=False)),
                (
                    "search_tokens",
                    models.JSONField(blank=True, default=list, editable=False),
                ),
                (
                    "search_vector",
                    django.contrib.postgres.search.SearchVectorField(
                        blank=True,
                        editable=False,
                        null=True,
                    ),
                ),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
        ),
        migrations.RunPython(backfill_search_documents, clear_search_documents),
        AddIndexConcurrently(
            model_name="listingsearchdocument",
            index=django.contrib.postgres.indexes.GinIndex(
                fields=["search_vector"],
                name="listingdoc_vector_gin",
            ),
        ),
        AddIndexConcurrently(
            model_name="listingsearchdocument",
            index=django.contrib.postgres.indexes.GinIndex(
                fields=["search_tokens"],
                name="listingdoc_tokens_gin",
            ),
        ),
        AddIndexConcurrently(
            model_name="listingsearchdocument",
            index=django.contrib.postgres.indexes.GinIndex(
                fields=["search_text"],
                name="listingdoc_text_trgm",
                opclasses=("gin_trgm_ops",),
            ),
        ),
    ]
