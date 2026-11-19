import pytest
from roman import to_roman

def test_subtractive():
    assert to_roman(4) == 'IV'
    assert to_roman(9) == 'IX'
    assert to_roman(40) == 'XL'
    assert to_roman(1994) == 'MCMXCIV'
    assert to_roman(3999) == 'MMMCMXCIX'

@pytest.mark.parametrize('n', [0, -1, 4000])
def test_range(n):
    with pytest.raises(ValueError):
        to_roman(n)
