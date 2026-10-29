import inspect
import pricing

def test_apply_discount():
    assert pricing.apply_discount(100, 15) == 85.0
    assert pricing.apply_discount(19.99, 25) == 14.99

def test_callers_reuse_it():
    for fn in (pricing.member_price, pricing.sale_price):
        assert "apply_discount" in inspect.getsource(fn)

def test_behaviour_unchanged():
    assert pricing.member_price(50) == 45.0 and pricing.sale_price(80, 50) == 40.0
