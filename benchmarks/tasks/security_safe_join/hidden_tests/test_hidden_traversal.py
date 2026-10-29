import os
import pytest
from files import safe_join

def test_inside(tmp_path):
    out = safe_join(str(tmp_path), "a/b.txt")
    assert os.path.realpath(out).startswith(os.path.realpath(str(tmp_path)))

@pytest.mark.parametrize("p", ["../secret", "a/../../secret", "/etc/passwd"])
def test_escape(tmp_path, p):
    with pytest.raises(PermissionError):
        safe_join(str(tmp_path), p)

def test_prefix_trick(tmp_path):
    base = tmp_path / "data"
    base.mkdir()
    with pytest.raises(PermissionError):
        safe_join(str(base), "../data2/x")
