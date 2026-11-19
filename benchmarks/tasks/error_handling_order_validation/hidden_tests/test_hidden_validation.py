import pytest
from orders import create_order

def test_qty():
    with pytest.raises(ValueError, match='qty must be positive'):
        create_order(0, 1)

@pytest.mark.parametrize('bad', [1.5, '2', True])
def test_qty_type(bad):
    with pytest.raises(TypeError):
        create_order(bad, 1)

def test_price():
    with pytest.raises(ValueError, match='unit_price must not be negative'):
        create_order(1, -0.01)
    assert create_order(1, 0)['total'] == 0
