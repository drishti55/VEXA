import math

AREA_FUNCS = {
    'circle': lambda s: math.pi * s['r'] ** 2,
    'square': lambda s: s['side'] ** 2,
    'rectangle': lambda s: s['w'] * s['h'],
}


def area(shape):
    fn = AREA_FUNCS.get(shape['kind'])
    if fn is None:
        raise ValueError(f"unknown shape {shape['kind']}")
    return fn(shape)
