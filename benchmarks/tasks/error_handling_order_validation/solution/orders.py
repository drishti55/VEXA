def create_order(qty, unit_price):
    if isinstance(qty, bool) or not isinstance(qty, int):
        raise TypeError('qty must be an int')
    if qty < 1:
        raise ValueError('qty must be positive')
    if unit_price < 0:
        raise ValueError('unit_price must not be negative')
    return {'qty': qty, 'unit_price': unit_price, 'total': round(qty * unit_price, 2)}
