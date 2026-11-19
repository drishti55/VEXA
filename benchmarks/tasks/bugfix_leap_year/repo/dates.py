def is_leap(year):
    return year % 4 == 0


def days_in_february(year):
    return 29 if is_leap(year) else 28
