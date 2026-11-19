import sqlite3


def make_db():
    conn = sqlite3.connect(':memory:')
    conn.execute('CREATE TABLE products (id INTEGER PRIMARY KEY, name TEXT)')
    conn.executemany('INSERT INTO products (name) VALUES (?)', [('apple',), ('apricot',), ('banana',), ("Bob's widget",)])
    return conn


def search(conn, term):
    rows = conn.execute(f"SELECT name FROM products WHERE name LIKE '%{term}%' ORDER BY name")
    return [r[0] for r in rows]
