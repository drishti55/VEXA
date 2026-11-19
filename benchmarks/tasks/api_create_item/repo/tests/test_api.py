from api import handle

def test_get():
    assert handle('GET', '/items/1') == (200, {'id': 1, 'name': 'apple'})
    assert handle('GET', '/items/99')[0] == 404
