ITEMS = {"1": {"name": "apple"}}

def handle(method, path):
    if path.startswith("/items/") and method == "GET":
        item = ITEMS.get(path.removeprefix("/items/"))
        return (200, item) if item else (404, {"error": "not found"})
    return 404, {"error": "not found"}
