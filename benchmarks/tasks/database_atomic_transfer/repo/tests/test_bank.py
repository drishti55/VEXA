from bank import connect, balance, transfer

def test_transfer():
    conn = connect()
    transfer(conn, 'alice', 'bob', 30)
    assert balance(conn, 'alice') == 70 and balance(conn, 'bob') == 80
