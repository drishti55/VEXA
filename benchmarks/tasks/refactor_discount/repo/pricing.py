def member_price(price):
    discounted = price - price * 10 / 100
    return round(discounted, 2)

def sale_price(price, percent):
    discounted = price - price * percent / 100
    return round(discounted, 2)
