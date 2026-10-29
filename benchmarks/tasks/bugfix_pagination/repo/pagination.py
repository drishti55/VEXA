def paginate(items, page, size):
    """Return the given 1-based page of items."""
    start = (page - 1) * size - (1 if page > 1 else 0)
    return items[start:start + size]
