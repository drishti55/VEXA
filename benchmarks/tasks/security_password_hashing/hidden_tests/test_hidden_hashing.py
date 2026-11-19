from auth import UserStore

def _as_bytes(v):
    return v if isinstance(v, bytes) else repr(v).encode()

def test_not_plaintext():
    s = UserStore()
    s.add('ada', 'correct horse')
    assert b'correct horse' not in _as_bytes(s.stored('ada'))

def test_salted():
    s = UserStore()
    s.add('a', 'same')
    s.add('b', 'same')
    assert s.stored('a') != s.stored('b')

def test_verify():
    s = UserStore()
    s.add('ada', 'pw1')
    assert s.verify('ada', 'pw1') and not s.verify('ada', 'pw2') and not s.verify('x', 'pw1')
