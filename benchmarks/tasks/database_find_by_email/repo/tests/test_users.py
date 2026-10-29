from users import UserRepo

def test_add_get():
    repo = UserRepo()
    uid = repo.add("Ada", "ada@example.com")
    assert repo.get(uid)["name"] == "Ada"
