import math


def area(shape):
    kind = shape['kind']
    if kind == 'circle':
        return math.pi * shape['r'] ** 2
    elif kind == 'square':
        return shape['side'] ** 2
    elif kind == 'rectangle':
        return shape['w'] * shape['h']
    else:
        raise ValueError(f"unknown shape {kind}")
