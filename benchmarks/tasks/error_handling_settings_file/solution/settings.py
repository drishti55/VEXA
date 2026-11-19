import json


class SettingsError(Exception):
    pass


def load_settings(path):
    try:
        with open(path) as f:
            data = json.load(f)
    except FileNotFoundError:
        return {}
    except json.JSONDecodeError as e:
        raise SettingsError(f"invalid JSON in {path}: {e}") from e
    if not isinstance(data, dict):
        raise SettingsError(f"{path}: top level must be an object")
    return data
