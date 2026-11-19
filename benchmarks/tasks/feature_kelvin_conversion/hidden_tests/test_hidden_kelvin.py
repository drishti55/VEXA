import pytest
from temperature import convert

def test_to_k():
    assert convert(0, 'C', 'K') == 273.15
    assert convert(212, 'F', 'K') == 373.15

def test_from_k():
    assert convert(273.15, 'K', 'C') == 0
    assert convert(0, 'K', 'F') == -459.67

def test_negative_kelvin():
    with pytest.raises(ValueError):
        convert(-1, 'K', 'C')
