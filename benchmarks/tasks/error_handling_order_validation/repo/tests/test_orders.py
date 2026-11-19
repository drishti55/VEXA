from orders import create_order

def test_ok():
    assert create_order(2, 5.0)['total'] == 10.0
