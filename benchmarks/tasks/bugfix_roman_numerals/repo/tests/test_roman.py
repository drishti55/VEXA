from roman import to_roman

def test_additive():
    assert to_roman(3) == 'III'
    assert to_roman(1666) == 'MDCLXVI'
