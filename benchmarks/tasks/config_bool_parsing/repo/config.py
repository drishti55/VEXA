def get_bool(env, key, default=False):
    if key not in env:
        return default
    return bool(env.get(key))
