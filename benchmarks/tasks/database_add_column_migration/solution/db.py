import sqlite3


def connect():
    conn = sqlite3.connect(':memory:')
    conn.execute('CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT NOT NULL)')
    conn.execute("INSERT INTO users (name) VALUES ('ada')")
    return conn


def migrate(conn):
    cols = {r[1] for r in conn.execute('PRAGMA table_info(users)')}
    if 'email' not in cols:
        conn.execute('ALTER TABLE users ADD COLUMN email TEXT')
        conn.commit()
