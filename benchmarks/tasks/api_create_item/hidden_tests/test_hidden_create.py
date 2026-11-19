from api import handle

def test_create_and_read():
    status, body = handle('POST', '/items', {'name': 'pear'})
    assert status == 201 and body['name'] == 'pear'
    assert body['id'] > 1
    assert handle('GET', f"/items/{body['id']}") == (200, body)

def test_validation():
    assert handle('POST', '/items', {}) == (400, {'error': 'name required'})
    assert handle('POST', '/items', {'name': '  '}) == (400, {'error': 'name required'})
