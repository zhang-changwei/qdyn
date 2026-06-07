import re
import ase.data

# Valid pseudo-hydrogen ZVAL charges
_VALID_PSEUDO_H_CHARGES: set[float] = {
    0.25, 0.33, 0.42, 0.5, 0.58, 0.66, 0.75, 1.00,
    1.25, 1.33, 1.5, 1.66, 1.75,
}


def validate_pseudo_h_symbols(raw_symbols: list[str]) -> None:
    """Validate that all H-like symbols use H\\d{3} format with a valid charge.

    Raises ValueError if any pseudo-hydrogen symbol has an unrecognised
    format or invalid ZVAL charge.
    """
    h_like = 0
    for sym in raw_symbols:
        sym = sym.strip()
        if not sym.startswith('H') or sym == 'H':
            if sym not in ase.data.chemical_symbols or sym == 'X':
                raise ValueError(
                    f"Invalid symbol: '{sym}'. Expected a valid chemical symbol "
                    "or a pseudo-hydrogen placeholder like H050, H075, etc."
                )
            continue
        else:
            rest = sym[1:]
            if not re.fullmatch(r'\d{3}', rest):
                raise ValueError(
                    f"Invalid pseudo-hydrogen symbol: '{sym}'. "
                    "Expected format: H\\d{3} (e.g. H050, H075)."
                )
            charge = int(rest) / 100.0
            if charge not in _VALID_PSEUDO_H_CHARGES:
                raise ValueError(
                    f"Invalid pseudo-hydrogen symbol: '{sym}'. "
                    f"Charge {charge} is not a valid pseudo-H ZVAL. "
                )
            h_like += 1
        
    if not h_like:
        raise ValueError(
            "No pseudo-hydrogen symbols (H\\d{3}) found in structure. "
            "Expected placeholder symbols like H050, H075, etc."
        )


def parse_pseudo_h_symbol(symbol: str) -> float | None:
    """Parse a pseudo-hydrogen symbol (e.g. "H050") to extract the ZVAL charge.
    """
    symbol = symbol.strip()
    if not symbol.startswith('H') or symbol == 'H':
        return None
    val = int(symbol[1:])
    return val / 100.0


def resolve_symbol(sym: str, tag: int) -> str:
    """Return the effective (placeholder) symbol for an atom.

    Pseudo-H atoms (tag > 0) get their placeholder symbol (e.g. "H050");
    plain-H or other elements keep their original symbol.
    """
    if sym == 'H' and tag > 0:
        return f"H{tag:03d}"''
    return sym
