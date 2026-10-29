import pytest
from calculator import modulo

def test_modulo():
    assert modulo(10, 3) == 1
    assert modulo(-7, 3) == 2

def test_modulo_zero():
    with pytest.raises(ValueError, match="Cannot divide by zero"):
        modulo(10, 0)
