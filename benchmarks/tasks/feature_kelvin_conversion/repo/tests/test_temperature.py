import pytest
from temperature import convert

def test_c_f():
    assert convert(100, 'C', 'F') == 212
    assert convert(32, 'F', 'C') == 0

def test_unknown():
    with pytest.raises(ValueError):
        convert(1, 'C', 'X')
