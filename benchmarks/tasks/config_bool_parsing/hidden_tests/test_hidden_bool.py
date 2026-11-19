import pytest
from config import get_bool

@pytest.mark.parametrize('v', ['0', 'false', 'No', 'OFF', ' false '])
def test_false(v):
    assert get_bool({'K': v}, 'K', default=True) is False

@pytest.mark.parametrize('v', ['1', 'TRUE', ' yes ', 'on'])
def test_true(v):
    assert get_bool({'K': v}, 'K') is True

def test_invalid():
    with pytest.raises(ValueError, match='K'):
        get_bool({'K': 'maybe'}, 'K')
