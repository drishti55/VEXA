import sqlite3

class UserRepo:
    def __init__(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT, email TEXT)")

    def add(self, name, email):
        cur = self.conn.execute("INSERT INTO users (name, email) VALUES (?, ?)", (name, email))
        return cur.lastrowid

    def get(self, user_id):
        row = self.conn.execute("SELECT id, name, email FROM users WHERE id = ?", (user_id,)).fetchone()
        return dict(zip(("id", "name", "email"), row)) if row else None

    def find_by_email(self, email):
        row = self.conn.execute(
            "SELECT id, name, email FROM users WHERE lower(email) = lower(?)", (email,)
        ).fetchone()
        return dict(zip(("id", "name", "email"), row)) if row else None
