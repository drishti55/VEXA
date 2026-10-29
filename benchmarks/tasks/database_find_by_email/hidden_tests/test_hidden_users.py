import inspect
from users import UserRepo

def test_find_case_insensitive():
    repo = UserRepo()
    uid = repo.add("Ada", "ada@example.com")
    assert repo.find_by_email("ADA@Example.com") == {"id": uid, "name": "Ada", "email": "ada@example.com"}

def test_missing():
    assert UserRepo().find_by_email("nobody@example.com") is None

def test_injection_safe():
    repo = UserRepo()
    repo.add("Ada", "ada@example.com")
    assert repo.find_by_email("x' OR '1'='1") is None
    assert "?" in inspect.getsource(UserRepo.find_by_email)
