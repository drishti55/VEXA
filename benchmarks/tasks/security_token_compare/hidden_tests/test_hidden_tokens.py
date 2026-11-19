import inspect
import tokens

def test_empty():
    assert not tokens.check_token('', '')
    assert not tokens.check_token(None, 'abc')
    assert not tokens.check_token('abc', None)
    assert not tokens.check_token(None, None)

def test_constant_time():
    assert 'compare_digest' in inspect.getsource(tokens.check_token)
