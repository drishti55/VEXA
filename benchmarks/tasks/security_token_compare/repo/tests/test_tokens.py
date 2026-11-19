from tokens import check_token

def test_match():
    assert check_token('abc', 'abc')
    assert not check_token('abc', 'abd')
