from __future__ import annotations

import hashlib
import re
from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.contrib.postgres.search import (
    SearchQuery,
    SearchRank,
    TrigramWordSimilarity,
)
from django.core import signing
from django.core.exceptions import ValidationError
from django.db import connection, transaction
from django.db.models import Case, F, FloatField, IntegerField, Q, Value, When
from django.db.models.functions import Coalesce
from django.utils import timezone

from listings.querysets import with_listing_card_data
from listings.models import Listing, ListingAttribute
from listings.search import apply_listing_sort
from marketlift.search.backends.base import ListingSearchBackend
from marketlift.search.regions import BRAZIL_REGION_STATES
from marketlift.search.contracts import (
    ParsedMarketplaceQuery,
    RelaxedConstraint,
    SearchPage,
    SearchRequest,
)

_CURSOR_SALT = "marketlift.search.cursor.v1"

_SPEC_UNIT_RE = re.compile(r"^[0-9.]+(?P<unit>gb|tb|mb|km|kg|m2|cm|mm|in|%)$")
_UNIT_COMPATIBILITY = {
    "tb": {"tb", "gb"},
    "gb": {"gb"},
    "mb": {"mb"},
    "km": {"km"},
    "kg": {"kg"},
    "m2": {"m2", "m²"},
    "cm": {"cm"},
    "mm": {"mm"},
    "in": {"in", "inch", "polegadas"},
    "%": {"%"},
}


def _text_token_q(field: str, token: str) -> Q:
    """Match a normalized token on whitespace boundaries without user regex."""
    return (
        Q(**{f"{field}__exact": token})
        | Q(**{f"{field}__startswith": f"{token} "})
        | Q(**{f"{field}__contains": f" {token} "})
        | Q(**{f"{field}__endswith": f" {token}"})
    )


def _specifications_fit_candidate_listings(qs, parsed: ParsedMarketplaceQuery) -> bool:
    """Return True only when the candidate listings actually expose compatible specs.

    Relaxation is a narrow marketplace fallback, not a way to discard nonsense.
    For example, ``Honda Civic 8gb`` must stay empty merely because the query has
    a valid product anchor: if the matching Civic listings do not carry a GB-based
    category attribute, ``8gb`` is not a meaningful constraint for those results
    and must not be dropped.

    Checking existing ListingAttribute rows (rather than only CategoryField schema)
    is intentionally stricter: it proves the candidate set contains real values in
    that unit family.
    """
    if not parsed.specification_tokens:
        return True

    candidate_ids = qs.order_by().values("pk")
    for token in parsed.specification_tokens:
        match = _SPEC_UNIT_RE.fullmatch(token)
        if not match:
            return False
        units = _UNIT_COMPATIBILITY.get(match.group("unit"), {match.group("unit")})
        unit_query = Q()
        for unit in units:
            unit_query |= Q(field__unit__iexact=unit)
        if not (
            ListingAttribute.objects.filter(listing_id__in=candidate_ids)
            .filter(unit_query)
            .exclude(field__isnull=True)
            .exists()
        ):
            return False
    return True


def _require_spec_tokens(qs, tokens: list[str] | tuple[str, ...]):
    if not tokens:
        return qs
    if connection.vendor == "postgresql":
        for token in tokens:
            qs = qs.filter(search_document__search_tokens__contains=[token])
        return qs
    for token in tokens:
        qs = qs.filter(_text_token_q("search_document__search_text", token))
    return qs


def _fingerprint(request: SearchRequest, parsed: ParsedMarketplaceQuery) -> str:
    raw = repr(
        (
            parsed.normalized,
            request.category,
            request.region,
            request.state,
            request.city,
            request.district,
            str(request.min_price),
            str(request.max_price),
            str(parsed.min_price),
            str(parsed.max_price),
            request.condition,
            request.seller_type,
            request.seller_id,
            request.verified_only,
            request.date_listed,
            request.attribute_filters,
            request.sort,
            request.exclude_user_id,
            str(request.created_after),
            request.allow_relaxation,
        )
    ).encode()
    return hashlib.sha256(raw).hexdigest()[:20]


def _decode_cursor(cursor: str | None, *, fingerprint: str) -> int:
    if not cursor:
        return 0
    try:
        payload = signing.loads(cursor, salt=_CURSOR_SALT, max_age=60 * 60 * 24)
    except signing.BadSignature as exc:
        raise ValidationError({"cursor": "Invalid or expired search cursor."}) from exc
    if payload.get("f") != fingerprint:
        raise ValidationError(
            {"cursor": "Search cursor does not belong to this query."}
        )
    try:
        offset = int(payload.get("o", 0))
    except (TypeError, ValueError) as exc:
        raise ValidationError({"cursor": "Invalid search cursor."}) from exc
    max_window = getattr(settings, "MARKETLIFT_SEARCH_MAX_WINDOW", 5000)
    if offset < 0 or offset > max_window:
        raise ValidationError(
            {"cursor": "Search cursor is outside the allowed result window."}
        )
    return offset


def _encode_cursor(offset: int, *, fingerprint: str) -> str:
    return signing.dumps(
        {"o": offset, "f": fingerprint}, salt=_CURSOR_SALT, compress=True
    )


def _decimal(value) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value))
    except Exception:
        return None


def _apply_structured_filters(
    qs, request: SearchRequest, parsed: ParsedMarketplaceQuery
):
    category = (request.category or "").strip()
    region = (request.region or "").strip().upper()
    state = (request.state or "").strip()
    city = (request.city or "").strip()
    district = (request.district or "").strip()

    if category:
        qs = qs.filter(category__slug=category)
    if region:
        qs = qs.filter(state_code__in=BRAZIL_REGION_STATES.get(region, ()))
    if state:
        qs = qs.filter(state_code__iexact=state)
    if city:
        qs = qs.filter(city__iexact=city)
    if district:
        qs = qs.filter(district__icontains=district)
    if request.condition:
        qs = qs.filter(condition=request.condition)
    if request.seller_type:
        qs = qs.filter(seller__seller_type=request.seller_type)
    if request.seller_id:
        qs = qs.filter(seller_id=request.seller_id)
    if request.verified_only:
        qs = qs.filter(seller__verified_at__isnull=False)
    if request.exclude_user_id:
        qs = qs.exclude(seller__user_id=request.exclude_user_id)
    if request.created_after is not None:
        qs = qs.filter(created_at__gt=request.created_after)

    min_candidates = [
        value for value in (request.min_price, parsed.min_price) if value is not None
    ]
    max_candidates = [
        value for value in (request.max_price, parsed.max_price) if value is not None
    ]
    min_price = max(min_candidates) if min_candidates else None
    max_price = min(max_candidates) if max_candidates else None
    if min_price is not None and max_price is not None and min_price > max_price:
        raise ValidationError(
            {"price": "Combined search price filters do not overlap."}
        )
    if min_price is not None:
        qs = qs.filter(price__gte=min_price)
    if max_price is not None:
        qs = qs.filter(price__lte=max_price)

    days = {"today": 1, "week": 7, "month": 30}.get(request.date_listed)
    if days:
        qs = qs.filter(created_at__gte=timezone.now() - timedelta(days=days))

    for key, value in list(request.attribute_filters.items())[:20]:
        if isinstance(value, dict):
            minimum = _decimal(value.get("min"))
            maximum = _decimal(value.get("max"))
            if minimum is not None:
                qs = qs.filter(
                    attribute_values__key=key,
                    attribute_values__number_value__gte=minimum,
                )
            if maximum is not None:
                qs = qs.filter(
                    attribute_values__key=key,
                    attribute_values__number_value__lte=maximum,
                )
        elif isinstance(value, bool):
            qs = qs.filter(
                attribute_values__key=key,
                attribute_values__boolean_value=value,
            )
        elif isinstance(value, Decimal):
            qs = qs.filter(
                attribute_values__key=key,
                attribute_values__number_value=value,
            )
        elif value not in (None, ""):
            qs = qs.filter(
                attribute_values__key=key,
                attribute_values__text_value__iexact=str(value),
            )
    return qs.distinct()


def _apply_core_terms(qs, parsed: ParsedMarketplaceQuery):
    if not parsed.core_tokens:
        return qs

    # Every meaningful core token is required. Fuzzy matching is only enabled
    # for alphabetic words of length >= 4, which prevents short model codes
    # such as S21 from matching unrelated text.
    fuzzy_aliases: list[str] = []
    for index, token in enumerate(parsed.core_tokens):
        if connection.vendor == "postgresql":
            exact = Q(search_document__search_tokens__contains=[token])
        elif token.isalpha() and len(token) >= 4:
            # Lightweight development/test fallback. PostgreSQL production uses
            # pg_trgm below; here prefix-like misspellings such as samsun/samsung
            # can still be exercised without turning short model codes into
            # substring matches.
            exact = Q(search_document__search_text__icontains=token)
        else:
            exact = _text_token_q("search_document__search_text", token)

        if token.isalpha() and len(token) >= 4 and connection.vendor == "postgresql":
            alias = f"_ml_trgm_{index}"
            qs = qs.annotate(
                **{
                    alias: TrigramWordSimilarity(
                        Value(token), "search_document__search_text"
                    )
                }
            )
            # pg_trgm's word-similar operator is index-assisted by gin_trgm_ops.
            # The score threshold is kept slightly above PostgreSQL's broad
            # similarity default to avoid noisy marketplace matches.
            fuzzy = Q(search_document__search_text__trigram_word_similar=token) & Q(
                **{f"{alias}__gte": 0.62}
            )
            qs = qs.filter(exact | fuzzy)
            fuzzy_aliases.append(alias)
        else:
            qs = qs.filter(exact)

    if connection.vendor == "postgresql":
        query = SearchQuery(
            " ".join(parsed.core_tokens), config="simple", search_type="plain"
        )
        qs = qs.annotate(
            search_rank=Coalesce(
                SearchRank(F("search_document__search_vector"), query),
                Value(0.0),
                output_field=FloatField(),
            )
        )
        if fuzzy_aliases:
            score = Value(0.0, output_field=FloatField())
            for alias in fuzzy_aliases:
                score = score + Coalesce(F(alias), Value(0.0))
            qs = qs.annotate(typo_score=score)
    return qs


def _annotate_spec_matches(qs, parsed: ParsedMarketplaceQuery):
    if not parsed.specification_tokens or connection.vendor != "postgresql":
        return qs
    score = Value(0, output_field=IntegerField())
    for token in parsed.specification_tokens:
        score = score + Case(
            When(search_document__search_tokens__contains=[token], then=Value(1)),
            default=Value(0),
            output_field=IntegerField(),
        )
    return qs.annotate(spec_match_count=score)


def _require_specs(qs, parsed: ParsedMarketplaceQuery):
    return _require_spec_tokens(qs, parsed.specification_tokens)


class PostgresListingSearchBackend(ListingSearchBackend):
    @transaction.atomic
    def search(
        self, request: SearchRequest, parsed: ParsedMarketplaceQuery
    ) -> SearchPage:
        if connection.vendor == "postgresql":
            timeout_ms = max(
                100,
                min(
                    int(
                        getattr(
                            settings, "MARKETLIFT_SEARCH_STATEMENT_TIMEOUT_MS", 1500
                        )
                    ),
                    10000,
                ),
            )
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT set_config('statement_timeout', %s, true)",
                    [f"{timeout_ms}ms"],
                )

        base = Listing.objects.public()
        if (
            parsed.original
            and not parsed.core_tokens
            and not parsed.specification_tokens
            and parsed.min_price is None
            and parsed.max_price is None
        ):
            base = base.none()
        base = _apply_structured_filters(base, request, parsed)
        base = _apply_core_terms(base, parsed)
        base = _annotate_spec_matches(base, parsed)

        exact = _require_specs(base, parsed)
        relaxed: list[RelaxedConstraint] = []

        # A specification-only query must never degrade into "show everything".
        # Relaxation is allowed only when there is a meaningful textual anchor AND
        # the candidate listings themselves contain attributes in the requested
        # unit family. That means:
        #   Samsung S21 8gb -> may fall back to other S21 RAM/storage variants.
        #   Honda Civic 8gb -> stays empty; 8gb is not a Civic specification here.
        #
        # With multiple specifications we relax the smallest possible suffix, one
        # token at a time. This retains as much explicit user intent as possible.
        can_relax = (
            request.allow_relaxation
            and parsed.specification_tokens
            and parsed.has_text_anchor
            and not exact.exists()
            and base.exists()
            and _specifications_fit_candidate_listings(base, parsed)
        )
        if can_relax:
            retained = list(parsed.specification_tokens)
            dropped: list[str] = []
            qs = exact
            while retained:
                dropped.insert(0, retained.pop())
                candidate = _require_spec_tokens(base, retained)
                if candidate.exists():
                    qs = candidate
                    relaxed = [
                        RelaxedConstraint(kind="specification", value=token)
                        for token in dropped
                    ]
                    break
        else:
            qs = exact

        qs = apply_listing_sort(qs, request.sort)
        total = qs.count()
        fingerprint = _fingerprint(request, parsed)
        cursor_offset = _decode_cursor(request.cursor, fingerprint=fingerprint)
        offset = cursor_offset if request.cursor else max(0, request.offset)
        max_window = getattr(settings, "MARKETLIFT_SEARCH_MAX_WINDOW", 5000)
        if offset > max_window:
            raise ValidationError(
                {"offset": "Search offset is outside the allowed result window."}
            )

        page_size = max(
            1,
            min(
                request.page_size,
                getattr(settings, "MARKETLIFT_SEARCH_MAX_PAGE_SIZE", 50),
            ),
        )
        id_rows = list(qs.only("pk")[offset : offset + page_size + 1])
        has_next = len(id_rows) > page_size
        id_rows = id_rows[:page_size]
        ordered_ids = [row.pk for row in id_rows]

        # Search/count queries stay lean. Card aggregates, media and promotions are
        # hydrated only for the small result page instead of joining them across
        # the entire candidate set.
        hydrated = {
            row.pk: row
            for row in with_listing_card_data(
                Listing.objects.public().filter(pk__in=ordered_ids)
            )
        }
        rows = [hydrated[pk] for pk in ordered_ids if pk in hydrated]

        next_cursor = None
        next_offset = offset + len(id_rows)
        if has_next and next_offset <= max_window:
            next_cursor = _encode_cursor(next_offset, fingerprint=fingerprint)

        return SearchPage(
            items=rows,
            total_count=total,
            next_cursor=next_cursor,
            parsed_query=parsed,
            relaxed=relaxed,
        )
