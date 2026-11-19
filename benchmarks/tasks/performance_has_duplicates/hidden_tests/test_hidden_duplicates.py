import threading


def _run_with_deadline(fn, seconds):
    """Run fn in a daemon thread; return (finished, value). Slow code fails fast instead of hanging."""
    box = {}
    t = threading.Thread(target=lambda: box.setdefault("v", fn()), daemon=True)
    t.start()
    t.join(seconds)
    return (not t.is_alive()), box.get("v")

from listutil import has_duplicates


def test_large_fast():
    finished, value = _run_with_deadline(lambda: has_duplicates(list(range(200_000))), 1.0)
    assert finished, 'did not finish within 1 second'
    assert value is False


def test_large_with_dup():
    finished, value = _run_with_deadline(lambda: has_duplicates(list(range(200_000)) + [199_999]), 1.0)
    assert finished and value is True
