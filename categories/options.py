from datetime import date

VEHICLE_CATEGORY_SLUGS = {
    "cars",
    "motorcycles",
    "trucks-commercial-vehicles",
    "buses-vans",
}


def option_is_current(field, option) -> bool:
    "Hide genuinely future years while allowing Brazil's next model year."
    if field.key != "year":
        return True
    try:
        year = int(str(option.value).strip())
    except (TypeError, ValueError):
        return True

    current_year = date.today().year
    category_slug = getattr(getattr(field, "category", None), "slug", "")
    max_year = (
        current_year + 1 if category_slug in VEHICLE_CATEGORY_SLUGS else current_year
    )
    return year <= max_year
