def apply_discount(price, percent):
    return round(price - price * percent / 100, 2)

def member_price(price):
    return apply_discount(price, 10)

def sale_price(price, percent):
    return apply_discount(price, percent)
