import sqlite3


def connect():
    conn = sqlite3.connect(':memory:')
    conn.executescript('''
        CREATE TABLE customers (id INTEGER PRIMARY KEY, name TEXT);
        CREATE TABLE orders (id INTEGER PRIMARY KEY, customer_id INTEGER, total REAL);
        INSERT INTO customers VALUES (1, 'ada'), (2, 'bob'), (3, 'cy'), (4, 'dee');
        INSERT INTO orders (customer_id, total) VALUES (1, 10), (1, 15), (2, 25), (3, 5), (3, 40);
    ''')
    return conn


def order_count(conn):
    return conn.execute('SELECT COUNT(*) FROM orders').fetchone()[0]


def top_customers(conn, n):
    rows = conn.execute('''
        SELECT c.name, SUM(o.total) AS spent FROM customers c
        JOIN orders o ON o.customer_id = c.id
        GROUP BY c.id ORDER BY spent DESC, c.name ASC LIMIT ?
    ''', (n,))
    return [(name, float(spent)) for name, spent in rows]
