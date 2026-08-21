"""Brazil location reference data used by validation, autocomplete and search."""

BRAZIL_REGIONS: dict[str, str] = {
    "N": "Norte",
    "NE": "Nordeste",
    "CO": "Centro-Oeste",
    "SE": "Sudeste",
    "S": "Sul",
}

BRAZIL_REGION_STATES: dict[str, tuple[str, ...]] = {
    "N": ("AC", "AP", "AM", "PA", "RO", "RR", "TO"),
    "NE": ("AL", "BA", "CE", "MA", "PB", "PE", "PI", "RN", "SE"),
    "CO": ("DF", "GO", "MT", "MS"),
    "SE": ("ES", "MG", "RJ", "SP"),
    "S": ("PR", "RS", "SC"),
}

BRAZIL_STATES: dict[str, str] = {
    "AC": "Acre",
    "AL": "Alagoas",
    "AP": "Amapá",
    "AM": "Amazonas",
    "BA": "Bahia",
    "CE": "Ceará",
    "DF": "Distrito Federal",
    "ES": "Espírito Santo",
    "GO": "Goiás",
    "MA": "Maranhão",
    "MT": "Mato Grosso",
    "MS": "Mato Grosso do Sul",
    "MG": "Minas Gerais",
    "PA": "Pará",
    "PB": "Paraíba",
    "PR": "Paraná",
    "PE": "Pernambuco",
    "PI": "Piauí",
    "RJ": "Rio de Janeiro",
    "RN": "Rio Grande do Norte",
    "RS": "Rio Grande do Sul",
    "RO": "Rondônia",
    "RR": "Roraima",
    "SC": "Santa Catarina",
    "SP": "São Paulo",
    "SE": "Sergipe",
    "TO": "Tocantins",
}

BRAZIL_STATE_CODES = frozenset(BRAZIL_STATES)

BRAZIL_STATE_REGION = {
    state_code: region_code
    for region_code, state_codes in BRAZIL_REGION_STATES.items()
    for state_code in state_codes
}


def normalize_brazil_region_code(value: str) -> str:
    region_code = (value or "").strip().upper()
    if region_code not in BRAZIL_REGIONS:
        raise ValueError("Select a valid Brazilian region.")
    return region_code


def normalize_brazil_state_code(value: str) -> str:
    state_code = (value or "").strip().upper()
    if state_code not in BRAZIL_STATE_CODES:
        raise ValueError("Select a valid Brazilian state.")
    return state_code


def state_belongs_to_region(state_code: str, region_code: str) -> bool:
    return BRAZIL_STATE_REGION.get(state_code.upper()) == region_code.upper()
