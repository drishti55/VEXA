import invoice

def test_constant():
    assert invoice.TAX_RATE == 0.2

def test_all_use_constant(monkeypatch):
    monkeypatch.setattr(invoice, 'TAX_RATE', 0.1)
    assert invoice.subtotal_with_tax(100) == 110.0
    assert invoice.tax_amount(50) == 5.0
    assert invoice.line_total(3, 10) == 33.0
