from pairs import count_pairs

def test_small():
    assert count_pairs([1, 2, 3, 4], 5) == 2
    assert count_pairs([1, 1, 1], 2) == 3
    assert count_pairs([], 1) == 0
