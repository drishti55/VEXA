import pytest
from cache import Cache

def test_evicts_lru():
    c = Cache(2)
    c.put('a', 1)
    c.put('b', 2)
    c.put('c', 3)
    assert c.get('a') is None and c.get('b') == 2 and c.get('c') == 3
    assert len(c) == 2

def test_get_refreshes():
    c = Cache(2)
    c.put('a', 1)
    c.put('b', 2)
    c.get('a')
    c.put('c', 3)
    assert c.get('a') == 1 and c.get('b') is None

def test_update_refreshes():
    c = Cache(2)
    c.put('a', 1)
    c.put('b', 2)
    c.put('a', 10)
    c.put('c', 3)
    assert c.get('a') == 10 and c.get('b') is None

def test_bad_capacity():
    with pytest.raises(ValueError):
        Cache(0)
