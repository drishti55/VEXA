from pagination import paginate

def test_first_page():
    assert paginate([1, 2, 3, 4], 1, 2) == [1, 2]
