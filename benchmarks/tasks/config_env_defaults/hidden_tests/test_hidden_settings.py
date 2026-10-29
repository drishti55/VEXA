import pytest
from settings import load_settings

def test_defaults():
    assert load_settings({}) == {"port": 8080, "debug": False}

@pytest.mark.parametrize("v,expected", [("1", True), ("TRUE", True), ("Yes", True), ("0", False), ("off", False)])
def test_debug_parsing(v, expected):
    assert load_settings({"DEBUG": v})["debug"] is expected

def test_invalid_port():
    with pytest.raises(ValueError):
        load_settings({"PORT": "x"})
