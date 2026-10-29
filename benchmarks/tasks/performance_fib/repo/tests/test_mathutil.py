from mathutil import fib

def test_small():
    assert [fib(i) for i in range(8)] == [0, 1, 1, 2, 3, 5, 8, 13]
