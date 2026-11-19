import re
from collections import Counter


def char_count(text):
    return len(text)


def word_frequencies(text):
    return dict(Counter(re.findall(r"[a-z0-9']+", text.lower())))
