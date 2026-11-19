from listutil import has_duplicates

def test_small():
    assert has_duplicates([1, 2, 1])
    assert not has_duplicates([1, 2, 3])
    assert not has_duplicates([])
