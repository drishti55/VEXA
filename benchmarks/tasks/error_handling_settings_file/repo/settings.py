import json


def load_settings(path):
    with open(path) as f:
        return json.load(f)
