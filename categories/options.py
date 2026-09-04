from datetime import date


def option_is_current(field, option) -> bool:
    """Hide future calendar years until that year is actually reached."""
    if field.key != "year":
        return True
    try:
        year = int(str(option.value).strip())
    except (TypeError, ValueError):
        return True
    return year <= date.today().year
