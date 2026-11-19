from router import Router

def test_param():
    r = Router()
    r.add('GET', '/users/{id}', lambda id: {'user': id})
    assert r.dispatch('GET', '/users/42') == (200, {'user': '42'})
    assert r.dispatch('GET', '/users/42/extra')[0] == 404
    assert r.dispatch('GET', '/users/')[0] == 404

def test_multiple():
    r = Router()
    r.add('GET', '/a/{x}/b/{y}', lambda x, y: x + y)
    assert r.dispatch('GET', '/a/1/b/2') == (200, '12')

def test_method_and_static():
    r = Router()
    r.add('GET', '/ping', lambda: 'pong')
    r.add('GET', '/users/{id}', lambda id: id)
    assert r.dispatch('POST', '/users/1')[0] == 404
    assert r.dispatch('GET', '/ping') == (200, 'pong')
