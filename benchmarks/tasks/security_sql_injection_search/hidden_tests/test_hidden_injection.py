from products import make_db, search

def test_injection():
    assert search(make_db(), "%' OR 1=1 --") == []

def test_apostrophe():
    assert search(make_db(), "Bob's") == ["Bob's widget"]

def test_case():
    assert search(make_db(), 'BAN') == ['banana']
