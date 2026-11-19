def merge_config(*layers):
    out = {}
    for layer in layers:
        out = {**out, **layer}
    return out
