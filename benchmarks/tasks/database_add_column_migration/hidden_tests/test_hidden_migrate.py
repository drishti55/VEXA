from db import connect, migrate

def _cols(conn):
    return [r[1] for r in conn.execute('PRAGMA table_info(users)')]

def test_adds_column():
    conn = connect()
    migrate(conn)
    assert 'email' in _cols(conn)

def test_idempotent_and_keeps_rows():
    conn = connect()
    migrate(conn)
    migrate(conn)
    assert _cols(conn).count('email') == 1
    assert conn.execute('SELECT name, email FROM users').fetchall() == [('ada', None)]
