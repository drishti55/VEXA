def create_order(qty, unit_price):
    return {'qty': qty, 'unit_price': unit_price, 'total': round(qty * unit_price, 2)}
