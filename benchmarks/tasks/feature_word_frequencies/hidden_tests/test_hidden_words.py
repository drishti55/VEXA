from textstats import word_frequencies

def test_counts():
    assert word_frequencies('The cat. the CAT!') == {'the': 2, 'cat': 2}

def test_empty():
    assert word_frequencies('') == {}

def test_apostrophe():
    assert word_frequencies("Don't stop, don't.") == {"don't": 2, 'stop': 1}
