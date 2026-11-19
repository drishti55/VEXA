from net import fetch_with_retry

def test_success():
    assert fetch_with_retry(lambda: 42) == 42
