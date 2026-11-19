from dates import is_leap, days_in_february

def test_basic():
    assert is_leap(2024) and not is_leap(2023)

def test_feb():
    assert days_in_february(2024) == 29
