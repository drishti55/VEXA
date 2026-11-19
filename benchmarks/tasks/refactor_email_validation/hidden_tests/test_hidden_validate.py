import inspect
import pytest
import accounts

def test_validate():
    assert accounts.validate_email('a@b.co')
    for bad in ['a@b', '@b.co', 'a@@b.co', 'ab.co']:
        assert not accounts.validate_email(bad)

def test_callers_reuse_it():
    for fn in (accounts.register, accounts.update_email):
        assert 'validate_email' in inspect.getsource(fn)

def test_behaviour():
    with pytest.raises(ValueError):
        accounts.update_email({}, 'x@y')
