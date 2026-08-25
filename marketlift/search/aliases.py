from __future__ import annotations

from decimal import Decimal, InvalidOperation

from .normalization import compact_decimal, normalize_text

# Search-only Portuguese aliases for canonical values stored by the current
# marketplace category schema. These do not alter transactional data or API
# values; they only make the search projection understand common Brazilian
# vocabulary.
_CONDITION_ALIASES = {
    "new": ("novo", "nova", "lacrado", "lacrada"),
    "used": ("usado", "usada"),
    "like new": ("seminovo", "seminova", "como novo", "como nova"),
}

_VALUE_ALIASES = {
    ("transmission", "automatic"): ("automatico", "automatica"),
    ("transmission", "automated manual"): (
        "automatizado",
        "automatizada",
        "manual automatizado",
    ),
    ("fuel", "gasoline"): ("gasolina",),
    ("fuel", "ethanol"): ("etanol",),
    ("fuel", "electric"): ("eletrico", "eletrica"),
    ("fuel", "hybrid"): ("hibrido", "hibrida"),
    ("body type", "pickup"): ("picape",),
    ("device type", "laptop"): ("notebook",),
    ("device type", "desktop"): ("computador desktop", "pc desktop"),
    ("listing purpose", "rent"): ("aluguel", "locacao", "alugar"),
    ("listing purpose", "sale"): ("venda", "vender"),
    ("property type", "apartment"): ("apartamento", "apto"),
    ("property type", "house"): ("casa",),
    ("property type", "condo"): ("condominio",),
    ("property type", "commercial"): ("comercial",),
    ("property type", "warehouse"): ("galpao",),
    ("property type", "farm"): ("fazenda", "sitio"),
    ("property condition", "excellent"): ("excelente",),
    ("property condition", "good"): ("bom estado", "boa condicao"),
    ("property condition", "needs renovation"): ("precisa reforma", "para reformar"),
}

_KEY_ALIASES = {
    "ram_gb": ("ram", "memoria ram"),
    "storage_gb": ("armazenamento", "memoria interna"),
    "year": ("ano",),
    "mileage_km": ("quilometragem", "km rodados"),
    "transmission": ("cambio", "transmissao"),
    "fuel": ("combustivel",),
    "body_type": ("carroceria",),
    "screen_size": ("tamanho da tela", "tela"),
    "battery_health": ("saude da bateria", "bateria"),
    "listing_purpose": ("finalidade",),
    "property_type": ("tipo de imovel",),
    "bedrooms": ("quartos",),
    "bathrooms": ("banheiros",),
    "size_m2": ("area", "area construida"),
    "parking_spaces": ("vagas", "vagas de garagem"),
    "furnished": ("mobiliado", "mobiliada"),
    "condo_fee": ("condominio", "taxa de condominio"),
}


def condition_search_aliases(condition: object) -> tuple[str, ...]:
    key = normalize_text(str(condition or ""))
    return _CONDITION_ALIASES.get(key, ())


def _normalized_scalar(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return normalize_text(str(value or ""))


def _integer_text(value: object) -> str | None:
    try:
        number = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    if number != number.to_integral():
        return compact_decimal(number)
    return str(int(number))


def attribute_search_aliases(attribute) -> tuple[str, ...]:
    key = normalize_text(str(getattr(attribute, "key", "") or "")).replace(" ", "_")
    value = getattr(attribute, "value", None)
    aliases: list[str] = list(_KEY_ALIASES.get(key, ()))

    normalized_value = _normalized_scalar(value)
    aliases.extend(_VALUE_ALIASES.get((key.replace("_", " "), normalized_value), ()))

    number = _integer_text(value)
    if number is not None:
        singular = number == "1"
        if key == "bedrooms":
            aliases.append(f"{number} {'quarto' if singular else 'quartos'}")
        elif key == "bathrooms":
            aliases.append(f"{number} {'banheiro' if singular else 'banheiros'}")
        elif key == "parking_spaces":
            aliases.append(f"{number} {'vaga' if singular else 'vagas'}")
        elif key == "year":
            aliases.append(f"ano {number}")

    if key == "furnished" and value is True:
        aliases.extend(("mobiliado", "mobiliada", "com mobilia"))
    if key == "documents_ready" and value is True:
        aliases.extend(("documentos prontos", "documentacao pronta"))
    if key == "delivery_available" and value is True:
        aliases.extend(("entrega disponivel", "com entrega"))

    # Preserve order while avoiding duplicate projection text.
    return tuple(dict.fromkeys(alias for alias in aliases if alias))
