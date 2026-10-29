def parse_port(value):
    try:
        port = int(str(value).strip())
    except (TypeError, ValueError):
        raise ValueError(f"invalid port: {value!r}") from None
    if not 1 <= port <= 65535:
        raise ValueError(f"port out of range: {port}")
    return port
