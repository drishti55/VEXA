import copy
from config import merge_config

def test_nested():
    defaults = {'db': {'host': 'localhost', 'port': 5432}, 'debug': False}
    env = {'db': {'port': 6543}, 'debug': True}
    assert merge_config(defaults, env) == {'db': {'host': 'localhost', 'port': 6543}, 'debug': True}

def test_three_layers():
    assert merge_config({'a': {'b': {'c': 1, 'd': 2}}}, {'a': {'b': {'c': 9}}}, {'a': {'e': 3}}) == {'a': {'b': {'c': 9, 'd': 2}, 'e': 3}}

def test_no_mutation():
    a = {'x': {'y': 1}}
    b = {'x': {'z': 2}}
    snap = copy.deepcopy((a, b))
    out = merge_config(a, b)
    out['x']['y'] = 99
    assert (a, b) == snap
