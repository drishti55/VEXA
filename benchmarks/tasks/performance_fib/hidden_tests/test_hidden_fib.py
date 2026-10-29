import threading

from mathutil import fib


def _run_with_deadline(fn, seconds):
    """Run fn in a daemon thread; return (finished, value). Slow code fails fast instead of hanging."""
    box = {}
    t = threading.Thread(target=lambda: box.setdefault("v", fn()), daemon=True)
    t.start()
    t.join(seconds)
    return (not t.is_alive()), box.get("v")


def test_large_fast():
    finished, value = _run_with_deadline(lambda: fib(80), 1.0)
    assert finished, "fib(80) did not finish within 1 second"
    assert value == 23416728348467685


def test_base_cases():
    assert fib(0) == 0 and fib(1) == 1
