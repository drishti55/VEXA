from datetime import date, timedelta


def days_between(start: date, end: date) -> int:
    return (end - start).days


def business_days(start: date, end: date, holidays=()) -> int:
    skip = set(holidays)
    count = 0
    d = start
    while d <= end:
        if d.weekday() < 5 and d not in skip:
            count += 1
        d += timedelta(days=1)
    return count
