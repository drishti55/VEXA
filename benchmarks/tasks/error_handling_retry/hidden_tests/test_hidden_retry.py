import pytest
from net import fetch_with_retry

def _flaky(fails, exc=ConnectionError):
    calls = []
    def fn():
        calls.append(1)
        if len(calls) <= fails:
            raise exc('boom')
        return 'ok'
    return fn, calls

def test_recovers():
    fn, calls = _flaky(2)
    assert fetch_with_retry(fn) == 'ok' and len(calls) == 3

def test_gives_up():
    fn, calls = _flaky(99)
    with pytest.raises(ConnectionError):
        fetch_with_retry(fn, attempts=3)
    assert len(calls) == 3

def test_other_errors_not_retried():
    fn, calls = _flaky(99, ValueError)
    with pytest.raises(ValueError):
        fetch_with_retry(fn)
    assert len(calls) == 1
