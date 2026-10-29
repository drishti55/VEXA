from app import handle

def test_item():
    assert handle("GET", "/items/1") == (200, {"name": "apple"})

def test_unknown():
    assert handle("GET", "/nope")[0] == 404
