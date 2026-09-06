from __future__ import annotations

import logging
import os
import re
from typing import Iterable

from django.core.cache import cache
from django.db import transaction
from django.utils.text import slugify

from categories.models import (
    Category,
    CategoryField,
    CategoryFieldOption,
    CategoryFieldOptionDependency,
)

from . import fipe, wikidata

logger = logging.getLogger(__name__)


def _int_env(name: str, default: int) -> int:
    try:
        return max(1, int(os.environ.get(name, default)))
    except (TypeError, ValueError):
        return default


def _clean(value: object) -> str:
    return " ".join(str(value or "").strip().split())


def _norm(value: object) -> str:
    return re.sub(r"[^a-z0-9]+", "", _clean(value).casefold())


def _root_value(label: str) -> str:
    value = slugify(label)[:120]
    return value or label[:120]


def _find_root_option(field: CategoryField, label: str) -> CategoryFieldOption | None:
    direct = field.options.filter(label__iexact=label).first()
    if direct is not None:
        return direct

    needle = _norm(label)
    for option in field.options.filter(active=True):
        parts = re.split(r"\s*/\s*|\s+\|\s+|\s+&\s+", option.label)
        if any(_norm(part) == needle for part in parts):
            return option
    return None


def _upsert_root_option(
    field: CategoryField, label: str, sort_order: int
) -> CategoryFieldOption:
    option = _find_root_option(field, label)
    if option is None:
        base = _root_value(label)
        value = base
        suffix = 2
        while field.options.filter(value=value).exists():
            value = f"{base[:112]}-{suffix}"
            suffix += 1
        option = CategoryFieldOption.objects.create(
            field=field,
            value=value,
            label=label[:120],
            active=True,
            sort_order=sort_order,
        )
        return option

    changed = []
    if not option.active:
        option.active = True
        changed.append("active")
    if option.label != label and _norm(option.label) == _norm(label):
        option.label = label[:120]
        changed.append("label")
    if changed:
        changed.append("updated_at")
        option.save(update_fields=tuple(changed))
    return option


def _child_for_parent(
    field: CategoryField,
    parent: CategoryFieldOption,
    label: str,
    *,
    sort_order: int,
    leaf: bool = False,
) -> CategoryFieldOption:
    existing = (
        field.options.filter(
            label__iexact=label,
            allowed_parent_links__parent_option=parent,
        )
        .distinct()
        .first()
    )
    if existing is not None:
        changed = []
        if not existing.active:
            existing.active = True
            changed.append("active")
        if changed:
            changed.append("updated_at")
            existing.save(update_fields=tuple(changed))
        CategoryFieldOptionDependency.objects.get_or_create(
            option=existing, parent_option=parent
        )
        return existing

    if leaf:
        candidate = label[:120]
        option = field.options.filter(value=candidate).first()
        if option is None:
            option = CategoryFieldOption.objects.create(
                field=field,
                value=candidate,
                label=label[:120],
                active=True,
                sort_order=sort_order,
            )
        elif not option.active:
            option.active = True
            option.save(update_fields=("active", "updated_at"))
    else:
        candidate = label[:120]
        collision = field.options.filter(value=candidate).first()
        if collision is not None:
            linked_to_parent = collision.allowed_parent_links.filter(
                parent_option=parent
            ).exists()
            if not linked_to_parent:
                suffix = f" ({parent.label})"
                candidate = f"{label[: max(1, 120 - len(suffix))]}{suffix}"
                counter = 2
                while field.options.filter(value=candidate).exists():
                    suffix = f" ({parent.label} {counter})"
                    candidate = f"{label[: max(1, 120 - len(suffix))]}{suffix}"
                    counter += 1
        option, _ = CategoryFieldOption.objects.update_or_create(
            field=field,
            value=candidate,
            defaults={
                "label": label[:120],
                "active": True,
                "sort_order": sort_order,
            },
        )

    CategoryFieldOptionDependency.objects.get_or_create(
        option=option, parent_option=parent
    )
    return option


def _prune_root(field: CategoryField, keep_ids: set) -> None:
    if not keep_ids:
        return
    field.options.filter(active=True).exclude(pk__in=keep_ids).update(active=False)


def _prune_child_branch(
    field: CategoryField,
    parent: CategoryFieldOption,
    keep_ids: set,
) -> None:
    links = CategoryFieldOptionDependency.objects.filter(
        option__field=field,
        parent_option=parent,
    )
    if keep_ids:
        links.exclude(option_id__in=keep_ids).delete()
    else:
        links.delete()

    orphan_ids = list(
        field.options.filter(active=True, allowed_parent_links__isnull=True)
        .values_list("pk", flat=True)
    )
    if orphan_ids:
        field.options.filter(pk__in=orphan_ids).update(active=False)


def _branch_marker(provider: str, field: CategoryField, parent: CategoryFieldOption | None):
    parent_token = str(parent.pk) if parent is not None else "root"
    return (
        f"marketlift:dynamic-catalog:hydrated:{provider}:"
        f"{field.category.slug}:{field.key}:{parent_token}"
    )


def _branch_due(
    provider: str,
    field: CategoryField,
    parent: CategoryFieldOption | None,
) -> bool:
    return not bool(cache.get(_branch_marker(provider, field, parent)))


def _mark_branch(
    provider: str,
    field: CategoryField,
    parent: CategoryFieldOption | None,
    *,
    ttl_env: str,
    default_ttl: int,
) -> None:
    cache.set(
        _branch_marker(provider, field, parent),
        "1",
        timeout=_int_env(ttl_env, default_ttl),
    )


def _named(items: Iterable[dict] | None) -> list[tuple[str, str]]:
    result = []
    for item in items or []:
        code = _clean(item.get("code") or item.get("id"))
        name = _clean(item.get("name"))
        if code and name:
            result.append((code, name[:120]))
    return result


def _match_named(
    items: Iterable[dict] | None,
    label: str,
) -> tuple[str, str] | None:
    needle = _norm(label)
    aliases = {
        _norm(part)
        for part in re.split(r"\s*/\s*|\s+\|\s+|\s+&\s+", label)
        if _clean(part)
    }
    aliases.add(needle)
    for code, name in _named(items):
        if _norm(name) in aliases:
            return code, name
    return None


@transaction.atomic
def _enrich_fipe(
    field: CategoryField,
    parent: CategoryFieldOption | None,
) -> None:
    scope = fipe.VEHICLE_SCOPES.get(field.category.slug)
    if not scope or field.key not in {"make", "model", "year"}:
        return
    if not _branch_due("fipe", field, parent):
        return

    if field.key == "make":
        items = fipe.brands(scope)
        if items is None:
            return
        keep_ids = set()
        for index, (_, name) in enumerate(_named(items)):
            option = _upsert_root_option(field, name, index)
            keep_ids.add(option.pk)
        if keep_ids:
            _prune_root(field, keep_ids)
            _mark_branch(
                "fipe",
                field,
                None,
                ttl_env="DYNAMIC_CATALOG_FIPE_TTL_SECONDS",
                default_ttl=30 * 24 * 60 * 60,
            )
        return

    if parent is None:
        return

    if field.key == "model":
        brands = fipe.brands(scope)
        brand = _match_named(brands, parent.label)
        if brand is None:
            return
        brand_code, _ = brand
        items = fipe.models(scope, brand_code)
        if items is None:
            return

        keep_ids = set()
        for index, (_, name) in enumerate(_named(items)):
            option = _child_for_parent(
                field,
                parent,
                name,
                sort_order=index,
                leaf=False,
            )
            keep_ids.add(option.pk)
        if keep_ids:
            _prune_child_branch(field, parent, keep_ids)
            _mark_branch(
                "fipe",
                field,
                parent,
                ttl_env="DYNAMIC_CATALOG_FIPE_TTL_SECONDS",
                default_ttl=30 * 24 * 60 * 60,
            )
        return

    model_option = parent
    make_link = (
        model_option.allowed_parent_links.select_related("parent_option")
        .filter(parent_option__field__key="make")
        .first()
    )
    if make_link is None:
        return
    make_option = make_link.parent_option

    brands = fipe.brands(scope)
    brand = _match_named(brands, make_option.label)
    if brand is None:
        return
    brand_code, _ = brand
    models = fipe.models(scope, brand_code)
    model = _match_named(models, model_option.label)
    if model is None:
        return
    model_code, _ = model
    items = fipe.years(scope, brand_code, model_code)
    if items is None:
        return

    years = []
    seen = set()
    for item in items:
        year = fipe.year_from_code(item.get("code"))
        if year is None or year in seen:
            continue
        seen.add(year)
        years.append(year)
    years.sort(reverse=True)

    keep_ids = set()
    for index, year in enumerate(years):
        option = _child_for_parent(
            field,
            model_option,
            str(year),
            sort_order=index,
            leaf=True,
        )
        keep_ids.add(option.pk)
    if keep_ids:
        _prune_child_branch(field, model_option, keep_ids)
        _mark_branch(
            "fipe",
            field,
            model_option,
            ttl_env="DYNAMIC_CATALOG_FIPE_TTL_SECONDS",
            default_ttl=30 * 24 * 60 * 60,
        )


@transaction.atomic
def _enrich_wikidata(
    field: CategoryField,
    parent: CategoryFieldOption | None,
) -> None:
    class_id = wikidata.CATEGORY_CLASSES.get(field.category.slug)
    if not class_id or field.key not in {"brand", "model"}:
        return
    if not _branch_due("wikidata", field, parent):
        return

    if field.key == "brand":
        items = wikidata.brands_for_category(class_id)
        if items is None:
            return
        for index, item in enumerate(items):
            name = _clean(item.get("name"))
            if name:
                _upsert_root_option(field, name, index)
        _mark_branch(
            "wikidata",
            field,
            None,
            ttl_env="DYNAMIC_CATALOG_WIKIDATA_TTL_SECONDS",
            default_ttl=30 * 24 * 60 * 60,
        )
        return

    if parent is None:
        return

    brands = wikidata.brands_for_category(class_id)
    if items_are_unavailable(brands):
        return
    match = _match_named(brands, parent.label)
    if match is None:
        # A curated alias such as "Xiaomi / Redmi / POCO" may not have an
        # exact Wikidata brand. Keep the curated branch and custom fallback.
        _mark_branch(
            "wikidata",
            field,
            parent,
            ttl_env="DYNAMIC_CATALOG_WIKIDATA_TTL_SECONDS",
            default_ttl=7 * 24 * 60 * 60,
        )
        return

    brand_id, _ = match
    items = wikidata.models_for_brand(class_id, brand_id)
    if items is None:
        return
    for index, (_, name) in enumerate(_named(items)):
        _child_for_parent(
            field,
            parent,
            name,
            sort_order=index,
            leaf=False,
        )
    # Wikidata is deliberately additive: the curated Marketlift catalog may
    # contain valid products Wikidata does not.
    _mark_branch(
        "wikidata",
        field,
        parent,
        ttl_env="DYNAMIC_CATALOG_WIKIDATA_TTL_SECONDS",
        default_ttl=30 * 24 * 60 * 60,
    )


def items_are_unavailable(items) -> bool:
    return items is None


def enrich_category_field_options(
    field: CategoryField,
    *,
    parent_option: CategoryFieldOption | None = None,
    search: str | None = None,
) -> None:
    del search  # reserved for future provider-side search without changing GraphQL.
    try:
        if field.category.slug in fipe.VEHICLE_SCOPES:
            _enrich_fipe(field, parent_option)
        elif field.category.slug in wikidata.CATEGORY_CLASSES:
            _enrich_wikidata(field, parent_option)
    except Exception:
        # External catalog availability must never block listing creation.
        # Existing cached options and "Other / Not listed" remain usable.
        logger.exception(
            "Dynamic catalog enrichment failed for %s.%s",
            field.category.slug,
            field.key,
        )
