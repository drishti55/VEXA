from settings import load_settings

def test_explicit():
    assert load_settings({"PORT": "9000", "DEBUG": "true"}) == {"port": 9000, "debug": True}
