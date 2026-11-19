import sqlite3


def connect():
    conn = sqlite3.connect(':memory:')
    conn.execute('CREATE TABLE accounts (id TEXT PRIMARY KEY, balance INTEGER NOT NULL)')
    conn.executemany('INSERT INTO accounts VALUES (?, ?)', [('alice', 100), ('bob', 50)])
    conn.commit()
    return conn


def balance(conn, account):
    row = conn.execute('SELECT balance FROM accounts WHERE id = ?', (account,)).fetchone()
    return row[0] if row else None


def transfer(conn, src, dst, amount):
    conn.execute('UPDATE accounts SET balance = balance - ? WHERE id = ?', (amount, src))
    conn.execute('UPDATE accounts SET balance = balance + ? WHERE id = ?', (amount, dst))
    conn.commit()
