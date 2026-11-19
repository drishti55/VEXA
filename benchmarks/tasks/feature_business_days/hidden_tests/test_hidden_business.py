from datetime import date
from workdays import business_days

def test_week():
    assert business_days(date(2024, 1, 1), date(2024, 1, 5)) == 5

def test_two_weeks():
    assert business_days(date(2024, 1, 1), date(2024, 1, 14)) == 10

def test_weekend_only():
    assert business_days(date(2024, 1, 6), date(2024, 1, 7)) == 0

def test_holidays():
    assert business_days(date(2024, 1, 1), date(2024, 1, 5), holidays=[date(2024, 1, 1)]) == 4

def test_reversed():
    assert business_days(date(2024, 1, 5), date(2024, 1, 1)) == 0
