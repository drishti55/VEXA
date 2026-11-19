def fetch_with_retry(fn, attempts=3):
    last = None
    for _ in range(attempts):
        try:
            return fn()
        except ConnectionError as e:
            last = e
    raise last
