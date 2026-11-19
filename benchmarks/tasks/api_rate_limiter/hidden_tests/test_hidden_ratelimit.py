from ratelimit import RateLimiter

class Clock:
    def __init__(self):
        self.t = 0.0
    def __call__(self):
        return self.t

def test_limit_and_window():
    c = Clock()
    rl = RateLimiter(3, 10, clock=c)
    assert [rl.allow('a') for _ in range(4)] == [True, True, True, False]
    c.t = 10.5
    assert rl.allow('a')

def test_clients_independent():
    c = Clock()
    rl = RateLimiter(1, 10, clock=c)
    assert rl.allow('a') and rl.allow('b') and not rl.allow('a')

def test_denied_not_counted():
    c = Clock()
    rl = RateLimiter(1, 10, clock=c)
    rl.allow('a')
    c.t = 5
    assert not rl.allow('a')
    c.t = 10.1
    assert rl.allow('a')
