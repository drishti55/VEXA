from datetime import date
from workdays import days_between

def test_days():
    assert days_between(date(2024, 1, 1), date(2024, 1, 31)) == 30
