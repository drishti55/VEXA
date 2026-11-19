import threading


def _run_with_deadline(fn, seconds):
    """Run fn in a daemon thread; return (finished, value). Slow code fails fast instead of hanging."""
    box = {}
    t = threading.Thread(target=lambda: box.setdefault("v", fn()), daemon=True)
    t.start()
    t.join(seconds)
    return (not t.is_alive()), box.get("v")

from pairs import count_pairs


def test_large_fast():
    nums = list(range(100_000))
    finished, value = _run_with_deadline(lambda: count_pairs(nums, 99_999), 1.0)
    assert finished, 'did not finish within 1 second'
    assert value == 50_000


def test_duplicates():
    assert count_pairs([2, 2, 2, 2], 4) == 6
    assert count_pairs([3, 3, 0, 6], 6) == 2
