from orders import connect, order_count

def test_count():
    assert order_count(connect()) == 5
