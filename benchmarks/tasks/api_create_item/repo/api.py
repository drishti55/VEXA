ITEMS = {1: {'id': 1, 'name': 'apple'}}


def handle(method, path):
    if method == 'GET' and path.startswith('/items/'):
        key = path.removeprefix('/items/')
        item = ITEMS.get(int(key)) if key.isdigit() else None
        return (200, item) if item else (404, {'error': 'not found'})
    return 404, {'error': 'not found'}
