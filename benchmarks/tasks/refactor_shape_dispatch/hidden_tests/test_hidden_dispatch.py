import pytest
import shapes

def test_table():
    assert {'circle', 'square', 'rectangle'} <= set(shapes.AREA_FUNCS)

def test_register(monkeypatch):
    monkeypatch.setitem(shapes.AREA_FUNCS, 'triangle', lambda s: s['b'] * s['h'] / 2)
    assert shapes.area({'kind': 'triangle', 'b': 4, 'h': 3}) == 6

def test_unknown():
    with pytest.raises(ValueError):
        shapes.area({'kind': 'blob'})
