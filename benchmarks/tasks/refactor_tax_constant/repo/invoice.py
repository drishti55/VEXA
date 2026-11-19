def subtotal_with_tax(amount):
    return round(amount * (1 + 0.2), 2)


def tax_amount(amount):
    return round(amount * 0.2, 2)


def line_total(qty, unit_price):
    return round(qty * unit_price * 1.2, 2)
