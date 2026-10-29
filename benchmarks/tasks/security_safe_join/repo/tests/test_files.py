import os
from files import safe_join

def test_simple(tmp_path):
    assert safe_join(str(tmp_path), "a.txt").endswith("a.txt")
