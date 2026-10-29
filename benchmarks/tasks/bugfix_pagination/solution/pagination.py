def paginate(items, page, size):
    """Return the given 1-based page of items."""
    start = (page - 1) * size
    return items[start:start + size]
