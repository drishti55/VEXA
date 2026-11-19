def is_leap(year):
    return year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)


def days_in_february(year):
    return 29 if is_leap(year) else 28
