from pricing import member_price, sale_price

def test_member():
    assert member_price(50) == 45.0

def test_sale():
    assert sale_price(19.99, 25) == 14.99
