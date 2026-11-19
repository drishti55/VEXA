import time


class RateLimiter:
    def __init__(self, limit, window_seconds, clock=time.monotonic):
        self.limit = limit
        self.window = window_seconds
        self.clock = clock

    def allow(self, client_id):
        return True
