import copy


def _merge(base, over):
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            _merge(base[k], v)
        else:
            base[k] = copy.deepcopy(v)


def merge_config(*layers):
    out = {}
    for layer in layers:
        _merge(out, layer)
    return out
