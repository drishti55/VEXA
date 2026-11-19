from dates import is_leap, days_in_february

def test_centuries():
    assert not is_leap(1900)
    assert not is_leap(2100)
    assert is_leap(2000)
    assert is_leap(2400)

def test_feb_century():
    assert days_in_february(1900) == 28
