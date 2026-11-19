from config import get_bool

def test_true_and_default():
    assert get_bool({'A': 'true'}, 'A') is True
    assert get_bool({}, 'A', default=True) is True
