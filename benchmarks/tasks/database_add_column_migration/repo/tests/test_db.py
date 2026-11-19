from db import connect

def test_seed():
    assert connect().execute('SELECT name FROM users').fetchall() == [('ada',)]
