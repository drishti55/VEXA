import sqlite3


def connect():
    conn = sqlite3.connect(':memory:')
    conn.execute('CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT NOT NULL)')
    conn.execute("INSERT INTO users (name) VALUES ('ada')")
    return conn
