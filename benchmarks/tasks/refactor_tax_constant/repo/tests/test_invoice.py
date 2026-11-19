from invoice import subtotal_with_tax, tax_amount, line_total

def test_values():
    assert subtotal_with_tax(100) == 120.0
    assert tax_amount(50) == 10.0
    assert line_total(3, 10) == 36.0
