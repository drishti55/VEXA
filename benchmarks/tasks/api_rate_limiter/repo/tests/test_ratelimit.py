from ratelimit import RateLimiter

def test_first_allowed():
    assert RateLimiter(3, 60).allow('a')
