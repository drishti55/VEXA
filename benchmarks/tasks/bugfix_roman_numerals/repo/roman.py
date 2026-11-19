VALUES = [(1000, 'M'), (500, 'D'), (100, 'C'), (50, 'L'), (10, 'X'), (5, 'V'), (1, 'I')]


def to_roman(n):
    out = ''
    for value, sym in VALUES:
        while n >= value:
            out += sym
            n -= value
    return out
