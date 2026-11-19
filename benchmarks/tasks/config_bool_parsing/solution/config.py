TRUE = {'1', 'true', 'yes', 'on'}
FALSE = {'0', 'false', 'no', 'off'}


def get_bool(env, key, default=False):
    if key not in env:
        return default
    v = str(env[key]).strip().lower()
    if v in TRUE:
        return True
    if v in FALSE:
        return False
    raise ValueError(f"{key}: not a boolean: {env[key]!r}")
