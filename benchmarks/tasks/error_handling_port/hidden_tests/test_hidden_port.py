import pytest
from netconfig import parse_port

def test_whitespace():
    assert parse_port(" 8080 ") == 8080

@pytest.mark.parametrize("bad", ["abc", "", "0", "70000", "-1", "80.5"])
def test_invalid(bad):
    with pytest.raises(ValueError):
        parse_port(bad)
