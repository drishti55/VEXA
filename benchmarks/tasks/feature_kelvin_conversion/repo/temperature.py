def convert(value, from_unit, to_unit):
    if from_unit == to_unit:
        return round(value, 2)
    if (from_unit, to_unit) == ('C', 'F'):
        return round(value * 9 / 5 + 32, 2)
    if (from_unit, to_unit) == ('F', 'C'):
        return round((value - 32) * 5 / 9, 2)
    raise ValueError(f"unsupported conversion {from_unit}->{to_unit}")
