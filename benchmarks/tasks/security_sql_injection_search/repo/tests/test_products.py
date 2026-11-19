from products import make_db, search

def test_search():
    assert search(make_db(), 'ap') == ['apple', 'apricot']
