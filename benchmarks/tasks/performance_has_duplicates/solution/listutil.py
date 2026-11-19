def has_duplicates(items):
    seen = set()
    for x in items:
        if x in seen:
            return True
        seen.add(x)
    return False
