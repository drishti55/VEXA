import hashlib
import hmac
import os

ITERATIONS = 100_000


class UserStore:
    def __init__(self):
        self._users = {}

    def add(self, username, password):
        salt = os.urandom(16)
        digest = hashlib.pbkdf2_hmac('sha256', password.encode(), salt, ITERATIONS)
        self._users[username] = salt + digest

    def stored(self, username):
        return self._users[username]

    def verify(self, username, password):
        rec = self._users.get(username)
        if rec is None:
            return False
        salt, digest = rec[:16], rec[16:]
        return hmac.compare_digest(digest, hashlib.pbkdf2_hmac('sha256', password.encode(), salt, ITERATIONS))
