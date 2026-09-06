"""Disjoint geographic pages. Only geography expands; product constraints stay exact."""

from dataclasses import replace
from datetime import datetime

from django.core import signing
from django.core.exceptions import ValidationError
from django.utils import timezone

from .backends.postgres import _fingerprint
from .contracts import SearchRequest
from .regions import BRAZIL_REGION_STATES
from .service import _load_backend, prepare_search

SALT = "marketlift.geographic-search.v1"


def geographic_tiers(request):
    """Named locations expand through their administrative parents.

    With coordinates, disjoint distance rings take precedence. We never label
    administrative proximity as a measured distance, nor cross country borders.
    """
    if request.latitude is not None and request.radius_km is not None:
        # Coordinate search defines the area by radius, including when a caller
        # also sends display labels from a selected place.
        request = replace(request, region=None, state=None, city=None, district=None)
        radii = sorted(
            {request.radius_km, *[r for r in (100, 300, 1000) if r > request.radius_km]}
        )
        tiers = []
        lower = None
        for radius in [*radii, None]:
            label = f"{radius:g} km" if radius is not None else request.country_code
            tiers.append(
                (
                    replace(request, radius_km=radius, minimum_radius_km=lower),
                    "distance",
                    label,
                )
            )
            lower = radius
        # Cards without coordinates are still available, but cannot be ranked by distance.
        tiers.append(
            (
                replace(
                    request,
                    latitude=None,
                    longitude=None,
                    radius_km=None,
                    sort="newest" if request.sort == "distance" else request.sort,
                    missing_coordinates_only=True,
                ),
                "unlocated",
                request.country_code,
            )
        )
        return tiers

    tiers = []
    current = request
    if current.district:
        tiers.append((current, "district", current.district))
        previous = dict(district__icontains=current.district)
        if current.city:
            previous["city__iexact"] = current.city
        if current.state:
            previous["state_code__iexact"] = current.state
        current = replace(current, district=None, excluded_geography=previous)
    if current.city:
        tiers.append((current, "city", current.city))
        previous = {"city__iexact": current.city}
        if current.state:
            previous["state_code__iexact"] = current.state
        current = replace(current, city=None, excluded_geography=previous)
    if current.state:
        tiers.append((current, "state", current.state))
        region = current.region or next(
            (
                code
                for code, states in BRAZIL_REGION_STATES.items()
                if current.country_code == "BR" and current.state in states
            ),
            None,
        )
        current = replace(
            current,
            state=None,
            region=region,
            excluded_geography={"state_code__iexact": current.state},
        )
    if current.region:
        tiers.append((current, "region", current.region))
        current = replace(
            current,
            region=None,
            excluded_geography={"state_code__in": BRAZIL_REGION_STATES[current.region]},
        )
    tiers.append((current, "country", current.country_code))
    return tiers


def search_progressive(request: SearchRequest):
    request, parsed = prepare_search(replace(request, allow_relaxation=False))
    fingerprint = _fingerprint(request, parsed)
    stage, inner, offset, snapshot = 0, None, 0, timezone.now()
    if request.cursor:
        try:
            payload = signing.loads(request.cursor, salt=SALT, max_age=86400)
            if payload["f"] != fingerprint:
                raise ValueError("different query")
            stage, inner, offset = int(payload["s"]), payload["c"], int(payload["o"])
            snapshot = datetime.fromisoformat(payload["at"])
        except (signing.BadSignature, KeyError, TypeError, ValueError) as exc:
            raise ValidationError(
                {"cursor": "Invalid or expired geographic cursor."}
            ) from exc
    tiers = geographic_tiers(replace(request, cursor=None, created_before=snapshot))
    if stage < 0 or stage >= len(tiers):
        raise ValidationError({"cursor": "Invalid geographic stage."})
    origin = tiers[0][2]
    while True:
        tier, level, label = tiers[stage]
        page = _load_backend().search(replace(tier, cursor=inner), parsed)
        consumed = offset + len(page.items)
        limited = page.next_cursor is None and consumed < page.total_count
        more_stage = stage + 1 < len(tiers) and not limited
        if page.items or not more_stage:
            break
        stage, inner, offset = stage + 1, None, 0
    next_cursor = None
    if page.next_cursor or more_stage:
        next_cursor = signing.dumps(
            {
                "f": fingerprint,
                "s": stage if page.next_cursor else stage + 1,
                "c": page.next_cursor,
                "o": consumed if page.next_cursor else 0,
                "at": snapshot.isoformat(),
            },
            salt=SALT,
            compress=True,
        )
    page.next_cursor = next_cursor
    return page, {
        "key": str(stage),
        "level": level,
        "label": label,
        "origin": origin,
        "expanded": stage > 0,
        "areaExhausted": consumed >= page.total_count,
        "windowLimited": limited,
    }
