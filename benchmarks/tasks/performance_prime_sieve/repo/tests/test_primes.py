from primes import primes_below

def test_small():
    assert primes_below(20) == [2, 3, 5, 7, 11, 13, 17, 19]
    assert primes_below(2) == []
