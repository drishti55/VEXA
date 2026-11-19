from cache import Cache

def test_put_get():
    c = Cache(2)
    c.put('a', 1)
    assert c.get('a') == 1
    assert c.get('zz', 'd') == 'd'
