class UserStore:
    def __init__(self):
        self._users = {}

    def add(self, username, password):
        self._users[username] = password

    def stored(self, username):
        return self._users[username]

    def verify(self, username, password):
        return self._users.get(username) == password
