import time
from collections import defaultdict, deque


class RateLimiter:
    def __init__(self, limit, window_seconds, clock=time.monotonic):
        self.limit = limit
        self.window = window_seconds
        self.clock = clock
        self._hits = defaultdict(deque)

    def allow(self, client_id):
        now = self.clock()
        hits = self._hits[client_id]
        while hits and hits[0] <= now - self.window:
            hits.popleft()
        if len(hits) >= self.limit:
            return False
        hits.append(now)
        return True
