from netconfig import parse_port

def test_plain_port():
    assert parse_port("80") == 80
