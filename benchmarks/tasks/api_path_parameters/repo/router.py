class Router:
    def __init__(self):
        self._routes = {}

    def add(self, method, pattern, handler):
        self._routes[(method, pattern)] = handler

    def dispatch(self, method, path):
        handler = self._routes.get((method, path))
        if handler is None:
            return 404, {'error': 'not found'}
        return 200, handler()
