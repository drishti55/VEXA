def load_settings(env):
    raw_port = env.get("PORT", "8080")
    try:
        port = int(raw_port)
    except ValueError:
        raise ValueError(f"invalid PORT: {raw_port!r}") from None
    debug = str(env.get("DEBUG", "")).strip().lower() in ("1", "true", "yes")
    return {"port": port, "debug": debug}
