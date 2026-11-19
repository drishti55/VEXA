from intervals import merge

def test_unsorted():
    assert merge([[8, 10], [1, 3], [2, 6]]) == [[1, 6], [8, 10]]

def test_touching():
    assert merge([[1, 4], [4, 5]]) == [[1, 5]]

def test_no_mutation():
    data = [[5, 6], [1, 2]]
    merge(data)
    assert data == [[5, 6], [1, 2]]

def test_empty():
    assert merge([]) == []
