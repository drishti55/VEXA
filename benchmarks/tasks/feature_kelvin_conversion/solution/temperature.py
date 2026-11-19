TO_C = {'C': lambda v: v, 'F': lambda v: (v - 32) * 5 / 9, 'K': lambda v: v - 273.15}
FROM_C = {'C': lambda c: c, 'F': lambda c: c * 9 / 5 + 32, 'K': lambda c: c + 273.15}


def convert(value, from_unit, to_unit):
    if from_unit not in TO_C or to_unit not in FROM_C:
        raise ValueError(f"unsupported conversion {from_unit}->{to_unit}")
    if from_unit == 'K' and value < 0:
        raise ValueError("Kelvin cannot be negative")
    return round(FROM_C[to_unit](TO_C[from_unit](value)), 2)
