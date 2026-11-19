import threading


def _run_with_deadline(fn, seconds):
    """Run fn in a daemon thread; return (finished, value). Slow code fails fast instead of hanging."""
    box = {}
    t = threading.Thread(target=lambda: box.setdefault("v", fn()), daemon=True)
    t.start()
    t.join(seconds)
    return (not t.is_alive()), box.get("v")

from primes import primes_below


def test_million():
    finished, value = _run_with_deadline(lambda: primes_below(1_000_000), 2.0)
    assert finished, 'did not finish within 2 seconds'
    assert len(value) == 78498 and value[-1] == 999983


def test_edges():
    assert primes_below(0) == [] and primes_below(3) == [2]
