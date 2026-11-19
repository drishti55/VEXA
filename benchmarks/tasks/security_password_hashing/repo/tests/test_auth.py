from auth import UserStore

def test_verify():
    s = UserStore()
    s.add('ada', 'pw1')
    assert s.verify('ada', 'pw1')
    assert not s.verify('ada', 'nope')
    assert not s.verify('bob', 'pw1')
