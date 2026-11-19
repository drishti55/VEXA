from router import Router

def test_static():
    r = Router()
    r.add('GET', '/ping', lambda: 'pong')
    assert r.dispatch('GET', '/ping') == (200, 'pong')
    assert r.dispatch('GET', '/nope')[0] == 404
