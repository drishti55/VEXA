import pytest
from stats import mean

def test_fraction():
    assert mean([2, 3]) == 2.5
    assert mean([1, 2]) == 1.5

def test_empty():
    with pytest.raises(ValueError):
        mean([])
