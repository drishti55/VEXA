ITEMS = {1: {'id': 1, 'name': 'apple'}}


def handle(method, path, body=None):
    if method == 'POST' and path == '/items':
        name = (body or {}).get('name', '')
        if not isinstance(name, str) or not name.strip():
            return 400, {'error': 'name required'}
        new_id = max(ITEMS, default=0) + 1
        ITEMS[new_id] = {'id': new_id, 'name': name}
        return 201, ITEMS[new_id]
    if method == 'GET' and path.startswith('/items/'):
        key = path.removeprefix('/items/')
        item = ITEMS.get(int(key)) if key.isdigit() else None
        return (200, item) if item else (404, {'error': 'not found'})
    return 404, {'error': 'not found'}
