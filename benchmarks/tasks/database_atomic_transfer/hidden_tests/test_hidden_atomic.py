import pytest
from bank import connect, balance, transfer

def test_insufficient():
    conn = connect()
    with pytest.raises(ValueError):
        transfer(conn, 'bob', 'alice', 500)
    assert balance(conn, 'bob') == 50 and balance(conn, 'alice') == 100

def test_unknown_account():
    conn = connect()
    with pytest.raises(ValueError):
        transfer(conn, 'alice', 'carol', 10)
    assert balance(conn, 'alice') == 100

def test_non_positive():
    conn = connect()
    with pytest.raises(ValueError):
        transfer(conn, 'alice', 'bob', 0)
    with pytest.raises(ValueError):
        transfer(conn, 'alice', 'bob', -5)
    assert balance(conn, 'alice') == 100
