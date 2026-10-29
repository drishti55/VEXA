ITEMS = {"1": {"name": "apple"}}

def handle(method, path):
    if path == "/health":
        if method != "GET":
            return 405, {"error": "method not allowed"}
        return 200, {"status": "ok"}
    if path.startswith("/items/") and method == "GET":
        item = ITEMS.get(path.removeprefix("/items/"))
        return (200, item) if item else (404, {"error": "not found"})
    return 404, {"error": "not found"}
