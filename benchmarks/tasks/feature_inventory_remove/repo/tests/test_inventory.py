from inventory import Inventory

def test_add():
    inv = Inventory()
    inv.add("bolt", 3)
    assert inv.count("bolt") == 3
