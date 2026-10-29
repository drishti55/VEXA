import pytest
from inventory import Inventory

def test_remove():
    inv = Inventory()
    inv.add("bolt", 5)
    inv.remove("bolt", 2)
    assert inv.count("bolt") == 3

def test_remove_to_zero_drops_item():
    inv = Inventory()
    inv.add("nut", 1)
    inv.remove("nut", 1)
    assert "nut" not in inv.items()

def test_insufficient_unchanged():
    inv = Inventory()
    inv.add("bolt", 1)
    with pytest.raises(KeyError):
        inv.remove("bolt", 2)
    assert inv.count("bolt") == 1

def test_unknown_and_invalid():
    inv = Inventory()
    with pytest.raises(KeyError):
        inv.remove("ghost", 1)
    inv.add("bolt", 1)
    with pytest.raises(ValueError):
        inv.remove("bolt", 0)
