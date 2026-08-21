"""Brazil location reference data used by validation and search."""

BRAZIL_REGION_STATES: dict[str, tuple[str, ...]] = {
    "N": ("AC", "AP", "AM", "PA", "RO", "RR", "TO"),
    "NE": ("AL", "BA", "CE", "MA", "PB", "PE", "PI", "RN", "SE"),
    "CO": ("DF", "GO", "MT", "MS"),
    "SE": ("ES", "MG", "RJ", "SP"),
    "S": ("PR", "RS", "SC"),
}

BRAZIL_STATE_CODES = frozenset(
    state_code
    for state_codes in BRAZIL_REGION_STATES.values()
    for state_code in state_codes
)


def normalize_brazil_state_code(value: str) -> str:
    state_code = (value or "").strip().upper()
    if state_code not in BRAZIL_STATE_CODES:
        raise ValueError("Select a valid Brazilian state.")
    return state_code
