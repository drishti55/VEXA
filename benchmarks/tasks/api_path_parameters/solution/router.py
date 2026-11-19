class Router:
    def __init__(self):
        self._routes = []

    def add(self, method, pattern, handler):
        self._routes.append((method, pattern.strip('/').split('/'), handler))

    def dispatch(self, method, path):
        parts = path.strip('/').split('/')
        for m, segs, handler in self._routes:
            if m != method or len(segs) != len(parts):
                continue
            params = {}
            for seg, part in zip(segs, parts):
                if seg.startswith('{') and seg.endswith('}'):
                    if not part:
                        break
                    params[seg[1:-1]] = part
                elif seg != part:
                    break
            else:
                return 200, handler(**params)
        return 404, {'error': 'not found'}
