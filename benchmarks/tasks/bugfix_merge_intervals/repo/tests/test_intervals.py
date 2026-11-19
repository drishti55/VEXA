from intervals import merge

def test_sorted_overlap():
    assert merge([[1, 3], [2, 6], [8, 10]]) == [[1, 6], [8, 10]]
