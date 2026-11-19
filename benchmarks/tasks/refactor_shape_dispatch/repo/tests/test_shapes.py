import math
import pytest
from shapes import area

def test_areas():
    assert area({'kind': 'square', 'side': 3}) == 9
    assert area({'kind': 'rectangle', 'w': 2, 'h': 5}) == 10
    assert area({'kind': 'circle', 'r': 1}) == pytest.approx(math.pi)

def test_unknown():
    with pytest.raises(ValueError):
        area({'kind': 'hexagon'})
